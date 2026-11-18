from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from platform_core.knowledge.training.lightrag_path_reranking_evaluation import evaluate_path_reranking


def _payload():
    return {
        "contract": "defense-kg-lightrag-path-reranking-evaluation-v1",
        "pipeline_revision": "hybrid-v2-r4",
        "k": 3,
        "minimum_ndcg_gain": 0.02,
        "max_latency_p95_ratio": 3,
        "max_llm_calls_per_query": 1,
        "max_estimated_cost": 1,
        "cases": [
            {
                "query_sha256": "a" * 64,
                "candidate_path_ids": ["p1", "p2", "p3", "p4"],
                "deterministic_ranking": ["p1", "p3", "p2", "p4"],
                "enhanced_ranking": ["p2", "p4", "p1", "p3"],
                "relevant_path_ids": ["p2", "p4"],
                "valid_path_ids": ["p1", "p2", "p4"],
                "deterministic_runtime": {"latency_ms": 100, "llm_calls": 0, "estimated_cost": 0},
                "enhanced_runtime": {"latency_ms": 180, "llm_calls": 1, "estimated_cost": 0.1},
                "judgment": {
                    "source": "human",
                    "reviewer_id": "reviewer-1",
                    "reviewed_at": "2026-11-03T15:00:00+08:00",
                    "guideline_version": "path-reranking-v1",
                },
            }
        ],
    }


def test_path_reranking_evaluation_proves_closed_paired_gain_and_cost():
    report = evaluate_path_reranking(_payload())

    assert report["passed"] is True
    assert report["contains_source_text"] is False
    assert report["metrics"]["enhanced"]["recall_at_k"] == 1
    assert report["metrics"]["delta"]["ndcg_at_k"] > 0
    assert report["metrics"]["runtime"]["enhanced"]["llm_calls_per_query"] == 1
    assert report["reviewer_ids"] == ["reviewer-1"]


def test_path_reranking_evaluation_rejects_open_or_fake_human_results():
    open_candidates = _payload()
    open_candidates["cases"][0]["enhanced_ranking"] = ["p2", "p4", "p1", "forged"]
    with pytest.raises(ValueError, match="同一封闭候选集"):
        evaluate_path_reranking(open_candidates)

    model_judgment = _payload()
    model_judgment["cases"][0]["judgment"]["source"] = "model"
    with pytest.raises(ValueError, match="human"):
        evaluate_path_reranking(model_judgment)


def test_path_reranking_quality_or_runtime_regression_blocks_gate():
    regressed = deepcopy(_payload())
    regressed["cases"][0]["enhanced_ranking"] = ["p3", "p1", "p2", "p4"]
    regressed["cases"][0]["enhanced_runtime"]["latency_ms"] = 500

    report = evaluate_path_reranking(regressed)
    gates = {item["id"]: item for item in report["gates"]}

    assert report["passed"] is False
    assert gates["ndcg_material_gain"]["passed"] is False
    assert gates["latency_p95_ratio"]["passed"] is False


def test_path_reranking_cli_writes_redacted_report(tmp_path):
    source = tmp_path / "input.json"
    output = tmp_path / "report.json"
    source.write_text(json.dumps(_payload(), ensure_ascii=False), encoding="utf-8")
    script = Path(__file__).parents[3] / "scripts" / "evaluate_lightrag_path_reranking.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--input",
            str(source),
            "--output",
            str(output),
            "--require-pass",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["contains_source_text"] is False
