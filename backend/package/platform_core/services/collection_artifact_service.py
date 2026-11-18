"""公众号与视频号成果发布到沙盒共享的个人 Workspace。"""

import asyncio
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import time
import uuid
import zipfile

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.knowledge.video_transcriber.utils.docx_exporter import video_docx_bytes
from platform_core.knowledge.video_transcriber.utils.transcript_layout import LAYOUT_VERSION, video_markdown
from platform_core.services import wechat_mp_service
from platform_core.services.task_service import Task, tasker
from platform_core.storage.minio.client import MinIOClient, aupload_file_to_minio
from platform_core.storage.postgres.models_knowledge_governance import (
    CollectionArtifactIngestion,
    CollectionArtifactRecord,
)
from platform_core.utils.datetime_utils import format_utc_datetime
from platform_core.utils import logger
from platform_core.utils.paths import open_regular_file_fd
from platform_core.workspace.filesystem import Workspace
from platform_core.workspace.paths import ensure_user_workspace

SOURCES = {"wechat-articles": "公众号文章", "wxchannels": "视频号文字稿"}
MAX_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_BYTES = 500 * 1024 * 1024


class ArtifactArchiveError(ValueError):
    """批量 ZIP 无法继续时返回可供前端定位的结构化细节。"""

    def __init__(self, code: str, message: str, *, failures: list[dict], total_bytes: int = 0):
        super().__init__(message)
        self.detail = {
            "code": code,
            "message": message,
            "failures": failures,
            "total_bytes": total_bytes,
            "limit_bytes": MAX_ARCHIVE_BYTES,
        }


def artifact_root(source: str) -> str:
    """使用固定来源目录，与个人空间和沙盒挂载共享同一份文件。"""
    return f"/采集成果/{SOURCES[source]}"


def manifest_directory(uid: str) -> Path:
    """服务端来源清单不放入可编辑的用户工作区。"""
    root = Path(os.getenv("COLLECTION_ARTIFACT_DATA_ROOT", "outputs/collection-artifacts"))
    return root.resolve() / wechat_mp_service.owner_key(uid)


def artifact_id(identity: str) -> str:
    """来源标识使用稳定摘要，重试不创建重复成果。"""
    return hashlib.sha256(identity.encode()).hexdigest()[:32]


@contextmanager
def manifest(uid: str, source: str):
    """跨 API/任务 Worker 串行更新成果清单，完成文件写入后原子提交。"""
    directory = manifest_directory(uid)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / f"{source}.json"
    with (directory / f"{source}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(path.read_text()) if path.exists() else {"items": {}, "errors": []}
        yield state
        with tempfile.NamedTemporaryFile(mode="w", dir=directory, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(state, stream, ensure_ascii=False)
        try:
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def read_manifest(uid: str, source: str) -> dict:
    """读取已经提交的来源清单，不创建目录或修改成果。"""
    path = manifest_directory(uid) / f"{source}.json"
    return json.loads(path.read_text()) if path.exists() else {"items": {}, "errors": []}


def write_artifact_file(workspace: Workspace, path: str, content: bytes):
    """通过既有 no-follow 边界创建目录并原子写入成果。"""
    if len(content) > MAX_BYTES:
        raise ValueError("单个成果文件超过 100 MB")
    parent = "/"
    for part in PurePosixPath(path).parts[1:-1]:
        try:
            workspace.create_authorized_directory(parent, part, root="/")
        except FileExistsError:
            pass
        parent = parent.rstrip("/") + "/" + part
    workspace.replace_authorized_file(path, content)


def target_folder(source: str, title: str, identity: str) -> str:
    """标题只用于展示目录名，身份摘要避免重名覆盖。"""
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", title).strip(" .")[:60] or SOURCES[source]
    return f"{artifact_root(source)}/{name}_{identity[:10]}"


def list_artifacts(uid: str, source: str) -> dict:
    """结果只返回仍存在的工作区文档，删除文件不会伪装成可入库成果。"""
    state = read_manifest(uid, source)
    workspace = Workspace(uid)
    items = []
    for record in state["items"].values():
        item = {key: value for key, value in record.items() if key not in {"signatures", "generated_hashes"}}
        for flag, key in (("available", "primary_path"), ("import_available", "import_path")):
            try:
                item[flag] = not workspace.stat_authorized_path(item[key], root=artifact_root(source))["is_dir"]
            except (OSError, ValueError):
                item[flag] = False
        items.append(item)
    return {
        "items": sorted(items, key=lambda item: item["updated_at"], reverse=True),
        "errors": state["errors"],
        "workspace_root": artifact_root(source),
    }


async def sync_artifact_records(
    db: AsyncSession,
    *,
    uid: str,
    source: str,
    projection: dict | None = None,
) -> dict:
    """把文件清单投影为持久成果及逐知识库入库状态。"""
    result = projection or list_artifacts(uid, source)
    workspace = Workspace(uid)
    records_by_key = {
        row.artifact_key: row
        for row in (
            await db.scalars(
                select(CollectionArtifactRecord).where(
                    CollectionArtifactRecord.owner_uid == uid,
                    CollectionArtifactRecord.source == source,
                )
            )
        ).all()
    }
    active_keys = {item["id"] for item in result["items"]}
    for artifact_key, record in list(records_by_key.items()):
        if artifact_key in active_keys:
            continue
        await db.delete(record)
        records_by_key.pop(artifact_key)
    for item in result["items"]:
        record = records_by_key.get(item["id"])
        content_hash = None
        if item.get("import_available"):
            try:
                content = workspace.read_authorized_file(item["import_path"], MAX_BYTES)
                content_hash = hashlib.sha256(content).hexdigest()
            except (OSError, ValueError):
                pass
        if record is None:
            record = CollectionArtifactRecord(
                id=artifact_id(f"{uid}:{source}:{item['id']}"),
                owner_uid=uid,
                source=source,
                artifact_key=item["id"],
                title=item.get("title") or SOURCES[source],
                account=item.get("account") or "",
                canonical_url=item.get("canonical_url") or "",
                content_hash=content_hash,
                primary_path=item["primary_path"],
                import_path=item["import_path"],
                files=list(item.get("files") or []),
                status="downloaded" if item.get("import_available") else "failed",
                failure_stage=None if item.get("import_available") else "download",
                error="" if item.get("import_available") else "成果主文件缺失",
            )
            db.add(record)
            records_by_key[item["id"]] = record
        else:
            changed = bool(content_hash and record.content_hash and content_hash != record.content_hash)
            record.title = item.get("title") or record.title
            record.account = item.get("account") or ""
            record.canonical_url = item.get("canonical_url") or record.canonical_url
            record.primary_path = item["primary_path"]
            record.import_path = item["import_path"]
            record.files = list(item.get("files") or [])
            if changed:
                record.status = "downloaded"
                record.failure_stage = None
                record.error = ""
            if content_hash:
                record.content_hash = content_hash
    await db.commit()
    return await list_artifacts_with_status(db, uid=uid, source=source, projection=result)


async def list_artifacts_with_status(
    db: AsyncSession,
    *,
    uid: str,
    source: str,
    projection: dict | None = None,
) -> dict:
    """合并当前磁盘可用性、持久成果状态及多知识库入库关系。"""
    result = projection or list_artifacts(uid, source)
    records = list(
        (
            await db.scalars(
                select(CollectionArtifactRecord).where(
                    CollectionArtifactRecord.owner_uid == uid,
                    CollectionArtifactRecord.source == source,
                )
            )
        ).all()
    )
    record_by_key = {row.artifact_key: row for row in records}
    ingestions_by_artifact: dict[str, list[CollectionArtifactIngestion]] = {}
    if records:
        ingestions = list(
            (
                await db.scalars(
                    select(CollectionArtifactIngestion)
                    .where(CollectionArtifactIngestion.artifact_id.in_([row.id for row in records]))
                    .order_by(CollectionArtifactIngestion.created_at.desc())
                )
            ).all()
        )
        for ingestion in ingestions:
            ingestions_by_artifact.setdefault(ingestion.artifact_id, []).append(ingestion)
    for item in result["items"]:
        record = record_by_key.get(item["id"])
        if record is None:
            item.update({"download_state": "downloaded", "failure_stage": None, "ingestions": []})
            continue
        ingestions = ingestions_by_artifact.get(record.id, [])
        download_state, failure_stage, error = _artifact_download_state(record, ingestions)
        item.update(
            {
                "record_id": record.id,
                "download_state": download_state,
                "failure_stage": failure_stage,
                "error": error,
                "content_hash": record.content_hash,
                "ingestions": [_ingestion_dict(row) for row in ingestions],
            }
        )
    return result


async def merge_article_listing_states(
    db: AsyncSession,
    *,
    uid: str,
    payload: dict,
    global_scope: bool = False,
) -> dict:
    """按用户或管理员全局视野合并公众号文章处理状态。"""
    articles = payload.get("articles")
    if not isinstance(articles, list) or not articles:
        return payload
    query = select(CollectionArtifactRecord).where(
        CollectionArtifactRecord.source == "wechat-articles",
    )
    if not global_scope:
        query = query.where(CollectionArtifactRecord.owner_uid == uid)
    records = list((await db.scalars(query.order_by(CollectionArtifactRecord.updated_at.desc()))).all())
    if not records:
        return payload
    ingestions = list(
        (
            await db.scalars(
                select(CollectionArtifactIngestion)
                .where(CollectionArtifactIngestion.artifact_id.in_([row.id for row in records]))
                .order_by(CollectionArtifactIngestion.created_at.desc())
            )
        ).all()
    )
    by_artifact: dict[str, list[CollectionArtifactIngestion]] = {}
    for ingestion in ingestions:
        by_artifact.setdefault(ingestion.artifact_id, []).append(ingestion)
    by_url: dict[str, list[CollectionArtifactRecord]] = {}
    by_title: dict[str, list[CollectionArtifactRecord]] = {}
    for record in records:
        canonical_url = _canonical_article_url(record.canonical_url)
        if canonical_url:
            by_url.setdefault(canonical_url, []).append(record)
        if record.title:
            by_title.setdefault(record.title, []).append(record)
    for article in articles:
        if not isinstance(article, dict):
            continue
        candidates = by_url.get(_canonical_article_url(article.get("link") or article.get("url")))
        if not candidates:
            candidates = by_title.get(str(article.get("title") or ""))
        if not candidates:
            continue

        evaluated = []
        for record in candidates:
            record_ingestions = by_artifact.get(record.id, [])
            state = _artifact_download_state(record, record_ingestions)
            evaluated.append(
                (
                    _DOWNLOAD_STATE_PRIORITY[state[0]],
                    record,
                    record_ingestions,
                    state,
                )
            )
        # records 已按 updated_at 倒序；max 在优先级相同时稳定保留最先出现的最新记录。
        _priority, record, record_ingestions, state = max(
            evaluated,
            key=lambda item: item[0],
        )
        download_state, failure_stage, error = state
        article["download_state"] = download_state
        article["failure_stage"] = failure_stage
        article["download_error"] = error
        article["download_scope"] = "global" if global_scope else "user"
        article["download_owner_count"] = len({row.owner_uid for row in candidates})

        # 管理员只需要全局处理状态；其他用户的知识库、任务和文件标识不跨用户暴露。
        if global_scope and record.owner_uid != uid:
            article["ingestions"] = []
            continue

        article["ingestions"] = [_ingestion_dict(row) for row in record_ingestions]
        if article["ingestions"]:
            current = [row for row in article["ingestions"] if row["content_hash"] == record.content_hash]
        else:
            current = []
        if current:
            latest = current[0]
            article.update(
                {
                    "target_kb_id": latest["kb_id"],
                    "ingest_task_id": latest["task_id"],
                    "knowledge_file_id": latest["knowledge_file_id"],
                }
            )
    return payload


def publish_video(
    uid: str, oid: str, title: str, text: str, document: bytes, account: str, *, previous_document: bytes | None = None
) -> dict:
    """Word 和可检索文字稿均持久保存；只有完整发布后才登记成果。"""
    identity = artifact_id(oid)
    source = "wxchannels"
    ensure_user_workspace(uid)
    workspace = Workspace(uid)
    with manifest(uid, source) as state:
        previous = state["items"].get(identity, {})
        folder = previous.get("folder") or target_folder(source, title, identity)
        filename = PurePosixPath(folder).name.rsplit("_", 1)[0]
        docx_path, md_path = f"{folder}/{filename}.docx", f"{folder}/{filename}.md"
        markdown = video_markdown(title, text, account, oid).encode()
        legacy_markdown = f"# {title}\n\n视频号：{account}\n\n视频 OID：{oid}\n\n## 文字稿\n\n{text}\n".encode()
        hashes = dict(previous.get("generated_hashes", {}))
        for path, content, legacy in ((docx_path, document, previous_document), (md_path, markdown, legacy_markdown)):
            if previous and previous_document is not None:
                try:
                    current = workspace.read_authorized_file(path, MAX_BYTES)
                except FileNotFoundError:
                    current = None
                expected = hashes.get(path) or (hashlib.sha256(legacy).hexdigest() if legacy is not None else None)
                if current is not None and hashlib.sha256(current).hexdigest() != expected:
                    # 用户修改过的工作区副本保留，任务下载仍可获得新版排版。
                    continue
            write_artifact_file(workspace, path, content)
            hashes[path] = hashlib.sha256(content).hexdigest()
        record = {
            "id": identity,
            "title": title,
            "account": account,
            "folder": folder,
            "primary_path": docx_path,
            "import_path": md_path,
            "files": [docx_path, md_path],
            "layout_version": LAYOUT_VERSION,
            "generated_hashes": hashes,
            "updated_at": time.time(),
        }
        state["items"][identity] = record
    return record


def sync_articles(uid: str) -> dict:
    """复制已成功下载的文章及媒体，保持原版下载目录和工作区编辑隔离。"""
    directory = wechat_mp_service.owner_directory(wechat_mp_service.owner_key(uid))
    history_path = directory / "download_history.json"
    if not history_path.exists():
        return list_artifacts(uid, "wechat-articles")
    history = json.loads(history_path.read_text())
    output = directory / "articles_full"
    ensure_user_workspace(uid)
    workspace = Workspace(uid)
    source = "wechat-articles"
    with manifest(uid, source) as state:
        errors = []
        active_identities = set()
        for entry in history:
            if not entry.get("success") or not entry.get("path"):
                continue
            title = str(entry.get("title") or "公众号文章")
            try:
                original = Path(entry["path"])
                if not original.is_absolute():
                    original = output / original
                relative = original.relative_to(output)
                if ".." in relative.parts or original.is_symlink():
                    raise ValueError("文章路径无效")
                identity = artifact_id(str(entry.get("link") or entry.get("url") or relative))
                active_identities.add(identity)
                # rglob 不跟随目录链接；读取时再次通过逐级 no-follow fd 校验。
                paths = sorted(p for p in original.rglob("*") if p.is_file()) if original.is_dir() else [original]
                if len(paths) > 2000:
                    raise ValueError("文章资源超过 2000 个文件")
                documents = [p for p in paths if p.suffix.lower() in {".md", ".html", ".pdf"}]
                if not documents:
                    continue
                previous = state["items"].get(identity, {})
                folder = previous.get("folder") or target_folder(source, title, identity)
                signatures, files = {}, []
                total = 0
                for path in paths:
                    parts = path.relative_to(output).parts
                    if ".." in parts:
                        raise ValueError("文章资源路径无效")
                    with open_regular_file_fd(output, parts) as (fd, info):
                        total += info.st_size
                        if info.st_size > MAX_BYTES or total > MAX_ARCHIVE_BYTES:
                            raise ValueError("文章资源超过单文件 100 MB 或合计 500 MB 限制")
                        suffix = path.relative_to(original) if original.is_dir() else Path(path.name)
                        target = f"{folder}/{suffix.as_posix()}"
                        signature = [info.st_mtime_ns, info.st_size]
                        signatures[target] = signature
                        files.append(target)
                        try:
                            exists = not workspace.stat_authorized_path(target, root=folder)["is_dir"]
                        except FileNotFoundError:
                            exists = False
                        if previous.get("signatures", {}).get(target) == signature and exists:
                            continue
                        with os.fdopen(os.dup(fd), "rb") as stream:
                            content = stream.read(MAX_BYTES + 1)
                        write_artifact_file(workspace, target, content)
                priority = {".md": 0, ".html": 1, ".pdf": 2}
                primary = min(documents, key=lambda path: (priority[path.suffix.lower()], len(path.parts), str(path)))
                primary_path = (
                    f"{folder}/{primary.relative_to(original).as_posix() if original.is_dir() else primary.name}"
                )
                state["items"][identity] = {
                    "id": identity,
                    "title": title,
                    "account": entry.get("account", ""),
                    "canonical_url": entry.get("link") or entry.get("url") or "",
                    "folder": folder,
                    "primary_path": primary_path,
                    "import_path": primary_path,
                    "files": files,
                    "signatures": signatures,
                    "updated_at": entry.get("time") or time.time(),
                }
            except (OSError, ValueError) as error:
                errors.append({"title": title, "error": str(error)})
        for identity in set(state["items"]) - active_identities:
            stale = state["items"].pop(identity)
            folder = stale.get("folder")
            if not folder:
                continue
            try:
                workspace.delete_authorized_path(folder, root=artifact_root(source))
            except FileNotFoundError:
                pass
            except (OSError, ValueError) as error:
                errors.append(
                    {
                        "title": stale.get("title") or "公众号文章",
                        "error": f"历史已删除，沙盒副本清理失败：{error}",
                    }
                )
        state["errors"] = errors
    return list_artifacts(uid, source)


async def sync_videos(uid: str) -> dict:
    """将接入前的已完成视频成果补入工作区，不重新运行语音识别。"""
    from platform_core.services.wxchannels_service import list_owned_tasks
    from platform_core.storage.minio.client import StorageError, get_minio_client

    existing = {
        item["id"]
        for item in (await asyncio.to_thread(list_artifacts, uid, "wxchannels"))["items"]
        if item["available"] and item["import_available"] and item.get("layout_version") == LAYOUT_VERSION
    }
    storage = get_minio_client()
    errors = []
    for task in await list_owned_tasks(uid):
        for item in (task.get("result") or {}).get("items", []):
            identity = artifact_id(item.get("oid", ""))
            if item.get("status") != "completed" or identity in existing:
                continue
            try:
                content = await storage.adownload_file(storage.KB_BUCKETS["documents"], item["object_key"])
                document = await asyncio.to_thread(
                    video_docx_bytes, item["title"], item["text"], task["payload"]["account"]
                )
                await asyncio.to_thread(
                    publish_video,
                    uid,
                    item["oid"],
                    item["title"],
                    item["text"],
                    document,
                    task["payload"]["account"],
                    previous_document=content,
                )
                existing.add(identity)
            except (StorageError, OSError, ValueError):
                errors.append({"title": item["title"], "error": "文字稿原文件不可用，请重试同步或重新转录"})

    def save_errors():
        """保留逐项失败，单条旧记录损坏不阻塞其他成果。"""
        with manifest(uid, "wxchannels") as state:
            state["errors"] = errors

    await asyncio.to_thread(save_errors)
    return await asyncio.to_thread(list_artifacts, uid, "wxchannels")


async def ingest_artifacts(
    db: AsyncSession,
    *,
    uid: str,
    source: str,
    ids: list[str],
    kb_id: str,
    category_id: str | None,
) -> dict:
    """逐成果创建幂等知识入库任务，同一成果允许进入不同知识库。"""
    manifest_records = read_manifest(uid, source)["items"]
    persistent = {
        row.artifact_key: row
        for row in (
            await db.scalars(
                select(CollectionArtifactRecord).where(
                    CollectionArtifactRecord.owner_uid == uid,
                    CollectionArtifactRecord.source == source,
                    CollectionArtifactRecord.artifact_key.in_(ids),
                )
            )
        ).all()
    }
    workspace = Workspace(uid)
    tasks: list[Task] = []
    results = []
    for identity in dict.fromkeys(ids):
        record = persistent.get(identity)
        manifest_record = manifest_records.get(identity)
        if record is None or manifest_record is None:
            results.append(
                {
                    "id": identity,
                    "status": "failed",
                    "failure_stage": "ingest",
                    "error": "成果不存在，请刷新",
                }
            )
            continue
        try:
            content = workspace.read_authorized_file(manifest_record["import_path"], MAX_BYTES)
            digest = hashlib.sha256(content).hexdigest()
            existing = await db.scalar(
                select(CollectionArtifactIngestion)
                .where(
                    CollectionArtifactIngestion.artifact_id == record.id,
                    CollectionArtifactIngestion.kb_id == kb_id,
                    CollectionArtifactIngestion.content_hash == digest,
                )
                .with_for_update()
            )
            if existing is not None and existing.status in {"importing", "imported"}:
                results.append(
                    {
                        "id": identity,
                        "status": existing.status,
                        "task_id": existing.task_id,
                        "knowledge_file_id": existing.knowledge_file_id,
                        "idempotent": True,
                    }
                )
                continue
            filename = PurePosixPath(manifest_record["import_path"]).name
            object_name = f"{kb_id}/collection-artifacts/{record.id}/{digest}-{filename}"
            minio_url = await aupload_file_to_minio(MinIOClient.KB_BUCKETS["documents"], object_name, content)
            ingestion_id = existing.id if existing is not None else uuid.uuid4().hex
            params = {
                "content_type": "file",
                "auto_index": True,
                "content_hashes": {minio_url: digest},
                "file_sizes": {minio_url: len(content)},
                "source_paths": {minio_url: filename},
                "category_id": category_id,
            }
            task = await tasker.create_in_session(
                db,
                name=f"成果入库：{record.title[:80]}",
                task_type="knowledge_ingest",
                payload={
                    "kb_id": kb_id,
                    "items": [minio_url],
                    "params": params,
                    "operator_id": uid,
                    "artifact_ingestion_id": ingestion_id,
                },
            )
            if existing is None:
                existing = CollectionArtifactIngestion(
                    id=ingestion_id,
                    artifact_id=record.id,
                    kb_id=kb_id,
                    category_id=category_id,
                    content_hash=digest,
                    task_id=task.id,
                    status="importing",
                    created_by=uid,
                )
                db.add(existing)
            else:
                existing.category_id = category_id
                existing.task_id = task.id
                existing.status = "importing"
                existing.error = ""
                existing.knowledge_file_id = None
            record.content_hash = digest
            record.status = "importing"
            record.failure_stage = None
            record.error = ""
            tasks.append(task)
            results.append({"id": identity, "status": "importing", "task_id": task.id})
        except (OSError, ValueError) as error:
            record.status = "failed"
            record.failure_stage = "ingest"
            record.error = str(error)[:4000]
            results.append({"id": identity, "status": "failed", "failure_stage": "ingest", "error": str(error)})
    await db.commit()
    for task in tasks:
        await tasker.publish(task)
    return {"items": results, "submitted": len(tasks), "failed": sum(row["status"] == "failed" for row in results)}


async def finish_artifact_ingestion(session, task_record, result: dict) -> None:
    ingestion_id = str((task_record.payload or {}).get("artifact_ingestion_id") or "")
    if not ingestion_id:
        return
    ingestion = await session.get(CollectionArtifactIngestion, ingestion_id)
    if ingestion is None:
        return
    item = next(iter(result.get("items") or []), {})
    ingestion.status = "imported"
    ingestion.error = ""
    ingestion.knowledge_file_id = item.get("file_id")
    artifact = await session.get(CollectionArtifactRecord, ingestion.artifact_id)
    if artifact is not None:
        artifact.status = "imported"
        artifact.failure_stage = None
        artifact.error = ""


async def fail_artifact_ingestion(session, task_record, error: str) -> None:
    ingestion_id = str((task_record.payload or {}).get("artifact_ingestion_id") or "")
    if not ingestion_id:
        return
    ingestion = await session.get(CollectionArtifactIngestion, ingestion_id)
    if ingestion is None:
        return
    ingestion.status = "failed"
    ingestion.error = error[:4000]
    artifact = await session.get(CollectionArtifactRecord, ingestion.artifact_id)
    if artifact is not None:
        artifact.status = "failed"
        artifact.failure_stage = "ingest"
        artifact.error = error[:4000]


def archive_artifacts(uid: str, source: str, ids: list[str], destination: str) -> dict:
    """重新校验实际文件；部分缺失时继续打包有效内容并附失败清单。"""
    records = read_manifest(uid, source)["items"]
    workspace = Workspace(uid)
    total = 0
    written = 0
    failures: list[dict] = []
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for identity in dict.fromkeys(ids):
            record = records.get(identity)
            if record is None:
                failures.append({"id": identity, "title": "", "error": "成果不存在"})
                continue
            artifact_written = 0
            for path in record.get("files") or []:
                try:
                    content = workspace.read_authorized_file(path, MAX_BYTES)
                except (OSError, ValueError) as error:
                    failures.append(
                        {
                            "id": identity,
                            "title": record.get("title") or "",
                            "path": path,
                            "error": str(error),
                        }
                    )
                    continue
                next_total = total + len(content)
                if next_total > MAX_ARCHIVE_BYTES:
                    failures.append(
                        {
                            "id": identity,
                            "title": record.get("title") or "",
                            "path": path,
                            "size": len(content),
                            "error": "加入该文件后将超过 500 MB 限制",
                        }
                    )
                    raise ArtifactArchiveError(
                        "archive_too_large",
                        "批量下载超过 500 MB，请减少所选成果",
                        failures=failures,
                        total_bytes=next_total,
                    )
                total = next_total
                archive.writestr(PurePosixPath(path).relative_to(artifact_root(source)).as_posix(), content)
                written += 1
                artifact_written += 1
            if artifact_written == 0 and not any(row.get("id") == identity for row in failures):
                failures.append({"id": identity, "title": record.get("title") or "", "error": "成果没有可用文件"})
        if failures and written:
            archive.writestr(
                "失败清单.json",
                json.dumps({"failures": failures}, ensure_ascii=False, indent=2).encode(),
            )
    if written == 0:
        raise ArtifactArchiveError(
            "all_artifacts_unavailable",
            "所选成果均不可用",
            failures=failures,
            total_bytes=total,
        )
    return {"written_files": written, "failed_items": failures, "total_bytes": total}


def _canonical_article_url(value: str | None) -> str:
    """规范化公众号 URL 的无意义尾部差异，避免状态合并漏匹配。"""
    return str(value or "").strip().rstrip("/")


_DOWNLOAD_STATE_PRIORITY = {
    "failed": 1,
    "downloaded": 2,
    "imported": 3,
    "importing": 4,
}


def _artifact_download_state(
    record: CollectionArtifactRecord,
    ingestions: list[CollectionArtifactIngestion],
) -> tuple[str, str | None, str]:
    """按当前内容版本聚合多知识库入库状态。"""
    if record.failure_stage == "download":
        return "failed", "download", record.error

    current = [row for row in ingestions if record.content_hash and row.content_hash == record.content_hash]
    if any(row.status == "importing" for row in current):
        return "importing", None, ""
    if any(row.status == "imported" for row in current):
        return "imported", None, ""
    failed = next((row for row in current if row.status == "failed"), None)
    if failed is not None:
        return "failed", "ingest", failed.error
    if record.failure_stage == "ingest" and not ingestions:
        return "failed", "ingest", record.error
    return "downloaded", None, ""


def _ingestion_dict(row: CollectionArtifactIngestion) -> dict:
    return {
        "id": row.id,
        "kb_id": row.kb_id,
        "category_id": row.category_id,
        "content_hash": row.content_hash,
        "task_id": row.task_id,
        "knowledge_file_id": row.knowledge_file_id,
        "status": row.status,
        "error": row.error,
        "created_at": format_utc_datetime(row.created_at),
        "updated_at": format_utc_datetime(row.updated_at),
    }


async def mirror_article_workspaces():
    """页面关闭后仍发布下载结果；按源历史修改时间跳过未变更账号。"""
    versions = {}
    while True:
        for owner in wechat_mp_service.data_root().glob("*/owner.json"):
            try:
                history = owner.parent / "download_history.json"
                if not history.exists():
                    continue
                stamp = history.stat().st_mtime_ns
                if versions.get(str(owner)) == stamp:
                    continue
                uid = json.loads(owner.read_text())["uid"]
                result = await asyncio.to_thread(sync_articles, uid)
                if not result["errors"]:
                    versions[str(owner)] = stamp
            except (OSError, ValueError, KeyError):
                logger.exception("公众号成果同步失败，稍后重试")
        await asyncio.sleep(10)
