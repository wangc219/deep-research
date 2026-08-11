from __future__ import annotations

import asyncio
import json
import multiprocessing
from pathlib import Path
from urllib.parse import urlsplit

from equipment_deep_research.agents.provider import (
    AgentRunRequest,
    ResponsesAgentProvider,
    _direct_combat_generator_diversity_instruction,
    _discovery_system_prompt,
    _ensure_specialized_winning_seed_lanes,
    _merge_required_source_anchors,
    _prepare_portfolio_gap_completion_rows,
    _prioritize_specialized_anchor_urls,
    _prioritize_winning_evidence_index,
    _recover_specialized_winning_seed_hypotheses,
    _portfolio_gap_completion_instruction,
    _portfolio_remaining_repair_slots,
    _query_specific_weapon_evidence_channels,
    _weapon_specialized_evidence_channels,
)
from equipment_deep_research.agents.performance import AdaptiveCallGate
from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.domain.models import BaselineFindingPacket, EvidenceCard
from equipment_deep_research.domain.store import DomainStore
from equipment_deep_research.harness.context import (
    ContextPackBuilder,
    _project_upstream_payload,
)
from equipment_deep_research.harness.stop_policy import evaluate_evidence_sufficiency
from equipment_deep_research.harness.scheduler import _diversify_evidence_candidates
from equipment_deep_research.providers.base import (
    ProviderFinalTurn,
    ProviderStreamEvent,
)
from equipment_deep_research.providers.fake import ScriptedFakeProvider
from equipment_deep_research.tools.knowledge_index import AgentKnowledgeIndex


def _agent(agent_id: str = "weapon_equipment") -> AgentDef:
    return AgentDef(
        agent_id,
        "武器装备",
        "装备研究",
        ["equipment"],
        ["search_sources"],
        {"visible_sections": ["upstream_handoffs"]},
        output_contract={"name": "baseline_finding_packet", "properties": []},
        research_policy={"search_tracks": ["型号", "预算"], "target_source_count": 4},
    )


def _record_memory_in_process(path: str, index: int) -> None:
    knowledge = AgentKnowledgeIndex(path)
    packet = BaselineFindingPacket(
        packet_id=f"packet-{index}",
        agent_id="weapon_equipment",
        capability_tags=["equipment"],
        topic_focus=f"并发主题 {index}",
        findings=[f"finding-{index}"],
        evidence_ids=[f"ev-{index}"],
        confidence=0.8,
        coverage_notes=[],
        open_questions=[],
        handoff_summary=f"summary-{index}",
        checkpoint="done",
        payload_type="equipment_observation_v1",
        payload={"equipment_profiles": [{"model": f"M-{index}"}]},
        schema_version="2.0",
    )
    evidence = EvidenceCard(
        f"ev-{index}",
        "Program",
        f"https://example.org/{index}",
        "A",
        "claim",
        "excerpt",
        "p1",
        "accepted",
        "weapon_equipment",
    )
    knowledge.record(packet=packet, evidence=[evidence])


def test_evidence_candidates_are_interleaved_by_source_domain() -> None:
    candidates = [
        EvidenceCard(
            f"ev-{index}",
            "source",
            url,
            "B",
            "claim",
            "excerpt",
            "source#p1",
            "candidate",
            "agent",
        )
        for index, url in enumerate(
            [
                "https://defense.gov/a",
                "https://defense.gov/b",
                "https://defense.gov/c",
                "https://marines.mil/a",
                "https://pacom.mil/a",
            ]
        )
    ]

    ordered = _diversify_evidence_candidates(candidates)

    assert [urlsplit(item.source_url).hostname for item in ordered[:3]] == [
        "defense.gov",
        "marines.mil",
        "pacom.mil",
    ]


def test_prefetched_discovery_is_reused_by_analysis(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_DISCOVERY_MAX_BATCHES", "1")
    backend = ScriptedFakeProvider(
        [
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(
                        text="https://example.org/program",
                        metadata={
                            "web_sources": [
                                {
                                    "url": "https://example.org/program",
                                    "title": "Program",
                                }
                            ]
                        },
                    )
                )
            ],
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(
                        text=(
                            '{"findings":["完成"],"confidence":0.8,'
                            '"open_questions":[],"handoff_summary":"完成",'
                            '"contradictions":["公开资料边界"],'
                            '"source_claims":[{"url":"https://example.org/program",'
                            '"claim":"项目资料"}],"analysis_sections":{}}'
                        )
                    )
                )
            ],
        ]
    )
    provider = ResponsesAgentProvider(backend)
    provider.provider_kind = "codex_cli"
    progress_rows: list[dict] = []
    provider.set_baseline_progress_callback(progress_rows.append)
    request = AgentRunRequest("run-pipeline", _agent(), "topic", "traditional_gap", {})

    prefetched = provider.prefetch_baseline_agent(request)
    result = provider.run_baseline_agent(request)

    assert prefetched["source_count"] == 1
    assert result.packet.handoff_summary == "完成"
    assert len(backend.inputs) == 2
    assert any(
        row["event_type"] == "baseline_discovery_lane_started"
        for row in progress_rows
    )
    assert any(
        row["event_type"] == "baseline_analysis_started"
        for row in progress_rows
    )


def test_codex_missing_field_repair_patches_only_invalid_output(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_DISCOVERY_MAX_BATCHES", "1")
    backend = ScriptedFakeProvider(
        [
            [ProviderStreamEvent.final(ProviderFinalTurn(text="discovery"))],
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(
                        text='{"findings":["完成"],"confidence":0.8,"source_claims":[{"url":"https://example.org/a","claim":"a"}]}'
                    )
                )
            ],
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(text='{"handoff_summary":"局部修复完成"}')
                )
            ],
        ]
    )
    provider = ResponsesAgentProvider(backend)
    provider.provider_kind = "codex_cli"

    result = provider.run_baseline_agent(
        AgentRunRequest(
            "run-repair", _agent("generic_equipment"), "topic", "traditional_gap", {}
        )
    )

    assert result.packet.handoff_summary == "局部修复完成"
    assert [item[2].get("web_search") is not None for item in backend.inputs] == [
        True,
        False,
        False,
    ]


def test_targeted_supplement_uses_one_narrow_discovery_lane_and_compact_analysis(
    monkeypatch,
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_DISCOVERY_MAX_BATCHES", "3")
    backend = ScriptedFakeProvider(
        [
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(
                        text="https://example.org/test",
                        metadata={
                            "web_sources": [
                                {
                                    "url": "https://example.org/test",
                                    "title": "Official Test",
                                }
                            ]
                        },
                    )
                )
            ],
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(
                        text=(
                            '{"findings":["完成定向补证"],"confidence":0.82,'
                            '"open_questions":[],"handoff_summary":"完成",'
                            '"contradictions":[],"source_claims":['
                            '{"url":"https://example.org/test","claim":"测试完成"}],'
                            '"analysis_sections":{}}'
                        )
                    )
                )
            ],
        ]
    )
    provider = ResponsesAgentProvider(backend)
    provider.provider_kind = "codex_cli"
    request = AgentRunRequest(
        "run-targeted",
        _agent(),
        "topic",
        "traditional_gap",
        {
            "recall_request": {
                "targeted_supplement": True,
                "required_data": ["补充日期化集成测试证据"],
            }
        },
        round_index=2,
    )

    result = provider.run_baseline_agent(request)

    assert result.packet.handoff_summary == "完成"
    assert len(backend.inputs) == 2
    discovery_messages, _, discovery_options = backend.inputs[0]
    discovery_payload = discovery_messages[-1].content
    assert discovery_payload["task_input"]["search_tracks"] == (
        "补充日期化集成测试证据",
    )
    assert discovery_payload["task_input"]["target_source_count"] == 3
    assert discovery_options["reasoning_effort"] == "medium"
    analysis_options = backend.inputs[1][2]
    assert analysis_options["reasoning_effort"] == "medium"
    assert analysis_options["max_output_tokens"] <= 1800


def test_reference_agent_uses_compact_medium_reasoning_profile() -> None:
    sources = [
        {"url": f"https://source-{index}.example/report", "title": f"S{index}"}
        for index in range(8)
    ]
    backend = ScriptedFakeProvider(
        [
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(
                        text="reference discovery",
                        metadata={"web_sources": sources},
                    )
                )
            ],
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(
                        text=(
                            '{"findings":["决定性边界"],"confidence":0.8,'
                            '"open_questions":[],"handoff_summary":"完成",'
                            '"contradictions":["反证边界"],"source_claims":['
                            '{"url":"https://source-0.example/report","claim":"关键事实"}],' 
                            '"analysis_sections":{}}'
                        )
                    )
                )
            ],
        ]
    )
    provider = ResponsesAgentProvider(backend)
    provider.provider_kind = "codex_cli"

    provider.run_baseline_agent(
        AgentRunRequest(
            "run-reference",
            _agent("reference-agent"),
            "topic",
            "traditional_gap",
            {
                "_agent_plan_mode": "reference",
                "_search_intensity": "light",
                "discovery_blueprint": {"execution_profile_id": "optimized_v2"},
            },
        )
    )

    discovery_payload = backend.inputs[0][0][-1].content
    discovery_options = backend.inputs[0][2]
    analysis_options = backend.inputs[1][2]
    assert discovery_payload["task_input"]["target_source_count"] == 3
    assert discovery_options["max_output_tokens"] <= 1000
    assert analysis_options["reasoning_effort"] == "medium"
    assert analysis_options["max_output_tokens"] <= 1800


def test_required_weapon_equipment_uses_bounded_quality_source_target() -> None:
    sources = [
        {"url": f"https://weapon-{index}.example/report", "title": f"W{index}"}
        for index in range(14)
    ]
    backend = ScriptedFakeProvider(
        [
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(
                        text=(
                            '{"findings":["装备项目证据闭环"],"confidence":0.8,'
                            '"open_questions":[],"handoff_summary":"完成",'
                            '"contradictions":[],"source_claims":['
                            '{"url":"https://weapon-0.example/report",'
                            '"claim":"装备项目证据闭环"}],'
                            '"analysis_sections":{}}'
                        ),
                        metadata={"web_sources": sources},
                    )
                )
            ],
        ]
    )
    provider = ResponsesAgentProvider(backend)
    provider.provider_kind = "codex_cli"

    provider.run_baseline_agent(
        AgentRunRequest(
            "run-deep-weapon",
            _agent(),
            "无人远程火力打击装备",
            "new_winning_mechanism",
            {
                "discovery_blueprint": {
                    "execution_profile_id": "winning_swarm_dynamic_v2"
                }
            },
        )
    )

    discovery_payload = backend.inputs[0][0][-1].content["task_input"]
    discovery_options = backend.inputs[0][2]
    assert discovery_payload["target_source_count"] == 4
    channel_ids = {
        channel["channel_id"]
        for channel in discovery_payload["specialized_evidence_channels"]
    }
    assert "query_target_threat_combat_effect" in channel_ids
    assert channel_ids == {
        "query_target_threat_combat_effect",
        "query_specific_weapon_architecture_baseline",
        "query_countermeasure_failure_boundary",
        "query_weapon_engineering_acquisition",
    }
    assert discovery_options["max_output_tokens"] == 1400
    assert discovery_options["reasoning_effort"] == "low"
    assert discovery_options["_disable_provider_timeout"] is True
    assert "_provider_timeout_seconds" not in discovery_options
    assert discovery_options["web_search"]["search_context_size"] == "medium"
    assert "output_schema" in discovery_options
    snapshot_prompt = repr([message.content for message in backend.inputs[0][0]])
    assert "公开现役/在研能力边界" in snapshot_prompt
    assert "不得提出或命名前瞻候选" in snapshot_prompt
    assert len(backend.inputs) == 1


def test_required_agent_keeps_high_reasoning_profile() -> None:
    backend = ScriptedFakeProvider(
        [
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(
                        text="required discovery",
                        metadata={
                            "web_sources": [
                                {
                                    "url": "https://required.example/report",
                                    "title": "Required",
                                }
                            ]
                        },
                    )
                )
            ],
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(
                        text=(
                            '{"findings":["核心判断"],"confidence":0.8,'
                            '"open_questions":[],"handoff_summary":"完成",'
                            '"contradictions":["反证边界"],"source_claims":['
                            '{"url":"https://required.example/report","claim":"核心事实"}],' 
                            '"analysis_sections":{}}'
                        )
                    )
                )
            ],
        ]
    )
    provider = ResponsesAgentProvider(backend)
    provider.provider_kind = "codex_cli"

    provider.run_baseline_agent(
        AgentRunRequest(
            "run-required",
            _agent("required-agent"),
            "topic",
            "traditional_gap",
            {
                "_agent_plan_mode": "required",
                "_search_intensity": "light",
                "discovery_blueprint": {"execution_profile_id": "optimized_v2"},
            },
        )
    )

    analysis_options = backend.inputs[1][2]
    assert analysis_options["reasoning_effort"] == "high"
    assert analysis_options["max_output_tokens"] == 1800


def test_context_projection_keeps_only_target_fields() -> None:
    store = DomainStore()
    store.add_baseline_packet(
        BaselineFindingPacket(
            packet_id="packet-international",
            agent_id="international_situation",
            capability_tags=["threat"],
            topic_focus="topic",
            findings=["finding"],
            evidence_ids=["ev-1"],
            confidence=0.8,
            coverage_notes=[],
            open_questions=[],
            handoff_summary="summary",
            checkpoint="done",
            payload_type="strategic_assessment_v1",
            payload={
                "threat_assessment": "threat",
                "alternative_hypotheses": ["h1"],
                "scenario_drivers": ["d1"],
                "warning_indicators": ["w1"],
                "strategic_pattern": "must-not-leak",
            },
            schema_version="2.0",
        )
    )
    agent = AgentDef(
        "combat_scenario",
        "场景",
        "",
        ["scenario"],
        [],
        {"visible_sections": ["upstream_handoffs"], "token_budget": 2000},
        handoff_policy={"accept_from": ["international_situation"]},
    )

    pack = ContextPackBuilder().build_for_baseline_agent(
        agent=agent,
        topic="topic",
        research_route="traditional_gap",
        store=store,
    )

    payload = pack.sections["upstream_handoffs"][0]["payload"]
    assert payload["threat_assessment"] == "threat"
    assert len(payload) <= 5


def test_operational_projection_preserves_opponent_monitoring_delta() -> None:
    projected = _project_upstream_payload(
        target_agent_id="operational_employment",
        source_agent_id="opponent_monitoring",
        payload={
            "observed_moves": ["deployment"],
            "formation_timeline": ["2027"],
            "warning_indicators": ["exercise tempo"],
            "counter_requirements": ["not required by this consumer"],
        },
    )

    assert projected == {
        "observed_moves": ["deployment"],
        "formation_timeline": ["2027"],
        "warning_indicators": ["exercise tempo"],
        "counter_requirements": ["not required by this consumer"],
    }


def test_incremental_memory_is_versioned_and_contextual_only(tmp_path: Path) -> None:
    index_path = tmp_path / "agent-memory.json"
    index = AgentKnowledgeIndex(index_path)
    packet = BaselineFindingPacket(
        packet_id="packet-equipment",
        agent_id="weapon_equipment",
        capability_tags=["equipment"],
        topic_focus="低空无人装备",
        findings=["finding"],
        evidence_ids=["ev-1"],
        confidence=0.82,
        coverage_notes=[],
        open_questions=[],
        handoff_summary="型号与批次基线",
        checkpoint="done",
        payload_type="equipment_observation_v1",
        payload={"equipment_profiles": [{"model": "A"}], "system_dependencies": ["C2"]},
        schema_version="2.0",
    )
    evidence = EvidenceCard(
        "ev-1",
        "Program",
        "https://example.org/program",
        "A",
        "claim",
        "excerpt",
        "p1",
        "accepted",
        "weapon_equipment",
    )

    index.record(packet=packet, evidence=[evidence])
    rows = index.recommend("weapon_equipment", "低空无人装备")

    assert rows[0]["source_urls"] == ["https://example.org/program"]
    assert rows[0]["factual_authority"] == "contextual_only"
    assert rows[0]["revalidation_required"] is True
    assert json.loads(index_path.read_text(encoding="utf-8"))["schema_version"] == "1.0"


def test_incremental_memory_supports_parallel_process_writers(tmp_path: Path) -> None:
    index_path = tmp_path / "agent-memory.json"
    context = multiprocessing.get_context("fork")
    processes = [
        context.Process(
            target=_record_memory_in_process,
            args=(str(index_path), index),
        )
        for index in range(4)
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=5)
        assert process.exitcode == 0

    payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert len(payload["records"]) == 4


def test_evidence_sufficiency_can_stop_before_soft_target() -> None:
    packet = BaselineFindingPacket(
        packet_id="p",
        agent_id="generic",
        capability_tags=["x"],
        topic_focus="topic",
        findings=["f"],
        evidence_ids=["a", "b", "c"],
        confidence=0.8,
        coverage_notes=[],
        open_questions=[],
        handoff_summary="done",
        checkpoint="done",
        limitations=["存在反证边界"],
    )
    evidence = [
        EvidenceCard(f"ev-{index}", "t", url, "A", "c", "e", "p", "q", "a")
        for index, url in enumerate(
            [
                "https://one.example/a",
                "https://two.example/b",
                "https://one.example/c",
            ]
        )
    ]

    decision = evaluate_evidence_sufficiency(
        packet,
        evidence,
        minimum_count=3,
        target_count=4,
        minimum_domains=2,
    )

    assert decision.allowed is True
    assert decision.accepted_count == 3
    assert decision.target_count == 4


def test_global_call_gate_bounds_parallel_async_calls_without_deadlock(
    monkeypatch,
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY", "2")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MIN", "2")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MAX", "2")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_RESERVED_PRIORITY_SLOTS", "0")

    class DelayedProvider:
        def __init__(self) -> None:
            self.active = 0
            self.maximum = 0

        def snapshot(self):
            return {"type": "codex_cli"}

        async def stream(self, messages, tools, options):
            del messages, tools, options
            self.active += 1
            self.maximum = max(self.maximum, self.active)
            try:
                await asyncio.sleep(0.01)
                yield ProviderStreamEvent.final(ProviderFinalTurn(text="done"))
            finally:
                self.active -= 1

    backend = DelayedProvider()
    provider = ResponsesAgentProvider(backend)

    async def run_calls():
        return await asyncio.gather(
            *(provider._collect_stream(backend, [], {}) for _ in range(6))
        )

    rows = asyncio.run(run_calls())

    assert [text for text, _ in rows] == ["done"] * 6
    assert all(
        isinstance(metadata.get("elapsed_seconds"), float)
        and metadata["elapsed_seconds"] >= 0
        for _, metadata in rows
    )
    assert backend.maximum == 2


def test_weapon_specialized_evidence_channels_are_distinct_and_query_anchored() -> None:
    rows = _weapon_specialized_evidence_channels("近年局部战争装备需求")

    assert [row["channel_id"] for row in rows] == [
        "query_target_threat_combat_effect",
        "query_specific_weapon_architecture_baseline",
        "query_countermeasure_failure_boundary",
        "query_weapon_engineering_acquisition",
    ]
    assert all(row["query_anchor"] == "近年局部战争装备需求" for row in rows)
    assert all(row["preferred_sources"] for row in rows)
    assert all("证据" in row["name"] for row in rows)
    assert not any(row.get("source_anchors") for row in rows)


def test_weapon_specialized_evidence_channels_do_not_preselect_weapon_families() -> None:
    rows = _weapon_specialized_evidence_channels(
        "无人远程精确打击与反辐射压制",
        structured_query_brief={
            "enemy_target_profile": ["机动防空雷达"],
            "battle_phase_and_constraints": ["远域进入", "强电磁压制"],
        },
    )
    ids = [row["channel_id"] for row in rows]

    assert ids == [
        "query_target_threat_combat_effect",
        "query_specific_weapon_architecture_baseline",
        "query_countermeasure_failure_boundary",
        "query_weapon_engineering_acquisition",
    ]


def test_query_semantic_channels_have_no_fixed_equipment_family_anchors() -> None:
    channels = _weapon_specialized_evidence_channels(
        "无人远程精确打击、反辐射诱骗、反蜂群拦截与低成本规模化装备"
    )
    urls = _prioritize_specialized_anchor_urls(channels)

    assert urls == []
    assert all(not row.get("source_anchors") for row in channels)


def test_weapon_discovery_prompt_uses_query_semantics_without_fixed_catalogue() -> None:
    prompt = _discovery_system_prompt("weapon_equipment")

    assert "Codex Query语义发散简报" in prompt
    assert "Query专属证据通道" in prompt
    assert "不得固定套用" in prompt
    assert "敌方目标、作战阶段" in prompt
    assert "候选武器构型" in prompt
    assert "Barracuda" not in prompt
    assert "PrSM" not in prompt


def test_winning_candidate_prompts_are_query_led_direct_weapon_architectures() -> None:
    initial = _direct_combat_generator_diversity_instruction()
    completion = _portfolio_gap_completion_instruction()

    assert "Query专属武器架构" in initial
    assert "不得预设无人机" in initial
    assert "Coyote" not in initial
    assert "未通过候选是负面样本而不是装备族禁区" in completion
    assert "打击、歼灭、毁伤、杀伤" in completion
    assert "跨Query替换自检" in completion
    assert "MALD" not in completion


def test_portfolio_gap_completion_does_not_use_topic_keyword_catalog() -> None:
    completion = _portfolio_gap_completion_instruction(
        "聚焦无人远程火力打击装备，承担突防、压制、歼灭和毁伤"
    )

    assert "重新消费Query语义简报" in completion
    assert "不能因为证据库存在某型号就强制生成" in completion
    assert "Barracuda" not in completion
    assert "第五个组合方向" not in completion


def test_query_specific_weapon_evidence_channels_do_not_seed_fixed_models() -> None:
    rows = _query_specific_weapon_evidence_channels(
        "远海高速机动水面编队火力续接",
        structured_query_brief={
            "enemy_target_profile": ["高速机动水面舰艇与编队防空"],
            "battle_phase_and_constraints": ["首轮突防后坐标快速过期"],
            "required_direct_military_effects": ["重创或击沉高价值水面舰艇"],
            "query_specific_weapon_architectures": ["潜射低特征多模反舰巡航弹药"],
        },
    )

    serialized = json.dumps(rows, ensure_ascii=False)
    assert len(rows) == 4
    assert all(row["query_anchor"] == "远海高速机动水面编队火力续接" for row in rows)
    assert "潜射低特征" in serialized
    assert all(row["source_anchors"] == [] for row in rows)
    assert all(name not in serialized for name in ("Coyote", "Roadrunner", "JASSM", "MALD"))


def test_partial_portfolio_completion_reserves_same_round_repair_slots() -> None:
    assert _portfolio_remaining_repair_slots(
        passed_count=3,
        finalist_minimum=5,
        completion_count=1,
    ) == 1
    assert _portfolio_remaining_repair_slots(
        passed_count=4,
        finalist_minimum=5,
        completion_count=1,
    ) == 0


def test_required_equipment_source_anchors_reserve_discovery_slots() -> None:
    rows = _merge_required_source_anchors(
        [
            {"title": "Open result", "url": "https://example.com/open"},
            {"title": "Existing JASSM", "url": "https://example.com/jassm"},
        ],
        [
            "https://example.com/jassm",
            "https://example.com/barracuda",
        ],
        limit=3,
    )

    assert [row["url"] for row in rows] == [
        "https://example.com/jassm",
        "https://example.com/barracuda",
        "https://example.com/open",
    ]
    assert rows[1]["retrieval_lane"] == "required_source_anchor"
    assert all(row["required_source_anchor"] is True for row in rows[:2])


def test_required_equipment_anchor_survives_domain_diversification_cutoff() -> None:
    candidates = [
        EvidenceCard(
            f"ev-{index}",
            title,
            url,
            "B",
            "claim",
            "excerpt",
            "source#p1",
            quality,
            "weapon_equipment",
        )
        for index, (title, url, quality) in enumerate(
            [
                (
                    "Roadrunner",
                    "https://www.anduril.com/roadrunner",
                    "codex_web_search_source; structured_source_claim; required_source_anchor",
                ),
                (
                    "Barracuda production agreement",
                    "https://www.anduril.com/news/barracuda-production",
                    "codex_web_search_source; structured_source_claim; required_source_anchor",
                ),
                (
                    "Army budget",
                    "https://www.army.mil/budget",
                    "codex_web_search_source; finding_fallback",
                ),
                (
                    "Switchblade 600",
                    "https://www.avinc.com/switchblade-600",
                    "codex_web_search_source; structured_source_claim",
                ),
            ]
        )
    ]

    ordered = _diversify_evidence_candidates(candidates)

    assert [item.source_title for item in ordered] == [
        "Roadrunner",
        "Barracuda production agreement",
        "Switchblade 600",
        "Army budget",
    ]


def test_winning_evidence_index_prioritizes_direct_weapon_cards() -> None:
    rows = _prioritize_winning_evidence_index(
        [
            {"evidence_id": "ev-combat_scenario-web-1", "created_by": "combat_scenario"},
            {"evidence_id": "ev-weapon_equipment-web-2", "created_by": "weapon_equipment"},
            {"evidence_id": "ev-system_confrontation-web-3", "created_by": "system_confrontation"},
        ]
    )

    assert rows[0]["evidence_id"] == "ev-weapon_equipment-web-2"


def test_winning_evidence_index_does_not_use_fixed_weapon_role_keywords() -> None:
    rows = _prioritize_winning_evidence_index(
        [
            {
                "evidence_id": "ev-weapon_equipment-web-prsm",
                "created_by": "weapon_equipment",
                "source_title": "PrSM Increment 2 flight test",
            },
            {
                "evidence_id": "ev-weapon_equipment-web-switchblade",
                "created_by": "weapon_equipment",
                "source_title": "Switchblade 600 loitering munition",
            },
        ],
        archetype="direct_combat_equipment_generator",
    )

    assert [row["evidence_id"] for row in rows] == [
        "ev-weapon_equipment-web-prsm",
        "ev-weapon_equipment-web-switchblade",
    ]


def test_specialized_seed_recovery_does_not_invent_remote_platform_rows() -> None:
    rows = _recover_specialized_winning_seed_hypotheses(
        [
            {
                "evidence_id": "ev-weapon_equipment-web-jassm",
                "source_title": "JASSM AGM-158 procurement",
            },
            {
                "evidence_id": "ev-weapon_equipment-web-prsm",
                "source_title": "PrSM Precision Strike Missile flight test",
            },
        ],
        archetype="remote_precision_munition_generator",
    )

    assert rows == []


def test_specialized_seed_recovery_ignores_compact_fields_instead_of_naming_weapons() -> None:
    rows = _recover_specialized_winning_seed_hypotheses(
        [
            {
                "evidence_id": "ev-weapon_equipment-web-jassm",
                "title": "Air-launched standoff missile program",
                "url": "https://example.com/agm-158-jassm",
            },
            {
                "evidence_id": "ev-weapon_equipment-web-prsm",
                "title": "Precision Strike Missile procurement",
                "url": "https://example.com/prsm",
            },
        ],
        archetype="remote_precision_munition_generator",
    )

    assert rows == []


def test_specialized_seed_recovery_requires_matching_public_evidence() -> None:
    rows = _recover_specialized_winning_seed_hypotheses(
        [
            {
                "evidence_id": "ev-combat_scenario-web-1",
                "source_title": "Generic contested environment",
            }
        ],
        archetype="mass_scalable_combat_family_generator",
    )

    assert rows == []


def test_offensive_gap_recovery_does_not_build_fixed_mald_effector() -> None:
    evidence = [
        {
            "evidence_id": "ev-weapon_equipment-web-mald",
            "source_title": "USAF Miniature Air Launched Decoy MALD-J fact sheet",
            "source_url": "https://www.af.mil/miniature-air-launched-decoy/",
        },
        {
            "evidence_id": "ev-weapon_equipment-web-harop",
            "source_title": "IAI Harop loitering munition",
        },
    ]

    rows = _recover_specialized_winning_seed_hypotheses(
        evidence,
        archetype="offensive_portfolio_gap_completion",
    )

    assert rows == []


def test_offensive_gap_recovery_does_not_parse_mald_identity_from_evidence() -> None:
    rows = _recover_specialized_winning_seed_hypotheses(
        [
            {
                "evidence_id": "ev-weapon_equipment-web-prsm",
                "source_title": "Precision Strike Missile | Lockheed Martin",
                "source_url": "https://www.lockheedmartin.com/prsm",
                "claim": "对比链条提到MALD、AARGM与Barracuda。",
            },
            {
                "evidence_id": "ev-weapon_equipment-web-mald",
                "source_title": "MALD Decoy | Raytheon",
                "source_url": "https://www.rtx.com/mald-decoy",
                "claim": "MALD-J是可消耗电子攻击效应器。",
            },
        ],
        archetype="offensive_portfolio_gap_completion",
    )

    assert rows == []


def test_offensive_gap_completion_preserves_model_rows_without_fixed_mald_injection() -> None:
    rows, added_count = _prepare_portfolio_gap_completion_rows(
        [
            {
                "title": "MALD-J/Harop复合诱导猎歼弹",
                "nearest_public_baseline": "MALD-J与Harop双基线",
                "equipment_forms": ["电子攻击与被动末制导复合弹体"],
            },
            {
                "title": "另一互异直接武器",
                "equipment_forms": ["固定构型巡航效应器"],
            },
        ],
        [
            {
                "evidence_id": "ev-weapon_equipment-web-mald",
                "source_title": "ADM-160 MALD-J electronic attack decoy",
            },
            {
                "evidence_id": "ev-weapon_equipment-web-harop",
                "source_title": "Harop loitering munition",
            },
        ],
        topic="聚焦无人远程火力打击装备，承担突防、压制、歼灭和毁伤",
    )

    assert added_count == 0
    assert len(rows) == 2
    assert rows[0]["title"] == "MALD-J/Harop复合诱导猎歼弹"
    assert rows[1]["title"] == "另一互异直接武器"


def test_specialized_seed_lane_enforcement_does_not_replace_query_rows_with_fixed_seed() -> None:
    rows, added_count = _ensure_specialized_winning_seed_lanes(
        [
            {
                "title": "低空无人携弹平台甲",
                "equipment_forms": ["低空无人携弹平台"],
            },
            {
                "title": "低空无人携弹平台乙",
                "equipment_forms": ["低空无人载机"],
            },
        ],
        [
            {
                "evidence_id": "ev-weapon_equipment-web-low-altitude",
                "source_title": "Low altitude unmanned combat platform",
            },
            {
                "evidence_id": "ev-weapon_equipment-web-barracuda",
                "source_title": "Barracuda FAMM affordable mass production",
            },
        ],
        archetype="mass_scalable_combat_family_generator",
    )

    assert len(rows) == 2
    assert [row["title"] for row in rows] == [
        "低空无人携弹平台甲",
        "低空无人携弹平台乙",
    ]
    assert added_count == 0


def test_winning_model_progress_uses_dedicated_event_family() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text="done"))]]
    )
    provider = ResponsesAgentProvider(backend)
    events: list[dict] = []
    provider.set_winning_progress_callback(events.append)

    text, _ = asyncio.run(
        provider._collect_stream(
            backend,
            [],
            {},
            progress={
                "agent_id": "winning_s6_image",
                "step": 6,
                "steps": [6],
                "current_step": "S6 能力画像综合",
            },
            progress_family="winning",
        )
    )

    assert text == "done"
    assert [event["event_type"] for event in events] == [
        "winning_model_call_started",
        "winning_model_call_completed",
    ]
    assert all(event["current_step"] == "S6 能力画像综合" for event in events)


def test_call_gate_reserves_capacity_for_critical_baseline_wave(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY", "4")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MIN", "4")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MAX", "4")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_RESERVED_PRIORITY_SLOTS", "2")
    gate = AdaptiveCallGate()

    normal_one = gate.try_acquire(priority="normal")
    normal_two = gate.try_acquire(priority="normal")
    assert normal_one is not None
    assert normal_two is not None
    assert gate.try_acquire(priority="normal") is None

    critical_one = gate.try_acquire(priority="critical")
    critical_two = gate.try_acquire(priority="critical")
    assert critical_one is not None
    assert critical_two is not None
    assert gate.try_acquire(priority="critical") is None

    for lease in (normal_one, normal_two, critical_one, critical_two):
        gate.release(0.1, success=True)


def test_call_gate_treats_core_phase_priorities_as_critical(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY", "4")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MIN", "4")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MAX", "4")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_RESERVED_PRIORITY_SLOTS", "2")

    for priority in ("swarm", "quality_gate", "delivery"):
        gate = AdaptiveCallGate()
        leases = [gate.try_acquire(priority=priority) for _ in range(4)]
        assert all(lease is not None for lease in leases)
        assert gate.try_acquire(priority=priority) is None
        for lease in leases:
            assert lease is not None
            assert lease.priority == "critical"
            gate.release(0.1, success=True)


def test_successful_long_quality_calls_do_not_collapse_concurrency(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY", "6")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MIN", "4")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MAX", "8")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_SLOW_CALL_SECONDS", "10")
    monkeypatch.delenv("EQUIPMENT_DR_CODEX_LATENCY_DOWNSHIFT", raising=False)
    gate = AdaptiveCallGate()

    for _ in range(6):
        lease = gate.try_acquire(priority="critical")
        assert lease is not None
        gate.release(300.0, success=True)

    assert gate.snapshot()["limit"] == 6
    assert gate.snapshot()["latency_downshift_enabled"] is False


def test_latency_downshift_is_explicit_and_requires_repeated_slow_calls(
    monkeypatch,
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY", "6")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MIN", "4")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MAX", "8")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_SLOW_CALL_SECONDS", "10")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_LATENCY_DOWNSHIFT", "1")
    gate = AdaptiveCallGate()

    for elapsed in (20.0, 20.0, 20.0, 1.0):
        lease = gate.try_acquire(priority="critical")
        assert lease is not None
        gate.release(elapsed, success=True)

    assert gate.snapshot()["limit"] == 5


def test_known_and_open_discovery_lanes_run_in_parallel_and_merge_sources(
    monkeypatch,
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_DISCOVERY_MAX_BATCHES", "2")

    class LaneAwareProvider:
        def __init__(self) -> None:
            self.started_lanes: set[str] = set()
            self.both_started = asyncio.Event()

        def snapshot(self):
            return {"type": "codex_cli"}

        async def stream(self, messages, tools, options):
            del tools, options
            task_input = messages[1].content["task_input"]
            lane = str(task_input["retrieval_lane"])
            self.started_lanes.add(lane)
            if len(self.started_lanes) == 2:
                self.both_started.set()
            await asyncio.wait_for(self.both_started.wait(), timeout=0.5)
            yield ProviderStreamEvent.final(
                ProviderFinalTurn(
                    text=f"https://{lane}.example/source",
                    metadata={
                        "web_sources": [
                            {
                                "url": f"https://{lane}.example/source",
                                "title": lane,
                            }
                        ]
                    },
                )
            )

    backend = LaneAwareProvider()
    provider = ResponsesAgentProvider(backend)
    agent = AgentDef(
        "agent-a",
        "agent-a",
        "",
        ["research"],
        ["search_sources"],
        {},
        research_policy={"search_tracks": ["track"], "target_source_count": 4},
    )
    result = provider.prefetch_baseline_agent(
        AgentRunRequest(
            "run-shared",
            agent,
            "topic",
            "traditional_gap",
            {"source_priorities": [{"url": "https://agent-a.example/"}]},
        )
    )

    assert backend.started_lanes == {"known_sources", "open_web"}
    assert result["source_count"] == 2


def test_discovery_lane_timeout_is_bounded_and_baseline_analysis_continues(
    monkeypatch,
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_DISCOVERY_MAX_BATCHES", "1")
    monkeypatch.setenv("EQUIPMENT_DR_WEB_DISCOVERY_TIMEOUT_SECONDS", "90")

    class LimitedDiscoveryProvider:
        def __init__(self) -> None:
            self.inputs: list[dict] = []

        def snapshot(self):
            return {"type": "codex_cli", "model": "fake"}

        async def stream(self, messages, tools, options):
            del messages, tools
            self.inputs.append(dict(options))
            if options.get("web_search"):
                raise TimeoutError("simulated hosted-search tail")
            yield ProviderStreamEvent.final(
                ProviderFinalTurn(
                    text=json.dumps(
                        {
                            "findings": ["使用共享边界继续形成低置信度研判"],
                            "confidence": 0.5,
                            "open_questions": ["检索通道待后续独立补证"],
                            "handoff_summary": "检索受限但未阻塞基线交接",
                            "contradictions": ["缺少本轮新增公开来源"],
                            "source_claims": [],
                            "analysis_sections": {},
                        },
                        ensure_ascii=False,
                    )
                )
            )

    backend = LimitedDiscoveryProvider()
    provider = ResponsesAgentProvider(backend)
    progress_rows: list[dict] = []
    provider.set_baseline_progress_callback(progress_rows.append)
    result = provider.run_baseline_agent(
        AgentRunRequest(
            "run-limited-discovery",
            _agent("generic_equipment"),
            "topic",
            "new_winning_mechanism",
            {
                "discovery_blueprint": {
                    "execution_profile_id": "winning_swarm_dynamic_v2"
                },
                "source_priorities": [
                    {"url": "https://shared.example/program", "title": "shared"}
                ],
            },
        )
    )

    assert result.packet.handoff_summary == "检索受限但未阻塞基线交接"
    # The generic contract may invoke one bounded missing-field repair after
    # analysis; the failed discovery lane itself is never retried.
    assert len(backend.inputs) in {2, 3}
    discovery_options = backend.inputs[0]
    assert discovery_options["_provider_timeout_seconds"] == 90
    assert discovery_options["_provider_retry_attempts"] == 1
    assert discovery_options["_disable_provider_timeout"] is False
    assert any(
        row.get("event_type") == "baseline_discovery_lane_limited"
        and row.get("fallback") == "reuse_shared_sources_and_explicit_anchors"
        for row in progress_rows
    )
