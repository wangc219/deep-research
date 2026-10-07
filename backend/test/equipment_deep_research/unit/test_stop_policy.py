from equipment_deep_research.agents.provider import AgentRunRequest, FakeAgentProvider
from equipment_deep_research.agents.registry import AgentRegistry
from equipment_deep_research.domain.models import BaselineFindingPacket
from equipment_deep_research.harness.stop_policy import evaluate_baseline_stop
from equipment_deep_research.harness.scheduler import _evidence_only_stop_reasons
from pathlib import Path


ROOT = Path(__file__).parents[3]


def test_default_fake_packets_satisfy_role_structural_stop_contracts() -> None:
    registry = AgentRegistry.load(ROOT / "configs/equipment_deep_research/agents.yaml")
    provider = FakeAgentProvider()
    for agent in registry.enabled_baseline_agents():
        packet = provider.run_baseline_agent(
            AgentRunRequest("run", agent, "topic", "traditional_gap", {})
        ).packet
        assert evaluate_baseline_stop(packet, enforce_evidence_counts=False).allowed


def test_equipment_stop_policy_blocks_missing_units_and_source_count() -> None:
    packet = BaselineFindingPacket(
        packet_id="packet-equipment",
        agent_id="weapon_equipment",
        capability_tags=["equipment"],
        topic_focus="topic",
        findings=["finding"],
        evidence_ids=["ev-1"],
        confidence=0.8,
        coverage_notes=[],
        open_questions=[],
        handoff_summary="handoff",
        checkpoint="complete",
        schema_version="2.0",
        payload_type="equipment_observation_v1",
        payload={
            "equipment_profiles": ["profile"],
            "current_parameters": ["parameter"],
            "parameter_observations": [{"parameter": "range", "value": 10}],
            "parameter_conflicts": ["conflict"],
            "development_models": ["model"],
            "technology_readiness": ["trl"],
            "capability_constraints": ["constraint"],
            "scenario_fit": ["fit"],
            "capability_gaps": ["gap"],
        },
    )

    decision = evaluate_baseline_stop(packet, enforce_evidence_counts=True)
    assert decision.allowed is False
    assert "2条" in " ".join(decision.reasons)
    assert "单位" in " ".join(decision.reasons)


def test_v1_packet_bypasses_v2_role_structural_stop_contracts() -> None:
    packet = BaselineFindingPacket(
        packet_id="packet-v1-strategic",
        agent_id="international_situation",
        capability_tags=["strategic_context"],
        topic_focus="topic",
        findings=["legacy finding"],
        evidence_ids=["ev-1"],
        confidence=0.75,
        coverage_notes=[],
        open_questions=[],
        handoff_summary="legacy handoff",
        checkpoint="complete",
        schema_version="1.0",
        analysis_sections={"strategic_environment": "legacy free-form section"},
    )

    decision = evaluate_baseline_stop(packet, enforce_evidence_counts=True)

    assert decision.allowed is True
    assert decision.reasons == ()


def test_evidence_only_stop_failure_can_use_hypothesis_limited_handoff() -> None:
    assert _evidence_only_stop_reasons(
        ("正式证据少于3条", "独立来源域少于2类")
    ) is True
    assert _evidence_only_stop_reasons(
        ("正式证据少于3条", "缺少参数观测")
    ) is False
