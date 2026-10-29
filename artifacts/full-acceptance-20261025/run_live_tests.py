"""使用临时验收账号执行真实服务测试，不输出凭据。"""

import asyncio
import os
import secrets
import subprocess
import sys
from uuid import uuid4

from sqlalchemy import select, update

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department, User
from platform_core.utils.auth_utils import AuthUtils


async def create_identity(uid, password):
    """创建只供本轮自动验收使用的账号。"""
    pg_manager.initialize()
    try:
        async with pg_manager.get_async_session_context() as db:
            department_id = await db.scalar(select(Department.id).limit(1))
            if department_id is None:
                raise RuntimeError("验收环境没有部门")
            db.add(User(uid=uid, username=uid, password_hash=AuthUtils.hash_password(password),
                        role="superadmin", department_id=department_id))
            await db.commit()
    finally:
        await pg_manager.close()


async def retire_identity(uid):
    """撤销临时账号，保留测试审计关系。"""
    pg_manager.initialize()
    try:
        async with pg_manager.get_async_session_context() as db:
            await db.execute(update(User).where(User.uid == uid).values(is_deleted=1, password_hash="disabled-acceptance"))
            await db.commit()
    finally:
        await pg_manager.close()


if __name__ == "__main__":
    uid = "acceptance_20261025_" + uuid4().hex[:10]
    password = secrets.token_urlsafe(32)
    asyncio.run(create_identity(uid, password))
    env = dict(os.environ, TEST_USERNAME=uid, TEST_PASSWORD=password,
               E2E_USERNAME=uid, E2E_PASSWORD=password, WORKSPACE_E2E_UID=uid)
    try:
        result = subprocess.run([sys.executable, "-m", "pytest", *sys.argv[1:]], env=env)
    finally:
        asyncio.run(retire_identity(uid))
    raise SystemExit(result.returncode)
