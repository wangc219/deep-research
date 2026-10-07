"""组织、功能授权及研究调用监控的统一用例。"""

from fastapi import HTTPException
from sqlalchemy import select, text

from platform_core.permissions import has_global_business_access
from platform_core.repositories.department_repository import DepartmentRepository
from platform_core.services.operation_log_service import log_operation
from platform_core.storage.postgres.models_business import Department, User

FEATURES = ("queries", "research", "capabilities", "reports", "favorites", "deep-thinking", "knowledge", "agents")


async def update_tenant(db, tenant_id: str, name: str, *, actor_id: int | None = None) -> dict:
    """在组织锁内更新企业用户名称。"""
    await db.execute(text("SELECT pg_advisory_xact_lock(78324191)"))
    current_name = await db.scalar(text("SELECT name FROM tenants WHERE id=:id FOR UPDATE"), {"id": tenant_id})
    if current_name is None:
        raise HTTPException(404, "企业用户不存在")
    normalized_name = name.strip()
    if not normalized_name:
        raise HTTPException(422, "企业用户名称不能为空")
    duplicate = await db.scalar(
        text("SELECT id FROM tenants WHERE name=:name AND id<>:id"),
        {"name": normalized_name, "id": tenant_id},
    )
    if duplicate:
        raise HTTPException(409, "企业用户名称已存在")
    await db.execute(
        text("UPDATE tenants SET name=:name WHERE id=:id"),
        {"name": normalized_name, "id": tenant_id},
    )
    await log_operation(db, actor_id, "更新企业用户", f"{tenant_id}: {current_name} -> {normalized_name}")
    await db.commit()
    return {"id": tenant_id, "name": normalized_name}


async def delete_tenant(db, tenant_id: str, *, actor_id: int | None = None) -> dict:
    """仅删除没有部门的非默认企业用户。"""
    if tenant_id == "default":
        raise HTTPException(400, "默认企业用户不允许删除")
    await db.execute(text("SELECT pg_advisory_xact_lock(78324191)"))
    name = await db.scalar(text("SELECT name FROM tenants WHERE id=:id FOR UPDATE"), {"id": tenant_id})
    if name is None:
        raise HTTPException(404, "企业用户不存在")
    if await db.scalar(select(Department.id).where(Department.tenant_id == tenant_id).limit(1)):
        raise HTTPException(409, "请先删除或迁移该企业用户下的部门")
    await db.execute(text("DELETE FROM feature_permissions WHERE tenant_id=:id"), {"id": tenant_id})
    await db.execute(text("DELETE FROM tenants WHERE id=:id"), {"id": tenant_id})
    await log_operation(db, actor_id, "删除企业用户", f"{tenant_id}: {name}")
    await db.commit()
    return {"success": True}


async def feature_access(db, user, feature: str) -> dict:
    """用户规则优先于部门规则，部门规则优先于租户规则。"""
    if has_global_business_access(user):
        return {"can_read": True, "can_write": True}
    rows = (
        (
            await db.execute(
                text("""
        SELECT can_read, can_write FROM feature_permissions
        WHERE tenant_id=:tenant AND feature=:feature AND
        ((subject_type='user' AND subject_id=:uid) OR
         (subject_type='department' AND subject_id=:department) OR
         (subject_type='tenant' AND subject_id=:tenant))
        ORDER BY CASE subject_type WHEN 'user' THEN 1 WHEN 'department' THEN 2 ELSE 3 END LIMIT 1
    """),
                {"tenant": user.tenant_id, "feature": feature, "uid": user.uid, "department": str(user.department_id)},
            )
        )
        .mappings()
        .first()
    )
    return dict(rows) if rows else {"can_read": True, "can_write": True}


async def organization(db, user) -> dict:
    """管理员查看其部门子树，超级管理员查看全部组织。"""
    params = {} if user.role == "superadmin" else {"tenant": user.tenant_id}
    tenant_where = "" if user.role == "superadmin" else " WHERE id=:tenant"
    tenants = (
        (await db.execute(text("SELECT id, name FROM tenants" + tenant_where + " ORDER BY name"), params))
        .mappings()
        .all()
    )
    stmt = select(Department).order_by(Department.id)
    if user.role != "superadmin":
        visible_department_ids = (
            await DepartmentRepository(db).list_subtree_ids(user.department_id)
            if user.department_id is not None
            else []
        )
        stmt = stmt.where(Department.id.in_(visible_department_ids))
    departments = (await db.execute(stmt)).scalars().all()
    users_stmt = select(User).where(User.is_deleted == 0)
    if user.role != "superadmin":
        users_stmt = users_stmt.where(User.department_id.in_(visible_department_ids))
    users = (await db.execute(users_stmt)).scalars().all()
    rules_where = "" if user.role == "superadmin" else " WHERE tenant_id=:tenant"
    rules = (
        (await db.execute(text("SELECT * FROM feature_permissions" + rules_where + " ORDER BY id"), params))
        .mappings()
        .all()
    )
    return {
        "tenants": [dict(t) for t in tenants],
        "departments": [d.to_dict() for d in departments],
        "users": [
            {"uid": u.uid, "username": u.username, "role": u.role, "department_id": u.department_id} for u in users
        ],
        "rules": [dict(r) for r in rules],
        "features": list(FEATURES),
    }


async def save_rule(db, values: dict, *, actor_id: int | None = None) -> dict:
    """校验主体归属后在一个事务中保存功能读写规则。"""
    if values["feature"] not in FEATURES:
        raise HTTPException(422, "未知功能")
    if values["can_write"] and not values["can_read"]:
        raise HTTPException(422, "写入权限必须包含读取权限")
    tenant = values["tenant_id"]
    if not await db.scalar(text("SELECT id FROM tenants WHERE id=:id"), {"id": tenant}):
        raise HTTPException(404, "租户不存在")
    kind, subject = values["subject_type"], values["subject_id"]
    if kind == "tenant":
        valid = subject == tenant
    elif kind == "department":
        valid = str(subject).isdigit() and await db.scalar(
            select(Department.id).where(Department.id == int(subject), Department.tenant_id == tenant)
        )
    else:
        valid = await db.scalar(
            select(User.uid)
            .join(Department)
            .where(User.uid == subject, User.is_deleted == 0, Department.tenant_id == tenant)
        )
    if not valid:
        raise HTTPException(422, "授权主体不属于所选租户")
    row = (
        (
            await db.execute(
                text("""
        INSERT INTO feature_permissions (tenant_id, subject_type, subject_id, feature, can_read, can_write)
        VALUES (:tenant_id, :subject_type, :subject_id, :feature, :can_read, :can_write)
        ON CONFLICT (tenant_id, subject_type, subject_id, feature)
        DO UPDATE SET can_read=EXCLUDED.can_read, can_write=EXCLUDED.can_write RETURNING *
    """),
                values,
            )
        )
        .mappings()
        .one()
    )
    await log_operation(db, actor_id, "更新功能权限", f"{tenant}/{kind}/{subject}/{values['feature']}")
    await db.commit()
    return dict(row)


async def set_department_structure(
    db,
    department_id: int,
    tenant_id: str,
    parent_id: int | None,
    *,
    name: str | None = None,
    description: str | None = None,
    actor_id: int | None = None,
):
    """在同一事务中更新部门资料，并防止并发构造循环部门树。"""
    await db.execute(text("SELECT pg_advisory_xact_lock(78324190)"))
    department = await db.get(Department, department_id)
    if department is None:
        raise HTTPException(404, "部门不存在")
    if not await db.scalar(text("SELECT id FROM tenants WHERE id=:id"), {"id": tenant_id}):
        raise HTTPException(404, "租户不存在")
    if department.tenant_id != tenant_id:
        if await db.scalar(select(User.id).where(User.department_id == department_id).limit(1)):
            raise HTTPException(409, "已有成员的部门不能跨租户移动，请新建目标租户部门")
        if await db.scalar(select(Department.id).where(Department.parent_id == department_id).limit(1)):
            raise HTTPException(409, "请先迁移子部门")
    cursor, visited = parent_id, {department_id}
    while cursor is not None:
        if cursor in visited:
            raise HTTPException(422, "部门结构不能形成循环")
        visited.add(cursor)
        parent = await db.get(Department, cursor)
        if parent is None or parent.tenant_id != tenant_id:
            raise HTTPException(422, "上级部门必须属于同一租户")
        cursor = parent.parent_id

    if name is not None:
        normalized_name = name.strip()
        if not normalized_name:
            raise HTTPException(422, "部门名称不能为空")
        duplicate = await db.scalar(
            select(Department.id).where(Department.name == normalized_name, Department.id != department_id)
        )
        if duplicate:
            raise HTTPException(409, "部门名称已存在")
        department.name = normalized_name
    if description is not None:
        department.description = description.strip() or None

    department.tenant_id, department.parent_id = tenant_id, parent_id
    await log_operation(
        db,
        actor_id,
        "更新部门",
        f"部门 {department_id}（{department.name}），租户 {tenant_id}，上级 {parent_id}",
    )
    await db.commit()
    return department.to_dict()


async def monitoring(db, user) -> dict:
    """提供真实 HTTP 调用趋势和当前主机资源指标。"""
    import os
    from pathlib import Path

    where = "created_at >= NOW() - INTERVAL '24 hours'"
    params = {}
    if not has_global_business_access(user):
        where += " AND tenant_id=:tenant"
        params["tenant"] = user.tenant_id
    totals = (
        (
            await db.execute(
                text(f"""SELECT COUNT(*) AS requests,
        COUNT(*) FILTER (WHERE status_code>=400) AS errors,
        COALESCE(AVG(duration_ms),0) AS avg_ms FROM platform_request_metrics WHERE {where}"""),
                params,
            )
        )
        .mappings()
        .one()
    )
    hourly = (
        (
            await db.execute(
                text(f"""SELECT date_trunc('hour',created_at) AT TIME ZONE current_setting('TIMEZONE') AS hour,
        COUNT(*) AS requests, COUNT(*) FILTER (WHERE status_code>=400) AS errors
        FROM platform_request_metrics WHERE {where} GROUP BY 1 ORDER BY 1"""),
                params,
            )
        )
        .mappings()
        .all()
    )
    features = (
        (
            await db.execute(
                text(f"""SELECT feature, COUNT(*) AS requests
        FROM platform_request_metrics WHERE {where} GROUP BY feature ORDER BY requests DESC"""),
                params,
            )
        )
        .mappings()
        .all()
    )
    memory_percent = None
    memory_file = Path("/proc/meminfo")
    if memory_file.exists():
        memory = {line.split(":")[0]: int(line.split()[1]) for line in memory_file.read_text().splitlines()}
        memory_percent = round((1 - memory["MemAvailable"] / memory["MemTotal"]) * 100, 1)
    load = os.getloadavg()[0]
    cores = os.cpu_count() or 1
    return {
        "totals": dict(totals),
        "hourly": [dict(h) for h in hourly],
        "features": [dict(f) for f in features],
        "resources": {
            "load_per_cpu": round(load / cores, 2),
            "memory_percent": memory_percent,
            "load_1m": load,
            "cpu_count": cores,
        },
        "window_hours": 24,
        "metric_kind": "http_requests",
    }
