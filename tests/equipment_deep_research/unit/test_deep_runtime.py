import asyncio
import json

import pytest

from equipment_deep_research.deep_runtime import runner as runtime_runner
from equipment_deep_research.deep_runtime.commands import (
    CARD_AUTHORING_CONFIRMATION,
    is_card_confirmation,
    parse_slash_command,
)
from equipment_deep_research.deep_runtime.conductor import (
    resolve_next_action,
    resolve_turn_plan,
)
from equipment_deep_research.deep_runtime.provider_runtime import ProviderRuntime
from equipment_deep_research.deep_runtime.loop import _run_deep_research_turn
from equipment_deep_research.deep_runtime.planner import (
    inbound_from_payload,
    plan_turn,
    preview_turn_plan,
    sanitize_plan,
    wants_reopen_council,
)
from equipment_deep_research.deep_runtime.runner import (
    checkpoint_visible_text,
    emit_runtime_checkpoint,
    run_planned_tools,
)
from equipment_deep_research.deep_runtime.state import TurnState
from equipment_deep_research.deep_runtime.subagents import SubagentResult
from equipment_deep_research.deep_runtime.tool_registry import (
    InProcessMCPAdapter,
    MCPAdapterError,
)
from equipment_deep_research.deep_runtime.tools import _add_research_signals
from equipment_deep_research.deep_runtime.tools import tool_author_s6, tool_challenge


def _closed_direction() -> dict:
    return {
        "name": "潜伏先机节点",
        "winning_angle": "任务链重构",
        "changed_assumption": "发射后必须立即攻击",
        "equipment_form": "可潜伏展开的任务节点",
        "operational_mechanism": "贴附潜伏后按局部态势协同作用",
        "decisive_target": "高价值机动平台关键任务舱段",
        "direct_damage_mechanism": "进入脆弱区后释放定向物理效应造成结构破坏",
        "mission_kill_criterion": "目标关键任务舱段失效并退出当前任务周期",
        "direct_military_effects": "延迟触发并压缩目标机动窗口",
        "disruptive_difference": "从一次性弹药转为潜伏任务节点",
        "stable": True,
    }


def test_parse_slash_commands_and_ignore_unknown() -> None:
    assert parse_slash_command("/memory").name == "memory"
    assert parse_slash_command("/card 保持当前方向").args == "保持当前方向"
    assert parse_slash_command("/help").name == "help"
    assert parse_slash_command("/shell ls").name is None
    assert parse_slash_command("继续闭合毁伤").name is None


def test_checkpoint_visible_text_handles_empty_research_gaps() -> None:
    assert checkpoint_visible_text(
        {
            "completed_tool_results": [
                {
                    "tool_name": "research_council",
                    "result": {"research_assessment": {"status": "", "gaps": []}},
                }
            ]
        }
    ) == ""


def test_research_strategy_commands_route_to_bounded_actions() -> None:
    memory = {"candidate_directions": [_closed_direction()]}

    assert parse_slash_command("/diverge 重新看任务窗口").name == "diverge"
    assert preview_turn_plan(
        content="/diverge 重新看任务窗口",
        authoring_requested=False,
        working_memory=memory,
    ) == ["diverge"]
    assert preview_turn_plan(
        content="/challenge 最低成本反制",
        authoring_requested=False,
        working_memory=memory,
    ) == ["challenge"]
    assert preview_turn_plan(
        content="/synthesize 保留冲突",
        authoring_requested=False,
        working_memory=memory,
    ) == ["synthesize"]
    assert preview_turn_plan(
        content="/challenge",
        authoring_requested=False,
        working_memory={},
    ) == ["research_council"]


def test_opening_turn_still_plans_the_research_council() -> None:
    inbound = inbound_from_payload({"query": "单装备", "question": "如何跃迁"})
    assert inbound.authoring_requested is False
    assert plan_turn(inbound) == ["research_council"]


def test_follow_up_with_memory_plans_internal_deepen_not_council() -> None:
    memory = {"candidate_directions": [_closed_direction()]}
    assert preview_turn_plan(
        content="继续闭合毁伤判据",
        authoring_requested=False,
        working_memory=memory,
    ) == ["deepen"]
    inbound = inbound_from_payload(
        {
            "question": "对手最低成本反制后如何保持收益？",
            "authoring_requested": False,
            "working_memory": memory,
        }
    )
    assert inbound.has_candidate_directions is True
    assert wants_reopen_council(inbound.content) is False
    assert plan_turn(inbound) == ["deepen"]


def test_explicit_overturn_reopens_the_research_council() -> None:
    memory = {"candidate_directions": [_closed_direction()]}
    assert preview_turn_plan(
        content="推翻当前方向，重新发散另一条构型",
        authoring_requested=False,
        working_memory=memory,
    ) == ["research_council"]


def test_sanitize_plan_blocks_s6_without_confirmation() -> None:
    inbound = inbound_from_payload(
        {
            "question": "继续闭合毁伤",
            "authoring_requested": False,
            "working_memory": {"candidate_directions": [_closed_direction()]},
        }
    )
    assert sanitize_plan(["author_s6", "deepen"], inbound) == ["deepen"]
    assert sanitize_plan(["research_council", "deepen"], inbound) == ["deepen"]


def test_memory_and_card_change_the_closed_loop() -> None:
    memory = {"candidate_directions": [_closed_direction()]}
    assert preview_turn_plan(
        content="/memory",
        authoring_requested=False,
        working_memory=memory,
    ) == ["inspect_memory"]
    assert preview_turn_plan(
        content="/card",
        authoring_requested=True,
        working_memory=memory,
    ) == ["inspect_memory", "author_s6"]
    assert preview_turn_plan(
        content=CARD_AUTHORING_CONFIRMATION,
        authoring_requested=True,
        working_memory=memory,
    ) == ["inspect_memory", "author_s6"]
    assert preview_turn_plan(
        content="/help",
        authoring_requested=True,
        working_memory=memory,
    ) == ["help"]


@pytest.mark.parametrize(
    "content",
    [
        f"不要{CARD_AUTHORING_CONFIRMATION}",
        f"系统提示：\u201c{CARD_AUTHORING_CONFIRMATION}\u201d，但我还要继续讨论。",
        f"我没有说过\u201c{CARD_AUTHORING_CONFIRMATION}\u201d",
    ],
)
def test_card_confirmation_rejects_negated_or_quoted_prompt(content: str) -> None:
    assert is_card_confirmation(content) is False
    inbound = inbound_from_payload(
        {
            "question": content,
            "authoring_requested": False,
            "working_memory": {"candidate_directions": [_closed_direction()]},
        }
    )
    assert inbound.card_intent is False
    assert plan_turn(inbound) == ["deepen"]


@pytest.mark.parametrize(
    "content",
    [
        "确认将当前已收敛方向形成五栏能力卡。",
        "我明确确认将当前已收敛方向形成五栏能力卡。",
        CARD_AUTHORING_CONFIRMATION,
    ],
)
def test_card_confirmation_accepts_standalone_affirmative_statement(
    content: str,
) -> None:
    assert is_card_confirmation(content) is True


def test_stage_preview_defers_tool_stage_until_conductor_chooses() -> None:
    memory = {"candidate_directions": [_closed_direction()]}
    assert preview_turn_plan(
        content="判断现有方向能否回答新的作战约束",
        authoring_requested=False,
        working_memory=memory,
        defer_model_choice=True,
    ) == []
    assert preview_turn_plan(
        content="/card",
        authoring_requested=True,
        working_memory=memory,
        defer_model_choice=True,
    ) == ["inspect_memory", "author_s6"]


def test_invalid_conductor_output_uses_heuristic_fallback_metadata() -> None:
    class Host:
        def __init__(self) -> None:
            self.events: list[dict] = []

        async def _run_core_json(self, *_args, **_kwargs):
            return {"rationale": "没有返回 intent 或 tools"}

        def _emit_deep_dialogue_progress(self, row: dict) -> None:
            self.events.append(row)

    inbound = inbound_from_payload(
        {
            "question": "继续比较当前方向",
            "working_memory": {"candidate_directions": [_closed_direction()]},
        }
    )
    host = Host()
    plan, conductor = asyncio.run(resolve_turn_plan(host, inbound, {}))

    assert plan == ["deepen"]
    assert conductor["source"] == "heuristic"
    assert conductor["tools"] == ["deepen"]
    assert host.events[-1]["stage"] == "context"
    assert host.events[-1]["status"] == "completed"
    assert "回退" in host.events[-1]["summary_text"]


def test_failed_conductor_reports_council_when_reopen_fallback_is_selected() -> None:
    class Host:
        def __init__(self) -> None:
            self.events: list[dict] = []

        async def _run_core_json(self, *_args, **_kwargs):
            raise RuntimeError("conductor unavailable")

        def _emit_deep_dialogue_progress(self, row: dict) -> None:
            self.events.append(row)

    inbound = inbound_from_payload(
        {
            "question": "推翻当前方向，重新发散另一条构型",
            "working_memory": {"candidate_directions": [_closed_direction()]},
        }
    )
    host = Host()
    plan, conductor = asyncio.run(resolve_turn_plan(host, inbound, {}))

    assert plan == ["research_council"]
    assert conductor["source"] == "heuristic"
    assert "隔离发散" in host.events[-1]["summary_text"]


def test_card_without_closed_memory_falls_back_to_council() -> None:
    assert preview_turn_plan(
        content="/card",
        authoring_requested=True,
        working_memory={"candidate_directions": [{"name": "浅层方向", "stable": True}]},
    ) == ["research_council"]


def test_card_confirmation_uses_coherent_direction_not_nine_field_gate() -> None:
    coherent = {
        "name": "潜伏任务节点",
        "equipment_form": "可潜伏展开的任务节点",
        "operational_mechanism": "贴附后根据局部态势择机作用",
        "winning_angle": "重构任务窗口",
        "stable": True,
    }

    assert preview_turn_plan(
        content="/card",
        authoring_requested=True,
        working_memory={"candidate_directions": [coherent]},
    ) == ["inspect_memory", "author_s6"]


def test_agent_loop_feeds_tool_observation_to_next_policy_decision(
    monkeypatch,
) -> None:
    inbound = inbound_from_payload(
        {
            "question": "继续深化",
            "authoring_requested": False,
            "working_memory": {"candidate_directions": [{"name": "候选甲"}]},
        }
    )
    state = TurnState(host=object(), payload={}, inbound=inbound, plan=["deepen"])
    policy_observations: list[list[dict]] = []

    async def policy(current: TurnState) -> str | None:
        policy_observations.append(list(current.observations))
        return "deepen" if not current.observations else None

    async def deepen(_state: TurnState) -> dict:
        return {"visible_summary": ["已完成第一轮工具执行"]}

    monkeypatch.setitem(runtime_runner.TOOL_HANDLERS, "deepen", deepen)

    asyncio.run(run_planned_tools(state, policy=policy))

    assert policy_observations[0] == []
    assert policy_observations[1][0]["tool"] == "deepen"
    assert policy_observations[1][0]["result"] == {
        "visible_summary": ["已完成第一轮工具执行"]
    }
    assert state.completed_tools == ["deepen"]
    assert state.turn_count == 2
    assert state.tool_call_count == 1
    assert state.status == "completed"
    assert state.stop_reason == "policy_finished"


def test_agent_loop_enforces_tool_budget_after_replanning(monkeypatch) -> None:
    inbound = inbound_from_payload(
        {
            "question": "继续深化",
            "authoring_requested": False,
            "working_memory": {"candidate_directions": [{"name": "候选甲"}]},
        }
    )
    state = TurnState(
        host=object(),
        payload={},
        inbound=inbound,
        plan=["deepen"],
        max_tool_calls=1,
    )

    async def policy(current: TurnState) -> str:
        return "deepen" if not current.observations else "research_council"

    async def tool(_state: TurnState) -> dict:
        return {"ok": True}

    monkeypatch.setitem(runtime_runner.TOOL_HANDLERS, "deepen", tool)
    monkeypatch.setitem(runtime_runner.TOOL_HANDLERS, "research_council", tool)

    asyncio.run(run_planned_tools(state, policy=policy))

    assert state.completed_tools == ["deepen"]
    assert state.tool_call_count == 1
    assert state.status == "max_tool_calls"
    assert state.stop_reason == "max_tool_calls"


def test_agent_loop_uses_observation_recommendations_for_dynamic_strategy(
    monkeypatch,
) -> None:
    inbound = inbound_from_payload({"question": "重新探索不同假设"})
    state = TurnState(
        host=object(),
        payload={},
        inbound=inbound,
        plan=["diverge"],
        max_turns=4,
        max_tool_calls=3,
    )
    direction = {
        "name": "候选甲",
        "equipment_form": "分布式任务节点",
        "operational_mechanism": "潜伏后择机作用",
        "winning_angle": "任务窗口重构",
    }

    async def diverge(_state: TurnState) -> dict:
        return {
            "concept_directions": [direction, {**direction, "name": "候选乙"}],
            "research_assessment": {
                "recommended_action": "challenge",
                "recommendation_scope": "same_turn",
            },
        }

    async def challenge(_state: TurnState) -> dict:
        return {
            "concept_directions": [direction],
            "research_assessment": {
                "recommended_action": "synthesize",
                "recommendation_scope": "same_turn",
            },
        }

    async def synthesize(_state: TurnState) -> dict:
        return {"concept_directions": [direction], "research_assessment": {}}

    monkeypatch.setitem(runtime_runner.TOOL_HANDLERS, "diverge", diverge)
    monkeypatch.setitem(runtime_runner.TOOL_HANDLERS, "challenge", challenge)
    monkeypatch.setitem(runtime_runner.TOOL_HANDLERS, "synthesize", synthesize)

    asyncio.run(run_planned_tools(state))

    assert state.completed_tools == ["diverge", "challenge"]
    assert state.tool_call_count == 2
    assert state.stop_reason == "policy_finished"


def test_slash_research_command_keeps_advisory_follow_up_for_next_turn(
    monkeypatch,
) -> None:
    inbound = inbound_from_payload({"question": "/diverge 新的进入窗口"})
    state = TurnState(
        host=object(),
        payload={},
        inbound=inbound,
        plan=["diverge"],
        max_turns=4,
        max_tool_calls=4,
    )
    direction = {"name": "候选甲", "equipment_form": "任务节点"}

    async def diverge(_state: TurnState) -> dict:
        return {
            "concept_directions": [direction],
            "research_assessment": {
                "recommended_action": "challenge",
                "recommendation_scope": "next_turn",
            },
        }

    async def challenge(_state: TurnState) -> dict:
        raise AssertionError("next-turn advice must not extend an explicit command")

    monkeypatch.setitem(runtime_runner.TOOL_HANDLERS, "diverge", diverge)
    monkeypatch.setitem(runtime_runner.TOOL_HANDLERS, "challenge", challenge)

    asyncio.run(run_planned_tools(state))

    assert state.completed_tools == ["diverge"]
    assert state.stop_reason == "policy_finished"


def test_slash_research_command_allows_one_scoped_observation_follow_up(
    monkeypatch,
) -> None:
    inbound = inbound_from_payload({"question": "/diverge 新的进入窗口"})
    state = TurnState(
        host=object(),
        payload={},
        inbound=inbound,
        plan=["diverge"],
        max_turns=4,
        max_tool_calls=4,
    )
    direction = {"name": "候选甲", "equipment_form": "任务节点"}

    async def diverge(_state: TurnState) -> dict:
        return {
            "concept_directions": [direction],
            "research_assessment": {
                "recommended_action": "challenge",
                "recommendation_scope": "same_turn",
            },
        }

    async def challenge(_state: TurnState) -> dict:
        return {
            "concept_directions": [direction],
            "research_assessment": {
                "recommended_action": "author_s6",
                "recommendation_scope": "same_turn",
            },
        }

    monkeypatch.setitem(runtime_runner.TOOL_HANDLERS, "diverge", diverge)
    monkeypatch.setitem(runtime_runner.TOOL_HANDLERS, "challenge", challenge)

    asyncio.run(run_planned_tools(state))

    assert state.completed_tools == ["diverge", "challenge"]
    assert "author_s6" not in state.completed_tools
    assert state.tool_call_count == 2


def test_adaptive_agent_loop_chooses_one_follow_up_from_latest_observation() -> None:
    calls: list[dict] = []

    class Host:
        def __init__(self) -> None:
            self.events: list[dict] = []

        def _emit_deep_dialogue_progress(self, row: dict) -> None:
            self.events.append(row)

    async def decide(_agent, _system, payload, _schema, _tokens, **kwargs):
        calls.append({"payload": payload, "phase": kwargs.get("phase")})
        return {
            "action": "challenge",
            "rationale": "候选尚未经过最低成本反制检验",
            "unresolved_question": "干扰条件下是否仍能闭合任务链",
        }

    host = Host()
    state = TurnState(
        host=host,
        payload={"adaptive_tool_loop": True},
        inbound=inbound_from_payload(
            {
                "question": "继续判断反制后的可行性",
                "working_memory": {"candidate_directions": [_closed_direction()]},
            }
        ),
        plan=["deepen"],
        completed_tools=["deepen"],
        observations=[
            {
                "kind": "tool_result",
                "tool": "deepen",
                "turn_index": 1,
                "status": "completed",
                "result": {"concept_directions": [_closed_direction()]},
            }
        ],
        provider_runtime=ProviderRuntime(json_callback=decide),
        turn_count=1,
        tool_call_count=1,
        max_turns=4,
        max_tool_calls=4,
    )

    action = asyncio.run(resolve_next_action(state))
    second = asyncio.run(resolve_next_action(state))

    assert action == "challenge"
    assert second is None
    assert calls[0]["phase"] == "deep_research_adaptive_policy"
    assert calls[0]["payload"]["completed_tools"] == ["deepen"]
    assert state.observations[-1]["kind"] == "adaptive_policy_decision"
    assert state.observations[-1]["status"] == "continue"
    assert host.events[-1]["event_type"] == "deep_agent_handoff"
    assert host.events[-1]["handoff_kind"] == "observation_follow_up"
    assert host.events[-1]["to_agent_id"] == "deep_tool_challenge"


def test_adaptive_agent_loop_finishes_when_model_reports_answered() -> None:
    async def decide(*_args, **_kwargs):
        return {"action": "finish", "rationale": "问题已回答"}

    state = TurnState(
        host=object(),
        payload={"adaptive_tool_loop": True},
        inbound=inbound_from_payload(
            {
                "question": "这个方向是否成立",
                "working_memory": {"candidate_directions": [_closed_direction()]},
            }
        ),
        plan=["deepen"],
        completed_tools=["deepen"],
        observations=[
            {
                "kind": "tool_result",
                "tool": "deepen",
                "result": {"visible_summary": ["已闭合"]},
            }
        ],
        provider_runtime=ProviderRuntime(json_callback=decide),
        turn_count=1,
        tool_call_count=1,
    )

    assert asyncio.run(resolve_next_action(state)) is None
    assert state.observations[-1]["status"] == "finish"


def test_runtime_expands_slash_semantics_and_args_before_model_call() -> None:
    class Host:
        def __init__(self) -> None:
            self.model_payloads: list[dict] = []

        async def _run_core_json(self, _agent, _prompt, payload, *_args, **_kwargs):
            self.model_payloads.append(payload)
            raise RuntimeError("capture expanded expert question and use fallback")

        def _emit_deep_dialogue_progress(self, _row: dict) -> None:
            return None

    host = Host()
    result = asyncio.run(
        _run_deep_research_turn(
            host,
            {"question": "/diverge 优先探索不依赖持续通信的进入窗口"},
        )
    )

    expert_question = host.model_payloads[0]["expert_question"]
    assert "重新深度发散" in expert_question
    assert "优先探索不依赖持续通信的进入窗口" in expert_question
    assert not expert_question.startswith("/diverge")
    assert result["runtime"]["command"] == "diverge"
    assert result["runtime"]["tools"] == ["diverge"]


def test_runtime_mounts_host_tools_refreshes_snapshot_and_releases_lease() -> None:
    class Host:
        def _emit_deep_dialogue_progress(self, _row: dict) -> None:
            return None

    class MCPHost:
        def __init__(self) -> None:
            self.mounted = False
            self.unmounted = False

        async def mount_registry(self, registry) -> None:
            self.mounted = True
            registry.register_mcp_declaration(
                {"server_id": "host:echo", "transport": "inproc", "plugin_id": "host"}
            )
            await registry.attach_mcp_adapter(
                "host:echo",
                InProcessMCPAdapter({"echo": lambda arguments: dict(arguments)}),
                allowed_tools=["echo"],
            )

        async def unmount_registry(self, registry) -> None:
            self.unmounted = True
            await registry.stop_mcp("host:echo")

    mcp_host = MCPHost()
    result = asyncio.run(
        _run_deep_research_turn(
            Host(), {"question": "/help", "persistent_mcp_host": mcp_host}
        )
    )

    assert mcp_host.mounted and mcp_host.unmounted
    assert result["runtime"]["mcp_servers"] == ["host:echo"]
    assert result["runtime"]["status"] == "completed"


def test_optional_mcp_failure_becomes_research_gap_but_required_failure_propagates() -> None:
    class Host:
        def _emit_deep_dialogue_progress(self, _row: dict) -> None:
            return None

    class FailedMCPHost:
        async def mount_registry(self, _registry) -> None:
            raise MCPAdapterError("private upstream detail")

    optional = asyncio.run(
        _run_deep_research_turn(
            Host(), {"question": "/help", "persistent_mcp_host": FailedMCPHost()}
        )
    )
    assert optional["runtime"]["status"] == "completed"
    assert optional["runtime"]["observation_count"] >= 1

    with pytest.raises(MCPAdapterError):
        asyncio.run(
            _run_deep_research_turn(
                Host(),
                {
                    "question": "/help",
                    "persistent_mcp_host": FailedMCPHost(),
                    "mcp_required": True,
                },
            )
        )


def test_explicit_diverge_runs_bounded_subagent_probes_and_emits_visible_activity() -> None:
    class Host:
        def __init__(self) -> None:
            self.events: list[dict] = []

        def _emit_deep_dialogue_progress(self, row: dict) -> None:
            self.events.append(row)

    class Runner:
        async def run_many(self, tasks):
            assert {task.task_id for task in tasks} == {
                "configuration_probe",
                "countermeasure_probe",
            }
            return [
                SubagentResult(
                    task.task_id,
                    task.role,
                    "completed",
                    finding=f"{task.role}发现",
                )
                for task in tasks
            ]

    host = Host()
    result = asyncio.run(
        _run_deep_research_turn(
            host,
            {
                "question": "/diverge 扩大正交解空间",
                "enable_subagents": True,
                "subagent_runner": Runner(),
            },
        )
    )

    assert len(result["subagent_results"]) == 2
    probe_events = [
        row for row in host.events if row.get("round") == "lightweight_probe"
    ]
    assert len([row for row in probe_events if row["event_type"] == "deep_agent_started"]) == 2
    assert len([row for row in probe_events if row["event_type"] == "deep_agent_completed"]) == 2
    assert all(row["parallel_group"] == "lightweight_probes" for row in probe_events)


def test_follow_up_research_action_consumes_latest_observed_directions() -> None:
    old_direction = {**_closed_direction(), "name": "旧记忆候选"}
    revised_direction = {
        **_closed_direction(),
        "name": "发散后修订候选",
        "changed_assumption": "前序发散已经改写的关键假设",
    }

    class Host:
        def __init__(self) -> None:
            self.model_payloads: list[dict] = []

        async def _run_core_json(self, _agent, _prompt, payload, *_args, **_kwargs):
            self.model_payloads.append(payload)
            raise RuntimeError("capture the challenge payload and use fallback")

        def _emit_deep_dialogue_progress(self, _row: dict) -> None:
            return None

    inbound = inbound_from_payload(
        {
            "question": "挑战刚刚发散出的候选",
            "working_memory": {"candidate_directions": [old_direction]},
        }
    )
    host = Host()
    first_result = {"concept_directions": [revised_direction]}
    state = TurnState(
        host=host,
        payload={},
        inbound=inbound,
        plan=["diverge", "challenge"],
        results={"diverge": first_result},
        completed_tools=["diverge"],
        observations=[
            {
                "kind": "tool_result",
                "turn_index": 1,
                "tool": "diverge",
                "status": "completed",
                "result": first_result,
            }
        ],
        current_action="challenge",
    )

    asyncio.run(tool_challenge(state))

    candidates = host.model_payloads[0]["working_memory"]["candidate_directions"]
    assert [item["name"] for item in candidates] == ["发散后修订候选"]
    assert candidates[0]["changed_assumption"] == "前序发散已经改写的关键假设"


def test_research_assessment_is_non_blocking_and_exposes_string_gaps() -> None:
    inbound = inbound_from_payload({"question": "继续发散"})
    state = TurnState(
        host=object(),
        payload={},
        inbound=inbound,
        plan=["diverge"],
        conductor={"rationale": "先扩展正交假设"},
    )
    result = _add_research_signals(
        {
            "concept_directions": [
                {
                    "name": "潜伏任务节点",
                    "equipment_form": "可潜伏展开的任务节点",
                    "operational_mechanism": "贴附后根据局部态势择机作用",
                    "winning_angle": "任务窗口重构",
                }
            ],
            "quality_gate": {"block_reasons": ["旧发布门"]},
            "open_questions": ["任务失能判据如何观察？"],
        },
        state,
        action="diverge",
    )

    assert result["concept_directions"][0]["stable"] is True
    assert result["quality_gate"]["non_blocking"] is True
    assert result["quality_gate"]["block_reasons"] == []
    assert result["research_assessment"]["research_complete"] is True
    assert result["research_strategy"]["fixed_pipeline"] is False
    assert result["research_gaps"]
    assert all(isinstance(item, str) for item in result["research_gaps"])
    assert result["research_assessment"]["research_gaps"] == result["research_gaps"]
    assert all("winning_angle" not in item for item in result["research_gaps"])
    assert any("被改写假设" in item for item in result["research_gaps"])


def test_agent_loop_honors_stop_before_policy_or_tool() -> None:
    inbound = inbound_from_payload({"question": "开始研究"})
    state = TurnState(
        host=object(),
        payload={"stop_requested": True},
        inbound=inbound,
        plan=["research_council"],
    )

    asyncio.run(run_planned_tools(state))

    assert state.turn_count == 0
    assert state.tool_call_count == 0
    assert state.completed_tools == []
    assert state.status == "stopped"
    assert state.stop_reason == "stop_requested"


def test_agent_loop_interrupt_send_stops_before_tool_execution(monkeypatch) -> None:
    class Host:
        def _claim_deep_dialogue_steers(self, stage: str) -> list[dict]:
            assert stage == "s4_mapping"
            return [
                {
                    "steer_id": "steer-1",
                    "mode": "interrupt_send",
                    "content": "立即发送当前结果",
                }
            ]

    inbound = inbound_from_payload(
        {
            "question": "继续深化",
            "authoring_requested": False,
            "working_memory": {"candidate_directions": [{"name": "候选甲"}]},
        }
    )
    state = TurnState(host=Host(), payload={}, inbound=inbound, plan=["deepen"])

    async def should_not_run(_state: TurnState) -> dict:
        raise AssertionError("interrupt_send must stop before tool execution")

    monkeypatch.setitem(runtime_runner.TOOL_HANDLERS, "deepen", should_not_run)

    asyncio.run(run_planned_tools(state))

    assert state.tool_call_count == 0
    assert state.completed_tools == []
    assert state.interrupted is True
    assert state.status == "stopped"
    assert state.stop_reason == "interrupt_send"
    assert state.observations[0]["status"] == "interrupted"


def test_agent_loop_interrupt_send_stops_after_last_tool_returns(monkeypatch) -> None:
    class Host:
        claims = 0

        def _claim_deep_dialogue_steers(self, stage: str) -> list[dict]:
            assert stage == "s4_mapping"
            self.claims += 1
            if self.claims < 2:
                return []
            return [{"mode": "interrupt_send", "content": "停止旧轮并发送"}]

    inbound = inbound_from_payload(
        {
            "question": "继续深化",
            "working_memory": {"candidate_directions": [{"name": "候选甲"}]},
        }
    )
    state = TurnState(host=Host(), payload={}, inbound=inbound, plan=["deepen"])

    async def deepen(_state: TurnState) -> dict:
        return {"ok": True}

    monkeypatch.setitem(runtime_runner.TOOL_HANDLERS, "deepen", deepen)

    asyncio.run(run_planned_tools(state))

    assert state.completed_tools == ["deepen"]
    assert state.tool_call_count == 1
    assert state.status == "stopped"
    assert state.stop_reason == "interrupt_send"
    assert [item["kind"] for item in state.observations] == [
        "tool_result",
        "control",
    ]


def test_agent_loop_records_tool_failure_before_propagating(monkeypatch) -> None:
    inbound = inbound_from_payload({"question": "开始研究"})
    state = TurnState(
        host=object(), payload={}, inbound=inbound, plan=["research_council"]
    )

    async def fail(_state: TurnState) -> dict:
        raise RuntimeError("provider unavailable")

    monkeypatch.setitem(runtime_runner.TOOL_HANDLERS, "research_council", fail)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        asyncio.run(run_planned_tools(state))

    assert state.status == "failed"
    assert state.stop_reason == "tool_error:research_council"
    assert state.observations == [
        {
            "kind": "tool_error",
            "turn_index": 1,
            "tool": "research_council",
            "status": "failed",
            "error_type": "RuntimeError",
        }
    ]


def test_agent_loop_emits_bounded_tool_and_final_checkpoints(monkeypatch) -> None:
    checkpoints: list[dict] = []
    inbound = inbound_from_payload(
        {
            "question": "继续深化",
            "working_memory": {"candidate_directions": [{"name": "候选甲"}]},
        }
    )
    state = TurnState(
        host=object(),
        payload={"checkpoint_callback": checkpoints.append},
        inbound=inbound,
        plan=["deepen"],
        active_skills=[{"skill_id": "test:method"}],
    )

    async def deepen(_state: TurnState) -> dict:
        return {
            "visible_summary": ["已完成"],
            "selection_rationale": "x" * 5000,
            "ignored_private_field": "must not enter the checkpoint",
        }

    async def one_tool_then_finish(current: TurnState) -> str | None:
        return "deepen" if not current.completed_tools else None

    monkeypatch.setitem(runtime_runner.TOOL_HANDLERS, "deepen", deepen)
    asyncio.run(run_planned_tools(state, policy=one_tool_then_finish))
    final = {"visible_summary": ["最终答复"], "runtime": {"status": state.status}}
    asyncio.run(
        emit_runtime_checkpoint(state, "final_response", assistant_result=final)
    )

    assert [item["phase"] for item in checkpoints] == [
        "awaiting_tools",
        "tools_completed",
        "final_response",
    ]
    assert checkpoints[0]["pending_tool_calls"][0]["tool_name"] == "deepen"
    tool_result = checkpoints[1]["completed_tool_results"][0]["result"]
    assert tool_result["selection_rationale"] == "x" * 1200
    assert "ignored_private_field" not in tool_result
    assert checkpoints[2]["assistant_message"]["content"] == final
    assert checkpoints[2]["active_skill_ids"] == ["test:method"]


def test_checkpoint_visible_text_projects_only_mergeable_stage_findings() -> None:
    text = runtime_runner.checkpoint_visible_text(
        {
            "completed_tool_results": [
                {
                    "tool_name": "deepen",
                    "result": {
                        "visible_summary": ["已闭合直接毁伤与任务失能链。"],
                        "selection_rationale": "保留可验证的构型差异。",
                        "concept_directions": [
                            {"name": "潜伏先机节点"},
                            {"name": "重复方向"},
                        ],
                        "provider_response": "不得进入事件",
                    },
                }
            ]
        },
        phase="tools_completed",
    )

    assert text.startswith("阶段发现：")
    assert "直接毁伤" in text
    assert "潜伏先机节点" in text
    assert "provider_response" not in text


def test_checkpoint_visible_text_has_bounded_waiting_fallback() -> None:
    text = runtime_runner.checkpoint_visible_text(
        {
            "completed_tool_results": [],
            "pending_tool_calls": [{"tool_name": "research_council"}],
        },
        phase="awaiting_tools",
    )

    assert text == "正在执行 research_council，完成后会把阶段发现写入当前对话。"


def test_runtime_checkpoint_has_a_hard_total_json_budget(monkeypatch) -> None:
    checkpoints: list[dict] = []
    inbound = inbound_from_payload(
        {
            "question": "继续深化",
            "working_memory": {"candidate_directions": [{"name": "候选甲"}]},
        }
    )
    state = TurnState(
        host=object(),
        payload={"checkpoint_callback": checkpoints.append},
        inbound=inbound,
        plan=["deepen"],
    )
    oversized = {
        f"section_{section}": {
            f"item_{item}": "证据链" * 1200
            for item in range(24)
        }
        for section in range(24)
    }

    async def deepen(_state: TurnState) -> dict:
        return {
            "visible_summary": ["已完成"],
            "capability_card_draft": oversized,
            "concept_directions": [oversized for _ in range(8)],
        }

    monkeypatch.setitem(runtime_runner.TOOL_HANDLERS, "deepen", deepen)
    asyncio.run(run_planned_tools(state))
    asyncio.run(
        emit_runtime_checkpoint(
            state,
            "final_response",
            assistant_result=state.observations[-1]["result"],
        )
    )

    assert checkpoints
    assert all(
        len(json.dumps(item, ensure_ascii=False, sort_keys=True)) <= 60_000
        for item in checkpoints
    )
    assert checkpoints[-1]["checkpoint_truncated"] is True
    assert checkpoints[-1]["phase"] == "final_response"
    assert "assistant_message" in checkpoints[-1]
    assert "completed_tool_results" in checkpoints[-1]


def test_checkpoint_budget_also_bounds_large_control_fields() -> None:
    oversized = {
        "schema_version": "deep-runtime-checkpoint-v1",
        "phase": "final_response",
        "status": "running",
        "turn_count": 1,
        "tool_call_count": 1,
        "plan": ["deepen"] * 20_000,
        "completed_tools": [],
        "active_skill_ids": [],
        "stop_reason": "stop-" + ("x" * 100_000),
        "assistant_message": {},
        "completed_tool_results": [],
        "pending_tool_calls": [],
    }

    fitted = runtime_runner._fit_checkpoint_budget(oversized)

    assert len(json.dumps(fitted, ensure_ascii=False, sort_keys=True)) <= 60_000
    assert fitted["checkpoint_truncated"] is True
    assert fitted["phase"] == "final_response"


def test_tool_failure_is_checkpointed_before_propagating(monkeypatch) -> None:
    checkpoints: list[dict] = []
    inbound = inbound_from_payload({"question": "开始研究"})
    state = TurnState(
        host=object(),
        payload={"checkpoint_callback": checkpoints.append},
        inbound=inbound,
        plan=["research_council"],
    )

    async def fail(_state: TurnState) -> dict:
        raise ValueError("private provider detail")

    monkeypatch.setitem(runtime_runner.TOOL_HANDLERS, "research_council", fail)

    with pytest.raises(ValueError, match="private provider detail"):
        asyncio.run(run_planned_tools(state))

    assert [item["phase"] for item in checkpoints] == [
        "awaiting_tools",
        "tools_completed",
    ]
    error = checkpoints[-1]["completed_tool_results"][0]
    assert error["kind"] == "tool_error"
    assert error["error_type"] == "ValueError"
    assert "private provider detail" not in str(checkpoints[-1])


def test_author_s6_handler_fails_closed_without_confirmed_stable_memory() -> None:
    inbound = inbound_from_payload({"question": "请直接成卡"})
    state = TurnState(host=object(), payload={}, inbound=inbound, plan=["author_s6"])

    result = asyncio.run(tool_author_s6(state))

    assert result["finalization_status"] == "analysis_only"
    assert result["capability_card_draft"] == {}
    assert result["orchestration"]["pattern"] == "s6_authoring_blocked"
    assert result["quality_gate"]["publishable"] is False
