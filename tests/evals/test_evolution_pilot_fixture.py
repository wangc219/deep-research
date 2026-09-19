"""Contract tests for the deterministic S1-S6 evolution pilot fixture."""

import json
from pathlib import Path

from evals.models import EvalQuery


ROOT = Path(__file__).resolve().parents[2]


def test_evolution_pilot_fixture_is_valid_and_balanced() -> None:
    path = ROOT / "evals" / "fixtures" / "s1_s6_evolution_pilot.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    assert len(rows) == 12
    assert len({row["query_id"] for row in rows}) == len(rows)
    assert {row["difficulty"] for row in rows} == {"medium", "hard"}
    assert all(row["split"] == "pilot" for row in rows)
    assert all(row["seed"] == "evolution-pilot-v1" for row in rows)
    assert {stage for row in rows for stage in row["target_stages"]} == {
        "S1", "S2", "S3", "S4", "S5", "S6"
    }
    for row in rows:
        EvalQuery.from_dict({key: row[key] for key in EvalQuery.__dataclass_fields__})
        assert row["target_metrics"]
        assert row["residual_tags"]


def test_prompt_section_manifest_uses_project_relative_paths() -> None:
    path = ROOT / "src" / "equipment_deep_research" / "agents" / "prompts" / "dynamic_winning" / "section_manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))

    assert manifest["prompt_root"].startswith("src/")
    assert not manifest["prompt_root"].startswith("/")
    assert {item["id"] for item in manifest["change_units"]} == {"CU-S3-S4", "CU-COMMON-RUNTIME"}
    assert all(not item["path"].startswith("/") for item in manifest["files"].values())
