from pathlib import Path

import yaml

from evals.ablations import (
    DOMAIN_AGENT_IDS,
    _baseline_only_report,
    _first_pass_report,
    build_no_domain_agents_config,
)


ROOT = Path(__file__).parents[2]


def test_no_domain_config_is_generated_outside_production(tmp_path: Path) -> None:
    production = ROOT / "configs" / "equipment_deep_research" / "agents.yaml"
    before = production.read_bytes()
    target = build_no_domain_agents_config(ROOT, tmp_path / "sandbox")
    payload = yaml.safe_load(target.read_text(encoding="utf-8"))
    ids = {row["agent_id"] for row in payload["agents"]}
    assert "generic_researcher" in ids
    assert not (DOMAIN_AGENT_IDS & ids)
    generic = next(row for row in payload["agents"] if row["agent_id"] == "generic_researcher")
    assert generic["capability_tags"] == ["general_research", "open_source_retrieval"]
    assert generic["research_policy"]["target_source_count"] == 2
    assert generic["research_policy"]["evidence_accept_target"] == 2
    assert generic["model_profile"]["max_output_tokens"] == 1800
    assert production.read_bytes() == before
    assert target.is_relative_to(tmp_path)


def test_artifact_view_reports_exclude_later_reasoning() -> None:
    rows = [
        {"type": "EvidenceCard", "payload": {"source_url": "https://source.example"}},
        {"type": "BaselineFindingPacket", "payload": {"agent_id": "a", "findings": ["first finding"], "open_questions": []}},
        {"type": "BaselineFindingPacket", "payload": {"agent_id": "a", "findings": ["recall finding"], "open_questions": []}},
        {"type": "WinningReasoningNode", "payload": {"step": 1, "title": "first", "summary": "first pass"}},
        {"type": "WinningReasoningNode", "payload": {"step": 1, "title": "later", "summary": "later pass"}},
    ]
    baseline, _ = _baseline_only_report("topic", rows)
    first_pass, _ = _first_pass_report("topic", rows)
    assert "first finding" in baseline
    assert "first pass" in first_pass
    assert "recall finding" not in first_pass
    assert "later pass" not in first_pass
