"""Reporter workflow service using the provider host as its runtime port."""
# ruff: noqa: F821

from __future__ import annotations

from equipment_deep_research.agents.workflows import coordinator as _legacy

globals().update(
    {name: value for name, value in vars(_legacy).items() if not name.startswith("__")}
)

def draft_report(host, payload: dict[str, Any]) -> str:
    host._last_report_quality_issues = []
    host._latest_report_draft = ""
    portfolio_gate = payload.get("portfolio_quality_gate", {})
    if (
        str(payload.get("execution_profile_id", ""))
        == "winning_swarm_dynamic_v2"
        and isinstance(portfolio_gate, Mapping)
        and portfolio_gate
        and not bool(portfolio_gate.get("passed"))
        and not (
            not bool(portfolio_gate.get("direct_equipment_diversity_passed", True))
            and bool(portfolio_gate.get("direct_combat_main_body_passed"))
            and bool(portfolio_gate.get("capability_portrait_gate_passed"))
            and bool(portfolio_gate.get("equipment_diversity_passed"))
            and bool(portfolio_gate.get("expert_judge_passed"))
            and str(portfolio_gate.get("expert_judge_status", "")) == "completed"
            and not portfolio_gate.get("hard_blockers")
        )
    ):
        raise ValueError(
            "winning swarm portfolio quality gate failed before Reporter: "
            f"directions={portfolio_gate.get('direction_count', 0)}, "
            "direct_equipment="
            f"{portfolio_gate.get('direct_combat_equipment_count', 0)}, "
            "distinct_direct_families="
            f"{portfolio_gate.get('distinct_direct_equipment_family_count', 0)}, "
            "required_distinct_direct_families="
            f"{portfolio_gate.get('preferred_distinct_direct_equipment', 1)}"
        )
    # Reporter normal mode is deliberately quality-first: xhigh, a real
    # 12k output ceiling, and a bounded but long-form main attempt. Reporter
    # is explicitly exempt from runtime reasoning/token downshift; upstream
    # stages absorb deadline pressure instead.
    report_timeout_default = (
        "900"
        if str(payload.get("execution_profile_id", ""))
        in {"swarm_quality_v1", "winning_swarm_dynamic_v2"}
        else "3600"
    )
    timeout_seconds = min(
        3600.0,
        max(
            30.0,
            float(
                os.environ.get(
                    "EQUIPMENT_DR_REPORT_TIMEOUT_SECONDS",
                    report_timeout_default,
                )
            ),
        ),
    )
    if str(payload.get("execution_profile_id", "")) in {
        "swarm_quality_v1",
        "winning_swarm_dynamic_v2",
    }:
        # An explicit legacy 3600-second environment value must not turn
        # a bounded quality delivery into an unbounded tail. Fifteen
        # minutes leaves room for a deep Codex CLI synthesis while still
        # guaranteeing a resumable delivery path.
        # Operators can still lower this through the environment.
        timeout_seconds = min(timeout_seconds, 900.0)
    retry_timeout_seconds = min(
        180.0,
        max(
            30.0,
            float(
                os.environ.get(
                    "EQUIPMENT_DR_REPORT_RETRY_TIMEOUT_SECONDS",
                    "180",
                )
            ),
        ),
    )
    reporter_agent = host.agent_definitions.get("reporter")
    reporter_input = _reporter_generation_payload(payload, reporter_agent)
    output_token_budget = _reporter_output_token_budget(payload, default=12000)
    if (
        str(payload.get("execution_profile_id", ""))
        in {"swarm_quality_v1", "winning_swarm_dynamic_v2"}
        and os.environ.get("EQUIPMENT_DR_PARALLEL_REPORTER", "1") != "0"
    ):
        try:
            return host._draft_parallel_report(
                payload,
                reporter_input=reporter_input,
                output_token_budget=output_token_budget,
            )
        except (TimeoutError, ProviderRequestError, ValueError, RuntimeError) as exc:
            # Quality modes must not reintroduce an unbounded serial tail
            # after parallel layers finish. Preserve the best
            # assembled draft and deterministically complete the delivery
            # contract instead of launching a monolithic Reporter retry.
            return host._limited_report_delivery(payload, failure=exc)
    try:
        return host._draft_report_attempt(
            payload,
            reporter_agent=reporter_agent,
            reporter_input=reporter_input,
            output_token_budget=output_token_budget,
            timeout_seconds=timeout_seconds,
            phase="report_generation",
            allow_repair=False,
            allow_limited=False,
        )
    except (TimeoutError, ProviderRequestError, ValueError, RuntimeError) as exc:
        # A completed model response rejected by the delivery gate is not
        # a transport failure.  Keep that independent draft as a limited
        # delivery instead of paying for another full report.
        if isinstance(exc, ValueError) and not isinstance(exc, ProviderRequestError):
            return host._limited_report_delivery(payload, failure=exc)
        if (
            isinstance(exc, RuntimeError)
            and not isinstance(exc, ProviderRequestError)
            and not _is_harness_budget_error(exc)
        ):
            return host._limited_report_delivery(payload, failure=exc)
        retry_state = host._deadline_state(priority="delivery")
        retry_remaining = float(retry_state.get("remaining_seconds") or 0.0)
        if retry_state.get("enabled") and retry_remaining < 45.0:
            return host._limited_report_delivery(payload, failure=exc)
        retry_input = dict(reporter_input)
        retry_input["retry_instruction"] = (
            "上一完整质量调用因传输或运行时异常未完成。仍按原三层九项合同、xhigh推理"
            "和12000 tokens上限独立重写完整报告，不得压缩为限时版或降低研究深度。"
        )
        if retry_state.get("enabled"):
            retry_timeout_seconds = min(
                retry_timeout_seconds,
                max(30.0, retry_remaining - 5.0),
            )
        try:
            return host._draft_report_attempt(
                payload,
                reporter_agent=reporter_agent,
                reporter_input=retry_input,
                output_token_budget=output_token_budget,
                timeout_seconds=retry_timeout_seconds,
                phase="report_generation_full_quality_retry",
                allow_repair=False,
                allow_limited=False,
            )
        except (TimeoutError, ProviderRequestError, ValueError, RuntimeError) as retry_exc:
            return host._limited_report_delivery(
                payload,
                failure=retry_exc,
            )


def draft_parallel_report(
    host,
    payload: Mapping[str, Any],
    *,
    reporter_input: dict[str, Any],
    output_token_budget: int,
) -> str:
    """Generate every top-level section concurrently without a hard cutoff."""

    legacy_sections = (
        (
            "layer_1_demand",
            "第一层：需求挖掘层——场景·战法/技术·装备能力特征",
            [
                "① 典型作战场景",
                "② 新战法或新概念技术及制胜机理",
                "③ 装备能力特征清单",
            ],
            3200,
            4000,
            [],
        ),
        (
            "layer_2_technology",
            "第二层：技术攻关层——能力实现途径与核心技术",
            [
                "④ 能力实现途径",
                "⑤ 核心技术清单与攻关优先级",
                "⑥ 技术耦合与短板风险",
            ],
            3200,
            4000,
            [],
        ),
        (
            "layer_3_portfolio",
            "第三层：能力图像与效能贡献层",
            [
                "⑦ 装备能力图像",
                "⑧ 效能贡献评估",
                "⑨ 发展优先级与近期抓手",
            ],
            4000,
            4000,
            [],
        ),
    )
    project_sections = (
        (
            "chapter_1_demand",
            "一、需求分析",
            [
                "（一）需求概述",
                "（二）国内外现状",
                "（三）建设必要性分析",
            ],
            3900,
            4000,
            [],
        ),
        (
            "chapter_2_portrait",
            "二、项目画像",
            [
                "（一）装备图像概述",
                "（二）作战运用模式",
                "（三）体系贡献率分析",
                "（四）主要战技指标",
            ],
            5600,
            8000,
            [],
        ),
        (
            "chapter_3_solution",
            "三、总体方案",
            ["（一）总体架构", "（二）子系统方案"],
            1700,
            4000,
            [],
        ),
        (
            "chapter_4_technology",
            "四、关键技术",
            ["（一）关键技术清单与攻关途径"],
            1700,
            4000,
            [],
        ),
        (
            "chapter_5_foundation",
            "五、研制基础",
            ["（一）参与单位", "（二）技术基础"],
            1200,
            4000,
            [],
        ),
    )
    project_mode = _report_template_mode(payload) == "project_argument_v1"
    sections = project_sections if project_mode else legacy_sections
    project_layer_handoff_keys = {
        "chapter_1_demand": {
            "decisive_anchors",
            "mission_chain_breaks",
            "counterevidence_and_limits",
            "priority_signals",
            "comparative_status",
            "capability_cues",
        },
        "chapter_2_portrait": {
            "mission_chain_breaks",
            "counterevidence_and_limits",
            "capability_cues",
        },
        "chapter_3_solution": {
            "counterevidence_and_limits",
            "capability_cues",
        },
        "chapter_4_technology": {
            "counterevidence_and_limits",
            "capability_cues",
        },
        "chapter_5_foundation": {
            "counterevidence_and_limits",
            "comparative_status",
            "capability_cues",
        },
    }
    project_layer_cue_fields = {
        "chapter_1_demand": {
            "direction",
            "target_scenario",
            "problem_statement",
            "capability_gap",
            "mission_effect",
            "public_equipment_baseline",
            "future_trigger",
            "disruptive_relationship",
            "priority",
            "boundary",
        },
        "chapter_2_portrait": {
            "direction",
            "mission_effect",
            "capability_gap",
            "mechanism_hint",
            "target_scenario",
            "problem_statement",
            "scientific_principle",
            "operational_concept",
            "operational_process",
            "capability_outcome",
            "winning_mechanism",
            "equipment_hint",
            "public_equipment_baseline",
            "future_trigger",
            "disruptive_relationship",
            "development_path",
            "indicator_portrait",
            "coupling_risk",
            "priority",
            "boundary",
            "enabling_technologies",
        },
        "chapter_3_solution": {
            "direction",
            "equipment_hint",
            "scientific_principle",
            "enabling_technologies",
            "operational_concept",
            "operational_process",
            "capability_outcome",
            "development_path",
            "coupling_risk",
            "boundary",
        },
        "chapter_4_technology": {
            "direction",
            "equipment_hint",
            "scientific_principle",
            "enabling_technologies",
            "coupling_risk",
            "boundary",
            "indicator_portrait",
            "priority",
        },
        "chapter_5_foundation": {
            "direction",
            "equipment_hint",
            "enabling_technologies",
            "development_path",
            "coupling_risk",
            "boundary",
            "indicator_portrait",
            "public_equipment_baseline",
            "priority",
        },
    }
    async def generate_layers() -> list[str]:
        calls = []
        for layer_id, h2, h3s, target_chars, token_cap, additional_h2s in sections:
            layer_input = dict(reporter_input)
            if project_mode:
                handoff = layer_input.get("research_handoff", {})
                if isinstance(handoff, Mapping):
                    allowed_handoff_keys = project_layer_handoff_keys[layer_id]
                    compact_handoff = {
                        key: value
                        for key, value in handoff.items()
                        if key in allowed_handoff_keys
                    }
                    cues = compact_handoff.get("capability_cues", [])
                    if isinstance(cues, Sequence) and not isinstance(
                        cues, (str, bytes)
                    ):
                        allowed_cue_fields = project_layer_cue_fields[layer_id]
                        compact_handoff["capability_cues"] = [
                            {
                                key: value
                                for key, value in cue.items()
                                if key in allowed_cue_fields
                            }
                            for cue in cues
                            if isinstance(cue, Mapping)
                        ]
                    layer_input["research_handoff"] = compact_handoff
            h2_h3_map = {h2: list(h3s)}
            if additional_h2s:
                h2_h3_map[h2] = list(h3s[:1])
                h2_h3_map[additional_h2s[0]] = list(h3s[1:])
            layer_input["parallel_section_contract"] = {
                "layer_id": layer_id,
                "required_h2": h2,
                "additional_required_h2": list(additional_h2s),
                "required_h3": h3s,
                "h2_h3_map": h2_h3_map,
                "output_scope": "only_assigned_layer",
                "no_h1": True,
                "standalone_complete_prose": True,
                "cross_layer_repetition_forbidden": True,
                "target_chars": target_chars,
                "target_is_minimum": False,
                "quality_unit": "decision_relevant_military_information",
                "hard_max_chars": 0,
                "output_token_budget_is_soft": True,
                "source_index": (
                    "append_after_layer"
                    if layer_id
                    in {"layer_3_portfolio", "chapter_5_foundation"}
                    else "omit"
                ),
            }
            h2_contract = "、".join([h2, *additional_h2s])
            heading_contract = "；".join(
                f"{section_h2}下依次写{','.join(section_h3s)}"
                for section_h2, section_h3s in h2_h3_map.items()
            )
            source_instruction = (
                "本分片末尾附加精简的核心公开来源索引。"
                if layer_input["parallel_section_contract"]["source_index"]
                == "append_after_layer"
                else "本分片不输出公开来源索引。"
            )
            portrait_projection_instruction = (
                "逐装备能力画像已经由S6独立Codex会话完成并通过硬门。本分片必须以S6画像为唯一"
                "装备事实底稿，按正式报告语体重新撰写装备图像概述、组合差异、作战运用流程、链路闭环、"
                "体系贡献计算口径和指标取舍；保持装备名称、主装备身份、作战对象、直接战果、"
                "证据边界和失效边界一致，不得另造装备、改变优先级或补写无依据参数。每段必须比较具体装备或形成"
                "可执行建设/验证决策，不得以省下的画像篇幅补写背景套话。"
                if layer_id == "chapter_2_portrait"
                else ""
            )
            system = (
                _report_writer_system_prompt(payload)
                + f"\n你是并行Reporter分片 {layer_id}。只输出这些二级标题：{h2_contract}；"
                + heading_contract
                + "。不得输出其他层、总标题、前言或过程说明。每个判断必须完整、可独立拼接，"
                f"避免复述其他层；约{target_chars}字只是章节规划预算，不是最低要求，也不是质量目标。"
                "以高价值军事战场信息为质量单位：每段至少承担战场矛盾、具体装备/项目事实、因果判断、"
                "证据边界、对手反适应、验证判据或建设决策中的一项；删除通用战略套话、重复背景、字段复述"
                "和跨章节同义反复。指定三级项、证据边界和能力画像必须完整，但能用更短篇幅闭合时立即收束。"
                "栏目token预算仅用于调度估算，不是截断或失败条件；即使需要超过预算，也必须完成本栏目"
                "规定的标题、事实链和结论后再结束。"
                "research_handoff只提供事实、装备身份、因果要素和验证边界；除装备/单位专名、"
                "公开指标、URL和指定方向标题外，禁止连续照录其中的长句。先按本章任务重新组织"
                "因果链与段落，再用不同句法独立表达；不得通过删除事实、来源、反证或验证要求"
                "来规避原句复用检查。输入中的‘改写断点’只切分事实单元，不属于正文，禁止输出；"
                "断点前后的事实都必须保留并重新综合。"
                + portrait_projection_instruction
                + source_instruction
            )
            calls.append(
                host._run_reporter_text(
                    system,
                    layer_input,
                    min(output_token_budget, token_cap),
                    phase=f"report_generation_{layer_id}",
                    run_id=str(payload.get("run_id", "")),
                    isolation_id=f"{payload.get('run_id', 'run')}:{layer_id}",
                )
            )
        results = await asyncio.gather(*calls, return_exceptions=True)
        return [
            item if isinstance(item, str) else ""
            for item in results
        ]

    layer_texts = asyncio.run(generate_layers())
    merged = "\n\n".join(
        _sanitize_reporter_output(_normalize_report_summary(item))
        for item in layer_texts
        if str(item).strip()
    )
    model_normalized = _normalize_report_structure_deterministically(
        _normalize_branch_report_labels(merged, payload)
    )
    normalized = _stabilize_report_delivery_contract(
        model_normalized,
        payload,
    )
    normalized = _enforce_report_hard_max(normalized, payload)
    host._latest_report_draft = normalized
    quality_issues = [
        item
        for item in _report_draft_quality_issues(normalized, payload)
        if not _is_report_seed_copy_issue(item)
    ]
    quality_issues.extend(_report_seed_copy_issues(model_normalized, payload))
    blocking = _report_delivery_blocking_issues(quality_issues)
    if blocking or not _minimum_viable_model_report(normalized, payload):
        host._last_report_quality_issues = list(quality_issues)
        raise ValueError(
            "parallel Reporter assembly is not reviewable: "
            + "；".join((blocking or quality_issues)[:8])
        )
    host._last_report_quality_issues = list(quality_issues)
    return normalized


def limited_report_delivery(
    host,
    payload: Mapping[str, Any],
    *,
    failure: BaseException,
) -> str:
    """Return the best reviewable report instead of failing the whole run."""

    failure_note = f"{type(failure).__name__}: {failure}"
    issues = list(host._last_report_quality_issues)
    issues.append(f"Reporter限时收敛：{failure_note}"[:260])
    host._last_report_quality_issues = list(dict.fromkeys(issues))[:16]
    candidate = _stabilize_report_delivery_contract(
        _normalize_report_structure_deterministically(
            _normalize_branch_report_labels(
                _sanitize_reporter_output(
                    _normalize_report_summary(host._latest_report_draft)
                ),
                payload,
            )
        ),
        payload,
    )
    candidate = _enforce_report_hard_max(candidate, payload)
    if (
        _minimum_viable_model_report(candidate, payload)
        and _report_has_complete_canonical_structure(candidate)
    ):
        return candidate
    # The deterministic limited builder is still a publication path.  It
    # must consume the exact same Reporter-ready indicator and coupling
    # fields as the normal model draft; otherwise a transport/quality
    # fallback can reintroduce generic placeholders and dangling clipped
    # sentences after the normal stabilizer has already run.
    fallback = _build_limited_report(payload, draft=candidate)
    hybrid = _merge_partial_report_with_limited_completion(
        candidate,
        fallback,
        payload,
    )
    completed = hybrid or fallback
    return _enforce_report_hard_max(
        _stabilize_report_delivery_contract(
            completed,
            payload,
        ),
        payload,
    )


def draft_report_attempt(
    host,
    payload: Mapping[str, Any],
    *,
    reporter_agent: AgentDef | None,
    reporter_input: dict[str, Any],
    output_token_budget: int,
    timeout_seconds: float,
    phase: str,
    allow_repair: bool = True,
    allow_limited: bool = False,
) -> str:
    text = asyncio.run(
        asyncio.wait_for(
            host._run_reporter_text(
                _report_writer_system_prompt(payload),
                reporter_input,
                output_token_budget,
                phase=phase,
                run_id=str(payload.get("run_id", "")),
            ),
            timeout=timeout_seconds,
        )
    )
    model_normalized = _normalize_report_structure_deterministically(
        _normalize_branch_report_labels(
            _sanitize_reporter_output(_normalize_report_summary(text)),
            payload,
        )
    )
    normalized = _stabilize_report_delivery_contract(
        model_normalized,
        payload,
    )
    normalized = _enforce_report_hard_max(normalized, payload)
    host._latest_report_draft = normalized
    quality_issues = [
        item
        for item in _report_draft_quality_issues(normalized, payload)
        if not _is_report_seed_copy_issue(item)
    ]
    quality_issues.extend(_report_seed_copy_issues(model_normalized, payload))
    if not quality_issues:
        return normalized
    if (
        _report_issues_are_deterministic_format_only(quality_issues)
        and _minimum_viable_model_report(normalized, payload)
    ):
        # Heading labels, depth and duplicate source-index headings are
        # deterministic presentation defects.  Never pay for another
        # full Reporter pass to repair them; preserve the report and make
        # the residual visible to the quality artifact.
        host._last_report_quality_issues = list(quality_issues)
        return normalized
    blocking_issues = _report_delivery_blocking_issues(quality_issues)
    if not blocking_issues and _minimum_viable_model_report(normalized, payload):
        # Preserve the independent model report when only cosmetic heading
        # conventions remain. The downstream quality artifact may record
        # them, but they must not fail an otherwise reviewable delivery.
        host._last_report_quality_issues = list(quality_issues)
        return normalized
    if allow_limited and _minimum_viable_model_report(normalized, payload):
        host._last_report_quality_issues = list(quality_issues)
        return normalized
    if not allow_repair:
        host._last_report_quality_issues = list(quality_issues)
        raise ValueError(
            "fast finalize report is not reviewable: "
            + "；".join(quality_issues[:8])
        )
    repair_payload = _reporter_repair_payload(
        payload,
        draft=normalized,
        quality_issues=quality_issues,
        reporter_agent=reporter_agent,
        generation_payload=reporter_input,
    )
    repair_timeout_seconds = min(
        timeout_seconds,
        max(
            30.0,
            min(
                90.0,
                float(
                    os.environ.get(
                        "EQUIPMENT_DR_REPORT_REPAIR_TIMEOUT_SECONDS",
                        "90",
                    )
                ),
            ),
        ),
    )
    repaired = asyncio.run(
        asyncio.wait_for(
            host._run_reporter_text(
                _report_repair_system_prompt(payload),
                repair_payload,
                min(output_token_budget, 2000),
                phase=f"{phase}_repair",
                run_id=str(payload.get("run_id", "")),
            ),
            timeout=repair_timeout_seconds,
        )
    )
    repaired_normalized = _stabilize_report_delivery_contract(
        _normalize_report_structure_deterministically(
            _normalize_branch_report_labels(
                _sanitize_reporter_output(_normalize_report_summary(repaired)),
                payload,
            )
        ),
        payload,
    )
    repaired_normalized = _enforce_report_hard_max(
        repaired_normalized,
        payload,
    )
    host._latest_report_draft = repaired_normalized
    remaining_issues = _report_draft_quality_issues(
        repaired_normalized,
        payload,
    )
    if remaining_issues:
        host._last_report_quality_issues = list(remaining_issues)
        if (
            is_quality_execution_profile_id(
                payload.get("execution_profile_id", "")
            )
            and _branch_delivery_is_complete(payload)
            and _minimum_viable_model_report(repaired_normalized, payload)
        ):
            # optimized_v2 treats Reporter checks as delivery diagnostics,
            # not a reason to discard a complete independent model report.
            # Formal quality/claim gates still persist their findings for
            # audit and residual evolution after delivery.
            return repaired_normalized
        blocking_issues = _report_delivery_blocking_issues(remaining_issues)
        if not blocking_issues and _minimum_viable_model_report(
            repaired_normalized,
            payload,
        ):
            return repaired_normalized
        nonnegotiable = _report_nonnegotiable_delivery_issues(
            remaining_issues
        )
        if not nonnegotiable and _minimum_viable_model_report(
            repaired_normalized,
            payload,
        ):
            # After the one allowed targeted repair, benchmark-detail
            # shortcomings become residuals. They must not trigger another
            # full Reporter call or fail a substantively complete report.
            return repaired_normalized
        if allow_limited and _minimum_viable_model_report(
            repaired_normalized,
            payload,
        ):
            return repaired_normalized
        raise ValueError(
            "report delivery gate failed after repair: "
            + "；".join(remaining_issues[:8])
        )
    return repaired_normalized


async def run_reporter_text(
    host,
    system: str,
    payload: dict[str, Any],
    max_output_tokens: int,
    *,
    phase: str,
    run_id: str = "",
    isolation_id: str = "",
) -> str:
    """Run Reporter in a fresh minimal Codex context without agent runtime."""

    # Reporter is a delivery-quality boundary, not a deadline relief valve.
    # Keep this invariant local to the actual provider call so a future
    # caller, legacy phase name (including fast_finalize/timeout_retry),
    # registry override, or global Codex performance profile cannot silently
    # lower report reasoning depth or truncate the output allowance.
    # Serial delivery retains xhigh/12k. Parallel template sections use
    # high reasoning with an 8k maximum planning budget, then stop against
    # their own section contract once complete.
    configured_effort = "xhigh"
    if isolation_id and str(phase).startswith("report_generation_"):
        # Parallel report sections are bounded synthesis jobs.  ``high``
        # preserves Codex CLI's reasoning quality while avoiding the
        # xhigh latency multiplier across the template's actual sections.
        configured_effort = "high"
    # Parallel callers provide a section-specific soft planning budget
    # (4k for short sections, 8k for the equipment portrait). Honor it at
    # the provider boundary without treating it as a truncation condition.
    if isolation_id and str(phase).startswith("report_generation_"):
        try:
            configured_max_tokens = max(1200, min(8000, int(max_output_tokens)))
        except (TypeError, ValueError):
            configured_max_tokens = 8000
    else:
        configured_max_tokens = 12000
    options = _apply_codex_performance_options(
        {
            "reasoning_effort": _phase_reasoning_effort(
                "reporter", phase, configured_effort
            ),
            "model_verbosity": "medium",
            "prompt_mode": "standalone",
            "max_output_tokens": configured_max_tokens,
            "_soft_output_token_budget": bool(isolation_id),
            "_no_deadline_degrade": True,
            "_disable_provider_timeout": bool(isolation_id),
        },
        host.provider_kind,
        quality_critical=True,
    )
    text, metadata = await host._collect_stream(
        host._provider_for("reporter", isolation_id=isolation_id),
        [
            ModelMessage("system", system),
            ModelMessage("user", payload),
        ],
        options,
        priority="delivery",
        progress={
            "run_id": run_id,
            "agent_id": "reporter",
            "phase": phase,
            "current_step": (
                "报告定向修复"
                if phase.endswith("_repair")
                else (
                    "项目论证报告撰写"
                    if _report_template_mode(payload)
                    == "project_argument_v1"
                    else "三层九项报告撰写"
                )
            ),
        },
        progress_family="report",
    )
    host._record_call_metric(
        host._model_call_metric("reporter", phase, options, metadata)
    )
    return text


def consume_report_quality_issues(host) -> list[str]:
    issues, host._last_report_quality_issues = host._last_report_quality_issues, []
    return list(issues)
