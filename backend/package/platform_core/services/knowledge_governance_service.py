"""知识分类、统一来源采集和暂存审核用例。"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.config.environment import deep_research_env
from platform_core.services.knowledge_source_connectors import collect_source_items, content_hash
from platform_core.services.knowledge_source_credentials import decrypt_source_secret, encrypt_source_secret
from platform_core.services.scheduled_agent_service import next_run_at, validate_schedule
from platform_core.services.task_service import Task, TaskContext, tasker
from platform_core.storage.minio.client import MinIOClient, aupload_file_to_minio
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_knowledge import KnowledgeBase, KnowledgeFile
from platform_core.storage.postgres.models_knowledge_governance import (
    KnowledgeCategory,
    KnowledgeSource,
    KnowledgeSourceCredential,
    KnowledgeSourceItem,
    KnowledgeSourceRun,
)
from platform_core.utils.datetime_utils import format_utc_datetime, utc_now, utc_now_naive

SOURCE_TASK_TYPE = "knowledge_source_collect"
ACTIVE_SOURCE_RUN_STATUSES = {"pending", "running"}


def source_governance_enabled() -> bool:
    """按部署环境决定是否启用来源治理和定时采集。"""
    value = deep_research_env("SOURCE_GOVERNANCE_ENABLED", "true")
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def user_tenant_id(user) -> str:
    """读取当前用户组织边界。"""
    return str(getattr(user, "tenant_id", "default") or "default")


async def list_category_tree(
    db: AsyncSession,
    *,
    tenant_id: str,
    include_inactive: bool = False,
    accessible_kb_ids: set[str] | None = None,
) -> dict:
    """读取组织分类并组装稳定树结构。"""
    statement = select(KnowledgeCategory).where(KnowledgeCategory.tenant_id == tenant_id)
    if not include_inactive:
        statement = statement.where(KnowledgeCategory.active.is_(True))
    rows = list((await db.scalars(statement.order_by(KnowledgeCategory.sort_order, KnowledgeCategory.name))).all())
    allowed = accessible_kb_ids
    kb_counts = await _category_asset_counts(
        db,
        KnowledgeBase.category_id,
        KnowledgeBase.kb_id,
        allowed,
    )
    source_counts = await _category_asset_counts(
        db,
        KnowledgeSource.category_id,
        KnowledgeSource.kb_id,
        allowed,
    )
    file_counts = await _category_asset_counts(
        db,
        KnowledgeFile.category_id,
        KnowledgeFile.kb_id,
        allowed,
    )
    uncategorized_stats = {
        "knowledge_bases": await _uncategorized_asset_count(
            db,
            KnowledgeBase.category_id,
            KnowledgeBase.kb_id,
            allowed,
        ),
        "sources": await _uncategorized_asset_count(
            db,
            KnowledgeSource.category_id,
            KnowledgeSource.kb_id,
            allowed,
        ),
        "documents": await _uncategorized_asset_count(
            db,
            KnowledgeFile.category_id,
            KnowledgeFile.kb_id,
            allowed,
        ),
    }
    items = {
        row.id: _category_dict(row)
        | {
            "children": [],
            "stats": {
                "knowledge_bases": kb_counts.get(row.id, 0),
                "sources": source_counts.get(row.id, 0),
                "documents": file_counts.get(row.id, 0),
            },
        }
        for row in rows
    }
    roots = []
    for row in rows:
        item = items[row.id]
        parent = items.get(row.parent_id)
        if parent is None:
            roots.append(item)
        else:
            parent["children"].append(item)
    return {
        "items": roots,
        "flat": list(items.values()),
        "uncategorized": {
            "name": "未分类",
            "stats": uncategorized_stats,
        },
    }


async def ensure_organization_category(
    db: AsyncSession,
    *,
    tenant_id: str,
    category_id: str | None,
) -> None:
    """校验可空分类属于当前组织，供知识库创建入口复用。"""
    if category_id:
        await _tenant_category(db, tenant_id, category_id, require_active=True)


async def create_category(db: AsyncSession, *, tenant_id: str, user_uid: str, data: dict) -> dict:
    """创建一个组织分类节点。"""
    parent_id = _optional_text(data.get("parent_id"))
    if parent_id:
        await _tenant_category(db, tenant_id, parent_id, require_active=True)
    category = KnowledgeCategory(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        parent_id=parent_id,
        name=_required_text(data.get("name"), "分类名称", 255),
        description=str(data.get("description") or "").strip(),
        sort_order=int(data.get("sort_order") or 0),
        active=bool(data.get("active", True)),
        created_by=user_uid,
    )
    db.add(category)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="同一层级已存在同名分类") from exc
    return _category_dict(category)


async def update_category(db: AsyncSession, *, tenant_id: str, category_id: str, data: dict) -> dict:
    """更新分类并拒绝把节点挂到自身后代。"""
    category = await _tenant_category(db, tenant_id, category_id, lock=True)
    if "parent_id" in data:
        parent_id = _optional_text(data.get("parent_id"))
        if parent_id == category.id:
            raise HTTPException(status_code=409, detail="分类不能以自身作为父级")
        if parent_id:
            await _tenant_category(db, tenant_id, parent_id, require_active=True)
            descendants = await _category_descendant_ids(db, tenant_id, category.id)
            if parent_id in descendants:
                raise HTTPException(status_code=409, detail="分类不能移动到自身子级下")
        category.parent_id = parent_id
    if "name" in data:
        category.name = _required_text(data.get("name"), "分类名称", 255)
    if "description" in data:
        category.description = str(data.get("description") or "").strip()
    if "sort_order" in data:
        category.sort_order = int(data.get("sort_order") or 0)
    if "active" in data:
        category.active = bool(data["active"])
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="同一层级已存在同名分类") from exc
    return _category_dict(category)


async def delete_category(db: AsyncSession, *, tenant_id: str, category_id: str) -> None:
    """仅删除无子级、无知识资产引用的分类。"""
    category = await _tenant_category(db, tenant_id, category_id, lock=True)
    has_child = await db.scalar(select(KnowledgeCategory.id).where(KnowledgeCategory.parent_id == category.id).limit(1))
    referenced = False
    for statement in (
        select(KnowledgeBase.kb_id).where(KnowledgeBase.category_id == category.id),
        select(KnowledgeFile.file_id).where(KnowledgeFile.category_id == category.id),
        select(KnowledgeSource.id).where(KnowledgeSource.category_id == category.id),
    ):
        if await db.scalar(statement.limit(1)):
            referenced = True
            break
    if has_child or referenced:
        raise HTTPException(status_code=409, detail="分类仍有子级或知识资产引用，请先迁移引用或停用分类")
    await db.delete(category)
    await db.commit()


async def ensure_category_for_kb(
    db: AsyncSession,
    *,
    tenant_id: str,
    kb_id: str,
    category_id: str | None,
    allow_inactive: bool = False,
) -> KnowledgeCategory | None:
    """确保来源或文档分类位于知识库主分类分支。"""
    if not category_id:
        return None
    category = await _tenant_category(
        db,
        tenant_id,
        category_id,
        require_active=not allow_inactive,
    )
    kb = await db.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if not kb.category_id:
        return category
    if category.id == kb.category_id:
        return category
    descendants = await _category_descendant_ids(db, tenant_id, kb.category_id)
    if category.id not in descendants:
        raise HTTPException(status_code=409, detail="来源或文档分类必须位于知识库主分类之下")
    return category


async def assign_knowledge_base_category(
    db: AsyncSession, *, tenant_id: str, kb_id: str, category_id: str | None
) -> dict:
    """设置知识库主分类并验证现有来源和文档仍在分支内。"""
    kb = await db.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id).with_for_update())
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if category_id:
        category = await _tenant_category(db, tenant_id, category_id)
        if not category.active and category.id != kb.category_id:
            raise HTTPException(status_code=409, detail="停用分类不能分配给新的知识资产")
        allowed = {category_id, *(await _category_descendant_ids(db, tenant_id, category_id))}
        invalid_source = await db.scalar(
            select(KnowledgeSource.id)
            .where(
                KnowledgeSource.kb_id == kb_id,
                KnowledgeSource.category_id.is_not(None),
                KnowledgeSource.category_id.not_in(allowed),
            )
            .limit(1)
        )
        invalid_file = await db.scalar(
            select(KnowledgeFile.file_id)
            .where(
                KnowledgeFile.kb_id == kb_id,
                KnowledgeFile.category_id.is_not(None),
                KnowledgeFile.category_id.not_in(allowed),
            )
            .limit(1)
        )
        if invalid_source or invalid_file:
            raise HTTPException(status_code=409, detail="现有来源或文档不属于新主分类分支，请先迁移分类")
    kb.category_id = category_id
    await db.commit()
    return {"kb_id": kb_id, "category_id": category_id}


async def list_sources(db: AsyncSession, *, tenant_id: str, kb_id: str | None = None) -> dict:
    """列出组织内来源及最近运行摘要。"""
    statement = select(KnowledgeSource).where(KnowledgeSource.tenant_id == tenant_id)
    if kb_id:
        statement = statement.where(KnowledgeSource.kb_id == kb_id)
    sources = list((await db.scalars(statement.order_by(KnowledgeSource.updated_at.desc()))).all())
    return {"items": [_source_dict(source) for source in sources]}


async def create_source(db: AsyncSession, *, tenant_id: str, user_uid: str, data: dict) -> dict:
    """创建来源并把连接密码独立加密。"""
    kb_id = _required_text(data.get("kb_id"), "知识库", 80)
    category_id = _optional_text(data.get("category_id"))
    await ensure_category_for_kb(db, tenant_id=tenant_id, kb_id=kb_id, category_id=category_id)
    source_type = str(data.get("source_type") or "").strip()
    if source_type not in {"upload", "postgresql", "mysql", "website", "web_search"}:
        raise HTTPException(status_code=422, detail="来源类型不受支持")
    config = validate_source_config(source_type, sanitize_source_config(data.get("config")))
    cron_expression, timezone, following = _schedule_values(data.get("cron_expression"), data.get("timezone"))
    credential_id = await _save_credential(db, tenant_id, user_uid, data.get("credential"))
    source = KnowledgeSource(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        kb_id=kb_id,
        category_id=category_id,
        name=_required_text(data.get("name"), "来源名称", 255),
        source_type=source_type,
        config=config,
        credential_id=credential_id,
        enabled=bool(data.get("enabled", True)),
        notify_on_new=bool(data.get("notify_on_new", False)),
        cron_expression=cron_expression,
        timezone=timezone,
        next_run_at=following,
        created_by=user_uid,
    )
    db.add(source)
    await db.commit()
    return _source_dict(source)


async def update_source(db: AsyncSession, *, tenant_id: str, source_id: str, user_uid: str, data: dict) -> dict:
    """更新来源，连接密码为空时保留原密文。"""
    source = await _tenant_source(db, tenant_id, source_id, lock=True)
    if "category_id" in data:
        category_id = _optional_text(data.get("category_id"))
        await ensure_category_for_kb(
            db,
            tenant_id=tenant_id,
            kb_id=source.kb_id,
            category_id=category_id,
            allow_inactive=category_id == source.category_id,
        )
        source.category_id = category_id
    if "name" in data:
        source.name = _required_text(data.get("name"), "来源名称", 255)
    if "config" in data:
        source.config = validate_source_config(
            source.source_type,
            sanitize_source_config(data.get("config")),
        )
    if "credential" in data and data.get("credential"):
        new_id = await _save_credential(db, tenant_id, user_uid, data.get("credential"))
        old_id = source.credential_id
        source.credential_id = new_id
        if old_id:
            await db.execute(delete(KnowledgeSourceCredential).where(KnowledgeSourceCredential.id == old_id))
    if "enabled" in data:
        source.enabled = bool(data["enabled"])
    if "notify_on_new" in data:
        source.notify_on_new = bool(data["notify_on_new"])
    if "cron_expression" in data or "timezone" in data:
        expression, timezone, following = _schedule_values(
            data.get("cron_expression", source.cron_expression), data.get("timezone", source.timezone)
        )
        source.cron_expression = expression
        source.timezone = timezone
        source.next_run_at = following
    await db.commit()
    return _source_dict(source)


async def delete_source(db: AsyncSession, *, tenant_id: str, source_id: str) -> None:
    """删除来源配置及暂存运行，保留已经正式入库的文档。"""
    source = await _tenant_source(db, tenant_id, source_id, lock=True)
    credential_id = source.credential_id
    await db.delete(source)
    if credential_id:
        await db.execute(delete(KnowledgeSourceCredential).where(KnowledgeSourceCredential.id == credential_id))
    await db.commit()


async def test_source_connection(db: AsyncSession, *, tenant_id: str, source_id: str) -> dict:
    """使用极小采集上限验证来源配置，不写暂存项。"""
    source = await _tenant_source(db, tenant_id, source_id)
    config = dict(source.config or {})
    config.update({"max_rows": 1, "max_pages": 1, "count": 1})
    credential = await _source_credential(db, source)
    items = await collect_source_items(source.source_type, config, credential)
    return {"ok": True, "sample_count": len(items), "sample_title": items[0]["title"] if items else ""}


async def create_source_run(
    db: AsyncSession, *, tenant_id: str, source_id: str, owner_uid: str, trigger: str = "manual"
) -> dict:
    """在同一事务中创建来源运行与持久 Task，提交后发布。"""
    source = await _tenant_source(db, tenant_id, source_id, lock=True)
    active = await db.scalar(
        select(KnowledgeSourceRun.id)
        .where(
            KnowledgeSourceRun.source_id == source.id,
            KnowledgeSourceRun.status.in_(ACTIVE_SOURCE_RUN_STATUSES),
        )
        .limit(1)
    )
    if active:
        raise HTTPException(status_code=409, detail="该来源已有正在运行的采集任务")
    run = KnowledgeSourceRun(
        id=uuid.uuid4().hex,
        source_id=source.id,
        owner_uid=owner_uid,
        trigger=trigger,
        config_snapshot={"source_type": source.source_type, "config": source.config or {}},
    )
    task = await tasker.create_in_session(
        db,
        name=f"采集知识来源：{source.name}",
        task_type=SOURCE_TASK_TYPE,
        payload={"source_run_id": run.id, "operator_id": owner_uid},
        payload_match={"source_id": source.id},
    )
    run.task_id = task.id
    db.add(run)
    source.last_status = "pending"
    await db.commit()
    await tasker.publish(task)
    return _source_run_dict(run)


async def list_source_runs(db: AsyncSession, *, tenant_id: str, source_id: str) -> dict:
    """列出来源最近运行。"""
    await _tenant_source(db, tenant_id, source_id)
    rows = list(
        (
            await db.scalars(
                select(KnowledgeSourceRun)
                .where(KnowledgeSourceRun.source_id == source_id)
                .order_by(KnowledgeSourceRun.created_at.desc())
                .limit(50)
            )
        ).all()
    )
    return {"items": [_source_run_dict(row) for row in rows]}


async def list_staging_items(
    db: AsyncSession,
    *,
    tenant_id: str,
    kb_id: str | None,
    review_status: str | None,
    page: int,
    page_size: int,
) -> dict:
    """分页读取组织内可审核暂存证据。"""
    statement = (
        select(KnowledgeSourceItem)
        .join(KnowledgeSource, KnowledgeSource.id == KnowledgeSourceItem.source_id)
        .where(KnowledgeSource.tenant_id == tenant_id)
    )
    count_statement = (
        select(func.count(KnowledgeSourceItem.id))
        .join(KnowledgeSource, KnowledgeSource.id == KnowledgeSourceItem.source_id)
        .where(KnowledgeSource.tenant_id == tenant_id)
    )
    if kb_id:
        statement = statement.where(KnowledgeSourceItem.kb_id == kb_id)
        count_statement = count_statement.where(KnowledgeSourceItem.kb_id == kb_id)
    if review_status:
        statement = statement.where(KnowledgeSourceItem.review_status == review_status)
        count_statement = count_statement.where(KnowledgeSourceItem.review_status == review_status)
    total = int(await db.scalar(count_statement) or 0)
    rows = list(
        (
            await db.scalars(
                statement.order_by(KnowledgeSourceItem.discovered_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return {"items": [_source_item_dict(row) for row in rows], "total": total, "page": page, "page_size": page_size}


async def review_staging_items(
    db: AsyncSession,
    *,
    tenant_id: str,
    kb_id: str,
    user_uid: str,
    ids: list[str],
    decision: str,
    note: str,
    category_id: str | None,
) -> dict:
    """批量审核暂存项；通过时提交知识库解析与索引任务。"""
    if decision not in {"approved", "rejected"}:
        raise HTTPException(status_code=422, detail="审核决定必须为 approved 或 rejected")
    rows = list(
        (
            await db.scalars(
                select(KnowledgeSourceItem)
                .join(KnowledgeSource, KnowledgeSource.id == KnowledgeSourceItem.source_id)
                .where(
                    KnowledgeSource.tenant_id == tenant_id,
                    KnowledgeSourceItem.kb_id == kb_id,
                    KnowledgeSourceItem.id.in_(ids),
                    KnowledgeSourceItem.review_status == "pending",
                )
                .with_for_update()
            )
        ).all()
    )
    if len(rows) != len(set(ids)):
        raise HTTPException(status_code=404, detail="部分暂存项不存在或不可访问")
    tasks: list[Task] = []
    results = []
    now = utc_now()
    for item in rows:
        chosen_category = category_id or item.category_id
        await ensure_category_for_kb(
            db,
            tenant_id=tenant_id,
            kb_id=item.kb_id,
            category_id=chosen_category,
            allow_inactive=chosen_category == item.category_id,
        )
        item.category_id = chosen_category
        item.review_status = decision
        item.review_note = note
        item.reviewed_by = user_uid
        item.reviewed_at = now
        if decision == "rejected":
            results.append({"id": item.id, "status": "rejected"})
            continue

        content = item.markdown.encode("utf-8")
        object_name = f"{item.kb_id}/sources/{item.source_id}/{item.content_hash}.md"
        minio_url = item.minio_url or await aupload_file_to_minio(
            MinIOClient.KB_BUCKETS["documents"], object_name, content
        )
        item.minio_url = minio_url
        params = {
            "content_type": "file",
            "auto_index": True,
            "content_hashes": {minio_url: item.content_hash},
            "file_sizes": {minio_url: len(content)},
            "source_paths": {minio_url: _safe_markdown_filename(item.title, item.content_hash)},
            "category_id": chosen_category,
            "source_id": item.source_id,
            "source_item_id": item.id,
        }
        task = await tasker.create_in_session(
            db,
            name=f"审核通过并入库：{item.title[:80]}",
            task_type="knowledge_ingest",
            payload={
                "kb_id": item.kb_id,
                "items": [minio_url],
                "params": params,
                "operator_id": user_uid,
                "source_item_ids": [item.id],
            },
        )
        item.ingest_task_id = task.id
        tasks.append(task)
        results.append({"id": item.id, "status": "approved", "task_id": task.id})
    await db.commit()
    for task in tasks:
        await tasker.publish(task)
    return {"items": results}


async def run_knowledge_source_collection(context: TaskContext) -> dict:
    """从持久运行快照执行来源采集、去重和版本登记。"""
    run_id = str(context.payload["source_run_id"])
    async with pg_manager.get_async_session_context() as db:
        run = await db.get(KnowledgeSourceRun, run_id)
        if run is None:
            raise ValueError("知识来源运行不存在")
        source = await db.get(KnowledgeSource, run.source_id)
        if source is None:
            raise ValueError("知识来源已删除")
        run.status = "running"
        run.started_at = utc_now()
        source.last_status = "running"
        credential = await _source_credential(db, source)
        snapshot = dict(run.config_snapshot or {})
        source_type = str(snapshot.get("source_type") or source.source_type)
        config = dict(snapshot.get("config") or source.config or {})
        if (source.cursor or {}).get("value") is not None:
            config["cursor_value"] = source.cursor["value"]
        await db.commit()

    await context.set_progress(10, "正在读取来源")
    candidates, collection_attempts = await _collect_source_items_with_retry(
        source_type,
        config,
        credential,
        context,
    )
    await context.raise_if_cancelled()
    await context.set_progress(55, f"已读取 {len(candidates)} 条，正在去重")

    created = 0
    duplicates = 0
    failed = 0
    cursor_value = None
    async with pg_manager.get_async_session_context() as db:
        run = await db.get(KnowledgeSourceRun, run_id)
        source = await db.get(KnowledgeSource, run.source_id)
        created_items: list[KnowledgeSourceItem] = []
        for candidate_index, candidate in enumerate(candidates):
            try:
                markdown = str(candidate.get("markdown") or "").strip()
                if not markdown:
                    raise ValueError("来源正文为空")
                digest = content_hash(markdown)
                existing_hash = await db.scalar(
                    select(KnowledgeSourceItem)
                    .where(
                        KnowledgeSourceItem.source_id == source.id,
                        KnowledgeSourceItem.content_hash == digest,
                    )
                    .limit(1)
                )
                if existing_hash:
                    duplicates += 1
                    db.add(
                        _operational_source_item(
                            source,
                            run,
                            candidate,
                            candidate_index,
                            status="duplicate",
                            reason="内容哈希已存在，本次未重复入库",
                            duplicate_of=existing_hash,
                        )
                    )
                    continue
                external_key = _required_text(candidate.get("external_key"), "来源业务键", 1024)
                previous = await db.scalar(
                    select(KnowledgeSourceItem)
                    .where(
                        KnowledgeSourceItem.source_id == source.id,
                        KnowledgeSourceItem.external_key == external_key,
                    )
                    .order_by(KnowledgeSourceItem.version.desc())
                    .limit(1)
                )
                metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
                item = KnowledgeSourceItem(
                    id=uuid.uuid4().hex,
                    source_id=source.id,
                    run_id=run.id,
                    kb_id=source.kb_id,
                    category_id=source.category_id,
                    external_key=external_key,
                    canonical_url=str(candidate.get("canonical_url") or "")[:2048],
                    title=_required_text(candidate.get("title"), "来源标题", 2000),
                    markdown=markdown,
                    metadata_json=metadata,
                    content_hash=digest,
                    version=(previous.version + 1) if previous else 1,
                    previous_item_id=previous.id if previous else None,
                )
                db.add(item)
                created_items.append(item)
                created += 1
                cursor_value = metadata.get("cursor", cursor_value)
            except (ValueError, TypeError) as exc:
                failed += 1
                db.add(
                    _operational_source_item(
                        source,
                        run,
                        candidate if isinstance(candidate, dict) else {},
                        candidate_index,
                        status="failed",
                        reason=str(exc),
                    )
                )
        status = "partial" if failed else "completed"
        run.status = status
        run.stats = {
            "discovered": len(candidates),
            "created": created,
            "duplicates": duplicates,
            "failed": failed,
            "collection_attempts": collection_attempts,
        }
        run.completed_at = utc_now()
        source.last_status = status
        source.last_error = ""
        source.last_run_at = utc_now()
        if cursor_value is not None:
            source.cursor = {**(source.cursor or {}), "value": cursor_value}
        if source.cron_expression:
            source.next_run_at = _next_run_at_aware(source.cron_expression, source.timezone)
        if created_items and source.notify_on_new:
            from platform_core.services.innovation_brief_service import create_collection_update_briefs

            await db.flush()
            notified_subscriptions = await create_collection_update_briefs(
                db,
                source=source,
                source_run_id=run.id,
                items=created_items,
            )
            run.stats = {**run.stats, "notified_subscriptions": notified_subscriptions}
        await db.commit()

    result = {"source_run_id": run_id, **run.stats}
    await context.set_result(result)
    await context.set_progress(100, f"采集完成，新增 {created} 条，重复 {duplicates} 条")
    return result


async def fail_knowledge_source_collection(session, task_record, error: str) -> None:
    """原子收敛失败的来源运行和来源状态。"""
    run_id = str((task_record.payload or {}).get("source_run_id") or "")
    if not run_id:
        return
    run = await session.get(KnowledgeSourceRun, run_id)
    if run is None:
        return
    run.status = "failed"
    run.error = error[:4000]
    run.completed_at = utc_now()
    source = await session.get(KnowledgeSource, run.source_id)
    if source is not None:
        source.last_status = "failed"
        source.last_error = error[:4000]
        source.last_run_at = utc_now()


async def _collect_source_items_with_retry(
    source_type: str,
    config: dict,
    credential: dict | None,
    context: TaskContext,
) -> tuple[list[dict], int]:
    """按来源配置执行有界指数退避，最终错误交给 Durable Task 收敛。"""
    retries_value = config.get("max_retries")
    delay_value = config.get("retry_delay_seconds")
    max_retries = min(max(int(2 if retries_value is None else retries_value), 0), 5)
    retry_delay = min(max(float(1.0 if delay_value is None else delay_value), 0.0), 60.0)
    for attempt in range(1, max_retries + 2):
        try:
            return await collect_source_items(source_type, config, credential), attempt
        except asyncio.CancelledError:
            raise
        except Exception:
            if attempt > max_retries:
                raise
            await context.raise_if_cancelled()
            await context.set_progress(
                min(9, 2 + attempt),
                f"来源读取失败，正在进行第 {attempt + 1} 次尝试",
            )
            if retry_delay:
                await asyncio.sleep(min(retry_delay * (2 ** (attempt - 1)), 60.0))
    raise RuntimeError("来源重试状态异常")


async def claim_due_source_runs(*, limit: int = 10) -> int:
    """为到期来源创建不重叠的持久采集任务。"""
    if not source_governance_enabled():
        return 0

    created = 0
    now = utc_now()
    for _ in range(limit):
        task = None
        async with pg_manager.get_async_session_context() as db:
            source = await db.scalar(
                select(KnowledgeSource)
                .where(
                    KnowledgeSource.enabled.is_(True),
                    KnowledgeSource.cron_expression.is_not(None),
                    KnowledgeSource.next_run_at <= now,
                )
                .order_by(KnowledgeSource.next_run_at, KnowledgeSource.id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if source is None:
                break
            active = await db.scalar(
                select(KnowledgeSourceRun.id)
                .where(
                    KnowledgeSourceRun.source_id == source.id,
                    KnowledgeSourceRun.status.in_(ACTIVE_SOURCE_RUN_STATUSES),
                )
                .limit(1)
            )
            source.next_run_at = _next_run_at_aware(source.cron_expression, source.timezone)
            if not active:
                run = KnowledgeSourceRun(
                    id=uuid.uuid4().hex,
                    source_id=source.id,
                    owner_uid=source.created_by,
                    trigger="scheduled",
                    config_snapshot={"source_type": source.source_type, "config": source.config or {}},
                )
                task = await tasker.create_in_session(
                    db,
                    name=f"定时采集：{source.name}",
                    task_type=SOURCE_TASK_TYPE,
                    payload={"source_run_id": run.id, "operator_id": source.created_by},
                    payload_match={"source_id": source.id},
                )
                run.task_id = task.id
                db.add(run)
            await db.commit()
        if task:
            await tasker.publish(task)
            created += 1
    return created


async def _tenant_category(
    db: AsyncSession,
    tenant_id: str,
    category_id: str,
    *,
    lock: bool = False,
    require_active: bool = False,
) -> KnowledgeCategory:
    statement = select(KnowledgeCategory).where(
        KnowledgeCategory.id == category_id, KnowledgeCategory.tenant_id == tenant_id
    )
    if lock:
        statement = statement.with_for_update()
    category = await db.scalar(statement)
    if category is None:
        raise HTTPException(status_code=404, detail="分类不存在或不属于当前组织")
    if require_active and not category.active:
        raise HTTPException(status_code=409, detail="停用分类不能分配给新的知识资产")
    return category


async def _tenant_source(db: AsyncSession, tenant_id: str, source_id: str, *, lock: bool = False) -> KnowledgeSource:
    statement = select(KnowledgeSource).where(KnowledgeSource.id == source_id, KnowledgeSource.tenant_id == tenant_id)
    if lock:
        statement = statement.with_for_update()
    source = await db.scalar(statement)
    if source is None:
        raise HTTPException(status_code=404, detail="知识来源不存在")
    return source


async def _category_descendant_ids(db: AsyncSession, tenant_id: str, category_id: str) -> set[str]:
    rows = list(
        (
            await db.execute(
                select(KnowledgeCategory.id, KnowledgeCategory.parent_id).where(
                    KnowledgeCategory.tenant_id == tenant_id
                )
            )
        ).all()
    )
    children: dict[str, list[str]] = {}
    for child_id, parent_id in rows:
        if parent_id:
            children.setdefault(parent_id, []).append(child_id)
    descendants = set()
    stack = list(children.get(category_id, []))
    while stack:
        child = stack.pop()
        if child in descendants:
            continue
        descendants.add(child)
        stack.extend(children.get(child, []))
    return descendants


async def _category_asset_counts(db, category_column, kb_column, allowed_kb_ids: set[str] | None) -> dict:
    statement = select(category_column, func.count()).where(category_column.is_not(None)).group_by(category_column)
    if allowed_kb_ids is not None:
        if not allowed_kb_ids:
            return {}
        statement = statement.where(kb_column.in_(allowed_kb_ids))
    return {category_id: int(count) for category_id, count in (await db.execute(statement)).all()}


async def _uncategorized_asset_count(
    db,
    category_column,
    kb_column,
    allowed_kb_ids: set[str] | None,
) -> int:
    """统计当前用户可访问范围内仍保持空分类的历史资产。"""
    statement = select(func.count()).where(category_column.is_(None))
    if allowed_kb_ids is not None:
        if not allowed_kb_ids:
            return 0
        statement = statement.where(kb_column.in_(allowed_kb_ids))
    return int(await db.scalar(statement) or 0)


async def _save_credential(db: AsyncSession, tenant_id: str, user_uid: str, credential: Any) -> str | None:
    if not credential:
        return None
    if not isinstance(credential, dict):
        raise HTTPException(status_code=422, detail="来源凭据必须为对象")
    record = KnowledgeSourceCredential(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        encrypted_secret=encrypt_source_secret(json.dumps(credential, ensure_ascii=False)),
        created_by=user_uid,
    )
    db.add(record)
    await db.flush()
    return record.id


async def _source_credential(db: AsyncSession, source: KnowledgeSource) -> dict | None:
    if not source.credential_id:
        return None
    record = await db.get(KnowledgeSourceCredential, source.credential_id)
    if record is None or record.tenant_id != source.tenant_id:
        raise ValueError("知识来源凭据不存在")
    value = json.loads(decrypt_source_secret(record.encrypted_secret))
    if not isinstance(value, dict):
        raise ValueError("知识来源凭据格式无效")
    return value


def _schedule_values(expression: Any, timezone: Any) -> tuple[str | None, str, datetime | None]:
    zone = str(timezone or "Asia/Shanghai")
    normalized = str(expression or "").strip()
    if not normalized:
        return None, zone, None
    normalized, zone = validate_schedule(normalized, zone)
    return normalized, zone, _next_run_at_aware(normalized, zone)


def _next_run_at_aware(expression: str, timezone: str) -> datetime:
    """把旧调度器的 naive UTC 结果标记为 TIMESTAMPTZ 所需的 aware UTC。"""
    return next_run_at(expression, timezone, utc_now_naive()).replace(tzinfo=UTC)


def sanitize_source_config(value: Any) -> dict:
    if not isinstance(value, dict):
        return {}
    forbidden = {
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "authorization",
        "cookie",
        "credentials",
    }
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            for key, item in current.items():
                normalized = str(key).casefold().replace("-", "_")
                if normalized in forbidden or any(normalized.endswith(f"_{name}") for name in forbidden):
                    raise HTTPException(status_code=422, detail="连接凭据必须放入 credential，不得写入来源配置")
                pending.append(item)
        elif isinstance(current, list):
            pending.extend(current)
    if len(json.dumps(value, ensure_ascii=False)) > 100_000:
        raise HTTPException(status_code=422, detail="来源配置不能超过 100 KB")
    return value


def validate_source_config(source_type: str, config: dict) -> dict:
    """在保存前拒绝越权能力，并保证各连接器拥有最小必要配置。"""
    if source_type in {"postgresql", "mysql"}:
        forbidden = {"sql", "query", "statement", "raw_sql"}
        if forbidden.intersection(key.casefold() for key in config):
            raise HTTPException(status_code=422, detail="数据库来源不接受任意 SQL，只能配置表/视图和字段映射")
        if not str(config.get("table") or "").strip():
            raise HTTPException(status_code=422, detail="数据库来源必须选择表或视图")
        if not str(config.get("primary_key") or "").strip():
            raise HTTPException(status_code=422, detail="数据库来源必须配置主键")
        if not isinstance(config.get("content_columns"), list) or not config["content_columns"]:
            raise HTTPException(status_code=422, detail="数据库来源必须配置正文列")
    elif source_type == "website":
        forbidden = {"headers", "cookies", "cookie", "authorization", "login", "session"}
        if forbidden.intersection(key.casefold() for key in config):
            raise HTTPException(status_code=422, detail="网站来源首版不支持登录态、Cookie 或自定义认证头")
        if not any(config.get(key) for key in ("urls", "seed_urls", "sitemap_url", "rss_url")):
            raise HTTPException(status_code=422, detail="网站来源至少需要 URL、sitemap 或 RSS")
    elif source_type == "web_search":
        if not any(config.get(key) for key in ("queries", "topics", "query_combinations")):
            raise HTTPException(status_code=422, detail="WebSearch 来源至少需要关注话题或查询组合")
    return config


def _required_text(value: Any, label: str, maximum: int) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise HTTPException(status_code=422, detail=f"{label}不能为空")
    if len(normalized) > maximum:
        raise HTTPException(status_code=422, detail=f"{label}不能超过 {maximum} 个字符")
    return normalized


def _optional_text(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _safe_markdown_filename(title: str, digest: str) -> str:
    """生成不含路径控制字符的稳定 Markdown 文件名。"""
    stem = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "-", str(title or "")).strip(" .-")
    stem = re.sub(r"\s+", " ", stem)[:180].strip()
    return f"{stem or digest[:16]}.md"


def _operational_source_item(
    source: KnowledgeSource,
    run: KnowledgeSourceRun,
    candidate: dict,
    index: int,
    *,
    status: str,
    reason: str,
    duplicate_of: KnowledgeSourceItem | None = None,
) -> KnowledgeSourceItem:
    """为重复或逐项失败保留可审核的运行事实，不复制原始正文。"""
    marker = f"{run.id}:{index}:{status}:{duplicate_of.id if duplicate_of else ''}:{reason}"
    digest = content_hash(marker)
    title = str(candidate.get("title") or (duplicate_of.title if duplicate_of else "采集项处理失败"))
    return KnowledgeSourceItem(
        id=uuid.uuid4().hex,
        source_id=source.id,
        run_id=run.id,
        kb_id=source.kb_id,
        category_id=source.category_id,
        external_key=f"{status}:{run.id}:{index}",
        canonical_url=str(candidate.get("canonical_url") or "")[:2048],
        title=title[:2000],
        markdown=f"# {title}\n\n状态：{status}\n\n原因：{reason}\n",
        metadata_json={
            "operational_status": status,
            "reason": reason,
            "duplicate_content_hash": duplicate_of.content_hash if duplicate_of else None,
        },
        content_hash=digest,
        version=1,
        previous_item_id=duplicate_of.id if duplicate_of else None,
        review_status=status,
    )


def _category_dict(row: KnowledgeCategory) -> dict:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "parent_id": row.parent_id,
        "name": row.name,
        "description": row.description,
        "sort_order": row.sort_order,
        "active": bool(row.active),
        "created_by": row.created_by,
        "created_at": format_utc_datetime(row.created_at),
        "updated_at": format_utc_datetime(row.updated_at),
    }


def _source_dict(row: KnowledgeSource) -> dict:
    return {
        "id": row.id,
        "kb_id": row.kb_id,
        "category_id": row.category_id,
        "name": row.name,
        "source_type": row.source_type,
        "config": row.config or {},
        "credential_configured": bool(row.credential_id),
        "enabled": bool(row.enabled),
        "notify_on_new": bool(row.notify_on_new),
        "cron_expression": row.cron_expression,
        "timezone": row.timezone,
        "cursor": row.cursor or {},
        "last_status": row.last_status,
        "last_error": row.last_error,
        "last_run_at": format_utc_datetime(row.last_run_at),
        "next_run_at": format_utc_datetime(row.next_run_at),
        "created_by": row.created_by,
        "created_at": format_utc_datetime(row.created_at),
        "updated_at": format_utc_datetime(row.updated_at),
    }


def _source_run_dict(row: KnowledgeSourceRun) -> dict:
    return {
        "id": row.id,
        "source_id": row.source_id,
        "task_id": row.task_id,
        "trigger": row.trigger,
        "status": row.status,
        "stats": row.stats or {},
        "error": row.error,
        "started_at": format_utc_datetime(row.started_at),
        "completed_at": format_utc_datetime(row.completed_at),
        "created_at": format_utc_datetime(row.created_at),
    }


def _source_item_dict(row: KnowledgeSourceItem) -> dict:
    return {
        "id": row.id,
        "source_id": row.source_id,
        "run_id": row.run_id,
        "kb_id": row.kb_id,
        "category_id": row.category_id,
        "external_key": row.external_key,
        "canonical_url": row.canonical_url,
        "title": row.title,
        "markdown": row.markdown,
        "metadata": row.metadata_json or {},
        "content_hash": row.content_hash,
        "version": row.version,
        "previous_item_id": row.previous_item_id,
        "review_status": row.review_status,
        "review_note": row.review_note,
        "reviewed_by": row.reviewed_by,
        "reviewed_at": format_utc_datetime(row.reviewed_at),
        "knowledge_file_id": row.knowledge_file_id,
        "ingest_task_id": row.ingest_task_id,
        "discovered_at": format_utc_datetime(row.discovered_at),
    }
