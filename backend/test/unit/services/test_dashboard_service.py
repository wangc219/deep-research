"""Unit tests for DashboardService and Thread analytics."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from platform_core.services.dashboard_service import DashboardService
from platform_core.storage.postgres.models_business import (
    Agent,
    AgentRun,
    Base,
    Conversation,
    ConversationStats,
    Department,
    Message,
    MessageFeedback,
    ToolCall,
    User,
)
from platform_core.storage.postgres.models_equipment import EquipmentResearchEvent, EquipmentResearchRun
from platform_core.utils.datetime_utils import utc_now_naive
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = [pytest.mark.asyncio, pytest.mark.unit]


@pytest_asyncio.fixture()
async def dashboard_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        dept = Department(name="Engineering")
        superadmin = User(
            username="Super Admin",
            uid="uid-superadmin",
            password_hash="$argon2id$placeholder",
            role="superadmin",
            department=dept,
        )
        user1 = User(
            username="Alice",
            uid="uid-alice",
            password_hash="$argon2id$placeholder",
            role="user",
            department=dept,
        )
        user2 = User(
            username="Bob",
            uid="uid-bob",
            password_hash="$argon2id$placeholder",
            role="user",
            department=dept,
        )
        deleted_user = User(
            username="Deleted User",
            uid="uid-deleted",
            password_hash="$argon2id$placeholder",
            role="user",
            department=dept,
            is_deleted=1,
        )

        agent1 = Agent(
            slug="agent-helper",
            backend_id="b-1",
            name="Helper Agent",
            share_config={},
        )
        agent2 = Agent(
            slug="agent-coder",
            backend_id="b-2",
            name="Coder Agent",
            share_config={},
        )

        now = utc_now_naive()
        yesterday = now - timedelta(days=1)

        conv1 = Conversation(
            thread_id="thread-101",
            project_id="p-1",
            uid="uid-alice",
            agent_id="agent-helper",
            title="Alice Helper Query",
            status="active",
            is_pinned=True,
            created_at=yesterday,
            updated_at=now,
        )
        conv2 = Conversation(
            thread_id="thread-102",
            project_id="p-2",
            uid="uid-bob",
            agent_id="agent-coder",
            title="Bob Coder Task",
            status="active",
            is_pinned=False,
            created_at=now,
            updated_at=now,
        )
        conv3 = Conversation(
            thread_id="thread-103",
            project_id="p-3",
            uid="uid-alice",
            agent_id="agent-coder",
            title="Alice Python Debug",
            status="archived",
            is_pinned=False,
            created_at=yesterday,
            updated_at=yesterday,
        )
        deleted_conversation = Conversation(
            thread_id="thread-deleted",
            project_id="p-deleted",
            uid="uid-alice",
            agent_id="agent-helper",
            title="Deleted conversation",
            status="deleted",
            created_at=yesterday,
            updated_at=now,
        )
        deleted_user_conversation = Conversation(
            thread_id="thread-deleted-user",
            project_id="p-deleted-user",
            uid="uid-deleted",
            agent_id="agent-helper",
            title="Deleted user conversation",
            status="active",
            created_at=yesterday,
            updated_at=now,
        )
        missing_agent_conversation = Conversation(
            thread_id="thread-missing-agent",
            project_id="p-missing-agent",
            uid="uid-alice",
            agent_id="removed-agent",
            title="Removed agent conversation",
            status="active",
            created_at=yesterday,
            updated_at=now,
        )
        subagent_conversation = Conversation(
            thread_id="thread-subagent",
            project_id="p-subagent",
            uid="uid-alice",
            agent_id="agent-helper",
            title="Subagent conversation",
            status="subagent",
            created_at=yesterday,
            updated_at=now,
        )

        stats1 = ConversationStats(conversation=conv1, message_count=4, total_tokens=1200)
        stats2 = ConversationStats(conversation=conv2, message_count=8, total_tokens=3500)
        stats3 = ConversationStats(conversation=conv3, message_count=1, total_tokens=300)

        msg1 = Message(conversation=conv1, role="user", content="Hello", created_at=yesterday)
        msg2 = Message(conversation=conv1, role="assistant", content="Hi there!", created_at=yesterday)
        msg3 = Message(conversation=conv2, role="user", content="Write code", created_at=now)
        msg4 = Message(
            conversation=conv2,
            role="assistant",
            content="Here is code",
            created_at=now,
            extra_metadata={"usage_metadata": {"input_tokens": 5, "output_tokens": 3}},
        )
        hidden_model_audit = Message(
            conversation=conv2,
            role="assistant",
            content="Intermediate model output",
            message_type="model_audit",
            operation_id="model-audit-1",
            execution_status="completed",
            created_at=now,
            extra_metadata={"usage_metadata": {"input_tokens": 100, "output_tokens": 100}},
        )
        hidden_tool_audit = Message(
            conversation=conv2,
            role="tool",
            content="Intermediate tool output",
            message_type="tool_audit",
            operation_id="tool-audit-1",
            started_at=now,
            sequence=2,
            execution_status="completed",
            created_at=now,
            extra_metadata={"usage_metadata": {"input_tokens": 100, "output_tokens": 100}},
        )
        removed_agent_message = Message(
            conversation=missing_agent_conversation,
            role="assistant",
            content="Historical removed agent output",
            created_at=now,
        )

        tool1 = ToolCall(message=msg4, tool_name="bash", status="success", created_at=now)
        removed_agent_tool = ToolCall(
            message=removed_agent_message,
            tool_name="legacy_tool",
            status="success",
            created_at=now,
        )

        feedback1 = MessageFeedback(message=msg2, uid="uid-alice", rating="like", created_at=yesterday)
        hidden_model_feedback = MessageFeedback(
            message=hidden_model_audit,
            uid="uid-bob",
            rating="dislike",
            created_at=now,
        )
        hidden_tool_feedback = MessageFeedback(
            message=hidden_tool_audit,
            uid="uid-bob",
            rating="like",
            created_at=now,
        )
        removed_agent_feedback = MessageFeedback(
            message=removed_agent_message,
            uid="uid-alice",
            rating="dislike",
            created_at=now,
        )

        db.add_all(
            [
                dept,
                superadmin,
                user1,
                user2,
                deleted_user,
                agent1,
                agent2,
                conv1,
                conv2,
                conv3,
                deleted_conversation,
                deleted_user_conversation,
                missing_agent_conversation,
                subagent_conversation,
                stats1,
                stats2,
                stats3,
                msg1,
                msg2,
                msg3,
                msg4,
                hidden_model_audit,
                hidden_tool_audit,
                removed_agent_message,
                tool1,
                removed_agent_tool,
                feedback1,
                hidden_model_feedback,
                hidden_tool_feedback,
                removed_agent_feedback,
            ]
        )
        await db.commit()
        yield db
    await engine.dispose()


async def test_dashboard_service_basic_stats(dashboard_db):
    service = DashboardService(dashboard_db)
    stats = await service.get_basic_stats()

    assert stats["total_conversations"] == 3
    assert stats["active_conversations"] == 2
    assert stats["total_messages"] == 4
    assert stats["total_users"] == 3
    assert stats["feedback_stats"]["total_feedbacks"] == 1
    assert stats["feedback_stats"]["satisfaction_rate"] == 100.0

    tool_stats = await service.get_tool_call_stats()
    assert tool_stats["total_calls"] == 1

    user_stats = await service.get_user_activity_stats()
    assert len(user_stats["daily_active_users"]) == 120
    assert user_stats["daily_active_users"][0]["date"] < user_stats["daily_active_users"][-1]["date"]

    feedbacks = await service.get_feedbacks()
    assert len(feedbacks) == 1


async def test_agent_analytics_omits_removed_top_performers_contract(dashboard_db):
    """智能体统计保留概览字段且不再生成 TOP 5 排行。"""
    analytics = await DashboardService(dashboard_db).get_agent_analytics()

    assert set(analytics) == {
        "total_agents",
        "configured_agents",
        "participating_agents",
        "total_agent_runs",
        "completed_agent_runs",
        "failed_agent_runs",
        "active_agent_runs",
        "subagent_runs",
        "deep_research_agent_runs",
        "agent_run_success_rate",
        "runtime_agent_stats",
        "agent_conversation_counts",
        "agent_satisfaction_rates",
        "agent_tool_usage",
        "agent_names",
    }
    assert analytics["total_agents"] == 2
    assert analytics["agent_names"] == {
        "agent-helper": "Helper Agent",
        "agent-coder": "Coder Agent",
    }
    coder_satisfaction = next(
        item for item in analytics["agent_satisfaction_rates"] if item["agent_id"] == "agent-coder"
    )
    assert coder_satisfaction == {
        "agent_id": "agent-coder",
        "satisfaction_rate": 100,
        "total_feedbacks": 0,
    }


async def test_agent_analytics_includes_deep_research_and_subagent_runs(dashboard_db):
    """数据总览统一统计平台 Subagent 与装备研究 S-Agent 的真实参与。"""
    dashboard_db.add_all(
        [
            AgentRun(
                id="run-subagent-1",
                conversation_thread_id="thread-subagent",
                runtime_scope_id="thread-101",
                agent_slug="agent-coder",
                uid="uid-alice",
                status="completed",
                request_id="request-subagent-1",
                source="subagent",
                channel="internal",
                run_type="subagent",
                input_payload={},
            ),
            AgentRun(
                id="run-deep-1",
                conversation_thread_id="thread-101",
                runtime_scope_id="thread-101",
                agent_slug="deep-research",
                uid="uid-alice",
                status="running",
                request_id="request-deep-1",
                source="equipment_deep_research",
                channel="web",
                run_type="chat",
                input_payload={},
            ),
            EquipmentResearchRun(
                id="equipment-run-analytics",
                project_id="p-1",
                owner_uid="uid-alice",
                topic="Agent analytics",
                status="completed",
                payload={},
            ),
            EquipmentResearchEvent(
                run_id="equipment-run-analytics",
                sequence=1,
                event_type="winning_agent_started",
                payload={"agent_id": "winning_s6_image"},
            ),
            EquipmentResearchEvent(
                run_id="equipment-run-analytics",
                sequence=2,
                event_type="baseline_agent_completed",
                payload={"agent_id": "winning_s6_image"},
            ),
        ]
    )
    await dashboard_db.commit()

    analytics = await DashboardService(dashboard_db).get_agent_analytics()

    assert analytics["configured_agents"] == 2
    assert analytics["participating_agents"] == 3
    assert analytics["total_agents"] == 4
    assert analytics["total_agent_runs"] == 3
    assert analytics["completed_agent_runs"] == 2
    assert analytics["active_agent_runs"] == 1
    assert analytics["subagent_runs"] == 1
    assert analytics["deep_research_agent_runs"] == 2
    assert analytics["agent_names"]["winning_s6_image"] == "S6 能力画像综合"


async def test_dashboard_service_thread_analytics(dashboard_db):
    service = DashboardService(dashboard_db)
    analytics = await service.get_thread_analytics(time_range="7days")

    summary = analytics["summary"]
    assert summary["total_threads"] == 3
    assert summary["active_threads"] >= 1
    assert summary["pinned_threads"] == 1
    assert summary["total_messages"] == 4
    assert summary["total_tokens"] == 5000
    assert summary["avg_messages_per_thread"] > 0
    assert summary["avg_tokens_per_thread"] > 0

    assert len(analytics["daily_trends"]) == 7

    depth = analytics["depth_distribution"]
    assert depth["1-2 条"] == 1  # conv3 has 1 message
    assert depth["3-5 条"] == 1  # conv1 has 4 messages
    assert depth["6-10 条"] == 1  # conv2 has 8 messages

    agents = analytics["agent_distribution"]
    assert len(agents) == 2
    coder_stat = next(a for a in agents if a["agent_id"] == "agent-coder")
    assert coder_stat["thread_count"] == 2
    assert coder_stat["agent_name"] == "Coder Agent"

    with_subagents = await service.get_thread_analytics(time_range="7days", include_subagents=True)
    assert with_subagents["summary"]["total_threads"] == 4
    helper_with_subagent = next(
        item for item in with_subagents["agent_distribution"] if item["agent_id"] == "agent-helper"
    )
    assert helper_with_subagent["thread_count"] == 2

    top_users = analytics["top_users"]
    assert len(top_users) >= 2
    alice_stat = next(u for u in top_users if u["uid"] == "uid-alice")
    assert alice_stat["username"] == "Alice"
    assert alice_stat["thread_count"] == 2

    assert analytics["status_distribution"]["active"] == 2
    assert analytics["status_distribution"]["archived"] == 1

    coder_only = await service.get_thread_analytics(time_range="7days", agent_id="agent-coder")
    assert coder_only["summary"]["total_threads"] == 2
    assert coder_only["summary"]["total_messages"] == 2
    assert [item["agent_id"] for item in coder_only["agent_distribution"]] == ["agent-coder"]
    assert coder_only["status_distribution"] == {"active": 1, "archived": 1}
    assert {item["uid"] for item in coder_only["top_users"]} == {"uid-alice", "uid-bob"}


async def test_thread_analytics_groups_daily_trends_by_shanghai_date(dashboard_db):
    service = DashboardService(dashboard_db)
    fixed_now = datetime(2026, 8, 24, 1, 0)
    baseline = await service.repo.get_thread_analytics(time_range="7days", now=fixed_now)
    baseline_by_date = {item["date"]: item for item in baseline["daily_trends"]}

    boundary_conversation = Conversation(
        thread_id="thread-shanghai-boundary",
        project_id="p-boundary",
        uid="uid-alice",
        agent_id="agent-helper",
        title="Shanghai boundary",
        status="active",
        created_at=datetime(2026, 8, 23, 16, 30),
        updated_at=datetime(2026, 8, 23, 16, 30),
    )
    boundary_message = Message(
        conversation=boundary_conversation,
        role="user",
        content="After Shanghai midnight",
        created_at=datetime(2026, 8, 23, 16, 30),
    )
    dashboard_db.add_all([boundary_conversation, boundary_message])
    await dashboard_db.commit()

    analytics = await service.repo.get_thread_analytics(time_range="7days", now=fixed_now)
    trend_by_date = {item["date"]: item for item in analytics["daily_trends"]}

    assert trend_by_date["2026-08-24"]["new_threads"] == baseline_by_date["2026-08-24"]["new_threads"] + 1
    assert trend_by_date["2026-08-24"]["active_threads"] == baseline_by_date["2026-08-24"]["active_threads"] + 1
    assert trend_by_date["2026-08-24"]["message_count"] == baseline_by_date["2026-08-24"]["message_count"] + 1


async def test_thread_analytics_query_count_does_not_grow_with_time_range(dashboard_db):
    service = DashboardService(dashboard_db)
    engine = dashboard_db.bind.sync_engine
    statement_counts = []
    current_count = 0

    def count_statement(*_args):
        nonlocal current_count
        current_count += 1

    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        await service.get_thread_analytics(time_range="7days")
        statement_counts.append(current_count)
        current_count = 0
        await service.get_thread_analytics(time_range="90days")
        statement_counts.append(current_count)
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)

    assert statement_counts[0] == statement_counts[1]
    assert statement_counts[0] <= 12


async def test_dashboard_service_list_conversations_search(dashboard_db):
    service = DashboardService(dashboard_db)

    all_convs = await service.list_conversations(limit=20)
    assert all_convs["total"] == 6
    assert len(all_convs["items"]) == 6
    assert all(item["status"] != "deleted" for item in all_convs["items"])
    deleted_convs = await service.list_conversations(status="deleted", limit=20)
    assert deleted_convs["total"] == 1
    assert deleted_convs["items"][0]["thread_id"] == "thread-deleted"
    deleted_item = next(item for item in all_convs["items"] if item["thread_id"] == "thread-deleted-user")
    missing_agent_item = next(item for item in all_convs["items"] if item["thread_id"] == "thread-missing-agent")
    assert deleted_item["user_deleted"] is True
    assert missing_agent_item["agent_deleted"] is True

    search_result = await service.list_conversations(search="Python")
    assert search_result["total"] == 1
    assert search_result["items"][0]["thread_id"] == "thread-103"
    assert search_result["items"][0]["username"] == "Alice"
    assert search_result["items"][0]["agent_name"] == "Coder Agent"

    active_only = await service.list_conversations(status="active")
    assert active_only["total"] == 4
    assert len(active_only["items"]) == 4

    options = await service.get_conversation_filter_options()
    assert next(item for item in options["users"] if item["uid"] == "uid-deleted")["is_deleted"] is True
    assert next(item for item in options["agents"] if item["agent_id"] == "removed-agent")["is_deleted"] is True


async def test_dashboard_service_conversation_detail(dashboard_db):
    service = DashboardService(dashboard_db)
    detail = await service.get_conversation_detail("thread-102")

    assert detail is not None
    assert detail["thread_id"] == "thread-102"
    assert detail["total_tokens"] == 3500
    assert detail["user_deleted"] is False
    assert detail["agent_deleted"] is False
    assert len(detail["messages"]) == 2
    assistant_msg = next(m for m in detail["messages"] if m["role"] == "assistant")
    assert "tool_calls" in assistant_msg
    assert assistant_msg["tool_calls"][0]["tool_name"] == "bash"


async def test_conversation_tokens_use_runs_and_expose_missing_usage(dashboard_db):
    """审计累加同会话 Run，忽略旧汇总并区分真实零和未知。"""
    from platform_core.storage.postgres.models_business import AgentRun
    from sqlalchemy import select

    conversation = (
        await dashboard_db.execute(select(Conversation).where(Conversation.thread_id == "thread-102"))
    ).scalar_one()
    for index, usage in enumerate(
        [
            {"total": {"total_tokens": 120}, "complete": True, "usage_reported_call_count": 1},
            {"total": {"total_tokens": 80}, "complete": True, "usage_reported_call_count": 1},
        ]
    ):
        dashboard_db.add(
            AgentRun(
                id=f"usage-run-{index}",
                conversation_id=conversation.id,
                conversation_thread_id=conversation.thread_id,
                runtime_scope_id=conversation.thread_id,
                agent_slug=conversation.agent_id,
                uid=conversation.uid,
                status="completed",
                request_id=f"usage-request-{index}",
                token_usage=usage,
            )
        )
    await dashboard_db.commit()
    service = DashboardService(dashboard_db)
    detail = await service.get_conversation_detail(conversation.thread_id)
    item = (await service.list_conversations(search="thread-102"))["items"][0]
    assert detail["total_tokens"] == item["total_tokens"] == 200
    assert item["token_usage_complete"] is True

    run = await dashboard_db.get(AgentRun, "usage-run-1")
    run.token_usage = {"available": False}
    await dashboard_db.commit()
    item = (await service.list_conversations(search="thread-102"))["items"][0]
    assert item["total_tokens"] == 120
    assert item["token_usage_complete"] is False

    run = await dashboard_db.get(AgentRun, "usage-run-0")
    run.token_usage = {"total": {"total_tokens": 0}, "complete": False, "usage_reported_call_count": 0}
    await dashboard_db.commit()
    item = (await service.list_conversations(search="thread-102"))["items"][0]
    assert item["total_tokens"] is None
    assert item["token_usage_complete"] is False

    run.token_usage = {"total": {"total_tokens": 0}, "complete": True, "usage_reported_call_count": 1}
    await dashboard_db.delete(await dashboard_db.get(AgentRun, "usage-run-1"))
    await dashboard_db.commit()
    item = (await service.list_conversations(search="thread-102"))["items"][0]
    assert item["total_tokens"] == 0
    assert item["token_usage_complete"] is True


async def test_model_usage_overview_unifies_agent_and_equipment_runs(dashboard_db):
    from platform_core.storage.postgres.models_business import AgentRun
    from platform_core.storage.postgres.models_equipment import EquipmentResearchRun

    dashboard_db.add(
        AgentRun(
            id="deep-usage-run",
            conversation_thread_id="thread-101",
            runtime_scope_id="thread-101",
            agent_slug="agent-helper",
            uid="uid-alice",
            status="completed",
            request_id="deep-usage-request",
            source="equipment_deep_research",
            run_type="chat",
            input_payload={"model_spec": "provider:model-a"},
            token_usage={
                "models": {"provider:model-a": {"model_call_count": 2, "usage": {"total_tokens": 90}}},
                "total": {"input_tokens": 60, "output_tokens": 30, "total_tokens": 90},
                "model_call_count": 2,
                "complete": True,
            },
        )
    )
    dashboard_db.add(
        EquipmentResearchRun(
            id="equipment-usage-run",
            project_id="p-1",
            owner_uid="uid-alice",
            topic="Test equipment research",
            status="completed",
            payload={
                "model_spec": "provider:model-a",
                "model_usage": {
                    "models": {"provider:model-a": {"call_count": 3, "total_tokens": 210}},
                    "total": {"input_tokens": 150, "output_tokens": 60, "total_tokens": 210},
                    "call_count": 3,
                    "complete": True,
                },
            },
        )
    )
    await dashboard_db.commit()

    overview = await DashboardService(dashboard_db).get_model_usage_overview()

    assert overview["summary"]["call_count"] == 5
    assert overview["summary"]["total_tokens"] == 300
    assert {item["surface"] for item in overview["by_surface"]} >= {"深研对话", "研究任务"}
    model = next(item for item in overview["by_model"] if item["model_spec"] == "provider:model-a")
    assert model["call_count"] == 5
    assert model["total_tokens"] == 300


async def test_model_usage_ledger_counts_failed_retries_without_double_counting(dashboard_db):
    """账本替代同任务旧汇总；失败请求计次但不伪造 token。"""
    from platform_core.storage.postgres.models_business import AgentRun, PlatformModelCall

    dashboard_db.add(
        AgentRun(
            id="ledger-run",
            conversation_thread_id="thread-101",
            runtime_scope_id="thread-101",
            agent_slug="agent-helper",
            uid="uid-alice",
            status="completed",
            request_id="ledger-request",
            source="chat",
            run_type="chat",
            token_usage={
                "model_call_count": 2,
                "total": {"total_tokens": 999},
                "complete": True,
            },
        )
    )
    for i, status in enumerate(("failed", "completed")):
        dashboard_db.add(
            PlatformModelCall(
                id=f"ledger-call-{i}",
                model_spec="configured:model",
                surface="智能对话",
                run_id="ledger-run",
                status=status,
                duration_ms=10,
                input_tokens=10 if i else None,
                output_tokens=5 if i else None,
                total_tokens=15 if i else None,
            )
        )
    await dashboard_db.commit()
    result = await DashboardService(dashboard_db).get_model_usage_overview()
    assert result["summary"]["pending_sync_call_count"] == 0
    assert result["summary"]["call_count"] == 2
    assert result["summary"]["total_tokens"] == 15
    assert result["summary"]["failed_call_count"] == 1
    assert result["summary"]["usage_call_coverage_rate"] == 50.0
    assert result["by_model"][0]["total_tokens"] == 15


async def test_model_usage_overview_includes_query_s6_report_and_deep_calls(
    dashboard_db,
):
    """统一账本应覆盖 Query、S6 五栏、报告章节和深研，且替代同 Run 旧汇总。"""

    from platform_core.storage.postgres.models_business import PlatformModelCall

    dashboard_db.add(
        EquipmentResearchRun(
            id="research-ledger",
            project_id="p-1",
            owner_uid="uid-alice",
            topic="并行研究用量",
            status="completed",
            payload={
                "model_spec": "provider:model-a",
                "model_usage": {
                    "call_count": 99,
                    "total": {"total_tokens": 9999},
                    "complete": True,
                },
            },
        )
    )
    rows = (
        ("usage-query", "Query 生成", "generation-1", "query_generation", 11),
        (
            "usage-s6",
            "研究任务",
            "research-ledger",
            "winning_s6_parallel_card_01_module_overview",
            13,
        ),
        (
            "usage-report",
            "研究任务",
            "research-ledger",
            "report_generation_chapter_2_operations",
            17,
        ),
        (
            "usage-deep",
            "深研对话",
            "deep-job-1",
            "deep_contextual_dialogue_s6_column_4",
            19,
        ),
    )
    for call_id, surface, run_id, phase, tokens in rows:
        dashboard_db.add(
            PlatformModelCall(
                id=call_id,
                model_spec="provider:model-a",
                surface=surface,
                run_id=run_id,
                phase=phase,
                status="completed",
                duration_ms=10,
                input_tokens=tokens - 3,
                output_tokens=3,
                total_tokens=tokens,
            )
        )
    await dashboard_db.commit()

    result = await DashboardService(dashboard_db).get_model_usage_overview()

    by_surface = {item["surface"]: item for item in result["by_surface"]}
    assert by_surface["Query 生成"]["call_count"] == 1
    assert by_surface["研究任务"]["call_count"] == 2
    assert by_surface["研究任务"]["total_tokens"] == 30
    assert by_surface["深研对话"]["call_count"] == 1
    assert result["summary"]["call_count"] == 4
    assert result["summary"]["total_tokens"] == 60
