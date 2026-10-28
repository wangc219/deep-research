from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from platform_core.repositories.conversation_repository import ConversationRepository
from platform_core.services.agent_request_service import _supersede_latest_question
from platform_core.storage.postgres.models_business import (
    SUPERSEDED_MESSAGE_TYPE,
    Conversation,
    Message,
    MessageFeedback,
    Project,
    User,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_message_replacement_is_atomic_on_postgres():
    """在真实 PostgreSQL 上验证行锁、反馈删除与普通历史过滤。"""
    engine = create_async_engine(os.environ["POSTGRES_URL"], pool_pre_ping=True)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            user = await session.scalar(select(User).where(User.is_deleted == 0).limit(1))
            assert user is not None
            suffix = uuid.uuid4().hex
            project = Project(
                id=f"pytest-edit-{suffix}",
                uid=str(user.uid),
                name=f"pytest-edit-{suffix}",
                selection_status="implicit",
                workdir_path=f"projects/pytest-edit-{suffix}",
                directory_mode="managed",
            )
            session.add(project)
            await session.flush()
            conversation = Conversation(
                thread_id=f"pytest-edit-{suffix}",
                project_id=project.id,
                uid=str(user.uid),
                agent_id="default",
                status="active",
            )
            session.add(conversation)
            await session.flush()
            question = Message(
                conversation_id=conversation.id,
                role="user",
                content="old question",
                extra_metadata={"raw_message": {"id": "old-human"}},
            )
            answer = Message(
                conversation_id=conversation.id,
                role="assistant",
                content="old answer",
            )
            session.add_all([question, answer])
            await session.flush()
            session.add(MessageFeedback(message_id=answer.id, uid=str(user.uid), rating="dislike"))
            await session.flush()

            replacement = await _supersede_latest_question(
                db=session,
                conversation_id=conversation.id,
                message_id=question.id,
                replacement_request_id="replacement-request",
            )
            await session.flush()

            assert replacement["source_id"] == "old-human"
            assert question.message_type == SUPERSEDED_MESSAGE_TYPE
            assert answer.message_type == SUPERSEDED_MESSAGE_TYPE
            assert await session.scalar(
                select(func.count())
                .select_from(MessageFeedback)
                .where(MessageFeedback.message_id == answer.id)
            ) == 0
            assert await ConversationRepository(session).get_messages(conversation.id) == []
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()
