"""Behavior and dependency boundaries of the winning execution modes."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from equipment_deep_research.agents.dynamic_prompt_resources import (
    load_dynamic_winning_json,
    load_dynamic_winning_prompt,
)
from equipment_deep_research.agents.workflows.winning_flows import (
    helpers,
    optimized,
    standard,
)
from equipment_deep_research.agents.workflows.winning_flows.state import SwarmState
from equipment_deep_research.orchestration.winning_mode import resolve_winning_mode


@pytest.mark.parametrize(
    "profile,flow,quality",
    [
        ("legacy_v1", "standard", False),
        ("optimized_v2", "standard", True),
        ("swarm_quality_v1", "quality_swarm", True),
        ("winning_swarm_dynamic_v2", "dynamic_swarm", True),
    ],
)
def test_profile_selection_keeps_discovery_separate_from_resume(profile, flow, quality):
    mode = resolve_winning_mode(profile)
    assert mode.initial_flow(swarm_enabled=True, resuming=False) == flow
    assert mode.uses_quality_contract is quality
    assert mode.initial_flow(swarm_enabled=True, resuming=True) == "standard"
    assert mode.initial_flow(swarm_enabled=False, resuming=False) == "standard"
    # Resume suppresses discovery, not the dynamic S6 input/authoring contract.
    assert mode.dynamic_swarm is (profile == "winning_swarm_dynamic_v2")


def test_s6_concurrency_uses_wide_independent_lane_with_hard_safety_cap(
    monkeypatch,
):
    monkeypatch.setenv("EQUIPMENT_DR_S6_CODEX_CONCURRENCY", "64")
    assert helpers._bounded_s6_parallelism({"s6_codex_concurrency": 64}) == 32

    monkeypatch.setenv("EQUIPMENT_DR_S6_CODEX_CONCURRENCY", "24")
    assert helpers._bounded_s6_parallelism({"s6_codex_concurrency": 32}) == 24


def test_s6_decision_spine_excludes_indicator_and_boundary_obligations():
    spine = helpers._dynamic_s6_spine_instruction()
    assert "必须独立形成" in spine
    assert "indicator_portrait" not in spine
    assert "证据边界" not in spine
    assert "适用边界" not in spine


@pytest.mark.parametrize("pipeline", ["0", "1"])
def test_standard_steps_consume_committed_dependencies_and_resume_only_selected(
    monkeypatch, pipeline
):
    monkeypatch.setenv("EQUIPMENT_DR_USE_DYNAMIC_WINNING_SCHEDULER", pipeline)
    accumulated = {"1": "reused", "2": "reused"}
    seen = []

    async def run_step(index, *, prior_step_outputs, **kwargs):
        seen.append((index, dict(prior_step_outputs)))
        assert str(index - 1) in prior_step_outputs
        return {"run": {"step": index}}

    def commit(outcome):
        accumulated[str(outcome["run"]["step"])] = "committed"

    asyncio.run(
        standard.run_standard_steps(
            [3, 4],
            middle_cycle=2,
            middle_feedback=["repair"],
            accumulated=accumulated,
            commit_step=commit,
            run_step=run_step,
            step_dependency_map={3: (1, 2), 4: (3,)},
            plan_step_waves=lambda selected: [(3,), (4,)],
        )
    )
    assert [index for index, _ in seen] == [3, 4]
    assert seen[1][1]["3"] == "committed"


def test_pipeline_releases_downstream_without_waiting_for_unrelated_step(monkeypatch):
    monkeypatch.setenv("EQUIPMENT_DR_USE_DYNAMIC_WINNING_SCHEDULER", "1")

    async def scenario():
        downstream_started = asyncio.Event()
        accumulated = {}

        async def run_step(index, **kwargs):
            if index == 2:
                await asyncio.wait_for(downstream_started.wait(), timeout=1)
            if index == 3:
                assert "1" in kwargs["prior_step_outputs"]
                assert "2" not in kwargs["prior_step_outputs"]
                downstream_started.set()
            return {"run": {"step": index}}

        await standard.run_standard_steps(
            [1, 2, 3],
            middle_cycle=1,
            middle_feedback=None,
            accumulated=accumulated,
            commit_step=lambda o: accumulated.update({str(o["run"]["step"]): True}),
            run_step=run_step,
            step_dependency_map={1: (), 2: (), 3: (1,)},
            plan_step_waves=lambda _: pytest.fail("pipeline must not use fixed waves"),
        )
        assert set(accumulated) == {"1", "2", "3"}

    asyncio.run(scenario())


def test_pipeline_failure_cancels_siblings_before_returning(monkeypatch):
    monkeypatch.setenv("EQUIPMENT_DR_USE_DYNAMIC_WINNING_SCHEDULER", "1")

    async def scenario():
        sibling_started = asyncio.Event()
        sibling_cancelled = asyncio.Event()

        async def run_step(index, **kwargs):
            if index == 1:
                await sibling_started.wait()
                raise ValueError("provider failure")
            try:
                sibling_started.set()
                await asyncio.Event().wait()
            finally:
                sibling_cancelled.set()

        with pytest.raises(ValueError, match="provider failure"):
            await standard.run_standard_steps(
                [1, 2],
                middle_cycle=1,
                middle_feedback=None,
                accumulated={},
                commit_step=lambda _: pytest.fail("failed calls cannot commit"),
                run_step=run_step,
                step_dependency_map={1: (), 2: ()},
                plan_step_waves=lambda _: [],
            )
        assert sibling_cancelled.is_set()

    asyncio.run(scenario())


def test_optimized_cohort_commits_each_logical_result_before_downstream():
    calls = []
    accumulated = {}

    async def cohort(indices, **kwargs):
        calls.append(tuple(indices))
        return [{"run": {"step": i}} for i in reversed(indices)]

    async def single(index, **kwargs):
        assert kwargs["prior_step_outputs"] == {"1": True, "2": True}
        calls.append(index)
        return {"run": {"step": index}}

    asyncio.run(
        optimized.run_optimized_steps(
            [1, 2, 3],
            middle_cycle=1,
            middle_feedback=None,
            accumulated=accumulated,
            commit_step=lambda o: accumulated.update({str(o["run"]["step"]): True}),
            run_step=single,
            step_dependency_map={1: (), 2: (), 3: (1, 2)},
            host=SimpleNamespace(),
            loop_trace=[],
            physical_cohorts=[(1, 2)],
            primary_branch="B",
            run_physical_cohort=cohort,
            run_tactic_validation_wave=lambda: pytest.fail(
                "B does not run A validation"
            ),
        )
    )
    assert calls == [(1, 2), 3]
    assert list(accumulated) == ["1", "2", "3"]


def test_swarm_state_is_per_run():
    first, second = SwarmState(), SwarmState()
    first.dynamic_outputs.append({"run": "first"})
    first.swarm_completed_task_ids.add("task-1")
    assert not second.dynamic_outputs
    assert not second.swarm_completed_task_ids


def test_dynamic_prompt_contracts_are_distinct_and_covered():
    assert "S1重点" in load_dynamic_winning_prompt("S1")
    assert "S2重点" in load_dynamic_winning_prompt("S2")
    assert "S1重点" not in load_dynamic_winning_prompt("S2")
    s3_prompt = load_dynamic_winning_prompt("S3")
    s4_prompt = load_dynamic_winning_prompt("S4")
    assert s3_prompt != s4_prompt
    assert "coverage_steer" in s3_prompt
    assert "coverage_steer" in s4_prompt
    for prompt in (s3_prompt, s4_prompt):
        assert "至少三种不同装备架构" in prompt
        assert "面向未来战争需要的多样性来自不同制胜断点" in prompt
        assert "random_naming_style_assignment" in prompt
        assert "8—12个汉字" in prompt
        assert "只输出严格JSON" in prompt
    assert "S4必须独立重构路线" not in s3_prompt
    assert "S4必须独立重构路线" in s4_prompt
    assert "只输出system规定的严格JSON结构" in load_dynamic_winning_prompt(
        "S3", section="creative"
    )
    assert "只输出system规定的严格JSON结构" in load_dynamic_winning_prompt(
        "S4", section="creative"
    )
    # The legacy helper fragments remain a compatibility surface for the
    # quality-swarm path; the Markdown resources are the dynamic runtime
    # authority and need not be byte-for-byte copies of those fragments.
    helper_contract = (
        helpers._s3_s4_quality_first_instruction()
        + helpers._creative_s3_candidate_instruction()
    )
    assert "宁缺毋滥" in helper_contract
    assert "从Query的核心战场矛盾自由创造" in helper_contract
    s5_prompt = load_dynamic_winning_prompt("S5")
    assert "S5独立组合评审" in s5_prompt
    assert "完整候选池" in s5_prompt
    assert "不得只在单一创作者切片内打分" in s5_prompt
    assert "coverage_steer" in load_dynamic_winning_prompt("S3")
    assert "{axis_label}" in load_dynamic_winning_prompt(
        "common", section="coverage_steer.instruction"
    )
    s6_prompt = load_dynamic_winning_prompt("S6")
    assert "每栏都以约400个有效中文字为中心" in s6_prompt
    assert "复杂因果尚未闭合时可适当略多" in s6_prompt
    assert "禁止按字符硬切" in s6_prompt
    assert "不能用总字数或平均数抵消短栏" in s6_prompt
    assert "五栏合计通常约2000至2250字" in s6_prompt
    technology_prompt = load_dynamic_winning_prompt("S6", section="S6_2")
    for required in (
        "可选实现途径",
        "推荐主路径",
        "核心攻关顺序",
        "联网检索能力",
        "新质概念武器研发",
    ):
        assert required in technology_prompt
    with pytest.raises(ValueError, match="unknown dynamic winning stage"):
        load_dynamic_winning_prompt("../../unrelated")
    with pytest.raises(ValueError, match="missing dynamic prompt section"):
        load_dynamic_winning_prompt("S1", section="missing")


def test_s6_portrait_sections_are_loaded_from_independent_companion_files():
    prompt_root = (
        Path(__file__).parents[3]
        / "src/equipment_deep_research/agents/prompts/dynamic_winning"
    )
    base = (prompt_root / "S6.md").read_text(encoding="utf-8")
    for index in range(1, 6):
        section = f"S6_{index}"
        companion = prompt_root / f"{section}.md"
        assert companion.is_file()
        companion_text = companion.read_text(encoding="utf-8")
        assert f"<!-- prompt: {section} -->" in companion_text
        assert f"<!-- prompt: {section} -->" not in base
        assert load_dynamic_winning_prompt("S6", section=section).strip()


def test_semantic_clustering_schema_is_loaded_from_reviewed_markdown():
    schema = load_dynamic_winning_json(
        "common", section="semantic_clustering.output_schema"
    )

    assert isinstance(schema, dict)
    assert set(schema) == {"pairwise_comparisons", "stop_reason"}
    comparison = schema["pairwise_comparisons"][0]
    assert comparison["relationship"] == (
        "same_thesis|non_independent_variant|independent"
    )
    assert comparison["axis_equivalence"]["core_mechanism"] == "boolean"

    # Keep model-visible schema prose out of the execution module.  The
    # implementation still references the field name while reading results,
    # but it must not carry the contract's example values or descriptions.
    from equipment_deep_research.agents.workflows.winning_flows import clustering

    source = Path(clustering.__file__).read_text(encoding="utf-8")
    assert '"exact id"' not in source
    assert '"same_thesis|non_independent_variant|independent"' not in source


def test_flow_modules_do_not_import_their_coordinator_or_inject_globals():
    package = Path(standard.__file__).parent
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert (
                    node.module != "equipment_deep_research.agents.workflows.winning"
                ), path
                assert all(alias.name != "*" for alias in node.names), path
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"globals", "exec"}, path


def test_dynamic_mission_graph_uses_markdown_at_provider_boundary(monkeypatch):
    import json

    from equipment_deep_research.agents.workflows.winning_flows.dynamic_swarm import (
        execute_dynamic_mission_graph,
    )
    from equipment_deep_research.orchestration.winning_swarm import (
        WinningSwarmController,
    )

    monkeypatch.setenv("EQUIPMENT_DR_S3_S4_CREATIVE_PASSES", "1")

    class Host:
        supports_agent_runtime = True

        def __init__(self):
            self.calls = []
            self.count = 0

        def _provider_for(self, *a, **kw):
            return SimpleNamespace(snapshot=lambda: {})

        async def _run_core_json(
            self, agent, system, payload, schema, *args, phase="", **kw
        ):
            self.calls.append((phase, system, payload))
            if "reasoning_seeds" in schema:
                return json.dumps({"reasoning_seeds": []})
            if "hypotheses" in schema:
                self.count += 1
                return json.dumps(
                    {
                        "hypotheses": [
                            {
                                "name": f"载具甲{self.count}",
                                "concise_winning_summary": "此项为隔离执行流的固定样本，用于验证输入传递和候选聚合，并在组合评审中统一判退，不构成任何实际装备方案。",
                            }
                        ]
                    }
                )
            if "decisions" in schema:
                candidates = payload.get("candidate_ledger", {}).get("hypotheses", [])
                return json.dumps(
                    {
                        "decisions": [
                            {
                                "hypothesis_id": c["hypothesis_id"],
                                "decision": "reject",
                                "reason": "fixture rejection",
                            }
                            for c in candidates
                        ],
                        "portfolio_order": [],
                    }
                )
            if "open_hints" in schema:
                return json.dumps({"open_hints": []})
            raise AssertionError((phase, schema.keys()))

    async def scenario():
        host = Host()
        state = SwarmState()
        accumulated = {}
        events = []

        async def cluster(candidates, **kw):
            return list(candidates), []

        await execute_dynamic_mission_graph(
            accumulated=accumulated,
            baseline_boundaries=[],
            cluster_hypotheses_with_independent_codex=cluster,
            creative_military_value_handoff=lambda: {"claims": []},
            emit_swarm_event=lambda *a, **kw: events.append((a, kw)),
            host=host,
            primary_branch="B",
            runs=[],
            shared={
                "run_id": "flow-test",
                "topic": "isolated fixture",
                "execution_profile_id": "winning_swarm_dynamic_v2",
                "research_route": "traditional_gap",
                "structured_query_brief": {},
                "evidence_index": [],
            },
            state=state,
            swarm_controller=WinningSwarmController(
                {"policy_id": "winning_swarm_dynamic_v2", "enabled": True}
            ),
            valid_reference_ids=set(),
        )
        for stage in ["S1", "S2", "S3", "S4", "S5"]:
            assert any(
                load_dynamic_winning_prompt(stage) in system
                for _, system, _ in host.calls
            ), stage
        creative_payloads = [
            payload
            for phase, _, payload in host.calls
            if phase == "winning_swarm_dynamic_seed"
        ]
        assert creative_payloads
        assert all("coverage_steer" in payload for payload in creative_payloads)
        axes = {
            str(payload["coverage_steer"]["exclusive_axis"])
            for payload in creative_payloads
        }
        assert "mechanism" in axes
        event_names = [args[0] for args, _ in events if args]
        assert "winning_semantic_cluster_skipped" in event_names
        assert not accumulated["winning_swarm"]["final_equipment_portfolio"]
        planned = [
            details
            for args, details in events
            if args and args[0] == "winning_mission_graph_planned"
        ]
        assert planned
        # The normalized dynamic-v2 policy targets ten first-wave seats.  This
        # catches regressions where the executor silently falls back to the
        # historical sixteen-seat default instead of consuming policy.
        assert planned[0]["target_instances"] == 10
        assert planned[0]["task_count"] == 10

    asyncio.run(scenario())


def test_dynamic_v2_cross_pool_s5_reviews_remaining_candidates_when_one_creator_is_empty(monkeypatch):
    """An empty creator branch must not waste a dedicated S5 slice."""

    import json

    from equipment_deep_research.agents.workflows.winning_flows.dynamic_swarm import (
        execute_dynamic_mission_graph,
    )
    from equipment_deep_research.orchestration.winning_swarm import (
        WinningSwarmController,
    )

    # Keep the fixture one-shot so the intentionally empty creator does not
    # become non-empty on an optional second creative pass.
    monkeypatch.setenv("EQUIPMENT_DR_S3_S4_CREATIVE_PASSES", "1")

    class Host:
        supports_agent_runtime = True

        def __init__(self):
            self.creator_calls = 0
            self.s5_calls: list[list[str]] = []

        def _provider_for(self, *args, **kwargs):
            return SimpleNamespace(snapshot=lambda: {})

        async def _run_core_json(
            self, agent, system, payload, schema, *args, phase="", **kwargs
        ):
            if phase == "winning_pre_generation_active_angle_selection":
                return json.dumps({"open_hints": []})
            if phase == "winning_swarm_dynamic_reasoning_seed":
                return json.dumps({"reasoning_seeds": []})
            if phase == "winning_swarm_dynamic_seed":
                self.creator_calls += 1
                if self.creator_calls == 1:
                    return json.dumps(
                        {
                            "hypotheses": [],
                            "stop_reason": "fixture_empty_creator",
                        }
                    )
                return json.dumps(
                    {
                        "hypotheses": [
                            {
                                "name": f"前出装备{self.creator_calls}",
                                "concise_winning_summary": (
                                    "在当前任务链断点前出部署并直接形成可观察战果。"
                                ),
                                "combat_dimension": (
                                    f"OTHER:独立断点{self.creator_calls}"
                                ),
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
            if phase == "winning_swarm_dynamic_portfolio_review_fast":
                rows = payload.get("candidate_ledger", {}).get("hypotheses", [])
                allowed_ids = [str(row["hypothesis_id"]) for row in rows]
                # Cross-pool reviewers see the live candidate pool, not one
                # creator's empty slice.
                assert allowed_ids
                self.s5_calls.append(allowed_ids)
                return json.dumps(
                    {
                        "decisions": [
                            {
                                "hypothesis_id": hypothesis_id,
                                "decision": "reject",
                                "reason": "fixture rejection",
                            }
                            for hypothesis_id in allowed_ids
                        ],
                        "portfolio_order": allowed_ids,
                    },
                    ensure_ascii=False,
                )
            if phase == "winning_semantic_pair_clustering":
                return json.dumps(
                    {"pairwise_comparisons": [], "stop_reason": "fixture"}
                )
            raise AssertionError((phase, sorted(schema)))

    async def scenario():
        host = Host()
        state = SwarmState()
        accumulated = {}
        events = []

        async def cluster(candidates, **kwargs):
            return list(candidates), []

        await execute_dynamic_mission_graph(
            accumulated=accumulated,
            baseline_boundaries=[],
            cluster_hypotheses_with_independent_codex=cluster,
            creative_military_value_handoff=lambda: {"claims": []},
            emit_swarm_event=lambda *args, **kwargs: events.append((args, kwargs)),
            host=host,
            primary_branch="B",
            runs=[],
            shared={
                "run_id": "empty-scope-test",
                "topic": "empty creator scope",
                "execution_profile_id": "winning_swarm_dynamic_v2",
                "research_route": "traditional_gap",
                "structured_query_brief": {},
                "evidence_index": [],
            },
            state=state,
            swarm_controller=WinningSwarmController(
                {
                    "policy_id": "winning_swarm_dynamic_v2",
                    "enabled": True,
                    "coverage_expand_max_recruits": 0,
                }
            ),
            valid_reference_ids=set(),
        )

        event_names = [args[0] for args, _ in events if args]
        assert host.creator_calls == 4
        assert len(host.s5_calls) == 2
        assert all(scope for scope in host.s5_calls)
        assert event_names.count("winning_s5_parallel_score_started") == 2
        assert all(len(scope) >= 2 for scope in host.s5_calls)

    asyncio.run(scenario())


@pytest.mark.parametrize("max_concurrency", [1, 2])
def test_dynamic_v2_low_concurrency_dispatches_s4_before_s3_tail(
    monkeypatch, max_concurrency
):
    """The incremental S4 boundary must remain useful with only two lanes.

    S3/S4 creators share a heterogeneous first-wave pool.  A constrained
    provider with one or two lanes should still dispatch an S4 seat as soon
    as one S3 seat publishes, instead of filling both lanes with the
    remaining S3 tail first.  This test keeps the provider fixture
    deliberately small and observes scheduler lifecycle events rather than
    relying on wall-clock ordering.
    """

    import json

    from equipment_deep_research.agents.workflows.winning_flows.dynamic_swarm import (
        execute_dynamic_mission_graph,
    )
    from equipment_deep_research.orchestration.winning_swarm import (
        WinningSwarmController,
    )

    monkeypatch.setenv("EQUIPMENT_DR_S3_S4_CREATIVE_PASSES", "1")

    class Host:
        supports_agent_runtime = True

        def __init__(self):
            self.active_calls = 0
            self.maximum_active_calls = 0
            self.s3_calls = 0

        def _provider_for(self, *args, **kwargs):
            return SimpleNamespace(snapshot=lambda: {})

        async def _run_core_json(
            self, agent, system, payload, schema, *args, phase="", **kwargs
        ):
            del agent, system, schema, args, kwargs
            self.active_calls += 1
            self.maximum_active_calls = max(
                self.maximum_active_calls, self.active_calls
            )
            try:
                if phase == "winning_pre_generation_active_angle_selection":
                    return json.dumps({"open_hints": []})
                if phase == "winning_swarm_dynamic_reasoning_seed":
                    return json.dumps({"reasoning_seeds": []})
                if phase == "winning_swarm_dynamic_seed":
                    task = payload.get("specialist_task", {})
                    mission_node = str(task.get("mission_node", ""))
                    instance_id = str(task.get("agent_instance_id", ""))
                    if mission_node == "S3":
                        self.s3_calls += 1
                        # The first S3 branch publishes quickly.  Keep the
                        # second branch in flight long enough for the
                        # incremental S4 boundary to be exercised.
                        await asyncio.sleep(0.005 if self.s3_calls == 1 else 0.08)
                    return json.dumps(
                        {
                            "hypotheses": [
                                {
                                    "name": (
                                        f"前出实体武器{instance_id[-4:]}"
                                    ),
                                    "concise_winning_summary": (
                                        "具体武器在任务链断点前出接敌并直接压制目标，"
                                        "改变对手原有防御交换关系。"
                                    ),
                                    "combat_dimension": (
                                        "OTHER:low-concurrency-dimension-"
                                        f"{instance_id[-4:]}"
                                    ),
                                }
                            ],
                            "considered_dimensions": [
                                "OTHER:low-concurrency-dimension"
                            ],
                        },
                        ensure_ascii=False,
                    )
                if phase == "winning_swarm_dynamic_portfolio_review_fast":
                    rows = list(
                        payload.get("candidate_ledger", {}).get("hypotheses", [])
                    )
                    ids = [str(row["hypothesis_id"]) for row in rows]
                    return json.dumps(
                        {
                            "decisions": [
                                {
                                    "hypothesis_id": candidate_id,
                                    "decision": "retain",
                                    "reason": "fixture retains an independent direct weapon",
                                    "innovation_priority": 0.8,
                                    "disruption_tier": "new_quality_breakthrough",
                                }
                                for candidate_id in ids
                            ],
                            "portfolio_order": ids,
                        },
                        ensure_ascii=False,
                    )
                if phase == "winning_semantic_pair_clustering":
                    return json.dumps(
                        {"pairwise_comparisons": [], "stop_reason": "fixture"}
                    )
                raise AssertionError((phase, payload))
            finally:
                self.active_calls -= 1

    async def scenario():
        host = Host()
        state = SwarmState()
        accumulated = {}
        events = []

        async def cluster(candidates, **kwargs):
            return list(candidates), []

        await execute_dynamic_mission_graph(
            accumulated=accumulated,
            baseline_boundaries=[],
            cluster_hypotheses_with_independent_codex=cluster,
            creative_military_value_handoff=lambda: {"claims": []},
            emit_swarm_event=lambda *args, **kwargs: events.append((args, kwargs)),
            host=host,
            primary_branch="B",
            runs=[],
            shared={
                "run_id": "low-concurrency-dispatch-test",
                "topic": "low-concurrency dispatch",
                "execution_profile_id": "winning_swarm_dynamic_v2",
                "research_route": "traditional_gap",
                "structured_query_brief": {},
                "evidence_index": [],
            },
            state=state,
                swarm_controller=WinningSwarmController(
                    {
                        "policy_id": "winning_swarm_dynamic_v2",
                        "enabled": True,
                        "max_concurrency": max_concurrency,
                        "coverage_expand_max_recruits": 0,
                    }
                ),
            valid_reference_ids=set(),
        )

        progress = [
            {**details, "event_type": args[0] if args else ""}
            for args, details in events
        ]
        s3_done = [
            index
            for index, row in enumerate(progress)
            if row.get("event_type") == "winning_agent_session_completed"
            and row.get("mission_node") == "S3"
        ]
        s4_started = [
            index
            for index, row in enumerate(progress)
            if row.get("event_type") == "winning_agent_session_started"
            and row.get("mission_node") == "S4"
        ]
        boundary = [
            row
            for row in progress
            if row.get("event_type") == "winning_s4_incremental_boundary_opened"
        ]
        boundary_index = next(
            index
            for index, row in enumerate(progress)
            if row.get("event_type") == "winning_s4_incremental_boundary_opened"
        )
        assert len(s3_done) == 3
        assert s4_started
        assert boundary and boundary[0]["completed_s3_instance_ids"]
        assert min(s3_done) < boundary_index < min(s4_started) < max(s3_done)
        assert host.maximum_active_calls <= max_concurrency
        assert (
            accumulated["winning_swarm"]["budget"]["maximum_observed_concurrency"]
            <= max_concurrency
        )

    asyncio.run(scenario())


def test_dynamic_s5_invalid_merge_target_rejects_source_candidate(monkeypatch):
    """Malformed S5 merges must not inherit the default-retain state."""

    import json

    from equipment_deep_research.agents.workflows.winning_flows.dynamic_swarm import (
        execute_dynamic_mission_graph,
    )
    from equipment_deep_research.orchestration.winning_swarm import (
        WinningSwarmController,
    )

    monkeypatch.setenv("EQUIPMENT_DR_S3_S4_CREATIVE_PASSES", "1")

    class Host:
        supports_agent_runtime = True

        def __init__(self):
            self.calls = []
            self.creator_count = 0
            self.reviewer_count = 0

        def _provider_for(self, *args, **kwargs):
            return SimpleNamespace(snapshot=lambda: {})

        async def _run_core_json(
            self, agent, system, payload, schema, *args, phase="", **kwargs
        ):
            self.calls.append((phase, system, payload))
            if "reasoning_seeds" in schema:
                return json.dumps({"reasoning_seeds": []})
            if "open_hints" in schema:
                return json.dumps({"open_hints": []})
            if "hypotheses" in schema:
                self.creator_count += 1
                return json.dumps(
                    {
                        "hypotheses": [
                            {
                                "name": f"独立前出装备{self.creator_count}",
                                "concise_winning_summary": (
                                    "在当前任务链断点前出部署并直接形成可观察战果。"
                                ),
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
            if "decisions" in schema:
                self.reviewer_count += 1
                rows = list(payload.get("candidate_ledger", {}).get("hypotheses", []))
                decisions = []
                for row in rows:
                    candidate_id = str(row.get("hypothesis_id", ""))
                    if self.reviewer_count == 1:
                        decisions.append(
                            {
                                "hypothesis_id": candidate_id,
                                "decision": "merge",
                                "merge_target_hypothesis_id": "",
                                "reason": "故意构造空合并目标以测试拒绝边界",
                            }
                        )
                    else:
                        decisions.append(
                            {
                                "hypothesis_id": candidate_id,
                                "decision": "retain",
                                "reason": "保留独立候选",
                            }
                        )
                return json.dumps(
                    {
                        "decisions": decisions,
                        "portfolio_order": [
                            str(row.get("hypothesis_id", "")) for row in rows
                        ],
                    },
                    ensure_ascii=False,
                )
            raise AssertionError((phase, schema.keys()))

    async def scenario():
        host = Host()
        state = SwarmState()
        accumulated = {}
        events = []

        async def cluster(candidates, **kwargs):
            return list(candidates), []

        await execute_dynamic_mission_graph(
            accumulated=accumulated,
            baseline_boundaries=[],
            cluster_hypotheses_with_independent_codex=cluster,
            creative_military_value_handoff=lambda: {"claims": []},
            emit_swarm_event=lambda *args, **kwargs: events.append((args, kwargs)),
            host=host,
            primary_branch="B",
            runs=[],
            shared={
                "run_id": "invalid-merge-test",
                "topic": "invalid merge target boundary",
                "execution_profile_id": "winning_swarm_dynamic_v2",
                "research_route": "traditional_gap",
                "structured_query_brief": {},
                "evidence_index": [],
            },
            state=state,
            swarm_controller=WinningSwarmController(
                {"policy_id": "winning_swarm_dynamic_v2", "enabled": True}
            ),
            valid_reference_ids=set(),
        )

        invalid_rows = [
            row
            for row in state.swarm_rejections
            if row.get("stage") == "full_pool_s5_invalid_merge_target"
        ]
        assert invalid_rows
        rejected_id = invalid_rows[0]["hypothesis_id"]
        assert rejected_id not in {
            row["hypothesis_id"]
            for row in accumulated["winning_swarm"]["hypotheses"]
        }
        assert any(
            args
            and args[0] == "winning_s5_invalid_merge_rejected"
            and kwargs.get("hypothesis_id") == rejected_id
            for args, kwargs in events
        )

    asyncio.run(scenario())
