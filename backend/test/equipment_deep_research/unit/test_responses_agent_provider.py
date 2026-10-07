from __future__ import annotations

import asyncio
import re
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
    _clean_winning_hypothesis_title,
    _clip_complete_report_phrase,
    _dedupe_capability_title,
    _enforce_report_hard_max,
    _is_remote_precision_portfolio_direction,
    _latest_inner_loop_failures,
    _report_draft_quality_issues,
    _report_equipment_attribution_issues,
    _report_fragment_quality_issues,
    _report_hard_max_chars,
    _report_issues_require_fallback,
    _report_markdown_structure_issues,
    _report_seed_copy_issues,
    _report_table_issues,
    _remove_empty_report_clauses,
    _normalize_branch_report_labels,
    _normalize_report_structure_deterministically,
    _normalize_s6_deterministic_format,
    _report_writer_system_prompt,
    _reporter_generation_payload,
    _reporter_timeout_retry_payload,
    _ensure_specialized_winning_seed_lanes,
    _recover_specialized_winning_seed_hypotheses,
    _sanitize_reporter_output,
    _stabilize_report_delivery_contract,
    _typed_packet_payload,
)
from equipment_deep_research.agents.workflows.reporting_support import (
    _canonical_report_h3,
    _report_has_complete_canonical_structure,
    _report_template_mode,
)
from equipment_deep_research.agents.workflows.reporter import (
    _parallel_report_output_cap,
    _repair_reason_fingerprint,
    _reporter_chapter_fallback_profile,
    _resolve_reporter_provider,
)
from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.agents.registry import AgentRegistry
from equipment_deep_research.agents.workflows.coordinator import (
    _merge_partial_report_with_limited_completion,
)
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
from equipment_deep_research.orchestration.runner import (
    DeepResearchRunner,
    _report_coupling_risk,
    _report_indicator_portrait,
)
from equipment_deep_research.orchestration.deliverables import branch_writer_brief
from equipment_deep_research.orchestration.winning_swarm import (
    SWARM_SPECIALIST_ARCHETYPES,
)
from pathlib import Path


def test_parallel_report_output_cap_scales_to_declared_section_target() -> None:
    contract = {"parallel_section_contract": {"target_chars": 1900}}
    assert _parallel_report_output_cap(5200, contract) == 4505
    assert _parallel_report_output_cap(2600, contract) == 2600


def test_parallel_report_output_cap_preserves_legacy_full_turns() -> None:
    assert _parallel_report_output_cap(12000, {"query": "legacy"}) == 8000


def test_report_repair_fingerprint_collapses_same_root_with_different_counts() -> None:
    first = _repair_reason_fingerprint(["三级栏目正文偏短：仅620字，目标约1100字"])
    second = _repair_reason_fingerprint(["三级栏目正文偏短：仅840字，目标约1100字"])
    assert first == second == ("substance_floor",)


def test_report_repair_fingerprint_keeps_distinct_roots_separate() -> None:
    assert _repair_reason_fingerprint(["缺少指定三级标题"]) != _repair_reason_fingerprint(
        ["正文含流程性占位句"]
    )


def test_s6_normalization_preserves_codex_portrait_for_quality_review() -> None:
    direction = {
        "type": "upgrade",
        "name": "断链复核低成本巡航弹",
        "equipment_form": (
            "地面或舰载箱式发射的低成本巡航弹，内置组合导航、"
            "末端多模传感器和任务包安全控制器"
        ),
        "target_scenario": "前沿机场停摆、敌方防空和强电磁压制并存时",
        "capability_gap": (
            "公开基线强调低成本生产，未充分证明强干扰、断续授权和末端自主复核下的战役级补射能力"
        ),
        "scientific_principle": "以任务分工和工业补充速度改变高价拦截成本交换",
        "enabling_technologies": ["抗干扰组合导航", "多模末制导复核", "任务包安全控制"],
        "operational_concept": "后方地面或舰载箱式发射、抗扰进入、末端复核和补射",
        "operational_process": ["目标包装订", "机动分批发射", "抗扰进入", "末端复核与补射"],
        "capability_outcome": "形成弱网环境下可持续补射的远程消耗弹药层",
        "military_value": "承担次高价值目标补射并维持机场受毁后的火力密度",
        "winning_mechanism": "以低成本多波次补射消耗高价拦截库存",
        "baseline_system": "Barracuda-500M类地面发射低成本巡航弹基线",
        "strike_chain_contribution": "承担高端弹药后的补射和消耗层",
        "query_relevance": "前沿机场受毁与强电磁压制下的跨岛链持续补射",
        "capability_portrait": (
            "概述：面向前沿机场停摆，针对公开基线未证明断链补射，以低成本巡航弹为主装备，"
            "利用规模交换原理，采用抗扰导航，通过箱式发射与末端复核，形成补射能力，实现纵深毁伤。\n"
            "- 装备与技术实现：集成组合导航与多模末制导。\n"
            "- 关键作战流程：完成装订、发射、进入、复核和补射。\n"
            "- 形成能力与作战效果：形成弱网补射能力。\n"
            "- 制胜逻辑机理与对抗边界：以低成本弹药消耗高价拦截弹。"
        ),
    }

    normalized = _normalize_s6_deterministic_format(
        {"concept_directions": [direction], "confidence": 0.72},
        topic="前沿机场受毁与强电磁压制下跨岛链无人远程火力持续释能装备研究",
    )["concept_directions"][0]

    # A concrete swarm/S6 weapon identity is retained verbatim; the combat
    # action belongs in the portrait rather than being appended to its name.
    assert normalized["name"] == "断链复核低成本巡航弹"
    assert "针对公开基线" in normalized["capability_portrait"].splitlines()[0]
    assert normalized["capability_portrait"] == direction["capability_portrait"]


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


def test_swarm_and_quality_judge_have_separate_reserved_call_budgets() -> None:
    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    provider.configure_run_budget(
        {
            "maximum_model_calls": 1,
            "maximum_model_calls_with_residuals": 1,
            "maximum_swarm_model_calls": 2,
            "maximum_quality_judge_model_calls": 1,
            "hard_deadline_seconds": 900,
            "absolute_deadline_seconds": 1800,
        }
    )

    provider._reserve_model_call(priority="critical")
    with pytest.raises(RuntimeError, match="model-call hard budget"):
        provider._reserve_model_call(priority="critical")

    assert provider._reserve_model_call(priority="swarm") is not None
    assert provider._reserve_model_call(priority="swarm") is not None
    with pytest.raises(RuntimeError, match="swarm model-call budget"):
        provider._reserve_model_call(priority="swarm")

    assert provider._reserve_model_call(priority="quality_gate") is not None
    with pytest.raises(RuntimeError, match="quality-judge model-call budget"):
        provider._reserve_model_call(priority="quality_gate")


def test_ignore_runtime_deadline_does_not_bypass_swarm_call_budget() -> None:
    """Long quality turns may ignore the wall clock, but not call ceilings."""

    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    provider.configure_run_budget(
        {
            "wall_clock_deadlines_enabled": True,
            "hard_deadline_seconds": 1,
            "absolute_deadline_seconds": 2,
            "maximum_swarm_model_calls": 1,
        }
    )

    # The explicit deadline escape hatch should only affect time checks.
    provider._reserve_model_call(
        priority="swarm",
        ignore_runtime_deadline=True,
    )
    with pytest.raises(RuntimeError, match="swarm model-call budget"):
        provider._reserve_model_call(
            priority="swarm",
            ignore_runtime_deadline=True,
        )


def test_report_title_does_not_consume_single_column_recovery_budget() -> None:
    backend = ScriptedFakeProvider(
        [
            [ProviderStreamEvent.final(ProviderFinalTurn(text="规范报告题目"))],
            [ProviderStreamEvent.final(ProviderFinalTurn(text="完整栏目正文"))],
        ]
    )
    provider = ResponsesAgentProvider(backend)
    provider.configure_run_budget(
        {
            "wall_clock_deadlines_enabled": False,
            "maximum_delivery_model_calls": 1,
            "maximum_reporter_model_calls": 1,
            "codex_concurrency": 1,
        }
    )

    title = asyncio.run(
        provider._run_reporter_text(
            "rewrite title",
            {"query": "test"},
            120,
            phase="report_title_rewrite",
        )
    )
    column = asyncio.run(
        provider._run_reporter_text(
            "write one column",
            {"query": "test"},
            1200,
            phase="report_generation_item_1_scenario",
            isolation_id="report:item-1",
        )
    )

    assert title == "规范报告题目"
    assert column == "完整栏目正文"
    assert provider._budget_started_delivery_calls == 1
    assert provider._budget_started_reporter_calls == 1


@pytest.mark.parametrize(
    "execution_profile_id",
    ["swarm_quality_v1", "winning_swarm_dynamic_v2"],
)
def test_quality_reporter_generates_nine_single_item_columns_in_parallel(
    monkeypatch,
    execution_profile_id: str,
) -> None:
    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    running = 0
    maximum_running = 0
    phases: list[str] = []
    contracts: list[dict] = []

    async def fake_reporter(
        system,
        payload,
        max_output_tokens,
        *,
        phase,
        run_id="",
        isolation_id="",
    ):
        nonlocal running, maximum_running
        del system, max_output_tokens, run_id, isolation_id
        running += 1
        maximum_running = max(maximum_running, running)
        phases.append(phase)
        await asyncio.sleep(0.02)
        running -= 1
        contract = payload["parallel_section_contract"]
        contracts.append(contract)
        return "\n".join(
            [f"## {contract['required_h2']}"]
            + [f"### {item}\n完整研究判断。" for item in contract["required_h3"]]
        )

    provider._run_reporter_text = fake_reporter  # type: ignore[method-assign]
    monkeypatch.setattr(
        "equipment_deep_research.agents.provider._report_draft_quality_issues",
        lambda report, payload: [],
    )
    monkeypatch.setattr(
        "equipment_deep_research.agents.provider._minimum_viable_model_report",
        lambda report, payload: True,
    )

    result = provider.draft_report(
        {
            "run_id": "parallel-reporter",
            "topic": "动态集群装备研究",
            "execution_profile_id": execution_profile_id,
            "branch": "A",
        }
    )

    assert maximum_running == 9
    assert all(len(contract["required_h3"]) == 1 for contract in contracts)
    assert all(contract["hard_max_chars"] == 0 for contract in contracts)
    assert set(phases) == {
        "report_generation_item_1_scenario",
        "report_generation_item_2_winning_mechanism",
        "report_generation_item_3_capability_features",
        "report_generation_item_4_realization_path",
        "report_generation_item_5_core_technologies",
        "report_generation_item_6_coupling_risks",
        "report_generation_item_7_capability_image",
        "report_generation_item_8_effectiveness",
        "report_generation_item_9_priority",
    }
    assert "## 第一层：需求挖掘层" in result
    assert "## 第三层：能力图像与效能贡献层" in result
    assert result.count("## 第一层：需求挖掘层") == 1
    assert result.count("### ① 典型作战场景") == 1


@pytest.mark.parametrize(
    "execution_profile_id",
    ["swarm_quality_v1", "winning_swarm_dynamic_v2"],
)
def test_project_quality_reporter_uses_twelve_single_column_concurrency(
    monkeypatch,
    execution_profile_id: str,
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY", "8")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_MODEL_CONCURRENCY_MAX", "8")
    monkeypatch.setenv("EQUIPMENT_DR_REPORTER_MODEL_CONCURRENCY", "12")
    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    running = 0
    maximum_running = 0
    phases: list[str] = []
    contracts: list[dict] = []
    layer_payloads: dict[str, dict] = {}
    layer_systems: dict[str, str] = {}
    token_budgets: list[int] = []
    efforts: list[str] = []
    observed_gate_limits: list[int] = []

    async def fake_reporter(
        system,
        payload,
        max_output_tokens,
        *,
        phase,
        run_id="",
        isolation_id="",
    ):
        nonlocal running, maximum_running
        del run_id, isolation_id
        running += 1
        maximum_running = max(maximum_running, running)
        phases.append(phase)
        layer_payloads[phase] = payload
        layer_systems[phase] = system
        token_budgets.append(max_output_tokens)
        efforts.append(system)
        observed_gate_limits.append(provider._call_gate.snapshot()["maximum"])
        contract = payload["parallel_section_contract"]
        contracts.append(contract)
        await asyncio.sleep(0.02)
        running -= 1
        parts: list[str] = []
        filler = (
            "该装备在真实威胁态势下以专属动作改写敌我交换关系，"
            "形成可验收直接战果，并保持对手反适应与成立边界可复核。"
        ) * 25
        for h2, h3s in contract["h2_h3_map"].items():
            parts.append(f"## {h2}")
            for h3 in h3s:
                parts.append(f"### {h3}\n{filler}")
                parts.extend(
                    f"#### {h4}\n{filler}"
                    for h4 in contract["required_h4"]
                )
        if contract["layer_id"] == "chapter_2_equipment_image":
            marker = f"### （一）装备图像概述\n{filler}"
            table = (
                "### （一）装备图像概述\n"
                "| 武器装备 | 核心技术 | 形成能力 | 作战概念与主要效果 |\n"
                "|---|---|---|---|\n"
                "| 有限区搜索远程反舰巡航弹药 | 有限区搜索与身份复核 | 断链后直接反舰毁伤 | "
                "按有界搜索区复获并复核水面目标，满足授权后实施直接毁伤 |"
                f"\n{filler}"
            )
            parts = [part.replace(marker, table) for part in parts]
        return "\n".join(parts)

    provider._run_reporter_text = fake_reporter  # type: ignore[method-assign]
    monkeypatch.setattr(
        "equipment_deep_research.agents.provider._report_draft_quality_issues",
        lambda report, payload: [],
    )
    monkeypatch.setattr(
        "equipment_deep_research.agents.provider._minimum_viable_model_report",
        lambda report, payload: True,
    )

    result = provider.draft_report(
        {
            "run_id": "project-parallel-reporter",
            "topic": "强电磁压制下精确打击任务续接装备研究",
            "execution_profile_id": execution_profile_id,
            "report_template_mode": "project_argument_v1",
            "branch": "G",
            "synthesis_seed": {
                "decisive_anchors": ["断链后目标证据快速过期"],
                "comparative_status": {
                    "foreign_cases": ["公开远程反舰弹药基线"]
                },
                "capability_cues": [
                    {
                        "direction": "有限区搜索远程反舰巡航弹药",
                        "capability_gap": "目标航迹过期后缺少安全再捕获闭环",
                        "mission_effect": "断链后直接反舰毁伤",
                        "public_equipment_baseline": "LRASM公开基线",
                        "equipment_hint": "多模远程反舰巡航弹药",
                        "scientific_principle": "有限区搜索与身份复核",
                        "operational_process": ["任务装订", "有限区搜索", "直接攻击"],
                        "system_contribution_thesis": "使过期航迹不再直接终止反舰任务，而是转入有界自主复获",
                        "indicator_portrait": "搜索区覆盖率与剩余能量裕度",
                        "coupling_risk": "导航、能源和复核串联耦合",
                    }
                ],
            },
        }
    )

    assert maximum_running == 12
    assert set(observed_gate_limits) == {12}
    assert provider._call_gate.snapshot()["maximum"] == 8
    assert all(len(contract["required_h3"]) == 1 for contract in contracts)
    assert token_budgets == [
        4000,
        4200,
        4200,
        5200,
        6000,
        4000,
        4000,
        2400,
        4400,
        5600,
        2800,
        3600,
    ]
    assert [contract["target_chars"] for contract in contracts] == [
        1100,
        1100,
        1100,
        1400,
        1700,
        1100,
        1100,
        550,
        1100,
        1400,
        650,
        850,
    ]
    assert all(
        "异常偏短触发线，不是写作目标" in item for item in efforts
    )
    assert all("禁止连续照录其中的长句" in item for item in efforts)
    assert all("不得通过删除事实、来源、反证或验证要求" in item for item in efforts)
    assert all("动笔前先为每个direction建立独立" in item for item in efforts)
    assert all(
        "正文优先解释装备怎样解决态势威胁、改变交战关系和形成制胜效果"
        in item
        for item in efforts
    )
    assert all("并行单栏作者" in item for item in efforts)
    assert all("不得代写完整五章或其他栏目" in item for item in efforts)
    assert not any("按上述标题完成正文" in item for item in efforts)
    assert all(contract["hard_max_chars"] == 0 for contract in contracts)
    assert set(phases) == {
        "report_generation_chapter_1_demand_overview",
        "report_generation_chapter_1_status",
        "report_generation_chapter_1_necessity",
        "report_generation_chapter_2_equipment_image",
        "report_generation_chapter_2_operations",
        "report_generation_chapter_2_contribution",
        "report_generation_chapter_2_indicators",
        "report_generation_chapter_3_architecture",
        "report_generation_chapter_3_subsystems",
        "report_generation_chapter_4_technology",
        "report_generation_chapter_5_units",
        "report_generation_chapter_5_technical_foundation",
    }
    demand_handoff = layer_payloads[
        "report_generation_chapter_1_demand_overview"
    ]["research_handoff"]
    portrait_handoff = layer_payloads[
        "report_generation_chapter_2_contribution"
    ]["research_handoff"]
    solution_handoff = layer_payloads[
        "report_generation_chapter_3_subsystems"
    ]["research_handoff"]
    technology_handoff = layer_payloads[
        "report_generation_chapter_4_technology"
    ]["research_handoff"]
    foundation_handoff = layer_payloads[
        "report_generation_chapter_5_technical_foundation"
    ]["research_handoff"]
    assert "comparative_status" in demand_handoff
    assert "comparative_status" in portrait_handoff
    assert "decisive_anchors" in solution_handoff
    assert "comparative_status" in technology_handoff
    assert "comparative_status" in foundation_handoff
    demand_cue = demand_handoff["capability_cues"][0]
    portrait_cue = portrait_handoff["capability_cues"][0]
    solution_cue = solution_handoff["capability_cues"][0]
    technology_cue = technology_handoff["capability_cues"][0]
    assert "capability_gap" in demand_cue
    assert "operational_process" in demand_cue
    assert "operational_process" in portrait_cue
    assert "system_contribution_thesis" in portrait_cue
    assert portrait_cue["system_contribution_thesis"] == (
        "使过期航迹不再直接终止反舰任务，而是转入有界自主复获"
    )
    assert "indicator_portrait" in portrait_cue
    portrait_system = layer_systems["report_generation_chapter_2_indicators"]
    assert "数量、表达和验证设计由实际分析决定" in portrait_system
    assert "3至5个专属指标" not in portrait_system
    assert "定向能应关注" not in portrait_system
    assert "operational_process" in solution_cue
    assert "mission_effect" in solution_cue
    assert "coupling_risk" in technology_cue
    assert "operational_process" in technology_cue
    assert "不能共用一套展开顺序" in layer_systems[
        "report_generation_chapter_3_subsystems"
    ]
    assert "不得为每件装备机械补齐相同技术栏目" in layer_systems[
        "report_generation_chapter_4_technology"
    ]
    assert "不得复制通用承研分工" in layer_systems[
        "report_generation_chapter_5_units"
    ]
    final_contract = next(
        item
        for item in contracts
        if item["layer_id"] == "chapter_5_technical_foundation"
    )
    assert final_contract["h2_h3_map"] == {
        "五、研制基础": ["（二）技术基础"],
    }
    assert "## 五、研制基础" in result
    assert result.count("## 二、项目画像") == 1
    assert result.count("### （四）主要战技指标") == 1


def test_dynamic_reporter_only_stops_for_explicit_safety_blocker(
    monkeypatch,
) -> None:
    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    started = False

    def fail_parallel(*args, **kwargs):
        nonlocal started
        del args, kwargs
        started = True
        raise AssertionError("Reporter must not start for an invalid portfolio")

    monkeypatch.setattr(provider, "_draft_parallel_report", fail_parallel)

    with pytest.raises(ValueError, match="safety gate"):
        provider.draft_report(
            {
                "topic": "无人远程火力打击装备研究",
                "execution_profile_id": "winning_swarm_dynamic_v2",
                "portfolio_quality_gate": {
                    "passed": False,
                    "direction_count": 2,
                    "direct_combat_equipment_count": 2,
                        "distinct_direct_equipment_family_count": 2,
                        "preferred_distinct_direct_equipment": 5,
                        "hard_blockers": ["unsafe direct effect"],
                },
            }
        )

    assert started is False


def test_specialized_seed_lanes_preserve_codex_rows_without_fixed_seed_recovery() -> None:
    evidence = [
        {
            "evidence_id": "ev-weapon_equipment-web-harop",
            "source_title": "IAI Harop loitering munition",
            "claim": "Harop searches, identifies and attacks high-value targets.",
        },
        {
            "evidence_id": "ev-weapon_equipment-web-aargm",
            "source_title": "Navy AARGM-ER enters production",
            "claim": "AARGM-ER anti-radiation missile production decision.",
        },
        {
            "evidence_id": "ev-weapon_equipment-web-jassm",
            "source_title": "JASSM AGM-158 standoff missile",
            "claim": "Low-observable standoff precision strike missile.",
        },
        {
            "evidence_id": "ev-weapon_equipment-web-prsm-army",
            "source_title": "Army announces first Precision Strike Missile delivery",
            "claim": "The Army received its first PrSM missiles.",
        },
        {
            "evidence_id": "ev-weapon_equipment-web-prsm-gao",
            "source_title": "GAO long-range modernization assessment",
            "claim": "PrSM iterative development and test risks.",
        },
    ]
    direct = _recover_specialized_winning_seed_hypotheses(
        evidence,
        archetype="direct_combat_equipment_generator",
    )
    assert direct == []

    remote, recovered_count = _ensure_specialized_winning_seed_lanes(
        [
            {
                "title": "PrSM多功能母弹释放与持续联网复合构型",
                "nearest_public_baseline": "PrSM",
                "changed_confrontation_variable": "堆叠多种未经锚定能力",
                "equipment_forms": ["地面发射远程精确制导导弹"],
                "evidence_ids": ["ev-weapon_equipment-web-prsm-gao"],
            },
            {
                "title": "JASSM持续联网末段复核复合构型",
                "nearest_public_baseline": "JASSM",
                "changed_confrontation_variable": "堆叠多种未经锚定能力",
                "equipment_forms": ["空射防区外巡航导弹"],
                "evidence_ids": ["ev-weapon_equipment-web-jassm"],
            },
        ],
        evidence,
        archetype="remote_precision_munition_generator",
    )

    assert recovered_count == 0
    assert {item["title"] for item in remote} == {
        "PrSM多功能母弹释放与持续联网复合构型",
        "JASSM持续联网末段复核复合构型",
    }
    prsm = next(item for item in remote if item["title"].startswith("PrSM"))
    assert prsm["evidence_ids"] == ["ev-weapon_equipment-web-prsm-gao"]


def test_project_parallel_reporter_runs_with_twelve_column_budget(monkeypatch) -> None:
    backend = ScriptedFakeProvider(
        [
            [ProviderStreamEvent.final(ProviderFinalTurn(text=f"## column {index}"))]
            for index in range(1, 13)
        ]
    )
    provider = ResponsesAgentProvider(backend)
    provider.configure_run_budget(
        {
            "wall_clock_deadlines_enabled": False,
            "maximum_model_calls": 20,
            "maximum_model_calls_with_residuals": 20,
            "maximum_swarm_model_calls": 16,
            "maximum_quality_judge_model_calls": 2,
            "maximum_delivery_model_calls": 5,
            "maximum_reporter_model_calls": 36,
            "codex_concurrency": 8,
            "reporter_codex_concurrency": 12,
        }
    )
    monkeypatch.setattr(
        "equipment_deep_research.agents.provider._report_draft_quality_issues",
        lambda report, payload: [],
    )
    monkeypatch.setattr(
        "equipment_deep_research.agents.provider._minimum_viable_model_report",
        lambda report, payload: True,
    )
    monkeypatch.setattr(
        provider,
        "_limited_report_delivery",
        lambda *args, **kwargs: pytest.fail("twelve-column project report must not fallback"),
    )

    result = provider.draft_report(
        {
            "run_id": "twelve-column-budget",
            "topic": "强电磁压制下精确打击任务续接装备研究",
            "execution_profile_id": "winning_swarm_dynamic_v2",
            "report_template_mode": "project_argument_v1",
        }
    )

    assert len(backend.inputs) == 12
    assert "column" in result


def test_dynamic_v2_reporter_preserves_parallel_work_without_full_serial_rewrite(monkeypatch) -> None:
    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    full_attempted = False

    def fail_parallel(*args, **kwargs):
        del args, kwargs
        provider._latest_report_draft = "## 第一层：需求挖掘层\n已完成的并行草稿。"
        raise ValueError("parallel assembly needs deterministic completion")

    def fail_full(*args, **kwargs):
        nonlocal full_attempted
        del args, kwargs
        full_attempted = True
        return "full-context recovery report"

    monkeypatch.setattr(provider, "_draft_parallel_report", fail_parallel)
    monkeypatch.setattr(provider, "_draft_report_attempt", fail_full)
    monkeypatch.setattr(
        provider,
        "_limited_report_delivery",
        lambda payload, failure: "deterministically completed report",
    )

    result = provider.draft_report(
        {
            "topic": "动态集群装备研究",
            "execution_profile_id": "winning_swarm_dynamic_v2",
        }
    )

    assert result == "deterministically completed report"
    assert full_attempted is False


def test_parallel_deepseek_rewrites_only_the_failed_project_column(monkeypatch) -> None:
    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    phases: list[str] = []

    def valid_fragment(contract: dict) -> str:
        filler = (
            "该装备在真实威胁态势下以专属动作改写敌我交换关系，"
            "形成可验收直接战果，并保持对手反适应与成立边界可复核。"
        ) * 25
        parts = [f"## {contract['required_h2']}"]
        for heading in contract["required_h3"]:
            if heading == "（一）装备图像概述":
                parts.append(
                    "### （一）装备图像概述\n"
                    "| 武器装备 | 核心技术 | 形成能力 | 作战概念与主要效果 |\n"
                    "|---|---|---|---|\n"
                    "| 定向拒止弹 | 窄波束效应控制 | 区域电子拒止 | "
                    "进入任务走廊后对无人目标电子组件施加定向效应，压低持续穿透能力 |"
                    f"\n{filler}"
                )
            else:
                parts.append(f"### {heading}\n{filler}")
            parts.extend(
                f"#### {h4}\n{filler}"
                for h4 in contract.get("required_h4", [])
            )
        return "\n".join(parts)

    async def fake_reporter(system, payload, max_output_tokens, **kwargs):
        del system, max_output_tokens
        phase = kwargs["phase"]
        phases.append(phase)
        contract = payload["parallel_section_contract"]
        if contract["layer_id"] == "chapter_3_architecture" and not phase.endswith(
            "_deepseek_fallback"
        ):
            return ""
        return valid_fragment(contract)

    provider._run_reporter_text = fake_reporter  # type: ignore[method-assign]
    monkeypatch.setattr(
        "equipment_deep_research.agents.workflows.reporter._reporter_chapter_fallback_profile",
        lambda host, payload: "deepseek",
    )
    monkeypatch.setattr(
        "equipment_deep_research.agents.provider._report_draft_quality_issues",
        lambda report, payload: [],
    )
    monkeypatch.setattr(
        "equipment_deep_research.agents.provider._minimum_viable_model_report",
        lambda report, payload: True,
    )

    result = provider.draft_report(
        {
            "run_id": "chapter-only-fallback",
            "topic": "复杂环境武器装备研究",
            "execution_profile_id": "winning_swarm_dynamic_v2",
            "report_template_mode": "project_argument_v1",
            "synthesis_seed": {
                "capability_cues": [
                    {
                        "direction": "定向拒止弹",
                        "equipment_hint": "巡飞定向效应弹",
                        "mission_effect": "压低无人目标持续穿透能力",
                        "operational_concept": "进入任务走廊后实施定向效应",
                    }
                ]
            },
        }
    )

    assert "## 三、总体方案" in result
    assert phases.count("report_generation_chapter_1_demand_overview") == 1
    assert phases.count("report_generation_chapter_2_equipment_image") == 1
    assert phases.count("report_generation_chapter_4_technology") == 1
    assert phases.count("report_generation_chapter_5_technical_foundation") == 1
    assert phases.count("report_generation_chapter_3_architecture") == 1
    assert phases.count("report_generation_chapter_3_architecture_retry1") == 1
    # An unchanged empty/transport root receives one primary retry before the
    # independent fallback lane; a second identical repair wave is suppressed.
    assert phases.count("report_generation_chapter_3_architecture_retry2") == 0
    assert phases.count("report_generation_chapter_3_architecture_deepseek_fallback") == 1
    assert not any(
        phase.endswith("_deepseek_fallback")
        for phase in phases
        if "chapter_3_architecture" not in phase
    )


def test_reporter_chapter_fallback_defaults_to_deepseek_provider(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    monkeypatch.setenv(
        "EQUIPMENT_DR_DEEPSEEK_BASE_URL",
        "https://api.deepseek.com/v1/chat/completions",
    )
    monkeypatch.delenv("EQUIPMENT_DR_REPORTER_CHAPTER_FALLBACK_PROFILE", raising=False)
    monkeypatch.delenv("EQUIPMENT_DR_REPORTER_CHAPTER_FALLBACK", raising=False)

    class Host:
        agent_providers = {}
        provider_factory = staticmethod(lambda name, isolation: object())
        model_profile_factory = None

    assert _reporter_chapter_fallback_profile(Host(), {}) == "deepseek"


def test_resolve_reporter_provider_uses_deepseek_env_not_openlux_profile() -> None:
    created: list[tuple[str, str]] = []

    class FakeDeepSeek:
        def snapshot(self) -> dict[str, str]:
            return {"type": "chat_completions", "provider_id": "deepseek"}

    class Host:
        agent_providers = {"reporter": ScriptedFakeProvider([])}

        def _provider_for(self, agent_id, isolation_id=""):
            del agent_id
            return self.agent_providers["reporter"]

        def provider_factory(self, name, isolation):
            created.append((name, isolation))
            return FakeDeepSeek()

        model_profile_factory = None

    selected, chain_fallback = _resolve_reporter_provider(
        Host(),
        isolation_id="run-1:chapter_1:deepseek-fallback",
        force_fallback=True,
        provider_profile="deepseek",
    )

    assert chain_fallback is False
    assert selected.snapshot()["provider_id"] == "deepseek"
    assert created == [("deepseek", "run-1:chapter_1:deepseek-fallback:deepseek")]
    assert all(name != "codex-deepseek" for name, _isolation in created)


def test_project_table_row_rejects_cross_equipment_material_attribution() -> None:
    payload = {
        "synthesis_seed": {
            "capability_cues": [
                {"direction": "验真照射末制导弹药"},
                {"direction": "差分显迹巡飞打击弹"},
            ]
        }
    }
    report = (
        "| 武器装备 | 核心技术 | 形成能力 | 作战概念与主要效果 |\n"
        "|---|---|---|---|\n"
        "| 验真照射末制导弹药 | 末段复核 | 直接毁伤 | "
        "采用差分显迹巡飞打击弹的复观材料形成结论 |"
    )

    issues = _report_equipment_attribution_issues(report, payload)

    assert any("混入其他装备材料" in issue for issue in issues)
    assert any("差分显迹巡飞打击弹" in issue for issue in issues)


def test_parallel_quality_reporter_does_not_apply_a_section_timeout(
    monkeypatch,
) -> None:
    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    captured: dict[str, object] = {}

    def capture_parallel(payload, **kwargs):
        del payload
        captured.update(kwargs)
        return "完整并行报告"

    monkeypatch.setenv("EQUIPMENT_DR_REPORT_TIMEOUT_SECONDS", "487")
    monkeypatch.setattr(provider, "_draft_parallel_report", capture_parallel)

    result = provider.draft_report(
        {
            "topic": "动态集群装备研究",
            "execution_profile_id": "winning_swarm_dynamic_v2",
        }
    )

    assert result == "完整并行报告"
    assert "timeout_seconds" not in captured


def test_limited_report_rebuilds_truncated_parallel_draft_with_all_nine_items() -> None:
    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    provider._latest_report_draft = (
        "## 第一层：需求挖掘层——场景·战法/技术·装备能力特征\n"
        "### ① 典型作战场景\n内容。\n"
        "### ② 新战法或新概念技术及制胜机理\n内容。\n"
        "### ③ 装备能力特征清单\n内容。\n"
        "## 第二层：技术攻关层——能力实现途径与核心技术\n"
        "### ④ 能力实现途径\n内容。\n"
        "### ⑤ 核心技术清单与攻关优先级\n内容。\n"
        "### ⑥ 技术耦合与短板风险\n内容。\n"
        "## 第三层：能力图像与效能贡献层\n"
        "### ⑦ 装备能力图像\n内容。\n"
        "### ⑧ 效能贡献评估\n被截断。"
    )

    result = provider._limited_report_delivery(
        {
            "topic": "无人远程火力打击装备",
            "branch_writer_brief": {"branch": "A", "hard_max_chars": 12000},
            "research_handoff": {"capability_cues": []},
        },
        failure=ValueError("parallel layer truncated"),
    )

    assert "### ⑨ 发展优先级与近期抓手" in result
    assert len(result) <= 12000


def test_project_limited_delivery_preserves_completed_model_chapter() -> None:
    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    provider._latest_report_draft = """## 一、需求分析

### （一）需求概述
#### 1. 背景分析
独特模型判断：强电磁压制改变的不是单条链路质量，而是目标包在暴露窗口内的有效寿命；必须用前出局部闭环续接远程火力。
#### 2. 需求阐述
需求从目标确认、授权、末段修正和战损评估四个断点反推，并绑定可试验的任务成功率与闭环时间口径。
#### 3. 项目画像
项目用可消耗低空平台与反辐射效应器构成窗口制造、近距确认、直接毁伤和战损回传的组合。

### （二）国内外现状
#### 1. 国外情况
公开案例只作类别基线，不外推强压制条件下的任务续接能力。
#### 2. 国内现状（中国）
国内公开基础与项目增量分开判断，接口闭合和联合验证仍是核心增量。
#### 3. 对比小结
差异化在于把压制行为转化为暴露事件，并以可消耗平台补齐目标区最后一段闭环。

### （三）建设必要性分析
#### 1. 作战使用角度
项目直接恢复受扰条件下的压制、毁伤和再攻击依据。
#### 2. 装备能力提升角度
能力建设同时校准响应、自主边界、成本交换和持续波次。
#### 3. 领域占位角度
形成可扩展平台族和统一任务接口。
#### 4. 综合效益
以任务收益、成本交换、工业补充和体系韧性联合验证。"""
    payload = {
        "topic": "强电磁压制下精确打击任务续接装备研究",
        "execution_profile_id": "winning_swarm_dynamic_v2",
        "report_template_mode": "project_argument_v1",
        "synthesis_seed": {
            "decisive_anchors": ["主链路中断后目标包快速失效。"],
            "mission_chain_breaks": ["目标确认、授权和战损评估无法连续闭合。"],
            "capability_cues": [
                {
                    "direction": "可消耗低空察打一体平台",
                    "equipment_hint": "低空可消耗无人突击平台",
                    "mission_effect": "续接目标确认并实施近距毁伤",
                    "mechanism_hint": "前出待机、局部确认、受限交战和战损摘要回传",
                }
            ],
        },
    }

    result = provider._limited_report_delivery(
        payload,
        failure=RuntimeError("one parallel chapter unavailable"),
    )

    assert "独特模型判断：强电磁压制改变的不是单条链路质量" in result
    assert all(
        heading in result
        for heading in (
            "## 一、需求分析",
            "## 二、项目画像",
            "## 三、总体方案",
            "## 四、关键技术",
            "## 五、研制基础",
        )
    )


def test_limited_completion_preserves_sibling_model_column_in_partial_chapter() -> None:
    candidate = """## 三、总体方案

### （一）总体架构
模型独有架构判断：微波拦截炮仅共享交战授权和扇区占用状态，照射控制仍由炮上火控闭合，频率失配即中止。
"""
    fallback = """## 三、总体方案

### （一）总体架构
回退架构文字不应覆盖已经完成的模型栏目。

### （二）子系统方案
回退子系统文字只用于补齐缺失栏目，并保留为可复核的证据状态。
"""

    merged = _merge_partial_report_with_limited_completion(
        candidate,
        fallback,
        {"report_template_mode": "project_argument_v1"},
    )

    assert "模型独有架构判断" in merged
    assert "回退架构文字不应覆盖" not in merged
    assert "回退子系统文字只用于补齐" in merged
    assert merged.count("## 三、总体方案") == 1


def test_dynamic_swarm_limited_delivery_replaces_template_leaking_chapter() -> None:
    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    payload = {
        "topic": "天基低时延信息支撑精确打击体系研究",
        "execution_profile_id": "winning_swarm_dynamic_v2",
        "report_template_mode": "project_argument_v1",
        "branch_writer_brief": {"branch": "G"},
        "synthesis_seed": {
            "decisive_anchors": ["机动目标状态会在跨域传递中快速过期。"],
            "mission_chain_breaks": ["目标更新、授权与效果回传无法连续闭合。"],
            "capability_cues": [
                {
                    "direction": "星隙矢",
                    "target_scenario": "敌方机动发射车短停快走并实施链路干扰时",
                    "equipment_hint": "可在飞行中接收受控更新的远程精确弹药",
                    "operational_process": ["任务装订", "低时延更新", "末段复核", "受控交战"],
                    "mission_effect": "压缩目标脱离窗口并降低空耗",
                    "boundary": "目标证据不足、授权失效或剩余机动余量不足时中止交战",
                }
            ],
        },
    }
    fallback = _build_limited_report(payload)
    flow_start = fallback.index("#### 1. 作战运用流程")
    closure_start = fallback.index("#### 2. 链路闭环分析", flow_start)
    next_section = fallback.index("### （三）体系贡献率分析", closure_start)
    provider._latest_report_draft = (
        fallback[:flow_start]
        + "#### 1. 作战运用流程\n\n"
        + "按任务准备与装订、平台部署与进入、目标发现确认、火力分配、交战毁伤、效果评估和再组织分阶段说明装备使用方式与指标口径。\n\n"
        + "#### 2. 链路闭环分析\n\n"
        + "围绕时间链、信息与精度链、火力链、毁伤评估链分析单点短板、级联风险和制胜机理。\n\n"
        + fallback[next_section:]
    )

    result = provider._limited_report_delivery(
        payload,
        failure=ValueError("dynamic parallel report contained template text"),
    )

    assert "按任务准备与装订、平台部署与进入" not in result
    assert "围绕时间链、信息与精度链" not in result
    assert "敌方机动发射车短停快走并实施链路干扰" in result
    assert "压缩目标脱离窗口并降低空耗" in result


def test_project_limited_report_uses_handoff_instead_of_template_phrases() -> None:
    result = _build_limited_report(
        {
            "topic": "强电磁压制下精确打击任务续接装备研究",
            "execution_profile_id": "swarm_quality_v1",
            "report_template_mode": "project_argument_v1",
            "synthesis_seed": {
                "decisive_anchors": ["强压制使远程目标包在短时暴露窗口内快速失效。"],
                "mission_chain_breaks": ["末段确认和毁伤评估无法持续在线。"],
                "priority_signals": ["P0验证目标区局部闭环能否恢复再攻击依据。"],
                "capability_cues": [
                    {
                        "direction": "反辐射巡飞压制效应器群",
                        "problem_statement": "持续压制源压缩精确打击窗口",
                        "equipment_hint": "可消耗反辐射巡飞效应器",
                        "mission_effect": "迫使压制源关机或暴露并制造突防窗口",
                        "winning_mechanism": "把对手压制行为转化为可捕获的辐射暴露事件",
                        "disruptive_relationship": "从被动抗扰转向主动猎杀压制收益来源",
                    }
                ],
            },
        }
    )

    assert "强压制使远程目标包在短时暴露窗口内快速失效" in result
    assert "把对手压制行为转化为可捕获的辐射暴露事件" in result
    assert "本限时版本只使用已接受交接" not in result
    assert "以comparative_findings交接为准" not in result
    assert "任务状态与授权控制层" in result
    assert "| 子系统/装备方向 | 硬件与产品形态 |" in result
    assert "| 技术名称 | 技术内涵 | 成熟度/现有基础 |" in result
    assert "不生成通用单位分工表" in result
    assert "| 单位类型 | 主要责任 | 必须交付的接口或证据 |" not in result
    assert "只保留交接中能够归属到具体武器" in result
    assert "按任务准备与装订、平台部署与进入" not in result
    assert "围绕时间链、信息与精度链" not in result
    assert "反辐射巡飞压制效应器群" in result.split("#### 1. 作战运用流程", 1)[1]
    assert "迫使压制源关机或暴露并制造突防窗口" in result


def test_project_report_gate_flags_visible_writing_instructions() -> None:
    report = """## 二、项目画像

### （一）装备图像概述

装备方向已形成。

### （二）作战运用模式

#### 1. 作战运用流程

按任务准备与装订、平台部署与进入、目标发现确认、火力分配、交战毁伤、效果评估和再组织分阶段说明装备使用方式与指标口径。

#### 2. 链路闭环分析

围绕时间链、信息与精度链、火力链、毁伤评估链分析单点短板、级联风险和制胜机理。
"""

    issues = _report_draft_quality_issues(
        report,
        {
            "report_template_mode": "project_argument_v1",
            "branch_writer_brief": {"branch": "B"},
        },
    )

    assert any("写作指令或模板占位句" in issue for issue in issues)
    assert _report_issues_require_fallback(issues) is True


def test_project_report_prompt_requires_plain_chinese_and_high_value_focus() -> None:
    prompt = _report_writer_system_prompt(
        {
            "execution_profile_id": "optimized_v2",
            "report_template_mode": "project_argument_v1",
        }
    )

    for marker in (
        "军事需求场景、装备能力提升、新技术如何进入武器与任务链、新场景如何被装备能力打开",
        "优先使用中文直述",
        "少用英文缩写和生僻词",
        "首次出现写明中文含义",
        "删除方法论解释、泛化体系口号、同义复述",
    ):
        assert marker in prompt


def test_parallel_reporter_layer_keeps_full_quality_capacity() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text="# report layer"))]]
    )
    provider = ResponsesAgentProvider(backend)
    provider.provider_kind = "codex_cli"

    result = asyncio.run(
        provider._run_reporter_text(
            "write one layer",
            {"query": "test"},
            4200,
            phase="report_generation_layer_1_demand",
        )
    )

    assert result == "# report layer"
    _, _, options = backend.inputs[0]
    assert options["reasoning_effort"] == "xhigh"
    assert options["max_output_tokens"] == 12000


@pytest.mark.parametrize(
    ("phase", "requested_tokens"),
    [
        ("deep_contextual_dialogue_divergence", 2600),
        ("deep_contextual_dialogue_critique", 3000),
        ("deep_contextual_dialogue_synthesis", 12000),
    ],
)
def test_deep_dialogue_preserves_small_round_budgets_and_allows_12000_synthesis(
    phase: str,
    requested_tokens: int,
) -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text='{"ok":true}'))]]
    )
    provider = ResponsesAgentProvider(backend)

    result = asyncio.run(
        provider._run_core_text(
            "deep_thinking_dialogue",
            "run a bounded council round",
            {"input": {"run_id": "run-deep-budget"}},
            requested_tokens,
            phase=phase,
        )
    )

    assert result == '{"ok":true}'
    _, _, options = backend.inputs[0]
    assert options["max_output_tokens"] == requested_tokens
    if phase == "deep_contextual_dialogue_synthesis":
        assert options["_provider_timeout_seconds"] == 900
        assert options["_allow_extended_provider_timeout"] is True
        assert options["_disable_provider_timeout"] is True
        assert options["_provider_retry_attempts"] == 1
    else:
        assert options["_provider_timeout_seconds"] == 300
        assert "_allow_extended_provider_timeout" not in options
        assert options["_disable_provider_timeout"] is True


def test_deep_dialogue_synthesis_retry_uses_bounded_recovery_window() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text='{"ok":true}'))]]
    )
    provider = ResponsesAgentProvider(backend)

    result = asyncio.run(
        provider._run_core_text(
            "deep_thinking_dialogue",
            "resume final authoring",
            {"input": {"run_id": "run-deep-retry"}},
            10000,
            phase="deep_contextual_dialogue_synthesis_retry",
        )
    )

    assert result == '{"ok":true}'
    _, _, options = backend.inputs[0]
    assert options["max_output_tokens"] == 10000
    assert options["_provider_timeout_seconds"] == 600
    assert options["_allow_extended_provider_timeout"] is True
    assert options["_disable_provider_timeout"] is True


def test_deep_dialogue_s6_column_has_no_hard_provider_timeout() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text='{"content":"ok"}'))]]
    )
    provider = ResponsesAgentProvider(backend)

    result = asyncio.run(
        provider._run_core_text(
            "deep_thinking_dialogue",
            "write S6 column one",
            {"input": {"run_id": "run-deep-column"}},
            4200,
            phase="deep_contextual_dialogue_s6_column_1",
        )
    )

    assert result == '{"content":"ok"}'
    _, _, options = backend.inputs[0]
    assert options["max_output_tokens"] == 4200
    assert options["_disable_provider_timeout"] is True
    assert options["_allow_extended_provider_timeout"] is True


def test_deep_dialogue_s6_technology_column_enables_governed_live_search() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text='{"content":"ok"}'))]]
    )
    provider = ResponsesAgentProvider(backend)

    result = asyncio.run(
        provider._run_core_text(
            "deep_thinking_dialogue",
            "write S6 technology implementation",
            {"input": {"run_id": "run-deep-tech-column"}},
            4200,
            phase="deep_contextual_dialogue_s6_column_2",
        )
    )

    assert result == '{"content":"ok"}'
    _, _, options = backend.inputs[0]
    assert options["web_search"] == {
        "search_context_size": "medium",
        "external_web_access": True,
    }
    assert options["include_web_sources"] is True
    assert options["require_web_search"] is False
    assert options["_disable_provider_timeout"] is False
    assert options["_provider_timeout_seconds"] == 180


def test_deep_dialogue_s6_technology_retry_does_not_repeat_live_search() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text='{"content":"ok"}'))]]
    )
    provider = ResponsesAgentProvider(backend)

    asyncio.run(
        provider._run_core_text(
            "deep_thinking_dialogue",
            "recover S6 technology implementation",
            {"input": {"run_id": "run-deep-tech-retry"}},
            4200,
            phase="deep_contextual_dialogue_s6_column_2_retry",
        )
    )

    _, _, options = backend.inputs[0]
    assert options["_disable_provider_timeout"] is False
    assert options["_provider_timeout_seconds"] == 180
    assert "web_search" not in options
    assert "include_web_sources" not in options
    assert "require_web_search" not in options


def test_deep_dialogue_s6_technology_model_recovery_does_not_repeat_live_search() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text='{"content":"ok"}'))]]
    )
    provider = ResponsesAgentProvider(backend)

    asyncio.run(
        provider._run_core_text(
            "deep_thinking_dialogue",
            "recover S6 technology implementation from model knowledge",
            {"input": {"run_id": "run-deep-tech-model-recovery"}},
            3200,
            phase="deep_contextual_dialogue_s6_column_2_model_recovery",
        )
    )

    _, _, options = backend.inputs[0]
    assert options["_disable_provider_timeout"] is False
    assert options["_provider_timeout_seconds"] == 180
    assert "web_search" not in options
    assert "include_web_sources" not in options
    assert "require_web_search" not in options


def test_deep_dialogue_s6_non_technology_column_does_not_force_live_search() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text='{"content":"ok"}'))]]
    )
    provider = ResponsesAgentProvider(backend)

    asyncio.run(
        provider._run_core_text(
            "deep_thinking_dialogue",
            "write S6 overview",
            {"input": {"run_id": "run-deep-overview-column"}},
            4200,
            phase="deep_contextual_dialogue_s6_column_1",
        )
    )

    _, _, options = backend.inputs[0]
    assert "web_search" not in options
    assert "include_web_sources" not in options
    assert "require_web_search" not in options


def test_parallel_project_chapter_uses_high_reasoning_and_section_token_cap() -> None:
    backend = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text="# report chapter"))]]
    )
    provider = ResponsesAgentProvider(backend)
    provider.provider_kind = "codex_cli"

    result = asyncio.run(
        provider._run_reporter_text(
            "write one project chapter",
            {"query": "test", "report_template_mode": "project_argument_v1"},
            2600,
            phase="report_generation_chapter_4_technology",
            isolation_id="report:chapter-4",
        )
    )

    assert result == "# report chapter"
    _, _, options = backend.inputs[0]
    assert options["reasoning_effort"] == "high"
    assert options["max_output_tokens"] == 2600
    assert options["_soft_output_token_budget"] is True
    assert options["_disable_provider_timeout"] is True


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


def test_disabled_wall_clock_deadlines_do_not_block_complete_real_run() -> None:
    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    provider.configure_run_budget(
        {
            "wall_clock_deadlines_enabled": False,
            "soft_deadline_seconds": 0,
            "hard_deadline_seconds": 0,
            "delivery_grace_seconds": 0,
            "absolute_deadline_seconds": 0,
            "maximum_model_calls": 10,
            "maximum_model_calls_with_residuals": 14,
            "maximum_swarm_model_calls": 16,
            "maximum_quality_judge_model_calls": 2,
            "maximum_delivery_model_calls": 4,
        }
    )
    provider._run_started_at -= 24 * 60 * 60

    assert provider._deadline_state(priority="swarm")["enabled"] is False
    assert provider._reserve_model_call(priority="swarm") is None
    assert provider._reserve_model_call(priority="quality_gate") is None
    assert provider._reserve_model_call(priority="delivery") is None
    assert provider._reserve_model_call(priority="normal") is None


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


def test_s6_does_not_reject_upgrade_names_with_a_local_suffix_rule() -> None:
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

    assert not any("现役升级标题禁止使用包" in issue for issue in issues)
    assert not any("现役升级名称未体现" in issue for issue in issues)


def _direct_weapon_evidence_fixture() -> list[dict[str, str]]:
    return [
        {
            "evidence_id": "ev-weapon_equipment-web-jassm",
            "created_by": "weapon_equipment",
            "source_title": "JASSM / Lockheed Martin",
            "source_url": "https://example.test/jassm",
            "claim": "JASSM-ER is an air-launched standoff cruise missile.",
        },
        {
            "evidence_id": "ev-weapon_equipment-web-prsm",
            "created_by": "weapon_equipment",
            "source_title": "First Precision Strike Missile delivery",
            "source_url": "https://example.test/prsm",
            "claim": "The Army received the first PrSM delivery.",
        },
        {
            "evidence_id": "ev-weapon_equipment-web-harop",
            "created_by": "weapon_equipment",
            "source_title": "IAI Harop",
            "source_url": "https://example.test/harop",
            "claim": "Harop is a loitering munition for attack missions.",
        },
        {
            "evidence_id": "ev-weapon_equipment-web-barracuda",
            "created_by": "weapon_equipment",
            "source_title": "Surface-Launched Barracuda-500M production",
            "source_url": "https://example.test/barracuda",
            "claim": "Barracuda-500M is a mass-producible cruise effector.",
        },
        {
            "evidence_id": "ev-weapon_equipment-web-mald",
            "created_by": "weapon_equipment",
            "source_title": "MALD decoy and MALD-J jammer variant",
            "source_url": "https://example.test/mald",
            "claim": "MALD-J is the jammer variant of the air-launched decoy.",
        },
        {
            "evidence_id": "ev-weapon_equipment-web-launched-effects",
            "created_by": "weapon_equipment",
            "source_title": "Army Launched Effects and LASSO testing",
            "source_url": "https://example.test/launched-effects",
            "claim": "Launched Effects support low-altitude sensing and attack.",
        },
    ]


def test_s6_handoff_prioritizes_full_direct_weapon_evidence_set() -> None:
    direct_rows = _direct_weapon_evidence_fixture()
    general_rows = [
        {
            "evidence_id": f"ev-general-{index}",
            "created_by": "combat_scenario",
            "source_title": f"General source {index}",
            "source_url": f"https://example.test/general-{index}",
            "claim": "General scenario evidence.",
        }
        for index in range(12)
    ]
    handoff = _capability_synthesis_handoff(
        topic="无人远程精确火力打击装备",
        branch="B",
        prior_step_outputs={
            "effect_chain": [
                {
                    "effect": "远程精确毁伤",
                    "evidence_refs": ["ev-general-0"],
                }
            ]
        },
        evidence_index=[*general_rows, *direct_rows],
    )

    selected_ids = {
        row["evidence_id"] for row in handoff["public_evidence"]
    }
    assert {row["evidence_id"] for row in direct_rows} <= selected_ids
    assert len(handoff["public_evidence"]) == 14


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
        "report_generation_layer_1_demand",
        "report_generation_chapter_1_demand",
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


def test_report_hard_max_compaction_preserves_canonical_structure() -> None:
    text = _three_layer_report(detail_count=180)
    payload = {
        "branch_writer_brief": {
            "branch": "A",
            "hard_max_chars": 12000,
        }
    }

    compacted = _enforce_report_hard_max(text, payload)

    assert len(compacted) <= 12000
    assert all(
        heading in compacted
        for heading in (
            "### ① 典型作战场景",
            "### ⑤ 核心技术清单与攻关优先级",
            "### ⑨ 发展优先级与近期抓手",
        )
    )


@pytest.mark.parametrize(
    ("execution_profile_id", "report_template_mode"),
    [
        ("swarm_quality_v1", "three_layer_nine_item"),
        ("swarm_quality_v1", "project_argument_v1"),
        ("winning_swarm_dynamic_v2", "three_layer_nine_item"),
        ("winning_swarm_dynamic_v2", "project_argument_v1"),
    ],
)
def test_quality_report_has_no_character_hard_gate(
    execution_profile_id: str,
    report_template_mode: str,
) -> None:
    report = "## 一、需求分析\n\n" + ("完整深度论证保持原句。" * 2400)
    payload = {
        "report_template_mode": report_template_mode,
        "execution_profile_id": execution_profile_id,
        "branch_writer_brief": {"branch": "B", "hard_max_chars": 12000},
    }

    assert len(report) > 20000
    assert _report_hard_max_chars(payload) == 0
    assert _enforce_report_hard_max(report, payload) == report


def test_project_quality_prompt_forbids_quality_loss_from_compression() -> None:
    prompt = _report_writer_system_prompt(
        {
            "execution_profile_id": "swarm_quality_v1",
            "report_template_mode": "project_argument_v1",
        }
    )

    assert "最低深度参照，不是字符上限" in prompt
    assert "绝不得为了压缩而删去具体装备事实" in prompt
    assert "来源映射、反证、验证边界或项目落地建议" in prompt


def test_non_quality_report_still_honors_configured_character_gate() -> None:
    payload = {
        "report_template_mode": "project_argument_v1",
        "execution_profile_id": "optimized_v2",
        "branch_writer_brief": {"branch": "B", "hard_max_chars": 12000},
    }

    assert _report_hard_max_chars(payload) == 12000


def test_report_contract_without_explicit_ceiling_is_unbounded() -> None:
    payload = {
        "report_template_mode": "three_layer_nine_item",
        "execution_profile_id": "optimized_v2",
        "branch_writer_brief": branch_writer_brief("B"),
    }

    assert payload["branch_writer_brief"]["hard_max_chars"] == 0
    assert _report_hard_max_chars(payload) == 0


@pytest.mark.parametrize(
    "direction",
    [
        {
            "name": "Barracuda/FAMM固定构型低成本巡航效应器族",
            "military_value": "持续实施战役纵深精确毁伤",
            "portfolio_role": "remote_precision_strike",
        },
        {
            "name": "远域低成本巡航弹药",
            "operational_mechanism": "防区外进入并完成精确毁伤",
            "mission_classification": "remote_precision_strike",
        },
    ],
)
def test_remote_precision_classifier_uses_structured_model_role(
    direction: dict[str, str],
) -> None:
    assert _is_remote_precision_portfolio_direction(direction) is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "B. Barracuda/FAMM类固定构型低成本巡航效应器族",
            "Barracuda/FAMM类固定构型低成本巡航效应器族",
        ),
        ("A． 批量可消耗低空携弹无人平台族", "批量可消耗低空携弹无人平台族"),
        ("1： 反辐射巡飞猎歼弹药", "反辐射巡飞猎歼弹药"),
        ("B-21远程轰炸机", "B-21远程轰炸机"),
        ("2S35自行火炮", "2S35自行火炮"),
    ],
)
def test_capability_title_removes_only_leading_enumerator(
    raw: str,
    expected: str,
) -> None:
    assert _dedupe_capability_title(raw) == expected


def test_reporter_draft_gate_rejects_punctuation_disguised_fragments() -> None:
    text = _three_layer_report(extra="在高强度对抗中。矛盾在于。作战上。体现为。")
    payload = {
        "execution_profile_id": "swarm_quality_v1",
        "branch_writer_brief": {"branch": "B", "hard_max_chars": 12000},
    }

    fragment_issues = _report_fragment_quality_issues(text)
    issues = _report_draft_quality_issues(text, payload)

    assert any("截断残句" in item for item in fragment_issues)
    assert any("截断残句" in item for item in issues)


def test_report_fragment_gate_accepts_complete_sentence_ending_with_target() -> None:
    text = _three_layer_report(
        extra="该方向不追求让弹药脱离人类授权自主选择目标。"
    )

    assert _report_fragment_quality_issues(text) == []


def test_report_fragment_gate_accepts_equipment_list_table_cell() -> None:
    text = _three_layer_report(
        extra=(
            "| 技术点 | 对应装备方向 |\n"
            "|---|---|\n"
            "| 抗扰PNT | JASSM-ER类、PrSM类、低空无人携弹平台 |"
        )
    )

    assert _report_fragment_quality_issues(text) == []


def test_report_fragment_gate_accepts_sentence_mapping_to_equipment_list() -> None:
    text = _three_layer_report(
        extra=(
            "该能力重点对应Barracuda-500M/FAMM类固定构型低成本巡航效应器族"
            "及批量可消耗低空平台。"
        )
    )

    assert _report_fragment_quality_issues(text) == []


@pytest.mark.parametrize(
    "fragment",
    [
        "为后续无人火力持续压制关。",
        "采用PrSM类地面机动发射远程精确制。",
        "把低成本巡航效应器及。",
        "形成可持续消耗任务的。",
        "以美国陆军PrSM类导弹及其现有发为对照。",
        "一旦失效会级联拖垮该。",
        "作战机理延伸到任务区自主搜索…。",
        "以末段确认降低误击风险，并以安全。",
        "在导航受扰条件下保持边界，并以末段撤销降低攻击。",
        "开展传感器—授权—发射闭环试验，确。",
        "工程承接沿任务区推进。",
        "开展工程样机和对抗试验；通过条件。",
    ],
)
def test_report_fragment_gate_rejects_real_semantic_clipping_samples(fragment: str) -> None:
    text = _three_layer_report(extra=fragment)

    issues = _report_fragment_quality_issues(text)

    assert any("截断残句" in item for item in issues)


def test_complete_phrase_clipping_never_promotes_comma_to_sentence_boundary() -> None:
    text = "任务系统完成目标更新、导航校验、末段确认，并进入后续毁伤评估。"

    clipped = _clip_complete_report_phrase(text, 30)

    assert clipped == text
    assert "末段确认。" not in clipped


def test_report_coupling_risk_keeps_conditional_and_consequence_in_one_sentence() -> None:
    item = SimpleNamespace(
        name="断链复核低成本巡航弹",
        system_dependencies=[
            "与现有指挥信息、情报侦察、保障和训练体系形成标准化接口",
            "在通信受限、数据不完备和局部节点失效条件下支持降级运行",
        ],
        risk_boundaries=[
            "失效边界：若目标机动超出任务包有效期，或末端传感器不能区分目标与诱饵，必须拒打。"
        ],
        operational_constraints=[],
        project_function=(
            "后方地面或机动发射单元在高带宽链路受阻时，发射低成本巡航弹并完成末段复核。"
        ),
        capability_outcome="形成弱网环境下可持续补射的远程消耗弹药层。",
        mission_effect="维持机场受毁后的消耗战火力密度。",
    )

    risk = _report_coupling_risk(item)
    clipped = _clip_complete_report_phrase(risk, 150)

    assert "一旦触发，断链复核低成本巡航弹将不能形成弱网环境下可持续补射的远程消耗弹药层" in risk
    assert "链路受阻时。" not in risk
    assert "一旦触发" not in clipped or "将不能" in clipped


def test_report_indicator_portrait_forwards_agent_authored_metrics() -> None:
    authored = (
        "以岛链外有效待机时长、授权后首批弹药释放时延和未用载荷安全保留率为核心测量轴；"
        "对照有人载机基线，若在位母机无法维持后续火力批次则判退。"
    )
    item = SimpleNamespace(
        name="岛链外长航时无人载弹母机",
        equipment_category="无人作战飞机",
        equipment_form="长航时低特征无人作战飞机，挂载防区外精确打击弹药",
        operational_mechanism="岛链外待机、授权分批释放、保留未用载荷和退出",
        capability_gap="前沿机场受毁后缺少空基防区外弹药释放节点",
        capability_type="new_capability",
        indicator_portrait=authored,
    )

    portrait = _report_indicator_portrait(item)

    assert portrait == authored.rstrip("。")


def test_complete_phrase_clipping_preserves_unpunctuated_judgment() -> None:
    text = "追溯研究结论并说明军事增量价值作用机理和失效边界"

    clipped = _clip_complete_report_phrase(text, 18)

    assert clipped == text
    assert "…" not in clipped


def test_empty_report_clause_is_removed_without_rewriting_prior_sentence() -> None:
    text = "近期新研方向已经明确。3至10年演进窗口的触发条件包括。"

    assert _remove_empty_report_clauses(text) == "近期新研方向已经明确。"


@pytest.mark.parametrize(
    "fragment",
    [
        "若导航欺骗识别晚于航路偏差形成。",
        "若单弹突防率或精度过低。",
        "固定构型低成本巡航效应器族的概念。",
    ],
)
def test_empty_report_clause_removes_dangling_condition_or_nominal_stub(
    fragment: str,
) -> None:
    assert _remove_empty_report_clauses(f"完整判断。{fragment}") == "完整判断。"


def test_empty_report_clause_keeps_complete_conditional() -> None:
    sentence = "若对手形成有效反制，则该机理在失效边界外不成立。"

    assert _remove_empty_report_clauses(sentence) == sentence


def test_report_hard_max_compacts_many_short_paragraphs() -> None:
    headings = [
        "## 第一层：作战需求与能力缺口",
        "### ① 典型作战场景",
        "### ② 任务链与关键矛盾",
        "### ③ 能力缺口与需求优先级",
        "## 第二层：技术体系与装备实现",
        "### ④ 能力体系与装备映射",
        "### ⑤ 核心技术清单与攻关优先级",
        "### ⑥ 工程实现、成本与产能约束",
        "## 第三层：装备组合与发展路线",
        "### ⑦ 装备能力图像",
        "### ⑧ 制胜效能与体系贡献",
        "### ⑨ 发展优先级与近期抓手",
    ]
    paragraphs = [
        "该段保持公开证据边界，说明装备能力、体系接口、失败条件和验证方向。"
        for _ in range(520)
    ]
    text = "\n\n".join([*headings, *paragraphs])
    payload = {
        "branch_writer_brief": {
            "branch": "A",
            "hard_max_chars": 12000,
        }
    }

    compacted = _enforce_report_hard_max(text, payload)

    assert len(compacted) <= 12000
    assert all(heading in compacted for heading in headings)


def test_report_hard_max_normalizes_incomplete_line_endings_below_limit() -> None:
    text = (
        "## 第一层：作战需求与能力缺口\n\n"
        "### ① 典型作战场景\n\n"
        "该方向仍需公开证据校准，\n\n"
        "- 该验证项保留失败边界；"
    )
    payload = {
        "branch_writer_brief": {
            "branch": "A",
            "hard_max_chars": 12000,
        }
    }

    compacted = _enforce_report_hard_max(text, payload)

    assert "该方向仍需公开证据校准。" in compacted
    assert "- 该验证项保留失败边界。" in compacted


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("S3候选一：受约束闭环型隐身远程导弹", "受约束闭环型隐身远程导弹"),
        ("S3-A：潜伏唤醒式巡飞猎歼弹药", "潜伏唤醒式巡飞猎歼弹药"),
        ("候选B：静默守候反辐射巡飞效应器", "静默守候反辐射巡飞效应器"),
        ("竞争分支A：去中心化空中弹舱群", "去中心化空中弹舱群"),
        ("A：批量可消耗低空无人携弹猎歼平台族", "批量可消耗低空无人携弹猎歼平台族"),
    ],
)
def test_winning_hypothesis_title_removes_internal_candidate_labels(
    raw: str,
    expected: str,
) -> None:
    assert _clean_winning_hypothesis_title(raw) == expected


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


def test_chat_completions_uses_controlled_source_priorities_when_hosted_search_is_unavailable() -> None:
    class ChatCompletionsScriptedProvider(ScriptedFakeProvider):
        def snapshot(self) -> dict[str, str]:
            return {"type": "chat_completions", "model": self.model, "base_url_host": "api.openlux.ai"}

    backend = ChatCompletionsScriptedProvider(
        [
            [ProviderStreamEvent.final(ProviderFinalTurn(
                text="检索通道已完成，但网关未返回托管来源。",
                metadata={"search_queries": ["受控来源锚点"], "web_sources": []},
            ))],
            [ProviderStreamEvent.final(ProviderFinalTurn(text=(
                '{"findings":["形成可审计的未来装备需求判断"],"confidence":0.78,'
                '"open_questions":[],"handoff_summary":"完成",'
                '"source_claims":[{"url":"https://model-claimed.example/unsupported",'
                '"claim":"模型声称的来源，仅作为待材料化线索"}]}'
            )))],
            [ProviderStreamEvent.final(ProviderFinalTurn(text=(
                '{"findings":["形成可审计的未来装备需求判断"],"confidence":0.78,'
                '"open_questions":[],"handoff_summary":"完成"}'
            )))],
        ]
    )
    agent = AgentDef("a", "武器装备", "", ["equipment"], [], {})
    result = ResponsesAgentProvider(backend).run_baseline_agent(
        AgentRunRequest(
            "run-chat-completions",
            agent,
            "未来装备需求",
            "new_winning_mechanism",
            {
                "_search_intensity": "light",
                "source_priorities": [
                    {"url": "https://www.defense.gov/official", "title": "官方公开资料"},
                    {"url": "https://www.nato.int/reference", "title": "联盟公开资料"},
                ],
            },
        )
    )

    assert result.metadata["source_anchor_fallback"] == "provider_neutral_source_anchor_fallback"
    assert result.metadata["source_anchor_count"] == 2
    assert {item.source_url for item in result.evidence} >= {
        "https://www.defense.gov/official",
        "https://www.nato.int/reference",
    }
    assert all("required_source_anchor" in item.quality_assessment for item in result.evidence if item.source_url.startswith("https://www."))
    # The model-claimed URL is a lead, not a formally accepted citation; it
    # remains subject to the same later materialization path as every other
    # source row.
    assert any(item.source_url == "https://model-claimed.example/unsupported" for item in result.evidence)


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


def test_quality_profile_bounds_equipment_discovery_straggler_context() -> None:
    backend = ScriptedFakeProvider(
        [
            [ProviderStreamEvent.final(ProviderFinalTurn(
                text=(
                    '{"findings":["形成装备需求判断"],"confidence":0.8,'
                    '"open_questions":[],"handoff_summary":"完成"}'
                ),
                metadata={"web_sources": []},
            ))],
        ]
    )
    agent = AgentDef(
        "weapon_equipment",
        "武器装备",
        "装备公开资料研究",
        ["equipment"],
        [],
        {},
        research_policy={
            "search_tracks": [f"track-{index}" for index in range(8)],
            "target_source_count": 18,
        },
    )

    ResponsesAgentProvider(backend).run_baseline_agent(
        AgentRunRequest(
            "run-quality-equipment",
            agent,
            "强电磁压制下精确打击任务续接装备研究",
            "new_winning_mechanism",
            {
                "discovery_blueprint": {
                    "execution_profile_id": "winning_swarm_dynamic_v2",
                    "primary_branch": "D",
                }
            },
        )
    )

    assert len(backend.inputs) == 1
    discovery_messages, _, discovery_options = backend.inputs[0]
    discovery_input = discovery_messages[1].content["task_input"]
    assert 4 <= discovery_input["target_source_count"] <= 6
    assert discovery_options["web_search"]["search_context_size"] == "medium"
    assert discovery_options["max_output_tokens"] == 1400
    assert discovery_options["_disable_provider_timeout"] is False
    assert discovery_options["_provider_timeout_seconds"] == 90


def test_optimized_v2_winning_timeout_returns_deterministic_fallback(monkeypatch) -> None:
    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    provider.provider_kind = "codex_cli"

    async def timeout(_payload):
        raise TimeoutError()

    monkeypatch.setattr(provider, "_analyze_winning_subagents", timeout)

    assert provider.analyze_winning_mechanism(
        {"discovery_blueprint": {"execution_profile_id": "optimized_v2"}}
    ) == {}


@pytest.mark.parametrize(
    "execution_profile_id",
    ["swarm_quality_v1", "winning_swarm_dynamic_v2"],
)
def test_quality_winning_timeout_does_not_replace_s1_s6_with_local_fallback(
    monkeypatch,
    execution_profile_id: str,
) -> None:
    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    provider.provider_kind = "codex_cli"

    async def timeout(_payload):
        raise TimeoutError("quality S1-S6 timed out")

    monkeypatch.setattr(provider, "_analyze_winning_subagents", timeout)

    with pytest.raises(TimeoutError, match="quality S1-S6 timed out"):
        provider.analyze_winning_mechanism(
            {"discovery_blueprint": {"execution_profile_id": execution_profile_id}}
        )


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


def test_concurrent_runs_use_distinct_codex_homes_and_reporter_workspaces(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = Path(__file__).parents[3]
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
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

    first = runner._select_agent_provider("real", None, run_id="run-first")
    second = runner._select_agent_provider("real", None, run_id="run-second")
    first_reporter = first._provider_for("reporter")
    second_reporter = second._provider_for("reporter")

    assert first_reporter.codex_home != second_reporter.codex_home
    assert "run-first" in str(first_reporter.codex_home)
    assert "run-second" in str(second_reporter.codex_home)
    assert first_reporter.workspace_path != second_reporter.workspace_path


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


def test_real_mode_routes_reporter_to_selected_provider_even_with_responses_baseline(
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
    assert provider._provider_for("reporter").snapshot()["type"] == "responses"


def test_real_mode_accepts_non_codex_reporter_override(
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

    provider = runner._select_agent_provider(
        "real",
        "responses",
        agent_model_profiles={
            "reporter": {
                "provider": "responses",
                "model": "gpt-test",
            }
        },
    )
    assert provider._provider_for("reporter").snapshot()["type"] == "responses"


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


@pytest.mark.parametrize("merge_target", ["S3", "S4"])
def test_dynamic_swarm_runtime_accepts_reassigned_node_through_nested_json_wrapper(
    merge_target: str,
) -> None:
    runtime = build_codex_runtime_profile(
        "winning_swarm_innovative_equipment_dimension_generator",
        payload={
            "input": {
                "input": {
                    "specialist_task": {
                        "task_id": f"dynamic-{merge_target.lower()}-creative-1",
                        "agent_instance_id": f"dynamic-{merge_target.lower()}-creative-1",
                        "archetype": "innovative_equipment_dimension_generator",
                        "merge_target": merge_target,
                        "allow_child_spawn": False,
                    },
                    # The model-call path can add another governed input wrapper
                    # around metadata while leaving specialist_task at this level.
                    # The former fixed-depth scan found the task but missed this
                    # dynamic profile marker and rejected the S3 assignment.
                    "input": {
                        "execution_profile_id": "winning_swarm_dynamic_v2",
                    },
                }
            }
        },
        phase="winning_swarm_dynamic_seed",
        compact=True,
    )

    assert runtime["mission_node"] == merge_target
    assert runtime["skill"] == {
        "S3": "新质武器概念创造",
        "S4": "跨域/反常规武器概念创造",
    }[merge_target]


@pytest.mark.parametrize("merge_target", ["S3", "S4"])
def test_dynamic_swarm_runtime_accepts_profile_marker_alongside_specialist_task(
    merge_target: str,
) -> None:
    """The live run_core_json path keeps both fields in one business payload."""
    runtime = build_codex_runtime_profile(
        "winning_swarm_innovative_equipment_dimension_generator",
        payload={
            "input": {
                "execution_profile_id": "winning_swarm_dynamic_v2",
                "specialist_task": {
                    "task_id": f"same-level-{merge_target.lower()}-creative-1",
                    "agent_instance_id": f"same-level-{merge_target.lower()}-creative-1",
                    "archetype": "innovative_equipment_dimension_generator",
                    "merge_target": merge_target,
                    "allow_child_spawn": False,
                },
            }
        },
        phase="winning_swarm_dynamic_seed",
        compact=True,
    )

    assert runtime["mission_node"] == merge_target


def test_static_swarm_runtime_still_rejects_catalog_boundary_crossing() -> None:
    with pytest.raises(
        ValueError,
        match="crossed its catalog merge boundary",
    ):
        build_codex_runtime_profile(
            "winning_swarm_innovative_equipment_dimension_generator",
            payload={
                "input": {
                    "input": {
                        "execution_profile_id": "swarm_quality_v1",
                        "specialist_task": {
                            "archetype": "innovative_equipment_dimension_generator",
                            "merge_target": "S3",
                            "allow_child_spawn": False,
                        },
                    }
                }
            },
            phase="winning_swarm_breadth",
            compact=True,
        )


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
            "winning_s1_opponent",
            "winning_s2_operations",
            "winning_s3_breakthrough",
            "winning_s4_capability",
            "winning_s5_gap",
        }:
            assert runtime["analysis_anchor"] == "query_dominant_military_divergence"
            assert "本Agent专业角色与方法第一" in runtime["query_dominance_rule"]
            assert "不得决定议题" in runtime["query_dominance_rule"]


def test_swarm_quality_runtime_keeps_full_role_methods_and_skills() -> None:
    spec = SWARM_SPECIALIST_ARCHETYPES["evidence_verifier"]
    runtime = build_codex_runtime_profile(
        "winning_swarm_evidence_verifier",
        payload={
            "execution_profile_id": "swarm_quality_v1",
            "input": {
                "execution_profile_id": "swarm_quality_v1",
                "specialist_task": {
                    "agent_instance_id": "quality-evidence-1",
                    "archetype": "evidence_verifier",
                    "display_name": spec["display_name"],
                    "purpose": spec["purpose"],
                    "merge_target": "S5",
                    "trigger_residuals": list(spec["residuals"]),
                    "allow_child_spawn": False,
                },
            },
        },
        phase="winning_swarm_dynamic_portfolio_review_fast",
        compact=True,
    )

    assert "skills" in runtime and "skill" not in runtime
    assert len(runtime["skills"]) >= 2
    assert len(runtime["methodology"]) >= 4
    assert len(runtime["quality_gates"]) >= 5
    assert runtime["active_dynamic_skill_ids"] == [
        "js-equipment-agent-runtime",
        "js-winning-shared-layer",
    ]


def test_optimized_v2_winning_call_activates_codex_runtime_skills() -> None:
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
    assert "$js-equipment-agent-runtime" in system_prompt
    assert "$js-winning-shared-layer" in system_prompt
    assert "agent_runtime.military_mission_lens" in system_prompt
    assert "打击/歼灭闭环" in runtime["military_mission_lens"]
    assert "skill" in runtime and "skills" not in runtime
    assert len(runtime["tools"]) <= 2


def test_non_codex_provider_does_not_receive_codex_skill_directives() -> None:
    provider = ResponsesAgentProvider(ScriptedFakeProvider([]))
    messages = provider._runtime_messages(
        "winning_s2_operations",
        "只输出严格JSON。",
        {
            "execution_profile_id": "swarm_quality_v1",
            "discovery_blueprint": {
                "execution_profile_id": "swarm_quality_v1",
                "primary_branch": "A",
            },
        },
        phase="winning_s2_operations",
    )

    system_prompt = str(messages[0].content)
    assert "$js-equipment-agent-runtime" not in system_prompt
    assert "$js-winning-shared-layer" not in system_prompt


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
        "report_spine",
        "research_handoff",
            "report_ready_section_map",
            "public_sources",
            "report_template_mode",
        }
    assert "high_value_clues" not in user_payload
    assert (
        user_payload["target_length"]
        == "信息闭环优先、通常7000-10000字的核心正文"
    )
    assert "立即收尾" in user_payload["length_policy"]["stop_when"]
    assert "不设统一字符硬上限" in user_payload["length_policy"]["delivery_target"]
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
    assert retry["target_length"] == "信息闭环优先、通常7000-10000字的核心正文"
    assert "立即收尾" in retry["length_policy"]["stop_when"]
    assert "不设统一字符硬上限" in retry["length_policy"]["delivery_target"]
    assert "不得触发重写" in retry["length_policy"]["overrun"]
    assert len(retry["research_handoff"]["capability_cues"]) == 7
    assert attempts[0]["output_token_budget"] == 12000
    assert attempts[0]["timeout_seconds"] == 3600
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
                        "chain_type": "强链",
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
                        "chain_type": "开链",
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
    assert "远程精确导弹的关键耦合与单点风险为" in stabilized
    assert "低空无人突击集群的关键耦合与单点风险为" in stabilized
    assert "逐装备详细能力画像如下" not in stabilized
    assert "**远程精确导弹**（强链）" in stabilized
    assert "**低空无人突击集群**（开链）" in stabilized
    assert "远程精确导弹的量化验证口径采用射程看战役纵深" in stabilized
    assert "低空无人突击集群的量化验证口径采用覆盖看低空进入半径" in stabilized
    assert stabilized.count("量化验证方向包括任务成功率") == 0
    assert "。。" not in stabilized
    assert "。；" not in stabilized

    stabilized_twice = _stabilize_report_delivery_contract(stabilized, payload)
    assert stabilized_twice == stabilized
    assert stabilized_twice.count("逐项效能、创新关系与失效边界如下") == 1
    assert stabilized_twice.count("逐装备演示验证矩阵如下") == 1
    assert stabilized_twice.count("逐装备详细能力画像如下") == 0


def test_report_delivery_stabilizer_reflows_long_prose_without_content_loss() -> None:
    sentence = "该段用于验证报告在不删减研究内容的前提下按完整句增加段落边界。"
    long_prose = sentence * 40
    report = _three_layer_report().replace(
        "对手在濒海复杂地域实施高烈度对抗，关键时间窗为首轮任务链形成前后；约束条件包括强电磁压制、低空遮蔽和补给受限。公开事实与分析推断分别标注，关键假设和反证保留。",
        long_prose,
    )

    stabilized = _stabilize_report_delivery_contract(report, {})
    prose_blocks = [
        " ".join(block.split())
        for block in re.split(r"\n\s*\n", stabilized)
        if block.strip() and not block.lstrip().startswith(("#", "|", "- ", "* "))
    ]

    assert stabilized.count(sentence) == 40
    assert "### ① 典型作战场景\n\n" in stabilized
    assert all(len(block) <= 1050 for block in prose_blocks)
    assert _stabilize_report_delivery_contract(stabilized, {}) == stabilized


def test_report_stabilizer_does_not_repeat_same_failure_boundary_three_times() -> None:
    name = "有限区搜索远程反舰巡航弹药"
    boundary = (
        "在远洋、目标密集或中立船舶众多场景中，识别与授权边界更严格，收益下降。"
    )
    report = _three_layer_report()
    payload = {
        "synthesis_seed": {
            "capability_cues": [
                {
                    "direction": name,
                    "capability_portrait": (
                        "概述：面向受扰海上交战场景，针对外部航迹中断，利用弹上有限区搜索原理，"
                        "采用多模末制导与抗干扰导航，通过装订、进入、复核和受控交战，形成断链后"
                        "再捕获能力，实现对经授权水面目标的直接毁伤。\n"
                        "- 装备与技术实现：集成弹载感知、任务计算和安全授权。\n"
                        "- 关键作战流程：完成装订、进入、复核、交战和中止。\n"
                        "- 形成能力与作战效果：形成直接反舰毁伤贡献。\n"
                        "- 制胜逻辑机理与对抗边界：以有限搜索替代持续外部更新。\n"
                        "- 发展与验证路径：开展半实物、靶场和红队验证。"
                    ),
                    "mission_effect": "断链后继续再捕获并直接毁伤经授权水面目标",
                    "mechanism_hint": (
                        "按目标误差边界装订任务→弹药进入有限搜索区→末段完成多模复核"
                    ),
                    "coupling_risk": f"弹载识别与安全授权串联耦合；{boundary}",
                    "boundary": boundary,
                }
            ]
        }
    }

    stabilized = _stabilize_report_delivery_contract(report, payload)
    matrix = stabilized.split("逐装备演示验证矩阵如下", 1)[1]

    assert matrix.count(boundary) == 1
    assert "起始条件检验：按目标误差边界装订任务" in matrix
    assert "任务动作检验：弹药进入有限搜索区" in matrix
    assert "闭环结果检验：末段完成多模复核" in matrix
    assert (
        f"失败条件是上述{name}适用场景或反适应边界被触发，且直接作战贡献未达到任务基线"
        in matrix
    )
    assert _stabilize_report_delivery_contract(stabilized, payload) == stabilized


def test_project_report_stabilizer_does_not_invent_missing_capability_table() -> None:
    report = """## 二、项目画像

### （一）装备图像概述

Reporter先写了一段综合判断，但遗漏了能力方向对照表。

### （二）作战运用模式

#### 1. 作战运用流程

流程正文。

#### 2. 链路闭环分析

闭环正文。

### （三）体系贡献率分析

贡献哨兵：该装备改变的是目标航迹过期后任务被迫终止的结果。

### （四）主要战技指标

指标哨兵：以有界搜索中的误击拒止能力检验核心判断。
"""
    names = [f"具体武器装备方向{index}" for index in range(1, 6)]
    payload = {
        "report_template_mode": "project_argument_v1",
        "synthesis_seed": {
            "capability_cues": [
                {
                    "direction": name,
                    "equipment_hint": f"{name}平台与载荷",
                    "enabling_technologies": [f"{name}制导与任务接口"],
                    "capability_outcome": f"形成{name}直接作战能力",
                    "operational_concept": f"{name}完成部署、交战与再组织",
                    "mission_effect": f"{name}形成直接毁伤贡献",
                }
                for name in names
            ]
        },
    }

    stabilized = _stabilize_report_delivery_contract(report, payload)
    assert "Reporter先写了一段综合判断" in stabilized
    assert "贡献哨兵：该装备改变的是目标航迹过期后任务被迫终止的结果。" in stabilized
    assert "指标哨兵：以有界搜索中的误击拒止能力检验核心判断。" in stabilized
    assert "| 装备系统方向 |" not in stabilized
    assert "逐装备体系贡献" not in stabilized
    assert "逐装备主要战技指标与验证矩阵" not in stabilized
    assert not any(name in stabilized for name in names)
    assert _stabilize_report_delivery_contract(stabilized, payload) == stabilized


def test_report_stabilizer_replaces_orphaned_portrait_titles_once() -> None:
    name = "远程精确打击武器"
    orphaned = (
        f"**{name}｜装备能力画像**\n\n"
        f"**{name}｜装备能力画像**\n\n"
        "逐装备详细能力画像如下；旧块将在本次重建。"
    )
    report = _three_layer_report().replace(
        "### ⑧ 效能贡献评估",
        f"{orphaned}\n\n### ⑧ 效能贡献评估",
        1,
    )
    payload = {
        "synthesis_seed": {
            "capability_cues": [
                {
                    "direction": name,
                    "capability_portrait": (
                        "概述：形成直接作战能力。\n"
                        "- 装备与技术实现：集成平台、载荷与任务系统。\n"
                        "- 关键作战流程：完成部署、确认与交战。"
                    ),
                    "mission_effect": "形成直接毁伤贡献",
                }
            ]
        }
    }

    stabilized = _stabilize_report_delivery_contract(report, payload)

    assert stabilized.count(f"**{name}｜装备能力画像**") == 1
    assert "- 装备与技术实现：" in stabilized
    assert _stabilize_report_delivery_contract(stabilized, payload) == stabilized


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


def test_reporter_capability_cue_handoff_has_no_default_quota(monkeypatch) -> None:
    cues = [
        {
            "direction": f"具体装备方向{index}",
            "mission_effect": f"形成直接作战效果{index}",
            "mechanism_hint": f"按装备专属流程交战{index}",
        }
        for index in range(15)
    ]
    payload = {
        "topic": "强干扰弱通信条件下装备研究",
        "report_template_mode": "project_argument_v1",
        "synthesis_seed": {"capability_cues": cues},
    }

    generation = _reporter_generation_payload(payload)
    retry = _reporter_timeout_retry_payload(payload)
    assert len(generation["research_handoff"]["capability_cues"]) == 15
    assert len(retry["research_handoff"]["capability_cues"]) == 15

    monkeypatch.setenv("EQUIPMENT_DR_REPORT_CAPABILITY_CUE_LIMIT", "5")
    limited = _reporter_generation_payload(payload)
    limited_retry = _reporter_timeout_retry_payload(payload)
    assert len(limited["research_handoff"]["capability_cues"]) == 5
    assert len(limited_retry["research_handoff"]["capability_cues"]) == 5


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

    fragmented_portrait = _sanitize_reporter_output(
        "概述：装备改变低空拦截交换。装备与技术实现：弹载传感器与战斗部闭合。"
        "关键作战流程：完成授权后进入拦阻区。形成能力与作战效果：形成持续拒止。"
        "制胜逻辑机理：把逐架交战改为波次交战。"
    )
    assert "。\n装备与技术实现：" in fragmented_portrait
    assert "。\n关键作战流程：" in fragmented_portrait
    assert "。\n形成能力与作战效果：" in fragmented_portrait
    assert "。\n制胜逻辑机理：" in fragmented_portrait


def test_reporter_gate_preserves_all_input_directions_without_rejudging_relationship_count() -> None:
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
    assert not any("至少需要3类" in issue for issue in shallow_issues)


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
    assert "先解析任务对象、威胁形态、作战阶段、地域环境和制胜矛盾" in system_prompt
    assert "未触发时不得进入候选组合或报告目录" in system_prompt
    assert "直接承担侦察打击、突防、歼灭、压制、拦截、毁伤或区域拒止" in system_prompt
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
    assert "最终报告可随论证完整度自然超过核心正文目标" in system_prompt
    assert "不得为追逐字数重复论证" in system_prompt
    assert "绝对交付硬上限" not in system_prompt


def test_report_seed_copy_gate_allows_one_exact_technical_sentence() -> None:
    sentence = (
        "固定被动射频提示只驱动预鉴定响应选择器，并复用既有电子攻击载荷；"
        "接口公开不足属于工程验证风险，不证明既有闭环能力；同时必须验证收发隔离、"
        "功耗、散热、电磁兼容和统计显著性。"
    )
    payload = {"synthesis_seed": {"capability_portrait": sentence}}

    assert _report_seed_copy_issues(f"技术边界：{sentence}", payload) == []


def test_report_seed_copy_gate_rejects_long_or_repeated_material_splicing() -> None:
    long_seed = "".join(f"第{index}项研判说明任务链、装备身份、反证边界与验证计划。" for index in range(12))
    payload = {"synthesis_seed": {"capability_portrait": long_seed}}

    issues = _report_seed_copy_issues(long_seed, payload)

    assert any("长段原句复用" in item for item in issues)


def test_report_fragment_gate_accepts_complete_stage_classification_sentence() -> None:
    sentence = "从任务阶段看，典型作战可拆成五个相互压迫的阶段。"

    assert _report_fragment_quality_issues(sentence) == []


def test_report_fragment_gate_accepts_complete_capability_definition_sentences() -> None:
    text = (
        "通过被动射频、光电、行为特征或景象匹配对候选目标或航路状态进行确认的能力。\n"
        "在平台损失、节点失效和链路受扰后，体系仍能维持任务波次和闭环的能力。"
    )

    assert _report_fragment_quality_issues(text) == []


def test_report_fragment_gate_accepts_complete_risk_and_participation_sentences() -> None:
    text = (
        "连续遥控不可假设，外部目标更新可能中断；若授权规则、禁击规则与平台自主边界不一致，"
        "容易出现错失战机或越界风险。\n"
        "远程精确毁伤方向需要空射、地面发射或兼容平台的接口单位参与。"
    )

    assert _report_fragment_quality_issues(text) == []


def test_report_stabilizer_completes_isolated_validation_condition_label() -> None:
    stabilized = _stabilize_report_delivery_contract(
        "验证矩阵保留失败边界；通过条件。",
        {},
    )

    assert "通过条件需在对应试验场景、基线与统计口径下明确。" in stabilized
    assert _report_fragment_quality_issues(stabilized) == []


def test_report_fragment_gate_accepts_structured_content_lead_in() -> None:
    text = (
        "逐装备承接关系如下。\n\n"
        "| 装备方向 | 验证边界 |\n"
        "|---|---|\n"
        "| 远程精确毁伤装备 | 代表性干扰条件下验证 |"
    )

    assert _report_fragment_quality_issues(text) == []


def test_reporter_handoff_marks_long_prose_for_rewrite_without_deleting_content() -> None:
    mechanism = (
        "面向强电磁压制与弱通信条件，现役平台先完成黑盒基线表征并固化安全边界。"
        "固定被动射频提示只驱动预鉴定响应选择器，复用既有电子攻击载荷。"
        "随后验证收发隔离、功耗、散热、电磁兼容、统计显著性与任务收益。"
    )
    portrait = (
        "概述：" + ("本弹把压制源持续开机改写为测向标定入口，" * 12)
        + "装备与技术实现：" + ("主攻弹载测向与逆程宽束耦合，" * 12)
    )

    generation = _reporter_generation_payload(
        {
            "execution_profile_id": "baseline_v1",
            "synthesis_seed": {
                "capability_cues": [
                    {
                        "direction": "A. MALD-J弹上威胁感知闭环电子攻击效应器",
                        "problem_statement": mechanism,
                        "capability_portrait": portrait,
                    }
                ]
            },
        },
        None,
    )
    cue = generation["research_handoff"]["capability_cues"][0]
    marked = cue["problem_statement"]
    direction = cue["direction"]

    assert direction == "MALD-J弹上威胁感知闭环电子攻击效应器"
    assert "〔改写断点：保留事实但不得照录〕" in marked
    assert marked.replace("〔改写断点：保留事实但不得照录〕", "") == mechanism
    assert max(
        len(item)
        for item in marked.split("〔改写断点：保留事实但不得照录〕")
    ) <= 56
    # S6 portraits must remain intact so parallel columns can synthesize them.
    assert cue["capability_portrait"] == portrait
    assert "〔改写断点：保留事实但不得照录〕" not in cue["capability_portrait"]


def test_reporter_output_sanitizer_removes_internal_rewrite_boundaries() -> None:
    text = (
        "| A. 批量可消耗低空无人携弹平台 | 完整事实前半句"
        "〔改写断点：保留事实但不得照录〕完整事实后半句。 |"
    )

    assert _sanitize_reporter_output(text) == (
        "| 批量可消耗低空无人携弹平台 | 完整事实前半句完整事实后半句。 |"
    )


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
        assert "具体类别必须服从Query语义简报" in system_prompt
        assert "未触发类别不得为增加多样性或凑齐目录而生成" in system_prompt
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


def test_reporter_quality_gate_repairs_structurally_incomplete_core_branch_draft() -> None:
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
    assert not any("最低门槛" in item for item in issues)
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
    assert "以直接承担侦察打击" in prompt


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
    assert not any("军事运用价值不足" in item for item in issues)
    assert not any("因果论证不足" in item for item in issues)
    assert not any("装备决策不足" in item for item in issues)


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
    assert options["max_output_tokens"] == 12000
    assert options["reasoning_effort"] == "xhigh"
    assert options["prompt_mode"] == "standalone"


def test_project_report_structure_allows_repeated_parenthetical_h3_labels() -> None:
    text = "\n".join(
        (
            "## 一、需求分析",
            "### （一）需求概述",
            "#### 1. 背景分析",
            "#### 2. 需求阐述",
            "#### 3. 项目画像",
            "### （二）国内外现状",
            "#### 1. 国外情况",
            "#### 2. 国内现状（中国）",
            "#### 3. 对比小结",
            "### （三）建设必要性分析",
            "#### 1. 作战使用角度",
            "#### 2. 装备能力提升角度",
            "#### 3. 领域占位角度",
            "#### 4. 综合效益",
            "## 二、项目画像",
            "### （一）装备图像概述",
            "### （二）作战运用模式",
            "#### 1. 作战运用流程",
            "#### 2. 链路闭环分析",
            "### （三）体系贡献率分析",
            "### （四）主要战技指标",
            "## 三、总体方案",
            "### （一）总体架构",
            "### （二）子系统方案",
            "## 四、关键技术",
            "### （一）关键技术清单与攻关途径",
            "## 五、研制基础",
            "### （一）参与单位",
            "### （二）技术基础",
        )
    )

    issues = _report_markdown_structure_issues(
        text,
        {"report_template_mode": "project_argument_v1"},
    )

    assert not any("重复" in issue for issue in issues)
    assert not any("顺序混乱" in issue for issue in issues)


def test_project_report_normalizer_restores_uniquely_implied_parent_heading() -> None:
    draft = "\n".join(
        (
            "## 二、项目画像",
            "### （四）主要战技指标",
            "指标正文。",
            "### （一）总体架构",
            "总体架构正文。",
            "### （二）子系统方案",
            "子系统方案正文。",
            "## 四、关键技术",
            "### （一）关键技术清单与攻关途径",
            "关键技术正文。",
        )
    )

    normalized = _normalize_report_structure_deterministically(draft)

    assert normalized.count("## 三、总体方案") == 1
    assert normalized.index("## 三、总体方案") < normalized.index(
        "### （一）总体架构"
    )
    assert "总体架构正文。" in normalized
    assert "子系统方案正文。" in normalized


def test_project_report_normalizer_splits_heading_stuck_to_completed_sentence() -> None:
    draft = "## 二、项目画像\n结论不得提前承诺点值。## 三、总体方案\n### （一）总体架构\n正文。"

    normalized = _normalize_report_structure_deterministically(draft)

    assert "结论不得提前承诺点值。\n\n## 三、总体方案" in normalized
    assert normalized.count("## 三、总体方案") == 1
    assert "### （一）总体架构" in normalized


def test_project_report_normalizer_does_not_split_plain_inline_hash_text() -> None:
    draft = "## 二、项目画像\n正文说明版本##draft仍需复核。"

    normalized = _normalize_report_structure_deterministically(draft)

    assert "正文说明版本##draft仍需复核。" in normalized


def test_project_report_normalizer_keeps_h4_labels_at_h4_depth() -> None:
    draft = "\n".join(
        (
            "## 一、需求分析",
            "### （一）需求概述",
            "#### 1. 背景分析",
            "背景正文。",
            "#### 2. 需求阐述",
            "需求正文。",
            "#### 3. 项目画像",
            "画像正文。",
        )
    )

    normalized = _normalize_report_structure_deterministically(draft)

    assert "#### 1. 背景分析" in normalized
    assert "#### 2. 需求阐述" in normalized
    assert "#### 3. 项目画像" in normalized
    assert "### ① 典型作战场景" not in normalized


def test_project_report_normalizer_does_not_drop_h3_containing_chapter_name() -> None:
    draft = "\n".join(
        (
            "## 四、关键技术",
            "### （一）关键技术清单与攻关途径",
            "关键技术正文。",
        )
    )

    normalized = _normalize_report_structure_deterministically(draft)

    assert "## 四、关键技术" in normalized
    assert "### （一）关键技术清单与攻关途径" in normalized
    assert "关键技术正文。" in normalized


def test_report_template_mode_follows_run_config_and_nested_payload() -> None:
    nested = {
        "generation": {"report_template_mode": "project_argument_v1"},
        "report_context": {"report_template_mode": "three_layer_nine_item"},
    }

    assert _report_template_mode(nested) == "project_argument_v1"
    assert (
        _report_template_mode(
            {"report_template_mode": "three_layer_nine_item"},
            nested,
        )
        == "three_layer_nine_item"
    )
    generation = _reporter_generation_payload(
        {
            "topic": "模板贯通",
            "generation": {"report_template_mode": "project_argument_v1"},
        },
        None,
    )
    assert generation["report_template_mode"] == "project_argument_v1"
    assert list(generation["format_contract"]["h2"]) == [
        "一、需求分析",
        "二、项目画像",
        "三、总体方案",
        "四、关键技术",
        "五、研制基础",
    ]
    legacy = _reporter_generation_payload(
        {
            "topic": "模板贯通",
            "report_template_mode": "three_layer_nine_item",
        },
        None,
    )
    assert legacy["report_template_mode"] == "three_layer_nine_item"
    assert list(legacy["format_contract"]["h2"])[0].startswith("第一层")
    retry = _reporter_timeout_retry_payload(
        {"topic": "模板贯通", "report_template_mode": "project_argument_v1"}
    )
    assert retry["report_template_mode"] == "project_argument_v1"


def test_project_template_does_not_rewrite_h4_project_portrait_into_three_layer() -> None:
    payload = {"report_template_mode": "project_argument_v1"}
    draft = "\n".join(
        (
            "## 一、需求分析",
            "### （一）需求概述",
            "### 3. 项目画像",
            "画像正文。",
        )
    )

    assert _canonical_report_h3("3. 项目画像", "project_argument_v1") == ""
    normalized = _normalize_report_structure_deterministically(draft, payload)

    assert "#### 3. 项目画像" in normalized
    assert "### ① 典型作战场景" not in normalized
    assert "### ③ 装备能力特征清单" not in normalized
    assert "画像正文。" in normalized


def test_three_layer_template_is_not_rewritten_into_five_chapters() -> None:
    payload = {"report_template_mode": "three_layer_nine_item"}
    draft = "\n".join(
        (
            "## 第一层：需求挖掘层——场景·战法/技术·装备能力特征",
            "### ① 典型作战场景",
            "场景正文。",
            "## 第二层：技术攻关层——能力实现途径与核心技术",
            "### ⑤ 核心技术清单与攻关优先级",
            "关键技术正文。",
            "## 第三层：能力图像与效能贡献层",
            "### ⑦ 装备能力图像",
            "画像正文。",
        )
    )

    normalized = _normalize_report_structure_deterministically(draft, payload)

    assert "## 四、关键技术" not in normalized
    assert "## 二、项目画像" not in normalized
    assert "### （一）装备图像概述" not in normalized
    assert "### ⑦ 装备能力图像" in normalized
    assert "### ① 典型作战场景" in normalized
    assert not _report_has_complete_canonical_structure(normalized, payload)
    assert _report_has_complete_canonical_structure(
        "\n".join(
            (
                "## 一、需求分析",
                "### （一）需求概述",
            )
        ),
        {"report_template_mode": "three_layer_nine_item"},
    ) is False


def test_project_template_keeps_equipment_overview_heading() -> None:
    payload = {"report_template_mode": "project_argument_v1"}
    draft = "\n".join(
        (
            "## 二、项目画像",
            "### （一）装备图像概述",
            "| 武器装备 | 核心技术 | 形成能力 | 作战概念与主要效果 |",
            "| --- | --- | --- | --- |",
            "| 巡飞弹 | 末段识别 | 临机毁伤 | 前出待战 |",
        )
    )

    normalized = _normalize_report_structure_deterministically(draft, payload)

    assert "### （一）装备图像概述" in normalized
    assert "### ⑦ 装备能力图像" not in normalized
    assert "| 武器装备 | 核心技术 | 形成能力 | 作战概念与主要效果 |" in normalized


def test_report_stabilizer_does_not_reauthor_bad_project_image_table() -> None:
    direction = "低空可消耗察打一体无人突击平台续接目标证据链"
    long_text = "强干扰条件下的跨域任务续接、目标复核、精确打击与战损评估。" * 20
    draft = """## 二、项目画像

### （一）装备图像概述

| 装备系统方向 | 装备平台与方案 | 核心技术 | 形成能力 | 作战概念与主要效果 |
|---|---|---|---|---|
| 临时方向 | 临时方案 | 临时技术 | 临时能力 | 临时概念 |

### （二）作战运用模式
"""
    result = _stabilize_report_delivery_contract(
        draft,
        {
            "report_template_mode": "project_argument_v1",
            "research_handoff": {
                "capability_cues": [
                    {
                        "direction": f"A. {direction}",
                        "equipment_hint": (
                            "强干扰条件下的跨域任务续接、目标复核、"
                            "〔改写断点：保留事实但不得照录〕精确打击与战损评估。"
                        ),
                        "enabling_technologies": [long_text],
                        "capability_outcome": long_text,
                        "operational_concept": long_text,
                        "mission_effect": long_text,
                    }
                ]
            },
        },
    )

    assert "临时方向" in result
    assert direction not in result
    assert any(
        "表头必须合并为四列" in issue
        for issue in _report_table_issues(result, project_mode=True)
    )


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
