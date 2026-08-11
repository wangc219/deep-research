"""Baseline discovery, evidence analysis, repair and result parsing workflow."""
# ruff: noqa: F821

from __future__ import annotations

from equipment_deep_research.agents.workflows import coordinator as _legacy

globals().update(
    {name: value for name, value in vars(_legacy).items() if not name.startswith("__")}
)

def run_baseline_agent(host, request: AgentRunRequest) -> AgentRunResult:
    text, metadata = asyncio.run(host._run(request))
    payload = _parse_baseline_payload(text)
    findings = [
        str(item) for item in payload.get("findings", []) if str(item).strip()
    ]
    if not findings:
        findings = [f"{request.agent.display_name}未返回可采纳的结构化发现。"]
    confidence = float(payload.get("confidence", 0.45))
    confidence = min(1.0, max(0.0, confidence))
    evidence = _evidence_from_web_sources(
        request=request,
        payload=payload,
        sources=metadata.get("web_sources", []),
        provider_kind=host.provider_kind,
    )
    search_queries = [str(item) for item in metadata.get("search_queries", [])]
    analysis_sections = {
        str(name): payload.get("analysis_sections", {}).get(
            str(name), payload.get(str(name), "")
        )
        for name in (
            request.agent.output_contract.get("properties", [])
            if isinstance(request.agent.output_contract, dict)
            else []
        )
    }
    definition = BASELINE_PAYLOAD_TYPES.get(request.agent.agent_id)
    if definition is not None:
        for name in definition[1]:
            if analysis_sections.get(name) in (None, "", [], {}):
                analysis_sections[name] = list(findings)
    frontier_inspirations = [
        dict(item)
        for item in payload.get("frontier_inspirations", [])
        if isinstance(item, Mapping) and str(item.get("signal", "")).strip()
    ][:3]
    if frontier_inspirations:
        analysis_sections["frontier_inspirations"] = frontier_inspirations
    payload_type, typed_payload, packet_version = _typed_packet_payload(
        request.agent.agent_id, analysis_sections
    )
    packet = BaselineFindingPacket(
        packet_id=(
            f"packet-{request.agent.agent_id}"
            if request.round_index == 1
            else f"packet-{request.agent.agent_id}-r{request.round_index}"
        ),
        agent_id=request.agent.agent_id,
        capability_tags=list(request.agent.capability_tags),
        topic_focus=request.topic,
        findings=findings,
        evidence_ids=[item.evidence_id for item in evidence],
        confidence=confidence,
        coverage_notes=[
            "模型已使用 Responses Web Search 完成公开资料研判；来源仍须通过本地材料化和质量门控后才能成为正式证据。"
        ],
        open_questions=[str(item) for item in payload.get("open_questions", [])],
        handoff_summary=str(payload.get("handoff_summary", findings[0])),
        checkpoint=f"{request.agent.agent_id}: model turn complete",
        search_log=search_queries,
        limitations=(
            [str(item) for item in payload.get("contradictions", [])]
            if evidence
            else ["本轮模型未返回可材料化公开来源，结论必须降级并进入补证或再调。"]
        ),
        claim_ids=[
            "claim-"
            + sha256(f"{request.agent.agent_id}:{item}".encode()).hexdigest()[:12]
            for item in findings
        ],
        analysis_sections=analysis_sections,
        payload_type=payload_type,
        payload=typed_payload,
        schema_version=packet_version,
    )
    return AgentRunResult(
        packet=packet,
        evidence=evidence,
        raw_message=text,
        model_calls=[
            dict(item)
            for item in metadata.get("call_metrics", [])
            if isinstance(item, Mapping)
        ],
    )


def prefetch_baseline_agent(host, request: AgentRunRequest) -> dict[str, Any]:
    """Start the discovery phase before upstream analysis dependencies finish."""
    _, metadata = asyncio.run(host._discovery_for_request(request))
    return {
        "agent_id": request.agent.agent_id,
        "search_batch_count": metadata.get("search_batch_count", 0),
        "source_count": len(metadata.get("web_sources", [])),
        "lane_counts": dict(metadata.get("lane_counts", {})),
        "web_sources": [
            dict(item)
            for item in metadata.get("web_sources", [])
            if isinstance(item, Mapping)
        ],
    }


def _baseline_frontier_inspiration_instruction() -> str:
    return (
        "完成本角色的事实基线后，再切换到前瞻军事研究视角做一次开放旁视：从完整Query、"
        "公开材料中的弱信号、矛盾和尚未闭合的变化出发，判断是否存在可能改写常规对抗关系、"
        "军事交换关系或力量运用方式的高价值启发。不要按技术类别、装备族、创新维度或数量"
        "配额逐项覆盖，也不要把热门技术与现役平台机械相加。先在会话内部比较后，只把真正"
        "可能改变后续制胜命题的少量内容写入frontier_inspirations，并按价值排序；没有成立"
        "信号就返回空数组。每项压缩写清信号、被挑战的常规假设、可能形成的军事不连续性、"
        "Query相关性、事实与推断边界及交给后续Codex继续破解的开放问题。它不是候选装备、"
        "命名提示、技术套餐或推荐结论，不得提前给出成品方案。"
    )


def _baseline_output_schema(agent: AgentDef) -> dict[str, Any]:
    properties = (
        agent.output_contract.get("properties", [])
        if isinstance(agent.output_contract, dict)
        else []
    )
    schema = {
        "findings": ["string"],
        "confidence": "0..1",
        "open_questions": ["string"],
        "handoff_summary": "string",
        "search_plan": [{"track": "string", "queries": ["string"]}],
        "contradictions": [
            "conflicting evidence, alternative hypothesis, or uncertainty"
        ],
        "confidence_basis": (
            "explain evidence diversity, freshness, directness and remaining uncertainty"
        ),
        "source_claims": [
            {
                "url": "cited public source URL",
                "claim": "claim supported by that source",
            }
        ],
        "frontier_inspirations": [
            {
                "signal": "source-grounded emerging change or a clearly labeled model hypothesis",
                "conventional_assumption_challenged": "the incumbent military assumption that may stop holding",
                "possible_military_discontinuity": "how the contest, exchange, timing, effect or force relationship could change",
                "query_relevance": "why this matters to the current Query rather than military modernization in general",
                "evidence_boundary": "what public evidence supports, what remains inference, and what would disconfirm it",
                "source_urls": ["exact URL from discovered_sources when available"],
                "downstream_question": "an open question for later Codex reasoning, not an equipment answer",
            }
        ],
        "analysis_sections": {
            str(name): "string | object | array" for name in properties
        },
    }
    return schema


async def run(host, request: AgentRunRequest) -> tuple[str, dict[str, Any]]:
    design = host.baseline_workflow.design_for(request.agent)
    recall_request = request.context.get("recall_request", {})
    targeted_supplement = bool(
        isinstance(recall_request, Mapping)
        and recall_request.get("targeted_supplement")
    )
    schema = _baseline_output_schema(request.agent)
    schema = host.baseline_workflow.output_schema(request.agent, schema)
    prompt = BaselinePromptBuilder().build(
        agent=request.agent,
        route=request.research_route,
        task={"topic": request.topic},
        context=request.context,
        compact_runtime=True,
    )
    provider = host._provider_for(request.agent.agent_id)
    deep_equipment_search = design.search_mode == "equipment_deep"
    specialized_evidence_channels = (
        _weapon_specialized_evidence_channels(
            request.topic,
            structured_query_brief=request.context.get(
                "structured_query_brief", {}
            ),
        )
        if deep_equipment_search
        else []
    )
    optimized_v2 = (
        isinstance(request.context.get("discovery_blueprint", {}), Mapping)
        and is_quality_execution_profile_id(
            request.context.get("discovery_blueprint", {}).get(
                "execution_profile_id"
            )
        )
    )
    plan_mode = _agent_plan_mode(request.context)
    compact_reference = optimized_v2 and plan_mode == "reference"
    analysis_specialization = design.analysis_specialization(
        optimized=optimized_v2
    )
    discovery_text, discovery_metadata = await host._discovery_for_request(request)
    if optimized_v2 and deep_equipment_search:
        single_pass_text = str(
            discovery_metadata.get("single_pass_baseline_text", "")
        ).strip()
        single_pass_error = str(
            discovery_metadata.get("single_pass_baseline_error", "")
        ).strip()
        if single_pass_error:
            raise RuntimeError(
                "weapon_equipment boundary snapshot unavailable: "
                + single_pass_error
            )
        single_pass_payload = _parse_json_object(single_pass_text)
        substantive_findings = [
            str(item).strip()
            for item in single_pass_payload.get("findings", [])
            if str(item).strip()
        ]
        if not substantive_findings:
            raise RuntimeError(
                "weapon_equipment model turn completed but outer baseline result "
                "validation found no substantive findings"
            )
        host._emit_baseline_progress(
            {
                "event_type": "baseline_analysis_completed",
                "run_id": request.run_id,
                "agent_id": request.agent.agent_id,
                "round_index": request.round_index,
                "repaired": False,
                "execution_mode": "single_pass_public_boundary_snapshot",
            }
        )
        return single_pass_text, discovery_metadata

    if optimized_v2:
        role_focus = design.role_focus(optimized=True)
        if deep_equipment_search:
            role_focus += (
                _query_led_combat_equipment_theme_instruction()
                + "本Agent只建立可追溯的现役/在研事实、能力边界、体系依赖、反证和可验证差距；"
                "不得提出前瞻装备候选、不得为S3命名装备、不得把公开型号谱系写成创新路线或推荐目录。"
                "型号只作为后续候选的最近公开比较基线，不能进入首轮创新生成上下文。"
            )
        analysis_system = (
            "优先按本Agent专业角色和专用方法独立分析Query主题的核心军事矛盾，并以强军事运用价值收敛；"
            "本Agent角色+Query主题+打击、歼灭、压制、反制、拒止、威慑等直接作战价值共同主导。"
            "必须先消化query_combat_equipment_divergence_brief，再从本Agent角色重新核验和扩展；"
            "不得跳过Query语义直接套用共享示例，也不得把简报中的待证架构当成既成事实。"
            "其他Agent精简信息只能作为次级事实证据、约束或反证，不得决定议题、结构、命名、优先级和结论，"
            "也不得继承或拼接其叙事。"
            "从侦察预警、指挥决策、协同、打击、歼灭、压制、反制、拒止、威慑、抗毁、保障恢复中选择相关任务效果深入论证。"
            + (
                "输出严格JSON；本次为参考Agent精简研判：只保留3至4条会改变场景边界、装备选择、技术优先级或反证判断的决定性信息，"
                "其余背景、同义结论和低价值资料全部舍弃；明确指出对三层九项中哪一项有贡献。"
                if compact_reference
                else "输出严格JSON；findings最多5条，每条写清判断、军事任务价值、证据边界和失效条件。"
            )
            + "source_claims只引用来源目录中的URL。不要复述检索过程、角色定义、Harness、Skill或执行步骤。"
            + (
                _baseline_frontier_inspiration_instruction()
                if not targeted_supplement
                else ""
            )
            + role_focus
            + analysis_specialization
        )
        analysis_payload = {
            "assignment": prompt,
            "web_discovery": _compact_discovery_text(
                discovery_text,
                max_chars=4000 if compact_reference else 6000,
            ),
            "discovered_sources": _compact_discovered_sources(
                discovery_metadata.get("web_sources", []),
                limit=4 if compact_reference else 6,
            ),
            "specialized_evidence_channels": specialized_evidence_channels,
            "query_led_combat_equipment_themes": (
                _query_led_combat_equipment_theme_contract()
                if deep_equipment_search
                else {}
            ),
            "query_combat_equipment_divergence_brief": (
                _query_combat_equipment_divergence_brief(
                    request.topic,
                    structured_query_brief=request.context.get(
                        "structured_query_brief", {}
                    ),
                )
            ),
            "discovery_blueprint": _compact_discovery_blueprint(
                request.context.get("discovery_blueprint", {})
            ),
            "recall_request": recall_request,
        }
    else:
        analysis_system = (
            "你是受限的研究子智能体。上一步检索Agent已提供web discovery结果；不要虚构 URL。"
            "必须依据assignment与discovery交叉分析，主动识别反证、冲突数据和替代假设。"
            "必须先消化query_combat_equipment_divergence_brief，并从本Agent专业角色核验其任务对象、"
            "阶段、约束和武器架构；不得绕过Query语义套用固定示例。"
            "输出严格 JSON，并在 source_claims 中只引用discovered_sources中的 URL。"
            + (
                "这是一次制胜链批判触发的窄化补证。只回答recall_request中的单一问题，"
                "优先一手或权威来源，最多3条发现、4个source_claims；不得扩展为新的全景研究。"
                if targeted_supplement
                else ""
            )
            + (
                "武器装备研究必须分别给出国外与中国国内装备全景和重点型号档案，按具体案例记录"
                "问题难点解决方式、技术方案途径、核心技术、核心公开指标、实证/图片URL和证据边界；再按‘装备能力—体系依赖/边界—"
                "主题场景压力—防御性反制功能—现役升级或新研需求—成熟度—验证方法—证据’闭环输出。"
                "findings最多8条、open_questions最多5条、source_claims最多18条；"
                if deep_equipment_search
                else "交接包必须高信息密度且完整闭合：findings 最多6条、open_questions最多4条、"
                "source_claims最多12条；"
            )
            + (
                _query_led_combat_equipment_theme_instruction()
                if deep_equipment_search
                else ""
            )
            + analysis_specialization
            + (
                _baseline_frontier_inspiration_instruction()
                if not targeted_supplement
                else ""
            )
            + "每个analysis_sections字段只保留结论、关键参数、证据边界和适用条件，"
            + "不得复制长篇原文、完整搜索过程或大表格，也不得输出具体攻击步骤或武器制造参数。"
        )
        analysis_payload = {
            "assignment": prompt,
            "web_discovery": discovery_text,
            "discovered_sources": discovery_metadata.get("web_sources", []),
            "search_queries": discovery_metadata.get("search_queries", []),
            "specialized_evidence_channels": specialized_evidence_channels,
            "query_led_combat_equipment_themes": (
                _query_led_combat_equipment_theme_contract()
                if deep_equipment_search
                else {}
            ),
            "query_combat_equipment_divergence_brief": (
                _query_combat_equipment_divergence_brief(
                    request.topic,
                    structured_query_brief=request.context.get(
                        "structured_query_brief", {}
                    ),
                )
            ),
            "discovery_blueprint": request.context.get("discovery_blueprint", {}),
            "recall_request": recall_request,
        }

    messages = host._runtime_messages(
        request.agent.agent_id,
        analysis_system,
        analysis_payload,
        phase="evidence_analysis",
        agent=request.agent,
        harness_profile=host._harness_for(request.agent),
    )
    options = _agent_model_options(
        host.model_options,
        request.agent,
        provider_kind=host.provider_kind,
    )
    options["model_verbosity"] = "low" if optimized_v2 else "medium"
    if not targeted_supplement:
        analysis_token_cap = int(
            os.environ.get(
                (
                    "EQUIPMENT_DR_EQUIPMENT_ANALYSIS_MAX_OUTPUT_TOKENS"
                    if deep_equipment_search
                    else "EQUIPMENT_DR_BASELINE_ANALYSIS_MAX_OUTPUT_TOKENS"
                ),
                (
                    "1800"
                    if deep_equipment_search and optimized_v2
                    else "1800"
                    if optimized_v2
                    else "5200"
                    if deep_equipment_search
                    else "4200"
                ),
            )
        )
        if optimized_v2:
            analysis_token_cap = min(
                analysis_token_cap,
                1800 if deep_equipment_search else 1800,
            )
        options["max_output_tokens"] = min(
            int(options.get("max_output_tokens", analysis_token_cap)),
            analysis_token_cap,
        )
    if targeted_supplement:
        options["reasoning_effort"] = "medium"
        options["max_output_tokens"] = min(
            int(options.get("max_output_tokens", 1800)), 1800
        )
        options["model_verbosity"] = "low"
    elif compact_reference:
        options["reasoning_effort"] = "medium"
        options["max_output_tokens"] = min(
            int(options.get("max_output_tokens", 1800)), 1800
        )
        options["model_verbosity"] = "low"
    options = _apply_codex_performance_options(options, host.provider_kind)
    if optimized_v2 and deep_equipment_search and not targeted_supplement:
        options["reasoning_effort"] = "medium"
        options["_provider_timeout_seconds"] = min(
            int(options.get("_provider_timeout_seconds", 150)), 150
        )
        options["_disable_provider_timeout"] = False
        options["_provider_retry_attempts"] = 1
    options["output_schema"] = schema
    options.pop("web_search", None)
    options.pop("include_web_sources", None)
    options.pop("require_web_search", None)
    host._emit_baseline_progress(
        {
            "event_type": "baseline_analysis_started",
            "run_id": request.run_id,
            "agent_id": request.agent.agent_id,
            "round_index": request.round_index,
            "source_count": len(discovery_metadata.get("web_sources", [])),
            "plan_mode": plan_mode,
        }
    )
    text, analysis_metadata = await host._collect_stream(
        provider,
        messages,
        options,
        priority=str(request.context.get("_execution_priority", "critical")),
        progress={
            "run_id": request.run_id,
            "agent_id": request.agent.agent_id,
            "round_index": request.round_index,
            "phase": "evidence_analysis",
        },
    )
    analysis_metric = host._model_call_metric(
        request.agent.agent_id,
        "evidence_analysis",
        options,
        analysis_metadata,
    )
    host._record_call_metric(analysis_metric)
    discovery_metadata["call_metrics"].append(analysis_metric)
    repaired_text, repair_metric = await host._repair_baseline_output(
        request=request,
        text=text,
        schema=schema,
        discovered_sources=discovery_metadata.get("web_sources", []),
    )
    if repair_metric is not None:
        discovery_metadata["call_metrics"].append(repair_metric)
    host._emit_baseline_progress(
        {
            "event_type": "baseline_analysis_completed",
            "run_id": request.run_id,
            "agent_id": request.agent.agent_id,
            "round_index": request.round_index,
            "repaired": repair_metric is not None,
        }
    )
    return repaired_text, discovery_metadata


async def discovery_for_request(
    host,
    request: AgentRunRequest,
) -> tuple[str, dict[str, Any]]:
    key = (request.run_id, request.agent.agent_id, request.round_index)
    owner = False
    with host._discovery_lock:
        cached = host._discovery_cache.get(key)
        if cached is not None:
            return cached[0], dict(cached[1])
        future = host._discovery_inflight.get(key)
        if future is None:
            future = Future()
            host._discovery_inflight[key] = future
            owner = True
    if not owner:
        result = await asyncio.wrap_future(future)
        return result[0], dict(result[1])
    try:
        result = await host._discover(request)
    except BaseException as exc:
        with host._discovery_lock:
            host._discovery_inflight.pop(key, None)
            if not future.done():
                future.set_exception(exc)
        raise
    with host._discovery_lock:
        host._discovery_cache[key] = (result[0], dict(result[1]))
        host._discovery_inflight.pop(key, None)
        if not future.done():
            future.set_result(result)
    return result


async def discover(
    host,
    request: AgentRunRequest,
) -> tuple[str, dict[str, Any]]:
    recall_request = request.context.get("recall_request", {})
    targeted_supplement = bool(
        isinstance(recall_request, Mapping)
        and recall_request.get("targeted_supplement")
    )
    targeted_questions = (
        [
            str(item)
            for item in recall_request.get("required_data", [])
            if str(item).strip()
        ][:2]
        if targeted_supplement
        else []
    )
    search_tracks = [
        str(item)
        for item in request.agent.research_policy.get("search_tracks", [])
        if str(item).strip()
    ]
    if targeted_questions:
        search_tracks = targeted_questions
    deep_equipment_search = request.agent.agent_id == "weapon_equipment"
    specialized_evidence_channels = (
        _weapon_specialized_evidence_channels(
            request.topic,
            structured_query_brief=request.context.get(
                "structured_query_brief", {}
            ),
        )
        if deep_equipment_search and not targeted_supplement
        else []
    )
    if specialized_evidence_channels:
        specialized_tracks = [
            f"{item['name']}：{item['focus']}"
            for item in specialized_evidence_channels
        ]
        search_tracks = list(
            dict.fromkeys([*specialized_tracks, *search_tracks])
        )
    target_source_count = (
        max(
            2,
            min(
                4,
                int(
                    os.environ.get(
                        "EQUIPMENT_DR_TARGETED_EVIDENCE_SOURCE_TARGET", "3"
                    )
                ),
            ),
        )
        if targeted_supplement
        else (
            max(
                14,
                min(
                    18,
                    int(
                        request.agent.research_policy.get(
                            "target_source_count", 8
                        )
                    ),
                ),
            )
            if deep_equipment_search
            else min(
                12,
                int(request.agent.research_policy.get("target_source_count", 8)),
            )
        )
    )
    source_priorities = [
        dict(item)
        for item in [
            *request.context.get("source_priorities", []),
            *request.context.get("shared_source_priorities", []),
        ]
        if isinstance(item, Mapping)
    ]
    incremental_knowledge = [
        dict(item)
        for item in request.context.get("incremental_knowledge", [])
        if isinstance(item, Mapping)
    ]
    memory_urls = [
        str(url)
        for item in incremental_knowledge
        for url in item.get("source_urls", [])
        if str(url).startswith("https://")
    ]
    blueprint_context = request.context.get("discovery_blueprint", {})
    use_specialized_anchors = bool(
        isinstance(blueprint_context, Mapping)
        and is_quality_execution_profile_id(
            blueprint_context.get("execution_profile_id")
        )
    )
    specialized_anchor_urls = (
        _prioritize_specialized_anchor_urls(specialized_evidence_channels)
        if use_specialized_anchors
        else []
    )
    known_urls = list(
        dict.fromkeys(
            [
                *specialized_anchor_urls,
                *(str(item.get("url", "")) for item in source_priorities),
                *memory_urls,
            ]
        )
    )
    search_intensity = str(
        request.context.get(
            "_search_intensity",
            request.agent.research_policy.get("search_intensity", "standard"),
        )
    ).strip().lower()
    optimized_v2 = (
        isinstance(request.context.get("discovery_blueprint", {}), Mapping)
        and is_quality_execution_profile_id(
            request.context.get("discovery_blueprint", {}).get(
                "execution_profile_id"
            )
        )
    )
    single_pass_equipment_boundary = bool(
        optimized_v2 and deep_equipment_search and not targeted_supplement
    )
    plan_mode = _agent_plan_mode(request.context)
    compact_reference = optimized_v2 and plan_mode == "reference"
    compact_callback = optimized_v2 and plan_mode == "callback"
    if compact_reference:
        target_source_count = min(target_source_count, 3)
    elif compact_callback:
        target_source_count = min(target_source_count, 3)
    if optimized_v2:
        # One hybrid web-research call already receives trusted source
        # priorities plus permission to discover new sources. Running a
        # second speculative lane roughly doubles gateway time while the
        # accepted-source cap discards most of its marginal output.
        search_intensity = "light"
        if not targeted_supplement:
            # Bound the search result set around the governed saturation
            # target. The scheduler may continue only when domain diversity,
            # counterevidence, or the minimum gate remains unresolved; it no
            # longer pursues a fixed ten-source weapon quota after quality
            # sufficiency has stabilized.
            quality_lead_cap = max(
                3,
                min(
                    4,
                    int(
                        os.environ.get(
                            "EQUIPMENT_DR_QUALITY_EQUIPMENT_LEAD_CAP",
                            "4",
                        )
                    ),
                ),
            )
            target_source_count = min(
                target_source_count,
                3
                if compact_reference or compact_callback
                else quality_lead_cap,
            )
    max_batches = (
        1
        if targeted_supplement or optimized_v2
        else max(
            1,
            min(
                int(os.environ.get("EQUIPMENT_DR_DISCOVERY_MAX_BATCHES", "2")),
                int(
                    request.agent.research_policy.get(
                        "max_search_batches",
                        os.environ.get("EQUIPMENT_DR_DISCOVERY_MAX_BATCHES", "2"),
                    )
                ),
            ),
        )
    )
    fast_lane_enabled = bool(known_urls)
    lanes: list[dict[str, Any]] = []
    if search_intensity == "light":
        lanes.append(
            {
                "lane": "hybrid_web",
                "tracks": search_tracks,
                "source_priorities": source_priorities,
                "known_urls": known_urls[:12],
                "reasoning_effort": (
                    "low" if optimized_v2 and deep_equipment_search else "medium"
                ),
                "max_output_tokens": (
                    1200
                    if targeted_supplement
                    else 1000
                    if compact_reference or compact_callback
                    else (
                        1400
                        if optimized_v2
                        else 2600
                    )
                    if deep_equipment_search
                    else 1400
                ),
            }
        )
    else:
        open_batch_slots = max(1, max_batches - int(fast_lane_enabled))
        open_batches = _partition_tracks(search_tracks, open_batch_slots)
        if fast_lane_enabled:
            lanes.append(
                {
                    "lane": "known_sources",
                    "tracks": search_tracks[:3],
                    "source_priorities": source_priorities,
                    "known_urls": known_urls[:12],
                    "reasoning_effort": "low",
                    "max_output_tokens": 1200,
                }
            )
        lanes.extend(
            {
                "lane": "open_web",
                "tracks": tracks,
                "source_priorities": [],
                "known_urls": [],
                "reasoning_effort": "medium",
                "max_output_tokens": (
                    1200
                    if targeted_supplement
                    else 2200
                    if deep_equipment_search
                    else 1600
                ),
            }
            for tracks in open_batches
        )
    medium_context_agents = {
        "combat_scenario",
        "operational_employment",
        "scenario_divergence",
        "technology_radar",
        "opponent_monitoring",
        "system_confrontation",
        "cross_domain_fusion",
        "nontraditional_security",
    }
    granted_lanes = host._reserve_search_batches(len(lanes))
    if granted_lanes < len(lanes):
        lanes = lanes[:granted_lanes]
    if not lanes:
        return (
            "搜索预算已耗尽；仅可复用Run内已登记公开来源。",
            {
                "web_sources": [],
                "search_queries": [],
                "search_batch_count": 0,
                "lane_counts": {},
                "call_metrics": [],
                "search_budget_exhausted": True,
            },
        )

    # Phase 3: Optimize search_context_size based on step number for winning agents
    step_num = 0
    if request.agent.agent_id.startswith("winning_s"):
        try:
            step_num = int(request.agent.agent_id.split("_s")[1].split("_")[0])
        except (ValueError, IndexError):
            pass

    if step_num > 0:
        # Use optimized search context size for S1-S6 steps
        search_context_size = get_optimized_search_context_size(
            step_num,
            request.agent.agent_id,
        )
    else:
        # Use original logic for non-winning agents
        search_context_size = (
            "medium" if request.agent.agent_id in medium_context_agents else "high"
        )
    if compact_reference or compact_callback:
        search_context_size = "medium"
    elif optimized_v2 and deep_equipment_search:
        search_context_size = str(
            os.environ.get(
                "EQUIPMENT_DR_QUALITY_EQUIPMENT_SEARCH_CONTEXT_SIZE",
                "medium",
            )
        ).strip().lower()
        if search_context_size not in {"low", "medium", "high"}:
            search_context_size = "medium"
    discovery_system = host.baseline_workflow.discovery_system_prompt(
        request.agent
    )
    if single_pass_equipment_boundary:
        discovery_system = (
            "你是公开武器装备边界快照Agent。只用一次模型调用完成Query定向检索与结构化研判。"
            "职责仅限：公开现役/在研能力边界、体系依赖、直接反证、可验证差距和候选级后续核验线索；"
            "不得提出或命名前瞻候选，不得把公开型号谱系变成S3创新目录。"
            "只保留最多4条会改变后续候选判断的结论，每条说明军事任务影响、证据边界和失效条件。"
            "source_claims只能引用本次web search实际返回的URL；证据不足时写入open_questions或contradictions。"
            "输出严格JSON，不复述检索过程。"
            + _baseline_frontier_inspiration_instruction()
            + _query_led_combat_equipment_theme_instruction()
        )
    elif deep_equipment_search:
        discovery_system += _query_led_combat_equipment_theme_instruction()
    if compact_reference or compact_callback:
        discovery_system += (
            " 本次采用精简参考检索：只返回4至6个最关键公开来源，优先决定性事实、明确边界、"
            "反证与可改变装备判断的信息；不追求背景完整性，不扩写通用常识。"
        )
    host._emit_baseline_progress(
        {
            "event_type": "baseline_discovery_started",
            "run_id": request.run_id,
            "agent_id": request.agent.agent_id,
            "round_index": request.round_index,
            "lane_count": len(lanes),
            "known_source_count": len(known_urls),
            "search_intensity": search_intensity,
            "plan_mode": plan_mode,
        }
    )

    async def run_lane(
        lane_index: int,
        lane: Mapping[str, Any],
        shared_sources_for_lane: Sequence[Mapping[str, Any]],
    ) -> tuple[int, dict[str, Any], str, dict[str, Any], dict[str, Any]]:
        host._emit_baseline_progress(
            {
                "event_type": "baseline_discovery_lane_started",
                "run_id": request.run_id,
                "agent_id": request.agent.agent_id,
                "round_index": request.round_index,
                "lane": lane.get("lane"),
                "lane_index": lane_index,
                "lane_count": len(lanes),
            }
        )
        options = _apply_codex_performance_options(
            {
                "reasoning_effort": str(lane["reasoning_effort"]),
                "model_verbosity": "low",
                "max_output_tokens": int(lane["max_output_tokens"]),
                # Discovery is a lead-generation step. A single hosted
                # search tail must not hold every downstream Agent after
                # the other baseline roles have already completed. One
                # bounded attempt is enough; the run can reuse shared
                # sources, explicit anchors, and clearly mark the gap.
                **(
                    {
                        # Efficiency comes from one bounded multi-point search
                        # call, a small source/output budget and no second
                        # analysis call.  Do not turn elapsed seconds into a
                        # business failure for the equipment boundary snapshot.
                        "_disable_provider_timeout": True,
                    }
                    if single_pass_equipment_boundary
                    else {
                        "_provider_timeout_seconds": max(
                            60,
                            int(
                                os.environ.get(
                                    "EQUIPMENT_DR_WEB_DISCOVERY_TIMEOUT_SECONDS",
                                    "120"
                                    if optimized_v2 and deep_equipment_search
                                    else "150",
                                )
                            ),
                        )
                    }
                ),
                **(
                    {}
                    if single_pass_equipment_boundary
                    else {"_disable_provider_timeout": False}
                ),
                "_provider_retry_attempts": 1,
                "web_search": {
                    "search_context_size": search_context_size,
                    "external_web_access": True,
                },
                "include_web_sources": True,
                "require_web_search": True,
                **(
                    {
                        "output_schema": host.baseline_workflow.output_schema(
                            request.agent,
                            _baseline_output_schema(request.agent),
                        )
                    }
                    if single_pass_equipment_boundary
                    else {}
                ),
            },
            host.provider_kind,
        )
        phase = (
            "weapon_equipment_boundary_snapshot"
            if single_pass_equipment_boundary
            else "web_discovery_fast"
            if lane.get("lane") == "known_sources"
            else "web_discovery_open"
        )
        started_at = monotonic()
        try:
            text, metadata = await host._collect_stream(
                host._discovery_provider_for(request.agent.agent_id),
                host._runtime_messages(
                    request.agent.agent_id,
                    discovery_system,
                    {
                        "topic": request.topic,
                        "structured_query_brief": request.context.get(
                            "structured_query_brief", {}
                        ),
                        "query_combat_equipment_divergence_brief": (
                            _query_combat_equipment_divergence_brief(
                                request.topic,
                                structured_query_brief=request.context.get(
                                    "structured_query_brief", {}
                                ),
                            )
                        ),
                        "research_route": request.research_route,
                        "agent_role": request.agent.display_name,
                        "retrieval_lane": lane.get("lane"),
                        "search_batch": lane_index,
                        "search_batch_count": len(lanes),
                        "search_tracks": list(lane.get("tracks", [])),
                        "specialized_evidence_channels": specialized_evidence_channels,
                        "target_source_count": max(
                            3,
                            (target_source_count + len(lanes) - 1) // len(lanes),
                        ),
                        "source_priorities": list(lane.get("source_priorities", [])),
                        "known_urls": list(lane.get("known_urls", [])),
                        "shared_discovery_sources": list(shared_sources_for_lane),
                        "incremental_knowledge": incremental_knowledge,
                        "discovery_blueprint": request.context.get(
                            "discovery_blueprint", {}
                        ),
                        "recall_request": recall_request,
                        "output_contract": (
                            "single_pass_public_boundary_snapshot"
                            if single_pass_equipment_boundary
                            else "source_discovery"
                        ),
                    },
                    phase="web_discovery",
                    agent=request.agent,
                    harness_profile=host._harness_for(request.agent),
                ),
                options,
                priority=(
                    "critical"
                    if len(lanes) > 1
                    else str(request.context.get("_execution_priority", "normal"))
                ),
                progress={
                    "run_id": request.run_id,
                    "agent_id": request.agent.agent_id,
                    "round_index": request.round_index,
                    "phase": phase,
                    "lane": lane.get("lane"),
                    "lane_index": lane_index,
                },
            )
        except Exception as exc:
            elapsed_seconds = round(monotonic() - started_at, 3)
            metadata = {
                "web_sources": [],
                "search_queries": [],
                "discovery_limited": True,
                "failure_type": type(exc).__name__,
                "error_message": str(exc)[:300],
                "elapsed_seconds": elapsed_seconds,
            }
            text = (
                "本检索通道在有界时限内未返回；后续只复用Run内共享来源、"
                "显式来源锚点并降低相关事实置信度，不重试扩搜。"
            )
            metric = {
                "agent_id": request.agent.agent_id,
                "phase": phase,
                "elapsed_seconds": elapsed_seconds,
                "success": False,
                "failure_type": type(exc).__name__,
                "error_message": str(exc)[:300],
                "provider_retry_attempts": 1,
                "discovery_limited": True,
            }
            host._record_call_metric(metric)
            host._emit_baseline_progress(
                {
                    "event_type": "baseline_discovery_lane_limited",
                    "run_id": request.run_id,
                    "agent_id": request.agent.agent_id,
                    "round_index": request.round_index,
                    "lane": lane.get("lane"),
                    "lane_index": lane_index,
                    "failure_type": type(exc).__name__,
                    "error_message": str(exc)[:300],
                    "elapsed_seconds": elapsed_seconds,
                    "fallback": "reuse_shared_sources_and_explicit_anchors",
                }
            )
            return lane_index, dict(lane), text, metadata, metric
        metric = host._model_call_metric(
            request.agent.agent_id,
            phase,
            options,
            metadata,
        )
        host._record_call_metric(metric)
        host._emit_baseline_progress(
            {
                "event_type": "baseline_discovery_lane_completed",
                "run_id": request.run_id,
                "agent_id": request.agent.agent_id,
                "round_index": request.round_index,
                "lane": lane.get("lane"),
                "lane_index": lane_index,
            }
        )
        return lane_index, dict(lane), text, metadata, metric

    indexed_lanes = list(enumerate(lanes, start=1))
    with host._discovery_lock:
        shared_sources = list(
            host._shared_discovery_sources.get(request.run_id, {}).values()
        )[:18]
    # The known-source and open-web lanes are complementary, not dependent.
    # Launch them speculatively in the same wave and merge their evidence
    # before analysis.  This preserves both coverage tracks while removing
    # the sum of their gateway latencies from the critical path.
    lane_results = list(
        await asyncio.gather(
            *(
                run_lane(index, lane, shared_sources)
                for index, lane in indexed_lanes
            )
        )
    )
    fragments: list[str] = []
    sources: list[dict[str, Any]] = []
    queries: list[str] = []
    metrics: list[dict[str, Any]] = []
    lane_counts: dict[str, int] = {}
    seen_urls: set[str] = set()
    for lane_index, lane, text, metadata, metric in lane_results:
        lane_name = str(lane.get("lane", "open_web"))
        metrics.append(metric)
        fragments.append(
            f"## {lane_name} {lane_index}: {'；'.join(lane.get('tracks', []))}\n{text}"
        )
        batch_sources = metadata.get(
            "web_sources"
        ) or _source_rows_from_discovery_text(text)
        accepted_in_lane = 0
        for source in batch_sources:
            if not isinstance(source, Mapping):
                continue
            url = _without_tracking_parameters(str(source.get("url", "")).strip())
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            row = {**dict(source), "url": url, "retrieval_lane": lane_name}
            sources.append(row)
            accepted_in_lane += 1
        lane_counts[lane_name] = lane_counts.get(lane_name, 0) + accepted_in_lane
        queries.extend(
            str(item)
            for item in metadata.get("search_queries", [])
            if str(item).strip()
        )
    selected_sources = (
        _merge_required_source_anchors(
            sources,
            specialized_anchor_urls,
            limit=target_source_count,
        )
        if deep_equipment_search and use_specialized_anchors
        else sources[:target_source_count]
    )
    with host._discovery_lock:
        shared = host._shared_discovery_sources.setdefault(request.run_id, {})
        for source in selected_sources:
            url = str(source.get("url", ""))
            if url:
                shared[url] = {
                    **source,
                    "discovered_by": request.agent.agent_id,
                }
    metadata = {
        "web_sources": selected_sources,
        "search_queries": list(dict.fromkeys(queries)),
        "search_batch_count": len(lanes),
        "lane_counts": lane_counts,
        "call_metrics": metrics,
        "shared_source_count": len(shared_sources),
    }
    if single_pass_equipment_boundary and lane_results:
        single_pass_text = str(lane_results[0][2]).strip()
        single_pass_metric = lane_results[0][4]
        metadata["single_pass_baseline_text"] = single_pass_text
        if not bool(single_pass_metric.get("success", True)):
            metadata["single_pass_baseline_error"] = str(
                single_pass_metric.get("error_message", "bounded snapshot failed")
            )
        metadata["execution_mode"] = "single_pass_public_boundary_snapshot"
    if (
        host.provider_kind == "codex_cli"
        and selected_sources
        and not metadata["search_queries"]
    ):
        metadata["search_queries"] = [
            f"Codex public-source discovery: {request.topic}"
        ]
    host._emit_baseline_progress(
        {
            "event_type": "baseline_discovery_completed",
            "run_id": request.run_id,
            "agent_id": request.agent.agent_id,
            "round_index": request.round_index,
            "source_count": len(selected_sources),
            "lane_counts": lane_counts,
        }
    )
    return "\n\n".join(fragments), metadata


async def repair_baseline_output(
    host,
    *,
    request: AgentRunRequest,
    text: str,
    schema: Mapping[str, Any],
    discovered_sources: Sequence[Mapping[str, Any]],
) -> tuple[str, dict[str, Any] | None]:
    if host.provider_kind != "codex_cli":
        return text, None
    payload = _parse_json_object(text)
    missing = _missing_baseline_fields(payload, request.agent)
    if not missing:
        return text, None
    patch_schema = _repair_schema(schema, missing)
    options = _apply_codex_performance_options(
        {
            "reasoning_effort": "medium",
            "model_verbosity": "low",
            "max_output_tokens": min(1800, 300 + len(missing) * 180),
            "output_schema": patch_schema,
        },
        host.provider_kind,
    )
    repair_text, metadata = await host._collect_stream(
        host._provider_for(request.agent.agent_id),
        host._runtime_messages(
            request.agent.agent_id,
            "你是结构化结果修复Agent。只补齐missing_fields，不重做检索、不改写已有效字段、"
            "不新增URL；若证据不足则明确写入open_questions或contradictions。只输出严格JSON。",
            {
                "topic": request.topic,
                "missing_fields": missing,
                "current_payload": payload,
                "discovered_sources": list(discovered_sources),
            },
            phase="evidence_analysis_repair",
            agent=request.agent,
            harness_profile=host._harness_for(request.agent),
        ),
        options,
        priority=str(request.context.get("_execution_priority", "critical")),
        progress={
            "run_id": request.run_id,
            "agent_id": request.agent.agent_id,
            "round_index": request.round_index,
            "phase": "evidence_analysis_repair",
        },
    )
    patch = _parse_json_object(repair_text)
    merged = _merge_missing_payload(payload, patch, missing)
    metric = host._model_call_metric(
        request.agent.agent_id,
        "evidence_analysis_repair",
        options,
        metadata,
    )
    host._record_call_metric(metric)
    return json.dumps(merged, ensure_ascii=False, separators=(",", ":")), metric
