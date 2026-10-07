"""把领域运行中的 S5 组合评分投影到正式能力画像。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


S5_SCORE_WEIGHTS = {
    "innovation": 0.30,
    "demand": 0.30,
    "feasibility": 0.20,
    "effectiveness": 0.10,
    "development": 0.10,
}

_IDENTITY_FIELDS = (
    "hypothesis_id",
    "card_binding_id",
    "capability_id",
    "name",
    "equipment_name",
    "primary_equipment_identity",
)


def _identity_aliases(value: Mapping[str, Any]) -> set[str]:
    return {
        normalized
        for field in _IDENTITY_FIELDS
        if (normalized := " ".join(str(value.get(field) or "").split()).casefold())
    }


def _normalized_scores(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    scores: dict[str, float] = {}
    for dimension in S5_SCORE_WEIGHTS:
        try:
            score = float(value.get(dimension))
        except (TypeError, ValueError):
            return {}
        if not 0.0 <= score <= 1.0:
            return {}
        scores[dimension] = round(score, 4)
    return scores


def s5_scorecards_from_summary(summary: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """读取 round_summary 中由 S5 冻结、供 S6 成卡的逐候选评分。"""

    if not isinstance(summary, Mapping):
        return []
    winning = summary.get("winning_mechanism")
    stages = winning.get("stages", []) if isinstance(winning, Mapping) else []
    rows: list[dict[str, Any]] = []
    for stage in stages if isinstance(stages, Sequence) else []:
        if not isinstance(stage, Mapping):
            continue
        outputs = stage.get("outputs")
        directions = (
            outputs.get("core_agent_concept_directions", [])
            if isinstance(outputs, Mapping)
            else []
        )
        for direction in directions if isinstance(directions, Sequence) else []:
            if not isinstance(direction, Mapping):
                continue
            scores = _normalized_scores(direction.get("s5_dimension_scores"))
            aliases = _identity_aliases(direction)
            if not scores or not aliases:
                continue
            weighted = round(
                sum(scores[key] * weight for key, weight in S5_SCORE_WEIGHTS.items()),
                4,
            )
            rows.append(
                {
                    "aliases": aliases,
                    "scores": scores,
                    "weighted_score": weighted,
                    "score_basis": str(direction.get("innovation_basis") or "").strip()[:1200],
                    "naming_anchor": str(direction.get("naming_anchor") or "").strip()[:240],
                }
            )
    return rows


def enrich_capabilities_with_s5_scores(
    capabilities: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """按不可变身份匹配 S5 评分；无匹配时保持卡片原样。"""

    scorecards = s5_scorecards_from_summary(summary)
    enriched: list[dict[str, Any]] = []
    for capability in capabilities:
        card = dict(capability)
        aliases = _identity_aliases(card)
        matches = [scorecard for scorecard in scorecards if aliases & scorecard["aliases"]]
        if len(matches) == 1:
            match = matches[0]
            card["s5_dimension_scores"] = dict(match["scores"])
            card["s5_weighted_score"] = match["weighted_score"]
            card["s5_score_schema"] = "s5_five_dimension_v1"
            card["s5_score_weights"] = dict(S5_SCORE_WEIGHTS)
            if match["score_basis"]:
                card["s5_score_basis"] = match["score_basis"]
            if match["naming_anchor"]:
                card["s5_naming_anchor"] = match["naming_anchor"]
        enriched.append(card)
    return enriched
