from __future__ import annotations

from equipment_deep_research.agents.workflows.orchestrator import deep_contextual_dialogue
from equipment_deep_research.deep_thinking import build_reference_capability


def test_deep_contextual_dialogue_is_one_call_and_not_six_stage_workflow() -> None:
    calls: list[tuple[str, str, dict, dict, int, str]] = []

    class Host:
        async def _run_core_json(self, agent_id, prompt, payload, schema, budget, *, phase):
            calls.append((agent_id, prompt, payload, schema, budget, phase))
            return {"visible_summary": ["基于已有卡片继续推演"], "concept_directions": []}

    result = deep_contextual_dialogue(Host(), {"query": "单装备"})
    assert result["visible_summary"] == ["基于已有卡片继续推演"]
    assert len(calls) == 1
    agent_id, prompt, payload, _schema, _budget, phase = calls[0]
    assert agent_id == "deep_thinking_dialogue"
    assert phase == "deep_contextual_dialogue"
    # The wording may distinguish a hard prohibition ("绝不") from a
    # user-facing instruction ("不要"), but the contract is the same: this
    # entrypoint must not dispatch or simulate the baseline S1-S6 workflow.
    assert "重新执行、模拟或调用" in prompt
    assert "S1-S6" in prompt
    assert "workflow_dispatch" not in payload


def test_deep_contextual_dialogue_contract_keeps_existing_snapshot() -> None:
    captured: dict = {}

    class Host:
        async def _run_core_json(self, agent_id, prompt, payload, schema, budget, *, phase):
            captured.update(payload)
            return {"visible_summary": [], "concept_directions": []}

    deep_contextual_dialogue(Host(), {"query": "装备", "existing_result": {"id": "canonical"}})
    assert captured["existing_result"]["id"] == "canonical"


def test_reference_capability_exposes_canonical_equipment_and_effect_fields() -> None:
    artifact = build_reference_capability(
        run_id="run-1",
        query="低空目标拦截",
        candidate={
            "name": "参考拦截无人机",
            "equipment_form": "末段拦截无人机",
            "hypothesis_id": "hypothesis-1",
            "card_binding_id": "binding-1",
            "operational_mechanism": "弹上复核压缩末段交战窗口",
            "direct_military_effects": "直接拦截低空目标",
            "failure_boundary": "强干扰条件下识别可能退化",
            "validation_plan": "开展仿真与实装复核",
            "evidence_ids": ["ev-1"],
        },
    )

    assert artifact["equipment_form"] == "末段拦截无人机"
    assert artifact["equipment_forms"] == ["末段拦截无人机"]
    assert artifact["primary_equipment_identity"] == "参考拦截无人机"
    assert artifact["operational_mechanism"] == "弹上复核压缩末段交战窗口"
    assert artifact["mechanism_chain"] == artifact["operational_mechanism"]
    assert artifact["direct_military_effects"] == "直接拦截低空目标"
    assert artifact["military_value"] == artifact["direct_military_effects"]
    assert artifact["failure_boundary"] == "强干扰条件下识别可能退化"
    assert artifact["validation_plan"] == "开展仿真与实装复核"
