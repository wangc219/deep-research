"""真实 HTTP 与 PostgreSQL 的扩展授权验证。"""

from uuid import uuid4

import pytest
from sqlalchemy import select, text

from platform_core.agents.context import resolve_agent_resource_options
from platform_core.agents.skills.runtime import resolve_runtime_skills_for_context
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import MCPServer, User
from platform_core.storage_migrations.v077_mcp_access import MCP_ACCESS_SCHEMA_STATEMENTS
from types import SimpleNamespace


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mcp_role_policy_is_persisted_and_applies_to_skill_dependencies(
    test_client, admin_headers, standard_user
):
    """角色限制必须同时约束列表、Agent 可选项与 Skill 间接依赖。"""
    slug = f"pytest-access-{uuid4().hex[:8]}"
    path = f"/api/system/mcp-servers/{slug}"
    headers = standard_user["headers"]
    response = await test_client.post(
        "/api/system/mcp-servers",
        headers=admin_headers,
        json={
            "slug": slug,
            "name": "Pytest role policy",
            "transport": "streamable_http",
            "url": "http://127.0.0.1:9/mcp",
        },
    )
    assert response.status_code == 200, response.text
    skill_slug = f"pytest-access-skill-{uuid4().hex[:8]}"
    skill_md = f"---\nname: {skill_slug}\ndescription: access test\nmcp_dependencies: [{slug}]\n---\n# Test\n"
    prepared = await test_client.post(
        "/api/skills/import/prepare", headers=headers, files={"file": ("SKILL.md", skill_md.encode(), "text/markdown")}
    )
    assert prepared.status_code == 200, prepared.text
    draft = prepared.json()["data"]
    installed = await test_client.post(
        f"/api/skills/personal/install-drafts/{draft['draft_id']}/confirm",
        headers=headers,
        json={"slugs": [skill_slug]},
    )
    assert installed.status_code == 200, installed.text
    pg_manager.initialize()
    try:
        # 新增字段迁移在真实 PostgreSQL 重复执行，不改变已有服务记录。
        async with pg_manager.async_engine.begin() as conn:
            for _ in range(2):
                for statement in MCP_ACCESS_SCHEMA_STATEMENTS:
                    await conn.execute(text(statement))
        policy = {
            "allowed_roles": ["admin", "superadmin"],
            "share_config": {
                "version": 2,
                "read_scope": {"access_level": "global"},
                "manage_scope": None,
            },
        }
        forbidden = await test_client.put(path + "/access-policy", headers=headers, json=policy)
        assert forbidden.status_code == 403, forbidden.text
        saved = await test_client.put(path + "/access-policy", headers=admin_headers, json=policy)
        assert saved.status_code == 200, saved.text
        assert saved.json()["data"]["access_policy"]["allowed_roles"] == ["admin", "superadmin"]
        listed = await test_client.get("/api/system/mcp-servers", headers=headers)
        assert slug not in {s["slug"] for s in listed.json()["data"]}

        async with pg_manager.get_async_session_context() as db:
            user = await db.scalar(select(User).where(User.uid == standard_user["user"]["uid"]))
            server = await db.scalar(select(MCPServer).where(MCPServer.slug == slug))
            assert server.access_policy["allowed_roles"] == ["admin", "superadmin"]
            options = await resolve_agent_resource_options({"mcps"}, db=db, user=user)
            assert slug not in {s["key"] for s in options["mcps"]}
            snapshot = await resolve_runtime_skills_for_context(SimpleNamespace(skills=[skill_slug]), db=db, user=user)
            assert snapshot["runtime_skills"][skill_slug]["mcps"] == []

        # 授权单个用户后列表与运行时选项都应恢复，并且只返回脱敏信息。
        policy["allowed_roles"] = ["user"]
        policy["share_config"]["read_scope"] = {"access_level": "user", "user_uids": [standard_user["user"]["uid"]]}
        saved = await test_client.put(path + "/access-policy", headers=admin_headers, json=policy)
        assert saved.status_code == 200, saved.text
        listed = await test_client.get("/api/system/mcp-servers", headers=headers)
        visible = next(s for s in listed.json()["data"] if s["slug"] == slug)
        assert "headers" not in visible and "url" not in visible
        async with pg_manager.get_async_session_context() as db:
            user = await db.scalar(select(User).where(User.uid == standard_user["user"]["uid"]))
            options = await resolve_agent_resource_options({"mcps"}, db=db, user=user)
            assert slug in {s["key"] for s in options["mcps"]}
            snapshot = await resolve_runtime_skills_for_context(SimpleNamespace(skills=[skill_slug]), db=db, user=user)
            assert snapshot["runtime_skills"][skill_slug]["mcps"] == [slug]
    finally:
        await test_client.delete(f"/api/skills/personal/{skill_slug}", headers=headers)
        await test_client.delete(path, headers=admin_headers)
        await pg_manager.close()
