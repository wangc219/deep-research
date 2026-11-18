from __future__ import annotations

from platform_core.knowledge.graphs.lightrag_candidate_review import (
    build_entity_review_prompt,
    clear_non_ontology_entity_reason,
    entity_type_surface_hints,
    filter_clear_non_ontology_candidates,
    resolve_deterministic_entity_type_conflicts,
    review_entities,
    validate_entity_review_decisions,
    validate_entity_review_proposals,
)
from platform_core.knowledge.graphs.pipeline_config import normalize_pipeline_options


def _entity(*, reviewed: bool = False):
    return {
        "id": "weapon",
        "text": "高功率微波武器",
        "label": "ScientificPrinciple",
        "start": 0,
        "end": 7,
        "confidence": 0.78,
        "review_status": "accepted" if reviewed else "pending",
        "model_sources": ["human-reviewed" if reviewed else "lightrag"],
    }


def _raw_proposal(confidence: float = 0.98):
    return {
        "entity_id": "weapon",
        "text": "高功率微波武器",
        "start": 0,
        "end": 7,
        "current_label": "ScientificPrinciple",
        "action": "relabel",
        "suggested_label": "ProductSystem",
        "confidence": confidence,
        "reason": "原文把它作为武器系统而非作用机理",
    }


def test_clear_surface_gate_rejects_pure_ocr_symbols_without_harming_technical_names():
    assert clear_non_ontology_entity_reason("%’(") == "punctuation_or_ocr_fragment"
    assert clear_non_ontology_entity_reason("=>?") == "punctuation_or_ocr_fragment"
    assert clear_non_ontology_entity_reason("C++") is None
    assert clear_non_ontology_entity_reason("5G") is None
    assert clear_non_ontology_entity_reason("λ/4 天线") is None
    assert clear_non_ontology_entity_reason("@AB") == "ocr_marker_fragment"
    assert clear_non_ontology_entity_reason("8—0# 个月") == "ocr_corrupted_numeric_fragment"
    assert clear_non_ontology_entity_reason("12个月") is None
    assert clear_non_ontology_entity_reason("坠毁失事") == "generic_non_entity"


def test_clear_surface_gate_uses_layout_view_for_organizations_and_keeps_material_terms():
    assert clear_non_ontology_entity_reason("空军研究 实验室") == "organization_name"
    assert clear_non_ontology_entity_reason("美国海\r\n军") == "organization_name"
    assert clear_non_ontology_entity_reason("美国五角大楼") == "organization_name"
    assert clear_non_ontology_entity_reason("固") == "single_cjk_fragment"
    assert clear_non_ontology_entity_reason("氢") is None
    assert clear_non_ontology_entity_reason("激 光器") is None
    assert entity_type_surface_hints("激 光器") == [{"suggested_label": "Component", "reason": "器件或组件称谓"}]


def test_clear_surface_gate_rejects_real_pilot_headers_english_organizations_and_formula_fragments():
    assert clear_non_ontology_entity_reason("2007年5月第3期") == "publication_header"
    assert clear_non_ontology_entity_reason("第 22 卷\n16") == "publication_header"
    assert (
        clear_non_ontology_entity_reason("Southwest China Research Institute of Electronic Equipment")
        == "organization_name"
    )
    assert clear_non_ontology_entity_reason("pass") == "english_layout_stop_fragment"
    assert clear_non_ontology_entity_reason("P") == "single_formula_symbol"
    assert clear_non_ontology_entity_reason("λ") == "single_formula_symbol"
    assert clear_non_ontology_entity_reason("5G") is None
    assert clear_non_ontology_entity_reason("RC-ESPRIT") is None
    assert clear_non_ontology_entity_reason("partial observability.") == "ascii_trailing_punctuation"
    assert clear_non_ontology_entity_reason("成功的应用") == "generic_non_entity"


def test_english_surface_hints_collapse_lightrag_multi_type_terms_without_free_naming():
    assert entity_type_surface_hints("signal extract technique") == [
        {"suggested_label": "KeyTechnology", "reason": "英文技术称谓"}
    ]
    assert entity_type_surface_hints("matched filtering algorithm") == [
        {"suggested_label": "AlgorithmModel", "reason": "英文算法或模型称谓"}
    ]
    assert entity_type_surface_hints("array receiver") == [
        {"suggested_label": "Component", "reason": "英文器件或组件称谓"}
    ]
    assert entity_type_surface_hints("range resolution") == [
        {"suggested_label": "Metric", "reason": "英文可测量指标称谓"}
    ]


def test_clear_candidate_filter_drops_model_junk_and_dangling_relation_without_rewriting_span():
    text = "空军研究 实验室研制激 光器，固"
    organization = {
        "id": "org",
        "text": "空军研究 实验室",
        "label": "ProductSystem",
        "start": 0,
        "end": len("空军研究 实验室"),
        "model_sources": ["lightrag"],
    }
    component_start = text.index("激 光器")
    component = {
        "id": "component",
        "text": "激 光器",
        "label": "Component",
        "start": component_start,
        "end": component_start + len("激 光器"),
        "model_sources": ["lightrag"],
    }
    fragment_start = text.index("固")
    fragment = {
        "id": "fragment",
        "text": "固",
        "label": "Material",
        "start": fragment_start,
        "end": fragment_start + 1,
        "model_sources": ["lightrag_llm_initial_enhancement"],
    }
    filtered = filter_clear_non_ontology_candidates(
        {
            "entities": [organization, component, fragment],
            "relations": [
                {
                    "source": "org",
                    "target": "component",
                    "label": "HAS_COMPONENT",
                }
            ],
            "metadata": {},
        }
    )

    assert filtered["entities"] == [component]
    assert filtered["entities"][0]["text"] == text[component_start : component_start + len("激 光器")]
    assert filtered["entities"][0]["start"] == component_start
    assert filtered["relations"] == []
    report = filtered["metadata"]["deterministic_entity_quality_filter"]
    assert report["rejection_counts"] == {"organization_name": 1, "single_cjk_fragment": 1}
    assert report["dropped_entity_count"] == 2
    assert report["dropped_relation_count"] == 1


def test_clear_candidate_filter_preserves_human_reviewed_entity_and_relation():
    organization = {
        "id": "org",
        "text": "空军研究 实验室",
        "label": "ProductSystem",
        "start": 0,
        "end": len("空军研究 实验室"),
        "review_status": "accepted",
        "model_sources": ["human_domain_review"],
    }
    component = {
        "id": "component",
        "text": "激光器",
        "label": "Component",
        "start": 11,
        "end": 14,
    }
    filtered = filter_clear_non_ontology_candidates(
        {
            "entities": [organization, component],
            "relations": [
                {
                    "source": "org",
                    "target": "component",
                    "label": "HAS_COMPONENT",
                    "review_status": "accepted",
                }
            ],
            "metadata": {},
        }
    )

    assert [entity["id"] for entity in filtered["entities"]] == ["org", "component"]
    assert len(filtered["relations"]) == 1
    assert filtered["metadata"]["deterministic_entity_quality_filter"]["dropped_entity_count"] == 0


def test_clear_candidate_filter_drops_nested_ascii_word_fragment_but_keeps_word_boundary_concept():
    entities = [
        {
            "id": "multi",
            "text": "multi-agent reinforcement learning",
            "label": "KeyTechnology",
            "start": 0,
            "end": 34,
        },
        {
            "id": "full",
            "text": "reinforcement learning",
            "label": "KeyTechnology",
            "start": 12,
            "end": 34,
        },
        {
            "id": "fragment",
            "text": "orcement learning",
            "label": "KeyTechnology",
            "start": 17,
            "end": 34,
        },
    ]

    filtered = filter_clear_non_ontology_candidates(
        {"entities": entities, "relations": [], "metadata": {}}
    )

    assert [entity["id"] for entity in filtered["entities"]] == ["multi", "full"]
    report = filtered["metadata"]["deterministic_entity_quality_filter"]
    assert report["rejection_counts"] == {"nested_ascii_word_fragment": 1}


def test_surface_type_hints_are_conservative_and_do_not_confuse_weapon_with_generic_component_suffix():
    assert entity_type_surface_hints("高功率微波武器") == [
        {"suggested_label": "ProductSystem", "reason": "完整装备或武器产品称谓"}
    ]
    assert entity_type_surface_hints("匹配滤波算法") == [
        {"suggested_label": "AlgorithmModel", "reason": "算法或模型称谓"}
    ]
    assert entity_type_surface_hints("雷达系统") == []
    assert entity_type_surface_hints("毁坏电子器件") == []


def test_surface_type_hints_cover_military_signal_metrics_and_method_acronyms():
    assert entity_type_surface_hints("多普勒频移") == [{"suggested_label": "Metric", "reason": "可测量指标称谓"}]
    assert entity_type_surface_hints("相位差变化率") == [{"suggested_label": "Metric", "reason": "可测量指标称谓"}]
    assert entity_type_surface_hints("CDMA") == [
        {"suggested_label": "AlgorithmModel", "reason": "通信多址或信号处理方法缩写"}
    ]


def test_deterministic_type_resolution_disambiguates_real_signal_processing_spans():
    candidates = []
    for sequence, (text, labels) in enumerate(
        (
            ("多普勒频移", ("Metric", "ScientificPrinciple")),
            ("CDMA", ("AlgorithmModel", "ScientificPrinciple")),
            ("相位差变化率", ("Metric", "ScientificPrinciple")),
        )
    ):
        start = sequence * 10
        for label in labels:
            candidates.append(
                {
                    "id": f"{sequence}-{label}",
                    "text": text,
                    "label": label,
                    "start": start,
                    "end": start + len(text),
                    "confidence": 0.8,
                }
            )

    resolved = resolve_deterministic_entity_type_conflicts(
        {"entities": candidates, "relations": [], "metadata": {}},
        relabel_single_candidates=True,
    )

    assert [(entity["text"], entity["label"]) for entity in resolved["entities"]] == [
        ("多普勒频移", "Metric"),
        ("CDMA", "AlgorithmModel"),
        ("相位差变化率", "Metric"),
    ]
    assert resolved["metadata"]["entity_type_conflicts"]["conflict_count"] == 0


def test_deterministic_type_resolution_keeps_unique_surface_hint_and_rebinds_relation():
    weapon_labels = ["ScientificPrinciple", "Metric", "ProductSystem"]
    weapon_candidates = [
        {
            "id": f"weapon-{label}",
            "text": "高功率微波武器",
            "label": label,
            "start": 0,
            "end": 7,
            "confidence": 0.7,
            "model_sources": ["lightrag"],
        }
        for label in weapon_labels
    ]
    scenario = {
        "id": "scenario",
        "text": "电子压制场景",
        "label": "ApplicationScenario",
        "start": 8,
        "end": 14,
        "confidence": 0.9,
    }

    resolved = resolve_deterministic_entity_type_conflicts(
        {
            "entities": [*weapon_candidates, scenario],
            "relations": [
                {
                    "source": "weapon-ScientificPrinciple",
                    "target": "scenario",
                    "label": "SUPPORTS_APPLICATION",
                }
            ],
            "metadata": {},
        },
        relabel_single_candidates=True,
    )

    assert [(entity["text"], entity["label"]) for entity in resolved["entities"]] == [
        ("高功率微波武器", "ProductSystem"),
        ("电子压制场景", "ApplicationScenario"),
    ]
    assert resolved["relations"][0]["source"]["label"] == "ProductSystem"
    report = resolved["metadata"]["deterministic_entity_type_resolution"]
    assert report["resolved_group_count"] == 1
    assert report["dropped_entity_count"] == 2
    assert report["rebound_relation_count"] == 1


def test_deterministic_type_resolution_leaves_ambiguous_span_for_llm_review():
    candidates = [
        {"id": "a", "text": "液冷", "label": "Material", "start": 0, "end": 2},
        {"id": "b", "text": "液冷", "label": "ScientificPrinciple", "start": 0, "end": 2},
    ]

    resolved = resolve_deterministic_entity_type_conflicts({"entities": candidates, "relations": [], "metadata": {}})

    assert [entity["label"] for entity in resolved["entities"]] == ["Material", "ScientificPrinciple"]
    report = resolved["metadata"]["deterministic_entity_type_resolution"]
    assert report["resolved_group_count"] == 0
    assert report["unresolved_group_count"] == 1


def test_deterministic_type_resolution_relabels_single_surface_hint_and_drops_invalid_relation():
    resolved = resolve_deterministic_entity_type_conflicts(
        {
            "entities": [
                {
                    "id": "weapon",
                    "text": "高功率微波武器",
                    "label": "ProductSystem",
                    "start": 0,
                    "end": 7,
                    "confidence": 0.95,
                },
                {
                    "id": "drone",
                    "text": "无人机",
                    "label": "Constraint",
                    "start": 8,
                    "end": 11,
                    "confidence": 0.8,
                    "model_sources": ["lightrag"],
                },
            ],
            "relations": [
                {
                    "source": "weapon",
                    "target": "drone",
                    "label": "CONSTRAINED_BY",
                }
            ],
            "metadata": {},
        },
        relabel_single_candidates=True,
    )

    assert [(entity["text"], entity["label"]) for entity in resolved["entities"]] == [
        ("高功率微波武器", "ProductSystem"),
        ("无人机", "ProductSystem"),
    ]
    assert resolved["relations"] == []
    report = resolved["metadata"]["deterministic_entity_type_resolution"]
    assert report["relabeled_entity_count"] == 1
    assert report["dropped_relation_count"] == 1


def test_document_relation_consistency_converges_pod_and_directed_energy_types():
    entities = [
        {"id": "pod-product", "text": "吊舱", "label": "ProductSystem", "start": 0, "end": 2},
        {"id": "pod-component", "text": "吊舱", "label": "Component", "start": 10, "end": 12},
        {
            "id": "pod-principle",
            "text": "吊舱",
            "label": "ScientificPrinciple",
            "start": 20,
            "end": 22,
        },
        {"id": "battery", "text": "电池", "label": "Component", "start": 23, "end": 25},
        {"id": "cooling", "text": "晶体冷却方案", "label": "KeyTechnology", "start": 26, "end": 32},
        {"id": "energy-capability", "text": "定向能", "label": "Capability", "start": 33, "end": 36},
        {"id": "energy-tech", "text": "定向能", "label": "KeyTechnology", "start": 37, "end": 40},
        {"id": "missile", "text": "巡航导弹", "label": "ProductSystem", "start": 41, "end": 45},
        {"id": "suppression", "text": "电子压制能力", "label": "Capability", "start": 46, "end": 52},
    ]
    relations = [
        {"id": "r1", "source": "pod-product", "target": "battery", "label": "COMPOSED_OF"},
        {"id": "r2", "source": "pod-product", "target": "cooling", "label": "USES_TECHNOLOGY"},
        {"id": "r3", "source": "missile", "target": "energy-tech", "label": "USES_TECHNOLOGY"},
        {"id": "r4", "source": "energy-tech", "target": "suppression", "label": "ENABLES_CAPABILITY"},
    ]

    resolved = resolve_deterministic_entity_type_conflicts(
        {"entities": entities, "relations": relations, "metadata": {}}
    )

    labels_by_text = {}
    for entity in resolved["entities"]:
        labels_by_text.setdefault(entity["text"], set()).add(entity["label"])
    assert labels_by_text["吊舱"] == {"ProductSystem"}
    assert labels_by_text["定向能"] == {"KeyTechnology"}
    assert len(resolved["relations"]) == 4
    report = resolved["metadata"]["document_entity_type_consistency"]
    assert report["resolved_group_count"] == 2
    assert report["relabeled_entity_count"] == 3
    groups = {item["text"]: item for item in report["resolved_groups"]}
    assert groups["吊舱"]["relation_compatibility_scores"] == {
        "Component": 0,
        "ProductSystem": 2,
        "ScientificPrinciple": 0,
    }
    assert groups["定向能"]["relation_compatibility_scores"] == {
        "Capability": 0,
        "KeyTechnology": 2,
    }


def test_document_relation_consistency_keeps_conflict_when_evidence_is_insufficient():
    resolved = resolve_deterministic_entity_type_conflicts(
        {
            "entities": [
                {"id": "energy-capability", "text": "定向能", "label": "Capability", "start": 0, "end": 3},
                {"id": "energy-tech", "text": "定向能", "label": "KeyTechnology", "start": 4, "end": 7},
                {"id": "missile", "text": "巡航导弹", "label": "ProductSystem", "start": 8, "end": 12},
            ],
            "relations": [
                {
                    "id": "r1",
                    "source": "missile",
                    "target": "energy-tech",
                    "label": "USES_TECHNOLOGY",
                }
            ],
            "metadata": {},
        }
    )

    assert {entity["label"] for entity in resolved["entities"] if entity["text"] == "定向能"} == {
        "Capability",
        "KeyTechnology",
    }
    report = resolved["metadata"]["document_entity_type_consistency"]
    assert report["resolved_group_count"] == 0
    assert report["skipped_group_count"] == 1
    assert report["skipped_groups"][0]["reason"] == "insufficient_unique_relation_evidence"


def test_deterministic_type_resolution_keeps_multi_pass_audit_and_refreshes_conflicts():
    candidates = [
        {"id": "a", "text": "波束质量", "label": "Metric", "start": 0, "end": 4},
        {"id": "b", "text": "波束质量", "label": "Achievement", "start": 0, "end": 4},
    ]

    first = resolve_deterministic_entity_type_conflicts({"entities": candidates, "relations": [], "metadata": {}})
    second = resolve_deterministic_entity_type_conflicts(first)

    assert [entity["label"] for entity in second["entities"]] == ["Metric"]
    report = second["metadata"]["deterministic_entity_type_resolution"]
    assert report["pass_count"] == 2
    assert report["total_resolved_group_count"] == 1
    assert len(report["passes"]) == 2
    assert second["metadata"]["entity_type_conflicts"]["conflict_count"] == 0


def test_type_review_requires_exact_existing_span_and_closed_ontology_label():
    text = "高功率微波武器形成电子压制能力"
    proposals = validate_entity_review_proposals(
        [
            _raw_proposal(),
            {**_raw_proposal(), "start": 1},
            {**_raw_proposal(), "suggested_label": "Organization"},
        ],
        source_text=text,
        known_entities=[_entity()],
    )

    assert proposals == [
        {
            **_raw_proposal(),
            "status": "proposed",
            "applied": False,
        }
    ]


def test_review_rebinds_unique_existing_text_but_rejects_ambiguous_occurrences():
    unique_text = "高功率微波武器形成能力"
    unique = validate_entity_review_proposals(
        [{**_raw_proposal(), "entity_id": "", "start": 99, "end": 106}],
        source_text=unique_text,
        known_entities=[_entity()],
    )
    assert len(unique) == 1
    assert unique[0]["start"] == 0
    assert unique[0]["end"] == 7

    repeated_text = "火箭和火箭"
    repeated = [
        {"id": "", "text": "火箭", "label": "Component", "start": 0, "end": 2},
        {"id": "", "text": "火箭", "label": "Component", "start": 3, "end": 5},
    ]
    ambiguous = validate_entity_review_proposals(
        [
            {
                "entity_id": "",
                "text": "火箭",
                "start": 99,
                "end": 101,
                "current_label": "Component",
                "action": "relabel",
                "suggested_label": "ProductSystem",
                "confidence": 0.99,
            }
        ],
        source_text=repeated_text,
        known_entities=repeated,
    )
    assert ambiguous == []


def test_closed_review_refs_ignore_hallucinated_entities_and_use_platform_spans():
    text = "高功率微波武器形成能力"
    prompt, bindings = build_entity_review_prompt(
        text,
        [_entity()],
        ontology_definition={
            "entity_types": [
                {"code": "ScientificPrinciple", "description": "作用机理"},
                {"code": "ProductSystem", "description": "装备或系统"},
            ]
        },
    )
    assert prompt is not None
    assert '"entities":[],"relations":[]' in prompt
    assert list(bindings) == ["c1"]
    assert '"surface_type_hints":[{"suggested_label":"ProductSystem"' in prompt

    decisions, diagnostics = validate_entity_review_decisions(
        {
            "decisions": [
                {
                    "review_ref": "invented-e1",
                    "action": "reject",
                    "confidence": 1.0,
                },
                {
                    "review_ref": "c1",
                    "action": "relabel",
                    "suggested_label": "ProductSystem",
                    "confidence": 0.98,
                    "reason": "装备概念",
                    "text": "模型伪造文本",
                    "start": 999,
                    "end": 1000,
                },
            ]
        },
        source_text=text,
        bindings=bindings,
    )

    assert diagnostics == {
        "raw_decision_count": 2,
        "unknown_review_ref_count": 1,
        "valid_decision_count": 1,
    }
    assert decisions[0]["text"] == "高功率微波武器"
    assert decisions[0]["start"] == 0
    assert decisions[0]["end"] == 7


def test_review_prompt_exposes_same_surface_type_conflict_and_prioritizes_it():
    text = "高功率微波武器形成能力"
    candidates = [
        _entity(),
        {**_entity(), "id": "weapon-tech", "label": "KeyTechnology"},
    ]
    prompt, bindings = build_entity_review_prompt(
        text,
        candidates,
        ontology_definition={
            "entity_types": [
                {"code": "ScientificPrinciple", "description": "作用机理"},
                {"code": "KeyTechnology", "description": "技术方案"},
                {"code": "ProductSystem", "description": "装备或系统"},
            ]
        },
        trigger="suspect_only",
    )

    assert prompt is not None
    assert set(bindings) == {"c1", "c2"}
    assert '"same_surface_labels":["KeyTechnology","ScientificPrinciple"]' in prompt


def test_propose_mode_never_changes_existing_entity_or_relation():
    text = "高功率微波武器形成电子压制能力"
    capability = {
        "id": "capability",
        "text": "电子压制能力",
        "label": "Capability",
        "start": 9,
        "end": 15,
    }
    relation = {
        "source": _entity(),
        "target": capability,
        "label": "ENABLES_CAPABILITY",
    }
    proposals = validate_entity_review_proposals(
        [_raw_proposal()],
        source_text=text,
        known_entities=[_entity(), capability],
    )

    reviewed = review_entities(
        {"entities": [_entity(), capability], "relations": [relation], "metadata": {}},
        proposals,
        mode="propose",
    )

    assert reviewed["entities"][0]["label"] == "ScientificPrinciple"
    assert len(reviewed["relations"]) == 1
    report = reviewed["metadata"]["entity_review"]
    assert report["proposal_count"] == 1
    assert report["applied_count"] == 0


def test_experiment_mode_applies_high_confidence_pending_type_and_revalidates_relations():
    text = "高功率微波武器形成电子压制能力"
    capability = {
        "id": "capability",
        "text": "电子压制能力",
        "label": "Capability",
        "start": 9,
        "end": 15,
    }
    proposals = validate_entity_review_proposals(
        [_raw_proposal()],
        source_text=text,
        known_entities=[_entity(), capability],
    )
    reviewed = review_entities(
        {
            "entities": [_entity(), capability],
            "relations": [
                {
                    "source": _entity(),
                    "target": capability,
                    "label": "ENABLES_CAPABILITY",
                }
            ],
            "metadata": {},
        },
        proposals,
        mode="apply_experiment",
        min_confidence=0.95,
    )

    weapon = reviewed["entities"][0]
    assert weapon["label"] == "ProductSystem"
    assert weapon["original_label"] == "ScientificPrinciple"
    assert weapon["review_status"] == "pending"
    assert weapon["expert_review_required"] is True
    assert reviewed["relations"] == []
    report = reviewed["metadata"]["entity_review"]
    assert report["applied_count"] == 1
    assert report["relations_dropped_after_review"] == 1


def test_unresolved_same_surface_type_conflicts_are_audited_without_automatic_merge():
    first = _entity()
    second = {**_entity(), "id": "weapon-product", "label": "ProductSystem"}

    reviewed = review_entities(
        {"entities": [first, second], "relations": [], "metadata": {}},
        [],
        mode="apply_experiment",
    )

    assert [entity["label"] for entity in reviewed["entities"]] == ["ScientificPrinciple", "ProductSystem"]
    report = reviewed["metadata"]["entity_type_conflicts"]
    assert report["conflict_count"] == 1
    assert report["conflicts"][0]["labels"] == ["ProductSystem", "ScientificPrinciple"]
    assert report["conflicts"][0]["expert_review_required"] is True


def test_experiment_mode_never_rewrites_human_reviewed_entity():
    text = "高功率微波武器形成电子压制能力"
    proposals = validate_entity_review_proposals(
        [_raw_proposal()],
        source_text=text,
        known_entities=[_entity(reviewed=True)],
    )
    reviewed = review_entities(
        {"entities": [_entity(reviewed=True)], "relations": [], "metadata": {}},
        proposals,
        mode="apply_experiment",
    )

    assert reviewed["entities"][0]["label"] == "ScientificPrinciple"
    report = reviewed["metadata"]["entity_review"]
    assert report["applied_count"] == 0
    assert report["blocked_count"] == 1
    assert report["proposals"][0]["status"] == "blocked_human_review"


def test_experiment_mode_can_reject_non_entity_and_remove_incident_relations():
    text = "脉冲技术取得了成功"
    technology = {
        "id": "technology",
        "text": "脉冲技术",
        "label": "KeyTechnology",
        "start": 0,
        "end": 4,
    }
    generic = {
        "id": "generic",
        "text": "取得了成功",
        "label": "Achievement",
        "start": 4,
        "end": 9,
        "review_status": "pending",
        "model_sources": ["lightrag"],
    }
    proposals = validate_entity_review_proposals(
        [
            {
                "entity_id": "generic",
                "text": "取得了成功",
                "start": 4,
                "end": 9,
                "current_label": "Achievement",
                "action": "reject",
                "suggested_label": None,
                "confidence": 0.99,
                "reason": "一般性结果描述，不是论文、专利、样机或试验成果名称",
            }
        ],
        source_text=text,
        known_entities=[technology, generic],
    )
    reviewed = review_entities(
        {
            "entities": [technology, generic],
            "relations": [
                {
                    "source": technology,
                    "target": generic,
                    "label": "PRODUCES_ACHIEVEMENT",
                }
            ],
            "metadata": {},
        },
        proposals,
        mode="apply_experiment",
    )

    assert reviewed["entities"] == [technology]
    assert reviewed["relations"] == []
    report = reviewed["metadata"]["entity_review"]
    assert report["applied_count"] == 1
    assert report["reject_applied_count"] == 1
    assert report["relabel_applied_count"] == 0
    assert report["relations_dropped_after_review"] == 1


def test_reject_guard_does_not_allow_llm_to_delete_stable_technical_noun():
    text = "高功率微波武器形成能力"
    proposals = validate_entity_review_proposals(
        [
            {
                **_raw_proposal(),
                "action": "reject",
                "suggested_label": None,
                "confidence": 0.99,
            }
        ],
        source_text=text,
        known_entities=[_entity()],
    )

    assert proposals == []


def test_pipeline_allows_type_proposals_and_direct_apply_in_stable_channel():
    base = {
        "primary": {"endpoint": "http://lightrag", "model_version": "lightrag-v1"},
        "secondary": {"enabled": False},
        "llm_enhancement": {
            "enabled": True,
            "model_spec": "local:military-chat",
            "entity_review_mode": "propose",
        },
    }
    normalized = normalize_pipeline_options("lightrag_primary", base)
    assert normalized["orchestration_release_channel"] == "stable"
    assert normalized["llm_enhancement"]["entity_review_mode"] == "propose"

    blocked = {
        **base,
        "llm_enhancement": {
            **base["llm_enhancement"],
            "entity_review_mode": "apply_experiment",
        },
    }
    stable = normalize_pipeline_options("lightrag_primary", blocked)
    assert stable["llm_enhancement"]["entity_review_mode"] == "apply_experiment"

    experimental = normalize_pipeline_options(
        "lightrag_primary",
        {**blocked, "orchestration_release_channel": "experiment"},
    )
    assert experimental["llm_enhancement"]["entity_review_mode"] == "apply_experiment"
