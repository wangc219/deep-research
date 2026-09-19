from __future__ import annotations

import asyncio
from typing import Any

import pytest

from equipment_deep_research.agents.provider import (
    ResponsesAgentProvider,
    _reporter_generation_payload,
)
from equipment_deep_research.providers.fake import ScriptedFakeProvider
from equipment_deep_research.providers.base import ProviderFinalTurn, ProviderStreamEvent


def _research_handoff() -> dict[str, Any]:
    """Return the smallest substantive handoff that enables chapter repair."""

    return {
        "decisive_anchors": ["断链后目标证据快速过期"],
        "capability_cues": [
            {
                "direction": "有限区搜索远程弹药",
                "equipment_hint": "多模远程弹药",
                "mission_effect": "断链后保持有界复获与直接毁伤",
                "capability_gap": "外部航迹中断后缺少安全再捕获闭环",
            }
        ],
    }


def _valid_legacy_column(contract: dict[str, Any]) -> str:
    filler = (
        "该装备在真实威胁态势下以专属动作改写敌我交换关系，"
        "形成可验收的直接战果，并保留对手反适应与成立边界，"
        "使结论能够回到具体装备、作用对象和证据条件进行复核。"
    ) * 24
    parts = [f"## {contract['required_h2']}"]
    for heading in contract["required_h3"]:
        parts.append(f"### {heading}\n{filler}")
    return "\n".join(parts)


def test_reporter_generation_payload_builds_immutable_report_spine() -> None:
    payload = _reporter_generation_payload(
        {
            "topic": "强干扰条件下远程精确打击装备研究",
            "synthesis_seed": {
                "decisive_anchors": ["断链后目标证据快速过期"],
                "mission_chain_breaks": ["外部航迹中断"],
                "counterevidence_and_limits": ["公开参数仍待验证"],
                "capability_cues": [
                    {
                        "direction": "有限区搜索远程弹药",
                        "equipment_form": "多模远程弹药",
                        "capability_gap": "缺少安全再捕获闭环",
                        "target_scenario": "强电磁压制下断链突防",
                        "mechanism_chain": ["有界搜索", "身份复核", "直接毁伤"],
                        "failure_boundary": "搜索区外不保证复获",
                        "evidence_boundary": "公开来源有限",
                    }
                ],
            },
        }
    )

    spine = payload["report_spine"]
    assert spine["version"] == "report-spine-v1"
    assert spine["read_only"] is True
    assert spine["decisive_anchors"] == ["断链后目标证据快速过期"]
    assert spine["mission_chain_breaks"] == ["外部航迹中断"]
    assert spine["directions"] == [
        {
            "direction_id": "D01",
            "direction": "有限区搜索远程弹药",
            "equipment_form": "多模远程弹药",
            "capability_gap": "缺少安全再捕获闭环",
            "target_scenario": "强电磁压制下断链突防",
            "mechanism_chain": ["有界搜索", "身份复核", "直接毁伤"],
            "failure_boundary": "搜索区外不保证复获",
            "evidence_boundary": "公开来源有限",
        }
    ]
    assert spine["chapter_handoffs"]["layer_1"].startswith("场景")
    assert "章节不得重新发散候选" in spine["evidence_policy"]


def test_parallel_columns_receive_the_same_report_spine(monkeypatch) -> None:
    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    spines: list[dict[str, Any]] = []

    async def fake_reporter(
        system: str,
        payload: dict[str, Any],
        max_output_tokens: int,
        **kwargs: Any,
    ) -> str:
        del system, max_output_tokens, kwargs
        spines.append(payload["report_spine"])
        return _valid_legacy_column(payload["parallel_section_contract"])

    provider._run_reporter_text = fake_reporter  # type: ignore[method-assign]
    monkeypatch.setattr(
        "equipment_deep_research.agents.workflows.reporter._report_draft_quality_issues",
        lambda report, payload: [],
    )
    monkeypatch.setattr(
        "equipment_deep_research.agents.workflows.reporter._minimum_viable_model_report",
        lambda report, payload: True,
    )

    provider.draft_report(
        {
            "run_id": "shared-report-spine",
            "topic": "强干扰条件下远程精确打击装备研究",
            "execution_profile_id": "winning_swarm_dynamic_v2",
            "synthesis_seed": {
                "decisive_anchors": ["断链后目标证据快速过期"],
                "capability_cues": [
                    {
                        "direction": "有限区搜索远程弹药",
                        "equipment_form": "多模远程弹药",
                        "capability_gap": "缺少安全再捕获闭环",
                        "mission_effect": "断链后保持直接毁伤",
                    }
                ],
            },
        }
    )

    assert len(spines) == 9
    assert all(spine is spines[0] for spine in spines)
    assert all(spine["version"] == "report-spine-v1" for spine in spines)


def test_reporter_call_carries_run_id_into_provider_options() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text="完成栏目"))]]
    )
    provider = ResponsesAgentProvider(backend)

    result = asyncio.run(
        provider._run_reporter_text(
            "只输出栏目正文",
            {"report_spine": {"version": "report-spine-v1"}},
            1800,
            phase="report_generation_item_1_scenario",
            run_id="tenant-run-42",
            isolation_id="tenant-run-42:item-1",
        )
    )

    assert result == "完成栏目"
    _messages, _tools, options = backend.inputs[0]
    assert options["_run_id"] == "tenant-run-42"
    assert options["prompt_mode"] == "standalone"


def test_parallel_report_stops_duplicate_nonempty_repair_root(monkeypatch) -> None:
    """A repeated quality root must not consume a second identical repair wave."""

    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    phases: list[str] = []

    async def fake_reporter(
        system: str,
        payload: dict[str, Any],
        max_output_tokens: int,
        **kwargs: Any,
    ) -> str:
        del system, max_output_tokens
        phase = str(kwargs["phase"])
        phases.append(phase)
        contract = payload["parallel_section_contract"]
        if contract["layer_id"] == "item_4_realization_path":
            # Keep returning a non-empty draft with the same substance-floor
            # defect so the repair fingerprint can be observed.
            return (
                f"## {contract['required_h2']}\n"
                f"### {contract['required_h3'][0]}\n短稿。"
            )
        return _valid_legacy_column(contract)

    provider._run_reporter_text = fake_reporter  # type: ignore[method-assign]
    monkeypatch.setattr(
        "equipment_deep_research.agents.workflows.reporter._report_draft_quality_issues",
        lambda report, payload: [],
    )
    monkeypatch.setattr(
        "equipment_deep_research.agents.workflows.reporter._minimum_viable_model_report",
        lambda report, payload: True,
    )
    monkeypatch.setattr(
        "equipment_deep_research.agents.workflows.reporter._reporter_chapter_fallback_profile",
        lambda host, payload: "",
    )

    with pytest.raises(ValueError, match="parallel Reporter assembly"):
        provider._draft_parallel_report(
            {
                "run_id": "duplicate-repair-root",
                "topic": "动态集群装备研究",
            },
            reporter_input={"research_handoff": _research_handoff()},
            output_token_budget=5000,
        )

    assert phases.count("report_generation_item_4_realization_path") == 1
    assert phases.count("report_generation_item_4_realization_path_retry1") == 1
    assert "report_generation_item_4_realization_path_retry2" not in phases
    assert provider._last_report_repair_stalled_columns == [
        "item_4_realization_path"
    ]
    # Other columns complete exactly once; the failed column is isolated.
    assert all(
        phases.count(f"report_generation_{layer_id}") == 1
        for layer_id in (
            "item_1_scenario",
            "item_2_winning_mechanism",
            "item_3_capability_features",
            "item_5_core_technologies",
            "item_6_coupling_risks",
            "item_7_capability_image",
            "item_8_effectiveness",
            "item_9_priority",
        )
    )


def test_parallel_report_budget_limits_repair_to_failed_column(monkeypatch) -> None:
    """A nearly exhausted Reporter lane reserves its last slot for one failure."""

    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    provider.configure_run_budget({"maximum_reporter_model_calls": 13})
    # The fake seam bypasses the provider's normal call accounting, so mirror
    # one atomic Reporter slot per invocation below.
    provider._budget_started_reporter_calls = 0
    phases: list[str] = []

    async def fake_reporter(
        system: str,
        payload: dict[str, Any],
        max_output_tokens: int,
        **kwargs: Any,
    ) -> str:
        del system, max_output_tokens
        phase = str(kwargs["phase"])
        phases.append(phase)
        provider._budget_started_reporter_calls += 1
        contract = payload["parallel_section_contract"]
        if contract["layer_id"] == "item_4_realization_path":
            return ""
        return _valid_legacy_column(contract)

    provider._run_reporter_text = fake_reporter  # type: ignore[method-assign]
    monkeypatch.setattr(
        "equipment_deep_research.agents.workflows.reporter._report_draft_quality_issues",
        lambda report, payload: [],
    )
    monkeypatch.setattr(
        "equipment_deep_research.agents.workflows.reporter._minimum_viable_model_report",
        lambda report, payload: True,
    )
    monkeypatch.setattr(
        "equipment_deep_research.agents.workflows.reporter._reporter_chapter_fallback_profile",
        lambda host, payload: "",
    )

    with pytest.raises(ValueError, match="parallel Reporter assembly"):
        provider._draft_parallel_report(
            {"run_id": "budget-isolated-repair", "topic": "动态集群装备研究"},
            reporter_input={"research_handoff": _research_handoff()},
            output_token_budget=5000,
        )

    assert phases.count("report_generation_item_4_realization_path") == 1
    assert phases.count("report_generation_item_4_realization_path_retry1") == 1
    assert not any(phase.endswith("_retry2") for phase in phases)
    assert not any("_retry1" in phase for phase in phases if "item_4" not in phase)
