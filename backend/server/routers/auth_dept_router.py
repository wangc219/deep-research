"""
部门管理路由
提供部门的增删改查接口，部门管理员可管理自己的部门子树
"""

import re

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.repositories.department_repository import DepartmentRepository
from platform_core.repositories.user_repository import UserRepository
from platform_core.services.identity_admin_service import IdentityConflictError, create_department_identity
from platform_core.services.operation_log_service import log_operation
from platform_core.services.user_identity_service import is_valid_phone_number
from platform_core.storage.postgres.models_business import Department, User
from server.utils.auth_middleware import get_admin_user, get_db

# 创建路由器
department = APIRouter(prefix="/departments", tags=["department"])


# =============================================================================
# === 请求和响应模型 ===
# =============================================================================


class DepartmentCreate(BaseModel):
    """创建部门请求"""

    name: str
    description: str | None = None
    tenant_id: str = "default"
    parent_id: int | None = None
    admin_uid: str | None = None
    admin_password: str | None = Field(default=None, min_length=8)
    admin_phone: str | None = None


class DepartmentUpdate(BaseModel):
    """更新部门请求"""

    name: str | None = None
    description: str | None = None


class DepartmentResponse(BaseModel):
    """部门响应"""

    id: int
    name: str
    description: str | None = None
    created_at: str
    user_count: int = 0
    tenant_id: str = "default"
    parent_id: int | None = None


# =============================================================================
# === 部门管理路由 ===
# =============================================================================


async def _managed_department_ids(repository: DepartmentRepository, current_user: User) -> set[int]:
    """返回当前管理员可管理的部门子树。"""
    if current_user.role == "superadmin":
        return set()
    if current_user.department_id is None:
        return set()
    return set(await repository.list_subtree_ids(current_user.department_id))


async def _ensure_department_managed(
    repository: DepartmentRepository,
    current_user: User,
    department_id: int,
) -> None:
    """拒绝部门管理员访问自己部门子树之外的部门。"""
    if current_user.role == "superadmin":
        return
    if department_id not in await _managed_department_ids(repository, current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能管理本部门或下级部门")


@department.get("", response_model=list[DepartmentResponse])
async def get_departments(current_user: User = Depends(get_admin_user), db: AsyncSession = Depends(get_db)):
    """获取所有部门列表（管理员可访问）"""
    dept_repo = DepartmentRepository(db)
    rows = await dept_repo.list_with_user_count()
    if current_user.role != "superadmin":
        visible = await _managed_department_ids(dept_repo, current_user)
        rows = [row for row in rows if row["id"] in visible]
    return rows


@department.get("/{department_id}", response_model=DepartmentResponse)
async def get_department(
    department_id: int,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """获取指定部门详情"""
    repository = DepartmentRepository(db)
    await _ensure_department_managed(repository, current_user, department_id)
    department = await repository.get_with_user_count(department_id)
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="部门不存在")
    return department


@department.post("", response_model=DepartmentResponse, status_code=status.HTTP_201_CREATED)
async def create_department(
    department_data: DepartmentCreate,
    request: Request,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """创建新部门，并可由超级管理员同时创建部门管理员。"""
    dept_repo = DepartmentRepository(db)
    user_repo = UserRepository(db)

    tenant_id = department_data.tenant_id
    parent_id = department_data.parent_id
    if current_user.role != "superadmin":
        if department_data.admin_uid or department_data.admin_password or department_data.admin_phone:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="部门管理员不能创建其他管理员账户",
            )
        if current_user.department_id is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前管理员未绑定部门")
        parent_id = parent_id or current_user.department_id
        if parent_id not in await _managed_department_ids(dept_repo, current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="只能在本部门或下级部门下新建部门",
            )
        tenant_id = current_user.tenant_id

    # 检查部门名称是否已存在
    if await dept_repo.exists_by_name(department_data.name):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="部门名称已存在")

    if bool(department_data.admin_uid) != bool(department_data.admin_password):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="管理员登录 ID 和初始密码必须同时填写"
        )
    if department_data.admin_phone and not department_data.admin_uid:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="填写手机号时必须同时创建管理员")

    # 验证可选管理员 uid 格式
    admin_uid = department_data.admin_uid
    if admin_uid and not re.match(r"^[a-zA-Z0-9_]+$", admin_uid):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户ID只能包含字母、数字和下划线",
        )

    if admin_uid and (len(admin_uid) < 3 or len(admin_uid) > 20):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户ID长度必须在3-20个字符之间",
        )

    # 检查 uid 是否已存在
    if admin_uid and await user_repo.exists_by_uid(admin_uid):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户ID已存在",
        )

    # 检查手机号是否已存在（如果提供了）
    admin_phone = department_data.admin_phone
    if admin_phone:
        if not is_valid_phone_number(admin_phone):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="手机号格式不正确")
        if await user_repo.exists_by_phone(admin_phone):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="手机号已存在",
            )

    try:
        created = await create_department_identity(
            db,
            name=department_data.name,
            tenant_id=tenant_id,
            parent_id=parent_id,
            description=department_data.description,
            admin_uid=admin_uid,
            admin_password=department_data.admin_password,
            admin_phone=admin_phone,
            actor_user_id=current_user.id,
            request=request,
        )
    except IdentityConflictError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return {**created.department.to_dict(), "user_count": 1 if created.admin else 0}


@department.put("/{department_id}", response_model=DepartmentResponse)
async def update_department(
    department_id: int,
    department_data: DepartmentUpdate,
    request: Request,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """更新部门信息"""
    repository = DepartmentRepository(db)
    await _ensure_department_managed(repository, current_user, department_id)
    department = await repository.get_by_id(department_id)

    if not department:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="部门不存在")

    updates = {}
    # 如果要修改名称，检查新名称是否已存在
    if department_data.name and department_data.name != department.name:
        existing = await repository.get_by_name(department_data.name)
        if existing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="部门名称已存在")
        updates["name"] = department_data.name

    if department_data.description is not None:
        updates["description"] = department_data.description

    department = await repository.update(department_id, updates)
    if department is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="部门不存在")

    # 记录操作
    await log_operation(db, current_user.id, "更新部门", f"更新部门: {department.name}", request)

    # 获取部门下用户数量
    user_count = await repository.count_users(department_id)
    await db.commit()

    return {**department.to_dict(), "user_count": user_count}


@department.delete("/{department_id}", status_code=status.HTTP_200_OK)
async def delete_department(
    department_id: int,
    request: Request,
    current_user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """删除部门"""
    repository = DepartmentRepository(db)
    await _ensure_department_managed(repository, current_user, department_id)
    # 检查部门是否存在
    department = await repository.get_by_id(department_id)

    if not department:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="部门不存在")

    if department.id == 1:  # 默认部门的ID为1
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="默认部门不允许删除")

    if await db.scalar(select(Department.id).where(Department.parent_id == department_id).limit(1)):
        raise HTTPException(status_code=409, detail="请先移动或删除子部门")
    if current_user.role != "superadmin":
        if department_id == current_user.department_id:
            raise HTTPException(status_code=400, detail="不能删除当前管理员所属部门")
        if await repository.count_users(department_id):
            raise HTTPException(status_code=409, detail="请先将部门成员迁移到可管理的其他部门")
    if department.tenant_id != "default" and await repository.count_users(department_id):
        raise HTTPException(status_code=409, detail="请先将成员迁移到同租户的其他部门")
    deletion = await repository.delete_and_migrate_users(department_id)
    if deletion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="部门不存在")

    # 记录操作
    if deletion.migrated_user_count:
        detail = f"删除部门: {deletion.name}，迁移 {deletion.migrated_user_count} 个用户到默认部门"
    else:
        detail = f"删除部门: {deletion.name}"
    await log_operation(db, current_user.id, "删除部门", detail, request)
    await db.commit()

    return {"success": True, "message": "部门已删除"}
