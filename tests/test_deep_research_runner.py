from __future__ import annotations

import json
from pathlib import Path

import pytest

from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.orchestration.runner import DeepResearchRunner
from equipment_deep_research.tools.permissions import ToolPermissionRegistry


ROOT = Path(__file__).resolve().parents[1]


def _runner(tmp_path: Path) -> DeepResearchRunner:
    return DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path,
        agent_config_path=ROOT / "configs" / "equipment_deep_research" / "agents.yaml",
        preset_config_path=ROOT / "configs" / "equipment_deep_research" / "presets.yaml",
    )


def test_fake_default_full_loop_outputs_files(tmp_path: Path) -> None:
    result = _runner(tmp_path).run(
        mode="fake",
        topic="低空无人机探测预警能力缺口",
        research_route="auto",
        run_id="fake-full",
    )
    run_dir = Path(result["run_dir"])
    assert (run_dir / "report.md").exists()
    assert (run_dir / "capability_images.json").exists()
    assert (run_dir / "round_summary.json").exists()
    assert (run_dir / "domain.jsonl").exists()
    assert (run_dir / "trace.jsonl").exists()
    assert (run_dir / "artifacts").exists()
    images = json.loads((run_dir / "capability_images.json").read_text(encoding="utf-8"))
    assert {item["capability_type"] for item in images} == {"new_capability", "upgrade"}
    assert "需要发展具备" not in (run_dir / "report.md").read_text(encoding="utf-8")
    assert result["stage_count"] == 3
    summary = json.loads((run_dir / "round_summary.json").read_text(encoding="utf-8"))
    assert summary["store_summary"]["materialized_evidence_count"] == 4
    assert len(summary["source_materials"]) == 4


def test_subset_agents_runs_with_coverage_limits(tmp_path: Path) -> None:
    result = _runner(tmp_path).run(
        mode="fake",
        topic="低空无人机探测预警能力缺口",
        research_route="auto",
        run_id="fake-subset",
        agent_ids=["combat_scenario", "weapon_equipment"],
    )
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert summary["selected_agent_ids"] == ["combat_scenario", "weapon_equipment"]
    assert summary["coverage"]["missing_required_tags"]
    report = Path(result["report_path"]).read_text(encoding="utf-8")
    assert "缺失关键能力标签" in report


def test_three_research_routes_have_e2e(tmp_path: Path) -> None:
    for route in ["new_winning_mechanism", "traditional_gap", "war_case_learning"]:
        result = _runner(tmp_path).run(
            mode="fake",
            topic=f"{route} 测试主题",
            research_route=route,
            run_id=f"run-{route}",
        )
        summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
        assert summary["resolved_route"] == route
        assert result["capability_count"] == 2


def test_real_smoke_materializes_public_source_diagnostics(tmp_path: Path) -> None:
    result = _runner(tmp_path).run(
        mode="real",
        topic="低空无人机探测预警能力缺口",
        research_route="auto",
        run_id="real-smoke",
    )
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert summary["mode"] == "real"
    assert len(summary["source_materials"]) == 4
    assert all(row["artifact_refs"] for row in summary["source_materials"])


def test_unapproved_public_source_is_not_formal_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from equipment_deep_research.agents import provider

    monkeypatch.setattr(provider, "_public_smoke_url_for_agent", lambda agent_id: "https://example.com/not-approved")
    result = _runner(tmp_path).run(
        mode="real",
        topic="低空无人机探测预警能力缺口",
        research_route="auto",
        run_id="blocked-source",
        agent_ids=["international_situation"],
    )
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert summary["source_materials"][0]["status"] == "blocked_unapproved_source"
    assert summary["store_summary"]["evidence_count"] == 0
    domain_rows = [
        json.loads(line)
        for line in (Path(result["run_dir"]) / "domain.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    packets = [row["payload"] for row in domain_rows if row["type"] == "BaselineFindingPacket"]
    assert packets[0]["evidence_ids"] == []
    assert result["audit_status"] == "limited"


def test_recall_requests_are_traceable_for_missing_coverage(tmp_path: Path) -> None:
    result = _runner(tmp_path).run(
        mode="fake",
        topic="低空无人机探测预警能力缺口",
        research_route="new_winning_mechanism",
        run_id="recall-trace",
        agent_ids=["combat_scenario", "weapon_equipment"],
    )
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert summary["recall_requests"]
    trace_rows = [
        json.loads(line)
        for line in (Path(result["run_dir"]) / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    recall_events = [row["payload"] for row in trace_rows if row["payload"]["event_type"] == "recall_requested"]
    assert {event["payload"]["target_capability_tag"] for event in recall_events} >= {"operation", "threat"}


def test_custom_agent_config_can_replace_default_baseline(tmp_path: Path) -> None:
    custom_agents = tmp_path / "agents.yaml"
    custom_agents.write_text(
        """
default_model: gpt-5.6-sol
agents:
  - agent_id: integrated_research
    display_name: 综合研判
    description: 覆盖首版新制胜机理路线所需标签的替换agent。
    capability_tags: [situation, threat, scenario, equipment, operation]
    tools: [search_sources, fetch_page, create_evidence_card]
    context_policy:
      visible_sections: [task, source_policy, own_checkpoint, recall_request]
    enabled: true
""".strip()
        + "\n",
        encoding="utf-8",
    )
    result = DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path,
        agent_config_path=custom_agents,
        preset_config_path=ROOT / "configs" / "equipment_deep_research" / "presets.yaml",
    ).run(
        mode="fake",
        topic="新型协同防空能力方向",
        research_route="new_winning_mechanism",
        run_id="custom-agent",
        agent_ids=["integrated_research"],
    )
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert summary["selected_agent_ids"] == ["integrated_research"]
    assert summary["coverage"]["coverage_passed"] is True


def test_tool_permission_denial_is_enforced() -> None:
    agent = AgentDef(
        agent_id="limited_agent",
        display_name="受限智能体",
        description="只允许写证据卡。",
        capability_tags=["scenario"],
        tools=["create_evidence_card"],
        context_policy={},
    )
    with pytest.raises(PermissionError):
        ToolPermissionRegistry.default().enforce_active_tool(agent, "fetch_page")
