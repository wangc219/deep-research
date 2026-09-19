from __future__ import annotations

from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _s5_dimension_scores,
    _s5_naming_assessment,
    _s5_retain_passes_concrete_weapon_contract,
)


def _explicit_contract(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "direct_equipment": True,
        "weapon_object_specific": True,
        "support_dependency_only": False,
        "known_science_consistent": True,
        "weapon_body_mechanism_closes": True,
        "material_innovation_breakpoint_present": True,
        "ordinary_upgrade_or_function_packaging": False,
        "disruption_tier": "new_quality_breakthrough",
    }
    value.update(overrides)
    return value


def test_s5_effective_innovation_is_recomputed_from_mechanism_and_name() -> None:
    assessment = {
        "dimension_scores": {
            "innovation": 0.99,
            "demand": 0.80,
            "feasibility": 0.70,
            "effectiveness": 0.60,
            "development": 0.50,
        },
        "s5_innovation_mechanism_score": 0.90,
        "naming_new_quality": 0.80,
        "naming_semantic_alignment": 0.95,
    }

    naming = _s5_naming_assessment(assessment)
    scores, weighted = _s5_dimension_scores(assessment)

    assert naming["status"] == "assessed"
    assert naming["effective_innovation"] == 0.89
    assert scores["innovation"] == 0.89
    assert weighted == 0.757


def test_s5_legacy_result_without_naming_fields_keeps_old_innovation_score() -> None:
    assessment = {
        "dimension_scores": {
            "innovation": 0.90,
            "demand": 0.80,
            "feasibility": 0.70,
            "effectiveness": 0.60,
            "development": 0.50,
        }
    }

    naming = _s5_naming_assessment(assessment)
    scores, weighted = _s5_dimension_scores(assessment)

    assert naming["status"] == "unassessed"
    assert scores["innovation"] == 0.90
    assert weighted == 0.76


def test_s5_partial_naming_result_does_not_treat_effective_score_as_mechanism() -> None:
    assessment = {
        "dimension_scores": {
            "innovation": 0.40,
            "demand": 0.80,
            "feasibility": 0.70,
            "effectiveness": 0.60,
            "development": 0.50,
        },
        "naming_new_quality": 1.0,
        "naming_semantic_alignment": 1.0,
    }

    naming = _s5_naming_assessment(assessment)
    scores, weighted = _s5_dimension_scores(assessment)

    assert naming["status"] == "incomplete"
    assert naming["s5_innovation_mechanism_score"] is None
    assert scores["innovation"] == 0.40
    assert weighted == 0.61


def test_s5_name_quality_cannot_rescue_ordinary_mechanism() -> None:
    scores, _weighted = _s5_dimension_scores(
        {
            "dimension_scores": {
                "innovation": 0.40,
                "demand": 0.80,
                "feasibility": 0.70,
                "effectiveness": 0.60,
                "development": 0.50,
            },
            "s5_innovation_mechanism_score": 0.35,
            "naming_new_quality": 1.0,
            "naming_semantic_alignment": 1.0,
        }
    )

    assert scores["innovation"] == 0.5125
    assert not _s5_retain_passes_concrete_weapon_contract(
        _explicit_contract(
            ordinary_upgrade_or_function_packaging=True,
            naming_new_quality=1.0,
            naming_semantic_alignment=1.0,
        )
    )


def test_s5_plain_but_accurate_name_can_survive_and_misaligned_name_cannot() -> None:
    assert _s5_retain_passes_concrete_weapon_contract(
        _explicit_contract(
            naming_new_quality=0.20,
            naming_semantic_alignment=0.90,
        )
    )
    assert not _s5_retain_passes_concrete_weapon_contract(
        _explicit_contract(
            naming_new_quality=1.0,
            naming_semantic_alignment=0.20,
        )
    )


def test_s5_extended_scores_can_be_read_from_explicit_basis_text() -> None:
    assessment = {
        "innovation_basis": (
            "创新性=0.88；需求性=0.80；科学可行性=0.70；效能性=0.60；发展性=0.50；"
            "机理/装备创新性=0.90；命名新质度=0.80；命名与本体一致性=0.95；"
            "命名锚点=超材料；命名评语=名称承载真实材料机理"
        )
    }

    naming = _s5_naming_assessment(assessment)
    scores, _weighted = _s5_dimension_scores(assessment)

    assert naming["status"] == "assessed"
    assert scores["innovation"] == 0.89
