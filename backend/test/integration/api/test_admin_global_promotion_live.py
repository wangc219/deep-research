"""真实 HTTP 验证管理员升降级即时生效及全局业务权限。"""

from __future__ import annotations

import hashlib
import os
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select, text

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import (
    Conversation,
    ConversationStats,
    Department,
    OperationLog,
    Project,
    ScheduledAgentJob,
    User,
)
from platform_core.storage.postgres.models_equipment import (
    EquipmentDeepSession,
    EquipmentFavorite,
    EquipmentQuery,
    EquipmentResearchRun,
)
from platform_core.storage.postgres.models_knowledge import KnowledgeBase
from platform_core.utils.auth_utils import AuthUtils
from platform_core.utils.datetime_utils import utc_now_naive

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_superadmin_promotion_grants_and_revokes_global_business_access_immediately():
    pg_manager.initialize()
    suffix = uuid4().hex[:10]
    owner_uid = f"promote_{suffix}_owner"
    candidate_uid = f"promote_{suffix}_candidate"
    guard_uid = f"promote_{suffix}_guard"
    root_uid = f"promote_{suffix}_root"
    uids = [owner_uid, candidate_uid, guard_uid, root_uid]
    project_id = str(uuid4())
    run_id = f"run-{uuid4()}"
    query_id = f"query-{uuid4()}"
    session_id = f"deep-{uuid4()}"
    favorite_id = f"favorite-{uuid4()}"
    kb_id = f"kb-{uuid4()}"
    thread_id = f"thread-{uuid4()}"
    scheduled_job_id = f"scheduled-{uuid4()}"
    user_ids: list[int] = []

    try:
        async with pg_manager.get_async_session_context() as db:
            department_id = await db.scalar(select(Department.id).limit(1))
            assert department_id is not None
            users = [
                User(
                    uid=uid,
                    username=uid,
                    password_hash="disabled-test-login",
                    role="superadmin" if uid == root_uid else "user",
                    department_id=department_id,
                )
                for uid in uids
            ]
            db.add_all(users)
            await db.flush()
            user_ids = [int(user.id) for user in users]
            owner_id, candidate_id, _guard_id, root_id = user_ids
            db.add(
                Project(
                    id=project_id,
                    uid=owner_uid,
                    name=f"管理员升权验证 {suffix}",
                    selection_status="selectable",
                    workdir_path=f"projects/{project_id}",
                    directory_mode="managed",
                )
            )
            await db.flush()
            conversation = Conversation(
                thread_id=thread_id,
                uid=owner_uid,
                agent_id="deep-research",
                title=f"管理员升权普通对话 {suffix}",
                status="active",
                extra_metadata={},
                project_id=project_id,
            )
            db.add(conversation)
            await db.flush()
            db.add(ConversationStats(conversation_id=conversation.id))
            db.add(
                ScheduledAgentJob(
                    id=scheduled_job_id,
                    uid=owner_uid,
                    creation_request_id=f"scheduled-create-{suffix}",
                    creation_intent_hash=hashlib.sha256(scheduled_job_id.encode()).hexdigest(),
                    project_id=project_id,
                    agent_slug="deep-research",
                    name=f"管理员升权定时任务 {suffix}",
                    prompt="验证管理员全局代管定时任务",
                    tool_approval_mode="default",
                    cron_expression="0 9 * * *",
                    timezone="Asia/Shanghai",
                    enabled=False,
                    next_run_at=utc_now_naive(),
                )
            )
            db.add(
                EquipmentResearchRun(
                    id=run_id,
                    project_id=project_id,
                    owner_uid=owner_uid,
                    topic=f"管理员升权研究 {suffix}",
                    status="draft",
                    payload={},
                )
            )
            await db.flush()
            db.add(EquipmentQuery(
                id=query_id,
                project_id=project_id,
                owner_uid=owner_uid,
                query_text=f"管理员升权 Query {suffix}",
                query_fingerprint=hashlib.sha256(query_id.encode()).hexdigest(),
                status="draft",
                payload={},
            ))
            db.add(EquipmentDeepSession(
                id=session_id,
                project_id=project_id,
                owner_uid=owner_uid,
                run_id=run_id,
                payload={"title": f"管理员升权深研 {suffix}", "status": "active"},
            ))
            db.add(EquipmentFavorite(
                id=favorite_id,
                project_id=project_id,
                owner_uid=owner_uid,
                run_id=run_id,
                card_key=f"card-{suffix}",
                snapshot={"name": f"管理员升权收藏 {suffix}"},
                display_name=f"管理员升权收藏 {suffix}",
                note="",
                tags=[],
            ))
            db.add(KnowledgeBase(
                kb_id=kb_id,
                name=f"管理员升权知识库 {suffix}",
                description="private knowledge base for admin promotion test",
                kb_type="milvus",
                embedding_model_spec="siliconflow-cn:Pro/BAAI/bge-m3",
                additional_params={},
                share_config={"version": 2, "read_scope": None, "manage_scope": None},
                created_by=owner_uid,
            ))
            await db.commit()

        headers = [
            {"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(user_id)})}
            for user_id in user_ids
        ]
        _owner_headers, candidate_headers, _guard_headers, root_headers = headers
        base_url = os.getenv("ENTERPRISE_TEST_API", "http://127.0.0.1:5050")
        async with httpx.AsyncClient(base_url=base_url, timeout=45) as client:
            assert (await client.get(f"/api/equipment/runs/{run_id}", headers=candidate_headers)).status_code == 404
            deep_response = await client.get(
                f"/api/equipment/deep-thinking/{session_id}", headers=candidate_headers
            )
            assert deep_response.status_code == 404
            favorite_response = await client.get(
                f"/api/equipment/favorites/{favorite_id}", headers=candidate_headers
            )
            assert favorite_response.status_code == 404
            before_kbs = (await client.get("/api/knowledge/databases", headers=candidate_headers)).json()["databases"]
            assert kb_id not in {item["kb_id"] for item in before_kbs}
            assert project_id not in {
                item["id"] for item in (await client.get("/api/projects", headers=candidate_headers)).json()
            }
            assert thread_id not in {
                item["id"] for item in (await client.get("/api/chat/threads", headers=candidate_headers)).json()
            }
            assert scheduled_job_id not in {
                item["id"]
                for item in (await client.get("/api/scheduled-tasks", headers=candidate_headers)).json()["jobs"]
            }
            assert (await client.get("/api/dashboard/stats", headers=candidate_headers)).status_code == 403

            response = await client.put(
                f"/api/auth/users/{candidate_id}",
                headers=root_headers,
                json={"role": "admin"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["role"] == "admin"

            # 继续复用升权前签发的 token，下一次请求即获得全局业务权限。
            assert run_id in {
                item["run_id"] for item in (await client.get("/api/equipment/runs", headers=candidate_headers)).json()
            }
            assert query_id in {
                item["query_id"]
                for item in (await client.get("/api/equipment/queries", headers=candidate_headers)).json()
            }
            assert session_id in {
                item["session_id"]
                for item in (await client.get("/api/equipment/deep-thinking", headers=candidate_headers)).json()
            }
            assert favorite_id in {
                item["favorite_id"]
                for item in (await client.get("/api/equipment/favorites", headers=candidate_headers)).json()["items"]
            }
            promoted_kbs = (await client.get("/api/knowledge/databases", headers=candidate_headers)).json()["databases"]
            assert kb_id in {item["kb_id"] for item in promoted_kbs}
            assert project_id in {
                item["id"] for item in (await client.get("/api/projects", headers=candidate_headers)).json()
            }
            assert thread_id in {
                item["id"] for item in (await client.get("/api/chat/threads", headers=candidate_headers)).json()
            }
            assert scheduled_job_id in {
                item["id"]
                for item in (await client.get("/api/scheduled-tasks", headers=candidate_headers)).json()["jobs"]
            }
            assert (await client.get("/api/dashboard/stats", headers=candidate_headers)).status_code == 200

            response = await client.put(
                f"/api/chat/thread/{thread_id}",
                headers=candidate_headers,
                json={"title": f"管理员代管普通对话后 {suffix}"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["uid"] == owner_uid

            response = await client.patch(
                f"/api/scheduled-tasks/{scheduled_job_id}",
                headers=candidate_headers,
                json={"name": f"管理员代管定时任务后 {suffix}"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["uid"] == owner_uid

            response = await client.patch(
                f"/api/equipment/runs/{run_id}",
                headers=candidate_headers,
                json={"topic": f"管理员代管后 {suffix}"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["owner_uid"] == owner_uid

            # 管理员拥有全局业务权限，但不能治理角色、超级管理员或租户。
            assert (
                await client.put(
                    f"/api/auth/users/{candidate_id}",
                    headers=candidate_headers,
                    json={"role": "superadmin"},
                )
            ).status_code == 403
            assert (
                await client.put(
                    f"/api/auth/users/{root_id}",
                    headers=candidate_headers,
                    json={"username": f"blocked_{suffix}"},
                )
            ).status_code == 403
            assert (
                await client.post(
                    "/api/enterprise/tenants",
                    headers=candidate_headers,
                    json={"name": f"blocked_{suffix}"},
                )
            ).status_code == 403

            response = await client.put(
                f"/api/auth/users/{candidate_id}",
                headers=root_headers,
                json={"role": "user"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["role"] == "user"

            # 降权同样无需重登，旧 token 的下一次请求立即恢复 owner-only。
            assert (await client.get(f"/api/equipment/runs/{run_id}", headers=candidate_headers)).status_code == 404
            after_kbs = (await client.get("/api/knowledge/databases", headers=candidate_headers)).json()["databases"]
            assert kb_id not in {item["kb_id"] for item in after_kbs}
            assert project_id not in {
                item["id"] for item in (await client.get("/api/projects", headers=candidate_headers)).json()
            }
            assert thread_id not in {
                item["id"] for item in (await client.get("/api/chat/threads", headers=candidate_headers)).json()
            }
            assert scheduled_job_id not in {
                item["id"]
                for item in (await client.get("/api/scheduled-tasks", headers=candidate_headers)).json()["jobs"]
            }

        async with pg_manager.get_async_session_context() as db:
            stored_run = await db.get(EquipmentResearchRun, run_id)
            assert stored_run is not None and stored_run.owner_uid == owner_uid
            assert stored_run.topic == f"管理员代管后 {suffix}"
            stored_conversation = await db.scalar(select(Conversation).where(Conversation.thread_id == thread_id))
            assert stored_conversation is not None and stored_conversation.uid == owner_uid
            assert stored_conversation.title == f"管理员代管普通对话后 {suffix}"
            stored_job = await db.get(ScheduledAgentJob, scheduled_job_id)
            assert stored_job is not None and stored_job.uid == owner_uid
            assert stored_job.name == f"管理员代管定时任务后 {suffix}"
            assert await db.get(User, owner_id) is not None
    finally:
        async with pg_manager.get_async_session_context() as db:
            await db.execute(delete(KnowledgeBase).where(KnowledgeBase.kb_id == kb_id))
            await db.execute(delete(EquipmentDeepSession).where(EquipmentDeepSession.id == session_id))
            await db.execute(delete(EquipmentFavorite).where(EquipmentFavorite.id == favorite_id))
            await db.execute(delete(EquipmentQuery).where(EquipmentQuery.id == query_id))
            await db.execute(delete(EquipmentResearchRun).where(EquipmentResearchRun.id == run_id))
            await db.execute(delete(ScheduledAgentJob).where(ScheduledAgentJob.id == scheduled_job_id))
            conversation_ids = select(Conversation.id).where(Conversation.thread_id == thread_id)
            await db.execute(delete(ConversationStats).where(ConversationStats.conversation_id.in_(conversation_ids)))
            await db.execute(delete(Conversation).where(Conversation.thread_id == thread_id))
            await db.execute(delete(Project).where(Project.id == project_id))
            await db.execute(delete(OperationLog).where(OperationLog.user_id.in_(user_ids)))
            await db.execute(text("DELETE FROM platform_request_metrics WHERE uid = ANY(:uids)"), {"uids": uids})
            await db.execute(delete(User).where(User.uid.in_(uids)))
            await db.commit()
        await pg_manager.close()
