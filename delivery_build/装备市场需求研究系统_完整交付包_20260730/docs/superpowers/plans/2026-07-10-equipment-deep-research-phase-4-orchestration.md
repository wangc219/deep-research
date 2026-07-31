# Phase 4 动态多智能体编排与通信实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 capability 驱动的动态 agent 选择、ResearchPlanGraph、有界并发 subagent 调度和结构化消息流，使默认四 agent、任意子集和自定义替换均形成真实多 agent 闭环。

**Architecture:** 编排器先解析问题和路线所需 capability，再生成 Map-Reduce-Refine 计划图。每个 map 节点对应隔离 subagent；reduce 只消费结构化 packet；refine 根据 coverage、冲突和开放问题创建下一波任务。

**Tech Stack:** asyncio、dataclasses、SQLite save point、pytest-asyncio。

## Global Constraints

- agent 数量由任务可拆性决定，不为凑数量创建 worker。
- baseline agent 之间不直接对话。
- 所有通信必须经过 `TaskEnvelope`、领域对象引用或 `RecallEnvelope`。
- `max_concurrency` 默认 4，可配置。
- worker 失败不得覆盖已完成 worker 的 save point。
- ResearchPlanGraph、WorkerReport 和 coverage 必须提供稳定 `to_view()` 投影，供 API 和前端展示，投影中不包含 raw context/session。

---

### Task 1: 实现问题解析与 capability 计划图

**Files:**
- Create: `src/equipment_deep_research/orchestration/planning.py`
- Modify: `src/equipment_deep_research/orchestration/coverage.py`
- Test: `tests/equipment_deep_research/unit/test_research_planning.py`

**Interfaces:**
- Consumes: `ResearchProblem`、`PresetPolicy`、`AgentRegistry`。
- Produces: `ResearchPlanner.build(problem, selected_agents) -> ResearchPlanGraph`。

- [ ] **Step 1: 写失败测试**

```python
def test_planner_builds_map_reduce_nodes_for_selected_agents() -> None:
    graph = planner.build(problem("低空无人机威胁与装备能力"), selected_default_agents())
    baseline = [n for n in graph.nodes if n.node_type == "baseline_map"]
    assert {n.target_agent_id for n in baseline} == {
        "international_situation", "combat_scenario", "weapon_equipment", "operational_employment"
    }
    reduce_node = next(n for n in graph.nodes if n.node_type == "baseline_reduce")
    assert set(reduce_node.depends_on) == {n.node_id for n in baseline}

def test_single_integrated_agent_does_not_spawn_redundant_workers() -> None:
    graph = planner.build(problem("综合防空能力需求"), [integrated_agent_all_tags()])
    assert len([n for n in graph.nodes if n.node_type == "baseline_map"]) == 1
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_research_planning.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现计划算法**

优先选择用户指定 agent；未指定时按最少 agent 覆盖必需 capability 的确定性贪心算法选择。每个 agent 一个 map 节点，之后是 reduce、winning、audit、report 节点。缺失 capability 写入 `coverage_limits`，不创建不存在的 agent。

- [ ] **Step 4: 运行计划测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_research_planning.py -q`

Expected: PASS。

- [ ] **Step 5: 验证三条路线计划图**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_research_planning.py -q -k route`

Expected: 三条路线的 required tags 与 `presets.yaml` 一致。

### Task 2: 实现结构化 MessageBus

**Files:**
- Create: `src/equipment_deep_research/orchestration/communication.py`
- Test: `tests/equipment_deep_research/unit/test_message_bus.py`

**Interfaces:**
- Produces: `AgentMessageEnvelope`、`OrchestrationMessageBus.publish()`、`drain_for()`、`history()`。

- [ ] **Step 1: 写失败测试**

```python
def test_bus_rejects_raw_session_payload() -> None:
    bus = OrchestrationMessageBus()
    with pytest.raises(ValueError, match="raw session"):
        bus.publish(AgentMessageEnvelope(
            message_id="m1", message_type="handoff", sender="a", recipient="b",
            object_refs=[], payload={"raw_messages": [{"role": "assistant"}]},
        ))

def test_bus_delivers_only_to_target_or_capability_subscriber() -> None:
    bus.publish(handoff(recipient="winning_mechanism", tags=["threat"]))
    assert len(bus.drain_for("winning_mechanism", ["winning_mechanism"])) == 1
    assert bus.drain_for("weapon_equipment", ["equipment"]) == []
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_message_bus.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现消息约束**

允许类型固定为 `task_assigned`、`handoff_ready`、`recall_requested`、`recall_completed`、`coverage_limited`、`stage_completed`。payload 最大 32KB，只允许标量、短摘要和对象引用；`messages/raw_session/provider_headers` 等键直接拒绝。

- [ ] **Step 4: 运行消息总线测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_message_bus.py -q`

Expected: PASS。

- [ ] **Step 5: 验证消息历史进入 trace**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_message_bus.py -q -k trace`

Expected: PASS。

### Task 3: 实现有界并发 Scheduler

**Files:**
- Rewrite: `src/equipment_deep_research/harness/scheduler.py`
- Test: `tests/equipment_deep_research/integration/test_scheduler_concurrency.py`

**Interfaces:**
- Consumes: `AgentRuntime.execute(TaskEnvelope)`。
- Produces: `DiscoveryScheduler.run_wave()`、`run_until_blocked()`、`cancel()`。

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_scheduler_runs_four_workers_with_concurrency_limit_two() -> None:
    runtime = MeasuringRuntime(delay=0.05)
    scheduler = DiscoveryScheduler(runtime_factory=lambda _: runtime, max_concurrency=2)
    results = await scheduler.run_wave([task(i) for i in range(4)])
    assert len(results) == 4
    assert runtime.max_active == 2

@pytest.mark.asyncio
async def test_one_worker_failure_does_not_discard_other_results() -> None:
    results = await scheduler_with_one_failure().run_wave([task(1), task(2), task(3)])
    assert [r.status for r in results].count("completed") == 2
    assert [r.status for r in results].count("failed") == 1
```

- [ ] **Step 2: 运行并确认当前串行 scheduler 失败**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_scheduler_concurrency.py -q`

Expected: FAIL。

- [ ] **Step 3: 用 asyncio.Semaphore 实现有界并发**

每个 worker 独立 Harness、session、budget 和 cancel token，共享同一个事务 store。结果按输入 task 顺序返回；trace 记录 spawn/start/complete/fail/cancel 和 parent task id。

- [ ] **Step 4: 运行 scheduler 测试**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_scheduler_concurrency.py -q`

Expected: PASS。

- [ ] **Step 5: 验证 session 隔离**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_scheduler_concurrency.py -q -k session`

Expected: 每个 agent run 只有自己的 session 文件和 task id。

### Task 4: 实现 subagent 创建判据

**Files:**
- Create: `src/equipment_deep_research/orchestration/subagents.py`
- Test: `tests/equipment_deep_research/unit/test_subagent_policy.py`

**Interfaces:**
- Produces: `SubagentDecision`、`SubagentPolicy.evaluate(candidate) -> SubagentDecision`。

- [ ] **Step 1: 写失败测试**

```python
def test_subagent_requires_all_four_conditions() -> None:
    decision = policy.evaluate(SubtaskCandidate(
        separable=True, context_isolation_gain=True,
        merge_contract="BaselineFindingPacket", budget_available=True,
    ))
    assert decision.spawn is True
    assert policy.evaluate(replace(candidate, merge_contract="")).spawn is False
    assert policy.evaluate(replace(candidate, separable=False)).spawn is False
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_subagent_policy.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现可解释判定**

`SubagentDecision` 返回 `spawn`、`reasons`、`estimated_cost`、`merge_node`。拒绝创建时，编排器把任务并入父 agent context，而不是丢弃。

- [ ] **Step 4: 运行 policy 测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_subagent_policy.py -q`

Expected: PASS。

- [ ] **Step 5: 记录判定 trace**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_subagent_policy.py -q -k trace`

Expected: PASS，包含 spawn/reject 原因。

### Task 5: 接入 runner 并完成动态 agent E2E

**Files:**
- Modify: `src/equipment_deep_research/orchestration/runner.py`
- Test: `tests/equipment_deep_research/e2e/test_dynamic_agents.py`
- Create: `docs/testing/phase-4-test-report.md`

**Interfaces:**
- Consumes: `ResearchPlanner`、`DiscoveryScheduler`、`OrchestrationMessageBus`。
- Produces: 并发 baseline wave 和结构化 reduce 结果。

- [ ] **Step 1: 写三类 E2E 失败测试**

```python
@pytest.mark.parametrize("agent_ids,expected_count", [
    (None, 4),
    (["combat_scenario", "weapon_equipment"], 2),
    (["integrated_research"], 1),
])
def test_dynamic_agent_topologies(agent_ids, expected_count, tmp_path) -> None:
    result = run_fake(tmp_path, agent_ids=agent_ids, custom_config=agent_ids == ["integrated_research"])
    summary = read_summary(result)
    assert len(summary["worker_reports"]) == expected_count
    assert summary["plan_graph"]["baseline_map_count"] == expected_count
```

- [ ] **Step 2: 运行并确认旧 runner 不输出计划图**

Run: `python3 -m pytest tests/equipment_deep_research/e2e/test_dynamic_agents.py -q`

Expected: FAIL。

- [ ] **Step 3: 接入计划、并发和 reduce**

baseline wave 完成后，orchestrator 仅读取 `BaselineFindingPacket`、EvidenceCard 索引和 worker status，生成 coverage/conflict/open-question 汇总；不得读取 session。

- [ ] **Step 4: 运行动态 E2E 与全量测试**

Run: `python3 -m pytest tests/equipment_deep_research/e2e/test_dynamic_agents.py -q`

Expected: PASS。

- [ ] **Step 5: 生成 Phase 4 审查包**

Run: `python3 -m pytest -q`

Expected: 全部 PASS；报告附三种 topology 的计划图、并发时间证据、session 隔离检查和 coverage limit 示例。
