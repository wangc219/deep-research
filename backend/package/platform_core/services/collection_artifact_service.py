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
import zipfile

from platform_core.knowledge.video_transcriber.utils.docx_exporter import video_docx_bytes
from platform_core.knowledge.video_transcriber.utils.transcript_layout import LAYOUT_VERSION, video_markdown
from platform_core.services import wechat_mp_service
from platform_core.utils import logger
from platform_core.utils.paths import open_regular_file_fd
from platform_core.workspace.filesystem import Workspace
from platform_core.workspace.paths import ensure_user_workspace

SOURCES = {"wechat-articles": "公众号文章", "wxchannels": "视频号文字稿"}
MAX_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_BYTES = 500 * 1024 * 1024


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
                # rglob 不跟随目录链接；读取时再次通过逐级 no-follow fd 校验。
                paths = sorted(p for p in original.rglob("*") if p.is_file()) if original.is_dir() else [original]
                if len(paths) > 2000:
                    raise ValueError("文章资源超过 2000 个文件")
                documents = [p for p in paths if p.suffix.lower() in {".md", ".html", ".pdf"}]
                if not documents:
                    continue
                identity = artifact_id(str(entry.get("link") or entry.get("url") or relative))
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
                    "folder": folder,
                    "primary_path": primary_path,
                    "import_path": primary_path,
                    "files": files,
                    "signatures": signatures,
                    "updated_at": entry.get("time") or time.time(),
                }
            except (OSError, ValueError) as error:
                errors.append({"title": title, "error": str(error)})
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


def archive_artifacts(uid: str, source: str, ids: list[str], destination: str):
    """只打包当前用户勾选的成果文件，逐文件验证 no-follow 与总大小。"""
    records = read_manifest(uid, source)["items"]
    if any(identity not in records for identity in ids):
        raise ValueError("部分成果不存在，请刷新后重新选择")
    workspace = Workspace(uid)
    total = 0
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for identity in dict.fromkeys(ids):
            for path in records[identity]["files"]:
                content = workspace.read_authorized_file(path, MAX_BYTES)
                total += len(content)
                if total > MAX_ARCHIVE_BYTES:
                    raise ValueError("批量下载超过 500 MB，请减少所选成果")
                archive.writestr(PurePosixPath(path).relative_to(artifact_root(source)).as_posix(), content)


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
