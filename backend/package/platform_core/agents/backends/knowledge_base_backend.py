from __future__ import annotations

from typing import Any


async def resolve_visible_knowledge_bases_for_context(context) -> list[dict[str, Any]]:
    from platform_core.services.knowledge_retrieval_service import list_visible_knowledge_bases

    uid = getattr(context, "uid", None)
    if not uid:
        setattr(context, "_visible_knowledge_bases", [])
        return []

    databases = await list_visible_knowledge_bases(uid, enabled_ids=getattr(context, "knowledges", None))

    setattr(context, "_visible_knowledge_bases", databases)
    return databases
