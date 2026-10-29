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
    """所有者和管理员可管理当前数据；旧历史仅超级管理员可读写。"""

    uid = str(getattr(user, "uid", "") or "")
    owner = str(owner_uid or "")
    role = str(getattr(user, "role", "") or "")
    if shared_legacy:
        return ResourcePermission.MANAGE if role == "superadmin" else ResourcePermission.NONE
    if has_global_business_access(user):
        return ResourcePermission.MANAGE
    if uid and owner and uid == owner:
        return ResourcePermission.MANAGE
    return ResourcePermission.NONE


def is_shared_legacy_resource(resource: Any) -> bool:
    """识别融合前导入的公共只读业务数据。"""

    return bool(
        getattr(resource, "legacy_source_id", None)
        or getattr(resource, "import_batch_id", None)
    )
