"""共享知识库检索用例，不依赖聊天运行时或具体研究领域。"""

import asyncio
from collections.abc import Sequence
from typing import Any


async def list_visible_knowledge_bases(
    uid: str | None,
    *,
    enabled_ids: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """将用户资源权限与本次启用范围取交集；空列表表示不启用知识库。"""
    if not uid:
        return []
    from platform_core.knowledge.runtime import knowledge_base

    summaries = await knowledge_base.get_databases_by_uid(str(uid))
    enabled = None if enabled_ids is None else {str(value).strip() for value in enabled_ids if str(value).strip()}
    return [
        {"kb_id": item.kb_id, "name": item.name, "description": item.description, "kb_type": item.kb_type}
        for item in summaries
        if enabled is None or item.kb_id in enabled
    ]


def find_query_target(*, kb_id: str, visible_kbs: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """仅解析服务端授权视图中的 ID；调用者不能用请求正文构造授权视图。"""
    if not visible_kbs:
        return None, "无法获取当前会话可访问的知识库"
    normalized = str(kb_id or "").strip()
    if normalized not in {str(item.get("kb_id") or "").strip() for item in visible_kbs}:
        return None, f"知识库资源 '{normalized}' 不存在或当前会话未启用"
    return normalized, None


async def retrieve_visible_knowledge(
    *,
    kb_id: str,
    query_text: str,
    visible_kbs: list[dict[str, Any]],
    file_name: str | None = None,
) -> Any:
    """复用平台检索管线及引用格式，授权失败时不调用嵌入或重排模型。"""
    target_id, error = find_query_target(kb_id=kb_id, visible_kbs=visible_kbs)
    if error:
        raise PermissionError(error)
    from platform_core.knowledge.runtime import knowledge_base

    kwargs = {"file_name": file_name} if file_name else {}
    return await knowledge_base.retrieve(target_id, query_text, **kwargs)


async def retrieve_visible_knowledge_batch(
    *,
    uid: str | None,
    query_text: str,
    enabled_ids: Sequence[str] | None = None,
    max_knowledge_bases: int = 6,
    concurrency: int = 3,
) -> dict[str, Any]:
    """对授权知识库执行有界并行检索，并保留每个来源的引用结构。

    该批量用例供研究、评估等非聊天入口复用。资源范围始终由服务端按
    ``uid`` 重新解析，请求中的 ``enabled_ids`` 只能收窄范围；单个知识库
    故障会进入 ``failures``，不会抹掉其他知识库已经返回的证据。
    """
    normalized_query = str(query_text or "").strip()
    if not normalized_query:
        raise ValueError("知识库检索问题不能为空")
    if max_knowledge_bases < 1:
        raise ValueError("max_knowledge_bases 必须大于 0")
    if concurrency < 1:
        raise ValueError("concurrency 必须大于 0")

    visible_kbs = await list_visible_knowledge_bases(uid, enabled_ids=enabled_ids)
    selected_kbs = visible_kbs[:max_knowledge_bases]
    semaphore = asyncio.Semaphore(min(concurrency, max_knowledge_bases))

    async def retrieve_one(item: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        async with semaphore:
            try:
                result = await retrieve_visible_knowledge(
                    kb_id=str(item["kb_id"]),
                    query_text=normalized_query,
                    visible_kbs=visible_kbs,
                )
            except Exception as exc:  # 单库降级；取消仍由 asyncio.CancelledError 向上传播。
                return (
                    "failure",
                    {
                        "kb_id": str(item["kb_id"]),
                        "name": str(item.get("name") or ""),
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:500],
                    },
                )
            return (
                "retrieval",
                {
                    "kb_id": str(item["kb_id"]),
                    "name": str(item.get("name") or ""),
                    "description": item.get("description"),
                    "kb_type": str(item.get("kb_type") or ""),
                    "result": result,
                },
            )

    rows = await asyncio.gather(*(retrieve_one(item) for item in selected_kbs))
    retrievals = [payload for kind, payload in rows if kind == "retrieval"]
    failures = [payload for kind, payload in rows if kind == "failure"]
    return {
        "query": normalized_query,
        "visible_count": len(visible_kbs),
        "selected_count": len(selected_kbs),
        "omitted_count": max(0, len(visible_kbs) - len(selected_kbs)),
        "retrievals": retrievals,
        "failures": failures,
    }
