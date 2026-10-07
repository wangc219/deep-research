"""企业管理 HTTP 入口。"""

from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from platform_core.repositories.department_repository import DepartmentRepository
from platform_core.services import enterprise_service as svc
from platform_core.services.operation_log_service import log_operation
from server.utils.auth_middleware import get_admin_user, get_db, get_required_user, get_superadmin_user

enterprise = APIRouter(prefix="/enterprise", tags=["enterprise"])


class TenantCreate(BaseModel):
    """创建租户。"""

    name: str = Field(min_length=1, max_length=100)


class TenantUpdate(BaseModel):
    """更新企业用户。"""

    name: str = Field(min_length=1, max_length=100)


class RuleCreate(BaseModel):
    """功能授权规则。"""

    tenant_id: str
    subject_type: Literal["tenant", "department", "user"]
    subject_id: str
    feature: str
    can_read: bool = True
    can_write: bool = True


class DepartmentStructure(BaseModel):
    """部门资料与组织位置。"""

    tenant_id: str
    parent_id: int | None = None
    name: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=255)


@enterprise.get("/organization")
async def organization(user=Depends(get_admin_user), db=Depends(get_db)):
    """读取可管理组织。"""
    return await svc.organization(db, user)


@enterprise.post("/tenants", status_code=201)
async def create_tenant(body: TenantCreate, user=Depends(get_superadmin_user), db=Depends(get_db)):
    """创建独立企业租户。"""
    values = {"id": uuid4().hex, "name": body.name.strip()}
    if not values["name"]:
        raise HTTPException(422, "租户名称不能为空")
    try:
        await db.execute(text("INSERT INTO tenants(id,name) VALUES (:id,:name)"), values)
        await log_operation(db, user.id, "创建租户", values["name"])
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "租户名称已存在") from exc
    return values


@enterprise.put("/tenants/{tenant_id}")
async def update_tenant(tenant_id: str, body: TenantUpdate, user=Depends(get_superadmin_user), db=Depends(get_db)):
    """修改企业用户名称。"""
    return await svc.update_tenant(db, tenant_id, body.name, actor_id=user.id)


@enterprise.delete("/tenants/{tenant_id}")
async def delete_tenant(tenant_id: str, user=Depends(get_superadmin_user), db=Depends(get_db)):
    """删除没有部门的非默认企业用户。"""
    return await svc.delete_tenant(db, tenant_id, actor_id=user.id)


@enterprise.put("/departments/{department_id}")
async def structure(department_id: int, body: DepartmentStructure, user=Depends(get_admin_user), db=Depends(get_db)):
    """统一更新部门资料与层级。"""
    tenant_id = body.tenant_id
    if user.role != "superadmin":
        repository = DepartmentRepository(db)
        if user.department_id is None:
            raise HTTPException(403, "当前管理员未绑定部门")
        visible_department_ids = set(await repository.list_subtree_ids(user.department_id))
        if department_id not in visible_department_ids:
            raise HTTPException(403, "只能管理本部门或下级部门")
        current = await repository.get_by_id(department_id)
        if current is None:
            raise HTTPException(404, "部门不存在")
        if department_id == user.department_id:
            if body.parent_id != current.parent_id:
                raise HTTPException(403, "不能调整当前管理员所属部门的上级部门")
        elif body.parent_id is None or body.parent_id not in visible_department_ids:
            raise HTTPException(403, "下级部门只能移动到可管理的部门子树内")
        tenant_id = user.tenant_id

    return await svc.set_department_structure(
        db,
        department_id,
        tenant_id,
        body.parent_id,
        name=body.name,
        description=body.description,
        actor_id=user.id,
    )


@enterprise.put("/permissions")
async def save_rule(body: RuleCreate, user=Depends(get_superadmin_user), db=Depends(get_db)):
    """保存明确的功能读写权限。"""
    return await svc.save_rule(db, body.model_dump(), actor_id=user.id)


@enterprise.delete("/permissions/{rule_id}")
async def delete_rule(rule_id: int, user=Depends(get_superadmin_user), db=Depends(get_db)):
    """删除覆盖规则并恢复继承。"""
    await db.execute(text("DELETE FROM feature_permissions WHERE id=:id"), {"id": rule_id})
    await log_operation(db, user.id, "删除功能权限", f"规则 {rule_id}")
    await db.commit()
    return {"success": True}


@enterprise.get("/permissions/me")
async def my_permissions(user=Depends(get_required_user), db=Depends(get_db)):
    """返回当前用户实际功能权限。"""
    return {feature: await svc.feature_access(db, user, feature) for feature in svc.FEATURES}


@enterprise.get("/monitoring")
async def monitoring(user=Depends(get_admin_user), db=Depends(get_db)):
    """查看本租户或全局运行指标。"""
    return await svc.monitoring(db, user)
