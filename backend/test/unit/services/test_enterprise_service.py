from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from platform_core.services.enterprise_service import delete_tenant, set_department_structure, update_tenant
from platform_core.storage.postgres.models_business import Department


def department(department_id: int, name: str, parent_id: int | None = None) -> Department:
    """构造无需数据库往返的部门测试对象。"""
    return Department(id=department_id, name=name, tenant_id="default", parent_id=parent_id)


@pytest.mark.asyncio
async def test_update_tenant_normalizes_name_and_commits():
    db = MagicMock()
    db.execute = AsyncMock()
    db.scalar = AsyncMock(side_effect=["旧企业", None])
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    result = await update_tenant(db, "tenant-1", "  新企业  ", actor_id=7)

    assert result == {"id": "tenant-1", "name": "新企业"}
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_tenant_requires_empty_non_default_tenant():
    db = MagicMock()
    db.execute = AsyncMock()
    db.scalar = AsyncMock(side_effect=["待删除企业", None])
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    assert await delete_tenant(db, "tenant-1", actor_id=7) == {"success": True}
    db.commit.assert_awaited_once()

    with pytest.raises(HTTPException, match="默认企业用户不允许删除"):
        await delete_tenant(db, "default", actor_id=7)


@pytest.mark.asyncio
async def test_update_department_profile_and_parent_in_one_transaction():
    db = MagicMock()
    db.execute = AsyncMock()
    db.scalar = AsyncMock(side_effect=["default", None])
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    current = department(2, "旧名称")
    parent = department(3, "上级部门")
    db.get = AsyncMock(side_effect=lambda _model, item_id: {2: current, 3: parent}.get(item_id))

    result = await set_department_structure(
        db,
        2,
        "default",
        3,
        name="  新名称  ",
        description="  新说明  ",
        actor_id=7,
    )

    assert result["name"] == "新名称"
    assert result["description"] == "新说明"
    assert result["parent_id"] == 3
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_department_rejects_descendant_as_parent():
    db = MagicMock()
    db.execute = AsyncMock()
    db.scalar = AsyncMock(return_value="default")
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    current = department(2, "当前部门")
    child = department(3, "下级部门", parent_id=2)
    db.get = AsyncMock(side_effect=lambda _model, item_id: {2: current, 3: child}.get(item_id))

    with pytest.raises(HTTPException, match="部门结构不能形成循环"):
        await set_department_structure(db, 2, "default", 3, actor_id=7)

    db.commit.assert_not_awaited()
