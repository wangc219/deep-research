from __future__ import annotations

from equipment_deep_research.agents.orchestrator_prompt import (
    AGENT_SELECTION_OUTPUT_SCHEMA,
    BLUEPRINT_OUTPUT_SCHEMA,
    META_REPLAN_OUTPUT_SCHEMA,
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


def test_orchestrator_output_schemas_keep_decisions_auditable() -> None:
    assert "driver_scores" in BLUEPRINT_OUTPUT_SCHEMA
    assert "unmatched_driver" in BLUEPRINT_OUTPUT_SCHEMA
    assert "custom_blueprint" in BLUEPRINT_OUTPUT_SCHEMA
    assert "baseline_agent_plan" in BLUEPRINT_OUTPUT_SCHEMA
    assert "coverage_matrix" in AGENT_SELECTION_OUTPUT_SCHEMA
    assert "stop_reason" in META_REPLAN_OUTPUT_SCHEMA
