from __future__ import annotations

import json
from pathlib import Path

from equipment_deep_research.orchestration.runner import DeepResearchRunner


ROOT = Path(__file__).parents[3]
CONFIG = ROOT / "configs/equipment_deep_research"


def test_relaxed_quality_gate_does_not_force_mechanical_recall(tmp_path: Path) -> None:
    result = DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path,
        agent_config_path=CONFIG / "agents.yaml",
        preset_config_path=CONFIG / "presets.yaml",
    ).run(
        mode="fake",
        topic="能力缺口",
        research_route="new_winning_mechanism",
        run_id="recall-route",
        agent_ids=["combat_scenario"],
        max_rounds=1,
    )
    domain = [json.loads(line) for line in (Path(result["run_dir"]) / "domain.jsonl").read_text(encoding="utf-8").splitlines()]
    recalls = [row["payload"] for row in domain if row["type"] == "RecallRequest"]
    assert recalls == []
    trace = [json.loads(line) for line in (Path(result["run_dir"]) / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert not any(row["payload"]["event_type"] == "recall_limited" for row in trace)
