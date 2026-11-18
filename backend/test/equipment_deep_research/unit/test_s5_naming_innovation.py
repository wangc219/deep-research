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
        "identity_contract_version": "single_weapon_v1",
        "single_weapon_identity_closes": True,
        "physical_main_body_specific": True,
        "novel_principle_explicit": True,
        "effect_carrier_closes": True,
        "independent_deployment_and_testable": True,
        "system_family_or_solution_bundle": False,
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
    assert weighted == 0.7655


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
    assert weighted == 0.77


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
    assert weighted == 0.545


def test_s5_name_quality_does_not_change_mechanism_score_or_create_boolean_hard_gate() -> None:
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
    assert _s5_retain_passes_concrete_weapon_contract(
        _explicit_contract(
            ordinary_upgrade_or_function_packaging=True,
            naming_new_quality=1.0,
            naming_semantic_alignment=1.0,
        )
    )


def test_s5_name_diagnostics_never_become_a_controller_hard_gate() -> None:
    assert _s5_retain_passes_concrete_weapon_contract(
        _explicit_contract(
            naming_new_quality=0.20,
            naming_semantic_alignment=0.90,
        )
    )
    assert _s5_retain_passes_concrete_weapon_contract(
        _explicit_contract(
            naming_new_quality=1.0,
            naming_semantic_alignment=0.20,
        )
    )


def test_s5_identity_diagnostics_never_become_a_controller_hard_gate() -> None:
    assert _s5_retain_passes_concrete_weapon_contract(
        _explicit_contract(system_family_or_solution_bundle=True),
        require_single_weapon_contract=True,
    )
    assert _s5_retain_passes_concrete_weapon_contract(
        _explicit_contract(),
        require_single_weapon_contract=True,
        require_converged_candidate=True,
    )
    assert _s5_retain_passes_concrete_weapon_contract(
        _explicit_contract(independent_deployment_and_testable=False),
        require_single_weapon_contract=True,
    )
    assert _s5_retain_passes_concrete_weapon_contract(
        {
            "direct_equipment": True,
            "weapon_object_specific": True,
            "known_science_consistent": True,
        },
        require_single_weapon_contract=True,
    )


def test_s5_strict_identity_contract_accepts_domain_open_concrete_weapon() -> None:
    assert _s5_retain_passes_concrete_weapon_contract(
        _explicit_contract(),
        require_single_weapon_contract=True,
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
