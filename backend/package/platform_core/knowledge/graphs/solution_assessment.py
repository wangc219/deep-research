"""为证据约束技术方案生成可复现的可信度分解与创新简报。"""

from __future__ import annotations

from typing import Any

SOLUTION_ASSESSMENT_VERSION = "defense-solution-assessment-v1"
INNOVATION_BRIEF_VERSION = "defense-innovation-brief-v1"

_CONFIDENCE_WEIGHTS = {
    "path_quality": 0.35,
    "source_diversity": 0.20,
    "citation_coverage": 0.25,
    "span_completeness": 0.20,
}


def assess_grounded_solution(
    *,
    query: str,
    solution: dict[str, Any],
    entities: list[dict[str, Any]],
    paths: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    graph_revision: str | None,
) -> dict[str, Any]:
    """以确定性规则评估证据支撑度；分数不代表事实真实性概率。"""
    components = {
        "path_quality": _path_quality(paths),
        "source_diversity": _source_diversity(evidence),
        "citation_coverage": _citation_coverage(solution),
        "span_completeness": _span_completeness(evidence),
    }
    score = round(
        sum(components[name] * weight for name, weight in _CONFIDENCE_WEIGHTS.items()),
        4,
    )
    level = "high" if score >= 0.80 else "medium" if score >= 0.60 else "low"
    limitations = _limitations(components, paths, evidence)
    confidence = {
        "score": score,
        "level": level,
        "algorithm_version": SOLUTION_ASSESSMENT_VERSION,
        "components": components,
        "weights": dict(_CONFIDENCE_WEIGHTS),
        "limitations": limitations,
        "interpretation": "证据支撑完整度评分，不是方案真实性或成功率；结果始终保持 Hypothesis。",
    }
    return {
        "confidence": confidence,
        "innovation_brief": _build_innovation_brief(
            query=query,
            solution=solution,
            entities=entities,
            paths=paths,
            evidence=evidence,
            graph_revision=graph_revision,
            confidence=confidence,
        ),
    }


def _path_quality(paths: list[dict[str, Any]]) -> float:
    if not paths:
        return 0.0
    scores = []
    for path in paths:
        has_relations = bool(path.get("relations"))
        has_evidence = bool((path.get("evidence") or {}).get("chunk_ids"))
        has_no_gaps = not bool(path.get("evidence_gaps"))
        score = 0.20 * has_relations + 0.40 * has_evidence + 0.40 * has_no_gaps
        scores.append(score)
    return round(sum(scores) / len(scores), 4)


def _source_diversity(evidence: list[dict[str, Any]]) -> float:
    source_count = len({str(item.get("file_id")) for item in evidence if item.get("file_id")})
    return round(min(source_count / 3, 1.0), 4)


def _citation_coverage(solution: dict[str, Any]) -> float:
    required = {"mechanism_hypothesis"}
    required.update(f"feasibility_basis[{index}]" for index, _ in enumerate(solution.get("feasibility_basis") or []))
    required.update(f"expected_effects[{index}]" for index, _ in enumerate(solution.get("expected_effects") or []))
    if not required:
        return 0.0
    cited = {
        str(citation.get("claim_path")) for citation in solution.get("citations") or [] if citation.get("evidence_ids")
    }
    return round(len(required & cited) / len(required), 4)


def _span_completeness(evidence: list[dict[str, Any]]) -> float:
    if not evidence:
        return 0.0
    scores = []
    for item in evidence:
        start = item.get("start_char")
        end = item.get("end_char")
        valid_span = isinstance(start, int) and isinstance(end, int) and 0 <= start < end
        score = (
            0.40 * bool(item.get("chunk_id"))
            + 0.20 * bool(item.get("file_id"))
            + 0.20 * bool(str(item.get("text") or "").strip())
            + 0.20 * valid_span
        )
        scores.append(score)
    return round(sum(scores) / len(scores), 4)


def _limitations(
    components: dict[str, float],
    paths: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> list[str]:
    limitations = []
    if len({item.get("file_id") for item in evidence if item.get("file_id")}) < 2:
        limitations.append("独立来源少于 2 个，尚不能形成交叉验证。")
    if components["span_completeness"] < 1:
        limitations.append("部分证据缺少完整字符 Span，需回到原文人工核验。")
    if any(path.get("evidence_gaps") for path in paths):
        limitations.append("至少一条图路径存在证据缺口。")
    if len(paths) < 2:
        limitations.append("当前仅有一条受信路径，替代机理尚未充分比较。")
    if components["citation_coverage"] < 1:
        limitations.append("生成声明未被证据引用完整覆盖。")
    return limitations


def _build_innovation_brief(
    *,
    query: str,
    solution: dict[str, Any],
    entities: list[dict[str, Any]],
    paths: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
    graph_revision: str | None,
    confidence: dict[str, Any],
) -> dict[str, Any]:
    cited_evidence_ids = list(
        dict.fromkeys(
            str(evidence_id)
            for citation in solution.get("citations") or []
            for evidence_id in citation.get("evidence_ids") or []
        )
    )
    return {
        "brief_version": INNOVATION_BRIEF_VERSION,
        "title": f"{query}：证据约束创新假设",
        "query": query,
        "mechanism_hypothesis": solution.get("mechanism_hypothesis"),
        "feasibility_basis": list(solution.get("feasibility_basis") or []),
        "expected_effects": list(solution.get("expected_effects") or []),
        "uncertainties": list(solution.get("uncertainties") or []),
        "entities": [
            {
                "entity_id": item.get("entity_id"),
                "name": item.get("name"),
                "type": item.get("type"),
            }
            for item in entities
        ],
        "path_ids": [str(path.get("path_id")) for path in paths if path.get("path_id")],
        "evidence_ids": cited_evidence_ids,
        "claim_level": "Hypothesis",
        "confidence": {"score": confidence["score"], "level": confidence["level"]},
        "graph_revision": graph_revision,
        "expert_review_required": True,
        "review_statement": "本简报仅供候选方案研判，进入事实图谱前必须完成专家复核与独立验证。",
    }
