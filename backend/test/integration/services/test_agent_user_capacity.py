"""真实 PostgreSQL 验证跨会话用户配额、独立业务池和释放后补位。"""

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from platform_core.repositories.agent_run_repository import AgentRunRepository
from platform_core.storage.postgres.models_business import Base, User, Project, Conversation, Message, AgentRun


@pytest.mark.asyncio
@pytest.mark.integration
async def test_concurrent_claims_respect_user_and_lane_capacity():
    schema = "pytest_user_capacity_" + uuid4().hex
    admin = create_async_engine(os.environ["POSTGRES_URL"])
    async with admin.begin() as db:
        await db.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(os.environ["POSTGRES_URL"], connect_args={"server_settings": {"search_path": schema}})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as db:
            await db.run_sync(Base.metadata.create_all)
        run_ids = []
        async with factory() as db:
            for user_index in range(2):
                uid = f"user-{user_index}"
                db.add(User(uid=uid, username=uid, password_hash="test"))
                await db.flush()
                project_id = str(uuid4())
                db.add(
                    Project(
                        id=project_id,
                        uid=uid,
                        selection_status="implicit",
                        workdir_path="projects/" + project_id,
                        directory_mode="managed",
                    )
                )
                await db.flush()
                for index in range(6 if user_index == 0 else 1):
                    thread = str(uuid4())
                    conversation = Conversation(thread_id=thread, uid=uid, project_id=project_id, agent_id="main")
                    db.add(conversation)
                    await db.flush()
                    message = Message(conversation_id=conversation.id, role="user", content="capacity")
                    db.add(message)
                    await db.flush()
                    run_id = str(uuid4())
                    run_ids.append(run_id)
                    db.add(
                        AgentRun(
                            id=run_id,
                            request_id=str(uuid4()),
                            uid=uid,
                            agent_slug="main",
                            run_type="chat",
                            source="equipment_deep_research" if index == 5 else "chat",
                            conversation_thread_id=thread,
                            runtime_scope_id=thread,
                            conversation_id=conversation.id,
                            input_message_id=message.id,
                            input_payload={},
                            status="pending",
                        )
                    )
            await db.commit()

        async def claim(run_id, limit):
            async with factory() as db:
                row, acquired = await AgentRunRepository(db).mark_running(
                    run_id, worker_id="claim-" + run_id, lease_seconds=120, max_user_running=limit
                )
                await db.commit()
                return row.id, acquired

        results = await asyncio.gather(*(claim(run_id, 2) for run_id in run_ids[:5]))
        assert sum(acquired for _, acquired in results) == 2
        assert (await claim(run_ids[6], 2))[1], "Another user must retain independent capacity"
        assert (await claim(run_ids[5], 1))[1], "Deep pool must have a separate user budget"
        winner = next(run_id for run_id, acquired in results if acquired)
        deferred = next(run_id for run_id, acquired in results if not acquired)
        async with factory() as db:
            await db.execute(update(AgentRun).where(AgentRun.id == winner).values(status="failed"))
            await db.commit()
        assert (await claim(deferred, 2))[1], "Released capacity must accept a pending run"
    finally:
        await engine.dispose()
        async with admin.begin() as db:
            await db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()
