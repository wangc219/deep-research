"""equipment deep research 原生 AgentRun 适配层测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from platform_core.services import equipment_deep_integration_service as service


def _s6_portrait(*, suffix: str = "") -> str:
    bodies = {
        "概述": "面向复杂对抗场景说明装备对象定位传统方式失效原因以及引入后的关键任务变化" * 3,
        "装备与技术实现": "采用主备技术路径明确总体构型分系统关键部件接口工程依赖与路线取舍" * 3,
        "关键作战流程": "任务单元按触发条件完成发现决策进入作用评估异常处置以及状态转段闭环" * 3,
        "形成能力与作战效果": "形成新增任务能力直接战果体系收益迫使敌方付出代价并给出可观察判据" * 3,
        "制胜逻辑机理": "改变旧有规则闭合作用链与交换关系分析对手经济反制及其必须承担的新代价" * 3,
    }
    return "\n".join(f"{label}{suffix}：{body}" for label, body in bodies.items())


@pytest.mark.asyncio
async def test_global_read_keeps_research_and_branch_owner(monkeypatch):
    """管理员查看上下文时使用实际所有者，避免能力版本和分支历史丢失。"""
    parent = SimpleNamespace(owner_uid="owner", payload={"thread_id": "parent-thread"})
    session = SimpleNamespace(
        id="session-1",
        owner_uid="owner",
        run_id="run-1",
        payload={"parent_session_id": "parent-session", "branch_from_message_id": "message-1"},
    )
    run = SimpleNamespace(
        id="run-1",
        owner_uid="owner",
        payload={},
        topic="民用设备维护",
        status="completed",
        research_route="auto",
        readonly=False,
    )
    repo = SimpleNamespace(
        get_run=AsyncMock(return_value=run),
        get_deep_session=AsyncMock(return_value=parent),
        list_capability_versions_for_run=AsyncMock(return_value=[]),
        list_artifact_refs=AsyncMock(return_value=[]),
    )
    conversations = SimpleNamespace(
        get_conversation_by_thread_id=AsyncMock(return_value=SimpleNamespace(id=1, uid="owner")),
        get_messages=AsyncMock(return_value=[SimpleNamespace(id="message-1", role="user", content="维护记录")]),
    )
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda db: repo)
    monkeypatch.setattr(service, "ConversationRepository", lambda db: conversations)
    result = await service.get_session_research_context(
        db=object(),
        user=SimpleNamespace(uid="manager", role="admin"),
        session=session,
    )
    repo.list_capability_versions_for_run.assert_awaited_once_with(owner_uid="owner", run_id="run-1", limit=12)
    assert result["branch_context"]
    conversations.get_messages.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_missing_deep_research_preset_fails_without_committing(monkeypatch) -> None:
    """请求事务内不临时初始化预置 Agent，避免仓储隐式提交。"""

    class Repository:
        def __init__(self, db):
            del db

        async def get_visible_by_slug(self, **kwargs):
            assert kwargs["slug"] == service.DEEP_AGENT_SLUG
            return None

        async def ensure_preset(self, *args, **kwargs):
            raise AssertionError("深研请求不能在业务事务中初始化预置 Agent")

    monkeypatch.setattr(service, "AgentRepository", Repository)

    with pytest.raises(HTTPException) as exc_info:
        await service.resolve_deep_agent(
            db=object(),
            user=SimpleNamespace(uid="user-1"),
            requested_slug=None,
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "深研智能体尚未完成初始化"


@pytest.mark.asyncio
async def test_runtime_overrides_enforce_knowledge_and_subagent_isolation(monkeypatch) -> None:
    """关闭知识库和 Subagent 时从 Skill、知识范围和工具装配三个层面隔离。"""
    monkeypatch.setattr(
        service,
        "resolve_agent_resource_options",
        AsyncMock(
            return_value={
                "skills": [
                    {"key": "custom-analysis"},
                    {"key": "deep-research"},
                    {"key": "equipment-research"},
                    {"key": "equipment-deep-conversation"},
                    {"key": "knowledge-base"},
                ]
            }
        ),
    )
    monkeypatch.setattr(service, "build_system_context", AsyncMock(return_value="hidden equipment context"))
    agent = SimpleNamespace(
        config_json={
            "context": {
                "skills": ["custom-analysis", "knowledge-base"],
                "preload_skills": ["custom-analysis", "knowledge-base"],
                "knowledges": ["kb-secret"],
            }
        }
    )
    session = SimpleNamespace(payload={"knowledge_enabled": False, "subagents_enabled": False})

    overrides = await service.build_runtime_context_overrides(
        db=object(),
        user=SimpleNamespace(uid="user-1"),
        agent=agent,
        session=session,
        active_skill_ids=["custom-analysis", "knowledge-base"],
    )

    assert overrides["system_prompt_append"] == "hidden equipment context"
    assert overrides["context"]["knowledges"] == []
    assert overrides["context"]["subagents_enabled"] is False
    assert "knowledge-base" not in overrides["context"]["skills"]
    assert "knowledge-base" not in overrides["context"]["preload_skills"]
    assert {
        "custom-analysis",
        "deep-research",
        "equipment-research",
        "equipment-deep-conversation",
    } <= set(overrides["context"]["skills"])


@pytest.mark.asyncio
async def test_runtime_overrides_use_session_knowledge_scope_without_retrieval(monkeypatch) -> None:
    """深研会话只绑定运行级知识库 ID，不在上下文构建阶段预取正文。"""
    monkeypatch.setattr(
        service,
        "resolve_agent_resource_options",
        AsyncMock(return_value={"skills": [{"key": "knowledge-base"}]}),
    )
    monkeypatch.setattr(service, "build_system_context", AsyncMock(return_value="equipment context"))
    agent = SimpleNamespace(
        config_json={
            "context": {
                "skills": ["knowledge-base"],
                "knowledges": ["kb-agent-default"],
            }
        }
    )
    session = SimpleNamespace(
        payload={
            "knowledge_enabled": True,
            "knowledge_ids": [" kb-run-a ", "kb-run-b", "kb-run-a"],
        }
    )

    overrides = await service.build_runtime_context_overrides(
        db=object(),
        user=SimpleNamespace(uid="user-1"),
        agent=agent,
        session=session,
    )

    assert overrides["context"]["knowledges"] == ["kb-run-a", "kb-run-b"]
    assert overrides["system_prompt_append"] == "equipment context"


@pytest.mark.asyncio
async def test_native_conversation_request_restores_deep_binding_for_generic_chat(monkeypatch) -> None:
    """从平台原生聊天入口继续深研时仍恢复领域来源与能力上下文。"""

    deep_session = SimpleNamespace(
        id="thinking-1",
        owner_uid="user-1",
        run_id="run-1",
        payload={
            "thread_id": "equipment-deep-thread-1",
            "agent_slug": "deep-research",
            "focus": "体系协同",
            "active_skill_ids": ["equipment-research"],
            "model_spec": "old-model",
        },
        updated_at=None,
    )

    class Repository:
        def __init__(self, db):
            del db

        async def get_deep_session(self, session_id):
            assert session_id == "thinking-1"
            return deep_session

    build_overrides = AsyncMock(return_value={"system_prompt_append": "equipment context", "context": {}})
    monkeypatch.setattr(service, "EquipmentResearchRepository", Repository)
    monkeypatch.setattr(service, "build_runtime_context_overrides", build_overrides)

    binding = await service.resolve_native_conversation_request_binding(
        db=object(),
        user=SimpleNamespace(uid="user-1", role="user"),
        conversation=SimpleNamespace(
            uid="user-1",
            thread_id="equipment-deep-thread-1",
            agent_id="deep-research",
            extra_metadata={
                "source": "equipment_deep_research",
                "equipment_deep_session_id": "thinking-1",
            },
        ),
        agent=SimpleNamespace(),
        request_metadata={"equipment_create_artifact": True},
        model_spec="new-model",
    )

    assert binding is not None
    assert binding.source == "equipment_deep_research"
    assert binding.external_id == "thinking-1"
    assert binding.origin_metadata == {
        "equipment_deep_session_id": "thinking-1",
        "equipment_run_id": "run-1",
        "equipment_deep_mode": "section_deepen",
        "equipment_deep_section": "",
    }
    assert binding.runtime_context_overrides["system_prompt_append"] == "equipment context"
    assert binding.request_metadata == {
        "equipment_deep_session_id": "thinking-1",
        "equipment_create_artifact": True,
        "equipment_deep_mode": "section_deepen",
        "equipment_deep_section": "",
    }
    assert deep_session.payload["model_spec"] == "new-model"
    build_overrides.assert_awaited_once()
    override_kwargs = build_overrides.await_args.kwargs
    assert override_kwargs["session"] is deep_session
    assert override_kwargs["focus"] == "体系协同"
    assert override_kwargs["active_skill_ids"] == ["equipment-research"]
    assert override_kwargs["create_artifact"] is True
    assert override_kwargs["research_mode"] == "section_deepen"
    assert override_kwargs["research_section"] == ""


@pytest.mark.asyncio
async def test_archived_deep_session_rejects_generic_native_chat_write(monkeypatch) -> None:
    """归档只读必须在领域绑定层强制，不能只依赖装备页的按钮禁用。"""

    archived = SimpleNamespace(
        id="thinking-archived",
        owner_uid="user-1",
        run_id="run-1",
        payload={
            "status": "archived",
            "thread_id": "equipment-deep-thread-archived",
            "agent_slug": "deep-research",
        },
    )
    repository = SimpleNamespace(get_deep_session=AsyncMock(return_value=archived))
    monkeypatch.setattr(service, "EquipmentResearchRepository", lambda _db: repository)

    with pytest.raises(HTTPException) as exc_info:
        await service.resolve_native_conversation_request_binding(
            db=object(),
            user=SimpleNamespace(uid="user-1", role="user"),
            conversation=SimpleNamespace(
                uid="user-1",
                thread_id="equipment-deep-thread-archived",
                agent_id="deep-research",
                extra_metadata={
                    "source": "equipment_deep_research",
                    "equipment_deep_session_id": "thinking-archived",
                },
            ),
            agent=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 409
    assert "已归档" in exc_info.value.detail


@pytest.mark.asyncio
async def test_native_chat_mention_narrows_scope_without_dropping_deep_context(monkeypatch) -> None:
    """通用聊天入口的 @知识库 只收窄范围，不能覆盖深研系统能力绑定。"""
    deep_session = SimpleNamespace(
        id="thinking-1",
        owner_uid="user-1",
        run_id="run-1",
        payload={
            "thread_id": "equipment-deep-thread-1",
            "agent_slug": "deep-research",
            "knowledge_enabled": True,
            "knowledge_ids": ["kb-a"],
        },
        updated_at=None,
    )

    class Repository:
        def __init__(self, db):
            del db

        async def get_deep_session(self, session_id):
            assert session_id == "thinking-1"
            return deep_session

    base_overrides = {
        "system_prompt_append": "equipment context",
        "context": {
            "skills": ["equipment-research", "knowledge-base"],
            "preload_skills": ["equipment-research", "knowledge-base"],
            "subagents_enabled": True,
            "knowledges": ["kb-a"],
        },
    }
    monkeypatch.setattr(service, "EquipmentResearchRepository", Repository)
    monkeypatch.setattr(
        service,
        "build_runtime_context_overrides",
        AsyncMock(return_value=base_overrides),
    )

    binding = await service.resolve_native_conversation_request_binding(
        db=object(),
        user=SimpleNamespace(uid="user-1", role="user"),
        conversation=SimpleNamespace(
            uid="user-1",
            thread_id="equipment-deep-thread-1",
            agent_id="deep-research",
            extra_metadata={
                "source": "equipment_deep_research",
                "equipment_deep_session_id": "thinking-1",
            },
        ),
        agent=SimpleNamespace(),
        runtime_context_overrides={"context": {"knowledges": ["kb-a", "kb-outside"]}},
    )

    assert binding is not None
    assert binding.runtime_context_overrides["system_prompt_append"] == "equipment context"
    assert binding.runtime_context_overrides["context"]["knowledges"] == ["kb-a"]
    assert binding.runtime_context_overrides["context"]["skills"] == [
        "equipment-research",
        "knowledge-base",
    ]
    assert binding.runtime_context_overrides["context"]["subagents_enabled"] is True


@pytest.mark.asyncio
async def test_native_conversation_request_ignores_unbound_platform_chat() -> None:
    binding = await service.resolve_native_conversation_request_binding(
        db=object(),
        user=SimpleNamespace(uid="user-1", role="user"),
        conversation=SimpleNamespace(extra_metadata={"source": "chat"}),
        agent=SimpleNamespace(),
    )

    assert binding is None


@pytest.mark.asyncio
async def test_system_context_uses_bound_material_as_open_divergence_baseline(monkeypatch) -> None:
    """绑定材料提供启发基线，但不能把新质装备发散框死在原卡内。"""
    monkeypatch.setattr(service, "get_session_research_context", AsyncMock(return_value={"session_id": "thinking-1"}))
    session = SimpleNamespace(
        payload={
            "capability_name": "相变黏弹拒飞弹",
            "capability_sections": [{"label": "装备与技术实现", "text": "材料作用体积。"}],
            "reference_weapons": [
                {
                    "hypothesis_id": "hyp-reference",
                    "title": "折叠环网空域拦截弹",
                    "overview": "区域网幕拦截。",
                }
            ],
        }
    )

    prompt = await service.build_system_context(
        db=object(),
        user=SimpleNamespace(uid="user-1", role="user"),
        session=session,
        research_mode="new_weapon_diverge",
    )

    assert "未来战争态势" in prompt
    assert "制胜优势、制衡对手" in prompt
    assert "现有装备目录、能力画像、参考武器和既有技术路线只是启发基线" in prompt
    assert "当前已注入能力画像卡「相变黏弹拒飞弹」及所绑定栏目" in prompt
    assert "不是新质装备候选边界" in prompt
    assert "折叠环网空域拦截弹" in prompt
    assert "仅作为对照与启发基线" in prompt
    assert "可以从其边界反推正交的新质装备方向" in prompt


@pytest.mark.asyncio
async def test_system_context_defaults_to_locked_section_deepening(monkeypatch) -> None:
    """旧请求缺少模式时采取保守默认，不得把栏目深挖改写成另一装备。"""
    monkeypatch.setattr(
        service,
        "get_session_research_context",
        AsyncMock(return_value={"session_id": "thinking-locked"}),
    )
    session = SimpleNamespace(
        payload={
            "capability_name": "相变黏弹拒飞弹",
            "capability_sections": [{"label": "装备与技术实现", "text": "材料作用体积。"}],
        }
    )

    prompt = await service.build_system_context(
        db=object(),
        user=SimpleNamespace(uid="user-1", role="user"),
        session=session,
        research_section="装备与技术实现",
    )

    assert "section_deepen（深化当前装备）" in prompt
    assert "研究目标是「装备与技术实现」栏目" in prompt
    assert "不得擅自改写为另一种武器装备" in prompt
    assert "研发该武器的关键技术卡点和工程痛点" in prompt
    assert "同步推演作战流程和制胜逻辑" in prompt
    assert "不得机械凑齐固定模板" in prompt
    assert "技术攻关舱通用工程化契约" in prompt
    for chapter in [
        "能力目标",
        "装备总体设计",
        "技术体系",
        "关键技术识别",
        "突破难点",
        "解决路径",
        "具体实现",
    ]:
        assert chapter in prompt
    assert "前一级结论成为后一级输入" in prompt
    assert "不得跳过能力目标直接罗列技术" in prompt
    assert "分系统、输入输出接口、指标与预算" in prompt
    assert "WBS、试验矩阵" in prompt
    assert "30/60/90天启动包" in prompt
    assert "工程假设/TBD" in prompt
    assert "不得覆盖原交付物" in prompt
    assert "当前已锁定能力画像卡「相变黏弹拒飞弹」" in prompt
    assert "不是新质装备候选边界" not in prompt


def test_research_mode_normalization_is_whitelisted_and_conservative() -> None:
    assert service.normalize_deep_research_mode("new_weapon_diverge") == "new_weapon_diverge"
    assert service.normalize_deep_research_mode("section_deepen") == "section_deepen"
    assert service.normalize_deep_research_mode("unexpected") == "section_deepen"


@pytest.mark.asyncio
async def test_system_context_documents_memory_as_read_only_command(monkeypatch) -> None:
    """平台 Agent 应理解 /memory 只读记忆，不能把它误当作新一轮研究。"""
    monkeypatch.setattr(service, "get_session_research_context", AsyncMock(return_value={}))

    prompt = await service.build_system_context(
        db=object(),
        user=SimpleNamespace(uid="user-1", role="user"),
        session=SimpleNamespace(payload={}),
    )

    assert "/memory 表示只读查看当前决策记忆中的候选方向、裁决与待追问" in prompt
    assert "且不启动新的发散或议事" in prompt


@pytest.mark.asyncio
async def test_system_context_enforces_s6_contract_during_card_authoring(monkeypatch) -> None:
    monkeypatch.setattr(service, "get_session_research_context", AsyncMock(return_value={}))

    prompt = await service.build_system_context(
        db=object(),
        user=SimpleNamespace(uid="user-1", role="user"),
        session=SimpleNamespace(payload={}),
        create_artifact=True,
    )

    for _key, label in service.S6_PORTRAIT_MODULES:
        assert label in prompt
    assert "先按五栏分别起草，再逐栏检查" in prompt
    assert "360–400 个有效中文字" in prompt
    assert "栏名后缀" in prompt
    assert "capability_portrait_modules" in prompt
    assert "capability_card_draft" in prompt


@pytest.mark.asyncio
async def test_system_context_asks_before_creating_a_new_card(monkeypatch) -> None:
    monkeypatch.setattr(service, "get_session_research_context", AsyncMock(return_value={}))

    prompt = await service.build_system_context(
        db=object(),
        user=SimpleNamespace(uid="user-1", role="user"),
        session=SimpleNamespace(payload={}),
        create_artifact=False,
    )

    assert "询问用户是否" in prompt
    assert "新的待核验能力卡" in prompt
    assert "不要每轮机械询问" in prompt
    assert "当前消息已经明确确认更新或成卡" in prompt


@pytest.mark.asyncio
async def test_system_context_requires_public_search_with_source_traceability(monkeypatch) -> None:
    """深研事实性结论必须使用公网检索并保留可追溯来源。"""
    monkeypatch.setattr(service, "get_session_research_context", AsyncMock(return_value={}))

    prompt = await service.build_system_context(
        db=object(),
        user=SimpleNamespace(uid="user-1", role="user"),
        session=SimpleNamespace(payload={}),
    )

    assert "本会话已启用公网检索能力" in prompt
    assert "必须优先调用 web_search" in prompt
    assert "至少两个独立来源交叉核验" in prompt
    assert "保留可点击的原始 URL" in prompt


@pytest.mark.asyncio
async def test_system_context_respects_agent_request_prompt_limit(monkeypatch) -> None:
    """大能力卡上下文也必须能通过 AgentRun 的 12k 字符入口校验。"""
    monkeypatch.setattr(
        service,
        "get_session_research_context",
        AsyncMock(return_value={"capability_sections": ["复杂电磁环境验证字段" * 2000]}),
    )

    prompt = await service.build_system_context(
        db=object(),
        user=SimpleNamespace(uid="user-1", role="user"),
        session=SimpleNamespace(payload={}),
    )

    assert len(prompt) <= 12_000
    assert prompt.endswith("</equipment_research_context>")
    assert "复杂电磁环境验证字段" in prompt


@pytest.mark.asyncio
async def test_save_capability_draft_adds_pending_version_without_mutating_history(monkeypatch) -> None:
    """能力沉淀只新增待核验版本，不覆盖已有版本。"""
    existing = SimpleNamespace(snapshot={"version_no": 3, "status": "verified"})
    deep_session = SimpleNamespace(
        id="thinking-1",
        project_id="project-1",
        owner_uid="user-1",
        run_id="run-1",
        payload={
            "capability_card_key": "cap-formal-1",
            "capability_name": "正式原卡",
        },
    )
    captured = {}

    class Repository:
        def __init__(self, db):
            del db

        async def get_deep_session(self, session_id):
            assert session_id == "thinking-1"
            return deep_session

        async def list_capability_versions_for_run(self, **kwargs):
            assert kwargs == {"owner_uid": "user-1", "run_id": "run-1", "limit": 100}
            return [existing]

        async def add_capability_version(self, version):
            captured["version"] = version
            return version

    db = SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(service, "EquipmentResearchRepository", Repository)

    result = await service.save_capability_draft(
        db=db,
        user=SimpleNamespace(uid="user-1", role="user"),
        session_id="thinking-1",
        name="协同探测能力",
        capability_image=_s6_portrait(),
        rationale="由三类证据交叉验证。",
        evidence_refs=["artifact-1", "artifact-1", "kb-2"],
        structured_fields={"metric": {"latency": "2s"}},
    )

    snapshot = captured["version"].snapshot
    assert existing.snapshot == {"version_no": 3, "status": "verified"}
    assert snapshot["version_no"] == 4
    assert snapshot["status"] == "pending_verification"
    assert snapshot["session_id"] == "thinking-1"
    assert snapshot["parent_capability_id"] == "cap-formal-1"
    assert snapshot["parent_capability_name"] == "正式原卡"
    assert snapshot["evidence_refs"] == ["artifact-1", "kb-2"]
    assert snapshot["deep_capability_portrait"] == snapshot["capability_image"]
    assert list(snapshot["capability_portrait_modules"]) == [
        "overview",
        "technology_implementation",
        "operational_process",
        "capability_effects",
        "winning_logic",
    ]
    assert snapshot["capability_card_draft"] == snapshot["capability_portrait_modules"]
    assert snapshot["structured_fields"]["metric"] == {"latency": "2s"}
    assert snapshot["structured_fields"]["s6_portrait_quality"]["below_soft_target"]
    assert result["snapshot"] == snapshot
    db.commit.assert_awaited_once()


def test_s6_draft_normalizes_suffixed_out_of_order_headings() -> None:
    rows = _s6_portrait(suffix="（修订）").splitlines()

    portrait, modules, structured = service.normalize_s6_capability_draft(
        capability_image="\n".join([rows[0], rows[1], rows[4], rows[2], rows[3]]),
        structured_fields={},
    )

    assert [row.split("：", 1)[0] for row in portrait.splitlines()] == [
        "概述",
        "装备与技术实现",
        "关键作战流程",
        "形成能力与作战效果",
        "制胜逻辑机理",
    ]
    assert list(modules) == [key for key, _label in service.S6_PORTRAIT_MODULES]
    assert structured["capability_portrait_modules"] == modules
    assert structured["capability_card_draft"] == modules
    assert "修订" not in portrait


@pytest.mark.parametrize(
    ("portrait", "detail"),
    [
        ("\n".join(_s6_portrait().splitlines()[:-1]), "缺少：制胜逻辑机理"),
        (_s6_portrait() + "\n概述：重复栏目" * 30, "重复栏目：概述"),
        (
            "\n".join(
                [
                    "概述：太短",
                    *_s6_portrait().splitlines()[1:],
                ]
            ),
            "栏目明显过短：概述",
        ),
    ],
)
def test_s6_draft_rejects_structurally_invalid_portraits(portrait: str, detail: str) -> None:
    with pytest.raises(HTTPException) as exc_info:
        service.normalize_s6_capability_draft(
            capability_image=portrait,
            structured_fields={},
        )

    assert exc_info.value.status_code == 422
    assert detail in str(exc_info.value.detail)


def test_s6_draft_accepts_complete_structured_modules_without_prose() -> None:
    source = _s6_portrait()
    parsed, duplicates = service._parse_s6_portrait_text(source)
    assert not duplicates

    portrait, modules, _structured = service.normalize_s6_capability_draft(
        capability_image="",
        structured_fields={"capability_portrait_modules": parsed},
    )

    assert portrait.startswith("概述：")
    assert modules == parsed
