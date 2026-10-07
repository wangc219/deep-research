"""真实 HTTP 验证原生深研会话的全局只读查看与用户隔离。"""

from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select, text

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Conversation, Department, Project, User
from platform_core.storage.postgres.models_equipment import EquipmentDeepSession
from platform_core.utils.auth_utils import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_native_deep_session_owner_and_global_read_access():
    """只创建隔离的会话元数据，不启动模型或写入用户工作区。"""
    pg_manager.initialize()
    marker = "deep_read_" + uuid4().hex[:12]
    project_id, session_id, thread_id = (str(uuid4()) for _ in range(3))
    uids = [marker + suffix for suffix in ("owner", "other", "root")]
    headers = []
    try:
        async with pg_manager.get_async_session_context() as db:
            department_id = await db.scalar(select(Department.id).limit(1))
            for index, uid in enumerate(uids):
                user = User(
                    uid=uid, username=uid, password_hash="disabled-test-login",
                    role="superadmin" if index == 2 else "user", department_id=department_id,
                )
                db.add(user)
                await db.flush()
                headers.append({"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(user.id)})})
            db.add(Project(
                id=project_id, uid=uids[0], name=marker, selection_status="selectable",
                workdir_path="projects/" + project_id, directory_mode="managed",
            ))
            await db.flush()
            db.add(Conversation(
                thread_id=thread_id, uid=uids[0], project_id=project_id,
                agent_id="deep-research", title=marker,
            ))
            db.add(EquipmentDeepSession(
                id=session_id, project_id=project_id, owner_uid=uids[0],
                payload={"runtime": "agent", "thread_id": thread_id, "title": marker},
            ))
            await db.commit()
        async with httpx.AsyncClient(base_url="http://web", timeout=30) as client:
            path = f"/api/equipment/deep-thinking/{session_id}"
            for index in (0, 2):
                response = await client.get(path, headers=headers[index])
                assert response.status_code == 200, {"viewer": index, "response": response.text}
                assert response.json()["owner_uid"] == uids[0]
            assert (await client.get(path, headers=headers[1])).status_code == 404
            # 管理员读权限不能绕过持久化会话与线程的归属一致性。
            async with pg_manager.get_async_session_context() as db:
                conversation = await db.scalar(select(Conversation).where(Conversation.thread_id == thread_id))
                session = await db.get(EquipmentDeepSession, session_id)
                session.owner_uid = uids[1]
                assert conversation.uid == uids[0]
                await db.commit()
            assert (await client.get(path, headers=headers[2])).status_code == 404
    finally:
        async with pg_manager.get_async_session_context() as db:
            await db.execute(delete(EquipmentDeepSession).where(EquipmentDeepSession.id == session_id))
            await db.execute(delete(Conversation).where(Conversation.thread_id == thread_id))
            await db.execute(delete(Project).where(Project.id == project_id))
            for uid in uids:
                await db.execute(text("DELETE FROM platform_request_metrics WHERE uid=:uid"), {"uid": uid})
                await db.execute(
                    text("DELETE FROM operation_logs WHERE user_id IN (SELECT id FROM users WHERE uid=:uid)"),
                    {"uid": uid},
                )
            await db.execute(delete(User).where(User.uid.in_(uids)))
            await db.commit()
        await pg_manager.close()
