from unittest.mock import AsyncMock, Mock

import pytest

from platform_core.agents.skills.repository import SkillRepository
from platform_core.storage.postgres.models_business import Skill


@pytest.mark.asyncio
async def test_skill_repository_flushes_without_committing() -> None:
    db = Mock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    db.commit = AsyncMock()

    item = await SkillRepository(db).create(
        slug="demo",
        name="Demo",
        description="demo",
        source_type="upload",
        tool_dependencies=[],
        mcp_dependencies=[],
        skill_dependencies=[],
        dir_path="shared/demo",
        share_config={"version": 2, "read_scope": None, "manage_scope": None},
        created_by="user-1",
    )

    db.add.assert_called_once_with(item)
    db.flush.assert_awaited_once()
    db.refresh.assert_awaited_once_with(item)
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_builtin_sync_preserves_administrator_role_restrictions() -> None:
    """升级内置 Skill 内容不能重置管理员已保存的运行权限。"""
    db = Mock(flush=AsyncMock(), refresh=AsyncMock())
    skill = Skill(slug="demo", share_config={"version": 2, "allowed_roles": ["admin"]})
    await SkillRepository(db).update_builtin_install(skill, version="v2", content_hash="new", updated_by="system")
    assert skill.share_config["allowed_roles"] == ["admin"]
    assert skill.share_config["read_scope"]["access_level"] == "global"
