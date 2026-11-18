from __future__ import annotations

from datetime import UTC, datetime

import pytest

from platform_core.knowledge.graphs.evolution_analysis import (
    EVOLUTION_ALGORITHM_VERSION,
    FRONTIER_WEIGHTS,
    analyze_technology_evolution,
)


def test_frontier_score_uses_versioned_required_weights_and_detects_burst():
    result = analyze_technology_evolution(
        [
            {
                "period": "2026-01",
                "document_count": 2,
                "citation_count": 1,
                "patent_family_count": 0,
                "validation_count": 0,
                "domains": ["雷达"],
                "evidence_quality": 0.8,
            },
            {
                "period": "2026-02",
                "document_count": 3,
                "citation_count": 2,
                "patent_family_count": 1,
                "validation_count": 1,
                "domains": ["雷达", "通信"],
                "evidence_quality": 0.9,
            },
            {
                "period": "2026-03",
                "document_count": 14,
                "citation_count": 9,
                "patent_family_count": 4,
                "validation_count": 3,
                "domains": ["雷达", "通信", "自主系统"],
                "evidence_quality": 0.95,
            },
        ],
        as_of=datetime(2026, 3, 31, tzinfo=UTC),
    )

    assert result["algorithm_version"] == EVOLUTION_ALGORITHM_VERSION
    assert result["weights"] == FRONTIER_WEIGHTS
    assert sum(result["weights"].values()) == pytest.approx(1.0)
    assert 0.0 <= result["frontier_score"] <= 1.0
    assert result["burst_level"] in {"moderate", "strong"}
    assert result["maturity_stage"] == "engineering_validation"
    assert result["maturity_inflection"]["period"] == "2026-03"


def test_empty_series_is_explicitly_insufficient_and_never_invents_signal():
    result = analyze_technology_evolution([], as_of=datetime(2026, 3, 31, tzinfo=UTC))

    assert result["frontier_score"] == 0.0
    assert result["maturity_stage"] == "emerging_principle"
    assert result["maturity_inflection"] is None
    assert result["burst_level"] == "insufficient_data"
    assert result["time_series"] == []


def test_merges_duplicate_months_and_rejects_invalid_period():
    result = analyze_technology_evolution(
        [
            {"period": "2026-01-05", "document_count": 1, "domains": ["雷达"]},
            {"period": "2026-01-20", "document_count": 2, "domains": ["通信"]},
        ],
        as_of=datetime(2026, 2, 1, tzinfo=UTC),
    )

    assert result["time_series"][0]["document_count"] == 3
    assert result["time_series"][0]["domains"] == ["雷达", "通信"]

    with pytest.raises(ValueError, match="period"):
        analyze_technology_evolution([{"period": "not-a-date"}])
