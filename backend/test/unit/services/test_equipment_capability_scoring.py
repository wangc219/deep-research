"""能力画像 S5 评分投影测试。"""

from platform_core.services.equipment_capability_scoring import (
    enrich_capabilities_with_s5_scores,
    s5_scorecards_from_summary,
)


def _summary() -> dict:
    return {
        "winning_mechanism": {
            "stages": [
                {},
                {
                    "outputs": {
                        "core_agent_concept_directions": [
                            {
                                "name": "裂棱散射眩扰弹",
                                "hypothesis_id": "hyp-1",
                                "card_binding_id": "card-1",
                                "s5_dimension_scores": {
                                    "innovation": 0.804,
                                    "demand": 0.82,
                                    "feasibility": 0.74,
                                    "effectiveness": 0.77,
                                    "development": 0.76,
                                },
                                "s5_weighted_score": 0.1,
                                "naming_anchor": "微棱散射与多谱感知眩扰",
                            }
                        ]
                    }
                },
            ]
        }
    }


def test_s5_scorecards_recompute_authoritative_weighted_score() -> None:
    scorecards = s5_scorecards_from_summary(_summary())

    assert len(scorecards) == 1
    assert scorecards[0]["weighted_score"] == 0.7882
    assert "hyp-1" in scorecards[0]["aliases"]


def test_capability_scores_match_identity_without_overwriting_unrelated_cards() -> None:
    cards = [
        {"hypothesis_id": "hyp-1", "name": "裂棱散射眩扰弹"},
        {"hypothesis_id": "hyp-2", "name": "其他装备"},
    ]

    enriched = enrich_capabilities_with_s5_scores(cards, _summary())

    assert enriched[0]["s5_dimension_scores"]["innovation"] == 0.804
    assert enriched[0]["s5_weighted_score"] == 0.7882
    assert enriched[0]["s5_score_schema"] == "s5_five_dimension_v1"
    assert "s5_dimension_scores" not in enriched[1]
