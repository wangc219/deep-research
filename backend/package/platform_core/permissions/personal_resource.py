"""研究任务、对话等个人业务数据的统一权限策略。"""

from __future__ import annotations

from typing import Any

from platform_core.permissions.resource_permission import ResourcePermission
from platform_core.permissions.roles import has_global_business_access


def resolve_personal_resource_permission(
    user: Any,
    owner_uid: str | None,
    *,
    shared_legacy: bool = False,
) -> ResourcePermission:
    """所有者和全局管理员可管理；融合前历史数据允许普通用户只读。"""

    uid = str(getattr(user, "uid", "") or "")
    owner = str(owner_uid or "")
    if has_global_business_access(user):
        return ResourcePermission.MANAGE
    if uid and owner and uid == owner:
        return ResourcePermission.MANAGE
    if shared_legacy:
        return ResourcePermission.READ
    return ResourcePermission.NONE


def is_shared_legacy_resource(resource: Any) -> bool:
    """识别融合前导入的公共只读业务数据。"""

    return bool(
        getattr(resource, "legacy_source_id", None)
        or getattr(resource, "import_batch_id", None) == "workbench-sync"
    )
