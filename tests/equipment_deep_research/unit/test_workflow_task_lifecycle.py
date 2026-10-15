from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from equipment_deep_research.agents.workflows.coordinator import S6QualityError
from equipment_deep_research.agents.workflows.task_lifecycle import (
    WorkflowTaskScope,
    gather_isolated,
)
from equipment_deep_research.agents.workflows.winning_flows.dynamic_swarm import (
    _s5_review_output_budget,
    execute_dynamic_mission_graph,
)
from equipment_deep_research.agents.workflows.winning_flows.s6_authoring import (
    _author_s6_module_with_retry,
    _validate_s6_response_identity,
)
from equipment_deep_research.contracts.runtime import ModelBudgetExhausted
from equipment_deep_research.domain.swarm_strategy.state import SwarmState
from equipment_deep_research.orchestration.winning_swarm import WinningSwarmController


def test_task_scope_drains_running_peers_on_scheduler_failure():
    async def scenario():
        started, drained = asyncio.Event(), asyncio.Event()

        async def model_call():
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                drained.set()

        with pytest.raises(ValueError, match="scheduler failure"):
            async with WorkflowTaskScope() as scope:
                task = scope.create_task(model_call())
                await started.wait()
                raise ValueError("scheduler failure")
        assert task.cancelled()
        assert drained.is_set()

    asyncio.run(scenario())


@pytest.mark.parametrize("parent_cancel", [False, True])
def test_isolated_gather_propagates_cancellation_and_drains_peers(parent_cancel):
    async def scenario():
        started, drained = asyncio.Event(), asyncio.Event()

        async def slow_column():
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                drained.set()

        async def cancelled_column():
            await started.wait()
            if parent_cancel:
                await asyncio.Event().wait()
            raise asyncio.CancelledError()

        task = asyncio.create_task(gather_isolated(slow_column(), cancelled_column()))
        if parent_cancel:
            await started.wait()
            task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert drained.is_set()

    asyncio.run(scenario())


def test_isolated_gather_keeps_successful_results_after_an_ordinary_failure():
    async def result(value):
        if isinstance(value, Exception):
            raise value
        return value

    rows = asyncio.run(gather_isolated(result("healthy"), result(ValueError("bad JSON"))))
    assert rows[0] == "healthy"
    assert isinstance(rows[1], ValueError)


def test_failed_s6_column_recovers_before_slow_sibling_finishes():
    async def scenario():
        recovered = asyncio.Event()
        attempts = []

        async def author(key, *, module_attempt, **kwargs):
            attempts.append((key, module_attempt))
            if key == "overview" and module_attempt == 1:
                raise ValueError("malformed JSON")
            if key == "overview":
                recovered.set()
            else:
                # The former wave barrier cannot pass this dependency: the
                # slow sibling needs the failed column's retry to start first.
                await asyncio.wait_for(recovered.wait(), timeout=1)
            return key, "independent complete prose"

        rows = await gather_isolated(*(
            _author_s6_module_with_retry(
                key, author_module=author, maximum_attempts=2, on_retry=lambda **kw: None
            ) for key in ("overview", "winning_logic")
        ))
        assert all(isinstance(row, tuple) for row in rows)
        assert attempts.count(("winning_logic", 1)) == 1
        assert ("overview", 2) in attempts

    asyncio.run(scenario())


@pytest.mark.parametrize("key", ["overview", "technology_implementation"])
def test_s6_budget_failure_never_retries_or_enters_offline_rescue(key):
    attempts = []

    async def author(key, **kwargs):
        attempts.append(kwargs["module_attempt"])
        raise ModelBudgetExhausted("lane exhausted")

    with pytest.raises(ModelBudgetExhausted):
        asyncio.run(_author_s6_module_with_retry(
            key, author_module=author, maximum_attempts=3, on_retry=lambda **kw: None
        ))
    assert attempts == [1]


def test_technology_offline_recovery_is_bounded_and_column_local():
    attempts = []

    async def author(key, **kwargs):
        attempts.append((key, kwargs["module_attempt"], kwargs.get("phase_suffix", "")))
        if kwargs.get("phase_suffix") == "_offline_recovery":
            return key, "complete offline prose"
        raise TimeoutError("tool unavailable")

    row = asyncio.run(_author_s6_module_with_retry(
        "technology_implementation", author_module=author,
        maximum_attempts=2, on_retry=lambda **kw: None,
    ))
    assert row == ("technology_implementation", "complete offline prose")
    assert [item[1] for item in attempts] == [1, 2, 3]
    assert attempts[-1][2] == "_offline_recovery"


@pytest.mark.parametrize("field", ["module_key", "card_binding_id", "hypothesis_id"])
@pytest.mark.parametrize("wrapped", [False, True])
def test_s6_rejects_misrouted_prose_before_identity_stabilization(field, wrapped):
    response = {"module_key": "overview", "card_binding_id": "card-1", "hypothesis_id": "h-1"}
    response[field] = "other-card"
    if wrapped:
        response = {"direction": response}
    with pytest.raises(S6QualityError, match=f"{field} mismatch"):
        _validate_s6_response_identity(
            response, binding_id="card-1", hypothesis_id="h-1", module_key="overview"
        )


def test_s6_legacy_omitted_routing_fields_remain_compatible():
    _validate_s6_response_identity(
        {"module_content": "complete prose"},
        binding_id="card-1", hypothesis_id="h-1", module_key="overview",
    )


def test_s5_output_budget_scales_for_full_pool_and_stays_bounded():
    assert _s5_review_output_budget(1) == 2400
    assert _s5_review_output_budget(18) > _s5_review_output_budget(6) > 2400
    assert _s5_review_output_budget(1000) == 16384


def test_dynamic_graph_cancellation_never_retries_and_drains_running_seeds():
    async def scenario():
        started, drained = asyncio.Event(), asyncio.Event()
        events, calls = [], []

        class Host:
            supports_agent_runtime = True

            def _provider_for(self, *args, **kwargs):
                return SimpleNamespace(snapshot=lambda: {})

            async def _run_core_json(self, agent, system, payload, schema, *args, **kwargs):
                calls.append(agent)
                if len(calls) == 1:
                    try:
                        started.set()
                        await asyncio.Event().wait()
                    finally:
                        drained.set()
                await started.wait()
                raise asyncio.CancelledError()

        async def cluster(candidates, **kwargs):
            return candidates, []

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(execute_dynamic_mission_graph(
                accumulated={}, baseline_boundaries=[],
                cluster_hypotheses_with_independent_codex=cluster,
                creative_military_value_handoff=lambda: {"claims": []},
                emit_swarm_event=lambda name, **kwargs: events.append(name),
                host=Host(), primary_branch="B", runs=[],
                shared={"topic": "generic fixture", "execution_profile_id": "winning_swarm_dynamic_v2"},
                state=SwarmState(),
                swarm_controller=WinningSwarmController({
                    "policy_id": "winning_swarm_dynamic_v2", "enabled": True,
                }),
                valid_reference_ids=set(),
            ), timeout=1)
        assert drained.is_set()
        assert len(set(calls)) == len(calls) > 1
        assert "winning_agent_instance_retry_scheduled" not in events

    asyncio.run(scenario())


def test_dynamic_coverage_does_not_redecide_on_unchanged_candidate_pool(monkeypatch):
    from equipment_deep_research.agents.workflows.winning_flows import dynamic_swarm

    decide = dynamic_swarm.decide_adaptive_action
    monkeypatch.setattr(
        dynamic_swarm, "decide_adaptive_action",
        lambda *args, **kwargs: replace(decide(*args, **kwargs), action="review"),
    )

    async def scenario():
        coverage_counts = []

        class Host:
            supports_agent_runtime = True
            creator_count = 0

            def _provider_for(self, *args, **kwargs):
                return SimpleNamespace(snapshot=lambda: {})

            async def _run_core_json(self, agent, system, payload, schema, *args, **kwargs):
                if "reasoning_seeds" in schema:
                    return json.dumps({"reasoning_seeds": []})
                if "open_hints" in schema:
                    return json.dumps({"open_hints": []})
                if "hypotheses" in schema:
                    self.creator_count += 1
                    if self.creator_count > 2:
                        # Empty later branches still wake the scheduler but
                        # must not advance coverage history or recruit again.
                        await asyncio.sleep(0.005 * self.creator_count)
                        return json.dumps({"hypotheses": []})
                    return json.dumps({"hypotheses": [{
                        "name": f"隔离样本{self.creator_count}",
                        "concise_winning_summary": "固定测试样本，用于执行流聚合验证，由评审统一判退，不表示实际装备方案。",
                    }]})
                if "decisions" in schema:
                    return json.dumps({"decisions": [
                        {"hypothesis_id": item["hypothesis_id"], "decision": "reject", "reason": "fixture"}
                        for item in payload["candidate_ledger"]["hypotheses"]
                    ], "portfolio_order": []})
                raise AssertionError(schema)

        def emit(name, **data):
            if name == "winning_coverage_decision":
                coverage_counts.append(data["coverage_snapshot"]["candidate_count"])

        async def cluster(candidates, **kwargs):
            return candidates, []

        await execute_dynamic_mission_graph(
            accumulated={}, baseline_boundaries=[],
            cluster_hypotheses_with_independent_codex=cluster,
            creative_military_value_handoff=lambda: {"claims": []}, emit_swarm_event=emit,
            host=Host(), primary_branch="B", runs=[],
            shared={"topic": "generic fixture", "execution_profile_id": "winning_swarm_dynamic_v2"},
            state=SwarmState(), swarm_controller=WinningSwarmController({
                "policy_id": "winning_swarm_dynamic_v2", "enabled": True,
            }), valid_reference_ids=set(),
        )
        assert coverage_counts == [2]

    asyncio.run(scenario())
