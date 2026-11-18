from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from platform_core.knowledge.graphs.extractors.lightrag_enhancement import LightRAGQualityEnhancer
from platform_core.knowledge.graphs.lightrag_relation_completion import (
    build_relation_completion_inventory,
    match_relation_cues,
    normalize_relation_completion_options,
)


def _entity(text: str, source: str, label: str, entity_id: str, confidence: float = 0.95) -> dict:
    start = source.index(text)
    return {
        "id": entity_id,
        "text": text,
        "label": label,
        "start": start,
        "end": start + len(text),
        "confidence": confidence,
        "model_sources": ["model_a", "model_b"],
    }


def test_relation_completion_builds_closed_ontology_valid_pairs_and_excludes_existing():
    text = "脉冲压缩采用匹配滤波算法，提高雷达距离分辨能力。另一系统使用相控阵天线。"
    technology = _entity("脉冲压缩", text, "KeyTechnology", "duplicate")
    algorithm = _entity("匹配滤波算法", text, "AlgorithmModel", "duplicate")
    capability = _entity("雷达距离分辨能力", text, "Capability", "capability")
    component = _entity("相控阵天线", text, "Component", "component")
    result = {
        "entities": [technology, algorithm, capability, component],
        "relations": [
            {
                "source": technology,
                "target": algorithm,
                "label": "USES_TECHNOLOGY",
            }
        ],
    }

    inventory = build_relation_completion_inventory(text, result, {"enabled": True})

    assert inventory["revision"] == "defense-lightrag-relation-completion-v4"
    assert inventory["metrics"]["eligible_entity_count"] == 4
    assert inventory["candidates"]
    assert len(inventory["endpoint_aliases"]) >= 2
    assert all(row["source_ref"].startswith("rc-e") for row in inventory["candidates"])
    assert all(row["target_ref"].startswith("rc-e") for row in inventory["candidates"])
    assert all("POTENTIAL_FOR" not in row["allowed_labels"] for row in inventory["candidates"])
    assert not any(
        row["source"]["text"] == "脉冲压缩"
        and row["target"]["text"] == "匹配滤波算法"
        and "USES_TECHNOLOGY" in row["allowed_labels"]
        for row in inventory["candidates"]
    )
    assert not any(
        {row["source"]["text"], row["target"]["text"]} == {"雷达距离分辨能力", "相控阵天线"}
        for row in inventory["candidates"]
    )
    broad = build_relation_completion_inventory(
        text,
        result,
        {"enabled": True, "require_relation_cue": False},
    )
    assert broad["candidates"]


def test_relation_completion_filters_low_confidence_entities_and_invalid_options():
    text = "脉冲压缩形成雷达距离分辨能力"
    result = {
        "entities": [
            _entity("脉冲压缩", text, "KeyTechnology", "tech", confidence=0.74),
            _entity("雷达距离分辨能力", text, "Capability", "cap"),
        ],
        "relations": [],
    }

    inventory = build_relation_completion_inventory(text, result, {"enabled": True})

    assert inventory["metrics"]["eligible_entity_count"] == 1
    assert inventory["candidates"] == []
    with pytest.raises(ValueError, match="relation_completion.enabled"):
        normalize_relation_completion_options({"enabled": "yes"})
    with pytest.raises(ValueError, match="min_relation_confidence"):
        normalize_relation_completion_options({"min_relation_confidence": 2})


def test_entity_first_relation_completion_accepts_single_lightrag_endpoints_but_keeps_grounding_guards():
    text = "脉冲压缩采用匹配滤波算法。相控阵天线和雷达距离分辨能力分属两句。"
    technology = _entity("脉冲压缩", text, "KeyTechnology", "tech", confidence=0.61)
    algorithm = _entity("匹配滤波算法", text, "AlgorithmModel", "algorithm", confidence=0.58)
    component = _entity("相控阵天线", text, "Component", "component", confidence=0.95)
    capability = _entity("雷达距离分辨能力", text, "Capability", "capability", confidence=0.95)
    for entity in (technology, algorithm, component, capability):
        entity["model_sources"] = ["lightrag"]

    config = normalize_relation_completion_options(
        {"enabled": True},
        orchestration_mode="lightrag_cascade",
        primary_extract_relations=False,
    )
    inventory = build_relation_completion_inventory(
        text,
        {"entities": [technology, algorithm, component, capability], "relations": []},
        config,
    )

    assert config["endpoint_policy"] == "entity_first_single_model"
    assert config["min_entity_confidence"] == 0.5
    assert config["min_entity_model_sources"] == 1
    assert config["require_same_sentence"] is True
    assert config["require_relation_cue"] is True
    assert any(
        row["source"]["text"] == "脉冲压缩"
        and row["target"]["text"] == "匹配滤波算法"
        and "USES_TECHNOLOGY" in row["allowed_labels"]
        for row in inventory["candidates"]
    )
    assert not any(
        {row["source"]["text"], row["target"]["text"]} == {"相控阵天线", "雷达距离分辨能力"}
        for row in inventory["candidates"]
    )


def test_relation_completion_treats_pdf_line_wrap_as_same_sentence_but_keeps_real_sentence_boundary():
    text = "吊舱将采用一种新\r\n的晶体冷却方案。激光器用于致盲。"
    pod = _entity("吊舱", text, "ProductSystem", "pod")
    cooling = _entity("晶体冷却方案", text, "KeyTechnology", "cooling")
    laser = _entity("激光器", text, "Component", "laser")
    blinding = _entity("致盲", text, "Capability", "blinding")

    inventory = build_relation_completion_inventory(
        text,
        {"entities": [pod, cooling, laser, blinding], "relations": []},
        {"enabled": True},
    )

    pod_to_cooling = next(
        row
        for row in inventory["candidates"]
        if row["source"]["text"] == "吊舱" and row["target"]["text"] == "晶体冷却方案"
    )
    assert "USES_TECHNOLOGY" in pod_to_cooling["allowed_labels"]
    assert text[pod_to_cooling["evidence_span"]["start"] : pod_to_cooling["evidence_span"]["end"]] == (
        "吊舱将采用一种新\r\n的晶体冷却方案。"
    )
    assert not any(
        row["source"]["text"] == "吊舱" and row["target"]["text"] == "激光器" for row in inventory["candidates"]
    )


def test_relation_completion_prefers_pairs_with_relation_cue_between_endpoints():
    text = "高功率微波巡航导弹采用型尾翼和低可探测设计，杀伤性武器用于突防。"
    missile = _entity("高功率微波巡航导弹", text, "ProductSystem", "missile")
    tail = _entity("型尾翼", text, "Component", "tail")
    stealth = _entity("低可探测设计", text, "KeyTechnology", "stealth")
    weapon = _entity("杀伤性武器", text, "ProductSystem", "weapon")

    inventory = build_relation_completion_inventory(
        text,
        {"entities": [missile, tail, stealth, weapon], "relations": []},
        {"enabled": True},
    )

    uses_candidates = [
        row for row in inventory["candidates"] if "USES_TECHNOLOGY" in row["allowed_labels"]
    ]
    assert uses_candidates
    assert all(row["source"]["text"] == "高功率微波巡航导弹" for row in uses_candidates)
    assert all(row["between_endpoint_cues"]["USES_TECHNOLOGY"] == ["采用"] for row in uses_candidates)
    assert inventory["metrics"]["cue_position_pruned_pairs"] >= 1


def test_entity_first_relation_completion_resolves_only_high_precision_surface_type_conflict():
    text = "吊舱采用晶体冷却方案，定向能形成压制能力。"
    pod = _entity("吊舱", text, "ProductSystem", "pod")
    cooling_component = _entity("晶体冷却方案", text, "Component", "cooling-component")
    cooling_technology = _entity("晶体冷却方案", text, "KeyTechnology", "cooling-technology")
    energy_capability = _entity("定向能", text, "Capability", "energy-capability")
    energy_metric = _entity("定向能", text, "Metric", "energy-metric")
    suppression = _entity("压制能力", text, "Capability", "suppression")
    entities = [
        pod,
        cooling_component,
        cooling_technology,
        energy_capability,
        energy_metric,
        suppression,
    ]
    for entity in entities:
        entity["model_sources"] = ["lightrag"]

    inventory = build_relation_completion_inventory(
        text,
        {"entities": entities, "relations": []},
        {
            "enabled": True,
            "endpoint_policy": "entity_first_single_model",
            "min_entity_confidence": 0.5,
            "min_entity_model_sources": 1,
        },
    )

    assert inventory["metrics"]["entity_resolution_counts"] == {"ambiguous_resolved_by_surface_hint": 1}
    assert inventory["metrics"]["entity_rejection_counts"] == {
        "ambiguous_nonselected_types": 1,
        "ambiguous_same_span_types": 2,
    }
    assert any(
        row["source"]["text"] == "吊舱"
        and row["target"]["text"] == "晶体冷却方案"
        and row["target"]["label"] == "KeyTechnology"
        and "USES_TECHNOLOGY" in row["allowed_labels"]
        for row in inventory["candidates"]
    )
    assert not any(
        row["source"]["text"] == "定向能" or row["target"]["text"] == "定向能" for row in inventory["candidates"]
    )


def test_relation_completion_rejects_ambiguous_same_span_and_single_model_endpoints():
    text = "系统使用微波炸弹攻击电视台"
    system = _entity("系统", text, "ProductSystem", "system")
    weapon = _entity("微波炸弹", text, "ProductSystem", "weapon")
    conflicting = {**weapon, "id": "technology", "label": "KeyTechnology"}
    broadcaster = _entity("电视台", text, "Component", "broadcaster")
    broadcaster["model_sources"] = ["lightrag"]

    inventory = build_relation_completion_inventory(
        text,
        {"entities": [system, weapon, conflicting, broadcaster], "relations": []},
        {"enabled": True},
    )

    assert inventory["candidates"] == []
    assert inventory["metrics"]["entity_rejection_counts"] == {
        "ambiguous_same_span_types": 2,
        "clear_non_ontology_entity": 1,
    }


def test_relation_completion_cues_are_shared_with_review_output():
    assert match_relation_cues("IMPROVES", "该方法显著提高距离分辨能力") == ["提高"]
    assert match_relation_cues("UNKNOWN", "提高") == []


@pytest.mark.asyncio
async def test_relation_completion_gleaning_resolves_temporary_refs_and_keeps_grounded_relation():
    text = "脉冲压缩形成雷达距离分辨能力"
    technology = _entity("脉冲压缩", text, "KeyTechnology", "same-id")
    capability = _entity("雷达距离分辨能力", text, "Capability", "same-id")
    llm = Mock()
    llm.validate_options = Mock()
    llm.aclose = AsyncMock()
    llm.complete_json = AsyncMock(
        return_value={
            "entities": [],
            "relations": [
                {
                    "pair_ref": "rc-p1",
                    "source": "rc-e1",
                    "target": "rc-e2",
                    "label": "ENABLES_CAPABILITY",
                    "claim_level": "Fact",
                    "confidence": 0.93,
                    "evidence_spans": [{"start": 0, "end": len(text)}],
                }
            ],
            "ocr_repair_proposals": [],
        }
    )
    enhancer = LightRAGQualityEnhancer(
        {
            "model_spec": "mock:model",
            "max_gleanings": 1,
            "entity_review_mode": "off",
            "relation_completion": {"enabled": True},
        },
        llm=llm,
    )

    result = await enhancer.glean(text, {"entities": [technology, capability], "relations": [], "metadata": {}})

    assert len(result["relations"]) == 1
    relation = result["relations"][0]
    assert relation["source"]["text"] == "脉冲压缩"
    assert relation["target"]["text"] == "雷达距离分辨能力"
    assert relation["evidence_spans"] == [{"start": 0, "end": len(text)}]
    report = result["metadata"]["llm_enhancement"]
    assert report["gleaning_mode"] == "relation_completion"
    assert report["relation_completion"]["accepted_relation_count"] == 1
    prompt = llm.complete_json.await_args.args[0]
    assert "封闭关系候选" in prompt
    assert '"source":"rc-e1"' in prompt


@pytest.mark.asyncio
async def test_relation_completion_applies_stricter_relation_confidence_gate():
    text = "脉冲压缩提高雷达距离分辨能力"
    technology = _entity("脉冲压缩", text, "KeyTechnology", "tech")
    capability = _entity("雷达距离分辨能力", text, "Capability", "cap")
    llm = Mock(validate_options=Mock(), aclose=AsyncMock())
    llm.complete_json = AsyncMock(
        return_value={
            "entities": [],
            "relations": [
                {
                    "source": "rc-e1",
                    "target": "rc-e2",
                    "label": "IMPROVES",
                    "confidence": 0.7,
                    "evidence_spans": [{"start": 0, "end": len(text)}],
                }
            ],
        }
    )
    enhancer = LightRAGQualityEnhancer(
        {
            "model_spec": "mock:model",
            "max_gleanings": 1,
            "entity_review_mode": "off",
            "relation_completion": {"enabled": True, "min_relation_confidence": 0.82},
        },
        llm=llm,
    )

    result = await enhancer.glean(text, {"entities": [technology, capability], "relations": [], "metadata": {}})

    assert result["relations"] == []
    budget = result["metadata"]["llm_enhancement"]["gleaning_output_budget"]
    assert budget["relation_rejection_counts"] == {"below_relation_confidence": 1}
