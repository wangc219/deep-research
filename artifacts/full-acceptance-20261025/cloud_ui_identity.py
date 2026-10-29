"""生成或撤销本轮临时浏览器验收身份；stdout 只允许传给私有状态文件。"""
import asyncio, json, os, secrets
from uuid import uuid4
from sqlalchemy import select,update
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department,User
from platform_core.utils.auth_utils import AuthUtils

async def main():
    """保留审计关系并在结束时禁用登录。"""
    pg_manager.initialize()
    try:
        async with pg_manager.get_async_session_context() as db:
            retire=os.getenv('ACCEPTANCE_RETIRE_UID')
            if retire:
                assert retire.startswith('browser_acceptance_')
                await db.execute(update(User).where(User.uid==retire).values(is_deleted=1,password_hash='disabled-acceptance'))
                await db.commit()
                print(json.dumps({'browser_identity_retired':True}));return
            uid='browser_acceptance_'+uuid4().hex[:12]
            password=secrets.token_urlsafe(32)
            department=await db.scalar(select(Department.id).limit(1))
            db.add(User(uid=uid,username=uid,password_hash=AuthUtils.hash_password(password),role='superadmin',department_id=department))
            await db.commit()
            print(json.dumps({'uid':uid,'password':password}))
    finally:
        await pg_manager.close()
asyncio.run(main())
