from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from equipment_deep_research.agents.provider import (
    AgentRunRequest,
    AgentSelectionRequest,
    ResponsesAgentProvider,
    _apply_codex_performance_options,
    _build_limited_report,
    _capability_direction_quality_issues,
    _capability_synthesis_handoff,
    _recover_invalid_s6_result,
    _s6_can_use_lightweight_card_repair,
    _s6_repair_targets,
    _latest_inner_loop_failures,
    _report_draft_quality_issues,
    _report_issues_require_fallback,
    _normalize_branch_report_labels,
    _normalize_report_structure_deterministically,
    _report_writer_system_prompt,
    _reporter_generation_payload,
    _sanitize_reporter_output,
    _stabilize_report_delivery_contract,
    _typed_packet_payload,
)
from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.agents.registry import AgentRegistry
from equipment_deep_research.agents.runtime_profiles import (
    CODEX_AGENT_RUNTIME_PROFILES,
    build_codex_runtime_profile,
)
from equipment_deep_research.providers.base import (
    ModelMessage,
    ProviderFinalTurn,
    ProviderStreamEvent,
)
from equipment_deep_research.providers.fake import ScriptedFakeProvider
from equipment_deep_research.providers.responses import ProviderRequestError
from equipment_deep_research.orchestration.runner import DeepResearchRunner
from equipment_deep_research.orchestration.deliverables import branch_writer_brief
from equipment_deep_research.orchestration.capability_fallback import (
    build_deadline_weapon_directions,
)
from equipment_deep_research.orchestration.winning_swarm import (
    SWARM_SPECIALIST_ARCHETYPES,
)
from pathlib import Path


def _three_layer_report(
    *,
    source_urls: list[str] | None = None,
    extra: str = "",
    detail_count: int = 72,
) -> str:
    urls = source_urls or []
    source_lines = [
        f"- [公开来源{index}]({url})"
        for index, url in enumerate(urls, start=1)
    ]
    details = [
        f"- 补充论证{index}：围绕任务阶段、体系接口、证据边界和验证条件形成不重复的高价值判断。"
        for index in range(1, detail_count + 1)
    ]
    return "\n\n".join(
        [
            "## 第一层：需求挖掘层——场景·战法/技术·装备能力特征",
            "### ① 典型作战场景\n对手在濒海复杂地域实施高烈度对抗，关键时间窗为首轮任务链形成前后；约束条件包括强电磁压制、低空遮蔽和补给受限。公开事实与分析推断分别标注，关键假设和反证保留。",
            "### ② 新战法或新概念技术及制胜机理\n现有范式依赖集中节点，受压后难以持续闭合杀伤链；新战法以分布式无人协同和远程精确打击重构行动—反行动关系，因此可获得制胜优势。若对手形成有效反制，则该机理在失效边界外不成立。",
            "### ③ 装备能力特征清单\n能力域覆盖感知、决策、突防、打击、压制、抗毁和保障；指标方向包括射程、响应时间、自主等级、成本量级、规模量级、精度和生存力，具体数值待验证。",
            "## 第二层：技术攻关层——能力实现途径与核心技术",
            "### ④ 能力实现途径\n近期采用沿用改进补齐接口，中期通过集成创新形成异构协同，远期对关键效应机理开展原理突破，并分别绑定现役升级和新研装备。",
            "### ⑤ 核心技术清单与攻关优先级\n具体技术点包括抗干扰制导律、轻质耐热材料体系、协同决策算法和开放式任务架构。成熟度按样机、工程化和试验验证分级；P0解决瓶颈，P1完成集成，P2保留预研，TRL证据不足处标记待验证。",
            "### ⑥ 技术耦合与短板风险\n感知、通信、制导和能源存在强耦合与依赖；若抗干扰链路成为卡脖子短板，将导致级联退化并拖垮整个能力链。",
            "## 第三层：能力图像与效能贡献层",
            "### ⑦ 装备能力图像\n能力域构成、指标画像和装备谱系位置共同表明，该方向位于现有装备体系与新一代低成本无人精打装备之间，边界是弱网自治和持续保障能力。",
            "### ⑧ 效能贡献评估\n该装备可补链恢复发现—打击闭环、强链提高压制与抗毁能力、开链形成远程毁伤新路径；量化方向包括突防率提升量级、交换比改善量级和决策周期压缩量级。",
            "### ⑨ 发展优先级与近期抓手\nP0启动低空无人精确打击演示验证项目，P1完善体系接口，P2保留原理样机。项目设置对抗场景、样机范围、验收指标、通过条件和失败条件；未来3至10年按触发条件演进，并披露未知、置信度和验证风险。",
            extra,
            *source_lines,
            *details,
        ]
    )


def test_c_branch_report_labels_are_normalized_without_rewriting_prose() -> None:
    original = """## 分支规定成果
### 规律一：透明战场压缩集中节点生存空间
正文甲保持不变，说明打击与反制价值。
### 案例规律二：低成本饱和改变攻防交换比
正文乙保持不变。
### 核心案例规律3：电子战成为杀伤链开关
### 跨案例规律（四）：无人化必须制度化
### 规律五：工业补充决定持续作战上限
### 规律（六）：不存在单一银弹装备
### 场景（一）：陆上透明战场消耗循环
### 未来场景二：濒海分布式拒止
### 高置信未来场景3：海上交通线持续扰袭
### 装备方向1：分布式抗毁指挥与杀伤链装备
### 装备类别（二）：低成本无人侦察打击装备
### 新兴装备方向3：分层反无人装备
### 新兴装备类别（四）：前沿快速恢复装备
"""
    normalized = _normalize_branch_report_labels(
        original,
        {"branch_writer_brief": {"branch": "C"}},
    )

    for label, count in (
        ("核心规律", 6),
        ("高置信场景", 3),
        ("新兴装备类别", 4),
    ):
        for index in range(1, count + 1):
            assert f"{label}{index}" in normalized
    assert "正文甲保持不变，说明打击与反制价值。" in normalized
    assert "正文乙保持不变。" in normalized
    assert len(normalized) <= len(original) + 40


def test_c_branch_label_normalization_avoids_full_report_repair(monkeypatch) -> None:
    draft = """## 分支规定成果
### 规律一：规律标题
### 规律二：规律标题
### 规律三：规律标题
### 规律四：规律标题
### 规律五：规律标题
### 规律六：规律标题
### 场景（一）：场景标题
### 场景（二）：场景标题
### 场景（三）：场景标题
### 装备方向1：装备标题
### 装备方向2：装备标题
### 装备方向3：装备标题
### 装备方向4：装备标题
迁移边界明确。正文保持不变。
"""
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text=draft))]]
    )
    provider = ResponsesAgentProvider(backend)

    def numbered_gate(text, payload):
        del payload
        missing = []
        for label, count in (
            ("核心规律", 6),
            ("高置信场景", 3),
            ("新兴装备类别", 4),
        ):
            for index in range(1, count + 1):
                if f"{label}{index}" not in text:
                    missing.append(f"{label}{index}")
        return missing

    monkeypatch.setattr(
        "equipment_deep_research.agents.provider._report_draft_quality_issues",
        numbered_gate,
    )
    result = provider.draft_report(
        {
            "topic": "从近年局部战争中挖掘我军装备发展需求",
            "branch_writer_brief": {"branch": "C"},
        }
    )

    assert "核心规律1" in result
    assert "高置信场景3" in result
    assert "新兴装备类别4" in result
    assert "正文保持不变。" in result
    assert len(backend.inputs) == 1


def test_report_heading_format_is_repaired_locally_without_second_model_call(
    monkeypatch,
) -> None:
    draft = """# 重复报告标题
## 第一层：需求挖掘层——场景·战法/技术·装备能力特征
### ① 典型作战场景
场景正文。
### ② 新战法或新概念技术及制胜机理
机理正文。
### ③ 装备能力特征清单
能力正文。
## 第二层：技术攻关层——能力实现途径与核心技术
### ④ 能力实现途径
途径正文。
### ⑤ 核心技术清单与攻关优先级
技术正文。
### ⑥ 技术耦合与短板风险
风险正文。
## 第三层：能力图像与效能贡献层
### ⑦ 能力画像
装备正文。
### ⑧ 效能贡献评估
效能正文。
### ⑨ 发展优先级与近期抓手
抓手正文。
## 核心公开来源索引
来源正文。
"""
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text=draft))]]
    )
    provider = ResponsesAgentProvider(backend)
    monkeypatch.setattr(
        "equipment_deep_research.agents.provider._report_draft_quality_issues",
        lambda text, payload: (
            ["报告格式存在契约外二级标题：核心公开来源索引"]
            if "## 核心公开来源索引" in text
            else []
        ),
    )

    result = provider.draft_report(
        {"topic": "装备需求", "branch_writer_brief": {"branch": "B"}}
    )

    assert len(backend.inputs) == 1
    assert not result.startswith("# ")
    assert "### ⑦ 装备能力图像" in result
    assert "## 核心公开来源索引" not in result
    assert "**核心公开来源索引**" in result
    assert _normalize_report_structure_deterministically(result) == result


def test_reporter_has_separate_delivery_grace_and_call_budget() -> None:
    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    provider.configure_run_budget(
        {
            "maximum_model_calls": 7,
            "maximum_model_calls_with_residuals": 10,
            "maximum_delivery_model_calls": 2,
            "soft_deadline_seconds": 720,
            "hard_deadline_seconds": 900,
            "delivery_grace_seconds": 300,
            "absolute_deadline_seconds": 1800,
        }
    )
    provider._run_started_at -= 901

    critical_remaining = provider._reserve_model_call(priority="critical")
    assert critical_remaining is not None and 115 <= critical_remaining <= 120

    first_remaining = provider._reserve_model_call(priority="delivery")
    second_remaining = provider._reserve_model_call(priority="delivery")
    assert first_remaining is not None and 250 <= first_remaining <= 260
    assert second_remaining is not None and 295 <= second_remaining <= 300
    with pytest.raises(RuntimeError, match="delivery model-call budget"):
        provider._reserve_model_call(priority="delivery")

    provider.configure_run_budget(
        {
            "hard_deadline_seconds": 900,
            "delivery_grace_seconds": 300,
            "maximum_delivery_model_calls": 2,
        }
    )
    provider._run_started_at -= 1201
    with pytest.raises(RuntimeError, match="delivery deadline"):
        provider._reserve_model_call(priority="delivery")

    provider.configure_run_budget(
        {
            "hard_deadline_seconds": 900,
            "delivery_grace_seconds": 300,
            "critical_fast_finalize_seconds": 120,
        }
    )
    provider._run_started_at -= 1021
    with pytest.raises(RuntimeError, match="critical fast-finalize deadline"):
        provider._reserve_model_call(priority="critical")


def test_reporter_keeps_full_quality_after_hard_deadline(
    monkeypatch,
) -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text="快速收敛报告正文"))]]
    )
    provider = ResponsesAgentProvider(backend)
    provider.configure_run_budget(
        {
            "hard_deadline_seconds": 900,
            "delivery_grace_seconds": 300,
            "absolute_deadline_seconds": 1200,
            "maximum_delivery_model_calls": 2,
            "deadline_downshift_window_seconds": 240,
            "delivery_retry_reserve_seconds": 45,
            "fast_finalize_output_token_cap": 4200,
        }
    )
    provider._run_started_at -= 901
    monkeypatch.setattr(
        "equipment_deep_research.agents.provider._report_draft_quality_issues",
        lambda text, payload: [],
    )

    result = provider.draft_report(
        {
            "topic": "硬截止快速收敛验证",
            "execution_profile_id": "optimized_v2",
            "report_context": {"primary_branch": "B"},
        }
    )

    assert result == "快速收敛报告正文"
    messages, _, options = backend.inputs[0]
    assert options["reasoning_effort"] == "xhigh"
    assert options["model_verbosity"] == "medium"
    assert options["max_output_tokens"] == 12000
    assert "retry_instruction" not in messages[1].content
    metric = provider._call_metrics_since(0)[-1]
    assert metric["deadline_mode"] == "fast_finalize"


def test_deadline_is_recomputed_after_model_queue_wait() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text="queued result"))]]
    )
    provider = ResponsesAgentProvider(backend)
    provider.configure_run_budget(
        {
            "hard_deadline_seconds": 900,
            "delivery_grace_seconds": 300,
            "absolute_deadline_seconds": 1200,
            "critical_fast_finalize_seconds": 120,
            "fast_finalize_output_token_cap": 4200,
        }
    )

    class QueueDelayGate:
        def try_acquire(self, *, priority):
            del priority
            return None

        def acquire(self, *, priority):
            provider._run_started_at -= 901
            return SimpleNamespace(
                priority=priority,
                queue_wait_seconds=901.0,
                concurrency_limit=1,
                active_calls=1,
            )

        def release(self, elapsed_seconds, *, success):
            del elapsed_seconds, success

        def snapshot(self):
            return {"active": 1, "concurrency_limit": 1}

    provider._call_gate = QueueDelayGate()  # type: ignore[assignment]
    options = {"reasoning_effort": "high", "max_output_tokens": 5000}
    text, metadata = asyncio.run(
        provider._collect_stream(
            backend,
            [ModelMessage("user", "test")],
            options,
            priority="critical",
        )
    )

    assert text == "queued result"
    assert options["reasoning_effort"] == "low"
    assert options["max_output_tokens"] <= 1800
    assert metadata["deadline_mode"] == "fast_finalize"
    assert metadata["deadline_remaining_seconds"] <= 120


def test_s6_rejects_productized_support_layer_upgrade_name() -> None:
    def direction(name: str, direction_type: str) -> dict[str, object]:
        portrait_seed = (
            f"{name}面向强对抗任务阶段，通过现役装备传感、火控和效应链重构，"
            "压缩目标发现至火力分配时间，并在对手干扰和机动条件下维持拦截、"
            "反制、毁伤评估与再打击能力；同时说明反适应、工程边界和验证条件。"
        )
        row: dict[str, object] = {
            "name": name,
            "type": direction_type,
            "function": "提升目标捕获、火力分配、拦截反制和再打击能力",
            "equipment_form": "现役雷达、火控系统与拦截武器",
            "operational_mechanism": "在预警、交战和毁伤评估阶段缩短火力闭环并提高抗饱和拦截能力",
            "military_value": "提升拦截、反制、拒止和威慑效果",
            "development_path": "近期现役升级—中期体系集成—实装对抗验证",
            "future_trigger": "对手强干扰与饱和突防能力持续增强",
            "adversary_adaptation": "对手可能采用诱饵、机动和多轴突防",
            "failure_boundary": "传感器受压且弹药供给不足时效果下降",
            "strike_countermeasure_value": "提升目标捕获、火力引导、拦截反制和再打击效能",
            "combat_effect_uplift": "恢复并强化拦截、毁伤和再打击闭环",
            "strike_chain_contribution": "贯通侦察、决策、火力、打击、评估和再组织",
            "capability_portrait": (portrait_seed * 8)[:420],
        }
        if direction_type == "upgrade":
            row.update(
                {
                    "baseline_system": "现役C2/ISR与防空反导火控系统",
                    "upgrade_package": ["目标级融合改进", "火控与拦截武器协同改进"],
                    "upgrade_boundary": "平台算力和火控接口无法承载时转入新研",
                }
            )
        return row

    issues = _capability_direction_quality_issues(
        {
            "concept_directions": [
                direction("抗毁C2/ISR边缘闭环升级包", "upgrade"),
                direction("分布式反舰导弹协同猎歼能力", "new_capability"),
                direction("多域电子战压制与区域拒止任务系统", "new_capability"),
            ]
        }
    )

    assert any("现役升级标题禁止使用包" in issue for issue in issues)
    assert any("现役升级名称未体现" in issue for issue in issues)


def test_invalid_s6_is_recovered_without_another_model_call() -> None:
    invalid = {
        "concept_directions": [
            {
                "name": "弱网联合杀伤网装备包",
                "type": "upgrade",
                "equipment_form": "通信节点和任务网关",
                "capability_gap": "强干扰下链路不稳定",
                "direct_evidence_refs": ["ev-1"],
            }
        ],
        "confidence": 0.7,
    }
    recovered, issues = _recover_invalid_s6_result(
        invalid,
        topic="强干扰、弱通信条件下低信息依赖精确打击研究",
        handoff={
            "query": "强干扰、弱通信条件下低信息依赖精确打击研究",
            "public_evidence": [{"evidence_id": "ev-1"}],
        },
    )

    assert issues == []
    assert recovered["deterministic_quality_recovery"] is True
    names = [item["name"] for item in recovered["concept_directions"]]
    assert len(names) == 6
    assert all("装备包" not in name for name in names)
    assert any("无人" in name or "巡飞弹" in name for name in names)
    assert any("导弹" in name for name in names)


def test_s6_uses_lightweight_repair_for_a_bounded_local_card_set() -> None:
    rows = build_deadline_weapon_directions(
        topic="强干扰弱通信精确打击",
        evidence_ids=["ev-1"],
    )
    rows[0] = {
        **rows[0],
        "name": "弱网联合杀伤网装备包",
        "equipment_form": "通信节点和任务网关",
    }
    result = {"concept_directions": rows, "confidence": 0.7}
    issues = _capability_direction_quality_issues(
        result,
        handoff={"query": "强干扰弱通信精确打击"},
    )

    assert issues
    assert _s6_can_use_lightweight_card_repair(result, issues) is True
    assert _s6_can_use_lightweight_card_repair(
        {"concept_directions": rows[:3]},
        ["S6必须形成5至7项具体、互异且高军事价值的最终武器装备方向"],
    ) is False


def test_s6_combines_three_portfolio_issues_into_one_lightweight_repair() -> None:
    rows = build_deadline_weapon_directions(
        topic="强干扰弱通信精确打击",
        evidence_ids=["ev-1"],
    )
    rows[0] = {
        **rows[0],
        "name": "强干扰下具备打击能力的体系",
        "type": "upgrade",
        "equipment_form": "通信节点和任务网关",
    }
    result = {"concept_directions": rows, "confidence": 0.7}
    issues = [
        "S6第1项标题是描述句，需改为简洁的具体装备名称",
        "S6第1项现役升级标题未明确现役武器、传感器、火控、电子战或指挥任务系统对象",
        "S6至少需要4个相互区分的直接武器或无人作战装备方向",
    ]

    targets = _s6_repair_targets(result, issues)
    assert 1 <= len(targets) <= 4
    assert _s6_can_use_lightweight_card_repair(result, issues) is True


def test_middle_loop_ignores_stale_s6_failure_after_repair_passes() -> None:
    trace = [
        {"loop": "inner", "step": 6, "iteration": 1, "passed": False,
         "event": "lightweight_card_repair_planned", "issues": ["标题不具体"]},
        {"loop": "inner", "step": 6, "iteration": 1, "passed": False,
         "issues": ["现役升级对象不明确"]},
        {"loop": "inner", "step": 6, "iteration": 2, "passed": True,
         "issues": []},
    ]

    assert _latest_inner_loop_failures(trace) == []


def test_s6_handoff_drops_upstream_solution_names_and_upgrade_packages() -> None:
    handoff = _capability_synthesis_handoff(
        topic="西太反介入装备能力缺口",
        branch="B",
        prior_step_outputs={
            "effect_chain": ["强干扰压缩目标发现窗口并削弱火力分配与拦截反制"],
            "gap_assessment": [
                {
                    "capability": "抗饱和拦截",
                    "grade": "关键差距",
                    "gap_statement": "现役火控在多轴突防下削弱拦截与再打击效果",
                    "current_upgrade": "抗毁C2/ISR边缘闭环升级包",
                    "new_development": "通信保障套件",
                    "verification": "强干扰多目标闭环对抗试验",
                    "evidence_refs": ["ev-1"],
                }
            ],
            "s4_concept_directions": [
                {"name": "抗毁C2/ISR边缘闭环升级包"}
            ],
        },
        evidence_index=[],
    )

    serialized = str(handoff)
    assert "抗毁C2/ISR边缘闭环升级包" not in serialized
    assert "通信保障套件" not in serialized
    assert "抗饱和拦截" in serialized
    assert "火力分配" in serialized


def test_delivery_deadline_is_always_capped_at_forty_minutes() -> None:
    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    provider.configure_run_budget(
        {
            "hard_deadline_seconds": 1700,
            "delivery_grace_seconds": 600,
            "absolute_deadline_seconds": 3600,
            "maximum_delivery_model_calls": 2,
        }
    )
    provider._run_started_at -= 2401

    with pytest.raises(RuntimeError, match="delivery deadline"):
        provider._reserve_model_call(priority="delivery")


def test_report_generation_uses_delivery_priority() -> None:
    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    priorities: list[str] = []

    async def fake_collect_stream(*args, priority="normal", **kwargs):
        del args, kwargs
        priorities.append(priority)
        return "# report", {}

    provider._collect_stream = fake_collect_stream  # type: ignore[method-assign]
    result = asyncio.run(
        provider._run_core_text(
            "reporter",
            "write",
            {"topic": "test"},
            100,
            phase="report_generation",
        )
    )

    assert result == "# report"
    assert priorities == ["delivery"]


def test_report_generation_core_path_cannot_be_degraded_by_fast_profile(
    monkeypatch,
) -> None:
    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    captured_options: dict[str, object] = {}

    async def capture_collect_stream(provider_backend, messages, options, **kwargs):
        del provider_backend, messages, kwargs
        captured_options.update(options)
        return "# report", {}

    monkeypatch.setenv("EQUIPMENT_DR_CODEX_PERFORMANCE_PROFILE", "fast")
    provider.provider_kind = "codex_cli"
    provider._collect_stream = capture_collect_stream  # type: ignore[method-assign]

    result = asyncio.run(
        provider._run_core_text(
            "reporter",
            "write",
            {"topic": "test"},
            100,
            phase="report_generation_fast_finalize",
        )
    )

    assert result == "# report"
    assert captured_options["reasoning_effort"] == "xhigh"
    assert captured_options["max_output_tokens"] == 12000
    assert captured_options["model_verbosity"] == "medium"
    assert captured_options["_no_deadline_degrade"] is True


@pytest.mark.parametrize(
    "phase",
    [
        "report_generation_fast_finalize",
        "report_generation_timeout_retry",
        "report_generation_repair",
    ],
)
def test_reporter_provider_call_is_always_xhigh_12000(
    phase,
    monkeypatch,
) -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text="# report"))]]
    )
    provider = ResponsesAgentProvider(backend)
    provider.provider_kind = "codex_cli"
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_PERFORMANCE_PROFILE", "fast")

    result = asyncio.run(
        provider._run_reporter_text(
            "write",
            {"query": "test"},
            2000,
            phase=phase,
        )
    )

    assert result == "# report"
    _, _, options = backend.inputs[0]
    assert options["reasoning_effort"] == "xhigh"
    assert options["max_output_tokens"] == 12000
    assert options["model_verbosity"] == "medium"


def test_reporter_blocks_repaired_model_draft_with_structural_gaps() -> None:
    structural_draft = (
        "### 综合判断\n"
        "需求卡片、推理链与证据链共同说明：现役升级应优先增强抗毁和持续作战能力，"
        "并以新装备补足反制、拒止与威慑闭环。因此若对手改变压制方式，否则任务链将失速；"
        "建设优先序、体系接口和验证路线必须绑定未来触发条件、失效边界与可证伪验证口径。\n"
        + "跨材料因果综合支持装备决策与军事任务效果。" * 180
    )
    payload = {
        "topic": "传统能力缺口",
        "branch_writer_brief": {
            "branch": "B",
            "required_sections": [],
            "target_chars": "2400-5000",
            "hard_max_chars": 7200,
        },
    }
    issues = _report_draft_quality_issues(structural_draft, payload)
    assert any("缺少固定二级章节" in item for item in issues)
    assert any("缺少固定三级项" in item for item in issues)
    assert any("三层九项中装备能力特征" in item for item in issues)
    assert _report_issues_require_fallback(issues) is True


def test_b_branch_accepts_public_source_language_as_evidence_chain() -> None:
    text = (
        "### 核心判断\n"
        "需求卡片、能力全景图与因果链形成完整回溯路径。公开来源支撑事实判断，"
        "并说明任务效果、功能、性能约束、体系接口、装备形态和验证指标。"
        "打击、反制、拒止、威慑和抗毁价值均落实到任务阶段；因此若条件变化，"
        "则依据失效边界和验证路径调整。"
        + "跨场景通用需求、条件性需求、特定场景需求及反证假设。" * 160
    )
    payload = {
        "branch_writer_brief": {
            "branch": "B",
            "required_sections": [],
            "target_chars": "2400-5000",
            "hard_max_chars": 7200,
        }
    }

    issues = _report_draft_quality_issues(text, payload)

    assert not any("证据链" in issue for issue in issues)


def test_report_length_overrun_is_not_emitted_as_a_draft_issue() -> None:
    text = _three_layer_report(detail_count=160)
    payload = {
        "branch_writer_brief": {
            "branch": "B",
            "required_sections": [],
            "target_chars": "2400-5000",
            "hard_max_chars": 3000,
        }
    }

    assert len(text) > 3000
    assert not any(
        "超过交付硬上限" in issue
        for issue in _report_draft_quality_issues(text, payload)
    )


def test_parallel_legacy_heading_structure_blocks_report_delivery() -> None:
    issues = [
        "报告格式不应输出一级标题，标题由交付层统一添加",
        "报告格式固定二级标题不得添加数字序号",
        "报告格式存在契约外二级标题：研究背景",
    ]

    assert _report_issues_require_fallback(issues) is True


def test_complete_branch_products_do_not_replace_three_layer_report_contract() -> None:
    text = (
        "## 核心判断\n公开事实与分析推断。\n"
        "## 因果机理与任务链\n因此若链路中断，否则打击、反制、拒止、威慑和抗毁能力下降。\n"
        "## 分支规定成果\n六条案例规律、三类未来场景、四类装备方向均已展开。\n"
        "## 能力需求与装备发展\n任务效果、功能、性能约束、体系接口、装备形态、现役升级、新装备与验证指标。\n"
        "## 跨场景适用性\n通用需求、条件性需求和特定场景需求。\n"
        "## 不确定性、验证与证据边界\n关键假设、反证、触发条件、失效边界与验证路径。\n"
        + "跨案例机制分析支撑持续作战和装备建设优先序。" * 180
    )
    payload = {
        "execution_profile_id": "optimized_v2",
        "branch_writer_brief": {
            "branch": "C",
            "required_sections": [],
            "target_chars": "2700-6000",
            "hard_max_chars": 10000,
        },
        "branch_deliverables": {
            "delivery_status": "complete",
            "products": {
                "case_patterns": [f"规律{i}" for i in range(6)],
                "future_scenarios": [f"场景{i}" for i in range(3)],
                "emerging_equipment_categories": [f"装备{i}" for i in range(4)],
            },
        },
    }

    issues = _report_draft_quality_issues(text, payload)
    assert any("缺少固定二级章节" in item for item in issues)
    assert any("缺少固定三级项" in item for item in issues)
    assert _report_issues_require_fallback(issues) is True


def test_c_branch_accepts_semantic_transfer_boundary_language() -> None:
    text = (
        "## 核心判断\n公开事实与分析推断。\n"
        "## 因果机理与任务链\n因此若链路中断，否则打击、反制、拒止、威慑和抗毁能力下降。\n"
        "## 分支规定成果\n核心规律1、核心规律2、核心规律3、核心规律4、核心规律5、核心规律6；"
        "高置信场景1、高置信场景2、高置信场景3；"
        "新兴装备类别1、新兴装备类别2、新兴装备类别3、新兴装备类别4。\n"
        "## 能力需求与装备发展\n任务效果、功能、性能约束、体系接口、装备形态、现役升级、新装备与验证指标。\n"
        "## 跨场景适用性\n结论只迁移任务机制，不照搬参数；地形、制空与联合作战成熟度是失效条件。\n"
        "## 不确定性、验证与证据边界\n关键假设、反证、触发条件与验证路径。\n"
        + "跨案例机制分析支撑持续作战和装备建设优先序。" * 180
    )
    payload = {
        "execution_profile_id": "optimized_v2",
        "branch_writer_brief": {
            "branch": "C",
            "required_sections": [],
            "target_chars": "2700-6000",
            "hard_max_chars": 10000,
        },
    }

    issues = _report_draft_quality_issues(text, payload)

    assert not any("迁移的适用与失效边界" in item for item in issues)


def test_delivery_gate_value_error_delivers_limited_without_whole_report_retry(
    monkeypatch,
) -> None:
    backend = ScriptedFakeProvider(
        [
            [ProviderStreamEvent.final(ProviderFinalTurn(text="初稿"))],
            [ProviderStreamEvent.final(ProviderFinalTurn(text="修复稿"))],
            [ProviderStreamEvent.final(ProviderFinalTurn(text="不应执行的重试稿"))],
        ]
    )
    provider = ResponsesAgentProvider(backend)
    monkeypatch.setattr(
        "equipment_deep_research.agents.provider._report_draft_quality_issues",
        lambda text, payload: ["缺少核心规律连续编号：[1]"],
    )

    result = provider.draft_report(
        {
            "topic": "案例经验",
            "branch_writer_brief": {"branch": "C"},
        }
    )

    assert len(backend.inputs) == 1
    assert "## 第一层：需求挖掘层" in result
    assert "### ⑨ 发展优先级与近期抓手" in result


def test_optimized_v2_delivers_reviewable_fallback_without_repair_when_branch_is_complete(
    monkeypatch,
) -> None:
    body = (
        "## 核心判断\n结论。\n"
        "## 因果机理与任务链\n因此若受压则影响打击、反制、拒止、威慑与抗毁。\n"
        "## 分支规定成果\n总体成果。\n"
        "## 能力需求与装备发展\n现役升级、新装备、体系接口与验证指标。\n"
        "## 跨场景适用性\n通用需求、条件性需求和特定场景需求。\n"
        "## 不确定性、验证与证据边界\n假设、反证、触发条件和失效边界。\n"
        + "独立模型形成可审阅的深度研究正文。" * 100
    )
    backend = ScriptedFakeProvider(
        [
            [ProviderStreamEvent.final(ProviderFinalTurn(text=body))],
            [ProviderStreamEvent.final(ProviderFinalTurn(text=body + "修复。"))],
        ]
    )
    provider = ResponsesAgentProvider(backend)
    monkeypatch.setattr(
        "equipment_deep_research.agents.provider._report_draft_quality_issues",
        lambda text, payload: ["仍有非致命报告质检项"],
    )

    result = provider.draft_report(
        {
            "topic": "案例经验",
            "execution_profile_id": "optimized_v2",
            "branch_writer_brief": {"branch": "C"},
            "branch_deliverables": {
                "delivery_status": "complete",
                "products": {},
            },
        }
    )

    assert "## 第一层：需求挖掘层" in result
    assert "### ⑨ 发展优先级与近期抓手" in result
    assert len(backend.inputs) == 1


def test_fast_codex_profile_caps_reasoning_tokens_and_search_context(
    monkeypatch,
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_PERFORMANCE_PROFILE", "fast")

    options = _apply_codex_performance_options(
        {
            "reasoning_effort": "high",
            "model_verbosity": "medium",
            "max_output_tokens": 7000,
            "web_search": {"search_context_size": "high"},
        },
        "codex_cli",
    )

    assert options["reasoning_effort"] == "medium"
    assert options["model_verbosity"] == "low"
    assert options["max_output_tokens"] == 2800
    assert options["web_search"]["search_context_size"] == "low"


def test_responses_adapter_returns_structured_packet_without_model_claimed_evidence() -> None:
    backend = ScriptedFakeProvider([
        [ProviderStreamEvent.final(ProviderFinalTurn(text="未发现可核验来源"))],
        [ProviderStreamEvent.final(ProviderFinalTurn(text='{"findings":["威胁态势上升"],"confidence":0.72,"open_questions":["补充公开证据"],"handoff_summary":"完成初步研判"}'))],
    ])
    agent = AgentDef("a", "国际形势", "", ["threat"], [], {})
    result = ResponsesAgentProvider(backend).run_baseline_agent(AgentRunRequest("r", agent, "topic", "new_winning_mechanism", {}))
    assert result.packet.findings == ["威胁态势上升"]
    assert result.packet.evidence_ids == []
    assert result.packet.confidence == 0.72
    assert backend.inputs[0][1] == ()


def test_responses_provider_uses_model_to_analyze_and_select_agents() -> None:
    backend = ScriptedFakeProvider(
        [[
            ProviderStreamEvent.final(
                ProviderFinalTurn(
                    text=(
                        '{"task_analysis":["任务聚焦装备差距和运用，不需要国际态势"],'
                        '"selected_agent_ids":["weapon_equipment","operational_employment"],'
                        '"rationale":"选择装备与运用专业Agent",'
                        '"dependency_notes":["两者可先独立研究后汇总"]}'
                    )
                )
            )
        ]]
    )
    result = ResponsesAgentProvider(backend).select_agents(
        AgentSelectionRequest(
            topic="现有装备参数差距与运用升级",
            research_route="traditional_gap",
            required_capability_tags=["equipment", "operation"],
            candidates=[
                {"agent_id": "international_situation", "capability_tags": ["situation"]},
                {"agent_id": "weapon_equipment", "capability_tags": ["equipment"]},
                {"agent_id": "operational_employment", "capability_tags": ["operation"]},
            ],
        )
    )
    assert result.model_used is True
    assert result.selected_agent_ids == ["weapon_equipment", "operational_employment"]
    assert "不需要国际态势" in result.task_analysis[0]


def test_responses_adapter_turns_only_provider_reported_web_sources_into_leads() -> None:
    backend = ScriptedFakeProvider(
        [[
            ProviderStreamEvent.final(
                ProviderFinalTurn(
                    text="公开报告：低空目标探测窗口缩短",
                    metadata={
                        "search_queries": ["低空目标 探测窗口"],
                        "web_sources": [
                            {"url": "https://example.org/report", "title": "公开报告", "snippet": "摘要"}
                        ],
                    },
                )
            )
        ], [
            ProviderStreamEvent.final(ProviderFinalTurn(
                text=(
                    '{"findings":["低空目标探测窗口缩短"],"confidence":0.76,'
                    '"open_questions":[],"handoff_summary":"完成联网研判",'
                    '"source_claims":[{"url":"https://example.org/report",'
                    '"claim":"公开报告显示探测窗口缩短"}]}'
                )
            ))
        ]]
    )
    agent = AgentDef("a", "国际形势", "", ["threat"], [], {})
    result = ResponsesAgentProvider(backend).run_baseline_agent(
        AgentRunRequest("r", agent, "topic", "new_winning_mechanism", {})
    )
    assert len(result.evidence) == 1
    assert result.evidence[0].source_url == "https://example.org/report"
    assert result.evidence[0].claim == "公开报告显示探测窗口缩短"
    assert result.evidence[0].quality_assessment == "responses_web_search_source"
    assert result.packet.evidence_ids == [result.evidence[0].evidence_id]
    assert result.packet.search_log == ["低空目标 探测窗口"]
    assert backend.inputs[0][2]["web_search"]["search_context_size"] == "high"


def test_responses_adapter_uses_source_claims_as_materialization_leads_when_gateway_omits_annotations() -> None:
    backend = ScriptedFakeProvider(
        [
            [ProviderStreamEvent.final(ProviderFinalTurn(
                text="发现公开资料：https://example.org/public-report",
                metadata={"search_queries": ["公开资料检索"], "web_sources": []},
            ))],
            [ProviderStreamEvent.final(ProviderFinalTurn(text=(
                '{"findings":["公开资料判断"],"confidence":0.74,'
                '"open_questions":[],"handoff_summary":"完成检索",'
                '"source_claims":[{"url":"https://example.org/public-report",'
                '"claim":"待材料化公开来源"}]}'
            )))],
        ]
    )
    agent = AgentDef("a", "国际形势", "", ["threat"], [], {})
    result = ResponsesAgentProvider(backend).run_baseline_agent(
        AgentRunRequest("r", agent, "topic", "new_winning_mechanism", {})
    )
    assert len(result.evidence) == 1
    assert result.evidence[0].source_url == "https://example.org/public-report"
    assert result.evidence[0].quality_assessment == "responses_web_search_lead"
    assert result.packet.search_log == ["公开资料检索"]


def test_codex_adapter_promotes_structured_claim_when_gateway_omits_annotations() -> None:
    class CodexScriptedProvider(ScriptedFakeProvider):
        def snapshot(self) -> dict[str, str]:
            return {"type": "codex_cli", "model": self.model, "base_url_host": ""}

    backend = CodexScriptedProvider(
        [
            [ProviderStreamEvent.final(ProviderFinalTurn(
                text="发现公开资料：https://www.defense.gov/News/report",
                metadata={"search_queries": ["公开资料检索"], "web_sources": []},
            ))],
            [ProviderStreamEvent.final(ProviderFinalTurn(text=(
                '{"findings":["公开资料判断"],"confidence":0.74,'
                '"open_questions":[],"handoff_summary":"完成检索",'
                '"source_claims":[{"url":"https://www.defense.gov/News/report",'
                '"claim":"官方公开来源支撑该判断"}]}'
            )))],
        ]
    )
    agent = AgentDef("a", "国际形势", "", ["threat"], [], {})

    result = ResponsesAgentProvider(backend).run_baseline_agent(
        AgentRunRequest("r", agent, "topic", "new_winning_mechanism", {})
    )

    assert len(result.evidence) == 1
    assert result.evidence[0].quality_assessment == "codex_web_search_source"
    assert result.evidence[0].source_title == "defense.gov"


def test_light_baseline_search_combines_known_and_open_tracks_in_one_lane(
    monkeypatch,
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_DISCOVERY_MAX_BATCHES", "2")
    backend = ScriptedFakeProvider(
        [
            [ProviderStreamEvent.final(ProviderFinalTurn(
                text="hybrid discovery",
                metadata={
                    "web_sources": [
                        {
                            "url": "https://example.org/report",
                            "title": "Report",
                            "snippet": "Public evidence summary",
                        }
                    ]
                },
            ))],
            [ProviderStreamEvent.final(ProviderFinalTurn(text=(
                '{"findings":["形成轻量完整研判"],"confidence":0.75,'
                '"open_questions":[],"handoff_summary":"完成",'
                '"source_claims":[{"url":"https://example.org/report",'
                '"claim":"公开来源支撑判断"}]}'
            )))],
        ]
    )
    agent = AgentDef(
        "operational_employment",
        "作战运用",
        "",
        ["operation"],
        [],
        {},
        research_policy={
            "search_tracks": ["条令", "演习", "战法"],
            "target_source_count": 8,
        },
    )

    result = ResponsesAgentProvider(backend).run_baseline_agent(
        AgentRunRequest(
            "run-light",
            agent,
            "topic",
            "new_winning_mechanism",
            {
                "_search_intensity": "light",
                "source_priorities": [{"url": "https://example.org/known"}],
            },
        )
    )

    assert result.packet.findings == ["形成轻量完整研判"]
    assert len(backend.inputs) == 2
    discovery_input = backend.inputs[0][0][1].content["task_input"]
    assert discovery_input["retrieval_lane"] == "hybrid_web"
    assert list(discovery_input["known_urls"]) == ["https://example.org/known"]
    assert backend.inputs[1][2]["reasoning_effort"] == "high"
    assert backend.inputs[1][2]["max_output_tokens"] == 4200


def test_optimized_v2_forces_one_hybrid_discovery_lane() -> None:
    backend = ScriptedFakeProvider(
        [
            [ProviderStreamEvent.final(ProviderFinalTurn(
                text="hybrid discovery",
                metadata={
                    "web_sources": [
                        {
                            "url": "https://example.org/official",
                            "title": "Official",
                            "snippet": "Public evidence",
                        }
                    ]
                },
            ))],
            [ProviderStreamEvent.final(ProviderFinalTurn(text=(
                '{"findings":["形成高密度研判"],"confidence":0.8,'
                '"open_questions":[],"handoff_summary":"完成",'
                '"source_claims":[{"url":"https://example.org/official",'
                '"claim":"公开来源支撑判断"}]}'
            )))],
        ]
    )
    agent = AgentDef(
        "international_situation",
        "国际形势",
        "",
        ["threat"],
        [],
        {},
        research_policy={
            "search_tracks": ["联盟", "部署", "装备"],
            "target_source_count": 8,
        },
    )

    result = ResponsesAgentProvider(backend).run_baseline_agent(
        AgentRunRequest(
            "run-optimized",
            agent,
            "topic",
            "traditional_gap",
            {
                "_search_intensity": "deep",
                "source_priorities": [{"url": "https://example.org/known"}],
                "discovery_blueprint": {
                    "execution_profile_id": "optimized_v2",
                    "primary_branch": "B",
                },
            },
        )
    )

    assert result.packet.findings == ["形成高密度研判"]
    assert len(backend.inputs) == 2
    discovery_input = backend.inputs[0][0][1].content["task_input"]
    assert discovery_input["retrieval_lane"] == "hybrid_web"
    assert discovery_input["search_batch_count"] == 1


def test_optimized_v2_winning_timeout_returns_deterministic_fallback(monkeypatch) -> None:
    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    provider.provider_kind = "codex_cli"

    async def timeout(_payload):
        raise TimeoutError()

    monkeypatch.setattr(provider, "_analyze_winning_subagents", timeout)

    assert provider.analyze_winning_mechanism(
        {"discovery_blueprint": {"execution_profile_id": "optimized_v2"}}
    ) == {}


def test_equipment_typed_payload_normalizes_missing_parameter_context() -> None:
    _, payload, version = _typed_packet_payload(
        "weapon_equipment",
        {
            "equipment_profiles": [{"model": "MQ-test"}],
            "current_parameters": ["range"],
            "parameter_observations": [{"parameter": "range", "value": 100}],
            "parameter_conflicts": ["none reported"],
            "development_models": ["prototype"],
            "technology_readiness": ["demonstrated"],
            "capability_constraints": ["weather"],
            "scenario_fit": ["maritime"],
            "capability_gaps": ["resilience"],
        },
    )

    observation = payload["parameter_observations"][0]
    assert version == "2.0"
    assert observation["unit"] == "未披露"
    assert observation["variant"] == "公开来源未注明批次"
    assert observation["condition"] == "公开来源条件"
    assert observation["confidence"] == 0.5


def test_operational_typed_payload_normalizes_three_required_coa_variants() -> None:
    _, payload, version = _typed_packet_payload(
        "operational_employment",
        {
            "operational_constraints": ["constraint"],
            "mission_chain": ["detect", "decide", "act"],
            "force_coordination": ["joint"],
            "coa": ["model returned an unkeyed COA comparison"],
            "sustainment_resilience": ["supply"],
            "failure_modes": ["link loss"],
            "lessons": ["lesson"],
            "equipment_function_requirements": ["requirement"],
        },
    )

    assert version == "2.0"
    assert {"baseline", "distributed", "resource_constrained"} <= set(payload["coa"])


def test_responses_provider_routes_orchestrator_baseline_and_winning_to_distinct_models() -> None:
    default = ScriptedFakeProvider([])
    orchestrator = ScriptedFakeProvider([[ProviderStreamEvent.final(ProviderFinalTurn(
        text='{"selected_agent_ids":["a"],"rationale":"ok","task_analysis":[],"dependency_notes":[]}'
    ))]])
    baseline = ScriptedFakeProvider([
        [ProviderStreamEvent.final(ProviderFinalTurn(text="discovery"))],
        [ProviderStreamEvent.final(ProviderFinalTurn(
            text='{"findings":["baseline"],"confidence":0.8,"open_questions":[],"handoff_summary":"done"}'
        ))],
    ])
    winning = ScriptedFakeProvider([[ProviderStreamEvent.final(ProviderFinalTurn(
        text='{"defense_decomposition":["d"],"winning_paths":["p"],"effect_chain":["e"],"capability_mapping":["m"],"gap_assessment":[],"concept_directions":[],"assumptions":[],"open_questions":[],"confidence":0.8}'
    ))]])
    provider = ResponsesAgentProvider(default, agent_providers={
        "orchestrator": orchestrator,
        "a": baseline,
        "winning_mechanism": winning,
    })
    provider.select_agents(AgentSelectionRequest("topic", "traditional_gap", ["equipment"], [{"agent_id":"a","capability_tags":["equipment"]}]))
    provider.run_baseline_agent(AgentRunRequest("r", AgentDef("a", "A", "", ["equipment"], [], {}), "topic", "traditional_gap", {}))
    advice = provider.analyze_winning_mechanism({"topic":"topic"})
    assert advice["confidence"] == 0.8
    assert len(orchestrator.inputs) == len(winning.inputs) == 1
    assert len(baseline.inputs) == 2
    assert default.inputs == []


def test_explicit_responses_provider_requires_credential(tmp_path: Path, monkeypatch) -> None:
    root = Path(__file__).parents[3]
    monkeypatch.delenv("EQUIPMENT_DR_API_KEY", raising=False)
    runner = DeepResearchRunner(project_root=root, output_root=tmp_path, agent_config_path=root / "configs/equipment_deep_research/agents.yaml", preset_config_path=root / "configs/equipment_deep_research/presets.yaml")
    try:
        runner._select_agent_provider("real", "responses")
    except ValueError as error:
        assert "EQUIPMENT_DR_API_KEY" in str(error)
    else:
        raise AssertionError("credential configuration must be required")


def test_real_mode_defaults_to_codex_without_responses_credentials(tmp_path: Path, monkeypatch) -> None:
    root = Path(__file__).parents[3]
    monkeypatch.delenv("EQUIPMENT_DR_API_KEY", raising=False)
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_BASE_URL", "https://codex.example.test/v1")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_API_KEY_ENV", "PROJECT_CODEX_KEY")
    monkeypatch.setenv("PROJECT_CODEX_KEY", "test-project-key")
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    runner = DeepResearchRunner(
        project_root=root,
        output_root=tmp_path,
        agent_config_path=root / "configs/equipment_deep_research/agents.yaml",
        preset_config_path=root / "configs/equipment_deep_research/presets.yaml",
    )
    provider = runner._select_agent_provider("real", None)
    assert provider.provider_kind == "codex_cli"
    assert provider._provider_for("reporter").snapshot()["type"] == "codex_cli"


def test_dynamic_swarm_provider_factory_isolates_and_caches_each_instance(
    monkeypatch,
) -> None:
    monkeypatch.delenv("EQUIPMENT_DR_CODEX_BASE_URL", raising=False)
    monkeypatch.delenv("EQUIPMENT_DR_CODEX_API_KEY_ENV", raising=False)
    created: list[str] = []

    class Provider:
        def __init__(self, isolation_id: str = "orchestrator-default") -> None:
            self.isolation_id = isolation_id

        def snapshot(self) -> dict[str, str]:
            return {
                "type": "codex_cli",
                "context_isolation": self.isolation_id,
            }

        def isolated_copy(self, isolation_id: str) -> "Provider":
            created.append(isolation_id)
            return Provider(isolation_id)

    provider = ResponsesAgentProvider(Provider())  # type: ignore[arg-type]

    first = provider._provider_for(
        "winning_swarm_evidence_verifier",
        isolation_id="specialist-1",
    )
    repeated = provider._provider_for(
        "winning_swarm_evidence_verifier",
        isolation_id="specialist-1",
    )
    second = provider._provider_for(
        "winning_swarm_evidence_verifier",
        isolation_id="specialist-2",
    )

    assert first is repeated
    assert first is not second
    assert first.snapshot()["context_isolation"] == "specialist-1"
    assert second.snapshot()["context_isolation"] == "specialist-2"
    assert created == ["specialist-1", "specialist-2"]


def test_real_mode_routes_reporter_to_custom_codex_even_with_responses_baseline(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = Path(__file__).parents[3]
    monkeypatch.setenv("EQUIPMENT_DR_API_KEY", "responses-key")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_BASE_URL", "https://codex.example.test/v1")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_API_KEY_ENV", "PROJECT_CODEX_KEY")
    monkeypatch.setenv("PROJECT_CODEX_KEY", "codex-key")
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    runner = DeepResearchRunner(
        project_root=root,
        output_root=tmp_path,
        agent_config_path=root / "configs/equipment_deep_research/agents.yaml",
        preset_config_path=root / "configs/equipment_deep_research/presets.yaml",
    )

    provider = runner._select_agent_provider("real", "responses")

    assert provider.provider_kind == "responses"
    assert provider._provider_for("reporter").snapshot()["type"] == "codex_cli"


def test_real_mode_rejects_non_codex_reporter_override(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = Path(__file__).parents[3]
    monkeypatch.setenv("EQUIPMENT_DR_API_KEY", "responses-key")
    runner = DeepResearchRunner(
        project_root=root,
        output_root=tmp_path,
        agent_config_path=root / "configs/equipment_deep_research/agents.yaml",
        preset_config_path=root / "configs/equipment_deep_research/presets.yaml",
    )

    with pytest.raises(ValueError, match="reporter must use Codex CLI"):
        runner._select_agent_provider(
            "real",
            "responses",
            agent_model_profiles={
                "reporter": {
                    "provider": "responses",
                    "model": "gpt-test",
                }
            },
        )


def test_every_configured_agent_has_a_nonempty_codex_runtime_profile() -> None:
    root = Path(__file__).parents[3]
    registry = AgentRegistry.load(root / "configs/equipment_deep_research/agents.yaml")
    for agent_id in registry.all_agent_ids():
        agent = registry.get(agent_id)
        runtime = build_codex_runtime_profile(agent_id, agent=agent)
        assert runtime["skills"], agent_id
        assert runtime["tools"], agent_id
        assert runtime["methodology"], agent_id
        assert runtime["quality_gates"], agent_id
        assert runtime["military_mission_lens"], agent_id
        assert any(
            marker in runtime["military_mission_lens"]
            for marker in (
                "打击",
                "歼灭",
                "反制",
                "拒止",
                "威慑",
                "抗毁",
                "持续作战",
                "军事任务",
            )
        ), agent_id
        assert runtime["safety_boundary"], agent_id
    assert set(CODEX_AGENT_RUNTIME_PROFILES) <= set(registry.all_agent_ids()) | {
        "orchestrator"
    }


@pytest.mark.parametrize(
    ("archetype", "spec"),
    list(SWARM_SPECIALIST_ARCHETYPES.items()),
)
def test_winning_swarm_runtime_profile_adapts_each_recruited_role(
    archetype: str,
    spec: dict,
) -> None:
    agent_id = f"winning_swarm_{archetype}"
    payload = {
        "input": {
            "execution_profile_id": "swarm_quality_v1",
            "specialist_task": {
                "task_id": f"task-{archetype}",
                "agent_instance_id": f"instance-{archetype}",
                "archetype": archetype,
                "display_name": spec["display_name"],
                "purpose": spec["purpose"],
                "wave": 2,
                "hypothesis_id": "hypothesis-1",
                "merge_target": spec["merge_target"],
                "trigger_residuals": list(spec["residuals"]),
                "expected_quality_gain": 0.05,
                "allow_child_spawn": False,
            },
        }
    }

    runtime = build_codex_runtime_profile(
        agent_id,
        payload=payload,
        phase="winning_swarm_targeted",
        compact=True,
    )

    assert runtime["runtime_profile_id"] == agent_id
    assert runtime["role"] == spec["purpose"]
    assert runtime["swarm_role_contract"]["display_name"] == spec["display_name"]
    assert runtime["swarm_role_contract"]["merge_target"] == spec["merge_target"]
    assert runtime["swarm_role_contract"]["allow_child_spawn"] is False
    assert runtime["swarm_assignment"]["hypothesis_id"] == "hypothesis-1"
    assert runtime["swarm_assignment"]["trigger_residuals"] == list(
        spec["residuals"]
    )
    assert runtime["active_dynamic_skill_ids"] == [
        "js-equipment-agent-runtime",
        "js-winning-shared-layer",
    ]
    assert "不得招募子 Agent" in "；".join(runtime["quality_gates"])
    assert "军事" in runtime["military_mission_lens"] or "打击" in runtime[
        "military_mission_lens"
    ]


def test_optimized_v2_runtime_is_minimal_and_role_specific() -> None:
    root = Path(__file__).parents[3]
    registry = AgentRegistry.load(root / "configs/equipment_deep_research/agents.yaml")
    payload = {
        "execution_profile_id": "optimized_v2",
        "discovery_blueprint": {
            "execution_profile_id": "optimized_v2",
            "primary_branch": "B",
            "emphasis": ["S4", "S5"],
        },
    }

    for agent_id in registry.all_agent_ids():
        runtime = build_codex_runtime_profile(
            agent_id,
            agent=registry.get(agent_id),
            payload=payload,
            phase="evidence_analysis",
            compact=True,
        )
        assert runtime["military_mission_lens"], agent_id
        assert "skill" in runtime and "skills" not in runtime, agent_id
        assert len(runtime["tools"]) <= 2, agent_id
        assert "harness" not in runtime, agent_id
        assert "research_policy" not in runtime, agent_id
        assert "knowledge_packs" not in runtime, agent_id
        if agent_id in {
            "international_situation",
            "combat_scenario",
            "weapon_equipment",
            "operational_employment",
            "case_research",
            "technology_radar",
            "opponent_monitoring",
            "system_confrontation",
            "cross_domain_fusion",
            "nontraditional_security",
        }:
            assert runtime["analysis_anchor"] == "query_dominant_military_divergence"
            assert "本Agent专业角色与方法第一" in runtime["query_dominance_rule"]
            assert "不得决定议题" in runtime["query_dominance_rule"]


def test_optimized_v2_winning_call_uses_short_military_runtime() -> None:
    backend = ScriptedFakeProvider([])
    backend.snapshot = lambda: {"type": "codex_cli"}  # type: ignore[attr-defined]
    provider = ResponsesAgentProvider(backend)
    messages = provider._runtime_messages(
        "winning_s2_operations",
        "只输出严格JSON。",
        {
            "execution_profile_id": "optimized_v2",
            "discovery_blueprint": {
                "execution_profile_id": "optimized_v2",
                "primary_branch": "A",
            },
        },
        phase="winning_s2_operations",
    )

    system_prompt = str(messages[0].content)
    runtime = messages[1].content["agent_runtime"]
    assert "$js-equipment-agent-runtime" not in system_prompt
    assert "$js-winning-shared-layer" not in system_prompt
    assert "agent_runtime.military_mission_lens" in system_prompt
    assert "打击/歼灭闭环" in runtime["military_mission_lens"]
    assert "skill" in runtime and "skills" not in runtime
    assert len(runtime["tools"]) <= 2


def test_reporter_call_uses_plain_isolated_context() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text="完成摘要"))]]
    )
    provider = ResponsesAgentProvider(backend)
    result = provider.draft_report(
        {
            "topic": "体系韧性",
            "discovery_blueprint": {
                "primary_branch": "F",
                "secondary_branches": ["B"],
                "runtime_route": "traditional_gap",
                "emphasis": ["体系仿真", "S3", "S4", "S5", "S6"],
            },
        }
    )
    assert result == "完成摘要"
    messages, _, options = backend.inputs[0]
    user_payload = messages[1].content
    assert "agent_runtime" not in user_payload
    assert user_payload["query"] == "体系韧性"
    assert set(user_payload) == {
        "query",
        "branch",
        "target_length",
        "length_policy",
        "first_pass_quality_contract",
        "branch_hard_requirements",
        "format_contract",
        "reporter_contract",
        "research_handoff",
        "report_ready_section_map",
        "public_sources",
    }
    assert "high_value_clues" not in user_payload
    assert user_payload["target_length"] == "9000-10000字核心正文"
    assert "立即收尾" in user_payload["length_policy"]["stop_when"]
    assert "12000字" in user_payload["length_policy"]["delivery_target"]
    assert "不得触发重写" in user_payload["length_policy"]["overrun"]
    first_pass = user_payload["first_pass_quality_contract"]
    assert first_pass["goal"] == "single_pass_delivery_without_quality_repair"
    assert any("优先序" in item for item in first_pass["pre_submission_checks"])
    assert any("3至10年" in item for item in first_pass["pre_submission_checks"])
    assert list(user_payload["format_contract"]["h2"]) == [
        "第一层：需求挖掘层——场景·战法/技术·装备能力特征",
        "第二层：技术攻关层——能力实现途径与核心技术",
        "第三层：能力图像与效能贡献层",
    ]
    assert list(user_payload["format_contract"]["h3"]) == [
        "① 典型作战场景",
        "② 新战法或新概念技术及制胜机理",
        "③ 装备能力特征清单",
        "④ 能力实现途径",
        "⑤ 核心技术清单与攻关优先级",
        "⑥ 技术耦合与短板风险",
        "⑦ 装备能力图像",
        "⑧ 效能贡献评估",
        "⑨ 发展优先级与近期抓手",
    ]
    assert "Harness" not in str(messages[0].content)
    assert "Skill" not in str(messages[0].content)
    assert options["prompt_mode"] == "standalone"


def test_reporter_timeout_retries_once_without_quality_downshift(monkeypatch) -> None:
    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    attempts: list[dict] = []

    def fake_attempt(payload, **kwargs):
        del payload
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise ProviderRequestError("Codex CLI timed out after 600 seconds")
        return "独立重写完成"

    monkeypatch.setattr(provider, "_draft_report_attempt", fake_attempt)
    result = provider.draft_report(
        {
            "topic": "体系韧性",
            "report_context": {"primary_branch": "B"},
            "branch_writer_brief": {
                "branch": "B",
                "required_sections": ["需求卡片", "能力全景图"],
                "mandatory_content": ["现役基线与五档差距"],
                "target_chars": "2800-5000",
                "hard_max_chars": 7200,
            },
            "synthesis_seed": {
                "decisive_anchors": ["判断一", "判断二"],
                "mission_chain_breaks": ["断点一", "断点二"],
                "counterevidence_and_limits": ["反证一", "反证二"],
                "priority_signals": ["信号一", "信号二"],
                "capability_cues": [
                    {"direction": f"方向{index}", "mission_effect": f"效果{index}"}
                    for index in range(1, 8)
                ],
            },
            "evidence_catalog": [
                {
                    "title": f"来源{index}",
                    "claim": f"证据摘要{index}",
                    "url": f"https://example.test/{index}",
                }
                for index in range(1, 9)
            ],
        }
    )

    assert result == "独立重写完成"
    assert [item["phase"] for item in attempts] == [
        "report_generation",
        "report_generation_full_quality_retry",
    ]
    retry = attempts[1]["reporter_input"]
    assert "不得压缩为限时版或降低研究深度" in retry["retry_instruction"]
    assert "draft" not in retry
    assert "research_handoff" in retry
    assert retry["target_length"] == "9000-10000字核心正文"
    assert "立即收尾" in retry["length_policy"]["stop_when"]
    assert "12000字" in retry["length_policy"]["delivery_target"]
    assert "不得触发重写" in retry["length_policy"]["overrun"]
    assert len(retry["research_handoff"]["capability_cues"]) == 7
    assert attempts[0]["output_token_budget"] == 12000
    assert attempts[0]["timeout_seconds"] == 600
    assert attempts[1]["output_token_budget"] == 12000
    assert attempts[1]["timeout_seconds"] == 180


def test_reporter_second_failure_returns_reviewable_limited_report(monkeypatch) -> None:
    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    phases: list[str] = []

    def always_timeout(payload, **kwargs):
        del payload
        phases.append(kwargs["phase"])
        raise TimeoutError("simulated reporter timeout")

    monkeypatch.setattr(provider, "_draft_report_attempt", always_timeout)

    result = provider.draft_report(
        {
            "topic": "体系韧性",
            "report_context": {"primary_branch": "B"},
        }
    )

    assert phases == ["report_generation", "report_generation_full_quality_retry"]
    assert "## 第一层：需求挖掘层" in result
    assert "### ⑨ 发展优先级与近期抓手" in result


def test_limited_report_preserves_domain_hard_gates_without_draft_fragment() -> None:
    cues = [
        {
            "direction": name,
            "equipment_hint": equipment,
            "mission_effect": effect,
            "mechanism_hint": "按任务阶段编组、待机、发射、突防并完成交战",
        }
        for name, equipment, effect in (
            ("远程精确制导弹药升级", "现役远程制导弹药", "纵深精确毁伤"),
            ("抗骗末制导远程导弹", "新研远程导弹", "强干扰突防打击"),
            ("低信息侦打巡飞弹", "车载巡飞弹", "短时目标猎歼"),
            ("低空突防无人打击机", "低空无人机", "低空压制毁伤"),
            ("反辐射巡飞弹猎杀", "反辐射巡飞弹", "干扰源猎杀压制"),
        )
    ]
    payload = {
        "topic": "强干扰、弱通信条件下无人远程精确火力打击装备研究",
        "report_context": {"primary_branch": "D"},
        "synthesis_seed": {
            "decisive_anchors": ["强干扰条件下纵深打击窗口缩短。"],
            "mission_chain_breaks": ["导航与外部火控中断导致毁伤链退化。"],
            "counterevidence_and_limits": ["公开证据不足，关键结论待验证。"],
            "priority_signals": ["P0优先开展抗干扰末制导演示验证。"],
            "capability_cues": cues,
        },
        "evidence_catalog": [
            {"title": "公开来源", "url": "https://example.test/evidence"}
        ],
    }

    result = _build_limited_report(payload, draft="未完成残段，若继续则")

    assert "限时模型草稿保留摘要" not in result
    assert result.count("| 远程") >= 1
    assert "现役效能跃升" in result
    assert "传统赛道跨代优势" in result
    assert "新概念赛道开辟" in result
    assert "成熟度" in result and "工程瓶颈" in result and "待验证" in result
    assert "对手反适应" in result and "失效边界" in result


def test_optimized_reporter_quality_failure_delivers_without_targeted_repair(monkeypatch) -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text="initial draft"))]]
    )
    provider = ResponsesAgentProvider(backend)
    provider.configure_run_budget(
        {
            "maximum_delivery_model_calls": 4,
            "soft_deadline_seconds": 900,
            "hard_deadline_seconds": 1500,
            "delivery_grace_seconds": 300,
            "absolute_deadline_seconds": 1800,
        }
    )
    monkeypatch.setattr(
        "equipment_deep_research.agents.provider._report_draft_quality_issues",
        lambda text, payload: ["initial draft failed"],
    )

    result = provider.draft_report(
        {
            "topic": "体系韧性",
            "execution_profile_id": "optimized_v2",
            "report_context": {"primary_branch": "B"},
            "branch_writer_brief": {
                "branch": "B",
                "required_sections": ["需求卡片", "能力全景图"],
                "mandatory_content": ["现役基线与五档差距"],
                "target_chars": "2800-5000",
                "hard_max_chars": 7200,
            },
        }
    )

    assert len(backend.inputs) == 1
    assert "## 第一层：需求挖掘层" in result
    assert "### ⑨ 发展优先级与近期抓手" in result
    assert any("Reporter限时收敛" in item for item in provider.consume_report_quality_issues())


def test_report_delivery_stabilizer_projects_prechecked_indicators_and_coupling() -> None:
    report = """## 第一层：需求挖掘层——场景·战法/技术·装备能力特征
### ① 典型作战场景
场景正文。
### ② 新战法或新概念技术及制胜机理
机理正文。
### ③ 装备能力特征清单
能力正文。
## 第二层：技术攻关层——能力实现途径与核心技术
### ④ 能力实现途径
路径正文。
### ⑤ 核心技术清单与攻关优先级
技术正文。
### ⑥ 技术耦合与短板风险
各分项必须联合校核。
## 第三层：能力图像与效能贡献层
### ⑦ 装备能力图像
能力图像如下：
| 装备方向 | 能力域 | 指标画像 | 作战边界 | 颠覆关系 | 谱系位置 |
|---|---|---|---|---|---|
| 远程精确导弹 | 精确毁伤 | 射程/响应时间/自主等级/成本量级/规模量级待证据校准 | 库存受限 | 多路径突防 | 新研装备 |
| 低空无人突击集群 | 集群压制 | 射程/响应时间/自主等级/成本量级/规模量级待证据校准 | 反无人密度受限 | 规模交换 | 新研装备 |
### ⑧ 效能贡献评估
效能正文。
### ⑨ 发展优先级与近期抓手
抓手正文。"""
    payload = {
        "synthesis_seed": {
            "capability_cues": [
                {
                    "direction": "远程精确导弹",
                    "mission_effect": "对战役纵深节点实施多路径精确毁伤",
                    "mechanism_hint": "分散发射后按预装订任务完成突防、末段确认和再打击",
                    "development_path": "远程导弹体系化武器族",
                    "disruptive_relationship": "从单弹性能竞争转向多路径持续波次竞争",
                    "boundary": "库存不足或任务规划过慢时失效",
                    "indicator_portrait": "射程看战役纵深，响应看目标包更新，自主性看末段确认，成本看拦截交换，规模看持续波次。",
                    "coupling_risk": "目标信息与末制导串联耦合；目标包老化是单点短板，一旦失效会级联拖垮再打击闭环。",
                },
                {
                    "direction": "低空无人突击集群",
                    "mission_effect": "以多方向低空进入实施诱骗、压制和毁伤",
                    "mechanism_hint": "多批次编组进入后重分配诱骗、突防和毁伤角色",
                    "development_path": "可消耗低空直接作战装备",
                    "disruptive_relationship": "从高价值平台制胜转向低成本规模交换",
                    "boundary": "反无人密度过高或补给中断时失效",
                    "indicator_portrait": "覆盖看低空进入半径，响应看角色重分配，自主性看人工授权，成本看单机交换，规模看单波数量。",
                    "coupling_risk": "协同算法与任务载荷串联耦合；去冲突失效是单点短板，会级联拖垮集群压制闭环。",
                },
            ]
        }
    }

    stabilized = _stabilize_report_delivery_contract(report, payload)

    assert "射程/响应时间/自主等级/成本量级/规模量级待证据校准" not in stabilized
    assert "射程看战役纵深" in stabilized
    assert "覆盖看低空进入半径" in stabilized
    assert "逐项耦合校核如下" in stabilized
    assert "目标包老化是单点短板" in stabilized
    assert "能力图像如下。\n\n| 装备系统方向" in stabilized
    assert "| 装备系统方向 | 能力域 | 指标画像 | 作战运用概念 | 谱系位置 |" in stabilized
    assert "| 装备方向 | 能力域 | 指标画像 | 作战边界 |" not in stabilized
    assert "逐项效能、创新关系与失效边界如下" in stabilized
    assert "逐装备演示验证矩阵如下" in stabilized
    assert "**远程精确导弹**（强链）" in stabilized
    assert "**低空无人突击集群**（开链）" in stabilized

    stabilized_twice = _stabilize_report_delivery_contract(stabilized, payload)
    assert stabilized_twice == stabilized
    assert stabilized_twice.count("逐项效能、创新关系与失效边界如下") == 1
    assert stabilized_twice.count("逐装备演示验证矩阵如下") == 1


def test_report_delivery_stabilizer_can_complete_12000_char_delivery_without_model_rewrite() -> None:
    base = _three_layer_report(detail_count=110)
    if len(base) < 9000:
        base += "\n\n" + ("代表性场景、证据边界和工程验证保持一致。" * 260)
    cues = [
        {
            "direction": f"远程精确打击武器{index}",
            "priority": f"P{index}",
            "mission_effect": f"对第{index}类战役目标形成直接打击、压制和毁伤贡献",
            "mechanism_hint": "在受扰条件下完成预装订进入、末段确认、直接交战和毁伤后续接",
            "development_path": "以公开装备类别为基线完成样机、半实物联试、综合靶场和红队对抗验证",
            "indicator_portrait": "分别校准战役覆盖、目标包更新时间、断链自主边界、单位任务成本、批次规模和受扰生存性",
            "coupling_risk": "目标信息、任务规划、末制导和载荷效应串联耦合；任一失效都会级联拖垮任务闭环",
            "boundary": "诱饵与目标无法区分、授权边界过期或代表性干扰下未形成直接作战贡献",
            "disruptive_relationship": "从单弹峰值性能竞争转向任务闭环、规模交换和持续波次竞争",
        }
        for index in range(1, 7)
    ]
    payload = {"synthesis_seed": {"capability_cues": cues}}

    stabilized = _stabilize_report_delivery_contract(base, payload)

    assert len(stabilized) > 12000
    assert stabilized.count("逐装备演示验证矩阵如下") == 1
    assert _stabilize_report_delivery_contract(stabilized, payload) == stabilized


def test_limited_report_delivery_also_applies_publication_stabilizer() -> None:
    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    cues = [
        {
            "direction": "远程精确制导弹药升级",
            "equipment_hint": "现役远程精确制导弹药改装型",
            "mission_effect": "在导航拒止条件下保持纵深精确毁伤",
            "mechanism_hint": "预装订备选目标并在末段完成类别确认",
            "indicator_portrait": "射程沿现役包线校核，响应看任务装订时间，自主性看断链末段确认，成本看单发改装增量，规模看库存升级比例。",
            "coupling_risk": "任务包与末制导串联耦合；目标特征库过期是单点短板，一旦失效会级联拖垮毁伤闭环。",
        },
        {
            "direction": "低信息侦打巡飞弹",
            "equipment_hint": "车载低空巡飞弹",
            "mission_effect": "对短时暴露目标实施搜索猎歼和补伤",
            "mechanism_hint": "弹间交换摘要并由最近弹认领目标",
            "indicator_portrait": "覆盖看驻留半径，响应看发现至认领时间，自主性看搜索去冲突，成本看单位驻留小时，规模看同时在空弹数。",
            "coupling_risk": "弹间协同与目标识别串联耦合；去冲突失效是单点短板，一旦失效会级联拖垮猎歼闭环。",
        },
        {
            "direction": "反辐射巡飞弹猎杀",
            "equipment_hint": "反辐射巡飞弹",
            "mission_effect": "压制防空和电子战辐射节点",
            "mechanism_hint": "持续待机并在辐射源开机时完成猎杀",
            "indicator_portrait": "覆盖看威胁频段，响应看开机至捕获窗口，自主性看关机续踪，成本看单位压制小时，规模看并发猎杀数。",
            "coupling_risk": "频谱感知与被动制导串联耦合；关机续踪失败是单点短板，一旦失效会级联拖垮压制闭环。",
        },
        {
            "direction": "低空无人突击集群",
            "equipment_hint": "可消耗低空无人突击机",
            "mission_effect": "多方向进入并实施规模压制毁伤",
            "mechanism_hint": "按预授权规则重分配突击和诱骗角色",
            "indicator_portrait": "覆盖看低空进入半径，响应看角色重分配时间，自主性看协同授权边界，成本看单机交换，规模看单波数量。",
            "coupling_risk": "协同算法与任务载荷串联耦合；角色分配失效是单点短板，一旦失效会级联拖垮集群突击闭环。",
        },
        {
            "direction": "远域反辐射压制无人僚机",
            "equipment_hint": "低可探测无人僚机",
            "mission_effect": "前出压制辐射源并消耗拦截资源",
            "mechanism_hint": "断链维持任务并释放诱饵和小型弹药",
            "indicator_portrait": "航程看防区外投送纵深，响应看任务下达至压制窗口，自主性看断链编队，成本看架次交换，规模看并发僚机数。",
            "coupling_risk": "飞控生存与压制载荷串联耦合；被动告警失效是单点短板，一旦失效会级联拖垮远域压制闭环。",
        },
    ]
    payload = {
        "topic": "强干扰、弱通信条件下无人远程精确打击装备研究",
        "report_context": {"primary_branch": "B"},
        "synthesis_seed": {
            "decisive_anchors": ["强干扰使实时坐标更新链失效。"],
            "mission_chain_breaks": ["导航、授权和毁伤评估无法持续在线。"],
            "counterevidence_and_limits": ["公开证据不足，具体阈值待试验。"],
            "priority_signals": ["P0优先验证抗扰末制导。"],
            "capability_cues": cues,
        },
        "evidence_catalog": [
            {"title": "公开来源", "url": "https://example.test/evidence"}
        ],
    }

    result = provider._limited_report_delivery(
        payload,
        failure=ValueError("model draft rejected"),
    )

    assert "射程/响应时间/自主等级/成本量级/规模量级待证据校准" not in result
    assert "射程沿现役包线校核" in result
    assert "覆盖看驻留半径" in result
    assert "逐项耦合校核如下" in result
    assert "目标特征库过期是单点短板" in result
    assert "若继续则" not in result


def test_reporter_compacts_and_sanitizes_upstream_clues() -> None:
    clean = _reporter_generation_payload(
        {
            "topic": "体系韧性",
            "report_context": {"primary_branch": "B"},
            "synthesis_seed": {
                "decisive_anchors": [
                    "国际形势Agent引用S1-S6、L1和packet-001形成Claim。"
                ],
                "capability_cues": [
                    {
                        "direction": "Codex综合cap-001",
                        "mission_effect": "S4形成打击与反制价值",
                        "disruptive_relationship": "从高成本单发拦截转向低成本规模消耗",
                    }
                ],
            },
            "evidence_catalog": [
                {
                    "title": "来源",
                    "url": "https://example.test/source",
                    "claim": "用于L2质量门与ev-001核验",
                }
            ],
        }
    )
    serialized = str(clean)

    for forbidden in (
        "Agent",
        "Codex",
        "S1-S6",
        "S4",
        "L1",
        "L2",
        "packet-001",
        "cap-001",
        "ev-001",
        "Claim",
    ):
        assert forbidden not in serialized
    assert "六阶段制胜分析" in serialized
    assert "对应分析阶段" in serialized
    assert "相关公开证据" in serialized
    assert "低成本规模消耗" in serialized
    assert clean["report_ready_section_map"]["⑦"][-1] == (
        "capability_cues.disruptive_relationship"
    )

    output = _sanitize_reporter_output(
        "国际形势Agent与Codex沿S1-S6、L1和packet-001形成结论。"
    )
    assert "Agent" not in output
    assert "Codex" not in output
    assert "S1-S6" not in output
    assert "L1" not in output
    assert "packet-001" not in output

    table_output = _sanitize_reporter_output(
        "### ⑦ 装备能力图像\n\n"
        "| direction | 能力域 | 指标画像 |\n"
        "|---|---|---|\n"
        "| 抗干扰远程精确制导弹药 | 远程打击 | 抗干扰制导 |"
    )
    assert "| 装备系统方向 | 能力域 | 指标画像 |" in table_output
    assert "| direction |" not in table_output


def test_reporter_gate_preserves_all_input_directions_and_three_relationship_groups() -> None:
    names = [f"具体武器装备方向{index}" for index in range(1, 6)]
    payload = {
        "branch_writer_brief": branch_writer_brief("F"),
        "synthesis_seed": {
            "capability_cues": [
                {"direction": name, "equipment_hint": f"{name}任务构型"}
                for name in names
            ]
        },
    }
    direction_body = (
        "### ⑦ 装备能力图像\n"
        "能力域、指标画像和装备谱系位置按输入方向逐项比较："
        + "、".join(names)
        + "。其中低成本规模消耗改变成本交换，长航时持续存在改变平台关系，"
        "毁伤评估和再打击用于压缩决策周期；支撑能力只作为横向依赖。"
    )
    text = _three_layer_report().replace(
        "### ⑦ 装备能力图像\n能力域构成、指标画像和装备谱系位置共同表明，该方向位于现有装备体系与新一代低成本无人精打装备之间，边界是弱网自治和持续保障能力。",
        direction_body,
    )

    issues = _report_draft_quality_issues(text, payload)
    assert not any("输入方向" in issue for issue in issues)
    assert not any("至少需要3类" in issue for issue in issues)

    missing_one = text.replace(names[-1], "未承接方向")
    missing_issues = _report_draft_quality_issues(missing_one, payload)
    assert any("4/5个输入方向" in issue for issue in missing_issues)

    shallow = text.replace("低成本规模消耗", "经济型运用").replace(
        "长航时持续存在", "常规平台运用"
    ).replace("毁伤评估和再打击用于压缩决策周期", "常规任务闭合")
    shallow = shallow.replace("低成本无人精打", "经济型无人精打").replace(
        "弱网自治", "受扰链路自治"
    ).replace("响应时间", "反应时长").replace("决策周期", "决策时长")
    shallow_issues = _report_draft_quality_issues(shallow, payload)
    assert any("至少需要3类" in issue for issue in shallow_issues)


def test_reporter_gate_rejects_support_package_or_invented_section7_rows() -> None:
    names = [f"直接战斗装备{index}" for index in range(1, 6)]
    payload = {
        "branch_writer_brief": branch_writer_brief("F"),
        "synthesis_seed": {
            "capability_cues": [
                {"direction": name, "equipment_hint": f"{name}任务构型"}
                for name in names
            ]
        },
    }
    rows = "\n".join(
        f"| {name} | 打击毁伤 | 指标 | 边界 | 关系 | 谱系 |"
        for name in names
    )
    valid_section = (
        "### ⑦ 装备能力图像\n\n"
        "| 装备系统方向 | 能力域 | 指标画像 | 使用边界 | 颠覆的传统关系 | 谱系位置 |\n"
        "|---|---|---|---|---|---|\n"
        f"{rows}\n\n"
        "低成本规模消耗、长航时持续存在和毁伤评估后再打击压缩决策周期。"
    )
    base = _three_layer_report().replace(
        "### ⑦ 装备能力图像\n能力域构成、指标画像和装备谱系位置共同表明，该方向位于现有装备体系与新一代低成本无人精打装备之间，边界是弱网自治和持续保障能力。",
        valid_section,
    )
    assert not any(
        "第一列必须与输入" in issue
        for issue in _report_draft_quality_issues(base, payload)
    )

    invalid = base.replace(
        f"| {names[-1]} | 打击毁伤 | 指标 | 边界 | 关系 | 谱系 |",
        "| 弱网联合杀伤网装备包 | C2支撑 | 指标 | 边界 | 关系 | 谱系 |",
    )
    issues = _report_draft_quality_issues(invalid, payload)
    assert any("第一列必须与输入" in issue for issue in issues)
    assert any("擅自新增弱网联合杀伤网装备包" in issue for issue in issues)


def test_optimized_reporter_treats_upstream_context_as_reasoning_seed() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text="完成摘要"))]]
    )
    provider = ResponsesAgentProvider(backend)
    provider.draft_report(
        {
            "topic": "体系韧性",
            "execution_profile_id": "optimized_v2",
            "report_context": {"primary_branch": "B"},
            "synthesis_seed": {"decisive_anchors": ["任务链存在断点"]},
        }
    )

    system_prompt = str(backend.inputs[0][0][0].content)
    assert "全新、独立" in system_prompt
    assert "以Query发散思考为主" in system_prompt
    assert "无人化、低空无人机" in system_prompt
    assert "强打击、歼灭、压制和毁伤" in system_prompt
    for heading in (
        "## 第一层：需求挖掘层——场景·战法/技术·装备能力特征",
        "### ① 典型作战场景",
        "### ② 新战法或新概念技术及制胜机理",
        "### ③ 装备能力特征清单",
        "## 第二层：技术攻关层——能力实现途径与核心技术",
        "### ④ 能力实现途径",
        "### ⑤ 核心技术清单与攻关优先级",
        "### ⑥ 技术耦合与短板风险",
        "## 第三层：能力图像与效能贡献层",
        "### ⑦ 装备能力图像",
        "### ⑧ 效能贡献评估",
        "### ⑨ 发展优先级与近期抓手",
    ):
        assert heading in system_prompt
    assert "research_handoff只是前置处理后的少量高价值研判种子" in system_prompt
    assert "禁止复制前置原句" in system_prompt
    assert "同一判断只写一次" in system_prompt
    assert "避免复述" in system_prompt
    assert "核心正文达到约9000字" in system_prompt
    assert "立即结束" in system_prompt
    assert "最终报告超过12000字" in system_prompt
    assert "不得为追逐字数重复论证" in system_prompt
    assert "绝对交付硬上限" not in system_prompt


def test_reporter_prompt_enforces_each_core_branch_writing_contract() -> None:
    expected = {
        "A": [
            "新战法",
            "能力指标",
            "②③⑦",
        ],
        "B": [
            "需求卡片",
            "能力全景图",
            "具体军事战斗装备",
        ],
        "C": [
            "案例规律",
            "未来场景",
            "跨案例迁移边界",
        ],
    }
    for branch, markers in expected.items():
        backend = ScriptedFakeProvider(
            [[ProviderStreamEvent.final(ProviderFinalTurn(text="完成正文"))]]
        )
        provider = ResponsesAgentProvider(backend)
        assert (
            provider.draft_report(
                {
                    "topic": "分支报告测试",
                    "branch_deliverables": {
                        "branch": branch,
                        "branch_name": f"分支{branch}",
                        "required_sections": [],
                        "products": {},
                    },
                }
            )
            == "完成正文"
        )
        messages = backend.inputs[0][0]
        system_prompt = str(messages[0].content)
        branch_requirement = messages[1].content["branch_hard_requirements"]["core"]
        assert "全新、独立" in system_prompt
        assert "research_handoff只是前置处理后的少量高价值研判种子" in system_prompt
        assert "禁止复制前置原句" in system_prompt
        assert "低空无人机" in system_prompt
        assert "场景—战法" in str(messages[1].content["first_pass_quality_contract"])
        for marker in markers:
            assert marker in branch_requirement, (branch, marker)


def test_reporter_prompt_enforces_adaptive_branch_mission_focus() -> None:
    expected = {
        "D": ["技术改变任务机制", "工程瓶颈", "验证路线"],
        "E": ["对手能力形成链", "对冲机理", "建设触发信号"],
        "F": ["体系脆弱性", "级联失效", "替代链"],
        "G": ["跨域缝隙", "接口", "降级验证"],
        "H": ["威胁扩散", "非致命装备需求", "规则边界"],
    }
    for branch, markers in expected.items():
        backend = ScriptedFakeProvider(
            [[ProviderStreamEvent.final(ProviderFinalTurn(text="完成正文"))]]
        )
        provider = ResponsesAgentProvider(backend)
        assert (
            provider.draft_report(
                {
                    "topic": "自适应分支报告测试",
                    "branch_deliverables": {
                        "branch": branch,
                        "branch_name": f"分支{branch}",
                        "required_sections": [],
                        "products": {},
                    },
                }
            )
            == "完成正文"
        )
        user_payload = backend.inputs[0][0][1].content
        branch_requirement = user_payload["branch_hard_requirements"]["core"]
        for marker in markers:
            assert marker in branch_requirement, (branch, marker)


def test_reporter_quality_gate_repairs_incomplete_core_branch_draft() -> None:
    source_urls = [
        "https://example.test/source-1",
        "https://example.test/source-2",
        "https://example.test/source-3",
    ]
    valid = _three_layer_report(
        source_urls=source_urls,
        extra="A分支的新战法、战法组合和能力指标已压缩进入九项，不另设平行模板。",
    )
    payload = {
        "topic": "新战法研究",
        "branch_writer_brief": {"branch": "A", "required_sections": []},
        "branch_deliverables": {"branch": "A", "products": {}},
        "evidence_catalog": [
            {"title": f"公开来源{index}", "url": url}
            for index, url in enumerate(source_urls, start=1)
        ],
    }
    issues = _report_draft_quality_issues("过短且没有分支产物", payload)
    assert any("最低门槛" in item for item in issues)
    assert any("缺少固定二级章节" in item for item in issues)
    assert any("缺少固定三级项" in item for item in issues)
    assert _report_draft_quality_issues(valid, payload) == []
    bounded_long = valid + ("跨材料综合判断继续保留因果、反证和验证边界。" * 200)
    bounded_long = bounded_long[:5400]
    bounded_payload = {
        **payload,
        "branch_writer_brief": branch_writer_brief("A"),
    }
    assert not any(
        "交付硬上限" in item
        for item in _report_draft_quality_issues(bounded_long, bounded_payload)
    )
    overlong = bounded_long + ("补充。" * 3000)
    assert not any(
        "交付硬上限12000字" in item
        for item in _report_draft_quality_issues(overlong, bounded_payload)
    )
    invalid_citation_issues = _report_draft_quality_issues(
        valid.replace(source_urls[0], "https://unknown.example.test/source"),
        payload,
    )
    assert any("来源目录之外的URL" in item for item in invalid_citation_issues)

    backend = ScriptedFakeProvider(
        [
            [ProviderStreamEvent.final(ProviderFinalTurn(text="过短且没有分支产物"))],
            [ProviderStreamEvent.final(ProviderFinalTurn(text=valid))],
        ]
    )
    result = ResponsesAgentProvider(backend).draft_report(payload)
    assert "## 第一层：需求挖掘层" in result
    assert "### ⑨ 发展优先级与近期抓手" in result
    assert len(backend.inputs) == 1


def test_other_branch_quality_gate_requires_every_adaptive_section() -> None:
    for branch in "DEFGH":
        brief = branch_writer_brief(branch)
        payload = {
            "topic": "自适应分支报告测试",
            "branch_writer_brief": brief,
            "branch_deliverables": {"branch": branch, "products": {}},
            "evidence_index": [],
        }
        incomplete = "旧分支章节不能替代三层九项。" + ("深度综合论证。" * 400)
        issues = _report_draft_quality_issues(incomplete, payload)
        assert any("缺少固定二级章节" in item for item in issues), branch
        assert any("缺少固定三级项" in item for item in issues), branch

        complete = _three_layer_report(
            extra=(
                f"{branch}分支高价值结论已经进入对应九项，打击、反制、抗毁与持续作战价值"
                "通过现役升级和新装备形成建设决策。"
            )
        )
        assert _report_draft_quality_issues(complete, payload) == [], branch


def test_branch_b_report_accepts_canonical_traceable_task_chain_and_prompts_labels() -> None:
    payload = {
        "topic": "传统能力缺口研究",
        "branch_writer_brief": branch_writer_brief("B"),
        "branch_deliverables": {"branch": "B", "products": {}},
        "evidence_catalog": [],
    }
    text = _three_layer_report(
        extra=(
            "需求卡片、能力全景图、推理链回溯和证据链已压缩融入九项；"
            "背景压力经任务链断点传导到拦截、反制和拒止效果。"
        )
    )
    assert _report_draft_quality_issues(text, payload) == []
    prompt = _report_writer_system_prompt(payload)
    for marker in ("需求卡片", "能力全景图", "推理链回溯", "证据链"):
        assert marker in prompt
    assert "公开型号或谱系锚点" in prompt
    assert "公开证据不足，保留类别级" in prompt
    assert "制造参数" in prompt
    assert "只选择与Query任务对象" in prompt
    assert "不得展示六维方法论清单" in prompt
    assert "至少4项直接承担" in prompt


def test_report_quality_gate_rejects_label_headings_and_shallow_decisions() -> None:
    brief = branch_writer_brief("G")
    payload = {
        "topic": "跨域融合",
        "branch_writer_brief": brief,
        "branch_deliverables": {"branch": "G", "products": {}},
    }
    text = (
        "\n".join(f"### {item}" for item in brief["required_sections"])
        + "\n### 军事价值性\n"
        + "仅说明一般能力。"
        + ("研究内容。" * 500)
    )
    issues = _report_draft_quality_issues(text, payload)
    assert any("独立标题" in item for item in issues)
    assert any("军事运用价值不足" in item for item in issues)
    assert any("因果论证不足" in item for item in issues)
    assert any("装备决策不足" in item for item in issues)


def test_codex_reporter_ignores_registry_skill_and_harness_context() -> None:
    class CodexScriptedProvider(ScriptedFakeProvider):
        def snapshot(self) -> dict[str, str]:
            return {"type": "codex_cli", "model": self.model, "base_url_host": ""}

    root = Path(__file__).parents[3]
    registry = AgentRegistry.load(root / "configs/equipment_deep_research/agents.yaml")
    backend = CodexScriptedProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text="完成摘要"))]]
    )
    provider = ResponsesAgentProvider(
        backend,
        agent_definitions={
            agent_id: registry.get(agent_id)
            for agent_id in registry.all_agent_ids()
        },
        harness_profiles=registry.harness_catalog.profiles,
    )

    assert provider.draft_report({"topic": "体系韧性"}) == "完成摘要"
    messages, _, options = backend.inputs[0]
    assert messages[1].content["query"] == "体系韧性"
    assert "report_context" not in messages[1].content
    assert "synthesis_seed" not in messages[1].content
    assert "agent_runtime" not in messages[1].content
    contract = messages[1].content["reporter_contract"]
    assert contract["required_outputs"]
    assert contract["writing_priorities"]
    assert contract["evidence_rules"]
    assert contract["structure_rules"]
    assert contract["stopping_conditions"]
    assert "skill_ids" not in contract
    assert "tools" not in contract
    assert "harness" not in str(contract).lower()
    assert "$js-equipment-agent-runtime" not in messages[0].content
    assert options["reasoning_effort"] == "xhigh"
    assert options["max_output_tokens"] == 12000
    assert options["reasoning_effort"] == "xhigh"
    assert options["prompt_mode"] == "standalone"


def test_weapon_equipment_codex_call_batches_tracks_and_injects_equipment_runtime() -> None:
    backend = ScriptedFakeProvider(
        [
            [ProviderStreamEvent.final(ProviderFinalTurn(text=f"discovery-{index}"))]
            for index in range(1, 3)
        ]
        + [[ProviderStreamEvent.final(ProviderFinalTurn(text=(
            '{"findings":["形成国外装备与防御性需求闭环"],"confidence":0.8,'
            '"open_questions":[],"handoff_summary":"完成装备研究"}'
        )))]]
    )
    agent = AgentDef(
        "weapon_equipment",
        "武器装备",
        "国外装备深度研究",
        ["equipment"],
        ["search_sources", "map_defensive_countermeasure", "formulate_equipment_requirement"],
        {},
        output_contract={"name": "baseline_finding_packet", "properties": []},
        skills=[{"name": "defensive_countermeasure_analysis"}],
        research_policy={
            "search_tracks": [f"track-{index}" for index in range(1, 9)],
            "target_source_count": 16,
        },
    )
    result = ResponsesAgentProvider(backend).run_baseline_agent(
        AgentRunRequest(
            "run-equipment",
            agent,
            "国外装备能力与防御性反制需求",
            "traditional_gap",
            {"discovery_blueprint": {"primary_branch": "B"}},
        )
    )
    assert len(backend.inputs) == 3
    for messages, _, _ in backend.inputs:
        runtime = messages[1].content["agent_runtime"]
        assert runtime["agent_id"] == "weapon_equipment"
        assert "map_defensive_countermeasure" in runtime["tools"]
        assert runtime["discovery_branches"][0]["code"] == "B"
    assert result.packet.findings == ["形成国外装备与防御性需求闭环"]
