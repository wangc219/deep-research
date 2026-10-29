"""为跨容器重启的验收创建临时身份；stdout 仅能交给本机私有状态文件。"""

import asyncio
from datetime import timedelta
import json
import os
from uuid import uuid4

from sqlalchemy import select, update

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department, User
from platform_core.utils.auth_utils import AuthUtils


async def main():
    """创建临时账号或撤销本脚本生成的账号，不打印密钥到验收日志。"""
    pg_manager.initialize()
    try:
        async with pg_manager.get_async_session_context() as db:
            retire = os.getenv('ACCEPTANCE_RETIRE_UID')
            if retire:
                assert retire.startswith('persistence_acceptance_')
                await db.execute(update(User).where(User.uid == retire).values(is_deleted=1, password_hash='disabled-test'))
                await db.commit()
                print(json.dumps({'temporary_identity_retired': True}))
                return
            uid = 'persistence_acceptance_' + uuid4().hex[:12]
            department = await db.scalar(select(Department.id).limit(1))
            user = User(uid=uid, username=uid, password_hash='disabled-test-login', role='superadmin', department_id=department)
            db.add(user)
            await db.flush()
            token = AuthUtils.create_access_token({'sub': str(user.id)}, expires_delta=timedelta(hours=2))
            await db.commit()
            print(json.dumps({'uid': uid, 'token': token}))
    finally:
        await pg_manager.close()


asyncio.run(main())
