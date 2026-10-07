"""平台角色的统一权限语义。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


GLOBAL_BUSINESS_ROLES = frozenset({"admin", "superadmin"})


def has_global_business_access(user: Any) -> bool:
    """管理员与超级管理员可跨用户管理业务资源。"""

    role = user.get("role") if isinstance(user, Mapping) else getattr(user, "role", None)
    return str(role or "") in GLOBAL_BUSINESS_ROLES
