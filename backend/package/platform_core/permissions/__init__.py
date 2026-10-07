"""跨资源权限能力。"""

from platform_core.permissions.personal_resource import (
    is_shared_legacy_resource,
    resolve_personal_resource_permission,
)
from platform_core.permissions.roles import GLOBAL_BUSINESS_ROLES, has_global_business_access
from platform_core.permissions.resource_permission import (
    AGENT_PERMISSION_POLICY,
    KNOWLEDGE_BASE_PERMISSION_POLICY,
    SKILL_PERMISSION_POLICY,
    ResourcePermission,
    ResourcePermissionDenied,
    normalize_permission_config,
    require_knowledge_base_permission,
    require_resource_permission,
    resolve_agent_permission,
    resolve_knowledge_base_permission,
    resolve_resource_permission,
    resolve_skill_permission,
    scope_matches,
)

__all__ = [
    "AGENT_PERMISSION_POLICY",
    "GLOBAL_BUSINESS_ROLES",
    "KNOWLEDGE_BASE_PERMISSION_POLICY",
    "SKILL_PERMISSION_POLICY",
    "ResourcePermission",
    "ResourcePermissionDenied",
    "normalize_permission_config",
    "has_global_business_access",
    "is_shared_legacy_resource",
    "resolve_personal_resource_permission",
    "require_knowledge_base_permission",
    "require_resource_permission",
    "resolve_agent_permission",
    "resolve_knowledge_base_permission",
    "resolve_resource_permission",
    "resolve_skill_permission",
    "scope_matches",
]
