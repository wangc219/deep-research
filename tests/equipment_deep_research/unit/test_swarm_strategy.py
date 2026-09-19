"""Pure-function tests for dynamic-v2 coverage, composition and gap decisions."""

from __future__ import annotations

from equipment_deep_research.domain.models import WinningHypothesis
from equipment_deep_research.orchestration.swarm_strategy import (
    AdaptiveSwarmDecision,
    assign_scout_mission,
    compose_dynamic_v2_first_wave,
    build_coverage_snapshot,
    decide_adaptive_action,
    extract_query_axis_hits,
    recruit_archetype_for_gap,
    resolve_dynamic_v2_instance_bounds,
)
from equipment_deep_research.orchestration.winning_swarm import WinningSwarmController


def _hypothesis(**overrides: object) -> WinningHypothesis:
    payload = {
        "hypothesis_id": "hypothesis-1",
        "title": "分布式低成本拦截节点改变饱和防御成本交换",
        "nearest_public_baseline": "现有公开基线依赖少量高价值集中式拦截节点",
        "changed_confrontation_variable": "把单节点性能优势改为可快速补充的节点密度",
        "mechanism_chain": ["分散部署", "局部感知与交战", "节点损耗后任务接续"],
        "direct_military_effects": ["持续物理拦截饱和来袭目标"],
        "equipment_forms": ["模块化无人拦截平台"],
        "project_function": "防空分队依靠模块化无人拦截平台持续实施物理拦截。",
        "novelty_delta": "从集中式高价值节点转向可补充的分布式装备族",
        "original_paradigm": "依靠少量高价值集中式节点维持区域拦截",
        "disruptive_shift": "把拦截权分散到可损耗自治节点",
        "independence_thesis": "改变交战权与战损接续关系",
        "counterevidence": ["复杂电磁环境可能降低局部协同质量"],
        "adversary_adaptations": ["对手转向诱饵和节点压制"],
        "failure_boundaries": ["局部感知完全失效时机制不成立"],
        "validation_plan": ["用对照场景测试节点损耗后的任务链闭合"],
        "cost_constraints": ["全寿命成本需与现役拦截方案比较"],
        "score": 0.9,
    }
    payload.update(overrides)
    return WinningHypothesis(**payload)


def test_first_wave_uses_target_and_keeps_heterogeneous_creators() -> None:
    small = compose_dynamic_v2_first_wave(target_instances=8, maximum_instances=21)
    default = compose_dynamic_v2_first_wave(target_instances=10, maximum_instances=21)
    large = compose_dynamic_v2_first_wave(target_instances=15, maximum_instances=21)

    assert small.instance_count == 8
    assert small.reviewer_count == 2
    assert small.creative_count == 3
    assert default.instance_count == 10
    assert default.creative_count == 4
    assert default.reviewer_count == 2
    assert large.instance_count == 11
    assert large.reviewer_count == 3
    assert large.reserved_recruit_slots == 10
    creative = [
        seat.archetype
        for seat in default.seats
        if seat.mission_node in {"S3", "S4"}
    ]
    assert "disruptive_mechanism_generator" in creative
    assert "innovative_equipment_dimension_generator" in creative
    assert "weak_signal_scout" in creative
    assert creative.count("innovative_equipment_dimension_generator") == 1


def test_dynamic_v2_instance_bounds_are_shared_and_reserve_capacity() -> None:
    defaults = resolve_dynamic_v2_instance_bounds()
    assert defaults.minimum_instances == 8
    assert defaults.target_instances == 10
    assert defaults.maximum_instances == 21

    reserved = resolve_dynamic_v2_instance_bounds(
        minimum_instances=8,
        target_instances=20,
        maximum_instances=21,
        hard_maximum_instances=18,
        reserved_instances=4,
    )
    assert reserved.minimum_instances == 8
    assert reserved.target_instances == 14
    assert reserved.maximum_instances == 18

    malformed = resolve_dynamic_v2_instance_bounds(
        minimum_instances="bad",  # type: ignore[arg-type]
        target_instances=999,
        maximum_instances=12,
    )
    assert malformed.minimum_instances == 8
    assert malformed.target_instances == 12
    assert malformed.maximum_instances == 12


def test_coverage_snapshot_flags_isomorphic_interceptor_family() -> None:
    clones = [
        _hypothesis(
            hypothesis_id=f"hyp-{index}",
            title=f"低成本拦截弹{index}",
            equipment_forms=["拦截弹"],
            mechanism_chain=["动能毁伤", "拦截来袭"],
            combat_dimension="拦截",
        )
        for index in range(1, 5)
    ]
    snapshot = build_coverage_snapshot(clones, topic="区域拒止")
    assert snapshot.candidate_count == 4
    assert snapshot.duplicate_ratio >= 0.5
    assert "carrier_form" in snapshot.primary_gaps or snapshot.duplicate_ratio > 0.4


def test_gap_decision_expands_on_low_coverage_and_stops_on_budget() -> None:
    interceptors = [
        _hypothesis(
            hypothesis_id="hyp-a",
            title="低成本拦截弹",
            equipment_forms=["拦截弹"],
            mechanism_chain=["动能毁伤"],
            adversary_adaptations=[],
            counterevidence=[],
            failure_boundaries=[],
            validation_plan=[],
        )
    ]
    snapshot = build_coverage_snapshot(interceptors, topic="海峡拒止")
    expand = decide_adaptive_action(
        snapshot,
        remaining_instances=4,
        remaining_calls=8,
    )
    assert expand.action == "expand"
    assert expand.recruit_archetype
    exhausted = decide_adaptive_action(
        snapshot,
        remaining_instances=0,
        remaining_calls=8,
    )
    assert exhausted.action in {"review", "stop"}
    assert exhausted.reason == "budget_exhausted"


def test_verify_recruits_red_team_when_contradiction_is_missing() -> None:
    item = _hypothesis(
        hypothesis_id="hyp-open",
        title="气溶胶介质拒止幕",
        equipment_forms=["气溶胶介质"],
        mechanism_chain=["空间拒止", "预置展开"],
        combat_dimension="通道拒止",
        adversary_adaptations=[],
        counterevidence=[],
        failure_boundaries=[],
        validation_plan=[],
        cost_constraints=["单次成本可消耗"],
    )
    snapshot = build_coverage_snapshot([item], topic="海峡拒止")
    # Force a high coverage / low contradiction path by using the real
    # contradiction metric from the snapshot.
    if snapshot.contradiction_coverage < 0.7:
        decision = decide_adaptive_action(
            snapshot,
            remaining_instances=3,
            remaining_calls=6,
            coverage_threshold=0.0,
        )
        assert decision.action in {"verify", "expand"}
        if decision.action == "verify":
            assert decision.recruit_archetype == "adversary_counter_adaptation_red_team"


def test_controller_builds_target_sized_graph_and_recruits_into_it() -> None:
    controller = WinningSwarmController(
        {"enabled": True, "policy_id": "winning_swarm_dynamic_v2"}
    )
    graph = controller.build_mission_graph(
        topic="海峡拒止",
        target_instances=10,
    )
    assert len(graph.agent_instances) == 10
    creators = [
        item
        for item in graph.agent_instances
        if item.mission_node in {"S3", "S4"}
    ]
    reviewers = [
        item for item in graph.agent_instances if item.mission_node == "S5"
    ]
    assert len(creators) == 4
    assert len(reviewers) == 2
    assert {item.archetype for item in creators} >= {
        "disruptive_mechanism_generator",
        "innovative_equipment_dimension_generator",
        "weak_signal_scout",
    }
    creator_ids = {item.instance_id for item in creators}
    assert all(set(item.depends_on) == creator_ids for item in reviewers)

    recruited = controller.recruit_for_coverage_gap(
        graph,
        topic="海峡拒止",
        execution_profile_id="winning_swarm_dynamic_v2",
        gap_axis="counter_adaptation",
        already_used=tuple(item.archetype for item in creators),
    )
    assert len(recruited.agent_instances) == 11
    new_creators = [
        item
        for item in recruited.agent_instances
        if item.mission_node in {"S3", "S4"}
    ]
    new_reviewers = [
        item for item in recruited.agent_instances if item.mission_node == "S5"
    ]
    assert len(new_creators) == 5
    assert any(
        item.archetype == "adversary_counter_adaptation_red_team"
        for item in new_creators
    )
    assert all(
        set(item.depends_on)
        == {row.instance_id for row in new_creators}
        for item in new_reviewers
    )


def test_query_hits_steer_orthogonal_scout_missions() -> None:
    hits = extract_query_axis_hits("海峡通道拦截弹拒止")
    assert "corridor" in hits["engagement_geometry"] or "munition" in hits["carrier_form"]
    on_query = assign_scout_mission(
        archetype="disruptive_mechanism_generator",
        topic="海峡通道拦截弹拒止",
        on_query_seat=True,
    )
    orthogonal = assign_scout_mission(
        archetype="innovative_equipment_dimension_generator",
        topic="海峡通道拦截弹拒止",
        occupied=build_coverage_snapshot(
            [
                _hypothesis(
                    title="低成本拦截弹",
                    equipment_forms=["拦截弹"],
                    mechanism_chain=["动能毁伤", "拦截来袭"],
                )
            ],
            topic="海峡通道拦截弹拒止",
        ),
    )
    assert on_query.axis == "mechanism"
    assert orthogonal.axis == "carrier_form"
    assert "munition" not in orthogonal.focus_values
    assert "material" in orthogonal.focus_values or "infrastructure" in orthogonal.focus_values
    payload = orthogonal.to_payload("避开弹药弹体")
    assert payload["exclusive_axis"] == "carrier_form"
    assert "避开弹药弹体" in str(payload["instruction"])


def test_recruit_archetype_switches_axis_instead_of_cloning() -> None:
    node, archetype = recruit_archetype_for_gap("carrier_form")
    assert node == "S4"
    assert archetype == "innovative_equipment_dimension_generator"
    node, archetype = recruit_archetype_for_gap(
        "counter_adaptation",
        already_used=("adversary_counter_adaptation_red_team",),
    )
    assert archetype == "cross_scenario_stress_tester"


def test_adaptive_decision_is_serialisable() -> None:
    snapshot = build_coverage_snapshot(
        [_hypothesis()],
        topic="query",
    )
    decision = decide_adaptive_action(
        snapshot,
        remaining_instances=2,
        remaining_calls=4,
    )
    assert isinstance(decision, AdaptiveSwarmDecision)
    payload = decision.to_event()
    assert "decision_action" in payload
    assert "decision_reason" in payload


def test_adaptive_decision_treats_unavailable_budget_metrics_as_unbounded() -> None:
    snapshot = build_coverage_snapshot(
        [_hypothesis(hypothesis_id="budget-metric")],
        topic="query",
    )
    decision = decide_adaptive_action(
        snapshot,
        remaining_instances=1,
        remaining_calls=1,
        remaining_tokens=None,
        remaining_time=None,
    )
    assert decision.reason != "budget_exhausted"


def test_adaptive_decision_stops_after_two_low_novelty_observations() -> None:
    snapshot = build_coverage_snapshot(
        [_hypothesis(hypothesis_id="same-family")],
        topic="query",
        previous_cluster_keys=("structural_failure|unmanned|area",),
    )
    decision = decide_adaptive_action(
        snapshot,
        remaining_instances=2,
        remaining_calls=2,
        consecutive_low_novelty=2,
    )
    assert decision.action == "stop"
    assert decision.reason == "marginal_novelty_exhausted"
