from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from platform_core.knowledge.graphs.acceptance_policy import normalize_acceptance_policy
from platform_core.knowledge.training.gold_contract import GoldDocument
from platform_core.knowledge.training.graph_acceptance import (
    PilotBuildStats,
    PredictionDocument,
    assess_pilot_acceptance,
    audit_gold_dataset,
    calibrate_acceptance_policy,
    evaluate_ie_predictions,
)
from platform_core.knowledge.training.graph_retrieval_quality import evaluate_graph_retrieval_quality
from platform_core.knowledge.training.innovation_quality import (
    evaluate_innovation_quality,
    innovation_quality_gate,
)
from platform_core.knowledge.training.retrieval_comparison import (
    compare_retrieval_methods,
    retrieval_comparison_gate,
)


def test_strict_evaluation_covers_entities_relations_alignment_and_evidence():
    gold = _gold_document("test-doc", "test")
    prediction = _prediction_document("test-doc")

    report = evaluate_ie_predictions([gold], [prediction])

    assert report["entity"] == {
        "true_positive": 2,
        "false_positive": 0,
        "false_negative": 0,
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
    }
    assert report["relation"]["f1"] == 1.0
    assert report["alignment"] == {"correct": 2, "total": 2, "accuracy": 1.0}
    assert report["evidence"]["span_rebuild_rate"] == 1.0
    assert report["evidence"]["completeness"] == 1.0


def test_strict_relation_requires_endpoint_type_and_direction_complete_match():
    gold = _gold_document("test-doc", "test")
    payload = _prediction_document("test-doc").model_dump(mode="json")
    payload["relations"][0]["source_entity_id"] = "e2"
    payload["relations"][0]["target_entity_id"] = "e1"
    prediction = PredictionDocument.model_validate(payload)

    report = evaluate_ie_predictions([gold], [prediction])

    assert report["entity"]["f1"] == 1.0
    assert report["relation"]["true_positive"] == 0
    assert report["relation"]["false_positive"] == 1
    assert report["relation"]["false_negative"] == 1


def test_gold_audit_seals_test_hash_and_requires_double_annotation():
    documents = [
        _gold_document("train-doc", "train"),
        _gold_document("dev-doc", "dev"),
        _gold_document("test-doc", "test"),
    ]

    report = audit_gold_dataset(
        documents,
        expected_splits={"train": 1, "dev": 1, "test": 1},
    )

    assert report["pilot_ready"] is True
    assert report["split_counts"] == {"train": 1, "dev": 1, "test": 1}
    assert len(report["sealed_test_documents"]["test-doc"]) == 64
    assert len(report["sealed_test_manifest_sha256"]) == 64

    invalid = _gold_document("invalid", "test").model_copy(update={"annotation": None})
    failed = audit_gold_dataset(
        [invalid],
        expected_splits={"train": 0, "dev": 0, "test": 1},
    )
    assert failed["pilot_ready"] is False
    assert any("缺少标注来源" in error for error in failed["errors"])


def test_gold_audit_allows_dual_model_prelabels_only_after_full_expert_review():
    document = _gold_document("model-reviewed", "test")
    payload = document.model_dump(mode="json")
    payload["annotation"] = {
        "review_mode": "dual_model_expert",
        "model_prelabel_ids": [
            "lightrag:fastino/lightrag.5-multi-v1@balanced",
            "lightrag:fastino/lightrag.5-multi-v1@strict",
        ],
        "arbitrator_id": "pilotzhongcaizhuanji",
        "adjudicated": True,
        "expert_review_scope": "all_candidates",
        "guideline_version": "defense-kg-model-assisted-annotation-v1",
    }

    report = audit_gold_dataset(
        [GoldDocument.model_validate(payload)],
        expected_splits={"train": 0, "dev": 0, "test": 1},
    )

    assert report["pilot_ready"] is True

    payload["annotation"]["expert_review_scope"] = "differences_only"
    incomplete = audit_gold_dataset(
        [GoldDocument.model_validate(payload)],
        expected_splits={"train": 0, "dev": 0, "test": 1},
    )
    assert incomplete["pilot_ready"] is False
    assert any("未经专家全量审核" in error for error in incomplete["errors"])


def test_calibration_uses_dev_only_and_selects_precision_safe_thresholds():
    gold = _gold_document("dev-doc", "dev")
    payload = _prediction_document("dev-doc").model_dump(mode="json")
    payload["entities"].append(
        {
            "entity_id": "false-e3",
            "block_id": "dev-doc-b1",
            "type": "KeyTechnology",
            "text": "提升",
            "start": 5,
            "end": 7,
            "confidence": 0.8,
            "review_status": "pending",
        }
    )
    payload["relations"].append(
        {
            "relation_id": "false-r2",
            "type": "ENABLES_CAPABILITY",
            "source_entity_id": "false-e3",
            "target_entity_id": "e2",
            "confidence": 0.7,
            "claim_level": "Fact",
            "review_status": "pending",
        }
    )
    prediction = PredictionDocument.model_validate(payload)

    policy = calibrate_acceptance_policy(
        [gold],
        [prediction],
        pipeline_revision="hybrid-v2-r1",
    )

    assert policy["calibrated"] is True
    assert policy["auto_accept_enabled"] is True
    assert policy["entity_thresholds"]["KeyTechnology"] == pytest.approx(0.94)
    assert policy["relation_thresholds"]["ENABLES_CAPABILITY"] == pytest.approx(0.91)
    assert policy["entity_precision"] == 1.0
    assert policy["relation_precision"] == 1.0
    normalized = normalize_acceptance_policy(policy, pipeline_revision="hybrid-v2-r1")
    assert normalized["calibrated_entity_types"] == ["Capability", "KeyTechnology"]
    assert normalized["calibrated_relation_types"] == ["ENABLES_CAPABILITY"]


def test_calibration_stays_disabled_when_a_label_cannot_reach_precision_gate():
    gold = _gold_document("dev-doc", "dev")
    payload = _prediction_document("dev-doc").model_dump(mode="json")
    payload["entities"] = [
        {
            "entity_id": "false-e1",
            "block_id": "dev-doc-b1",
            "type": "KeyTechnology",
            "text": "提升",
            "start": 5,
            "end": 7,
            "confidence": 1.0,
            "review_status": "pending",
        }
    ]
    payload["relations"] = []
    prediction = PredictionDocument.model_validate(payload)

    policy = calibrate_acceptance_policy(
        [gold],
        [prediction],
        pipeline_revision="hybrid-v2-r1",
    )

    assert policy["calibrated"] is False
    assert policy["auto_accept_enabled"] is False
    assert "KeyTechnology" in policy["calibration_report"]["entity"]["unmet_labels"]


def test_pilot_acceptance_requires_every_scale_quality_and_operational_gate():
    metrics = evaluate_ie_predictions(
        [_gold_document("test-doc", "test")],
        [_prediction_document("test-doc")],
    )
    stats = PilotBuildStats(
        source_documents=1000,
        paper_documents=1000,
        patent_documents=0,
        documents_with_build_runs=1000,
        accepted_entities=5000,
        accepted_relations=20000,
        duplicate_relation_mentions_excluded=True,
        unreviewed_hypotheses_excluded=True,
    )
    operational_checks = {
        "dynamic_update_verified": True,
        "multi_hop_query_verified": True,
        "evolution_analysis_verified": True,
        "innovation_integration_verified": True,
        "api_contract_verified": True,
        "reproducible_report_verified": True,
    }

    passed = assess_pilot_acceptance(
        gold_audit={"pilot_ready": True},
        sealed_test_metrics=metrics,
        build_stats=stats,
        operational_checks=operational_checks,
        retrieval_comparison=_passing_retrieval_comparison_report(),
        graph_retrieval_quality=_passing_graph_retrieval_quality_report(),
        innovation_quality=_passing_innovation_quality_report(),
    )
    assert passed["passed"] is True
    assert passed["failed_criteria"] == []

    missing_retrieval = assess_pilot_acceptance(
        gold_audit={"pilot_ready": True},
        sealed_test_metrics=metrics,
        build_stats=stats,
        operational_checks=operational_checks,
        graph_retrieval_quality=_passing_graph_retrieval_quality_report(),
        innovation_quality=_passing_innovation_quality_report(),
    )
    assert missing_retrieval["passed"] is False
    assert "retrieval_comparison_complete" in missing_retrieval["failed_criteria"]

    missing_graph_quality = assess_pilot_acceptance(
        gold_audit={"pilot_ready": True},
        sealed_test_metrics=metrics,
        build_stats=stats,
        operational_checks=operational_checks,
        retrieval_comparison=_passing_retrieval_comparison_report(),
        innovation_quality=_passing_innovation_quality_report(),
    )
    assert missing_graph_quality["passed"] is False
    assert "retrieval_quality_complete" in missing_graph_quality["failed_criteria"]

    failed_stats = stats.model_copy(update={"accepted_relations": 19999})
    failed = assess_pilot_acceptance(
        gold_audit={"pilot_ready": True},
        sealed_test_metrics=metrics,
        build_stats=failed_stats,
        operational_checks=operational_checks,
        retrieval_comparison=_passing_retrieval_comparison_report(),
        graph_retrieval_quality=_passing_graph_retrieval_quality_report(),
        innovation_quality=_passing_innovation_quality_report(),
    )
    assert failed["passed"] is False
    assert failed["failed_criteria"] == ["accepted_relations"]


def test_innovation_quality_evaluates_docx_dimensions_and_fails_closed():
    report = evaluate_innovation_quality(_innovation_quality_cases())

    assert report["complete"] is True
    graphrag = report["methods"]["graphrag"]
    assert graphrag["requirement_entity_match"]["f1"] == 1
    assert graphrag["path_validity"] == 1
    assert graphrag["multi_hop_relevance"] == 1
    assert graphrag["candidate_relation_rationality"] == 1
    assert graphrag["solution_evidence_consistency"] == 1
    assert graphrag["unsupported_claim_rate"] == 0
    assert graphrag["expert_acceptance_rate"] == 1
    assert all(item["passed"] for item in innovation_quality_gate(report))

    assert all(not item["passed"] for item in innovation_quality_gate(None))

    no_effect = deepcopy(_innovation_quality_cases())
    for case in no_effect:
        case["solution_claims"] = [
            {"claim_id": f"{case['method']}-claim1", "evidence_ids": ["E001"], "evidence_supported": True}
        ]
        case["expert_accepted"] = True
    no_effect_gate = {item["id"]: item for item in innovation_quality_gate(evaluate_innovation_quality(no_effect))}
    assert no_effect_gate["hallucination_suppression_vs_llm_unconstrained"]["passed"] is False
    assert no_effect_gate["innovation_expert_gain_vs_llm_unconstrained"]["passed"] is False

    inconsistent = deepcopy(_innovation_quality_cases())
    inconsistent[1]["gold_requirement_entity_ids"] = ["different-capability"]
    with pytest.raises(ValueError, match="共享相同 query 和需求实体金标"):
        evaluate_innovation_quality(inconsistent)


def test_retrieval_comparison_reports_graphrag_deltas_and_missing_methods():
    cases = _retrieval_comparison_cases()

    report = compare_retrieval_methods(cases)

    assert report["complete"] is True
    assert report["methods"]["graphrag"]["recall@3"] == 1.0
    assert report["methods"]["graphrag"]["evidence_coverage"] == 1.0
    assert report["graphrag_deltas"]["keyword"]["recall@3"] == 0.5

    incomplete = deepcopy(cases)
    incomplete[0]["runs"] = incomplete[0]["runs"][:-1]
    missing = compare_retrieval_methods(incomplete)
    assert missing["complete"] is False
    assert missing["missing_methods_by_query"] == {"q1": ["graphrag"]}


def test_retrieval_comparison_gate_requires_quality_and_advantage():
    report = compare_retrieval_methods(_retrieval_comparison_cases())

    criteria = retrieval_comparison_gate(report)

    assert all(item["passed"] for item in criteria)
    assert all(not item["passed"] for item in retrieval_comparison_gate(None))

    no_gain_cases = deepcopy(_retrieval_comparison_cases())
    graph_run = no_gain_cases[0]["runs"][-1]
    no_gain_cases[0]["runs"] = [
        {**run, "retrieved_ids": graph_run["retrieved_ids"], "evidence_ids": graph_run["evidence_ids"]}
        for run in no_gain_cases[0]["runs"]
    ]
    no_gain = {item["id"]: item for item in retrieval_comparison_gate(compare_retrieval_methods(no_gain_cases))}
    assert no_gain["graphrag_non_degradation_vs_keyword"]["passed"] is True
    assert no_gain["graphrag_gain_vs_keyword"]["passed"] is False


def test_evaluation_cli_writes_reproducible_bundle_and_fails_closed(tmp_path):
    gold_path = tmp_path / "gold.jsonl"
    prediction_path = tmp_path / "predictions.jsonl"
    innovation_path = tmp_path / "innovation.json"
    retrieval_path = tmp_path / "retrieval.json"
    graph_retrieval_path = tmp_path / "graph-retrieval.json"
    build_stats_path = tmp_path / "build-stats.json"
    operational_checks_path = tmp_path / "operational-checks.json"
    output = tmp_path / "report"
    gold_documents = [
        _gold_document("train-doc", "train"),
        _gold_document("dev-doc", "dev"),
        _gold_document("test-doc", "test"),
    ]
    prediction_documents = [_prediction_document("dev-doc"), _prediction_document("test-doc")]
    gold_path.write_text(
        "".join(document.model_dump_json() + "\n" for document in gold_documents),
        encoding="utf-8",
    )
    prediction_path.write_text(
        "".join(document.model_dump_json() + "\n" for document in prediction_documents),
        encoding="utf-8",
    )
    innovation_path.write_text(json.dumps(_innovation_quality_cases(), ensure_ascii=False), encoding="utf-8")
    retrieval_path.write_text(json.dumps(_retrieval_comparison_cases(), ensure_ascii=False), encoding="utf-8")
    graph_retrieval_path.write_text(
        json.dumps(_graph_retrieval_quality_cases(), ensure_ascii=False),
        encoding="utf-8",
    )
    build_stats_path.write_text(json.dumps(_passing_build_stats(), ensure_ascii=False), encoding="utf-8")
    operational_checks_path.write_text(json.dumps(_passing_operational_checks(), ensure_ascii=False), encoding="utf-8")
    backend_root = Path(__file__).parents[3]
    command = [
        sys.executable,
        str(backend_root / "scripts/evaluate_knowledge_graph.py"),
        "--gold",
        str(gold_path),
        "--predictions",
        str(prediction_path),
        "--pipeline-revision",
        "hybrid-v2-r1",
        "--output",
        str(output),
        "--innovation-cases",
        str(innovation_path),
        "--retrieval-cases",
        str(retrieval_path),
        "--graph-retrieval-cases",
        str(graph_retrieval_path),
        "--build-stats",
        str(build_stats_path),
        "--operational-checks",
        str(operational_checks_path),
        "--allow-non-pilot-gold",
        "--require-pass",
    ]

    result = subprocess.run(command, cwd=backend_root, capture_output=True, text=True, check=False)

    assert result.returncode == 2
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["report_contract"] == "defense-kg-evaluation-bundle-v4"
    assert manifest["calibration_ready"] is True
    assert manifest["pilot_passed"] is False
    assert str(innovation_path) in manifest["inputs"]
    assert str(retrieval_path) in manifest["inputs"]
    assert str(graph_retrieval_path) in manifest["inputs"]
    assert str(build_stats_path) in manifest["inputs"]
    assert str(operational_checks_path) in manifest["inputs"]
    assert set(manifest["reports"]) == {
        "acceptance-policy.json",
        "gold-audit.json",
        "innovation-quality.json",
        "graph-retrieval-quality.json",
        "pilot-acceptance.json",
        "retrieval-comparison.json",
        "sealed-test-metrics.json",
    }
    acceptance = json.loads((output / "pilot-acceptance.json").read_text(encoding="utf-8"))
    assert acceptance["failed_criteria"] == ["gold_dataset"]
    gold_audit = json.loads((output / "gold-audit.json").read_text(encoding="utf-8"))
    assert gold_audit["evaluation_scope"] == "development_only"
    assert gold_audit["pilot_ready"] is False


def _gold_document(document_id: str, split: str) -> GoldDocument:
    return GoldDocument.model_validate(
        {
            "document_id": document_id,
            "title": "相控阵雷达能力研究",
            "split": split,
            "language": "zh",
            "source_type": "patent" if document_id.startswith("test") else "paper",
            "domain": "雷达、感知与电子对抗",
            "source_version": "v1",
            "annotation": {
                "annotator_ids": ["annotator-a", "annotator-b"],
                "arbitrator_id": "expert-c",
                "adjudicated": True,
                "guideline_version": "defense-kg-annotation-v1",
            },
            "blocks": [{"block_id": f"{document_id}-b1", "text": "相控阵雷达提升探测能力", "page": 1}],
            "entities": [
                {
                    "entity_id": "e1",
                    "block_id": f"{document_id}-b1",
                    "type": "KeyTechnology",
                    "text": "相控阵雷达",
                    "start": 0,
                    "end": 5,
                    "canonical_entity_id": "canonical-radar",
                },
                {
                    "entity_id": "e2",
                    "block_id": f"{document_id}-b1",
                    "type": "Capability",
                    "text": "探测能力",
                    "start": 7,
                    "end": 11,
                    "canonical_entity_id": "canonical-detection",
                },
            ],
            "relations": [
                {
                    "relation_id": "r1",
                    "type": "ENABLES_CAPABILITY",
                    "source_entity_id": "e1",
                    "target_entity_id": "e2",
                    "evidence_block_ids": [f"{document_id}-b1"],
                    "evidence_spans": [
                        {
                            "block_id": f"{document_id}-b1",
                            "start": 0,
                            "end": 11,
                            "text": "相控阵雷达提升探测能力",
                        }
                    ],
                    "claim_level": "Fact",
                }
            ],
        }
    )


def _prediction_document(document_id: str) -> PredictionDocument:
    return PredictionDocument.model_validate(
        {
            "document_id": document_id,
            "pipeline_revision": "hybrid-v2-r1",
            "model_version": "lightrag.5-multi-v1",
            "entities": [
                {
                    "entity_id": "e1",
                    "block_id": f"{document_id}-b1",
                    "type": "KeyTechnology",
                    "text": "相控阵雷达",
                    "start": 0,
                    "end": 5,
                    "confidence": 0.94,
                    "canonical_entity_id": "canonical-radar",
                    "review_status": "accepted",
                },
                {
                    "entity_id": "e2",
                    "block_id": f"{document_id}-b1",
                    "type": "Capability",
                    "text": "探测能力",
                    "start": 7,
                    "end": 11,
                    "confidence": 0.95,
                    "canonical_entity_id": "canonical-detection",
                    "review_status": "accepted",
                },
            ],
            "relations": [
                {
                    "relation_id": "r1",
                    "type": "ENABLES_CAPABILITY",
                    "source_entity_id": "e1",
                    "target_entity_id": "e2",
                    "confidence": 0.91,
                    "evidence_spans": [
                        {
                            "block_id": f"{document_id}-b1",
                            "start": 0,
                            "end": 11,
                            "text": "相控阵雷达提升探测能力",
                        }
                    ],
                    "claim_level": "Fact",
                    "review_status": "accepted",
                }
            ],
        }
    )


def _passing_innovation_quality_report() -> dict:
    return evaluate_innovation_quality(_innovation_quality_cases())


def _passing_build_stats() -> dict:
    return {
        "source_documents": 1000,
        "paper_documents": 1000,
        "patent_documents": 0,
        "documents_with_build_runs": 1000,
        "accepted_entities": 5000,
        "accepted_relations": 20000,
        "duplicate_relation_mentions_excluded": True,
        "unreviewed_hypotheses_excluded": True,
    }


def _passing_operational_checks() -> dict:
    return {
        "dynamic_update_verified": True,
        "multi_hop_query_verified": True,
        "evolution_analysis_verified": True,
        "innovation_integration_verified": True,
        "api_contract_verified": True,
        "reproducible_report_verified": True,
    }


def _passing_retrieval_comparison_report() -> dict:
    return compare_retrieval_methods(_retrieval_comparison_cases())


def _passing_graph_retrieval_quality_report() -> dict:
    return evaluate_graph_retrieval_quality(_graph_retrieval_quality_cases())


def _graph_retrieval_quality_cases() -> list[dict]:
    records = []
    for method in (
        "keyword",
        "entity_vector",
        "triple_vector",
        "lightrag_hybrid",
        "lightrag_mix",
    ):
        enhanced = method.startswith("lightrag_")
        records.append(
            {
                "query_id": "graph-q1",
                "query": "哪些关键技术跨文档支撑探测能力？",
                "method": method,
                "gold_entity_ids": ["e1", "e2"],
                "gold_triple_ids": ["r1", "r2"],
                "retrieved_entity_ids": ["e1", "e2"] if enhanced else ["e1"],
                "retrieved_triple_ids": ["r1", "r2"] if enhanced else ["r1"],
                "retrieved_paths": [
                    {
                        "path_id": f"{method}-path",
                        "relation_ids": ["r1", "r2"],
                        "chunk_ids": ["c1", "c2"],
                        "file_ids": ["f1", "f2"],
                        "valid": True,
                        "relevant": True,
                    }
                ],
                "judgment": {
                    "source": "human",
                    "reviewer_id": "reviewer-1",
                    "reviewed_at": "2026-11-03T10:00:00+08:00",
                    "guideline_version": "defense-kg-retrieval-review-v1",
                },
            }
        )
    return records


def _retrieval_comparison_cases() -> list[dict]:
    return [
        {
            "query_id": "q1",
            "query": "哪些技术提升探测能力？",
            "gold_ids": ["e1", "e2"],
            "runs": [
                {
                    "method": "keyword",
                    "retrieved_ids": ["e1", "x"],
                    "evidence_ids": ["e1"],
                    "latency_ms": 10,
                },
                {
                    "method": "vector",
                    "retrieved_ids": ["x", "e2"],
                    "evidence_ids": ["e2"],
                    "latency_ms": 20,
                },
                {
                    "method": "llm_unconstrained",
                    "retrieved_ids": ["x"],
                    "evidence_ids": [],
                    "latency_ms": 30,
                },
                {
                    "method": "graphrag",
                    "retrieved_ids": ["e1", "e2"],
                    "evidence_ids": ["e1", "e2"],
                    "latency_ms": 40,
                },
            ],
        }
    ]


def _innovation_quality_cases() -> list[dict]:
    cases = []
    for method in ("keyword", "vector", "llm_unconstrained", "graphrag"):
        case = {
            "query_id": "innovation-q1",
            "query": "提升探测能力",
            "method": method,
            "gold_requirement_entity_ids": ["capability-detection"],
            "predicted_requirement_entity_ids": ["capability-detection"],
            "retrieved_paths": [{"path_id": f"{method}-p1", "hop_count": 2, "valid": True, "relevant": True}],
            "candidate_relations": [{"candidate_id": f"{method}-c1", "rational": True}],
            "solution_claims": [
                {
                    "claim_id": f"{method}-claim1",
                    "evidence_ids": ["E001"],
                    "evidence_supported": True,
                }
            ],
            "expert_accepted": True,
        }
        if method == "llm_unconstrained":
            case["solution_claims"] = [
                {
                    "claim_id": f"{method}-claim1",
                    "evidence_ids": [],
                    "evidence_supported": False,
                }
            ]
            case["expert_accepted"] = False
        cases.append(case)
    return cases
