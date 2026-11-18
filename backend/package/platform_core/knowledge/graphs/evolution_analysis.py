"""可复现的技术前沿度、成熟度拐点与爆发趋势计算。"""

from __future__ import annotations

from datetime import UTC, date, datetime
from math import sqrt
from typing import Any

EVOLUTION_ALGORITHM_VERSION = "defense-technology-evolution-v1"
FRONTIER_WEIGHTS = {
    "recency": 0.25,
    "publication_patent_growth": 0.20,
    "citation_family_growth": 0.20,
    "cross_domain_bridge": 0.15,
    "novelty": 0.10,
    "evidence_quality": 0.10,
}


def analyze_technology_evolution(
    observations: list[dict[str, Any]],
    *,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """从版本化时序观测计算前沿度、成熟度和爆发等级。"""
    now = (as_of or datetime.now(UTC)).astimezone(UTC)
    series = _normalize_observations(observations)
    components = _component_scores(series, now)
    frontier_score = round(sum(components[key] * weight for key, weight in FRONTIER_WEIGHTS.items()), 4)
    maturity_stage, maturity_inflection = _maturity(series)
    burst_level, burst_score = _burst(series)
    return {
        "algorithm_version": EVOLUTION_ALGORITHM_VERSION,
        "as_of": now.isoformat(),
        "frontier_score": frontier_score,
        "component_scores": components,
        "weights": FRONTIER_WEIGHTS,
        "maturity_stage": maturity_stage,
        "maturity_inflection": maturity_inflection,
        "burst_level": burst_level,
        "burst_score": burst_score,
        "time_series": series,
    }


def _normalize_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for raw in observations:
        period = _period_key(raw.get("period"))
        item = merged.setdefault(
            period,
            {
                "period": period,
                "document_count": 0,
                "citation_count": 0,
                "patent_family_count": 0,
                "validation_count": 0,
                "domains": [],
                "evidence_quality": [],
            },
        )
        for field in ("document_count", "citation_count", "patent_family_count", "validation_count"):
            item[field] += max(int(raw.get(field) or 0), 0)
        item["domains"] = list(
            dict.fromkeys([*item["domains"], *[str(value) for value in raw.get("domains") or [] if str(value)]])
        )
        quality = raw.get("evidence_quality")
        if quality is not None:
            item["evidence_quality"].append(_bounded(float(quality)))

    result = []
    for item in merged.values():
        qualities = item.pop("evidence_quality")
        item["evidence_quality"] = round(sum(qualities) / len(qualities), 4) if qualities else 0.0
        result.append(item)
    return sorted(result, key=lambda item: item["period"])


def _component_scores(series: list[dict[str, Any]], now: datetime) -> dict[str, float]:
    if not series:
        return {key: 0.0 for key in FRONTIER_WEIGHTS}
    last_period = datetime.fromisoformat(f"{series[-1]['period']}-01T00:00:00+00:00")
    age_months = max((now.year - last_period.year) * 12 + now.month - last_period.month, 0)
    recency = _bounded(1.0 - age_months / 24.0)
    previous, recent = _split_series(series)
    publication_patent_growth = _growth_score(
        sum(item["document_count"] + item["patent_family_count"] for item in previous),
        sum(item["document_count"] + item["patent_family_count"] for item in recent),
    )
    citation_family_growth = _growth_score(
        sum(item["citation_count"] + item["patent_family_count"] for item in previous),
        sum(item["citation_count"] + item["patent_family_count"] for item in recent),
    )
    domains = {domain for item in series for domain in item["domains"]}
    cross_domain_bridge = _bounded((len(domains) - 1) / 4.0)
    first_period = datetime.fromisoformat(f"{series[0]['period']}-01T00:00:00+00:00")
    lifetime_months = max((now.year - first_period.year) * 12 + now.month - first_period.month, 0)
    novelty = _bounded(1.0 - lifetime_months / 60.0)
    total_evidence = sum(max(item["document_count"], 1) for item in series)
    evidence_quality = sum(item["evidence_quality"] * max(item["document_count"], 1) for item in series)
    evidence_quality = _bounded(evidence_quality / total_evidence)
    return {
        "recency": round(recency, 4),
        "publication_patent_growth": round(publication_patent_growth, 4),
        "citation_family_growth": round(citation_family_growth, 4),
        "cross_domain_bridge": round(cross_domain_bridge, 4),
        "novelty": round(novelty, 4),
        "evidence_quality": round(evidence_quality, 4),
    }


def _maturity(series: list[dict[str, Any]]) -> tuple[str, dict[str, Any] | None]:
    documents = sum(item["document_count"] for item in series)
    validations = sum(item["validation_count"] for item in series)
    patents = sum(item["patent_family_count"] for item in series)
    if documents >= 30 and validations >= 5 and patents >= 3:
        stage = "system_integration"
    elif documents >= 15 and validations >= 2:
        stage = "engineering_validation"
    elif documents >= 5 or validations >= 1:
        stage = "experimental_validation"
    else:
        stage = "emerging_principle"

    if len(series) < 2:
        return stage, None
    previous = series[-2]
    current = series[-1]
    validation_delta = current["validation_count"] - previous["validation_count"]
    patent_delta = current["patent_family_count"] - previous["patent_family_count"]
    document_growth = _raw_growth(previous["document_count"], current["document_count"])
    if validation_delta <= 0 and patent_delta <= 0 and document_growth < 0.5:
        return stage, None
    return stage, {
        "period": current["period"],
        "validation_delta": validation_delta,
        "patent_family_delta": patent_delta,
        "document_growth": round(document_growth, 4),
        "reason": "验证、专利族或文献增速出现阶段性跃升",
    }


def _burst(series: list[dict[str, Any]]) -> tuple[str, float]:
    values = [item["document_count"] + item["patent_family_count"] for item in series]
    if len(values) < 3:
        return "insufficient_data", 0.0
    baseline = values[:-1]
    mean = sum(baseline) / len(baseline)
    variance = sum((value - mean) ** 2 for value in baseline) / len(baseline)
    deviation = sqrt(variance)
    score = (values[-1] - mean) / max(deviation, 1.0)
    if score >= 3.0:
        level = "strong"
    elif score >= 2.0:
        level = "moderate"
    elif score >= 1.0:
        level = "watch"
    else:
        level = "normal"
    return level, round(score, 4)


def _split_series(series: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    midpoint = max(len(series) // 2, 1)
    previous = series[:midpoint]
    recent = series[midpoint:] or series[-1:]
    return previous, recent


def _growth_score(previous: int, recent: int) -> float:
    growth = _raw_growth(previous, recent)
    return _bounded((growth + 1.0) / 3.0)


def _raw_growth(previous: int, recent: int) -> float:
    if previous <= 0:
        return 1.0 if recent > 0 else 0.0
    return (recent - previous) / previous


def _period_key(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).strftime("%Y-%m")
    if isinstance(value, date):
        return value.strftime("%Y-%m")
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        if len(text) == 7 and text[4] == "-" and text[:4].isdigit() and text[5:].isdigit():
            return text
        raise ValueError(f"无效趋势 period: {value}") from exc
    return parsed.strftime("%Y-%m")


def _bounded(value: float) -> float:
    return max(0.0, min(float(value), 1.0))
