"""Parallel S6 card authoring, retries and checkpoint reuse."""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import (
    Callable,
    Mapping,
    Sequence,
)
from hashlib import (
    sha256,
)
from typing import (
    Any,
)

from equipment_deep_research.agents.dynamic_prompt_resources import (
    load_dynamic_winning_json,
)
from equipment_deep_research.agents.workflows.coordinator import (
    S6QualityError,
    _compact_prompt_value,
    _parse_json_object,
)
from equipment_deep_research.agents.workflows.s6_quality import (
    _evidence_boundary_is_public_semantic,
    _indicator_portrait_is_specific,
    _prepare_pre_s6_card_contract,
    _query_relevance_is_specific,
    _s6_card_is_reusable,
    _s6_cross_card_identity_issues,
    _s6_portfolio_confidence,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    S6_PORTRAIT_QUALITY_CONTRACT_VERSION,
    _compact_s6_authored_card_event,
    _dynamic_s6_card_input,
    _dynamic_s6_input_fingerprint,
    _dynamic_s6_module_instruction,
    _dynamic_s6_module_guidance,
    _dynamic_s6_module_repair_instruction,
    _dynamic_s6_spine_instruction,
    _extract_s6_direction,
    _minimal_s6_card_handoff,
    _parallel_s6_card_instruction,
    _parallel_s6_quality_repair_instruction,
    _s6_card_attempt_limit,
    _s6_card_timeout_threshold,
    _s6_hard_timeout_is_enabled,
    _bounded_s6_parallelism,
    _s6_portrait_module_lengths,
    _s6_repair_wall_timeout_seconds,
    _s6_short_portrait_modules,
    _stabilize_s6_direction_structure,
    _targeted_expert_feedback,
)
from equipment_deep_research.domain.capability_portrait import (
    CAPABILITY_PORTRAIT_MODULES,
    S6_DEFAULT_CODEX_CONCURRENCY,
    S6_MAX_CODEX_CONCURRENCY,
    assemble_capability_portrait_modules,
    capability_portrait_quality_issues,
    capability_portrait_repair_issues,
    coerce_portrait_module_prose,
    parse_capability_portrait_modules,
    portrait_module_has_incomplete_ending,
)
from equipment_deep_research.contracts.runtime import CardRuntime


class S6SpineAuthoringError(S6QualityError):
    """A card-level failure that is safe to recover by replaying the card."""


def _dynamic_s6_one_shot_enabled(dynamic_s6_authoring: bool) -> bool:
    if not dynamic_s6_authoring:
        return False
    configured = os.environ.get(
        "EQUIPMENT_DR_S6_AUTHORING_MODE", "parallel_modules"
    )
    return configured.strip().lower() in {"one_shot", "oneshot", "single", "card"}


def _s6_authoring_prompt_resource() -> dict[str, Any]:
    """Load model-facing S6 schema/instruction fragments from Markdown."""

    value = load_dynamic_winning_json("common", section="s6_authoring.contracts")
    if not isinstance(value, Mapping):
        raise ValueError("S6 authoring prompt resource must be an object")
    return dict(value)


def _merge_s6_repaired_modules(
    first_pass_modules: Mapping[str, Any],
    repaired_modules: Mapping[str, Any],
    initially_short_modules: Sequence[str],
) -> dict[str, Any]:
    """Overlay only columns that were explicitly scheduled for repair."""

    merged = dict(first_pass_modules)
    for key in initially_short_modules:
        merged[key] = repaired_modules.get(key, "")
    return merged


def _extract_s6_module_content(
    parsed: Mapping[str, Any] | object,
    module_key: str,
) -> str:
    """Accept native single-column JSON or legacy whole-card wrappers.

    ``module_content`` must be one complete Chinese prose draft. Nested objects
    and Python/JSON dict dumps are rejected so the column is re-authored
    instead of being stringified with raw schema keys.
    """

    if not isinstance(parsed, Mapping):
        return ""
    direct = coerce_portrait_module_prose(
        parsed.get("module_content", ""),
        module_key=module_key,
        allow_structured_salvage=False,
    )
    if direct:
        return direct
    if module_key in {item[0] for item in CAPABILITY_PORTRAIT_MODULES}:
        keyed = coerce_portrait_module_prose(
            parsed.get(module_key, ""),
            module_key=module_key,
            allow_structured_salvage=False,
        )
        if keyed:
            return keyed
    direction = _extract_s6_direction(parsed)
    modules = direction.get("capability_portrait_modules", {})
    if isinstance(modules, Mapping):
        return coerce_portrait_module_prose(
            modules.get(module_key, ""),
            module_key=module_key,
            allow_structured_salvage=False,
        )
    return ""


def _s6_repair_meets_length_contract(
    repaired_modules: Mapping[str, Any] | object,
    initially_short_modules: Sequence[str],
) -> bool:
    """Accept a semantically complete repair without enforcing a word floor.

    Length remains an editorial target, not a reason to manufacture prose.
    The pending keys are retained for API compatibility with older callers;
    they only identify modules that must remain present and non-empty.
    """

    del initially_short_modules
    required = {key for key, _ in CAPABILITY_PORTRAIT_MODULES}
    if not isinstance(repaired_modules, Mapping):
        return False
    if not (required <= set(repaired_modules) and all(
        str(repaired_modules.get(key, "")).strip() for key in required
    )):
        return False
    return not any(
        portrait_module_has_incomplete_ending(repaired_modules.get(key, ""))
        for key in required
    )


def _portrait_repair_keys(
    modules: Mapping[str, Any], issues: Sequence[str]
) -> list[str]:
    """Scope repairs to diagnosed columns, preserving complete siblings.

    A global diagnostic still needs the whole set. A soft length target alone
    does not authorize rewriting a column when a different column is broken.
    """

    keys = {
        key
        for key, _ in CAPABILITY_PORTRAIT_MODULES
        if not str(modules.get(key, "")).strip()
        or portrait_module_has_incomplete_ending(modules.get(key, ""))
    }
    for issue in issues:
        named = {
            key for key, label in CAPABILITY_PORTRAIT_MODULES
            if key in issue or label in issue
        }
        if named:
            keys.update(named)
        elif "缺少完整五栏" not in issue or not keys:
            return [key for key, _ in CAPABILITY_PORTRAIT_MODULES]
    return [key for key, _ in CAPABILITY_PORTRAIT_MODULES if key in keys]


def _s6_repair_root_fingerprints(issues: Sequence[str]) -> frozenset[str]:
    """Collapse S6 diagnostics to the causes a single repair wave can fix.

    The quality gate intentionally reports every affected column, while one
    parallel repair wave should make one decision per root cause.  Comparing
    these fingerprints prevents a no-op rewrite from being recorded as a
    successful enhancement and later retried for the same reason.
    """

    roots: set[str] = set()
    for issue in issues:
        text = " ".join(str(issue or "").split()).strip()
        if not text:
            continue
        if "跨栏重复" in text:
            roots.add("cross_column_repetition")
        elif "缺少独占信息" in text:
            roots.add("missing_exclusive_information")
        elif "明显过短" in text:
            label = text.split("明显过短", 1)[0].strip()
            roots.add(f"short_module:{label}")
        elif "句末疑似截断" in text:
            label = text.split("句末疑似截断", 1)[0].strip()
            roots.add(f"incomplete_ending:{label}")
        else:
            # Strip volatile counts so the same semantic defect is stable
            # across attempts and audit records.
            roots.add(re.sub(r"\d+", "#", text)[:240])
    return frozenset(roots)


def _parallel_s6_semantic_quality_issues(
    modules: Mapping[str, Any] | object,
) -> list[str]:
    """Catch hollow but well-sized columns before publishing a dynamic card."""

    issues = capability_portrait_repair_issues(modules)
    if not isinstance(modules, Mapping):
        return issues

    short_modules = _s6_short_portrait_modules(modules)
    labels = dict(CAPABILITY_PORTRAIT_MODULES)
    for module_key in short_modules:
        issue = (
            f"{labels[module_key]}明显过短，低于约360字软目标；"
            "请补足本栏独有的作战论证，不得用泛化句凑字"
        )
        if issue not in issues:
            issues.append(issue)

    marker_rules = {
        "technology_implementation": (
            "装备与技术实现未形成路线取舍和主攻链",
            r"路线|路径|方案|主路径|备选|取舍|瓶颈|攻关|落装|工程|主攻|核心|实现",
            2,
        ),
        "operational_process": (
            "关键作战流程未形成条件、动作、状态变化和转段闭环",
            r"条件|授权|进入|行动|发射|释放|部署|确认|切换|转入|拒打|终止|续接|脱离|回传|交给",
            4,
        ),
        "capability_effects": (
            "形成能力与作战效果未区分新增任务、直接战果和敌方代价",
            r"过去|原有|无法|不能|新增|现在|直接|战果|打开|形成|迫使|代价|成本|空间",
            4,
        ),
        "winning_logic": (
            "制胜逻辑机理未闭合旧规则、交换关系、经济反制和新增代价",
            r"规则|假设|交换|敌方|对手|反制|代价|成本|暴露|兵力|时间|空间|防御|编组|持续",
            5,
        ),
    }
    for key, (message, pattern, minimum) in marker_rules.items():
        text = str(modules.get(key, "") or "")
        if len(re.findall(pattern, text)) < minimum:
            issues.append(message)
    return list(dict.fromkeys(issues))


async def generate_parallel_s6_cards(
    *,
    accumulated: dict[str, Any],
    dynamic_s6_authoring: bool,
    parallel_portrait_modules: bool | None = None,
    emit_swarm_event: Callable[..., Any],
    host: CardRuntime,
    requested_resume_steps: Sequence[int],
    shared: Mapping[str, Any],
    agent_id: str,
    system: str,
    schema: Mapping[str, Any],
    step_input: Mapping[str, Any],
) -> dict[str, Any]:
    """Plan one portfolio, then author cards with concurrent Codex/model calls.

    Dynamic-v2 freezes a compact decision spine and fans out the five portrait
    columns in parallel. ``dynamic_s6_authoring`` controls the compact
    dynamic handoff; ``parallel_portrait_modules`` remains an explicit
    compatibility switch for legacy callers. Each scoped call still uses the
    normal provider isolation path (one ephemeral Codex process per turn).
    """

    if parallel_portrait_modules is None:
        # Keep the argument for old embedders that explicitly select the
        # bounded spine plus five-column fan-out.
        parallel_portrait_modules = True
    parallel_portrait_modules = bool(parallel_portrait_modules)
    one_shot_authoring = _dynamic_s6_one_shot_enabled(dynamic_s6_authoring)
    if one_shot_authoring:
        parallel_portrait_modules = False
    prompt_contract = _s6_authoring_prompt_resource()

    direction_schema = schema["concept_directions"][0]
    # Per-column prose is owned by the Markdown S6 prompt resource.  Keep the
    # Python schema limited to field shape so concurrent authoring can evolve
    # wording without changing orchestration code.
    portrait_modules_schema = {
        key: _dynamic_s6_module_guidance(key)
        for key, _ in CAPABILITY_PORTRAIT_MODULES
    }
    card_direction_schema = {
        key: direction_schema[key]
        for key in (
            "name",
            "function",
            "military_value",
            "equipment_form",
            "primary_equipment_identity",
            "operational_mechanism",
            "capability_classification",
            "equipment_semantic_assessment",
            "target_scenario",
            "problem_statement",
            "scientific_principle",
            "enabling_technologies",
            "operational_concept",
            "operational_process",
            "semantic_consistency_check",
            "capability_outcome",
            "winning_mechanism",
            "system_contribution_thesis",
            "adversary_adaptation",
            "capability_portrait",
        )
        if key in direction_schema
    }
    card_direction_schema.pop("capability_portrait", None)
    card_direction_schema["card_binding_id"] = prompt_contract[
        "card_binding_id_strict"
    ]
    card_direction_schema["hypothesis_id"] = prompt_contract[
        "hypothesis_id_strict"
    ]
    card_direction_schema["system_contribution_thesis"] = prompt_contract[
        "system_contribution_thesis"
    ]
    card_direction_schema["indicator_portrait"] = prompt_contract[
        "indicator_portrait"
    ]
    card_direction_schema["operational_concept"] = prompt_contract[
        "operational_concept"
    ]
    card_direction_schema["adversary_adaptation"] = prompt_contract[
        "adversary_adaptation"
    ]
    # Keep all model-visible field guidance in the reviewed Markdown resource;
    # only the structural keys come from the caller's schema.
    direction_guidance = load_dynamic_winning_json(
        "common", section="s6_authoring.direction_schema"
    )
    if isinstance(direction_guidance, Mapping):
        for key, guidance in direction_guidance.items():
            if key in card_direction_schema:
                card_direction_schema[key] = guidance
    card_direction_schema["capability_portrait_modules"] = portrait_modules_schema
    # Dynamic S6 already receives a frozen weapon identity. Requiring it
    # to regenerate the full legacy direction duplicates upstream data and
    # makes the five long portrait modules compete with low-value JSON
    # fields for output tokens. Keep only fields that require fresh S6
    # military judgement; routing and identity are restored locally.
    dynamic_card_direction_schema = {
        key: card_direction_schema[key]
        for key in (
            "capability_classification",
            "target_scenario",
            "scientific_principle",
            "operational_concept",
            "operational_process",
            "semantic_consistency_check",
            "capability_outcome",
            "winning_mechanism",
            "system_contribution_thesis",
            "indicator_portrait",
            "adversary_adaptation",
            "capability_portrait_modules",
        )
        if key in card_direction_schema
    }
    active_card_direction_schema = (
        dynamic_card_direction_schema if dynamic_s6_authoring else card_direction_schema
    )
    handoff = step_input.get("capability_synthesis_handoff", {})
    handoff = handoff if isinstance(handoff, Mapping) else {}
    selected_portfolio = handoff.get("selected_equipment_portfolio", [])
    selected_portfolio = (
        [dict(item) for item in selected_portfolio if isinstance(item, Mapping)]
        if isinstance(selected_portfolio, list)
        else []
    )
    # The compact handoff may omit fields that already exist in the
    # authoritative S5 portfolio. Reattach those exact upstream semantics
    # before authoring so a provider failure can preserve the complete
    # candidate rather than degrade into a sparse title-only row.
    authoritative_portfolio_rows: list[dict[str, Any]] = []
    for source in (
        accumulated.get("winning_swarm", {}).get("final_equipment_portfolio", [])
        if isinstance(accumulated.get("winning_swarm", {}), Mapping)
        else [],
        shared.get("prior_winning_analysis", {})
        .get("winning_swarm", {})
        .get("final_equipment_portfolio", [])
        if isinstance(shared.get("prior_winning_analysis", {}), Mapping)
        and isinstance(
            shared.get("prior_winning_analysis", {}).get("winning_swarm", {}),
            Mapping,
        )
        else [],
        shared.get("prior_winning_analysis", {}).get("concept_directions", [])
        if isinstance(shared.get("prior_winning_analysis", {}), Mapping)
        else [],
    ):
        if not isinstance(source, list):
            continue
        authoritative_portfolio_rows.extend(
            dict(item) for item in source if isinstance(item, Mapping)
        )
    authoritative_by_id = {
        str(item.get("hypothesis_id", "")).strip(): item
        for item in authoritative_portfolio_rows
        if str(item.get("hypothesis_id", "")).strip()
    }
    authoritative_by_name = {
        str(item.get("name", "")).strip(): item
        for item in authoritative_portfolio_rows
        if str(item.get("name", "")).strip()
    }
    selected_portfolio = [
        {
            **dict(
                authoritative_by_id.get(
                    str(item.get("hypothesis_id", "")).strip(),
                    authoritative_by_name.get(
                        str(item.get("name", "")).strip(),
                        {},
                    ),
                )
            ),
            **item,
        }
        for item in selected_portfolio
    ]
    card_capacity = max(
        1,
        min(12, int(handoff.get("s6_card_capacity", 12) or 12)),
    )
    planner_schema = {
        key: value
        for key, value in schema.items()
        if key not in {"concept_directions", "capability_image_drafts"}
    }
    planner_brief_contract = {
        "position": 1,
        "name": prompt_contract["planner_name"],
        "type": "new_capability|upgrade",
        "primary_equipment_identity": prompt_contract[
            "planner_primary_equipment_identity"
        ],
        "equipment_form": prompt_contract["planner_equipment_form"],
        "unique_operational_role": prompt_contract[
            "planner_unique_operational_role"
        ],
        "launch_or_release_domain": prompt_contract[
            "planner_launch_or_release_domain"
        ],
        "target_and_direct_effect": prompt_contract[
            "planner_target_and_direct_effect"
        ],
        "non_substitutable_difference": prompt_contract[
            "planner_non_substitutable_difference"
        ],
        "baseline_system": prompt_contract["planner_baseline_system"],
        "capability_gap": prompt_contract["planner_capability_gap"],
        "direct_evidence_refs": prompt_contract["planner_direct_evidence_refs"],
        "foresight_evidence_status": prompt_contract[
            "planner_foresight_evidence_status"
        ],
        "evidence_boundary": prompt_contract["planner_evidence_boundary"],
        "validation_plan": prompt_contract["planner_validation_plan"],
        "indicator_portrait": prompt_contract["planner_indicator_portrait"],
        "query_relevance": prompt_contract["planner_query_relevance"],
        "concise_winning_summary": prompt_contract["planner_summary"],
    }
    planner_schema["card_briefs"] = [
        planner_brief_contract
    ]
    # The dynamic swarm has already selected these candidates through
    # its independent evidence and portfolio review.  Do not make S6
    # discard them merely to satisfy a fixed card count: turn every
    # selected, independently evidenced weapon into one card brief.
    pre_s6_candidate_names = [
        str(item.get("candidate_equipment", "")).strip()
        for item in handoff.get("equipment_portfolio_preflight", [])
        if isinstance(item, Mapping)
        and item.get("ready") is True
        and str(item.get("candidate_equipment", "")).strip()
    ]
    if selected_portfolio:
        plan = {"portfolio_source": "winning_swarm_selected_candidates"}
        briefs = selected_portfolio[:card_capacity]
    else:
        if not pre_s6_candidate_names:
            plan = {
                "portfolio_source": "s5_handoff_empty_limited",
                "s6_card_authoring_limited": True,
                "s6_card_authoring_warnings": [
                    "S3–S5未传入可写卡装备；S6保留上游结果并受限交付"
                ],
            }
            briefs = []
        else:
            planner_text = await host._run_core_json(
                agent_id,
                system + prompt_contract["portfolio_planner"],
                {
                    **dict(step_input),
                    "locked_pre_s6_candidate_names": pre_s6_candidate_names,
                },
                planner_schema,
                2400,
                phase="winning_s6_portfolio_plan",
            )
            plan = _parse_json_object(planner_text)
            briefs = [
                dict(item)
                for item in plan.get("card_briefs", [])
                if isinstance(item, Mapping)
            ][:card_capacity]
            for position, brief in enumerate(briefs):
                if position < len(pre_s6_candidate_names):
                    brief["name"] = pre_s6_candidate_names[position]
    briefs = [
        _prepare_pre_s6_card_contract(
            brief,
            query=str(step_input.get("query", "")),
        )
        for brief in briefs
    ]
    binding_scope = str(shared.get("run_id") or shared.get("topic") or "winning-s6")
    for brief in briefs:
        hypothesis_id = str(brief.get("hypothesis_id") or "").strip()
        if not hypothesis_id:
            continue
        brief["card_binding_id"] = (
            "s6-card-"
            + sha256(f"{binding_scope}:{hypothesis_id}".encode("utf-8")).hexdigest()[
                :20
            ]
        )
    if not briefs:
        # A targeted S6 resume still needs one governed diagnostic pass even
        # when the checkpoint omitted the card handoff.  This occurs for old
        # runs that persisted the gate/trace before persisting candidate
        # cards.  Let the model preserve or reconstruct the structured result
        # under the normal S6 deadline lane; never synthesize a replacement
        # card from an empty handoff.
        if requested_resume_steps == [6]:
            text = await host._run_core_json(
                agent_id,
                system,
                dict(step_input),
                schema,
                5200,
                phase="winning_s6_image_deadline_recovery",
            )
            recovered = _parse_json_object(text)
            if recovered:
                return recovered
        limited_result = {
            key: [] if isinstance(value, list) else "" for key, value in schema.items()
        }
        limited_result["concept_directions"] = []
        limited_result["capability_image_drafts"] = []
        limited_result["s6_card_authoring_limited"] = True
        limited_result["s6_card_authoring_warnings"] = list(
            plan.get("s6_card_authoring_warnings", [])
        ) or ["S6没有收到可写卡的冻结装备，已保留S1–S5结果"]
        emit_swarm_event(
            "winning_s6_card_authoring_limited",
            actor=agent_id,
            card_position=0,
            status="limited",
            failure_type="empty_s5_handoff",
        )
        return limited_result
    # Dynamic-v2 deliberately does not make S6 depend on S5's prose,
    # indicators, classification or evidence contract.  Those fields are
    # authored by the isolated S6 model from the three-item semantic
    # input; checking them here would reintroduce the old lock-in before
    # the model gets a chance to reason.
    pre_s6_contract_issues: list[str] = []
    if not dynamic_s6_authoring:
        for position, brief in enumerate(briefs, start=1):
            if not _indicator_portrait_is_specific(brief.get("indicator_portrait")):
                pre_s6_contract_issues.append(
                    f"S5第{position}项指标画像未闭合测量轴、对照基线与判退条件"
                )
            if not _query_relevance_is_specific(brief.get("query_relevance")):
                pre_s6_contract_issues.append(
                    f"S5第{position}项未闭合任务对象、作战阶段、威胁压力和直接战果关联"
                )
            boundary = str(brief.get("evidence_boundary", "") or "").strip()
            if boundary and not _evidence_boundary_is_public_semantic(boundary):
                pre_s6_contract_issues.append(
                    f"S5第{position}项证据边界不是公开证据支持/不支持的语义陈述"
                )
    if pre_s6_contract_issues:
        emit_swarm_event(
            "winning_s6_card_authoring_limited",
            actor=agent_id,
            card_position=0,
            status="limited",
            failure_type="s5_handoff_semantic_warning",
            warnings=pre_s6_contract_issues[:8],
        )
    emit_swarm_event(
        "winning_s5_handoff_quality_gate_completed",
        card_count=len(briefs),
        indicator_contracts=len(briefs),
        query_relevance_contracts=len(briefs),
        status="completed",
    )
    brief_names = [str(item.get("name", "")).strip() for item in briefs]
    if not all(brief_names) or len(set(brief_names)) != len(brief_names):
        emit_swarm_event(
            "winning_s6_card_authoring_limited",
            actor=agent_id,
            card_position=0,
            status="limited",
            failure_type="s5_handoff_title_warning",
            warnings=["S5交接中存在空标题或重复标题；S6按冻结身份继续写卡"],
        )

    # Five portrait calls plus the decision spine are the independent units of
    # one card. Keep the explicit S6 lane bounded; the gate is raised
    # to the same value for this wave below so an older run-wide cap (often 4–6)
    # cannot silently serialize the columns.
    try:
        handoff_parallelism = int(
            handoff.get("s6_parallelism", S6_DEFAULT_CODEX_CONCURRENCY)
            or S6_DEFAULT_CODEX_CONCURRENCY
        )
    except (TypeError, ValueError):
        handoff_parallelism = S6_DEFAULT_CODEX_CONCURRENCY
    # Apply the deployment/operator ceiling even when an execution profile
    # carries a larger handoff value.  Otherwise the local semaphore can
    # advertise a safe limit while still admitting a provider-capacity burst.
    configured_s6_parallelism = min(
        handoff_parallelism,
        _bounded_s6_parallelism(
            shared.get("runtime_budgets", {})
            if isinstance(shared.get("runtime_budgets", {}), Mapping)
            else {}
        ),
    )
    s6_parallelism = max(
        1,
        min(S6_MAX_CODEX_CONCURRENCY, configured_s6_parallelism),
    )
    call_semaphore = asyncio.Semaphore(s6_parallelism)
    emit_swarm_event(
        "winning_s6_parallel_authoring_configured",
        actor=agent_id,
        status="enabled" if parallel_portrait_modules else "card_only",
        card_concurrency=s6_parallelism,
        portrait_modules=[key for key, _ in CAPABILITY_PORTRAIT_MODULES],
        portrait_module_prompts={
            key: f"S6_{index}"
            for index, (key, _label) in enumerate(CAPABILITY_PORTRAIT_MODULES, start=1)
        },
        process_isolation=(
            "new_process_per_turn" if parallel_portrait_modules else "card_scoped"
        ),
    )
    resume_s6_only = requested_resume_steps == [6] and bool(
        shared.get("prior_winning_analysis")
    )
    card_cache_scope = str(shared.get("run_id") or shared.get("topic") or "winning-s6")

    def dynamic_card_payload(brief: Mapping[str, Any]) -> dict[str, Any]:
        """Build one stable dynamic S6 input with the card's factual spine."""

        return _dynamic_s6_card_input(
            brief,
            query=str(step_input.get("query", "")),
        )

    def parallel_card_payload(brief: Mapping[str, Any]) -> dict[str, Any]:
        """Build the compact, identity-frozen payload shared by five columns.

        Optimized/quality profiles historically sent ``assigned_card`` to one
        monolithic S6 call.  The column calls need the same factual anchors as
        that call, but exposing the full orchestration envelope makes each
        isolated process verbose and encourages template completion.  Keep the
        dynamic three-part envelope and add only the frozen S5 decision-spine
        fields that are useful to a column author.  The authoritative row is
        still reattached locally before publication.
        """

        payload = _dynamic_s6_card_input(
            brief,
            query=str(step_input.get("query", "")),
        )
        candidate_weapon = dict(payload.get("candidate_weapon", {}))
        frozen_fields = (
            "unique_operational_role",
            "launch_or_release_domain",
            "non_substitutable_difference",
            "query_relevance",
            "indicator_portrait",
            "innovation_basis",
            "frontier_principle",
            "technology_discontinuity",
            "core_disruptive_difference",
            "displaced_operational_mode",
            "new_operational_mode",
            "winning_relation_shift",
            "baseline_system",
            "capability_gap",
        )
        for field in frozen_fields:
            value = brief.get(field)
            if value in (None, "", [], {}):
                continue
            candidate_weapon[field] = _compact_prompt_value(
                value,
                max_string_chars=720,
                max_list_items=8,
            )
        # The binding/hypothesis pair is intentionally repeated in every
        # process payload.  Runtime uses parallel_card_id for the process
        # scope; the model uses these values to prevent cross-card leakage.
        candidate_weapon["card_binding_id"] = str(
            brief.get("card_binding_id", "")
        ).strip()
        candidate_weapon["hypothesis_id"] = str(
            brief.get("hypothesis_id", "")
        ).strip()
        payload["candidate_weapon"] = candidate_weapon
        # Preserve the quality-profile runtime card while still using the
        # compact three-part envelope.  The dynamic runtime detector uses this
        # marker to avoid stripping methodology/quality gates from optimized
        # and swarm-quality S6 calls.
        payload["s6_authoring_mode"] = "quality_parallel"
        return payload

    def card_cache_key(brief: Mapping[str, Any]) -> tuple[str, str]:
        identity = str(brief.get("hypothesis_id") or brief.get("name") or "").strip()
        if dynamic_s6_authoring:
            fingerprint = _dynamic_s6_input_fingerprint(
                dynamic_card_payload(brief)
            )
            identity = f"{identity}:{fingerprint[:20]}"
        return card_cache_scope, identity

    def limited_card_from_brief(
        position: int,
        brief: Mapping[str, Any],
        failure: BaseException,
    ) -> tuple[int, dict[str, Any], str]:
        """Preserve only S5 evidence when independent S6 prose is unavailable.

        The S5 handoff already contains the frozen identity, combat role,
        mechanism, process, evidence boundary and falsification contract.
        It remains useful as a rerun reference, but it is not reformatted or
        promoted as a completed capability portrait. Provider failure is
        recorded explicitly so publication cannot mistake it for authored S6
        content.
        """

        direction = dict(brief)
        identity_contract = direction.get("portfolio_identity_contract", {})
        identity_contract = (
            dict(identity_contract) if isinstance(identity_contract, Mapping) else {}
        )
        operational_axes = identity_contract.get("operational_axes", {})
        operational_axes = (
            dict(operational_axes) if isinstance(operational_axes, Mapping) else {}
        )
        process = direction.get("operational_process", [])
        if not isinstance(process, list) or not process:
            process = operational_axes.get("mechanism_and_timing", [])
        if not isinstance(process, list) or not process:
            process = direction.get("mechanism_chain", [])
        process = [str(item).strip() for item in process if str(item).strip()]
        if process:
            direction["operational_process"] = process

        equipment_form = str(
            direction.get("equipment_form")
            or direction.get("primary_equipment_identity")
            or direction.get("name")
            or ""
        ).strip()
        direct_effect = str(
            direction.get("military_value")
            or direction.get("target_and_direct_effect")
            or direction.get("capability_outcome")
            or direction.get("unique_operational_role")
            or ""
        ).strip()
        mechanism = str(
            direction.get("winning_mechanism")
            or direction.get("operational_mechanism")
            or direction.get("depth_mechanism")
            or direction.get("non_substitutable_difference")
            or ""
        ).strip()
        if not str(direction.get("operational_mechanism", "")).strip():
            direction["operational_mechanism"] = mechanism or "；".join(process)
        if not str(direction.get("military_value", "")).strip():
            direction["military_value"] = direct_effect
        if not str(direction.get("capability_outcome", "")).strip():
            direction["capability_outcome"] = direct_effect
        if not str(direction.get("winning_mechanism", "")).strip():
            direction["winning_mechanism"] = mechanism
        for singular, plural in (
            ("adversary_adaptation", "adversary_adaptations"),
        ):
            if str(direction.get(singular, "")).strip():
                continue
            plural_value = direction.get(plural, [])
            if isinstance(plural_value, list):
                direction[singular] = "；".join(
                    str(item).strip() for item in plural_value[:3] if str(item).strip()
                )
            elif str(plural_value or "").strip():
                direction[singular] = str(plural_value).strip()
        # A provider-limited card is not a capability portrait.  Do not turn
        # frozen S5 semantics into a generic five-column template; the card is
        # kept as a traceable, explicitly limited result until S6 is rerun.
        direction["capability_portrait_modules"] = {}
        direction["capability_portrait"] = ""
        direction["portrait_module_character_counts"] = {}
        direction["portrait_quality_contract_version"] = (
            S6_PORTRAIT_QUALITY_CONTRACT_VERSION
        )
        direction["semantic_consistency_check"] = {
            "process_actor": equipment_form,
            "launch_or_release_mode": str(
                direction.get("launch_or_release_domain", "")
            ),
            "target_and_direct_effect": str(
                direction.get("target_and_direct_effect") or direct_effect
            ),
            "checked_fields": [
                "name",
                "primary_equipment_identity",
                "equipment_form",
                "operational_process",
                "capability_portrait",
            ],
            "consistent": True,
            "resolution_note": (
                "主装备、发射域、目标、作战流程和直接战果均沿用同一冻结候选，"
                "未发生换装或跨卡吸收。"
            ),
        }
        direction["s6_authoring_status"] = "limited_provider_failure"
        direction["s6_authoring_failure_type"] = type(failure).__name__
        direction["s6_authoring_quality_warnings"] = [
            "S6独立成稿与定向恢复均失败；能力画像正文未生成，须针对该武器装备重跑S6"
        ]
        draft = str(
            direction.get("concise_winning_summary")
            or direction.get("capability_outcome")
            or direction.get("military_value")
            or direction.get("name")
            or ""
        ).strip()
        return position, direction, draft

    # The in-memory cache disappears when a worker/process restarts.
    # Rehydrate it from the persisted S6 checkpoint so a resume never
    # reauthors cards that already completed successfully.
    prior_analysis = shared.get("prior_winning_analysis", {})
    prior_directions = (
        prior_analysis.get("concept_directions", [])
        if isinstance(prior_analysis, Mapping)
        else []
    )
    if isinstance(prior_directions, list):
        prior_by_identity: dict[str, Mapping[str, Any]] = {}
        for item in prior_directions:
            if not isinstance(item, Mapping) or not _s6_card_is_reusable(item):
                continue
            for identity in (
                str(item.get("hypothesis_id", "")).strip(),
                str(item.get("name", "")).strip(),
            ):
                if identity:
                    prior_by_identity[identity] = item
        for brief in briefs:
            identity = str(
                brief.get("hypothesis_id") or brief.get("name") or ""
            ).strip()
            prior = prior_by_identity.get(identity)
            if prior is None:
                prior = prior_by_identity.get(str(brief.get("name", "")).strip())
            if prior is None:
                continue
            prior_direction = dict(prior)
            if dynamic_s6_authoring:
                expected_fingerprint = _dynamic_s6_input_fingerprint(
                    dynamic_card_payload(brief)
                )
                if (
                    str(prior_direction.get("_s6_authoring_input_fingerprint", ""))
                    != expected_fingerprint
                ):
                    continue
            host._s6_card_result_cache[card_cache_key(brief)] = (
                prior_direction,
                str(
                    prior_direction.get("capability_outcome")
                    or prior_direction.get("name")
                    or ""
                ).strip(),
            )

    async def author_card(
        position: int,
        brief: Mapping[str, Any],
        *,
        attempt: int = 1,
        retry_reason: str = "",
    ) -> tuple[int, dict[str, Any], str]:
        emit_swarm_event(
            "winning_s6_card_authoring_started",
            actor=agent_id,
            card_position=position,
            hypothesis_id=str(brief.get("hypothesis_id", "")),
            equipment_name=str(brief.get("name", "")),
            status="running",
            attempt=attempt,
            provider_timeout_seconds=_s6_card_timeout_threshold(resume=resume_s6_only),
            provider_timeout_mode=(
                "hard" if _s6_hard_timeout_is_enabled() else "soft_observation"
            ),
            concurrent_modules=bool(parallel_portrait_modules),
            s6_concurrency_limit=s6_parallelism,
            process_isolation=(
                "new_process_per_turn" if parallel_portrait_modules else "card_scoped"
            ),
        )
        card_payload = (
            dynamic_card_payload(brief)
            if dynamic_s6_authoring
            else parallel_card_payload(brief)
            if parallel_portrait_modules
            else {
                "query": step_input.get("query", ""),
                "branch": step_input.get("branch", ""),
                "parallel_card_id": f"s6-card-{position}",
                "portfolio_position": position,
                "portfolio_card_count": len(briefs),
                "assigned_card": _minimal_s6_card_handoff(brief),
            }
        )
        targeted_feedback = _targeted_expert_feedback(
            shared.get("expert_review_feedback", []),
            "S6",
        )
        if targeted_feedback:
            card_payload["expert_review_feedback"] = _compact_prompt_value(
                targeted_feedback,
                max_string_chars=520,
                max_list_items=8,
            )
        authoring_input_fingerprint = (
            _dynamic_s6_input_fingerprint(dynamic_card_payload(brief))
            if dynamic_s6_authoring
            else ""
        )
        retry_suffix = (
            " "
            + str(prompt_contract["retry_suffix"]).format(
                reason=retry_reason[:240]
            )
            if retry_reason
            else ""
        )
        phase_prefix = (
            f"winning_s6_parallel_card_resume_{position:02d}"
            if resume_s6_only
            else f"winning_s6_parallel_card_{position:02d}"
        )
        card_phase = (
            f"{phase_prefix}_one_shot"
            if one_shot_authoring
            else phase_prefix
        )
        binding_id = str(
            brief.get("card_binding_id")
            or (card_payload.get("candidate_weapon") or {}).get("card_binding_id")
            or f"s6-card-{position}"
        ).strip()
        output_length = 0
        capability_image_draft = ""
        module_authoring_warnings: list[str] = []

        if parallel_portrait_modules:
            spine_schema = {
                key: value
                for key, value in active_card_direction_schema.items()
                if key
                not in {
                    "capability_portrait_modules",
                    "indicator_portrait",
                    "validation_plan",
                    "evidence_boundary",
                }
            }
            spine_instruction = _dynamic_s6_spine_instruction()
            if not dynamic_s6_authoring:
                # Keep the legacy/optimized schema, but use the same isolated
                # spine contract as dynamic-v2.  The five prose columns are
                # owned by sibling calls and must never be regenerated here.
                spine_instruction += " " + str(
                    prompt_contract["quality_parallel_spine_suffix"]
                )
            module_schema = {
                "module_key": prompt_contract["module_key"],
                "module_content": prompt_contract["module_content"],
                "card_binding_id": prompt_contract["binding_id"],
                "hypothesis_id": prompt_contract["hypothesis_id"],
                "capability_image_draft": prompt_contract["module_image_draft"],
            }
            labels = {key: label for key, label in CAPABILITY_PORTRAIT_MODULES}
            prompt_sections = {
                key: f"S6_{index}"
                for index, (key, _label) in enumerate(
                    CAPABILITY_PORTRAIT_MODULES,
                    start=1,
                )
            }
            module_exclusive_contract = {
                "overview": "只负责旧模式失效、关系变化、直接战果和新增任务空间；不展开技术清单或逐步流程。",
                "technology_implementation": "只负责装备本体、可选实现路径、推荐主路径、关键耦合和工程约束；不复述作战流程或效果总结。",
                "operational_process": "只负责行动主体、进入条件、关键动作、状态变化、授权/拒打和终止/续接；不重新论证技术路线。",
                "capability_effects": "只负责过去不能执行的任务、新增能力、可观察战果、指标边界和对手约束；不复述旧规则推演。",
                "winning_logic": "只负责旧规则、被逆转假设、新交换关系、对手新增代价和成立边界；不重复技术落装或流程步骤。",
            }
            module_completion_contract = {
                "overview": {
                    "objective": "让决策者看懂本装备为何在特定战场断点产生直接制胜价值。",
                    "must_deliver": ["敌方优势", "传统模式失效", "本装备介入", "直接战果", "新增任务空间"],
                    "avoid": ["技术清单", "逐步操作流程", "泛化指标"],
                },
                "technology_implementation": {
                    "objective": "说明本装备沿哪条工程路线才能形成核心作战能力。",
                    "must_deliver": ["可选路线比较", "推荐主路径", "1至2项主攻瓶颈", "落装位置", "工程取舍"],
                    "avoid": ["零部件清单", "无关技术趋势", "作战流程复述"],
                },
                "operational_process": {
                    "objective": "说明本装备如何在真实交战条件下进入、改变并交付一个作战窗口。",
                    "must_deliver": ["行动主体", "进入条件", "关键动作", "状态变化", "拒打或续接条件"],
                    "avoid": ["通用五步模板", "技术路线论证", "抽象效果口号"],
                },
                "capability_effects": {
                    "objective": "区分性能提升与本装备过去无法执行的新任务，并落到可观察战果。",
                    "must_deliver": ["新增任务", "直接战果", "后续影响", "敌方约束", "我方新作战空间"],
                    "avoid": ["重复旧规则", "泛化指标堆叠", "技术实现细节"],
                },
                "winning_logic": {
                    "objective": "解释本装备如何重写敌我交换关系并形成持续优势。",
                    "must_deliver": ["旧规则", "被逆转假设", "新交换关系", "经济反制", "敌方新增代价"],
                    "avoid": ["技术落装细节", "逐步流程复述", "颠覆性口号"],
                },
            }
            spine_context: dict[str, Any] = {}

            async def run_scoped_json(
                *,
                scope: str,
                instruction: str,
                schema: Mapping[str, Any],
                max_output_tokens: int,
                phase: str,
                extra_payload: Mapping[str, Any] | None = None,
            ) -> str:
                scoped_payload = {
                    **card_payload,
                    "parallel_card_id": f"{binding_id}:{scope}",
                    "portfolio_position": position,
                    "portfolio_card_count": len(briefs),
                }
                if extra_payload:
                    scoped_payload.update(dict(extra_payload))
                async with call_semaphore:
                    return await host._run_core_json(
                        agent_id,
                        instruction + retry_suffix,
                        scoped_payload,
                        schema,
                        max_output_tokens,
                        phase=phase,
                    )

            async def author_spine() -> dict[str, Any]:
                text = await run_scoped_json(
                    scope="spine",
                    instruction=spine_instruction,
                    schema={
                        "direction": spine_schema,
                        "capability_image_draft": prompt_contract[
                            "spine_image_draft"
                        ],
                    },
                    # The spine is structured routing context, not five-column
                    # prose. Keep its dynamic turn bounded so the column wave
                    # remains the only substantive authoring work.
                    max_output_tokens=7000 if not dynamic_s6_authoring else 3000,
                    phase=f"{phase_prefix}_spine",
                )
                nonlocal output_length, capability_image_draft, spine_context
                output_length += len(text)
                parsed_spine = _parse_json_object(text)
                draft = str(parsed_spine.get("capability_image_draft", "")).strip()
                if draft and not capability_image_draft:
                    capability_image_draft = draft
                direction_spine = _extract_s6_direction(parsed_spine)
                if not direction_spine:
                    raise S6QualityError(
                        f"S6并行第{position}张装备卡决策脊柱未返回结构化方向"
                    )
                stabilized_spine = _stabilize_s6_direction_structure(
                    direction_spine,
                    brief,
                )
                spine_context = {
                    key: stabilized_spine.get(key)
                    for key in (
                        "name",
                        "primary_equipment_identity",
                        "equipment_form",
                        "target_and_direct_effect",
                        "winning_mechanism",
                        "displaced_operational_mode",
                        "new_operational_mode",
                        "winning_relation_shift",
                    )
                    if stabilized_spine.get(key) not in (None, "", [], {})
                }
                return stabilized_spine

            def module_authoring_context(module_key: str) -> dict[str, Any]:
                field_map = {
                    "overview": (
                        "non_substitutable_difference",
                        "innovation_basis",
                        "displaced_operational_mode",
                        "new_operational_mode",
                    ),
                    "technology_implementation": (
                        "non_substitutable_difference",
                        "frontier_principle",
                        "technology_discontinuity",
                        "engineering_bottleneck",
                    ),
                    "operational_process": (
                        "unique_operational_role",
                        "launch_or_release_domain",
                        "new_operational_mode",
                    ),
                    "capability_effects": (
                        "target_and_direct_effect",
                        "new_operational_mode",
                        "winning_relation_shift",
                    ),
                    "winning_logic": (
                        "displaced_operational_mode",
                        "new_operational_mode",
                        "winning_relation_shift",
                    ),
                }
                context = {
                    "equipment_identity": {
                        key: card_payload.get("candidate_weapon", {}).get(key)
                        for key in (
                            "name",
                            "primary_equipment_identity",
                            "equipment_form",
                            "target_and_direct_effect",
                        )
                        if card_payload.get("candidate_weapon", {}).get(key)
                    },
                    "overview": card_payload.get("winning_logic_overview", ""),
                }
                for field in field_map.get(module_key, ()):
                    value = brief.get(field)
                    if value not in (None, "", [], {}):
                        context[field] = _compact_prompt_value(
                            value,
                            max_string_chars=520,
                            max_list_items=3,
                        )
                return context

            async def author_module(
                module_key: str,
                *,
                module_attempt: int = 1,
                module_retry_reason: str = "",
            ) -> tuple[str, str]:
                label = labels[module_key]
                retry_instruction = (
                    " "
                    + str(prompt_contract["module_retry"]).format(
                        label=label,
                        attempt=module_attempt,
                        reason=module_retry_reason[:220],
                    )
                    if module_attempt > 1
                    else ""
                )
                text = await run_scoped_json(
                    scope=(
                        module_key
                        if module_attempt == 1
                        else f"{module_key}:retry{module_attempt}"
                    ),
                    instruction=_dynamic_s6_module_instruction(
                        module_key,
                        module_guidance=str(
                            portrait_modules_schema.get(module_key, "")
                        ),
                    )
                    + retry_instruction,
                    schema=module_schema,
                    # A governed portrait column is a ~380-character prose
                    # artifact. Keep its independent turn bounded so one
                    # unusually deep model deliberation cannot hold the whole
                    # S6 wave hostage; the column gate still rejects missing
                    # or malformed content.
                    max_output_tokens=1800,
                    phase=f"{phase_prefix}_module_{module_key}",
                    extra_payload={
                        "portrait_module_key": module_key,
                        "portrait_module_label": label,
                        "portrait_module_prompt_section": prompt_sections[module_key],
                        "portrait_module_attempt": module_attempt,
                        "module_exclusive_contract": module_exclusive_contract,
                        "spine_context": spine_context,
                        "module_authoring_context": module_authoring_context(module_key),
                        "module_completion_contract": module_completion_contract[module_key],
                        "parallel_quality_check": (
                            "提交前静默检查：先确认任务目标、五项必答内容和栏目独占边界；"
                            "再检查约360至400字、完整句、装备专属事实、与兄弟栏无长句重复。"
                            "任何一项不满足都在本次调用内重写，不输出检查过程。"
                        ),
                    },
                )
                nonlocal output_length, capability_image_draft
                output_length += len(text)
                parsed_module = _parse_json_object(text)
                draft = str(parsed_module.get("capability_image_draft", "")).strip()
                if draft and not capability_image_draft:
                    capability_image_draft = draft
                content = _extract_s6_module_content(parsed_module, module_key)
                if not content:
                    raise S6QualityError(
                        f"S6并行第{position}张装备卡栏目{label}未返回正文"
                    )
                return module_key, content

            # Freeze the card-local decision spine first, then fan out the five
            # prose columns with that read-only context. Spines still run
            # concurrently across cards; this short per-card dependency keeps
            # independent columns aligned without serializing the portfolio.
            try:
                spine_result = await author_spine()
            except asyncio.CancelledError:
                raise
            except BaseException as exc:
                raise S6SpineAuthoringError(
                    f"S6并行第{position}张装备卡决策脊柱失败："
                    f"{type(exc).__name__}: {exc}"
                ) from (exc if isinstance(exc, Exception) else None)
            module_results = list(
                await asyncio.gather(
                    *[author_module(key) for key, _ in CAPABILITY_PORTRAIT_MODULES],
                    return_exceptions=True,
                )
            )
            # A single malformed column must not throw away four good
            # independent drafts (or force a mechanical frozen-card fallback).
            # Retry only failed modules in their own card-scoped isolation
            # lanes, preserving successful siblings byte-for-byte. A card
            # replay is reserved exclusively for a failed decision spine.
            failed_module_keys = [
                key
                for key, item in zip(
                    (key for key, _ in CAPABILITY_PORTRAIT_MODULES),
                    module_results,
                    strict=True,
                )
                if isinstance(item, BaseException)
            ]
            maximum_module_attempts = _s6_card_attempt_limit()
            for module_attempt in range(2, maximum_module_attempts + 1):
                if not failed_module_keys:
                    break
                previous_failures = {
                    key: item
                    for key, item in zip(
                        (key for key, _ in CAPABILITY_PORTRAIT_MODULES),
                        module_results,
                        strict=True,
                    )
                    if isinstance(item, BaseException)
                }
                rescue_results = await asyncio.gather(
                    *(
                        author_module(
                            key,
                            module_attempt=module_attempt,
                            module_retry_reason=(
                                f"{type(previous_failures[key]).__name__}: "
                                f"{previous_failures[key]}"
                            ),
                        )
                        for key in failed_module_keys
                    ),
                    return_exceptions=True,
                )
                rescued_by_key = {
                    key: item
                    for key, item in zip(
                        failed_module_keys,
                        rescue_results,
                        strict=True,
                    )
                    if not isinstance(item, BaseException)
                }
                for index, (key, item) in enumerate(
                    zip(
                        (key for key, _ in CAPABILITY_PORTRAIT_MODULES),
                        module_results,
                        strict=True,
                    )
                ):
                    if isinstance(item, BaseException) and key in rescued_by_key:
                        module_results[index] = rescued_by_key[key]
                failed_module_keys = [
                    key
                    for key, item in zip(
                        (key for key, _ in CAPABILITY_PORTRAIT_MODULES),
                        module_results,
                        strict=True,
                    )
                    if isinstance(item, BaseException)
                ]
            if failed_module_keys:
                # A missing independent column is a card-level authoring
                # failure.  Never synthesize a generic replacement from the
                # frozen handoff; publish only complete, independently authored
                # five-column cards.
                failed_key = failed_module_keys[0]
                failure = next(
                    item
                    for key, item in zip(
                        (key for key, _ in CAPABILITY_PORTRAIT_MODULES),
                        module_results,
                        strict=True,
                    )
                    if key == failed_key
                )
                raise S6QualityError(
                    f"S6并行第{position}张装备卡栏目{labels[failed_key]}独立成稿失败；"
                    "不使用回退模板，须重跑该卡的S6定向成稿"
                ) from (failure if isinstance(failure, Exception) else None)
            assert isinstance(spine_result, dict)
            direction = dict(spine_result)
            if dynamic_s6_authoring:
                # Dynamic S6 spine responses are intentionally compact and may
                # omit frozen semantic fields.  Reattach the authoritative S5
                # spine before publication so audits see the same baseline,
                # mechanism, novelty and evidence boundary that were judged
                # during selection.
                direction = _stabilize_s6_direction_structure(direction, brief)
            if not dynamic_s6_authoring:
                # A spine response is allowed to focus on fresh judgement. If
                # a compatible provider omits a low-level routing field, carry
                # over the already-frozen S5 value instead of manufacturing a
                # generic placeholder or degrading the card to a fallback.
                for field in (
                    "type",
                    "equipment_family",
                    "function",
                    "military_value",
                    "operational_mechanism",
                    "capability_outcome",
                    "winning_mechanism",
                    "problem_statement",
                    "baseline_system",
                    "capability_gap",
                    "indicator_portrait",
                    "query_relevance",
                    "direct_evidence_refs",
                    "evidence_boundary",
                    "validation_plan",
                    "capability_classification",
                ):
                    if direction.get(field) in (None, "", [], {}) and brief.get(
                        field
                    ) not in (None, "", [], {}):
                        direction[field] = brief[field]
            authored_modules = {}
            for row in module_results:
                assert isinstance(row, tuple)
                module_key, content = row
                authored_modules[str(module_key)] = coerce_portrait_module_prose(
                    content,
                    module_key=str(module_key),
                    allow_structured_salvage=False,
                )
        else:
            async with call_semaphore:
                card_text = await host._run_core_json(
                    agent_id,
                    _parallel_s6_card_instruction() + retry_suffix,
                    card_payload,
                    {
                        "direction": active_card_direction_schema,
                        "capability_image_draft": prompt_contract[
                            "spine_image_draft"
                        ],
                    },
                    12000,
                    phase=card_phase,
                )
            output_length = len(card_text)
            parsed = _parse_json_object(card_text)
            capability_image_draft = str(
                parsed.get("capability_image_draft", "")
            ).strip()
            direction = _extract_s6_direction(parsed)
            if not direction:
                raise S6QualityError(f"S6并行第{position}张装备卡未返回结构化方向")
            direction = _stabilize_s6_direction_structure(direction, brief)
            authored_modules = direction.get("capability_portrait_modules", {})
            if isinstance(authored_modules, Mapping):
                authored_modules = {
                    str(key): coerce_portrait_module_prose(
                        value,
                        module_key=str(key),
                        allow_structured_salvage=False,
                    )
                    for key, value in dict(authored_modules).items()
                }
            else:
                authored_modules = parse_capability_portrait_modules(
                    direction.get("capability_portrait", "")
                )

        initial_short_modules = _s6_short_portrait_modules(authored_modules)
        quality_warnings: list[str] = list(module_authoring_warnings)
        authoring_audit_notes: list[str] = []
        enhancement_applied = False
        # Keep the complete diagnostic list for audit.  Every diagnosed cause,
        # including shortness, cross-column repetition and low exclusivity,
        # enters one bounded repair wave; only the same root cause is collapsed
        # inside that wave.
        repair_issues = (
            _parallel_s6_semantic_quality_issues(authored_modules)
            if dynamic_s6_authoring
            else capability_portrait_repair_issues(authored_modules)
        )
        if repair_issues:
            first_pass_modules = dict(authored_modules)
            try:
                if parallel_portrait_modules or dynamic_s6_authoring:
                    labels = {key: label for key, label in CAPABILITY_PORTRAIT_MODULES}
                    prompt_sections = {
                        key: f"S6_{index}"
                        for index, (key, _) in enumerate(CAPABILITY_PORTRAIT_MODULES, 1)
                    }
                    repair_module_keys = _portrait_repair_keys(
                        first_pass_modules, repair_issues
                    )
                    emit_swarm_event(
                        "winning_s6_targeted_repair_planned",
                        actor=agent_id,
                        card_position=position,
                        hypothesis_id=str(brief.get("hypothesis_id", "")),
                        repair_module_keys=repair_module_keys,
                        preserved_module_keys=[
                            key for key, _ in CAPABILITY_PORTRAIT_MODULES
                            if key not in repair_module_keys
                        ],
                    )

                    async def repair_module(module_key: str) -> tuple[str, str]:
                        label = labels[module_key]
                        async with call_semaphore:
                            repair_call = host._run_core_json(
                                agent_id,
                                _dynamic_s6_module_repair_instruction(module_key),
                                {
                                    **card_payload,
                                    "parallel_card_id": (
                                        f"{binding_id}:{module_key}:repair"
                                    ),
                                    "portrait_module_key": module_key,
                                    "portrait_module_label": label,
                                    "portrait_module_prompt_section": (
                                        prompt_sections[module_key]
                                    ),
                                    "current_module_content": first_pass_modules.get(
                                        module_key, ""
                                    ),
                                    # Give a repaired column visibility into
                                    # its siblings.  Without this context a
                                    # model can only optimize local length and
                                    # will often copy the same decisive clause
                                    # into overview/effects/logic, producing a
                                    # cross-column duplication advisory.
                                    "existing_sibling_modules": {
                                        key: value
                                        for key, value in first_pass_modules.items()
                                        if key != module_key
                                    },
                                    "quality_issues": [
                                        item
                                        for item in repair_issues
                                        if module_key in item or label in item
                                    ][:4]
                                    or repair_issues[:4],
                                },
                                {
                                    "module_key": prompt_contract["module_key"],
                                    "module_content": prompt_contract[
                                        "module_repair_content"
                                    ],
                                    "card_binding_id": prompt_contract["binding_id"],
                                    "hypothesis_id": prompt_contract["hypothesis_id"],
                                },
                                1800,
                                phase=(
                                    f"winning_s6_parallel_card_repair_{position:02d}"
                                    f"_module_{module_key}"
                                ),
                            )
                            repair_text = await asyncio.wait_for(
                                repair_call,
                                timeout=_s6_repair_wall_timeout_seconds(),
                            )
                        nonlocal output_length
                        output_length += len(repair_text)
                        parsed_repair = _parse_json_object(repair_text)
                        for field, expected in (
                            ("module_key", module_key),
                            ("card_binding_id", binding_id),
                            ("hypothesis_id", str(brief.get("hypothesis_id", ""))),
                        ):
                            returned = parsed_repair.get(field)
                            if str(returned or "") != expected:
                                raise S6QualityError(f"S6 repair {field} mismatch")
                        return module_key, _extract_s6_module_content(parsed_repair, module_key)

                    repaired_rows = await asyncio.gather(
                        *(
                            repair_module(module_key)
                            for module_key in repair_module_keys
                        ),
                        return_exceptions=True,
                    )
                    repaired_modules = dict(first_pass_modules)
                    for row in repaired_rows:
                        if isinstance(row, asyncio.CancelledError):
                            raise row
                        if isinstance(row, Exception):
                            quality_warnings.append(
                                f"栏目修复失败，保留该栏首稿：{type(row).__name__}: {row}"
                            )
                            continue
                        module_key, content = row
                        if content:
                            repaired_modules[module_key] = content
                    candidate_modules = repaired_modules
                else:
                    async with call_semaphore:
                        repair_call = host._run_core_json(
                            agent_id,
                            _parallel_s6_quality_repair_instruction(repair_issues),
                            {
                                **card_payload,
                                "current_direction": dict(direction),
                                "quality_issues": repair_issues[:8],
                                "short_module_keys": initial_short_modules,
                            },
                            {
                                "direction": active_card_direction_schema,
                                "capability_image_draft": prompt_contract[
                                    "quality_spine_image_draft"
                                ],
                            },
                            12000,
                            phase=f"winning_s6_parallel_card_repair_{position:02d}",
                        )
                        repair_text = await asyncio.wait_for(
                            repair_call,
                            timeout=_s6_repair_wall_timeout_seconds(),
                        )
                    repaired = _extract_s6_direction(_parse_json_object(repair_text))
                    repaired = _stabilize_s6_direction_structure(repaired, brief)
                    repaired_modules = repaired.get("capability_portrait_modules", {})
                    if not isinstance(repaired_modules, Mapping):
                        repaired_modules = parse_capability_portrait_modules(
                            repaired.get("capability_portrait", "")
                        )
                    repaired_modules = dict(repaired_modules)
                    candidate_modules = _merge_s6_repaired_modules(
                        first_pass_modules,
                        repaired_modules,
                        initial_short_modules,
                    )
                required_module_keys = {key for key, _ in CAPABILITY_PORTRAIT_MODULES}
                if required_module_keys <= set(candidate_modules) and all(
                    str(candidate_modules.get(key, "")).strip()
                    for key in required_module_keys
                ):
                    repaired_portrait = assemble_capability_portrait_modules(
                        candidate_modules
                    )
                    repaired_issues = (
                        _parallel_s6_semantic_quality_issues(candidate_modules)
                        if dynamic_s6_authoring
                        else capability_portrait_repair_issues(candidate_modules)
                    )
                    identity_probe = {
                        **direction,
                        "capability_portrait_modules": candidate_modules,
                        "capability_portrait": repaired_portrait,
                    }
                    before_roots = _s6_repair_root_fingerprints(repair_issues)
                    after_roots = _s6_repair_root_fingerprints(repaired_issues)
                    repair_progress = not after_roots or len(after_roots) < len(before_roots)
                    if (
                        repair_progress
                        and _s6_repair_meets_length_contract(
                            candidate_modules,
                            initial_short_modules,
                        )
                        and not _s6_cross_card_identity_issues(identity_probe, briefs)
                    ):
                        direction["capability_portrait_modules"] = candidate_modules
                        direction["capability_portrait"] = repaired_portrait
                        authored_modules = candidate_modules
                        enhancement_applied = True
                    else:
                        direction["capability_portrait_modules"] = first_pass_modules
                        authored_modules = first_pass_modules
                        quality_warnings.append(
                            "二次增强未减少质量问题或出现身份风险，已回退首稿"
                        )
                else:
                    quality_warnings.append("二次增强返回栏目不完整，已回退首稿")
            except asyncio.CancelledError:
                raise
            except Exception as repair_error:
                quality_warnings.append(
                    "二次增强失败，已保留首稿："
                    f"{type(repair_error).__name__}: {repair_error}"
                )
            emit_swarm_event(
                "winning_s6_card_quality_enhancement_completed",
                actor=agent_id,
                card_position=position,
                hypothesis_id=str(brief.get("hypothesis_id", "")),
                equipment_name=str(brief.get("name", "")),
                status=(
                    "enhanced" if enhancement_applied else "completed_with_original_draft"
                ),
                enhancement_applied=enhancement_applied,
                module_character_counts=_s6_portrait_module_lengths(authored_modules),
                warnings=quality_warnings[:4],
            )
        source_name = str(brief.get("name", "")).strip()
        if source_name:
            direction["name"] = source_name
        protected_fields = (
            (
                "name",
                "card_binding_id",
                "hypothesis_id",
                "source_hypothesis_title",
                "primary_equipment_identity",
                "equipment_form",
                "unique_operational_role",
                "launch_or_release_domain",
                "target_and_direct_effect",
                "non_substitutable_difference",
                "baseline_system",
                "capability_gap",
                "direct_evidence_refs",
                "foresight_evidence_status",
                "evidence_boundary",
                "validation_plan",
                "query_relevance",
                "innovation_basis",
                "frontier_principle",
                "technology_discontinuity",
                "core_disruptive_difference",
                "displaced_operational_mode",
                "new_operational_mode",
                "winning_relation_shift",
                "system_interfaces",
                "direct_combat_equipment",
            )
            if dynamic_s6_authoring
            else (
                "name",
                "card_binding_id",
                "hypothesis_id",
                "source_hypothesis_title",
                "type",
                "primary_equipment_identity",
                "equipment_form",
                "equipment_family",
                "unique_operational_role",
                "launch_or_release_domain",
                "target_and_direct_effect",
                "non_substitutable_difference",
                "portfolio_identity_contract",
                "baseline_system",
                "capability_gap",
                "direct_evidence_refs",
                "foresight_evidence_status",
                "evidence_boundary",
                "validation_plan",
                "indicator_portrait",
                "query_relevance",
                "capability_classification",
                "equipment_semantic_assessment",
                "concise_winning_summary",
                "expert_score",
                "expert_assessment_id",
                "direct_combat_equipment",
            )
        )
        for protected_field in protected_fields:
            protected_value = brief.get(protected_field)
            if protected_value not in (None, "", []):
                direction[protected_field] = protected_value
        classification = direction.get("capability_classification", {})
        if isinstance(authored_modules, Mapping) and classification:
            authored_modules = dict(authored_modules)
            authored_modules["capability_classification"] = classification
        required_module_keys = {key for key, _ in CAPABILITY_PORTRAIT_MODULES}
        missing_module_keys = required_module_keys - set(authored_modules)
        if missing_module_keys:
            missing_labels = "、".join(
                label
                for key, label in CAPABILITY_PORTRAIT_MODULES
                if key in missing_module_keys
            )
            raise S6QualityError(
                f"S6并行第{position}张装备卡能力画像缺少完整五栏：{missing_labels}"
            )
        if any(
            not str(authored_modules.get(key, "")).strip()
            for key in required_module_keys
        ):
            empty_labels = "、".join(
                label
                for key, label in CAPABILITY_PORTRAIT_MODULES
                if not str(authored_modules.get(key, "")).strip()
            )
            raise S6QualityError(
                f"S6并行第{position}张装备卡能力画像存在空栏：{empty_labels}"
            )
        assembled_portrait = assemble_capability_portrait_modules(authored_modules)
        if not assembled_portrait:
            raise S6QualityError(
                f"S6并行第{position}张装备卡未完整返回五个能力画像模块"
            )
        direction["capability_portrait_modules"] = authored_modules
        direction["capability_portrait"] = assembled_portrait
        authored_boundary = str(direction.get("evidence_boundary", "") or "").strip()
        semantic_check = direction.get("semantic_consistency_check", {})
        if isinstance(semantic_check, Mapping):
            semantic_check = dict(semantic_check)
            if str(semantic_check.get("consistent", "")).strip().lower() == "true":
                semantic_check["consistent"] = True
        else:
            semantic_check = {}
        if authoring_input_fingerprint:
            direction["_s6_authoring_input_fingerprint"] = authoring_input_fingerprint
        identity_issues = _s6_cross_card_identity_issues(direction, briefs)
        if identity_issues:
            check = dict(semantic_check)
            check["consistent"] = False
            check["deterministic_identity_issues"] = identity_issues[:4]
            direction["semantic_consistency_check"] = check
            raise S6QualityError(
                f"S6并行第{position}张装备卡发生跨卡装备身份污染："
                + "；".join(identity_issues[:2])
            )
        if semantic_check.get("consistent") is not True:
            authoring_audit_notes.append(
                "模型未显式回传语义一致性通过；运行时已按冻结身份、卡片绑定、目标和画像归属完成确定性复核"
            )
            semantic_check["author_reported_consistent"] = semantic_check.get(
                "consistent"
            )
        semantic_check["consistent"] = True
        semantic_check.setdefault(
            "resolution_note",
            "运行时已核对冻结装备身份、卡片绑定、目标和画像归属，未发现跨卡污染。",
        )
        direction["semantic_consistency_check"] = semantic_check
        if authoring_audit_notes:
            direction["s6_authoring_audit_notes"] = authoring_audit_notes[:4]
        final_module_lengths = _s6_portrait_module_lengths(authored_modules)
        direction["portrait_module_character_counts"] = final_module_lengths
        direction["portrait_quality_contract_version"] = (
            S6_PORTRAIT_QUALITY_CONTRACT_VERSION
        )
        remaining_issues = (
            _parallel_s6_semantic_quality_issues(authored_modules)
            if dynamic_s6_authoring
            else capability_portrait_quality_issues(authored_modules)
        )
        for issue in remaining_issues:
            if issue not in quality_warnings:
                quality_warnings.append(issue)
        if quality_warnings:
            direction["s6_authoring_status"] = "authored_quality_limited"
            direction["s6_authoring_quality_warnings"] = quality_warnings[:8]
        else:
            direction["s6_authoring_status"] = "authored_semantically_consistent"
        if authored_boundary and not _evidence_boundary_is_public_semantic(
            authored_boundary
        ):
            direction.pop("evidence_boundary", None)
        emit_swarm_event(
            "winning_s6_card_authoring_completed",
            actor=agent_id,
            card_position=position,
            hypothesis_id=str(brief.get("hypothesis_id", "")),
            equipment_name=str(direction.get("name", brief.get("name", ""))),
            status="completed",
            attempt=attempt,
            output_length=output_length,
            quality_limited=bool(quality_warnings),
            quality_warnings=quality_warnings[:4],
            direction=_compact_s6_authored_card_event(direction),
            concurrent_modules=bool(parallel_portrait_modules),
            process_isolation=(
                "new_process_per_turn" if parallel_portrait_modules else "card_scoped"
            ),
        )
        outcome = (
            position,
            dict(direction),
            capability_image_draft,
        )
        host._s6_card_result_cache[card_cache_key(brief)] = (
            dict(outcome[1]),
            outcome[2],
        )
        return outcome

    async def author_card_with_retry(
        position: int,
        brief: Mapping[str, Any],
    ) -> tuple[int, dict[str, Any], str]:
        """Retry one failed card in isolation before marking it limited.

        S6 cards are independent transactions.  A transient provider error,
        malformed JSON response, or stochastic semantic mismatch on one
        card must not turn into a permanent portfolio loss after a single
        attempt.  Retry only the failed card so successful cards are never
        re-authored and the bounded S6 budget remains predictable.
        """

        maximum_attempts = _s6_card_attempt_limit()
        previous_error: Exception | None = None
        # Five portrait columns own their retries locally and successful
        # siblings are never replayed. Only the decision spine may trigger a
        # whole-card retry because every assembled field depends on it.
        recoverable = (S6SpineAuthoringError,)
        for attempt in range(1, maximum_attempts + 1):
            try:
                return await author_card(
                    position,
                    brief,
                    attempt=attempt,
                    retry_reason=(
                        f"{type(previous_error).__name__}: {previous_error}"
                        if previous_error is not None
                        else ""
                    ),
                )
            except recoverable as error:
                if previous_error is not None:
                    error.__cause__ = previous_error
                if attempt >= maximum_attempts:
                    raise
                previous_error = error
                emit_swarm_event(
                    "winning_s6_card_authoring_retry_started",
                    actor=agent_id,
                    card_position=position,
                    hypothesis_id=str(brief.get("hypothesis_id", "")),
                    equipment_name=str(brief.get("name", "")),
                    status="retrying",
                    attempt=attempt + 1,
                    failure_type=type(error).__name__,
                    retry_reason=str(error)[:320],
                )
                # Desynchronize simultaneous provider/gateway failures and
                # give the upstream account a real cooldown. A short fixed
                # delay was not enough when an entire S6 wave hit the same
                # transient capacity window.
                backoff_seconds = min(8.0, 0.45 * (2 ** (attempt - 1)))
                await asyncio.sleep(backoff_seconds + min(0.9, 0.12 * position))
        raise AssertionError("unreachable S6 card retry state")

    authored: list[tuple[int, dict[str, Any], str]] = []
    pending_cards: list[tuple[int, Mapping[str, Any]]] = []
    for position, brief in enumerate(briefs, start=1):
        cached = host._s6_card_result_cache.get(card_cache_key(brief))
        if cached is None or not _s6_card_is_reusable(cached[0]):
            if cached is not None:
                host._s6_card_result_cache.pop(card_cache_key(brief), None)
            pending_cards.append((position, brief))
            continue
        cached_direction, cached_draft = cached
        cached_direction = dict(cached_direction)
        cached_protected_fields = (
            (
                "name",
                "card_binding_id",
                "hypothesis_id",
                "source_hypothesis_title",
                "primary_equipment_identity",
                "equipment_form",
                "unique_operational_role",
                "launch_or_release_domain",
                "target_and_direct_effect",
                "non_substitutable_difference",
                "baseline_system",
                "capability_gap",
                "direct_evidence_refs",
                "foresight_evidence_status",
                "evidence_boundary",
                "validation_plan",
                "query_relevance",
                "innovation_basis",
                "frontier_principle",
                "technology_discontinuity",
                "core_disruptive_difference",
                "displaced_operational_mode",
                "new_operational_mode",
                "winning_relation_shift",
                "system_interfaces",
                "direct_combat_equipment",
            )
            if dynamic_s6_authoring
            else (
                "name",
                "card_binding_id",
                "hypothesis_id",
                "source_hypothesis_title",
                "type",
                "primary_equipment_identity",
                "equipment_form",
                "equipment_family",
                "unique_operational_role",
                "launch_or_release_domain",
                "target_and_direct_effect",
                "non_substitutable_difference",
                "portfolio_identity_contract",
                "baseline_system",
                "capability_gap",
                "direct_evidence_refs",
                "foresight_evidence_status",
                "evidence_boundary",
                "validation_plan",
                "indicator_portrait",
                "query_relevance",
                "capability_classification",
                "expert_score",
                "expert_assessment_id",
                "direct_combat_equipment",
            )
        )
        for protected_field in cached_protected_fields:
            protected_value = brief.get(protected_field)
            if protected_value not in (None, "", []):
                cached_direction[protected_field] = protected_value
        cached_boundary = str(
            cached_direction.get("evidence_boundary", "") or ""
        ).strip()
        if cached_boundary and not _evidence_boundary_is_public_semantic(
            cached_boundary
        ):
            cached_direction.pop("evidence_boundary", None)
        source_name = str(brief.get("name", "")).strip()
        if source_name:
            cached_direction["name"] = source_name
        if _s6_cross_card_identity_issues(cached_direction, briefs):
            host._s6_card_result_cache.pop(card_cache_key(brief), None)
            pending_cards.append((position, brief))
            continue
        authored.append((position, cached_direction, str(cached_draft)))
        emit_swarm_event(
            "winning_s6_card_authoring_reused",
            actor=agent_id,
            card_position=position,
            hypothesis_id=str(brief.get("hypothesis_id", "")),
            equipment_name=str(cached_direction.get("name", brief.get("name", ""))),
            status="completed",
            direction=_compact_s6_authored_card_event(cached_direction),
        )
    card_failures: list[str] = []
    if pending_cards:
        # ``call_semaphore`` bounds S6's own fan-out, while the runtime gate
        # protects the provider across workflow stages.  Configure the latter
        # for this isolated S6 wave as well; otherwise legacy profiles with a
        # 4/6-call run cap would make the five columns appear concurrent in
        # asyncio but execute serially at the provider boundary.
        call_gate = getattr(host, "_call_gate", None)
        configure_concurrency = getattr(call_gate, "configure_concurrency", None)
        previous_gate_limit: int | None = None
        if callable(configure_concurrency) and callable(
            getattr(call_gate, "snapshot", None)
        ):
            try:
                snapshot = call_gate.snapshot()
                previous_gate_limit = int(
                    snapshot.get("limit", snapshot.get("maximum", s6_parallelism))
                )
                configure_concurrency(s6_parallelism)
            except Exception:
                previous_gate_limit = None
        try:
            card_results = await asyncio.gather(
                *(
                    author_card_with_retry(position, brief)
                    for position, brief in pending_cards
                ),
                return_exceptions=True,
            )
        finally:
            if previous_gate_limit is not None:
                try:
                    configure_concurrency(previous_gate_limit)
                except Exception:
                    pass
        for (position, brief), card_result in zip(
            pending_cards,
            card_results,
            strict=True,
        ):
            if isinstance(card_result, BaseException):
                if isinstance(card_result, S6SpineAuthoringError):
                    # Parallel gateways often fail in correlated bursts. Once
                    # the whole wave has drained, make one final serial rescue
                    # for this card's failed spine. Column failures never enter
                    # this whole-card path.
                    emit_swarm_event(
                        "winning_s6_card_authoring_rescue_started",
                        actor=agent_id,
                        card_position=position,
                        hypothesis_id=str(brief.get("hypothesis_id", "")),
                        equipment_name=str(brief.get("name", "")),
                        failure_type=type(card_result).__name__,
                        status="recovering",
                        attempt=_s6_card_attempt_limit() + 1,
                        retry_reason=str(card_result)[:320],
                    )
                    try:
                        # Let a correlated provider outage drain before the
                        # single-card rescue; otherwise the rescue immediately
                        # repeats the same saturated request.
                        await asyncio.sleep(min(6.0, 1.0 + 0.4 * position))
                        rescued = await author_card(
                            position,
                            brief,
                            attempt=_s6_card_attempt_limit() + 1,
                            retry_reason=(
                                "决策脊柱并发波次已耗尽，转入错峰单卡恢复："
                                f"{type(card_result).__name__}: {card_result}"
                            ),
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception as rescue_error:
                        card_result = rescue_error
                    else:
                        authored.append(rescued)
                        emit_swarm_event(
                            "winning_s6_card_authoring_rescued",
                            actor=agent_id,
                            card_position=position,
                            hypothesis_id=str(brief.get("hypothesis_id", "")),
                            equipment_name=str(brief.get("name", "")),
                            status="completed",
                            attempt=_s6_card_attempt_limit() + 1,
                            direction=_compact_s6_authored_card_event(rescued[1]),
                        )
                        continue
                failure_summary = (
                    f"第{position}张{str(brief.get('name', '')).strip()}："
                    f"{type(card_result).__name__}: {card_result}"
                )
                card_failures.append(failure_summary)
                limited = limited_card_from_brief(
                    position,
                    brief,
                    card_result,
                )
                authored.append(limited)
                # Failed/limited cards are intentionally not cached. A
                # targeted resume must retry them while preserving every
                # successfully authored sibling card.
                host._s6_card_result_cache.pop(card_cache_key(brief), None)
                emit_swarm_event(
                    "winning_s6_card_authoring_limited",
                    actor=agent_id,
                    card_position=position,
                    hypothesis_id=str(brief.get("hypothesis_id", "")),
                    equipment_name=str(brief.get("name", "")),
                    failure_type=type(card_result).__name__,
                    status="limited",
                    attempt=_s6_card_attempt_limit() + 1,
                    direction=_compact_s6_authored_card_event(limited[1]),
                )
                continue
            authored.append(card_result)
    authored.sort(key=lambda item: item[0])
    if selected_portfolio:
        # The dynamic swarm has already calibrated every selected
        # candidate through the blind expert judge. Unlike the
        # model-authored planner path, this direct-portfolio path has
        # no planner call to populate top-level fields. Leaving
        # ``confidence`` at the schema default (an empty string)
        # therefore makes the S6 gate fail even after every card has
        # passed authoring and preflight repair. Project the existing
        # expert/card calibration; do not invent or raise a score just
        # to cross the release threshold.
        plan["confidence"] = _s6_portfolio_confidence(
            selected_portfolio,
            [item[1] for item in authored],
        )
    result = {
        key: plan.get(key, [] if isinstance(value, list) else "")
        for key, value in schema.items()
        if key not in {"concept_directions", "capability_image_drafts"}
    }
    result["concept_directions"] = [item[1] for item in authored]
    result["capability_image_drafts"] = [
        item[2]
        or str(item[1].get("capability_outcome", "")).strip()
        or str(item[1].get("name", "")).strip()
        for item in authored
    ]
    result["s6_parallel_authoring"] = {
        "cards_concurrent": len(pending_cards) > 1,
        "cards_wave": "asyncio.gather" if pending_cards else "checkpoint_reuse",
        "portrait_modules_concurrent": bool(parallel_portrait_modules),
        "card_concurrency_limit": s6_parallelism,
        "portrait_module_prompt_sections": {
            key: f"S6_{index}"
            for index, (key, _label) in enumerate(
                CAPABILITY_PORTRAIT_MODULES,
                start=1,
            )
        },
        "process_isolation": (
            "new_process_per_turn" if parallel_portrait_modules else "card_scoped"
        ),
    }
    if dynamic_s6_authoring:
        result["s6_parallel_authoring"]["authoring_mode"] = (
            "one_shot" if one_shot_authoring else "parallel_modules"
        )
    card_quality_warnings = [
        f"第{position}张{str(direction.get('name', '')).strip()}：{warning}"
        for position, direction, _ in authored
        if isinstance(direction, Mapping)
        for warning in direction.get("s6_authoring_quality_warnings", [])
        if str(warning).strip()
    ]
    if card_quality_warnings:
        result["s6_card_quality_warnings"] = list(dict.fromkeys(card_quality_warnings))[
            :16
        ]
    if card_failures:
        result["s6_card_authoring_limited"] = True
        result["s6_card_authoring_warnings"] = card_failures[:8]
        result["s6_card_authoring_limited_count"] = len(card_failures)
        result["s6_reference_weapons"] = [
            {
                **dict(item[1]),
                "selection_status": "selected_limited",
                "s6_eligible": True,
                "reference_reason": (
                    "S6独立成稿暂不可用；仅保留已入选装备及其S5证据作为定向重跑输入，"
                    "当前不提供能力画像正文。"
                ),
            }
            for item in authored
            if item[1].get("s6_authoring_status")
            == "limited_provider_failure"
        ]
        # The selected weapon remains traceable and resumable, but is not a
        # formal S6 capability portrait until independent authoring succeeds.
    return result
