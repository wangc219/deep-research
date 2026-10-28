from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from platform_core.knowledge.graphs.milvus_graph_service import MilvusGraphService
from platform_core.knowledge.runtime import knowledge_base
from platform_core.knowledge.utils import params_for_uploaded_document
from platform_core.repositories.knowledge_file_repository import KnowledgeFileRepository
from platform_core.services.knowledge_folder_service import knowledge_folder_service
from platform_core.services.task_service import TaskContext
from platform_core.utils.logging_config import logger

DOCUMENT_ACTION_BATCH_SIZE = 500
DOCUMENT_ACTION_RESULT_ITEM_LIMIT = 200
DEFAULT_DOCUMENT_PARSE_CONCURRENCY = 2
MAX_DOCUMENT_PARSE_CONCURRENCY = 4


def resolve_document_concurrency(params: dict) -> int:
    """限制单个批量任务的文件解析并发。"""
    value = params.get("parse_concurrency", DEFAULT_DOCUMENT_PARSE_CONCURRENCY)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_DOCUMENT_PARSE_CONCURRENCY:
        raise ValueError("文件解析并发必须是 1 到 4 之间的整数")
    return value


async def run_document_batch(items: Sequence, process: Callable[[int, Any], Awaitable], *, concurrency: int) -> list:
    """按固定 worker 数处理文档，保持结果顺序，取消时收敛全部子任务。"""
    iterator = iter(enumerate(items))
    results = [None] * len(items)

    async def worker() -> None:
        for index, item in iterator:
            results[index] = await process(index, item)

    workers = [asyncio.create_task(worker()) for _ in range(min(concurrency, len(items)))]
    try:
        await asyncio.gather(*workers)
    except BaseException:
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        raise
    return results


def _is_failed_item(item: dict) -> bool:
    return item.get("status") == "failed" or bool(item.get("error"))


def _append_result_sample(items: list[dict], item: dict) -> None:
    if len(items) < DOCUMENT_ACTION_RESULT_ITEM_LIMIT:
        items.append(item)


async def fail_knowledge_file_task(session, task_record, error: str) -> None:
    """原子收敛仍由失败 Task attempt 拥有的知识文件中间态。"""
    await KnowledgeFileRepository.fail_task_processing_in_session(
        session,
        task_id=task_record.id,
        error=error,
    )


async def run_knowledge_ingest(context: TaskContext) -> dict:
    """从持久 payload 重建文档添加、解析和可选索引流程。"""
    payload = context.payload
    kb_id = payload["kb_id"]
    items = list(payload["items"])
    params = dict(payload.get("params") or {})
    parse_concurrency = resolve_document_concurrency(params)
    operator_id = payload["operator_id"]
    auto_index = bool(params.get("auto_index", False))
    indexing_params = {
        key: params[key]
        for key in ("chunk_preset_id", "chunk_parser_config")
        if key in params and params[key] is not None
    }
    processing_owner = {
        "processing_task_id": context.task_id,
        "processing_owner": context.worker_id,
    }

    await context.set_progress(5.0, "准备处理文档")
    total = len(items)
    processed_items: list[dict | None] = [None] * total
    added_files: list[dict] = []

    try:
        for index, item in enumerate(items, 1):
            await context.raise_if_cancelled()
            await context.set_progress(5.0 + (index / total) * 25.0, f"[1/3] 添加记录 {index}/{total}")
            try:
                file_meta = await knowledge_base.add_file_record(
                    kb_id,
                    item,
                    params=params_for_uploaded_document(item, params),
                    operator_id=operator_id,
                )
                added_files.append(
                    {
                        "index": index - 1,
                        "item": item,
                        "file_id": file_meta["file_id"],
                        "file_meta": file_meta,
                    }
                )
            except Exception as exc:
                logger.error("添加文件记录失败 %s: %s", item, exc)
                error_type = "timeout" if isinstance(exc, TimeoutError) else "add_failed"
                error_message = "添加超时" if isinstance(exc, TimeoutError) else "添加记录失败"
                processed_items[index - 1] = {
                    "item": item,
                    "status": "failed",
                    "error": f"{error_message}: {exc}",
                    "error_type": error_type,
                }

        parse_end = 60.0 if auto_index else 95.0
        parse_completed = 0
        progress_lock = asyncio.Lock()

        async def parse_record(index, record):
            nonlocal parse_completed
            await context.raise_if_cancelled()
            try:
                file_meta = await knowledge_base.parse_file(
                    kb_id,
                    record["file_id"],
                    operator_id=operator_id,
                    **processing_owner,
                )
                record["file_meta"] = file_meta
                if not auto_index or file_meta.get("status") != "parsed":
                    processed_items[record["index"]] = file_meta
            except Exception as exc:
                logger.error("解析文件失败 %s (file_id=%s): %s", record["item"], record["file_id"], exc)
                error_type = "timeout" if isinstance(exc, TimeoutError) else "parse_failed"
                error_message = "解析超时" if isinstance(exc, TimeoutError) else "解析失败"
                processed_items[record["index"]] = {
                    "item": record["item"],
                    "status": "failed",
                    "error": f"{error_message}: {exc}",
                    "error_type": error_type,
                }
            async with progress_lock:
                parse_completed += 1
                await context.set_progress(
                    30.0 + (parse_completed / len(added_files)) * (parse_end - 30.0),
                    f"[2/3] 已解析 {parse_completed}/{len(added_files)}，并发 {parse_concurrency}",
                )

        await run_document_batch(added_files, parse_record, concurrency=parse_concurrency)

        if auto_index:
            parsed_files = [record for record in added_files if record["file_meta"].get("status") == "parsed"]
            for index, record in enumerate(parsed_files, 1):
                await context.raise_if_cancelled()
                await context.set_progress(
                    60.0 + (index / len(parsed_files)) * 35.0,
                    f"[3/3] 入库文件 {index}/{len(parsed_files)}",
                )
                try:
                    await knowledge_base.update_file_params(
                        kb_id,
                        record["file_id"],
                        indexing_params,
                        operator_id=operator_id,
                    )
                    processed_items[record["index"]] = await knowledge_base.index_file(
                        kb_id,
                        record["file_id"],
                        operator_id=operator_id,
                        params=indexing_params,
                        **processing_owner,
                    )
                except Exception as exc:
                    logger.error("自动入库失败 %s (file_id=%s): %s", record["item"], record["file_id"], exc)
                    processed_items[record["index"]] = {
                        "item": record["item"],
                        "status": "failed",
                        "error": f"入库失败: {exc}",
                        "error_type": "index_failed",
                    }
    except asyncio.CancelledError:
        await context.set_progress(100.0, "任务已取消")
        raise

    await context.raise_if_cancelled()
    final_items = [
        item
        if item is not None
        else {
            "item": items[index],
            "status": "failed",
            "error": "文件未处理",
            "error_type": "not_processed",
        }
        for index, item in enumerate(processed_items)
    ]
    failed_count = sum(_is_failed_item(item) for item in final_items)
    summary = {
        "kb_id": kb_id,
        "item_type": "文件",
        "submitted": total,
        "failed": failed_count,
        "items": final_items,
    }
    await context.set_result(summary)
    await context.set_progress(100.0, f"文件处理完成，失败 {failed_count} 个" if failed_count else "文件处理完成")
    if failed_count:
        raise RuntimeError(f"文件处理完成，失败 {failed_count} 个")
    return summary


async def run_knowledge_parse(context: TaskContext) -> dict:
    """按指定文件或待处理状态执行可重建的解析任务。"""
    if context.payload.get("scope") == "pending":
        return await _run_pending_files(context, action="parse")
    return await _run_file_ids(context, action="parse")


async def run_knowledge_index(context: TaskContext) -> dict:
    """按指定文件或待处理状态执行可重建的索引任务。"""
    if context.payload.get("scope") in {"pending", "rebuild"}:
        return await _run_pending_files(context, action="index")
    return await _run_file_ids(context, action="index")


async def _run_file_ids(context: TaskContext, *, action: str) -> dict:
    payload = context.payload
    kb_id = payload["kb_id"]
    file_ids = list(payload["file_ids"])
    params = dict(payload.get("params") or {})
    operator_id = payload["operator_id"]
    label = "解析" if action == "parse" else "入库"
    processing_owner = {
        "processing_task_id": context.task_id,
        "processing_owner": context.worker_id,
    }
    await context.set_progress(5.0, f"准备{label}文档")

    processed_items: list[dict] = []
    completed = 0
    progress_lock = asyncio.Lock()
    concurrency = resolve_document_concurrency(params) if action == "parse" else 1

    async def process_file(index, file_id):
        nonlocal completed
        await context.raise_if_cancelled()
        try:
            if params:
                await knowledge_base.update_file_params(kb_id, file_id, params, operator_id=operator_id)
            if action == "parse":
                result = await knowledge_base.parse_file(
                    kb_id,
                    file_id,
                    operator_id=operator_id,
                    **processing_owner,
                )
            else:
                result = await knowledge_base.index_file(
                    kb_id,
                    file_id,
                    operator_id=operator_id,
                    params=params,
                    **processing_owner,
                )
        except Exception as exc:
            logger.error("{} failed for {}: {}", label, file_id, exc)
            result = {"file_id": file_id, "status": "failed", "error": str(exc)}
        async with progress_lock:
            completed += 1
            await context.set_progress(
                5.0 + (completed / len(file_ids)) * 90.0,
                f"已{label} {completed}/{len(file_ids)} 个文档，并发 {concurrency}",
            )
        return result

    processed_items = await run_document_batch(file_ids, process_file, concurrency=concurrency)

    await context.raise_if_cancelled()
    failed_count = sum(_is_failed_item(item) for item in processed_items)
    result = {"items": processed_items, "processed": len(processed_items), "failed": failed_count}
    await context.set_result(result)
    await context.set_progress(100.0, f"{label}完成，失败 {failed_count} 个")
    return result


async def _run_pending_files(context: TaskContext, *, action: str) -> dict:
    payload = context.payload
    kb_id = payload["kb_id"]
    statuses = list(payload["statuses"])
    initial_total = int(payload["count"])
    params = dict(payload.get("params") or {})
    operator_id = payload["operator_id"]
    label = "解析" if action == "parse" else "入库"
    processing_owner = {
        "processing_task_id": context.task_id,
        "processing_owner": context.worker_id,
    }
    await context.set_progress(5.0, f"准备{label}待处理文档")

    processed_count = 0
    failed_count = 0
    result_items: list[dict] = []
    after_file_id = None
    concurrency = resolve_document_concurrency(params) if action == "parse" else 1
    progress_lock = asyncio.Lock()

    async def process_file(index, file_id):
        nonlocal processed_count, failed_count
        await context.raise_if_cancelled()
        try:
            if params:
                await knowledge_base.update_file_params(kb_id, file_id, params, operator_id=operator_id)
            if action == "parse":
                result = await knowledge_base.parse_file(kb_id, file_id, operator_id=operator_id, **processing_owner)
            else:
                result = await knowledge_base.index_file(
                    kb_id,
                    file_id,
                    operator_id=operator_id,
                    params=params,
                    **processing_owner,
                )
        except Exception as exc:
            logger.error("Pending {} failed for {}: {}", action, file_id, exc)
            result = {"file_id": file_id, "status": "failed", "error": str(exc)}
        async with progress_lock:
            processed_count += 1
            failed_count += int(_is_failed_item(result))
            _append_result_sample(result_items, result)
            progress_total = max(initial_total, processed_count)
            await context.set_progress(
                5.0 + (processed_count / progress_total) * 90.0,
                f"已{label} {processed_count}/{progress_total} 个文档，并发 {concurrency}",
            )

    while True:
        file_ids = await knowledge_base.list_document_file_ids_by_statuses(
            kb_id,
            statuses=statuses,
            after_file_id=after_file_id,
            limit=DOCUMENT_ACTION_BATCH_SIZE,
        )
        if not file_ids:
            break
        await run_document_batch(file_ids, process_file, concurrency=concurrency)
        after_file_id = file_ids[-1]

    await context.raise_if_cancelled()
    result = {
        "items": result_items,
        "processed": processed_count,
        "failed": failed_count,
        "result_truncated": processed_count > len(result_items),
    }
    await context.set_result(result)
    await context.set_progress(
        100.0,
        f"{label}完成，失败 {failed_count} 个" if processed_count else f"没有待{label}文档",
    )
    return result


async def run_virtual_folder_migration(context: TaskContext) -> dict:
    """从持久 payload 重建历史虚拟目录迁移。"""
    return await knowledge_folder_service.migrate_virtual_folder_data(
        context,
        kb_id=context.payload["kb_id"],
        operator_id=context.payload["operator_id"],
    )


async def run_knowledge_graph(context: TaskContext) -> dict:
    """根据持久 action 重建图谱构建或向量修复任务。"""
    payload = context.payload
    kb_id = payload["kb_id"]
    service = MilvusGraphService()
    if payload.get("action") == "retry_failed":
        await context.set_progress(5.0, "准备重跑抽取失败的 Chunk")
        result = await service.build_pending_chunks(kb_id, context=context, failed_only=True)
        await context.raise_if_cancelled()
        await context.set_result(result)
        await context.set_progress(
            100.0,
            f"失败项重跑完成，成功 {result['success']} 个，仍失败 {result['extraction_failed']} 个",
        )
        return result

    if payload.get("action") == "reconcile":
        mode = payload.get("reconcile_mode") or "failed"
        await context.set_progress(5.0, "准备修复图谱向量索引")
        reconcile_result = await service.reconcile_vectors(kb_id, all_vectors=mode == "all_vectors")
        result = await service.build_pending_chunks(kb_id, context=context)
        await context.raise_if_cancelled()
        result["reconcile"] = reconcile_result
        await context.set_result(result)
        await context.set_progress(100.0, "图谱向量索引修复完成")
        return result

    await context.set_progress(5.0, "准备构建图谱")
    result = await service.build_pending_chunks(kb_id, context=context)
    await context.raise_if_cancelled()
    await context.set_result(result)
    await context.set_progress(
        100.0,
        f"图谱构建执行完成，成功 {result['success']} 个，抽取失败 {result['extraction_failed']} 个",
    )
    return result
