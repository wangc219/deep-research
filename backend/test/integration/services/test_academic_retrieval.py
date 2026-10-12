"""在独立真实 PostgreSQL Schema 中验证学术检索事务与缓存。"""

import asyncio
import json
import os
import re
from datetime import timedelta
from html import unescape
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from platform_core.config.options import aminer_api_opts, ensure_options_in_db, update_option_value
from platform_core.repositories.academic_retrieval_repository import AcademicRetrievalRepository
from platform_core.services.academic_retrieval_service import AcademicRetrievalService
from platform_core.services.aminer_client import aminer_credential_scope
from platform_core.storage.postgres.models_business import AcademicRetrievalCall, AgentRun, Conversation, SubagentThread
from platform_core.utils.datetime_utils import utc_now_naive
from test.integration.services.agent_run_test_helpers import create_agent_run
from test.integration.services.test_schema_migration_version import _create_isolated_manager, _drop_isolated_schema

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest.fixture(scope="session", autouse=True)
def ensure_live_api_schema():
    """本模块使用隔离 Schema。"""


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_knowledge_resources():
    """不创建在线知识资源。"""
    yield


@pytest.fixture(scope="session", autouse=True)
def cleanup_test_sandboxes():
    """不创建 Sandbox。"""
    yield


@pytest_asyncio.fixture
async def academic_db():
    """创建隔离链路与启用的测试凭证，不触碰现有配置。"""
    schema, admin, engine, manager = await _create_isolated_manager("pytest_aminer")
    try:
        await manager.create_business_tables()
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory.begin() as db:
            await ensure_options_in_db(db)
            await update_option_value(
                db,
                aminer_api_opts.key,
                {"enabled": True, "user_id": "test", "api_key": "test-key-with-at-least-32-characters"},
                "tester",
            )
        root_id, thread, _ = await create_agent_run(
            factory,
            prefix="academic",
            message_content="public topic",
            input_payload={},
            status="running",
            worker_id="owner",
            lease_expires_at=utc_now_naive() + timedelta(minutes=5),
        )
        async with factory.begin() as db:
            root = await db.get(AgentRun, root_id)
            child_thread = str(uuid4())
            conversation = Conversation(
                thread_id=child_thread,
                uid=root.uid,
                project_id=(await db.get(Conversation, root.conversation_id)).project_id,
                agent_id="research-explorer",
                status="active",
            )
            db.add(conversation)
            await db.flush()
            relation = SubagentThread(
                uid=root.uid,
                parent_conversation_id=root.conversation_id,
                child_conversation_id=conversation.id,
                child_thread_id=child_thread,
                subagent_slug="research-explorer",
                created_by_run_id=root.id,
            )
            db.add(relation)
            await db.flush()
            child = AgentRun(
                id=str(uuid4()),
                conversation_thread_id=child_thread,
                runtime_scope_id=thread,
                agent_slug="research-explorer",
                uid=root.uid,
                request_id=str(uuid4()),
                status="running",
                run_type="subagent",
                created_by_run_id=root.id,
                subagent_thread_relation_id=relation.id,
                worker_id="owner",
                lease_expires_at=root.lease_expires_at,
            )
            resume = AgentRun(
                id=str(uuid4()),
                conversation_thread_id=thread,
                runtime_scope_id=thread,
                agent_slug="main",
                uid=root.uid,
                request_id=str(uuid4()),
                status="completed",
                run_type="resume",
                created_by_run_id=root.id,
                worker_id="owner",
                lease_expires_at=root.lease_expires_at,
            )
            db.add_all([child, resume])
        yield factory, engine, manager, root, child, resume
    finally:
        await _drop_isolated_schema(schema, admin, engine)


def service(factory, run, transport):
    """使用真实事务与模拟供应商 HTTP。"""
    return AcademicRetrievalService(
        SimpleNamespace(uid=run.uid, run_id=run.id, worker_id="owner"), session_factory=factory, transport=transport
    )


async def test_migration_twice_keeps_existing_ledger(academic_db):
    """从缺失表升级两次，约束与数据保持完整。"""
    factory, engine, manager, root, _, _ = academic_db
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE academic_retrieval_calls"))
    await manager.ensure_business_schema()
    async with factory.begin() as db:
        db.add(
            AcademicRetrievalCall(
                id="migration-call",
                root_run_id=root.id,
                run_id=root.id,
                request_key="migration",
                endpoint="search",
                attempt_no=1,
                cost_cents=1,
                status="pending",
            )
        )
    await manager.ensure_business_schema()
    async with factory() as db:
        assert await db.get(AcademicRetrievalCall, "migration-call")


async def test_concurrent_parent_child_share_budget_and_resume_does_not_reset(academic_db):
    """并发父子请求只放行两次 Pro，恢复仍使用相同父账本。"""
    factory, _, _, root, child, resume = academic_db
    requests = []

    async def handler(request):
        requests.append(request.url)
        await asyncio.sleep(0.02)
        return httpx.Response(200, json={"code": 200, "success": True, "data": []})

    transport = httpx.MockTransport(handler)
    results = await asyncio.gather(
        *[
            service(factory, root if i % 2 else child, transport)._request("search", {"keyword": f"topic-{i}"})
            for i in range(8)
        ]
    )
    assert sum(result["status"] == "ok" for result in results) == 2
    assert len(requests) == 2
    async with factory.begin() as db:
        (await db.get(AgentRun, root.id)).status = "completed"
        await db.flush()
        (await db.get(AgentRun, resume.id)).status = "running"
    result = await service(factory, resume, transport)._request("search", {"keyword": "new topic"})
    assert result["status"] == "limit_reached"
    async with factory() as db:
        assert await db.scalar(select(func.sum(AcademicRetrievalCall.cost_cents))) == 2
        assert set((await db.scalars(select(AcademicRetrievalCall.root_run_id))).all()) == {root.id}


async def test_retries_charged_cache_reused_credentials_and_disable_are_immediate(academic_db):
    """两次发送各预占一次；缓存、停用和凭证替换无需新运行。"""
    factory, _, _, root, child, _ = academic_db
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"code": 200, "success": True, "data": []})

    transport = httpx.MockTransport(handler)
    payload = {"keyword": "same topic"}
    assert (await service(factory, root, transport)._request("search", payload))["status"] == "ok"
    cached = await service(factory, child, transport)._request("search", payload)
    assert cached["cached"] is True and calls == 2
    async with factory.begin() as db:
        assert await db.scalar(select(func.count(AcademicRetrievalCall.id))) == 2
        await update_option_value(db, aminer_api_opts.key, {"enabled": False}, "tester")
    assert (await service(factory, child, transport)._request("search", payload))["status"] == "disabled"
    async with factory.begin() as db:
        await update_option_value(
            db,
            aminer_api_opts.key,
            {"enabled": True, "api_key": "replacement-key-with-at-least-32-characters", "chat_search_limit": 3},
            "tester",
        )
    assert (await service(factory, child, transport)._request("search", payload))["cached"] is False
    assert calls == 3


async def test_pending_replay_and_fee_cap_block_duplicate_external_requests(academic_db):
    """未知结果不重发；参考文献请求先检查剩余费用。"""
    factory, _, _, root, child, _ = academic_db
    async with factory.begin() as db:
        await update_option_value(
            db, aminer_api_opts.key, {"chat_budget_cents": 10, "chat_reference_limit": 2}, "tester"
        )
        config = await aminer_api_opts.get(db)
        reservation = await AcademicRetrievalRepository(db).reserve(
            root_run_id=root.id,
            run_id=root.id,
            uid=root.uid,
            endpoint="references",
            request_key="pending",
            attempt_no=1,
            credential_scope=aminer_credential_scope(config),
        )
        assert reservation.call_id
    async with factory.begin() as db:
        replay = await AcademicRetrievalRepository(db).reserve(
            root_run_id=root.id,
            run_id=child.id,
            uid=root.uid,
            endpoint="references",
            request_key="pending",
            attempt_no=1,
            credential_scope=aminer_credential_scope(config),
        )
        assert replay.result["status"] == "in_progress"
    transport = httpx.MockTransport(lambda _: pytest.fail("超预算不得发送请求"))
    assert (await service(factory, child, transport)._request("references", {"id": "new"}))[
        "status"
    ] == "budget_exhausted"


async def test_cross_user_and_stale_worker_denied(academic_db):
    """运行身份由服务端验证，不能跨用户或沿用旧 Worker。"""
    factory, _, _, root, _, _ = academic_db
    async with factory() as db:
        repo = AcademicRetrievalRepository(db)
        for uid, worker in [("another", "owner"), (root.uid, "old-owner")]:
            with pytest.raises(ValueError):
                await repo.resolve_root(run_id=root.id, uid=uid, worker_id=worker)


@pytest.mark.parametrize("endpoint,ttl", [("search", timedelta(hours=1)), ("detail", timedelta(hours=24))])
async def test_cross_turn_cache_expires_without_charging_hits(academic_db, endpoint, ttl):
    """不同轮次共享成功缓存；TTL 到期后的请求重新预占。"""
    factory, _, _, root, _, _ = academic_db
    another_id, _, _ = await create_agent_run(
        factory,
        prefix="cache",
        message_content="public topic",
        input_payload={},
        status="running",
        worker_id="owner",
        lease_expires_at=utc_now_naive() + timedelta(minutes=5),
    )
    async with factory() as db:
        another = await db.get(AgentRun, another_id)
    calls = 0

    def handler(_):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"code": 200, "success": True, "data": []})

    transport = httpx.MockTransport(handler)
    payload = {"keyword": "public topic"} if endpoint == "search" else {"id": "p"}
    await service(factory, root, transport)._request(endpoint, payload)
    result = await service(factory, another, transport)._request(endpoint, payload)
    assert result["cached"] and calls == 1
    async with factory.begin() as db:
        ledger = await db.scalar(select(AcademicRetrievalCall))
        ledger.finished_at = utc_now_naive() - ttl - timedelta(seconds=1)
        assert await db.scalar(select(func.sum(AcademicRetrievalCall.cost_cents))) == 1
    result = await service(factory, another, transport)._request(endpoint, payload)
    assert not result["cached"] and calls == 2


async def test_deep_research_uses_parent_six_search_limit(academic_db):
    """研究探索员从父 Run 的深研来源读取六次额度。"""
    factory, _, _, root, child, _ = academic_db
    async with factory.begin() as db:
        (await db.get(AgentRun, root.id)).source = "equipment_deep_research"
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"code": 200, "success": True, "data": []}))
    results = await asyncio.gather(
        *[service(factory, child, transport)._request("search", {"keyword": f"deep-{i}"}) for i in range(7)]
    )
    assert sum(result["status"] == "ok" for result in results) == 6
    assert sum(result["status"] == "limit_reached" for result in results) == 1


MODEL_ROUTING_CASES = [
    ("smart_general", "今天心情不好，给我一句简短的鼓励。", None),
    ("smart_title", "找一下 Attention Is All You Need 的摘要和来源，简述其核心思想。200字内。", "title"),
    ("smart_topic", "比较稀疏注意力与 FlashAttention 在长序列推理中的技术取舍，结合论文证据，200字内。", "topic"),
    ("deep_research", "研究稀疏注意力与 FlashAttention 的工程取舍，给出有论文证据的结论，200字内。", "topic"),
    (
        "technology_cabin",
        "围绕长序列推理的显存瓶颈开展技术攻关，聚焦解决路径，比较稀疏注意力与 FlashAttention，结合论文证据，200字内。",
        "topic",
    ),
    ("research_explorer", "调研稀疏注意力与 FlashAttention 的工程取舍，返回有论文证据的发现，200字内。", "topic"),
    (
        "fact_verifier",
        "核验‘FlashAttention 能保证任意硬件上推理速度翻倍’的论断，给出论文证据及边界，200字内。",
        "topic",
    ),
    (
        "title_references",
        "查找 Attention Is All You Need，追溯其引用的基础工作，只扩展一层参考文献并列出来源，200字内。",
        "title",
    ),
    (
        "technology_auth_failure",
        "围绕长序列推理显存瓶颈比较稀疏注意力与 FlashAttention 的解决路径，结合公开证据，200字内。",
        "topic",
    ),
    (
        "technology_preloaded",
        "围绕长序列推理的显存瓶颈开展技术攻关，仅讨论公开技术的解决路径，比较稀疏注意力与 FlashAttention。"
        "结合论文证据，仅在聊天正文回答，200字内，无需平台任务或文件。",
        "topic",
    ),
]


@pytest.mark.skipif(os.getenv("RUN_AMINER_MODEL_PROBE") != "1", reason="显式启用才调用已配置的真实模型")
@pytest.mark.parametrize(
    "case,question,expected_mode", MODEL_ROUTING_CASES, ids=[item[0] for item in MODEL_ROUTING_CASES]
)
async def test_live_model_routes_and_executes_academic_tools(
    academic_db, monkeypatch, tmp_path, case, question, expected_mode
):
    """真实模型自动选择工具；生产主/子图、隔离 PostgreSQL 与模拟 AMiner 完成闭环。"""
    from langchain_core.messages import AIMessage, ToolMessage
    from langgraph.checkpoint.memory import InMemorySaver

    from platform_core.agents.base import BaseAgent
    from platform_core.agents.buildin.chatbot import graph as chatbot_graph
    from platform_core.agents.buildin.chatbot.context import ChatBotContext
    from platform_core.agents.buildin.subagent import graph as subagent_graph
    from platform_core.agents.buildin.subagent.context import SubAgentContext
    from platform_core.agents.context import prepare_agent_runtime_context
    from platform_core.agents.presets import deep_research, weapon_equipment_scheme
    from platform_core.agents.presets.subagents import fact_verifier, research_explorer
    from platform_core.agents.skills import service as skill_service
    from platform_core.agents.toolkits.buildin import academic, tools as tool_module
    from platform_core.models.chat import load_chat_model
    from platform_core.models.providers.cache import model_cache
    from platform_core.services import equipment_deep_integration_service as deep_service
    from platform_core.services.aminer_client import ACADEMIC_TOOL_NAMES
    from platform_core.storage.postgres.manager import pg_manager

    factory, _, manager, root, child, _ = academic_db
    await manager.create_knowledge_tables()
    model_spec = os.environ["AMINER_PROBE_MODEL"]
    assert model_cache.get_model_info(model_spec), "探针必须使用平台已配置的真实模型"
    is_child = case in {"research_explorer", "fact_verifier"}
    is_deep = case.startswith(("deep_", "technology_")) or is_child
    run = child if is_child else root
    async with factory.begin() as db:
        if is_deep:
            (await db.get(AgentRun, root.id)).source = "equipment_deep_research"
        for run_id in (root.id, child.id):
            (await db.get(AgentRun, run_id)).lease_expires_at = utc_now_naive() + timedelta(minutes=10)
    # 只在测试进程隔离数据库和外部 I/O，不修改在线配置、供应商 URL 或 worker。
    monkeypatch.setattr(pg_manager, "get_async_session_context", factory)
    monkeypatch.setattr(BaseAgent, "_get_checkpointer", AsyncMock(return_value=InMemorySaver()))
    monkeypatch.setattr(chatbot_graph, "sync_agent_context_skills", AsyncMock())
    monkeypatch.setattr(subagent_graph, "sync_agent_context_skills", AsyncMock())

    presets = {
        "deep_research": deep_research.SYSTEM_PROMPT,
        "technology_cabin": weapon_equipment_scheme.SYSTEM_PROMPT,
        "technology_auth_failure": weapon_equipment_scheme.SYSTEM_PROMPT,
        "technology_preloaded": weapon_equipment_scheme.SYSTEM_PROMPT,
        "research_explorer": research_explorer.SYSTEM_PROMPT,
        "fact_verifier": fact_verifier.SYSTEM_PROMPT,
    }
    system_prompt = presets.get(case, "")
    if case.startswith("technology_"):
        monkeypatch.setattr(
            deep_service,
            "get_session_research_context",
            AsyncMock(
                return_value={
                    "capability_name": "INTERNAL_PROJECT_DO_NOT_SEND",
                    "capability_sections": [{"content": "INTERNAL_PORTRAIT_DO_NOT_SEND"}],
                }
            ),
        )
        async with factory() as db:
            system_prompt += "\n" + await deep_service.build_system_context(
                db=db,
                user=SimpleNamespace(uid=run.uid),
                session=SimpleNamespace(payload={"knowledge_enabled": False, "subagents_enabled": False}),
                research_section="装备与技术实现",
            )
    context_schema = SubAgentContext if is_child else ChatBotContext
    context_args = dict(
        uid=run.uid,
        run_id=run.id,
        worker_id="owner",
        thread_id=run.conversation_thread_id,
        runtime_scope_id=root.runtime_scope_id,
        workdir_relative_path="projects/aminer-routing-probe",
        workdir_path="/home/gem/user-data/projects/aminer-routing-probe",
        model=model_spec,
        system_prompt=system_prompt,
        tools=[*sorted(ACADEMIC_TOOL_NAMES), "web_search"],
        knowledges=[],
        mcps=[],
        skills=[],
        preload_skills=[],
        model_retry_times=0,
    )
    if not is_child:
        context_args.update(subagents=[], subagents_enabled=False)
    if case == "technology_preloaded":
        # 真实技能安装、权限解析、深研覆盖与预加载；文件安装到 pytest 临时目录。
        monkeypatch.setattr(skill_service, "get_skill_data_dir", lambda: tmp_path)
        async with factory() as db:
            installed = await skill_service.init_builtin_skills(db)
            # 在线迁移已采用 v2 权限；隔离新建库也使用相同权限格式。
            for item in installed:
                item.share_config = skill_service.normalize_skill_share_config(
                    None, operator_uid=run.uid, source_type="builtin"
                )
            await db.commit()
            from platform_core.storage.postgres.models_business import User

            overrides = await deep_service.build_runtime_context_overrides(
                db=db,
                user=await db.scalar(select(User).where(User.uid == run.uid)),
                agent=SimpleNamespace(config_json={"context": weapon_equipment_scheme.PRESET.context}),
                session=SimpleNamespace(payload={"knowledge_enabled": False, "subagents_enabled": False}),
                research_section="装备与技术实现",
            )
        context_args.update(overrides["context"])
        context_args["tools"] = None
        context_args["system_prompt"] = weapon_equipment_scheme.SYSTEM_PROMPT + "\n" + overrides["system_prompt_append"]
    context = await prepare_agent_runtime_context(context_schema(**context_args))
    assert ACADEMIC_TOOL_NAMES.issubset(context.tools)
    if case == "technology_preloaded":
        assert {"deep-research", "equipment-research", "equipment-deep-conversation"}.issubset(context.preload_skills)

    papers = {
        "probe-attention": {
            "id": "probe-attention",
            "title": "Attention Is All You Need",
            "year": 2017,
            "authors": [{"name": "Ashish Vaswani"}],
            "doi": "10.48550/arXiv.1706.03762",
            "venue": {"raw": "NeurIPS"},
            "abstract_slice": "The Transformer relies solely on attention mechanisms.",
        },
        "probe-flash": {
            "id": "probe-flash",
            "title": "FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness",
            "year": 2022,
            "authors": [{"name": "Tri Dao"}],
            "doi": "10.48550/arXiv.2205.14135",
            "abstract_slice": "An IO-aware exact attention algorithm reduces memory reads and writes.",
        },
        "probe-sparse": {
            "id": "probe-sparse",
            "title": "Generating Long Sequences with Sparse Transformers",
            "year": 2019,
            "authors": [{"name": "Rewon Child"}],
            "doi": "10.48550/arXiv.1904.10509",
            "abstract_slice": "Sparse Transformers introduce factorized sparse attention patterns for long sequences. "
            "Sparsity changes token connectivity; engineering gains depend on workload and implementation.",
        },
    }
    http_requests = []

    def aminer_response(request):
        """记录公开查询与分页，不记录 Authorization。"""
        payload = json.loads(request.content) if request.method == "POST" else dict(request.url.params)
        http_requests.append({"path": request.url.path.rsplit("/paper/", 1)[-1], "payload": payload})
        assert "INTERNAL_" not in json.dumps(payload), "内部上下文被发送给论文服务"
        if case == "technology_auth_failure":
            return httpx.Response(200, json={"code": 40307, "success": False, "data": []})
        path = http_requests[-1]["path"]
        if path == "search":
            title = payload["title"].lower()
            selected = "probe-flash" if "flash" in title else "probe-sparse" if "sparse" in title else "probe-attention"
            data = [papers[selected]]
        elif path == "search/pro":
            data = list(papers.values())
        elif path == "info":
            data = [papers[paper_id] for paper_id in payload["ids"] if paper_id in papers]
        elif path == "detail":
            paper = papers[payload["id"]]
            data = [
                {
                    **paper,
                    "abstract": paper["abstract_slice"]
                    + " The reported results are bounded to the paper's evaluated settings; "
                    "hardware and workload affect speedups. This abstract does not establish "
                    "a universal twofold inference speedup, nor provide deployment measurements.",
                }
            ]
        else:
            data = [
                {
                    "id": payload["id"],
                    "cited": [
                        {
                            "id": "probe-bahdanau",
                            "title": "Neural Machine Translation by Jointly Learning to Align and Translate",
                            "year": 2015,
                            "doi": "10.48550/arXiv.1409.0473",
                        }
                    ],
                }
            ]
        return httpx.Response(200, json={"code": 200, "success": True, "data": data})

    transport = httpx.MockTransport(aminer_response)
    monkeypatch.setattr(
        academic,
        "AcademicRetrievalService",
        lambda ctx: AcademicRetrievalService(ctx, session_factory=factory, transport=transport),
    )
    web_requests = []

    def web_response(_primary, arguments):
        """网页保留独立可用的来源，用于验证论文故障降级。"""
        web_requests.append(arguments)
        return {
            "status": "ok",
            "results": [
                {
                    "title": "FlashAttention original paper",
                    "url": "https://arxiv.org/abs/2205.14135",
                    "content": "FlashAttention is an IO-aware exact attention algorithm. "
                    "Gains depend on hardware and workload; "
                    "the source does not guarantee a universal 2x inference speedup.",
                }
            ],
        }

    monkeypatch.setattr(tool_module, "_resilient_web_search", web_response)
    model_requests = []

    async def record_model_request(request):
        """仅记录模型收到的工具名，不保存密钥或推理。"""
        body = json.loads(request.content)
        model_requests.append([tool["function"]["name"] for tool in body.get("tools", [])])

    started = monotonic()
    async with httpx.AsyncClient(timeout=90, event_hooks={"request": [record_model_request]}) as client:
        model = load_chat_model(
            model_spec,
            session_id=context.thread_id,
            http_async_client=client,
            max_retries=0,
            timeout=90,
            max_tokens=1800,
        )
        monkeypatch.setattr(chatbot_graph, "load_chat_model", lambda **_: model)
        monkeypatch.setattr(subagent_graph, "load_chat_model", lambda **_: model)
        agent = subagent_graph.SubAgentBackend() if is_child else chatbot_graph.ChatbotAgent()
        graph = await agent.get_graph(context=context)
        async with asyncio.timeout(240):
            result = await graph.ainvoke(
                {"messages": [("user", question)]},
                config={
                    "configurable": {"thread_id": context.thread_id},
                    "recursion_limit": context.max_execution_steps,
                },
                context=context,
            )

    calls = [call for message in result["messages"] if isinstance(message, AIMessage) for call in message.tool_calls]
    academic_calls = [call for call in calls if call["name"] in ACADEMIC_TOOL_NAMES]
    tool_results = [
        json.loads(message.content)
        for message in result["messages"]
        if isinstance(message, ToolMessage) and message.name in ACADEMIC_TOOL_NAMES
    ]
    answer = result["messages"][-1].text
    async with factory() as db:
        ledger = list((await db.scalars(select(AcademicRetrievalCall))).all())
    report = {
        "case": case,
        "model": model_spec,
        "question": question,
        "tool_calls": calls,
        "http_requests": http_requests,
        "model_requests": len(model_requests),
        "web_calls": len(web_requests),
        "cost_cents": sum(item.cost_cents for item in ledger),
        "root_budget_shared": all(item.root_run_id == root.id for item in ledger),
        "seconds": round(monotonic() - started, 2),
        "answer": answer,
        "tool_results": tool_results,
        "preloaded_skills": context.preload_skills,
        "aminer_transport": "httpx.MockTransport",
        "checkpointer": "InMemorySaver",
        "live_aminer_calls": 0,
    }
    if report_dir := os.getenv("AMINER_PROBE_REPORT_DIR"):
        output = Path(report_dir)
        output.mkdir(parents=True, exist_ok=True)
        (output / f"{case}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                key: value
                for key, value in report.items()
                if key not in {"answer", "tool_calls", "http_requests", "tool_results"}
            },
            ensure_ascii=False,
        )
    )
    assert answer.strip() and not result["messages"][-1].tool_calls, "模型没有收敛为最终答案"
    obtained_sources = {
        paper[field]
        for tool_result in tool_results
        for paper in tool_result.get("results", [])
        for field in ("url", "doi")
        if paper.get(field)
    }
    if web_requests:
        obtained_sources.add("https://arxiv.org/abs/2205.14135")
    cited_sources = re.findall(r"""<cite\b[^>]*\bsource=["']([^"']+)["']""", answer)
    assert all(unescape(source) in obtained_sources for source in cited_sources), "引用不在本轮取得的来源中"
    assert report["root_budget_shared"] and report["cost_cents"] <= (50 if is_deep else 20)
    if expected_mode is None:
        assert not academic_calls and not http_requests
        return
    searches = [call for call in academic_calls if call["name"] == "academic_search"]
    assert searches
    if expected_mode == "title":
        assert searches[0]["args"].get("mode", "topic") == "title"
    # 技术名已知时可先定位已知标题，再做主题发现；并行 HTTP 不保证先后顺序。
    for request in http_requests:
        if request["path"] in {"search", "search/pro"}:
            assert request["payload"]["page"] == ("1" if request["path"] == "search" else "0")
            query_key = "title" if request["path"] == "search" else "keyword"
            assert any(
                call["args"]["query"] == request["payload"][query_key]
                and call["args"].get("mode", "topic") == ("title" if query_key == "title" else "topic")
                for call in searches
            )
    if case == "technology_auth_failure":
        first_batch = next(
            message.tool_calls
            for message in result["messages"]
            if isinstance(message, AIMessage) and message.tool_calls
        )
        first_searches = [call for call in first_batch if call["name"] == "academic_search"]
        assert all(item["status"] == "auth_failed" for item in tool_results)
        assert len(http_requests) == len(first_searches), "鉴权失败后又发起了论文请求"
        assert all(item.attempt_no == 1 for item in ledger), "鉴权错误发生了重试"
        assert web_requests and "https://arxiv.org/abs/2205.14135" in answer
        assert all(not ACADEMIC_TOOL_NAMES.intersection(names) for names in model_requests[1:])
    else:
        if case == "title_references":
            assert any(call["name"] == "academic_get_references" for call in academic_calls)
            assert "1409.0473" in answer
        else:
            assert any(
                item["content_level"] == "abstract" for result in tool_results for item in result.get("results", [])
            ), "未读取拟引用论文完整摘要"
        assert '<cite source="' in answer and any(
            source in answer for source in ("10.48550/arXiv.", "https://arxiv.org/abs/2205.14135")
        )
        if case == "fact_verifier":
            assert "A100" not in answer and "2–4" not in answer and "2-4" not in answer, (
                "精确实验数据未在本轮证据中取得"
            )
