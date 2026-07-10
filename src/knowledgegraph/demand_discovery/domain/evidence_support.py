"""Evidence support policy for semantic audit and autonomous report gates."""

from __future__ import annotations

from typing import Any, Literal

SupportLevel = Literal["direct", "partial", "adjacent", "weak", "irrelevant", "unassessed"]
SupportStatus = Literal["supported", "supported_with_reasoning", "unsupported", "unassessed"]

SUPPORT_LEVELS = {"direct", "partial", "adjacent", "weak", "irrelevant", "unassessed"}
REPORT_STATUSES = {"review_ready", "needs_revision", "watchlist", "rejected"}
SUPPORT_TYPES = {
    "explicit_demand",
    "inferred_gap",
    "context_only",
    "counter_evidence",
    "irrelevant",
}
REVIEW_READY_RUBRIC_ITEM_IDS = {
    "evidence_supports_candidate",
    "core_conclusion_supported",
    "adjacent_evidence_limited",
    "unassessed_evidence_handled",
}
REQUIRED_REVIEW_READY_RUBRIC_ITEM_IDS = {
    "evidence_supports_candidate",
    "core_conclusion_supported",
}
LEGACY_SUPPORT_LEVELS = {
    "strong": "direct",
    "high": "direct",
    "medium": "partial",
    "moderate": "partial",
    "provisional": "partial",
    "background": "adjacent",
    "low": "weak",
}


def normalize_support_level(value: Any) -> SupportLevel:
    normalized = str(value or "").strip().lower()
    normalized = LEGACY_SUPPORT_LEVELS.get(normalized, normalized)
    if normalized in SUPPORT_LEVELS:
        return normalized  # type: ignore[return-value]
    if any(token in normalized for token in ["irrelevant", "无关"]):
        return "irrelevant"
    if any(token in normalized for token in ["unassessed", "未审", "未评估"]):
        return "unassessed"
    if any(token in normalized for token in ["weak", "low", "偏弱"]):
        return "weak"
    if any(token in normalized for token in ["adjacent", "context_only", "相邻"]):
        return "adjacent"
    if any(token in normalized for token in ["strong", "direct", "high", "强"]):
        return "direct"
    if any(token in normalized for token in ["partial", "medium", "moderate", "provisional", "中等"]):
        return "partial"
    return "unassessed"


def evidence_reviews_from_scorecard(scorecard: dict[str, Any]) -> dict[str, dict[str, Any]]:
    support = scorecard.get("evidence_support", {})
    if not isinstance(support, dict):
        return {}
    reviews = support.get("evidence_reviews", {})
    if not isinstance(reviews, dict):
        return {}
    return {
        str(evidence_id): dict(review)
        for evidence_id, review in reviews.items()
        if isinstance(review, dict)
    }


def recommended_report_status_from_scorecard(scorecard: dict[str, Any]) -> str:
    support = scorecard.get("evidence_support", {})
    if not isinstance(support, dict):
        return ""
    status = str(support.get("recommended_report_status", "")).strip().lower()
    aliases = {
        "ready": "review_ready",
        "review-ready": "review_ready",
        "needs-revision": "needs_revision",
        "need_revision": "needs_revision",
        "revise": "needs_revision",
        "watch": "watchlist",
        "watch_list": "watchlist",
    }
    status = aliases.get(status, status)
    return status if status in REPORT_STATUSES else ""


def recheck_conditions_from_scorecard(scorecard: dict[str, Any]) -> list[str]:
    support = scorecard.get("evidence_support", {})
    if not isinstance(support, dict):
        return []
    values = support.get("recheck_conditions", [])
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    return [str(item).strip() for item in values if str(item).strip()]


def core_evidence_review_levels(
    scorecard: dict[str, Any],
    *,
    evidence_ids: list[str],
) -> dict[str, SupportLevel]:
    reviews = evidence_reviews_from_scorecard(scorecard)
    levels: dict[str, SupportLevel] = {}
    for evidence_id in evidence_ids:
        review = reviews.get(evidence_id)
        if not isinstance(review, dict) or not bool(review.get("used_for_core")):
            continue
        levels[evidence_id] = normalize_support_level(review.get("support_level"))
    return levels


def validate_evidence_support_scorecard(
    scorecard: dict[str, Any],
    *,
    evidence_ids: list[str],
) -> list[str]:
    errors: list[str] = []
    support = scorecard.get("evidence_support")
    if not isinstance(support, dict):
        return ["missing evidence_support scorecard"]
    verdict = str(support.get("verdict", "")).strip().lower()
    if verdict not in {"pass", "doubt", "fail"}:
        errors.append("evidence_support verdict must be pass, doubt, or fail")
    if not str(support.get("reason", "")).strip():
        errors.append("evidence_support reason is required")
    reviews = evidence_reviews_from_scorecard(scorecard)
    for evidence_id in evidence_ids:
        review = reviews.get(evidence_id)
        if review is None:
            errors.append(f"missing evidence review for {evidence_id}")
            continue
        level = normalize_support_level(review.get("support_level"))
        if level == "unassessed":
            errors.append(f"unassessed evidence review for {evidence_id}")
        support_type = str(review.get("support_type", "")).strip()
        if support_type not in SUPPORT_TYPES:
            errors.append(f"invalid support_type for {evidence_id}: {support_type}")
        if not str(review.get("reason", "")).strip():
            errors.append(f"missing evidence review reason for {evidence_id}")
    return errors


def core_conclusion_support_status(
    reviews: list[dict[str, Any]],
    *,
    evidence_map: dict[str, dict[str, Any]] | None = None,
) -> SupportStatus:
    core_reviews = [review for review in reviews if bool(review.get("used_for_core"))]
    if not core_reviews:
        return "unsupported"
    levels = [normalize_support_level(review.get("support_level")) for review in core_reviews]
    if "direct" in levels:
        return "supported"
    partial_reviews = [
        review
        for review in core_reviews
        if normalize_support_level(review.get("support_level")) == "partial"
    ]
    if len(partial_reviews) >= 2 and _has_two_independent_partial_sources(
        partial_reviews,
        evidence_map=evidence_map or {},
    ):
        return "supported_with_reasoning"
    if "unassessed" in levels:
        return "unassessed"
    return "unsupported"


def watchlist_scorecard_errors(
    scorecard: dict[str, Any],
    *,
    evidence_ids: list[str],
) -> list[str]:
    errors = validate_evidence_support_scorecard(scorecard, evidence_ids=evidence_ids)
    recommended_status = recommended_report_status_from_scorecard(scorecard)
    if recommended_status != "watchlist":
        errors.append(
            "evidence_support recommended_report_status must be watchlist"
        )
    if not recheck_conditions_from_scorecard(scorecard):
        errors.append("watchlist requires non-empty recheck_conditions")
    support = scorecard.get("evidence_support", {})
    if _verdict(support) == "fail":
        errors.append("watchlist cannot use failing evidence_support verdict")
    for evidence_id, level in core_evidence_review_levels(
        scorecard,
        evidence_ids=evidence_ids,
    ).items():
        if level in {"irrelevant", "unassessed"}:
            errors.append(
                f"{level} evidence cannot be used for watchlist core support: {evidence_id}"
            )
    return errors


def review_ready_scorecard_errors(
    scorecard: dict[str, Any],
    *,
    evidence_ids: list[str],
    evidence_map: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    errors = validate_evidence_support_scorecard(scorecard, evidence_ids=evidence_ids)
    if errors:
        return errors
    support = scorecard.get("evidence_support", {})
    support_verdict = _verdict(support)
    if support_verdict != "pass":
        errors.append(
            f"evidence_support verdict must be pass for review_ready: {support_verdict}"
        )
    for item_id in sorted(REVIEW_READY_RUBRIC_ITEM_IDS):
        row = scorecard.get(item_id)
        if not isinstance(row, dict):
            if item_id in REQUIRED_REVIEW_READY_RUBRIC_ITEM_IDS:
                errors.append(f"missing required review_ready rubric item: {item_id}")
            continue
        verdict = _verdict(row)
        if verdict != "pass":
            errors.append(f"{item_id} verdict must be pass for review_ready: {verdict}")
    reviews = evidence_reviews_from_scorecard(scorecard)
    support_status = core_conclusion_support_status(
        [
            {**reviews[evidence_id], "evidence_id": evidence_id}
            for evidence_id in evidence_ids
            if evidence_id in reviews
        ],
        evidence_map=evidence_map or {},
    )
    if support_status in {"unsupported", "unassessed"}:
        errors.append(f"core conclusion support is {support_status}")
    return errors


def required_rework_for_support_errors(errors: list[str]) -> list[str]:
    return [f"补充或修正 audit evidence_support：{item}" for item in errors]


def validate_semantic_audit_scorecard(
    *,
    scorecard: dict[str, Any],
    conclusion: str,
    evidence_ids: list[str],
) -> tuple[str, list[str]]:
    errors = validate_evidence_support_scorecard(scorecard, evidence_ids=evidence_ids)
    rework = required_rework_for_support_errors(errors)
    if errors and conclusion.strip().lower() in {"approved", "pass", "通过"}:
        return conclusion, rework
    return conclusion, rework


def _verdict(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    return str(row.get("verdict", "")).strip().lower()


def _has_two_independent_partial_sources(
    reviews: list[dict[str, Any]],
    *,
    evidence_map: dict[str, dict[str, Any]],
) -> bool:
    source_keys: set[str] = set()
    for review in reviews:
        evidence_id = str(review.get("evidence_id", "")).strip()
        evidence = evidence_map.get(evidence_id, {})
        source_id = str(evidence.get("source_id", "")).strip()
        body_ref = str(evidence.get("body_artifact_ref", "")).strip()
        if not body_ref:
            body_ref = str(evidence.get("source_location", "")).strip().split("#", 1)[0]
        if source_id:
            source_keys.add(f"source:{source_id}")
        elif body_ref:
            source_keys.add(f"body:{body_ref}")
    return len(source_keys) >= 2
