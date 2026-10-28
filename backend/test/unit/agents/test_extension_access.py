"""扩展使用权限与依赖闭包的回归测试。"""

from types import SimpleNamespace

import pytest

from platform_core.agents.mcp.permissions import normalize_mcp_access_policy, user_can_use_mcp
from platform_core.agents.skills.runtime import build_dependency_bundle, resolve_runtime_skills_for_context


def test_mcp_requires_both_role_and_scope():
    """被允许的角色仍然必须属于指定部门，空角色列表禁用所有调用。"""
    policy = {
        "allowed_roles": ["user"],
        "share_config": {
            "version": 2,
            "read_scope": {"access_level": "department", "department_ids": [8]},
            "manage_scope": None,
        },
    }
    server = SimpleNamespace(access_policy=policy)
    assert user_can_use_mcp(SimpleNamespace(role="user", department_id=8), server)
    assert not user_can_use_mcp(SimpleNamespace(role="admin", department_id=8), server)
    assert not user_can_use_mcp(SimpleNamespace(role="user", department_id=9), server)
    policy["allowed_roles"] = []
    assert not user_can_use_mcp(SimpleNamespace(role="user", department_id=8), server)
    with pytest.raises(ValueError):
        normalize_mcp_access_policy({"allowed_roles": ["owner"]})


def test_activated_skill_opens_transitive_dependencies():
    """一次激活根 Skill 即可打开嵌套依赖，循环不重复加载。"""
    skills = {
        "root": {"tools": ["search"], "mcps": [], "skills": ["child"]},
        "child": {"tools": ["query"], "mcps": ["papers"], "skills": ["root"]},
    }
    assert build_dependency_bundle(["root"], skills) == {"tools": ["search", "query"], "mcps": ["papers"]}


@pytest.mark.asyncio
async def test_skill_cannot_bypass_mcp_policy(monkeypatch):
    """即使 Skill 自己声明了 MCP，当前身份无权使用时也不会进入运行快照。"""

    async def accessible(_db, _user):
        return [
            SimpleNamespace(
                slug="test",
                name="test",
                description="test",
                source_scope="personal",
                version=None,
                content_hash=None,
                tool_dependencies=[],
                skill_dependencies=[],
                mcp_dependencies=["private", "public"],
            )
        ]

    async def servers(_db):
        return [
            SimpleNamespace(slug="public", enabled=True, access_policy=None),
            SimpleNamespace(slug="private", enabled=True, access_policy={"allowed_roles": ["admin"]}),
        ]

    monkeypatch.setattr("platform_core.agents.skills.runtime.list_accessible_skills", accessible)
    monkeypatch.setattr("platform_core.agents.mcp.service.get_all_mcp_servers", servers)
    snapshot = await resolve_runtime_skills_for_context(
        SimpleNamespace(skills=["test"]),
        db=object(),
        user=SimpleNamespace(role="user"),
    )
    assert snapshot["runtime_skills"]["test"]["mcps"] == ["public"]
