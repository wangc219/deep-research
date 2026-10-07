"""Independent semantic clustering service used by both swarm modes."""

from __future__ import annotations

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
    load_dynamic_winning_prompt,
)
from equipment_deep_research.agents.workflows.coordinator import (
    _parse_json_object,
)
from equipment_deep_research.agents.workflows.winning_flows.helpers import (
    _bounded_semantic_review_window,
)
from equipment_deep_research.domain.models import (
    SpecialistTask,
    WinningHypothesis,
    to_plain,
)
from equipment_deep_research.orchestration.winning_swarm import WinningSwarmController

from equipment_deep_research.contracts.runtime import SwarmRuntime


async def cluster_hypotheses_with_independent_codex(
    candidates: Sequence[WinningHypothesis],
    *,
    emit_swarm_event: Callable[..., Any],
    host: SwarmRuntime,
    shared: Mapping[str, Any],
    swarm_controller: WinningSwarmController,
    scope_id: str,
    changed_hypothesis_ids: set[str] | None = None,
) -> tuple[list[WinningHypothesis], list[dict[str, str]]]:
    """Use an isolated Codex session for five-axis semantic clustering."""

    exact_unique, exact_merges = swarm_controller.deduplicate_hypotheses(candidates)
    if len(exact_unique) < 2 or not host.supports_agent_runtime:
        return exact_unique, exact_merges
    # Semantic comparison is quadratic in the number of candidates and
    # the isolated Codex CLI has a finite request window.  Keep the full
    # ledger intact, but bound the review slice so large incremental
    # ledgers never create a request that predictably times out.  The S5
    # portfolio reviewer still sees the complete compact ledger later.
    semantic_review_candidates = 14
    semantic_review_pairs = 91  # C(14, 2)
    review_unique, pair_ids = _bounded_semantic_review_window(
        exact_unique,
        changed_hypothesis_ids=changed_hypothesis_ids,
        maximum_candidates=semantic_review_candidates,
    )
    instance_id = (
        "winning-semantic-clusterer-"
        + sha256(f"{shared.get('run_id', '')}:{scope_id}".encode()).hexdigest()[:16]
    )
    task = SpecialistTask(
        task_id=instance_id,
        agent_instance_id=instance_id,
        archetype="independent_portfolio_reviewer",
        display_name="候选五轴语义聚类",
        wave=0,
        purpose=load_dynamic_winning_prompt(
            "common", section="semantic_clustering.task_purpose"
        ),
        merge_target="S5",
        max_output_tokens=min(
            1800,
            700 + (len(exact_unique) * (len(exact_unique) - 1) // 2) * 160,
        ),
        allow_child_spawn=False,
    )
    candidate_rows = [
        {
            "hypothesis_id": item.hypothesis_id,
            "title": item.title,
            "target": item.project_function,
            "task_chain_breakpoint": item.problem_statement
            if hasattr(item, "problem_statement")
            else item.project_function,
            "winning_angle_id": item.winning_angle_id,
            "original_paradigm": item.original_paradigm,
            "disruptive_shift": item.disruptive_shift,
            "independence_thesis": item.independence_thesis,
            "changed_confrontation_variable": item.changed_confrontation_variable,
            "core_mechanism": list(item.mechanism_chain),
            "direct_military_results": list(item.direct_military_effects),
        }
        for item in review_unique
    ]
    if not pair_ids:
        return exact_unique, exact_merges
    if len(pair_ids) > semantic_review_pairs:
        emit_swarm_event(
            "winning_semantic_clustering_bounded",
            actor=instance_id,
            candidate_count=len(exact_unique),
            review_candidate_count=len(review_unique),
            pair_count=len(pair_ids),
            max_pair_count=semantic_review_pairs,
            scope_id=scope_id,
            reason="bounded_semantic_review_window",
        )
        return exact_unique, exact_merges
    output_schema_resource = load_dynamic_winning_json(
        "common", section="semantic_clustering.output_schema"
    )
    if not isinstance(output_schema_resource, Mapping):
        raise ValueError("semantic clustering output schema must be an object")
    # The schema descriptions are model-visible contract text. Keep them in
    # common.md with the rest of the dynamic prompt resources, and copy the
    # outer mapping so a provider adapter cannot mutate the cached resource.
    output_schema = dict(output_schema_resource)
    emit_swarm_event(
        "winning_semantic_clustering_started",
        actor=instance_id,
        candidate_count=len(candidate_rows),
        pair_count=len(pair_ids),
        scope_id=scope_id,
    )
    try:
        text = await host._run_core_json(
            "winning_swarm_independent_portfolio_reviewer",
            load_dynamic_winning_prompt(
                "common", section="semantic_clustering.system"
            ),
            {
                "run_id": shared.get("run_id", ""),
                "agent_instance_id": instance_id,
                "execution_profile_id": shared.get("execution_profile_id", ""),
                "specialist_task": to_plain(task),
                "query": shared.get("topic", ""),
                "structured_query_brief": shared.get("structured_query_brief", {}),
                "candidates": candidate_rows,
                "pair_ids": pair_ids,
            },
            output_schema,
            task.max_output_tokens,
            phase="winning_semantic_pair_clustering",
        )
        result = _parse_json_object(text)
        comparisons = result.get("pairwise_comparisons", [])
        if not isinstance(comparisons, list):
            raise ValueError("semantic clusterer returned invalid comparisons")
        valid_pairs = {tuple(item) for item in pair_ids}
        duplicate_pairs: set[frozenset[str]] = set()
        for row in comparisons:
            if not isinstance(row, Mapping):
                continue
            left = str(row.get("left_hypothesis_id", ""))
            right = str(row.get("right_hypothesis_id", ""))
            pair = (left, right)
            reverse_pair = (right, left)
            if pair not in valid_pairs and reverse_pair not in valid_pairs:
                continue
            relationship = str(row.get("relationship", "")).lower()
            try:
                confidence = float(row.get("confidence", 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
            axis_equivalence = row.get("axis_equivalence", {})
            all_axes_equivalent = bool(
                isinstance(axis_equivalence, Mapping)
                and all(
                    axis_equivalence.get(axis) is True
                    for axis in (
                        "target",
                        "task_chain_breakpoint",
                        "changed_variable",
                        "core_mechanism",
                        "direct_result",
                    )
                )
            )
            raw_difference_axes = row.get("material_difference_axes", [])
            no_material_differences = isinstance(raw_difference_axes, list) and not any(
                str(item).strip() for item in raw_difference_axes
            )
            if (
                relationship in {"same_thesis", "non_independent_variant"}
                and confidence >= 0.70
                and all_axes_equivalent
                and no_material_differences
            ):
                duplicate_pairs.add(frozenset((left, right)))
        # Complete-link grouping prevents transitive over-merging:
        # A≈B and B≈C never collapses A with C unless the independent
        # Codex also explicitly judged A≈C.
        groups: list[list[WinningHypothesis]] = []
        for item in sorted(
            exact_unique,
            key=lambda candidate: (
                -candidate.score,
                -len(candidate.evidence_ids),
                candidate.hypothesis_id,
            ),
        ):
            compatible_group = next(
                (
                    group
                    for group in groups
                    if all(
                        frozenset((item.hypothesis_id, member.hypothesis_id))
                        in duplicate_pairs
                        for member in group
                    )
                ),
                None,
            )
            if compatible_group is None:
                groups.append([item])
            else:
                compatible_group.append(item)
        kept: list[WinningHypothesis] = []
        merges = list(exact_merges)
        for group in groups:
            ordered = sorted(
                group,
                key=lambda item: (
                    -item.score,
                    -len(item.evidence_ids),
                    item.hypothesis_id,
                ),
            )
            representative = ordered[0]
            kept.append(representative)
            for duplicate in ordered[1:]:
                merges.append(
                    {
                        "source_hypothesis_id": duplicate.hypothesis_id,
                        "target_hypothesis_id": representative.hypothesis_id,
                        "reason": "independent_codex_five_axis_semantic_cluster",
                    }
                )
        emit_swarm_event(
            "winning_semantic_clustering_completed",
            actor=instance_id,
            candidate_count=len(exact_unique),
            retained_count=len(kept),
            merged_count=len(merges),
            scope_id=scope_id,
        )
        return kept, merges
    except BaseException as exc:
        emit_swarm_event(
            "winning_semantic_clustering_failed",
            actor=instance_id,
            failure_type=type(exc).__name__,
            error_message=str(exc)[:500],
            fallback="exact_five_axis_identity_only",
            scope_id=scope_id,
        )
        return exact_unique, exact_merges
