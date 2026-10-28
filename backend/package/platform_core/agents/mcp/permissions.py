"""MCP 使用范围：角色与共享范围同时满足才允许挂载。"""

from platform_core.permissions import normalize_permission_config, scope_matches

MCP_ROLES = frozenset({"user", "admin", "superadmin"})


def normalize_mcp_access_policy(policy: dict | None) -> dict:
    """校验角色与使用范围，兼容既有全局 MCP。"""
    value = policy or {}
    roles = value.get("allowed_roles", sorted(MCP_ROLES))
    if not isinstance(roles, list) or any(role not in MCP_ROLES for role in roles):
        raise ValueError("MCP 角色必须是 user、admin 或 superadmin")
    share = value.get("share_config") or {
        "version": 2,
        "read_scope": {"access_level": "global", "department_ids": [], "user_uids": []},
        "manage_scope": None,
    }
    return {"allowed_roles": sorted(set(roles)), "share_config": normalize_permission_config(share, strict=True)}


def user_can_use_mcp(user, server) -> bool:
    """仅授权角色与使用范围内的用户可以加载服务，包括 Skill 间接依赖。"""
    policy = normalize_mcp_access_policy(getattr(server, "access_policy", None))
    return user.role in policy["allowed_roles"] and scope_matches(user, policy["share_config"]["read_scope"])
