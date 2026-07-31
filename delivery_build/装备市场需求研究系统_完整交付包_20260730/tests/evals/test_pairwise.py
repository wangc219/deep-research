from pathlib import Path
import json

from evals.models import EvalQuery, EvalRunResult, read_jsonl
from evals.pairwise import build_blind_pairs, parse_judgment, render_judge_prompt


def _result(system: str, answer: str) -> EvalRunResult:
    return EvalRunResult("eval", "Q-0001", system, "completed", answer=answer)


def test_build_blind_pairs_separates_public_and_admin_identity(tmp_path: Path) -> None:
    query = EvalQuery("Q-0001", "研究任务", "台海", "电磁", "easy", "pilot")
    summary = build_blind_pairs(
        [query],
        [_result("full_method", "full_method answer"), _result("generic_deep_research", "generic_deep_research answer")],
        tmp_path,
        left_system="full_method",
        right_system="generic_deep_research",
    )
    assert summary == {"pair_count": 2, "query_count": 1}
    public = read_jsonl(tmp_path / "pairs.public.jsonl")
    admin = read_jsonl(tmp_path / "pairs.admin.jsonl")
    assert "full_method" not in json.dumps(public)
    assert "generic_deep_research" not in json.dumps(public)
    assert {row["system_a"] for row in admin} == {"full_method", "generic_deep_research"}
    assert {row["reversed"] for row in admin} == {False, True}


def test_build_blind_pairs_includes_bounded_data_center_evidence(tmp_path: Path) -> None:
    query = EvalQuery("Q-0001", "研究任务", "台海", "电磁", "easy", "pilot")
    full = _result("full_method", "正文只保留少量关键引用")
    full.evidence_context = [
        {
            "source_title": "公开机构报告",
            "source_url": "https://example.org/evidence",
            "source_tier": "A",
            "quality_assessment": "direct",
            "claim": "支持核心能力判断",
        }
    ]
    build_blind_pairs(
        [query],
        [full, _result("generic_agent", "通用回答")],
        tmp_path,
        left_system="full_method",
        right_system="generic_agent",
        include_reverse=False,
    )
    pair = read_jsonl(tmp_path / "pairs.public.jsonl")[0]
    assert "URL：https://example.org/evidence" in pair["evidence_a"]
    assert "支持核心能力判断" in pair["evidence_a"]
    prompt = render_judge_prompt(
        pair,
        "A={{ANSWER_A}}\nEA={{EVIDENCE_A}}\nB={{ANSWER_B}}\nEB={{EVIDENCE_B}}\n{{PAIR_ID}}",
    )
    assert "EA=- URL：https://example.org/evidence；摘要：支持核心能力判断" in prompt


def test_evidence_context_does_not_turn_citation_urls_into_fake_summaries(
    tmp_path: Path,
) -> None:
    query = EvalQuery("Q-0001", "研究任务", "台海", "电磁", "easy", "pilot")
    baseline = _result("generic_agent", "正文已有显式引用")
    baseline.citations = ["https://example.org/source-a"]
    baseline.sources = ["https://example.org/source-b"]
    build_blind_pairs(
        [query],
        [_result("full_method", "完整方法"), baseline],
        tmp_path,
        left_system="full_method",
        right_system="generic_agent",
        include_reverse=False,
    )
    pair = read_jsonl(tmp_path / "pairs.public.jsonl")[0]
    assert pair["evidence_b"].startswith("未提供独立的证据元数据")


def test_parse_judgment_validates_v0_schema() -> None:
    payload = {
        "winner": "A",
        "confidence": 0.8,
        "dimensions": {
            "task_fulfillment": "A",
            "facts_and_citations": "A",
            "analysis_depth": "B",
            "equipment_demand_value": "A",
            "uncertainty": "tie",
        },
        "reason": "A has stronger evidence",
        "citation_issues": [],
        "hard_failures": [],
    }
    judgment = parse_judgment(json.dumps(payload), pair_id="P-1", judge_id="judge")
    assert judgment.winner == "A"
    assert judgment.confidence == 0.8


def test_parse_judgment_accepts_route_adaptive_v1_schema() -> None:
    payload = {
        "primary_route": "B",
        "secondary_routes": ["F"],
        "route_confidence": 0.9,
        "winner": "A",
        "confidence": 0.85,
        "preference_strength": "strong",
        "dimensions": {
            "route_task_fulfillment": "A",
            "evidence_and_factuality": "A",
            "causal_and_mechanism_depth": "A",
            "military_operational_value": "A",
            "capability_mapping_and_demand_quality": "A",
            "novelty_and_foresight": "B",
            "system_and_cross_scenario_robustness": "A",
            "uncertainty_and_validation": "tie",
        },
        "route_deliverable_check": {
            "answer_a": {"coverage": "complete", "missing_items": []},
            "answer_b": {"coverage": "partial", "missing_items": ["需求卡片"]},
        },
        "reason": "A 的能力映射和证据链更完整。",
        "citation_issues": [],
        "hard_failures": [],
        "adjudication_required": False,
        "adjudication_reasons": [],
    }
    judgment = parse_judgment(json.dumps(payload), pair_id="P-v1", judge_id="judge")
    assert judgment.primary_route == "B"
    assert judgment.secondary_routes == ["F"]
    assert judgment.route_deliverable_check["answer_b"]["coverage"] == "partial"


def test_parse_judgment_keeps_legacy_communication_dimension_readable() -> None:
    payload = {
        "winner": "tie",
        "confidence": 0.7,
        "dimensions": {
            "task_fulfillment": "tie",
            "facts_and_citations": "tie",
            "analysis_depth": "tie",
            "equipment_demand_value": "tie",
            "uncertainty": "tie",
            "communication_efficiency": "A",
        },
        "reason": "历史记录",
        "citation_issues": [],
        "hard_failures": [],
    }
    judgment = parse_judgment(json.dumps(payload), pair_id="P-legacy", judge_id="judge")
    assert judgment.dimensions["communication_efficiency"] == "A"
