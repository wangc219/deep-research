"""个人业务资源的全局管理员写入审计。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.permissions import has_global_business_access
from platform_core.services.operation_log_service import log_operation


async def audit_superadmin_personal_resource_write(
    db: AsyncSession,
    *,
    actor: Any,
    action: str,
    resource_type: str,
    resource_id: str,
    owner_uid: str,
) -> None:
    """在业务 owning transaction 中记录全局管理员个人资源写操作。"""

    if not has_global_business_access(actor):
        return
    actor_id = getattr(actor, "id", None)
    if actor_id is None:
        raise RuntimeError("全局管理员写入审计缺少 actor id")

    actor_uid = str(getattr(actor, "uid", "") or "")
    details = json.dumps(
        {
            "audit_stage": "success",
            "action": str(action),
            "actor_uid": actor_uid,
            "actor_role": str(getattr(actor, "role", "") or ""),
            "resource_type": str(resource_type),
            "resource_id": str(resource_id),
            "owner_uid": str(owner_uid),
            "cross_user": actor_uid != str(owner_uid),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    await log_operation(
        db,
        int(actor_id),
        "全局管理员管理个人资源",
        details,
    )
