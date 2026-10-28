from __future__ import annotations

import asyncio
import json

from equipment_deep_research.providers.base import (
    ProviderFinalTurn,
    ProviderStreamEvent,
)
from equipment_deep_research.providers.fake import ScriptedFakeProvider
from equipment_deep_research.providers.responses import ProviderRetryableError
from equipment_deep_research.query_library.generator import (
    ModelQueryGenerator,
    _generation_profile,
    _generation_token_budget,
    _hypothesis_target,
)
from equipment_deep_research.query_library.models import GeneratedCandidate, SourceReference
from equipment_deep_research.query_library.quality import (
    coverage_plan,
    near_duplicate,
    sanitize_source_reference,
    validate_generated_candidate,
)


def _quality_fields(query: str) -> dict[str, object]:
    return {
        "demand_chain": {
            "situation_signal": "公开资料显示相关任务环境和对抗方式正在持续变化",
            "future_mission": "未来高强度对抗中需要持续完成跨域装备运用任务",
            "task_constraint": "复杂环境、短时窗口和体系节点受损限制任务完成",
            "capability_gap": "现有装备在自主协同和持续运用方面存在能力缺口",
            "weapon_requirement": f"形成与{query}直接对应的装备能力需求",
            "evidence_status": "inferred",
            "disconfirmation_condition": "若代表性试验表明现有装备已稳定满足任务要求，则该需求不成立",
        },
        "quality_review": {
            "causal_specificity": "pass",
            "differentiation": "pass",
            "researchability": "pass",
            "verdict": "pass",
            "revision_note": "已完成反向质检。",
        },
    }


DIVERGENCE = {
    "hypotheses": [
        {
            "hypothesis_id": "H01",
            "dimension": "未来任务",
            **_quality_fields("无人远程火力装备研究")["demand_chain"],
            "candidate_equipment_forms": ["无人平台", "智能弹药"],
            "priority_reason": "任务窗口和现有能力缺口同时存在。",
        }
    ]
}


def test_generator_returns_all_twelve_coverage_slots_with_sources() -> None:
    source = {
        "title": "公开规划资料",
        "url": "https://example.test/planning",
        "relevance_note": "提供公开术语和规划线索。",
    }
    grounding = {
        "summary": "公开资料显示无人远程火力装备持续向智能协同与规模化发展。",
        "search_queries": ["无人远程火力 装备 规划"],
        "signals": ["智能协同", "低成本规模化"],
        "sources": [source],
    }
    rows = []
    for index, slot in enumerate(coverage_plan(12), start=1):
        query = f"无人远程火力装备第{index}类{slot.split('-', 1)[-1]}研究"
        rows.append(
            {
                "coverage_slot": slot,
                "query": query,
                "supplemental_information": (
                    "面向未来高强度对抗，分析任务约束、技术趋势、体系效能、失效边界、"
                    "指标方向和验证场景；兼顾智能自主、传统现役跨代做优、新质蓝海颠覆拓新、"
                    "低成本供应链和装备族规模发展，形成装备能力需求建议。"
                ),
                "generation_rationale": "该问题把公开发展信号转化为可验证的装备需求研究任务。",
                "sources": [
                    {
                        "url": source["url"],
                        "relevance_note": "该来源支持当前术语和发展方向的校验。",
                    }
                ],
                **_quality_fields(query),
            }
        )
    provider = ScriptedFakeProvider(
        [
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(
                        text=json.dumps(grounding, ensure_ascii=False),
                        metadata={"web_sources": [source]},
                    )
                )
            ],
            [ProviderStreamEvent.final(ProviderFinalTurn(text=json.dumps(DIVERGENCE, ensure_ascii=False)))],
            [ProviderStreamEvent.final(ProviderFinalTurn(text=json.dumps({"queries": rows}, ensure_ascii=False)))],
        ]
    )

    result = asyncio.run(
        ModelQueryGenerator(provider).generate(
            topic="无人远程火力打击装备",
            supplemental_information="面向未来高端战争",
            reference_urls=("https://example.test/manual-reference",),
            count=12,
            batch_size=20,
            existing_queries=[],
        )
    )

    assert len(result.candidates) == 12
    assert {item.coverage_slot for item in result.candidates} == set(coverage_plan(12))
    assert all(item.source_references for item in result.candidates)
    assert all(14 <= len(item.query) <= 30 for item in result.candidates)
    assert provider.remaining_steps == 0
    assert provider.inputs[0][2]["require_web_search"] is False
    assert provider.inputs[0][2]["_provider_retry_attempts"] == 3
    grounding_request = json.loads(provider.inputs[0][0][1].content)
    assert grounding_request["reference_urls"] == ["https://example.test/manual-reference"]
    divergence_request = json.loads(provider.inputs[1][0][1].content)
    assert divergence_request["target_hypothesis_count"] == 24
    assert len(divergence_request["divergence_dimensions"]) >= 8
    assert "web_search" not in provider.inputs[2][2]
    generation_request = json.loads(provider.inputs[2][0][1].content)
    requirements = "".join(generation_request["requirements"])
    assert "coverage_slot只是思考发生维度" in requirements
    assert "具体装备项目" in requirements
    assert "项目功能" in requirements
    for request, contract_key in (
        (grounding_request, "output_contract"),
        (divergence_request, "requirements"),
        (generation_request, "requirements"),
    ):
        contract = "".join(request[contract_key])
        assert "安全态势、面临威胁和未来军事作战需要" in contract
        assert "不主动生成极端灾害、民用应急救援" in contract
        assert "仅当用户明确指定民用研究母题" in contract
        assert "自然环境应作为军事任务的条件约束" in contract
        assert "默认以中国为研究主体" in contract
        assert "围绕母题和自动态势两种模式均适用" in contract
        assert "具体武器装备类别" in contract
        assert "战略制衡" in contract
        assert "不预设某种装备能够制胜" in contract
        assert "不提出针对现实对手的攻击方案或武器改进设计" in contract
        assert "待研究的未决问题" in contract
    assert "为何值得现在研究" in requirements
    assert "公开证据缺口与验证路径" in requirements


def test_generator_records_codex_situation_assessment_without_web_results() -> None:
    grounding = {
        "summary": "未获得外部网页来源，按用户母题进行语义发散。",
        "search_queries": [],
        "signals": ["任务牵引", "装备能力需求"],
        "sources": [],
    }
    row = {
        "coverage_slot": coverage_plan(1)[0],
        "query": "未来无人精确打击装备任务需求研究",
        "supplemental_information": (
            "面向复杂对抗任务，分析作战场景、威胁约束、装备能力缺口、失效边界和可验证的发展方向。"
        ),
        "generation_rationale": "将输入母题中的任务牵引转化为可独立论证的装备能力研究问题。",
        "sources": [],
        **_quality_fields("未来无人精确打击装备任务需求研究"),
    }
    provider = ScriptedFakeProvider(
        [
            [ProviderStreamEvent.final(ProviderFinalTurn(text=json.dumps(grounding, ensure_ascii=False)))],
            [ProviderStreamEvent.final(ProviderFinalTurn(text=json.dumps(DIVERGENCE, ensure_ascii=False)))],
            [ProviderStreamEvent.final(ProviderFinalTurn(text=json.dumps({"queries": [row]}, ensure_ascii=False)))],
        ]
    )

    result = asyncio.run(
        ModelQueryGenerator(
            provider,
            provider_snapshot={"type": "codex_cli", "model": "test"},
        ).generate(
            topic="未来无人精确打击装备",
            supplemental_information="自动态势发散模式。不提供参考 URL 也应能够完成生成。",
            count=1,
            existing_queries=[],
        )
    )

    assert len(result.candidates) == 1
    assert result.source_references[0].source_kind == "document"
    assert result.source_references[0].url == ""
    assert result.source_references[0].title.startswith("态势研判")
    assert "中国当前安全环境" in result.source_references[0].relevance_note
    assert result.candidates[0].source_references == result.source_references
    grounding_request = json.loads(provider.inputs[0][0][1].content)
    assert grounding_request["analysis_mode"] == "codex_cli_china_situation_assessment"
    assert "3至5个聚焦检索" in grounding_request["task"]
    assert "外部态势→任务压力→作战缺口→武器装备能力与发展需求" in grounding_request["task"]
    assert provider.inputs[0][2]["web_search"]["search_context_size"] == "low"
    assert provider.inputs[0][2]["_provider_retry_attempts"] == 1
    generation_request = json.loads(provider.inputs[2][0][1].content)
    requirements = "".join(generation_request["requirements"])
    assert "实质不同的装备需求矛盾" in requirements
    assert "高关注方向" in requirements
    assert "不设固定类别配额" in requirements
    assert "充分发挥模型的异质发散能力" in requirements
    assert "被态势直接牵引的武器装备需求" in requirements
    assert "direct_strike_priority_slots" not in generation_request
    assert "不写成时事摘要" in requirements
    divergence_request = json.loads(provider.inputs[1][0][1].content)
    for request, contract_key in (
        (grounding_request, "output_contract"),
        (divergence_request, "requirements"),
        (generation_request, "requirements"),
    ):
        contract = "".join(request[contract_key])
        assert "不主动生成极端灾害、民用应急救援" in contract
        assert "不能把自然灾害本身替代为军事需求来源" in contract
    assert "偏离军事任务的民用灾害命题必须替换" in requirements
    assert provider.inputs[2][2]["_provider_retry_attempts"] == 2


def test_generator_continues_when_optional_grounding_times_out() -> None:
    row = {
        "coverage_slot": coverage_plan(1)[0],
        "query": "未来无人精确打击装备任务需求研究",
        "supplemental_information": (
            "面向复杂对抗任务，分析作战场景、威胁约束、装备能力缺口、失效边界和可验证的发展方向。"
        ),
        "generation_rationale": "将输入母题中的任务牵引转化为可独立论证的装备能力研究问题。",
        "sources": [],
        **_quality_fields("未来无人精确打击装备任务需求研究"),
    }

    class GroundingTimeoutProvider(ScriptedFakeProvider):
        async def stream(self, messages, tools, options):
            self.inputs.append((tuple(messages), tuple(tools), dict(options)))
            if len(self.inputs) == 1:
                raise ProviderRetryableError("hosted search timed out")
            async for event in super().stream(messages, tools, options):
                yield event

    provider = GroundingTimeoutProvider(
        [
            [ProviderStreamEvent.final(ProviderFinalTurn(text=json.dumps(DIVERGENCE, ensure_ascii=False)))],
            [ProviderStreamEvent.final(ProviderFinalTurn(text=json.dumps({"queries": [row]}, ensure_ascii=False)))],
        ]
    )

    result = asyncio.run(
        ModelQueryGenerator(provider).generate(
            topic="未来无人精确打击装备",
            supplemental_information="面向未来任务开展装备能力需求分析",
            count=1,
            existing_queries=[],
        )
    )

    assert [item.query for item in result.candidates] == [row["query"]]
    assert result.source_references[0].source_kind == "document"
    assert provider.inputs[0][2]["_provider_timeout_seconds"] == 90


def test_source_sanitizer_removes_sensitive_query_parameters() -> None:
    cleaned = sanitize_source_reference(
        SourceReference(
            title="source",
            url="https://example.test/report?id=7&token=secret&api_key=hidden#part",
        )
    )

    assert cleaned.url == "https://example.test/report?id=7"
    assert "secret" not in cleaned.url
    assert "hidden" not in cleaned.url


def test_near_duplicate_normalizes_punctuation_and_spacing() -> None:
    assert near_duplicate(
        "研究 无人远程火力装备：体系能力需求",
        "研究无人远程火力装备体系能力需求",
    )


def test_quality_gate_rejects_title_without_auditable_demand_chain() -> None:
    candidate = GeneratedCandidate(
        coverage_slot=coverage_plan(1)[0],
        query="未来无人精确打击装备任务需求研究",
        supplemental_information="面向未来复杂对抗任务，分析威胁约束、能力缺口、失效边界和装备发展方向。",
        generation_rationale="从未来作战任务反推装备能力需求。",
        source_references=(SourceReference(title="模型分析", source_kind="document"),),
    )

    issues = validate_generated_candidate(
        candidate,
        expected_slot=coverage_plan(1)[0],
        existing_queries=[],
        accepted_queries=[],
    )

    assert any("demand_chain.future_mission" in issue for issue in issues)
    assert "quality_review.verdict must pass after self-revision" in issues


def test_quality_gate_accepts_civil_emergency_equipment_domain_terms() -> None:
    candidate = GeneratedCandidate(
        coverage_slot=coverage_plan(1)[0],
        query="极端灾害应急照明供电装备韧性设计研究",
        supplemental_information="面向公共避难场所断电场景，研究照明、电源和便携供电系统的可靠性与失效边界。",
        generation_rationale="把灾害现场持续照明需求转化为可验证的应急装备研究问题。",
        source_references=(SourceReference(title="模型分析", source_kind="document"),),
        demand_chain={
            "situation_signal": "极端灾害导致公共电网长时中断",
            "future_mission": "持续保障避难场所基础照明",
            "task_constraint": "便携部署且补能条件受限",
            "capability_gap": "现有应急灯续航与状态诊断能力不足",
            "weapon_requirement": "便携电源具备长续航和故障自检能力",
            "disconfirmation_condition": "实测续航和切换可靠性没有改善",
            "evidence_status": "inferred",
        },
        quality_review={
            "verdict": "pass",
            "causal_specificity": "pass",
            "differentiation": "pass",
            "researchability": "pass",
        },
    )

    assert not validate_generated_candidate(
        candidate,
        expected_slot=coverage_plan(1)[0],
        existing_queries=[],
        accepted_queries=[],
        topic="极端灾害场景下民用应急照明与便携供电设备的可靠性提升",
    )


def test_generation_profiles_bound_divergence_and_output_budgets() -> None:
    assert _generation_profile("生成策略：高效") == "efficient"
    assert _hypothesis_target(12, "efficient") == 18
    assert _hypothesis_target(12, "balanced") == 24
    assert _hypothesis_target(20, "deep") == 30
    assert _generation_token_budget(8, autonomous_discovery=True, profile="efficient") < (
        _generation_token_budget(8, autonomous_discovery=True, profile="deep")
    )


def test_malformed_model_json_fails_instead_of_creating_template_results() -> None:
    import pytest
    from equipment_deep_research.query_library.models import GenerationValidationError

    responses = [
        json.dumps({"summary": "通信终端任务", "sources": []}),
        json.dumps(DIVERGENCE),
        "not JSON",
        "not JSON",
        "not JSON",
    ]
    provider = ScriptedFakeProvider([[ProviderStreamEvent.final(ProviderFinalTurn(text=value))] for value in responses])
    saved = []
    with pytest.raises(GenerationValidationError, match="仅 0/1"):
        asyncio.run(
            ModelQueryGenerator(provider).generate(
                topic="通信终端任务研究",
                supplemental_information="",
                count=1,
                existing_queries=[],
                on_candidate=saved.append,
            )
        )
    assert saved == []
    assert provider.remaining_steps == 0


def test_efficient_query_uses_one_call_without_unavailable_web_search_or_serial_planner() -> None:
    row = {
        "coverage_slot": coverage_plan(1)[0],
        "query": "复杂环境通信终端及配套供电系统研究",
        "supplemental_information": "分析复杂环境下通信终端持续运行的供电约束、故障边界、验证方法与装备功能需求。",
        "generation_rationale": "从持续通信任务约束识别终端与配套供电系统的研究需求。",
        **_quality_fields("复杂环境通信终端及配套供电系统研究"),
    }
    provider = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text=json.dumps({"queries": [row]})))]]
    )
    stages, batches = [], []
    result = asyncio.run(
        ModelQueryGenerator(provider, default_profile="efficient").generate(
            topic="通信终端可靠性研究",
            supplemental_information="",
            count=1,
            existing_queries=[],
            on_stage=stages.append,
            on_batch=batches.append,
        )
    )
    assert len(result.candidates) == 1
    assert len(provider.inputs) == 1
    assert stages == ["context_analysis", "query_generation"]
    options = provider.inputs[0][2]
    assert options["_disable_hidden_reasoning"] is True
    assert options["_provider_structured_retry_attempts"] == 0
    assert options["_query_stage_timeout_seconds"] == 60
    assert options["phase"] == "query_generation"
    assert options["max_output_tokens"] >= 4096
    assert batches[0]["completed"] == batches[0]["total"] == 1


def test_query_stage_deadline_cancels_slow_stream_even_if_provider_has_no_timeout():
    import pytest
    from equipment_deep_research.query_library.generator import _collect_stream

    class SlowProvider:
        cancelled = False

        async def stream(self, *_args):
            try:
                await asyncio.sleep(2)
                yield ProviderStreamEvent.final(ProviderFinalTurn(text="{}"))
            finally:
                self.cancelled = True

    provider = SlowProvider()
    with pytest.raises(ProviderRetryableError, match="阶段超时"):
        asyncio.run(_collect_stream(provider, (), {"_query_stage_timeout_seconds": 0.01}))
    assert provider.cancelled


def test_batches_overlap_save_fast_results_and_repair_only_failed_slots():
    import pytest
    from equipment_deep_research.query_library.models import GenerationValidationError

    class Generator(ModelQueryGenerator):
        def __init__(self):
            super().__init__(ScriptedFakeProvider([]), default_profile="efficient", provider_snapshot={"model": "a"})
            self.calls = []
            self.active = 0
            self.peak = 0
            self.first_saved = asyncio.Event()

        async def _generate_candidates(self, **kwargs):
            slots = kwargs["remaining_slots"]
            self.calls.append(list(slots))
            self.active += 1
            self.peak = max(self.peak, self.active)
            try:
                if slots[0] == coverage_plan(4)[0]:
                    await asyncio.wait_for(self.first_saved.wait(), 1)
                    raise ProviderRetryableError("temporary failure")
                await asyncio.sleep(0.01)
                rows = []
                names = [
                    "复杂对抗远程火力任务需求研究",
                    "低成本无人平台自主导航能力研究",
                    "分布式通信终端配套供电系统研究",
                    "深海探测传感器环境适应性能研究",
                ]
                for slot in slots:
                    query = names[list(coverage_plan(4)).index(slot)]
                    rows.append(
                        {
                            "coverage_slot": slot,
                            "query": query,
                            "supplemental_information": (
                                "分析智能自主装备的任务场景、装备功能与能力约束，"
                                "识别失效边界、验证方法和可审计的需求方向。"
                            ),
                            "generation_rationale": "从公开任务约束形成可验证的装备功能需求研究。",
                            **_quality_fields(query),
                        }
                    )
                return {"queries": rows}, {}
            finally:
                self.active -= 1

    async def run():
        generator = Generator()
        saved, progress = [], []

        def save(candidate):
            saved.append(candidate)
            generator.first_saved.set()

        with pytest.raises(GenerationValidationError, match="仅 2/4"):
            await generator.generate(
                topic="装备研究",
                supplemental_information="",
                count=4,
                existing_queries=[],
                on_candidate=save,
                on_batch=progress.append,
            )
        assert generator.peak == 2
        assert len(saved) == 2
        assert generator.calls == [list(coverage_plan(4))[:2], list(coverage_plan(4))[2:], list(coverage_plan(4))[:2]]
        assert progress[-1]["request_batches"] == 3
        assert progress[-1]["repair_batches"] == 1
        assert progress[-1]["completed"] == 2
        assert progress[-1]["rejected_count"] == 2

    asyncio.run(run())


def test_planning_cache_reuse_requires_same_model_input_and_one_hour_ttl():
    from datetime import UTC, datetime, timedelta
    import pytest
    from equipment_deep_research.query_library.models import GenerationValidationError

    class Generator(ModelQueryGenerator):
        def __init__(self, model):
            super().__init__(ScriptedFakeProvider([]), provider_snapshot={"model": model})
            self.ground_calls = 0
            self.planning_calls = 0

        async def _ground(self, **kwargs):
            self.ground_calls += 1
            return {"summary": "test", "sources": []}, {}

        async def _diverge_demand_hypotheses(self, **kwargs):
            self.planning_calls += 1
            return []

        async def _generate_candidates(self, **kwargs):
            return {"queries": []}, {}

    async def run():
        checkpoints = []
        first = Generator("a")
        kwargs = dict(topic="装备任务研究", supplemental_information="", count=1, existing_queries=[])
        with pytest.raises(GenerationValidationError):
            await first.generate(**kwargs, on_checkpoint=lambda value: checkpoints.append(dict(value)))
        checkpoint = checkpoints[-1]
        assert "identity" in checkpoint
        same = Generator("a")
        with pytest.raises(GenerationValidationError):
            await same.generate(**kwargs, checkpoint=checkpoint)
        assert (same.ground_calls, same.planning_calls) == (0, 0)
        for model, saved, topic in [
            ("b", checkpoint, kwargs["topic"]),
            ("a", {**checkpoint, "cached_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat()}, kwargs["topic"]),
            ("a", {**checkpoint, "cached_at": "2026-10-15T00:00:00"}, kwargs["topic"]),
            ("a", checkpoint, "另一项研究"),
        ]:
            other = Generator(model)
            with pytest.raises(GenerationValidationError):
                await other.generate(**{**kwargs, "topic": topic}, checkpoint=saved)
            assert (other.ground_calls, other.planning_calls) == (1, 1)

    asyncio.run(run())


def test_all_saved_candidates_resume_without_model_calls_and_report_recovery():
    provider = ScriptedFakeProvider([])
    candidate = GeneratedCandidate(
        coverage_slot=coverage_plan(1)[0],
        query="复杂环境智能通信终端可靠性研究",
        supplemental_information="已通过校验并保存",
        generation_rationale="任务恢复",
        source_references=(),
    )
    progress = []
    result = asyncio.run(
        ModelQueryGenerator(provider).generate(
            topic="通信终端研究",
            supplemental_information="",
            count=1,
            existing_queries=[],
            accepted_candidates=[candidate],
            on_batch=progress.append,
        )
    )
    assert result.candidates == (candidate,)
    assert provider.inputs == []
    assert progress[0]["restored_count"] == 1
    assert progress[0]["request_batches"] == 0
