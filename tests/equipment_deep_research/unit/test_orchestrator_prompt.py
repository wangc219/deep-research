from __future__ import annotations

from equipment_deep_research.agents.orchestrator_prompt import (
    AGENT_SELECTION_OUTPUT_SCHEMA,
    BLUEPRINT_OUTPUT_SCHEMA,
    META_REPLAN_OUTPUT_SCHEMA,
    ORCHESTRATOR_PROMPT_VERSION,
    orchestrator_system_prompt,
)


def test_orchestrator_prompt_covers_architecture_decision_order() -> None:
    prompt = orchestrator_system_prompt("blueprint_design")

    assert "资深 JS 专家人格" in prompt
    assert "需求语义解析" in prompt
    assert "驱动源识别" in prompt
    assert "蓝图生成" in prompt
    assert "Agent 与 DAG 编排" in prompt
    assert "循环控制" in prompt
    assert "OTHER" in prompt
    assert "不读取其他 Agent 原始会话" in prompt


def test_orchestrator_prompt_keeps_weapon_innovation_space_open() -> None:
    prompt = orchestrator_system_prompt("blueprint_design")

    assert ORCHESTRATOR_PROMPT_VERSION == "2.8"
    assert "不得给出装备名称、装备家族、技术路线" in prompt
    assert "固定颠覆种子、共享示例、公开型号和常见装备目录不得进入蓝图首轮上下文" in prompt
    assert "前瞻性、创新性和颠覆性" in prompt
    assert "不为并行凑数" in prompt
    brief_schema = BLUEPRINT_OUTPUT_SCHEMA["structured_query_brief"]
    assert "winning_problem_propositions" in brief_schema
    assert "equipment_semantic_boundary" in brief_schema
    assert "query_specific_weapon_architectures" not in brief_schema
    assert "frontier_technology_hypotheses" not in brief_schema
    assert "equipment_project_hypotheses" not in brief_schema


def test_orchestrator_output_schemas_keep_decisions_auditable() -> None:
    assert "driver_scores" in BLUEPRINT_OUTPUT_SCHEMA
    assert "unmatched_driver" in BLUEPRINT_OUTPUT_SCHEMA
    assert "custom_blueprint" in BLUEPRINT_OUTPUT_SCHEMA
    assert "baseline_agent_plan" in BLUEPRINT_OUTPUT_SCHEMA
    assert "coverage_matrix" in AGENT_SELECTION_OUTPUT_SCHEMA
    assert "stop_reason" in META_REPLAN_OUTPUT_SCHEMA
