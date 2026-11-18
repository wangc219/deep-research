from __future__ import annotations

from platform_core.knowledge.graphs.core_semantic_roles import (
    build_domain_extraction_guidance,
    build_core_role_guidance,
    core_role_for_entity_type,
)
from platform_core.knowledge.graphs.extractors.defense_quality_contract import build_defense_quality_contract


def test_five_role_mapping_preserves_fine_grained_types_and_concept_boundary():
    assert core_role_for_entity_type("ScientificPrinciple") == "principle"
    assert core_role_for_entity_type("AlgorithmModel") == "technology"
    assert core_role_for_entity_type("Material") == "technology"
    assert core_role_for_entity_type("ProductSystem") == "application"
    assert core_role_for_entity_type("ApplicationScenario") == "application"
    assert core_role_for_entity_type("Concept") == "concept"
    assert core_role_for_entity_type("Domain") == ""
    assert core_role_for_entity_type("Constraint") == ""


def test_llm_guidance_contains_reference_definitions_naming_and_actual_codes():
    guidance = build_core_role_guidance(
        [
            {"code": "ScientificPrinciple"},
            {"code": "AlgorithmModel"},
            {"code": "Capability"},
            {"code": "ProductSystem"},
            {"code": "Domain"},
        ]
    )

    assert "研究什么问题，面向什么对象、需求、环境或威胁" in guidance
    assert "为什么有效，能力收益从何而来" in guidance
    assert "AlgorithmModel" in guidance
    assert "ProductSystem" in guidance
    assert "当前本体未提供独立编码" in guidance
    assert "不能机械替代五类主干角色" in guidance
    assert "领域限定词 + 核心对象 + 类型后缀" in guidance


def test_hot_path_llm_quality_contract_uses_same_five_role_naming_rules():
    contract = build_defense_quality_contract(enable_hypotheses=False, max_hypotheses=0)

    assert "回答“研究什么问题，面向什么对象、需求、环境或威胁”" in contract
    assert "按上下文语义角色而不是关键词后缀判型" in contract
    assert "领域限定词 + 核心对象 + 类型后缀" in contract
    assert "英文缩写、译名和长短名称并入 aliases" in contract


def test_domain_guidance_adds_research_threads_and_real_world_evidence_gate():
    guidance = build_domain_extraction_guidance([{"code": "KeyTechnology"}, {"code": "ProductSystem"}])

    assert "main" in guidance
    assert "side" in guidance
    assert "parallel" in guidance
    assert "五类允许缺项" in guidance
    assert "仿真、模拟、数字孪生" in guidance
    assert "样机、外场实测、系统应用" in guidance
    assert "不得为了形成完整链路编造实际应用" in guidance
