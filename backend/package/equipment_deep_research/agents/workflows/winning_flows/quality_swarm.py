"""Quality-v1 breadth/challenge/convergence flow with private specialist execution."""
# ruff: noqa: F841

from __future__ import annotations

import asyncio
from collections.abc import (
    Callable,
    Mapping,
    Sequence,
)
from dataclasses import (
    replace,
)
from time import (
    monotonic,
)
from typing import (
    Any,
)

from equipment_deep_research.agents.dynamic_prompt_resources import (
    load_dynamic_winning_json,
    load_dynamic_winning_prompt,
)
from equipment_deep_research.agents.workflows.coordinator import (
    _compact_prompt_value,
    _is_harness_budget_error,
    _parse_json_object,
    _prioritize_winning_evidence_index,
    _query_combat_equipment_divergence_brief,
    _query_led_combat_equipment_theme_contract,
    _swarm_runtime_audit_contract,
    _swarm_session_ref,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _open_s3_exploration_brief,
    _open_s3_theme_instruction,
    _quality_cluster_candidate_instruction,
    _s3_s4_quality_first_instruction,
)
from equipment_deep_research.domain.models import (
    SpecialistTask,
    WinningHypothesis,
    to_plain,
)
from equipment_deep_research.domain.swarm_strategy import SwarmState
from equipment_deep_research.orchestration.winning_swarm import WinningSwarmController

from equipment_deep_research.contracts.runtime import SwarmRuntime


def _quality_swarm_prompt_resource(section: str) -> dict[str, Any]:
    """Load model-facing quality-swarm contracts from the reviewed Markdown."""

    value = load_dynamic_winning_json("common", section=section)
    if not isinstance(value, Mapping):
        raise ValueError(f"quality swarm prompt resource must be an object: {section}")
    return dict(value)


async def execute_quality_swarm(
    *,
    accumulated: dict[str, Any],
    cluster_hypotheses_with_independent_codex: Callable[..., Any],
    core_swarm_schedule: dict[str, Any],
    emit_swarm_event: Callable[..., Any],
    host: SwarmRuntime,
    packet_index: Sequence[Mapping[str, Any]],
    primary_branch: str,
    runs: list[dict[str, Any]],
    shared: Mapping[str, Any],
    state: SwarmState,
    swarm_controller: WinningSwarmController,
    valid_reference_ids: set[str],
    active_steps: Sequence[int],
    run_steps: Callable[..., Any],
) -> None:
    """Run breadth alongside S1/S2, then challenge, converge and finish S3-S6."""
    swarm_semaphore = asyncio.Semaphore(
        int(swarm_controller.policy.get("max_concurrency", 6))
    )
    quality_role_contract = _quality_swarm_prompt_resource(
        "quality_swarm.role_contract"
    )

    async def call_swarm_specialist(
        task: SpecialistTask,
        hypothesis: WinningHypothesis | None = None,
        *,
        batch: int = 0,
    ) -> dict[str, Any]:
        if task.allow_child_spawn:
            raise ValueError("dynamic specialists may not recruit child agents")
        runtime_agent_id = f"winning_swarm_{task.archetype}"
        scoped_provider = host._provider_for(
            runtime_agent_id,
            isolation_id=task.agent_instance_id,
            payload={
                "mission_node": "",
                "specialist_task": {"archetype": task.archetype},
            },
        )
        provider_snapshot = getattr(scoped_provider, "snapshot", lambda: {})()
        session_ref = _swarm_session_ref(task)
        runtime_contract = _swarm_runtime_audit_contract(
            task,
            provider_snapshot,
            runtime_agent_id=runtime_agent_id,
            session_ref=session_ref,
        )
        emit_swarm_event(
            "specialist_spawned",
            actor=task.agent_instance_id,
            **runtime_contract,
            batch=batch,
            status="recruiting",
        )
        async with swarm_semaphore:
            emit_swarm_event(
                "specialist_session_started",
                actor=task.agent_instance_id,
                **runtime_contract,
                batch=batch,
                status="running",
            )
            started_at = monotonic()
            common_input = {
                "run_id": shared.get("run_id", ""),
                "agent_instance_id": task.agent_instance_id,
                "mission_node": task.merge_target,
                "batch": batch,
                "topic": shared["topic"],
                "research_route": shared["research_route"],
                "execution_profile_id": shared["execution_profile_id"],
                "discovery_branch": primary_branch,
                "query_combat_equipment_divergence_brief": (
                    _open_s3_exploration_brief(
                        str(shared.get("topic", "")),
                        shared.get("structured_query_brief", {}),
                    )
                    if task.merge_target in {"S1", "S2", "S3"}
                    else _query_combat_equipment_divergence_brief(
                        str(shared.get("topic", "")),
                        structured_query_brief=shared.get("structured_query_brief", {}),
                    )
                ),
                "query_led_weapon_naming_style": {
                    "references": _query_led_combat_equipment_theme_contract()[
                        "naming_style_references"
                    ],
                    "rule": _query_led_combat_equipment_theme_contract()[
                        "naming_reference_rule"
                    ],
                    "format": quality_role_contract["naming_format"],
                },
                "specialist_task": to_plain(task),
                "role_contract": {
                    "mandate": task.purpose,
                    "decision_authority": (
                        quality_role_contract["wave1_decision_authority"]
                        if task.wave == 1
                        else quality_role_contract["wave2_decision_authority"]
                    ),
                    "handoff_contract": quality_role_contract["handoff_contract"],
                    "prohibitions": list(quality_role_contract["prohibitions"]),
                },
                "hypothesis": to_plain(hypothesis) if hypothesis else {},
                "packet_index": _compact_prompt_value(
                    packet_index,
                    max_string_chars=360,
                    max_list_items=10,
                ),
                "evidence_index": _compact_prompt_value(
                    _prioritize_winning_evidence_index(
                        shared.get("evidence_index", []),
                        archetype=task.archetype,
                    ),
                    max_string_chars=300,
                    max_list_items=24,
                ),
                "valid_reference_ids": sorted(valid_reference_ids),
                "isolation_contract": {
                    "raw_other_agent_sessions_visible": False,
                    "may_recruit_child_agent": False,
                    "declared_hypothesis_id": task.hypothesis_id,
                    "declared_merge_target": task.merge_target,
                },
            }
            if task.wave == 1:
                breadth_fields = _quality_swarm_prompt_resource(
                    "quality_swarm.breadth_schema"
                )
                schema: dict[str, Any] = {
                    "hypotheses": [dict(breadth_fields)],
                    "stop_reason": "string",
                }
                phase = "winning_swarm_breadth"
                wave_instruction = _quality_cluster_candidate_instruction()
                if task.merge_target in {"S3", "S4"}:
                    wave_instruction = (
                        _s3_s4_quality_first_instruction() + wave_instruction
                    )
            else:
                challenge_fields = _quality_swarm_prompt_resource(
                    "quality_swarm.challenge_schema"
                )
                schema = {
                    **dict(challenge_fields),
                }
                phase = (
                    "winning_swarm_targeted"
                    if task.wave == 2
                    else "winning_swarm_convergence"
                )
                wave_instruction = (
                    load_dynamic_winning_prompt(
                        "common", section="quality_swarm.targeted"
                    )
                    if task.wave == 2
                    else load_dynamic_winning_prompt(
                        "common", section="quality_swarm.convergence"
                    )
                )
            try:
                text = await host._run_core_json(
                    runtime_agent_id,
                    load_dynamic_winning_prompt(
                        "common", section="quality_swarm.system"
                    )
                    + wave_instruction
                    + _open_s3_theme_instruction(),
                    common_input,
                    schema,
                    task.max_output_tokens,
                    phase=phase,
                )
            except BaseException as exc:
                emit_swarm_event(
                    "specialist_session_completed",
                    actor=task.agent_instance_id,
                    **runtime_contract,
                    batch=batch,
                    status="failed",
                    elapsed_seconds=round(monotonic() - started_at, 3),
                    failure_type=type(exc).__name__,
                )
                raise
            emit_swarm_event(
                "specialist_session_completed",
                actor=task.agent_instance_id,
                **runtime_contract,
                batch=batch,
                status="completed",
                elapsed_seconds=round(monotonic() - started_at, 3),
            )
            result = _parse_json_object(text)
            if not result:
                raise ValueError(f"{task.agent_instance_id} returned invalid JSON")
            return result

    async def execute_swarm_tasks(
        tasks: Sequence[SpecialistTask],
    ) -> list[tuple[SpecialistTask, dict[str, Any]]]:
        ready, dependency_pruned = swarm_controller.ready_tasks(
            tasks,
            completed_task_ids=state.swarm_completed_task_ids,
            failed_task_ids=state.swarm_failed_task_ids,
        )
        for task in dependency_pruned:
            state.swarm_failed_task_ids.add(task.task_id)
            emit_swarm_event(
                "specialist_pruned",
                actor=task.agent_instance_id,
                task_id=task.task_id,
                agent_instance_id=task.agent_instance_id,
                archetype=task.archetype,
                display_name=task.display_name,
                role_purpose=task.purpose,
                trigger_residuals=list(task.trigger_residuals),
                wave=task.wave,
                hypothesis_id=task.hypothesis_id,
                merge_target=task.merge_target,
                runtime_profile_id=f"winning_swarm_{task.archetype}",
                allow_child_spawn=False,
                reason="recursive_spawn_or_failed_dependency",
                status="pruned",
            )
        if not ready:
            return []
        completed: list[tuple[SpecialistTask, dict[str, Any]]] = []
        for batch_index, batch in enumerate(
            swarm_controller.conflict_free_batches(ready),
            start=1,
        ):
            for task in batch:
                runtime_agent_id = f"winning_swarm_{task.archetype}"
                scoped_provider = host._provider_for(
                    runtime_agent_id,
                    isolation_id=task.agent_instance_id,
                )
                emit_swarm_event(
                    "specialist_recruitment_planned",
                    actor=task.agent_instance_id,
                    **_swarm_runtime_audit_contract(
                        task,
                        getattr(scoped_provider, "snapshot", lambda: {})(),
                        runtime_agent_id=runtime_agent_id,
                        session_ref=_swarm_session_ref(task),
                    ),
                    batch=batch_index,
                    status="planned",
                )
            outcomes = await asyncio.gather(
                *(
                    call_swarm_specialist(
                        task,
                        state.swarm_hypotheses.get(task.hypothesis_id),
                        batch=batch_index,
                    )
                    for task in batch
                ),
                return_exceptions=True,
            )
            for task, outcome in zip(batch, outcomes):
                if isinstance(outcome, BaseException):
                    state.swarm_failed_task_ids.add(task.task_id)
                    emit_swarm_event(
                        "specialist_pruned",
                        actor=task.agent_instance_id,
                        task_id=task.task_id,
                        wave=task.wave,
                        batch=batch_index,
                        hypothesis_id=task.hypothesis_id,
                        merge_target=task.merge_target,
                        reason=type(outcome).__name__,
                    )
                    continue
                state.swarm_completed_task_ids.add(task.task_id)
                completed.append((task, outcome))
                emit_swarm_event(
                    "specialist_completed",
                    actor=task.agent_instance_id,
                    task_id=task.task_id,
                    agent_instance_id=task.agent_instance_id,
                    archetype=task.archetype,
                    display_name=task.display_name,
                    role_purpose=task.purpose,
                    wave=task.wave,
                    batch=batch_index,
                    hypothesis_id=task.hypothesis_id,
                    merge_target=task.merge_target,
                    runtime_profile_id=f"winning_swarm_{task.archetype}",
                    status="completed",
                )
                runs.append(
                    {
                        "step": 0,
                        "agent_id": task.agent_instance_id,
                        "template_agent_id": "winning_dynamic_specialist",
                        "middle_cycle": 0,
                        "execution_mode": "dynamic",
                        "wave": task.wave,
                        "batch": batch_index,
                        "hypothesis_id": task.hypothesis_id,
                        "merge_target": task.merge_target,
                        "status": "completed",
                    }
                )
        return completed

    async def execute_swarm_breadth() -> None:

        state.swarm_plan = swarm_controller.plan_initial(
            topic=str(shared["topic"]),
            execution_profile_id=str(shared["execution_profile_id"]),
        )
        state.swarm_tasks.extend(state.swarm_plan.tasks)
        emit_swarm_event(
            "swarm_planned",
            plan=to_plain(state.swarm_plan),
            wave_count=len(state.swarm_plan.waves),
            task_count=len(state.swarm_plan.tasks),
            max_dynamic_instances=swarm_controller.policy["max_dynamic_instances"],
            max_concurrency=swarm_controller.policy["max_concurrency"],
            minimum_expected_gain=swarm_controller.policy["minimum_expected_gain"],
            core_schedule=core_swarm_schedule,
        )
        outcomes = await execute_swarm_tasks(state.swarm_plan.tasks)
        breadth_candidates: list[WinningHypothesis] = []
        breadth_outputs: list[dict[str, Any]] = []
        for task, result in outcomes:
            raw_hypotheses = result.get("hypotheses", [])
            rows = raw_hypotheses if isinstance(raw_hypotheses, list) else []
            if task.merge_target in {"S3", "S4"}:
                candidate_maximum = max(
                    1,
                    int(
                        swarm_controller.policy.get(
                            "s3_s4_candidate_maximum_per_session", 2
                        )
                    ),
                )
                candidate_pool_maximum = max(
                    candidate_maximum,
                    int(
                        swarm_controller.policy.get(
                            "s3_s4_candidate_pool_maximum_per_session",
                            candidate_maximum,
                        )
                    ),
                )
                if len(rows) > candidate_maximum:
                    emit_swarm_event(
                        "winning_s3_s4_candidate_output_bounded",
                        actor=task.agent_instance_id,
                        task_id=task.task_id,
                        mission_node=task.merge_target,
                        requested_candidate_count=len(rows),
                        retained_candidate_count=candidate_maximum,
                        candidate_maximum_per_session=candidate_maximum,
                        reason=(
                            "质量优先：每个S3/S4创作会话只保留最强候选，避免把同构变体带入评审"
                        ),
                    )
                rows = rows[:candidate_maximum]
            remaining_candidate_capacity = max(
                0,
                int(swarm_controller.policy.get("breadth_hypothesis_maximum", 20))
                - len(breadth_candidates),
            )
            rows = rows[:remaining_candidate_capacity]
            for ordinal, raw in enumerate(rows, start=1):
                if not isinstance(raw, Mapping):
                    continue
                hypothesis = swarm_controller.hypothesis_from_mapping(
                    raw,
                    task=task,
                    valid_evidence_ids=set(valid_reference_ids),
                    ordinal=ordinal,
                )
                gate = swarm_controller.evaluate_gate(
                    hypothesis,
                    stage="breadth",
                )
                state.swarm_gates.append(to_plain(gate))
                emit_swarm_event(
                    "swarm_gate_evaluated",
                    hypothesis_id=hypothesis.hypothesis_id,
                    stage="breadth",
                    passed=gate.passed,
                    score=gate.score,
                    residuals=gate.residuals,
                )
                if not gate.passed:
                    rejected = {
                        "hypothesis_id": hypothesis.hypothesis_id,
                        "stage": "breadth",
                        "reasons": gate.rejection_reasons or gate.residuals,
                    }
                    state.swarm_rejections.append(rejected)
                    emit_swarm_event("hypothesis_rejected", **rejected)
                    continue
                breadth_candidates.append(hypothesis)
                breadth_outputs.append(
                    {
                        "agent_instance_id": task.agent_instance_id,
                        "hypothesis_id": hypothesis.hypothesis_id,
                        "display_name": task.display_name,
                        "merge_target": task.merge_target,
                        "accepted": True,
                        "result": {
                            "findings": [
                                hypothesis.title,
                                *hypothesis.mechanism_chain[:2],
                            ],
                            "evidence_refs": hypothesis.evidence_ids,
                            "contribution_to_steps": [
                                {
                                    "step": int(task.merge_target[1:])
                                    if task.merge_target.startswith("S")
                                    else 6,
                                    "contribution": hypothesis.novelty_delta,
                                }
                            ],
                            "open_questions": hypothesis.residuals[:2],
                            "confidence": hypothesis.score,
                            "merge_target": task.merge_target,
                        },
                    }
                )
                emit_swarm_event(
                    "hypothesis_created",
                    actor=task.agent_instance_id,
                    task_id=task.task_id,
                    hypothesis_id=hypothesis.hypothesis_id,
                    title=hypothesis.title,
                    merge_target=task.merge_target,
                    score=hypothesis.score,
                )
        unique, merges = await cluster_hypotheses_with_independent_codex(
            breadth_candidates,
            scope_id="swarm-breadth",
        )
        kept_ids = {item.hypothesis_id for item in unique}
        state.swarm_merges.extend(merges)
        for row in merges:
            emit_swarm_event("hypothesis_merged", **row)
        state.swarm_hypotheses.update({item.hypothesis_id: item for item in unique})
        state.dynamic_outputs.extend(
            item for item in breadth_outputs if item["hypothesis_id"] in kept_ids
        )
        accumulated["dynamic_subagent_outputs"] = list(state.dynamic_outputs)

    async def execute_swarm_challenges() -> None:

        breadth_gates = [
            swarm_controller.evaluate_gate(item, stage="breadth")
            for item in state.swarm_hypotheses.values()
        ]
        tasks = swarm_controller.plan_targeted(
            list(state.swarm_hypotheses.values()),
            breadth_gates,
            topic=str(shared["topic"]),
            used_instances=len(state.swarm_tasks),
        )
        state.swarm_tasks.extend(tasks)
        outcomes = await execute_swarm_tasks(tasks)
        for task, result in outcomes:
            try:
                contribution = swarm_controller.contribution_from_mapping(
                    result,
                    task=task,
                    valid_evidence_ids=set(valid_reference_ids),
                )
            except ValueError as exc:
                state.swarm_failed_task_ids.add(task.task_id)
                emit_swarm_event(
                    "specialist_pruned",
                    actor=task.agent_instance_id,
                    task_id=task.task_id,
                    wave=task.wave,
                    hypothesis_id=task.hypothesis_id,
                    merge_target=task.merge_target,
                    reason=str(exc)[:300],
                )
                continue
            state.swarm_contributions.append(contribution)
            if not contribution.accepted:
                emit_swarm_event(
                    "specialist_pruned",
                    actor=task.agent_instance_id,
                    task_id=task.task_id,
                    wave=task.wave,
                    hypothesis_id=task.hypothesis_id,
                    merge_target=task.merge_target,
                    reason="incremental_quality_below_threshold",
                    incremental_quality=contribution.incremental_quality,
                )
                continue
            updated = swarm_controller.apply_contribution(
                state.swarm_hypotheses[task.hypothesis_id],
                contribution,
            )
            state.swarm_hypotheses[updated.hypothesis_id] = updated
            state.dynamic_outputs.append(
                {
                    "agent_instance_id": task.agent_instance_id,
                    "hypothesis_id": task.hypothesis_id,
                    "display_name": task.display_name,
                    "merge_target": task.merge_target,
                    "accepted": True,
                    "result": {
                        "findings": contribution.findings,
                        "evidence_refs": contribution.evidence_ids,
                        "contribution_to_steps": [
                            {
                                "step": int(task.merge_target[1:])
                                if task.merge_target.startswith("S")
                                else 6,
                                "contribution": finding,
                            }
                            for finding in contribution.findings[:3]
                        ],
                        "open_questions": updated.residuals[:2],
                        "confidence": updated.score,
                        "merge_target": task.merge_target,
                    },
                }
            )
            emit_swarm_event(
                "hypothesis_merged",
                actor=task.agent_instance_id,
                hypothesis_id=task.hypothesis_id,
                contribution_id=contribution.contribution_id,
                merge_target=task.merge_target,
                incremental_quality=contribution.incremental_quality,
            )
        accumulated["dynamic_subagent_outputs"] = list(state.dynamic_outputs)

    async def execute_swarm_convergence() -> None:

        preliminary, _, preliminary_gates = swarm_controller.select_finalists(
            list(state.swarm_hypotheses.values())
        )
        if not preliminary:
            preliminary = sorted(
                state.swarm_hypotheses.values(),
                key=lambda item: (-item.score, item.hypothesis_id),
            )[: int(swarm_controller.policy.get("finalist_maximum", 12))]
        state.swarm_gates.extend(to_plain(item) for item in preliminary_gates)
        tasks = swarm_controller.plan_convergence(
            preliminary,
            topic=str(shared["topic"]),
            used_instances=len(state.swarm_tasks),
        )
        state.swarm_tasks.extend(tasks)
        outcomes = await execute_swarm_tasks(tasks)
        for task, result in outcomes:
            try:
                contribution = swarm_controller.contribution_from_mapping(
                    result,
                    task=task,
                    valid_evidence_ids=set(valid_reference_ids),
                )
            except ValueError as exc:
                emit_swarm_event(
                    "specialist_pruned",
                    actor=task.agent_instance_id,
                    task_id=task.task_id,
                    wave=task.wave,
                    hypothesis_id=task.hypothesis_id,
                    merge_target=task.merge_target,
                    reason=str(exc)[:300],
                )
                continue
            state.swarm_contributions.append(contribution)
            if contribution.accepted:
                state.swarm_hypotheses[task.hypothesis_id] = (
                    swarm_controller.apply_contribution(
                        state.swarm_hypotheses[task.hypothesis_id],
                        contribution,
                    )
                )
                state.dynamic_outputs.append(
                    {
                        "agent_instance_id": task.agent_instance_id,
                        "hypothesis_id": task.hypothesis_id,
                        "display_name": task.display_name,
                        "merge_target": task.merge_target,
                        "accepted": True,
                        "result": {
                            "findings": contribution.findings,
                            "evidence_refs": contribution.evidence_ids,
                            "contribution_to_steps": [
                                {"step": 6, "contribution": finding}
                                for finding in contribution.findings[:3]
                            ],
                            "open_questions": state.swarm_hypotheses[
                                task.hypothesis_id
                            ].residuals[:2],
                            "confidence": state.swarm_hypotheses[
                                task.hypothesis_id
                            ].score,
                            "merge_target": task.merge_target,
                        },
                    }
                )
                emit_swarm_event(
                    "hypothesis_merged",
                    actor=task.agent_instance_id,
                    hypothesis_id=task.hypothesis_id,
                    contribution_id=contribution.contribution_id,
                    merge_target=task.merge_target,
                    incremental_quality=contribution.incremental_quality,
                )
        finalists, rejected, final_gates = swarm_controller.select_finalists(
            list(state.swarm_hypotheses.values())
        )
        state.swarm_gates.extend(to_plain(item) for item in final_gates)
        for gate in final_gates:
            emit_swarm_event(
                "swarm_gate_evaluated",
                hypothesis_id=gate.hypothesis_id,
                stage=gate.stage,
                passed=gate.passed,
                score=gate.score,
                residuals=gate.residuals,
                rejection_reasons=gate.rejection_reasons,
            )
        for hypothesis in rejected:
            gate = next(
                (
                    item
                    for item in final_gates
                    if item.hypothesis_id == hypothesis.hypothesis_id
                ),
                None,
            )
            rejection = {
                "hypothesis_id": hypothesis.hypothesis_id,
                "stage": "final",
                "reasons": (
                    list(gate.rejection_reasons)
                    if gate is not None and gate.rejection_reasons
                    else list(hypothesis.residuals)
                    or ["最终候选组合未选中，具体排序原因缺失"]
                ),
            }
            state.swarm_rejections.append(rejection)
            emit_swarm_event("hypothesis_rejected", **rejection)
        finalist_ids = {item.hypothesis_id for item in finalists}
        for hypothesis_id, hypothesis in list(state.swarm_hypotheses.items()):
            state.swarm_hypotheses[hypothesis_id] = replace(
                hypothesis,
                status=("finalist" if hypothesis_id in finalist_ids else "rejected"),
            )
        accumulated["dynamic_subagent_outputs"] = list(state.dynamic_outputs)
        accumulated["winning_swarm"] = {
            "policy": dict(swarm_controller.policy),
            "plan": to_plain(state.swarm_plan) if state.swarm_plan else {},
            "task_graph": [to_plain(item) for item in state.swarm_tasks],
            "waves": [
                {
                    "wave": wave,
                    "task_ids": [
                        item.task_id for item in state.swarm_tasks if item.wave == wave
                    ],
                }
                for wave in range(1, 4)
                if any(item.wave == wave for item in state.swarm_tasks)
            ],
            "hypotheses": [
                to_plain(item)
                for item in sorted(
                    state.swarm_hypotheses.values(),
                    key=lambda row: (-row.score, row.hypothesis_id),
                )
            ],
            "finalists": [to_plain(item) for item in finalists],
            "contributions": [to_plain(item) for item in state.swarm_contributions],
            "gates": list(state.swarm_gates),
            "merges": list(state.swarm_merges),
            "rejections": list(state.swarm_rejections),
            "promotion_candidates": [],
            "core_schedule": dict(core_swarm_schedule),
            "budget": {
                "planned_instances": len(state.swarm_tasks),
                "completed_instances": len(state.swarm_completed_task_ids),
                "failed_or_pruned_instances": len(state.swarm_failed_task_ids),
                "maximum_instances": swarm_controller.policy["max_dynamic_instances"],
                "maximum_concurrency": swarm_controller.policy["max_concurrency"],
                "maximum_waves": swarm_controller.policy["max_waves"],
            },
            "stop_reason": (
                "quality_gain_below_threshold"
                if any(not item.accepted for item in state.swarm_contributions)
                else "bounded_three_wave_complete"
            ),
        }
        emit_swarm_event(
            "swarm_gate_evaluated",
            stage="portfolio",
            passed=bool(finalists),
            finalist_count=len(finalists),
            rejected_count=len(rejected),
            swarm_summary=accumulated["winning_swarm"],
        )

    early_steps = [index for index in active_steps if index in {1, 2}]
    first_wave = [execute_swarm_breadth()]
    if early_steps:
        first_wave.append(run_steps(early_steps, middle_cycle=1))
    results = await asyncio.gather(*first_wave, return_exceptions=True)
    for outcome in results:
        if isinstance(outcome, BaseException) and not (
            isinstance(outcome, (RuntimeError, TimeoutError, ValueError))
            and _is_harness_budget_error(outcome)
        ):
            raise outcome
    await execute_swarm_challenges()
    await execute_swarm_convergence()
    remaining = [index for index in active_steps if index not in {1, 2}]
    if remaining:
        await run_steps(remaining, middle_cycle=1)
