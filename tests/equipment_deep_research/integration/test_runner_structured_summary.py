from __future__ import annotations

import json
from pathlib import Path

from equipment_deep_research.orchestration.runner import DeepResearchRunner


ROOT = Path(__file__).parents[3]
CONFIG = ROOT / "configs/equipment_deep_research"


def test_runner_exposes_provider_plan_reasoning_and_evidence_governance(tmp_path: Path) -> None:
    result = DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path / "runs",
        agent_config_path=CONFIG / "agents.yaml",
        preset_config_path=CONFIG / "presets.yaml",
        provider_config_path=CONFIG / "providers.yaml",
        evidence_config_path=CONFIG / "evidence.yaml",
    ).run(
        mode="fake",
        topic="低空无人机探测预警能力",
        research_route="new_winning_mechanism",
        run_id="structured-summary",
    )
    summary = json.loads(Path(result["summary_path"]).read_text(encoding="utf-8"))
    assert summary["provider"]["type"] == "fake"
    assert summary["plan_graph"]["baseline_map_count"] == 4
    assert summary["six_step_reasoning"]["gap_matrix"]["input_refs"]
    assert summary["evidence_assessments"]
    assert all(item["decision"] in {"accepted", "rejected", "duplicate"} for item in summary["evidence_assessments"])
