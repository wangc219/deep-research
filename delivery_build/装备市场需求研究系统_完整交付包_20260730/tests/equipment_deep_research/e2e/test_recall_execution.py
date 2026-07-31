from __future__ import annotations

import json
from pathlib import Path

from equipment_deep_research.agents.provider import AgentRunRequest, AgentRunResult
from equipment_deep_research.domain.models import BaselineFindingPacket, EvidenceCard
from equipment_deep_research.orchestration.runner import DeepResearchRunner


ROOT = Path(__file__).parents[3]
CONFIG = ROOT / "configs/equipment_deep_research"


class LowThenHighProvider:
    def run_baseline_agent(self, request: AgentRunRequest) -> AgentRunResult:
        round_index = request.round_index
        suffix = "" if round_index == 1 else f"-r{round_index}"
        evidence = EvidenceCard(
            f"ev-{request.agent.agent_id}{suffix}", "fixture", f"https://fixture.local/{request.agent.agent_id}{suffix}", "A",
            "可材料化公开证据", "可用于定向补充的直接摘录", "fixture:1", "fixture", request.agent.agent_id,
        )
        confidence = .65 if round_index == 1 else .9
        packet = BaselineFindingPacket(
            f"packet-{request.agent.agent_id}{suffix}", request.agent.agent_id, list(request.agent.capability_tags), request.topic,
            ["结构化发现"], [evidence.evidence_id], confidence, [], [], "定向补充完成", f"round={round_index}",
        )
        return AgentRunResult(packet, [evidence], "structured")


class RecallWithoutEvidenceProvider(LowThenHighProvider):
    def run_baseline_agent(self, request: AgentRunRequest) -> AgentRunResult:
        result = super().run_baseline_agent(request)
        if request.round_index == 1:
            return result
        packet = BaselineFindingPacket(
            f"packet-{request.agent.agent_id}-r{request.round_index}",
            request.agent.agent_id,
            list(request.agent.capability_tags),
            request.topic,
            ["再调未检得可材料化证据"],
            [],
            .9,
            [],
            ["仍缺少直接证据"],
            "再调完成但没有新增证据",
            f"round={request.round_index}",
        )
        return AgentRunResult(packet, [], "structured")


def test_runner_executes_routed_recall_and_reevaluates_gates_without_rerun(tmp_path: Path) -> None:
    result = DeepResearchRunner(
        project_root=ROOT, output_root=tmp_path, agent_config_path=CONFIG / "agents.yaml", preset_config_path=CONFIG / "presets.yaml", provider=LowThenHighProvider(),
    ).run(mode="fake", topic="定向再调", research_route="new_winning_mechanism", run_id="recall-execution")
    trace = [json.loads(line)["payload"] for line in (Path(result["run_dir"]) / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    kinds = [row["event_type"] for row in trace]
    assert kinds.index("recall_requested") < kinds.index("recall_task_completed") < kinds.index("recall_supplement_compressed") < kinds.index("winning_stage_gate_reevaluated")
    assert "winning_stage_resumed" not in kinds
    assert not any(
        row["event_type"] == "winning_stage_completed"
        and any(ref.endswith("-r2") for ref in row.get("output_refs", []))
        for row in trace
    )
    domain = [json.loads(line) for line in (Path(result["run_dir"]) / "domain.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(row["type"] == "BaselineFindingPacket" and row["payload"]["packet_id"].endswith("-r2") for row in domain)
    stages = [
        row["payload"]
        for row in domain
        if row["type"] == "WinningMechanismStageOutput"
    ]
    assert [stage["stage_id"] for stage in stages] == [
        "stage-L1",
        "stage-L2",
        "stage-L3",
    ]
    l1 = next(stage for stage in stages if stage["layer"] == "L1")
    supplements = l1["outputs"]["recall_supplements"]
    assert supplements[0]["return_node"] == "L1"
    assert supplements[0]["high_value_findings"] == ["结构化发现"]
    assert supplements[0]["new_evidence_ids"]
    assert all(stage["gate_passed"] for stage in stages)
    l1_gate_event = next(
        row
        for row in trace
        if row["event_type"] == "winning_stage_gate_reevaluated"
        and row["payload"]["layer"] == "L1"
    )
    assert l1_gate_event["payload"]["before_gate_passed"] is False
    assert l1_gate_event["payload"]["after_gate_passed"] is True
    assert l1_gate_event["payload"]["winning_chain_rerun"] is False


def test_recall_without_new_evidence_remains_limited_with_specific_reason(
    tmp_path: Path,
) -> None:
    result = DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path,
        agent_config_path=CONFIG / "agents.yaml",
        preset_config_path=CONFIG / "presets.yaml",
        provider=RecallWithoutEvidenceProvider(),
    ).run(
        mode="fake",
        topic="无有效补证的定向再调",
        research_route="new_winning_mechanism",
        run_id="recall-no-evidence",
    )
    domain = [
        json.loads(line)
        for line in (Path(result["run_dir"]) / "domain.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    stages = {
        row["payload"]["layer"]: row["payload"]
        for row in domain
        if row["type"] == "WinningMechanismStageOutput"
    }
    assert stages["L1"]["gate_passed"] is False
    assert stages["L1"]["gate_reasons"] == [
        "L1定向再调未形成新增可接纳证据，无法提高制胜逻辑结论置信度"
    ]
    assert stages["L2"]["gate_passed"] is False
    assert stages["L3"]["gate_passed"] is False


def test_callback_agent_closes_coverage_and_rechecks_all_gates(tmp_path: Path) -> None:
    result = DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path,
        agent_config_path=CONFIG / "agents.yaml",
        preset_config_path=CONFIG / "presets.yaml",
    ).run(
        mode="fake",
        topic="南海通信遮断无人协同压力能力研究",
        research_route="traditional_gap",
        run_id="callback-coverage-recheck",
        agent_ids=[
            "system_confrontation",
            "international_situation",
            "combat_scenario",
            "opponent_monitoring",
        ],
        discovery_branch="F",
        max_rounds=3,
    )
    run_dir = Path(result["run_dir"])
    summary = json.loads((run_dir / "round_summary.json").read_text())
    domain = [
        json.loads(line)
        for line in (run_dir / "domain.jsonl").read_text().splitlines()
    ]
    stages = [
        row["payload"]
        for row in domain
        if row["type"] == "WinningMechanismStageOutput"
    ]
    callback_packets = [
        row["payload"]
        for row in domain
        if row["type"] == "BaselineFindingPacket"
        and row["payload"]["agent_id"] == "weapon_equipment"
    ]

    assert summary["coverage"]["coverage_passed"] is True
    assert summary["coverage"]["missing_required_tags"] == []
    assert "weapon_equipment" in summary["selected_agent_ids"]
    assert callback_packets and len(callback_packets) == 1
    assert summary["recall_requests"] == []
    assert summary["discovery_blueprint"]["promoted_callback_agent_ids"] == [
        "weapon_equipment"
    ]
    assert all(stage["gate_passed"] for stage in stages)
    assert [stage["stage_id"] for stage in stages] == [
        "stage-L1",
        "stage-L2",
        "stage-L3",
    ]
    assert summary["agent_recommendations"] == []
    trace = [
        json.loads(line)["payload"]
        for line in (run_dir / "trace.jsonl").read_text().splitlines()
    ]
    coverage_events = [
        row
        for row in trace
        if row["event_type"] == "coverage_recomputed_after_recall"
    ]
    assert coverage_events == []
    baseline_starts = [
        row for row in trace if row["event_type"] == "baseline_wave_started"
    ]
    assert any(
        "weapon_equipment" in row["payload"]["agent_ids"]
        for row in baseline_starts
    )


def test_registry_fallback_routes_unplanned_situation_recall(tmp_path: Path) -> None:
    result = DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path,
        agent_config_path=CONFIG / "agents.yaml",
        preset_config_path=CONFIG / "presets.yaml",
    ).run(
        mode="fake",
        topic="挖掘在西太反介入体系下的装备能力缺口",
        research_route="traditional_gap",
        run_id="situation-registry-recall",
        agent_ids=[
            "combat_scenario",
            "weapon_equipment",
            "system_confrontation",
            "opponent_monitoring",
            "operational_employment",
        ],
        discovery_branch="B",
        max_rounds=3,
    )
    summary = json.loads(Path(result["summary_path"]).read_text())

    assert summary["coverage"]["coverage_passed"] is True
    assert summary["coverage"]["missing_required_tags"] == []
    assert "international_situation" in summary["selected_agent_ids"]
    situation_recalls = [
        item
        for item in summary["recall_requests"]
        if item["target_capability_tag"] == "situation"
    ]
    assert len(situation_recalls) == 1
    assert situation_recalls[0]["target_agent_id"] == "international_situation"
    assert situation_recalls[0]["status"] == "completed"
