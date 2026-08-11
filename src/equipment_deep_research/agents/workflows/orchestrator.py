"""Orchestrator selection, blueprint, convergence, audit and winning entrypoints."""
# ruff: noqa: F821

from __future__ import annotations

from equipment_deep_research.agents.workflows import coordinator as _legacy

globals().update(
    {name: value for name, value in vars(_legacy).items() if not name.startswith("__")}
)

def select_agents(host, request: AgentSelectionRequest) -> AgentSelectionResult:
    text = asyncio.run(host._select_agents(request))
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return AgentSelectionResult(
        selected_agent_ids=[
            str(item)
            for item in payload.get("selected_agent_ids", [])
            if str(item).strip()
        ],
        rationale=str(payload.get("rationale", "模型未返回有效选择理由。")),
        task_analysis=[str(item) for item in payload.get("task_analysis", [])],
        dependency_notes=[
            str(item) for item in payload.get("dependency_notes", [])
        ],
        model_used=True,
    )


def analyze_winning_mechanism(host, payload: dict[str, Any]) -> dict[str, Any]:
    if host.provider_kind == "codex_cli":
        try:
            return asyncio.run(host._analyze_winning_subagents(payload))
        except (RuntimeError, TimeoutError) as exc:
            if not (
                is_aggressive_optimized_v2_payload(payload)
                and _is_harness_budget_error(exc)
            ):
                raise
            host._emit_winning_progress(
                {
                    "event_type": "winning_budget_fallback",
                    "run_id": str(payload.get("run_id", "")),
                    "reason": type(exc).__name__,
                    "status": "limited_fallback",
                }
            )
            # The runner already owns a deterministic, evidence-bound
            # S1-S6 engine. Returning an empty model projection lets that
            # engine deliver the latest complete checkpoint instead of
            # failing the whole research task at the deadline.
            return {}
    text = asyncio.run(host._analyze_winning_mechanism(payload))
    return _parse_json_object(text)


def design_discovery_blueprint(host, payload: dict[str, Any]) -> dict[str, Any]:
    if host.provider_kind != "codex_cli":
        return {}
    return _parse_json_object(
        asyncio.run(
            host._run_core_json(
                "orchestrator",
                orchestrator_system_prompt("blueprint_design"),
                payload,
                BLUEPRINT_OUTPUT_SCHEMA,
                1800,
                phase="blueprint_design",
            )
        )
    )


def converge_discovery_outputs(host, payload: dict[str, Any]) -> dict[str, Any]:
    if host.provider_kind != "codex_cli":
        packets = payload.get("packets", [])
        return {
            "clusters": [
                {
                    "name": str(item.get("agent_id", "baseline")),
                    "packet_ids": [str(item.get("packet_id", ""))],
                }
                for item in packets
            ],
            "conflicts": [],
            "priorities": [
                str(item.get("handoff_summary", "")) for item in packets[:6]
            ],
            "cross_branch_links": [],
            "open_questions": [],
        }
    return _parse_json_object(
        asyncio.run(
            host._run_core_json(
                "convergence_fusion",
                "你是收敛融合Agent。跨背景、跨场景、跨分支聚类基线发现，去重但不得抹去冲突，"
                "形成优先序、跨分支关联和需要回传的问题。只输出严格JSON。",
                payload,
                {
                    "clusters": [
                        {
                            "name": "string",
                            "packet_ids": ["string"],
                            "shared_need": "string",
                        }
                    ],
                    "conflicts": ["string"],
                    "priorities": ["string"],
                    "cross_branch_links": ["string"],
                    "open_questions": ["string"],
                },
                4000,
            )
        )
    )


def review_discovery_meta_loop(host, payload: dict[str, Any]) -> dict[str, Any]:
    if host.provider_kind != "codex_cli":
        return {}
    return _parse_json_object(
        asyncio.run(
            host._run_core_json(
                "orchestrator",
                orchestrator_system_prompt("discovery_meta_replan"),
                payload,
                META_REPLAN_OUTPUT_SCHEMA,
                3000,
                phase="discovery_meta_replan",
            )
        )
    )


def review_audit(host, payload: dict[str, Any]) -> dict[str, Any]:
    optimized_v2 = is_quality_execution_profile_id(
        payload.get("execution_profile_id")
    )
    timeout_seconds = max(
        10.0,
        float(
            os.environ.get(
                "EQUIPMENT_DR_AUDIT_TIMEOUT_SECONDS",
                "30" if optimized_v2 else "75",
            )
        ),
    )
    return _parse_json_object(
        asyncio.run(
            asyncio.wait_for(
                host._run_core_json(
                    "auditor",
                    "你是独立审计Agent。输入是确定性审计摘要，不是待重新研究的原始材料。"
                    "只复核门控遗漏、证据追溯缺口、结论越界和发布风险；不得修改事实、"
                    "重复完整研究或自行放宽门控。发现最多4条，每条必须指向具体检查项、"
                    "层级或能力对象。只输出严格JSON。",
                    payload,
                    {
                        "risk_summary": "string",
                        "findings": ["string"],
                        "release_recommendation": "approved|limited",
                    },
                    700 if optimized_v2 else 1200,
                    phase="audit_review",
                ),
                timeout=timeout_seconds,
            )
        )
    )


async def select_agents_async(host, request: AgentSelectionRequest) -> str:
    return await host._run_core_json(
        "orchestrator",
        orchestrator_system_prompt("agent_selection"),
        {
            "topic": request.topic,
            "research_route": request.research_route,
            "required_capability_tags": request.required_capability_tags,
            "candidate_agents": request.candidates,
        },
        AGENT_SELECTION_OUTPUT_SCHEMA,
        3200,
        phase="agent_selection",
    )


async def analyze_winning_mechanism_async(host, payload: dict[str, Any]) -> str:
    return await host._run_core_json(
        "winning_mechanism",
        "你是装备能力图像系统的核心制胜机理智能体。严格依据输入中的结构化packet、"
        "正式证据、coverage和冲突集，完成防御解构、制胜路径、效果链、能力映射、"
        "五档差距和能力画像建议，并按discovery_blueprint.primary_branch生成分支专用"
        "branch_products。A分支应在证据允许时形成3种新战法、5种战法组合、8大能力域、"
        "30项能力指标和装备形态建议；B分支形成可追溯需求卡片/全景图的分析依据；C分支"
        "形成6条案例规律、3类高置信未来场景和4类新兴装备类别；D-H参照各自驱动源生成"
        "规律/场景/能力域/指标/装备形态。每个能力方向必须基于多点正式证据和S1-S6结果，"
        "分别给出military_value、depth_mechanism、foresight和novelty，说明任务效能与体系"
        "贡献、因果机制、未来触发条件/失效边界、相对现有基线的新增机制。数量不足必须保留真实缺口，禁止凑数。"
        "不得补造证据或越过门控。只输出严格JSON；除capability_indicators最多30项外，"
        "其他数组通常最多8项，总输出不超过7500 tokens。",
        {"winning_mechanism_input": payload},
        {
            "defense_decomposition": ["string"],
            "winning_paths": ["string"],
            "effect_chain": ["string"],
            "capability_mapping": ["string"],
            "gap_assessment": [
                {
                    "capability": "string",
                    "grade": "空白|关键差距|部分差距|满足|超出",
                    "basis": "string",
                }
            ],
            "concept_directions": [
                {
                    "name": "string",
                    "type": "new_capability|upgrade",
                    "function": "string",
                    "project_function": "who uses the concrete equipment under what conditions to produce what mission result",
                    "feasibility": "1..5",
                    "military_value": "string",
                    "depth_mechanism": "string",
                    "foresight": "string",
                    "novelty": "string",
                }
            ],
            "branch_products": {
                "tactic_concepts": ["string"],
                "tactic_combinations": ["string"],
                "capability_domains": ["string"],
                "capability_indicators": ["string"],
                "equipment_forms": ["string"],
                "case_patterns": ["string"],
                "future_scenarios": ["string"],
                "emerging_equipment_categories": ["string"],
                "technology_opportunities": ["string"],
                "threat_patterns": ["string"],
                "system_vulnerabilities": ["string"],
                "cross_domain_gaps": ["string"],
                "emerging_threat_profiles": ["string"],
            },
            "assumptions": ["string"],
            "open_questions": ["string"],
            "confidence": "0..1",
        },
        8000,
        phase="winning_synthesis",
    )
