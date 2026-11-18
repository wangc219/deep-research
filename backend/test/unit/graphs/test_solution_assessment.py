from __future__ import annotations

from platform_core.knowledge.graphs.solution_assessment import assess_grounded_solution


def test_assessment_is_deterministic_and_keeps_hypothesis_boundary():
    result = assess_grounded_solution(
        query="提升宽带感知能力",
        solution={
            "mechanism_hypothesis": "技术 A 可能支撑能力 B。",
            "feasibility_basis": ["已有直接关系。"],
            "expected_effects": ["可能改善覆盖范围。"],
            "uncertainties": ["尚无系统试验。"],
            "citations": [
                {"claim_path": "mechanism_hypothesis", "evidence_ids": ["E001"]},
                {"claim_path": "feasibility_basis[0]", "evidence_ids": ["E001"]},
                {"claim_path": "expected_effects[0]", "evidence_ids": ["E002"]},
            ],
            "claim_level": "Hypothesis",
        },
        entities=[{"entity_id": "e1", "name": "技术 A", "type": "KeyTechnology"}],
        paths=[
            {
                "path_id": "p1",
                "relations": [{"type": "ENABLES_CAPABILITY"}],
                "evidence": {"chunk_ids": ["c1"]},
                "evidence_gaps": [],
            }
        ],
        evidence=[
            {
                "evidence_id": "E001",
                "chunk_id": "c1",
                "file_id": "f1",
                "text": "证据一",
                "start_char": 0,
                "end_char": 3,
            },
            {
                "evidence_id": "E002",
                "chunk_id": "c2",
                "file_id": "f2",
                "text": "证据二",
                "start_char": 4,
                "end_char": 7,
            },
        ],
        graph_revision="revision-1",
    )

    assert result["confidence"]["algorithm_version"] == "defense-solution-assessment-v1"
    assert result["confidence"]["components"]["citation_coverage"] == 1
    assert result["confidence"]["interpretation"].endswith("结果始终保持 Hypothesis。")
    assert result["innovation_brief"]["claim_level"] == "Hypothesis"
    assert result["innovation_brief"]["evidence_ids"] == ["E001", "E002"]
    assert result["innovation_brief"]["graph_revision"] == "revision-1"
    assert result["innovation_brief"]["expert_review_required"] is True


def test_assessment_exposes_source_and_span_limitations():
    result = assess_grounded_solution(
        query="需求",
        solution={
            "mechanism_hypothesis": "假设",
            "feasibility_basis": [],
            "expected_effects": [],
            "uncertainties": ["待验证"],
            "citations": [{"claim_path": "mechanism_hypothesis", "evidence_ids": ["E001"]}],
        },
        entities=[],
        paths=[
            {
                "path_id": "p1",
                "relations": [{"type": "BASED_ON"}],
                "evidence": {"chunk_ids": ["c1"]},
                "evidence_gaps": ["缺失试验"],
            }
        ],
        evidence=[{"evidence_id": "E001", "chunk_id": "c1", "file_id": "f1", "text": "证据"}],
        graph_revision=None,
    )

    assert result["confidence"]["level"] in {"low", "medium"}
    assert any("交叉验证" in item for item in result["confidence"]["limitations"])
    assert any("字符 Span" in item for item in result["confidence"]["limitations"])
