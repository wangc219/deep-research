"""组织与初始身份管理用例的事务 Owner。"""

from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from platform_core.repositories.department_repository import DepartmentRepository
from platform_core.repositories.user_repository import UserRepository
from platform_core.services.operation_log_service import log_operation
from platform_core.services.user_identity_service import generate_unique_uid
from platform_core.storage.postgres.models_business import Department, User
from platform_core.utils.auth_utils import AuthUtils
from platform_core.utils.datetime_utils import utc_now_naive

_INITIALIZATION_LOCK_KEY = 0x59555849


class IdentityConflictError(Exception):
    """唯一身份或部门事实在提交时发生冲突。"""


class SystemAlreadyInitializedError(Exception):
    """系统初始化已由当前或并发请求完成。"""


class RegistrationUnavailableError(Exception):
    """系统组织基础数据尚不支持用户自助注册。"""


@dataclass(frozen=True)
class DepartmentAdminCreation:
    """同一事务创建的部门和管理员。"""

    department: Department
    admin: User


@dataclass(frozen=True)
class DepartmentCreation:
    """同一事务创建的部门及可选管理员。"""

    department: Department
    admin: User | None


async def register_public_user(
    db: AsyncSession,
    *,
    username: str,
    password: str,
    phone_number: str | None,
    department_id: int | None = None,
    request: Request | None = None,
) -> User:
    """在现有组织与权限模型内注册普通用户。

    自助注册可进入已存在的所选部门并固定为 user 角色；未指定时兼容进入默认部门。
    用户、审计与部门关系由同一个事务提交，之后继续由管理员界面治理。
    """

    try:
        department_repository = DepartmentRepository(db)
        department = (
            await department_repository.get_by_id(department_id)
            if department_id is not None
            else await department_repository.get_by_name("默认部门")
        )
        if department is None:
            raise RegistrationUnavailableError("所选部门不存在或系统尚未完成初始化")

        user_repository = UserRepository(db)
        existing_uids = await user_repository.get_all_uids()
        user = await user_repository.create(
            {
                "username": username,
                "uid": generate_unique_uid(username, existing_uids),
                "phone_number": phone_number,
                "avatar": None,
                "password_hash": AuthUtils.hash_password(password),
                "role": "user",
                "department_id": department.id,
                "last_login": utc_now_naive(),
            }
        )
        await log_operation(db, user.id, "用户自助注册", f"注册普通用户: {user.uid}", request)
        await db.commit()
        return user
    except IntegrityError as exc:
        await db.rollback()
        raise IdentityConflictError("用户名或手机号已存在") from exc
    except Exception:
        await db.rollback()
        raise


async def list_managed_users_page(
    db: AsyncSession,
    *,
    offset: int,
    limit: int,
    is_superadmin: bool,
    visible_department_ids: list[int] | None,
    department_id: int | None,
    role: str | None,
    search: str | None,
) -> dict:
    """返回管理员可见范围内的用户分页。"""
    if is_superadmin:
        effective_department_id = department_id
        effective_department_ids = None
    elif department_id is not None:
        effective_department_id = None
        effective_department_ids = [department_id] if department_id in (visible_department_ids or []) else []
    else:
        effective_department_id = None
        effective_department_ids = visible_department_ids or []
    if not is_superadmin and not effective_department_ids:
        return {"items": [], "total": 0, "limit": limit, "offset": offset}
    rows, total = await UserRepository(db).list_page_with_department(
        offset=offset,
        limit=limit,
        department_id=effective_department_id,
        department_ids=effective_department_ids,
        role=role,
        search=search,
    )
    items = []
    for user, department_name in rows:
        item = user.to_dict()
        item["department_name"] = department_name
        items.append(item)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


async def create_department_with_admin(
    db: AsyncSession,
    *,
    name: str,
    description: str | None,
    admin_uid: str,
    admin_password: str,
    admin_phone: str | None,
    actor_user_id: int,
    tenant_id: str = "default",
    parent_id: int | None = None,
    request: Request | None = None,
) -> DepartmentAdminCreation:
    """原子创建部门、首位管理员和强制审计事实。"""

    created = await create_department_identity(
        db,
        name=name,
        description=description,
        admin_uid=admin_uid,
        admin_password=admin_password,
        admin_phone=admin_phone,
        actor_user_id=actor_user_id,
        tenant_id=tenant_id,
        parent_id=parent_id,
        request=request,
    )
    if created.admin is None:
        raise RuntimeError("管理员创建结果缺失")
    return DepartmentAdminCreation(department=created.department, admin=created.admin)


async def create_department_identity(
    db: AsyncSession,
    *,
    name: str,
    description: str | None,
    actor_user_id: int,
    tenant_id: str = "default",
    parent_id: int | None = None,
    admin_uid: str | None = None,
    admin_password: str | None = None,
    admin_phone: str | None = None,
    request: Request | None = None,
) -> DepartmentCreation:
    """原子创建部门，并按需创建首位管理员。"""

    await db.execute(text("SELECT pg_advisory_xact_lock(78324190)"))
    if not await db.scalar(text("SELECT id FROM tenants WHERE id=:id"), {"id": tenant_id}):
        raise IdentityConflictError("租户不存在")
    if parent_id is not None:
        parent = await db.get(Department, parent_id)
        if parent is None or parent.tenant_id != tenant_id:
            raise IdentityConflictError("上级部门必须属于同一租户")
    if bool(admin_uid) != bool(admin_password):
        raise IdentityConflictError("管理员登录 ID 和初始密码必须同时填写")
    password_hash = AuthUtils.hash_password(admin_password) if admin_password else None
    try:
        try:
            department = await DepartmentRepository(db).create(
                {
                    "name": name,
                    "description": description,
                    "tenant_id": tenant_id,
                    "parent_id": parent_id,
                }
            )
            admin = None
            if admin_uid and password_hash:
                admin = await UserRepository(db).create(
                    {
                        "username": admin_uid,
                        "uid": admin_uid,
                        "phone_number": admin_phone,
                        "password_hash": password_hash,
                        "role": "admin",
                        "department_id": department.id,
                    }
                )
        except IntegrityError as exc:
            raise IdentityConflictError("部门名称、管理员用户ID、用户名或手机号已存在") from exc

        detail = f"创建部门: {name}"
        if admin_uid:
            detail += f"，并创建管理员: {admin_uid}"
        await log_operation(db, actor_user_id, "创建部门", detail, request)
        await db.commit()
        return DepartmentCreation(department=department, admin=admin)
    except Exception:
        await db.rollback()
        raise


async def initialize_system_admin(
    db: AsyncSession,
    *,
    uid: str,
    password: str,
    phone_number: str | None,
) -> DepartmentAdminCreation:
    """串行、原子地创建默认部门、超级管理员和初始化审计。"""

    password_hash = AuthUtils.hash_password(password)
    try:
        bind = db.get_bind()
        if bind.dialect.name == "postgresql":
            await db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": _INITIALIZATION_LOCK_KEY})

        if not await UserRepository(db).is_first_run():
            raise SystemAlreadyInitializedError("系统已经初始化，无法再次创建初始管理员")

        try:
            department = await DepartmentRepository(db).create(
                {
                    "name": "默认部门",
                    "description": "系统初始化时创建的默认部门",
                }
            )
            admin = await UserRepository(db).create(
                {
                    "username": uid,
                    "uid": uid,
                    "phone_number": phone_number,
                    "avatar": None,
                    "password_hash": password_hash,
                    "role": "superadmin",
                    "department_id": department.id,
                    "last_login": utc_now_naive(),
                }
            )
        except IntegrityError as exc:
            raise IdentityConflictError("初始化身份事实与现有数据库约束冲突") from exc

        await log_operation(db, admin.id, "系统初始化", "创建超级管理员账户")
        await db.commit()
        return DepartmentAdminCreation(department=department, admin=admin)
    except SystemAlreadyInitializedError:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise
