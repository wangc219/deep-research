# Phase 5 三条 Deep Research 研究路线实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将三条核心业务路线实现为可配置、多轮、证据缺口驱动的研究控制器，在 fake 工具环境下先形成完整 Deep Research 行为。

**Architecture:** 路线定义负责问题链、必需 capability、阶段目标和停止条件；通用 ResearchLoop 负责检索-阅读-证据-发现-反思-下一轮。每轮只根据未覆盖问题、冲突和低置信 claim 生成新查询，避免重复搜索。

**Tech Stack:** asyncio、YAML route config、pytest scripted tools。

## Global Constraints

- 三路线共享 Harness、scheduler 和工具，不复制执行内核。
- 默认最多 5 轮；达到覆盖、质量和边际收益条件可提前停止。
- 每轮必须产生 `ResearchRoundSummary` 和 checkpoint。
- 能力画像结论不在本阶段生成；本阶段输出可供制胜机理消费的高质量 packet。

---

### Task 1: 定义路线策略与问题链

**Files:**
- Create: `src/equipment_deep_research/orchestration/routes.py`
- Create: `configs/equipment_deep_research/routes.yaml`
- Test: `tests/equipment_deep_research/unit/test_route_policies.py`

**Interfaces:**
- Produces: `RoutePolicy`、`RouteRegistry.load()`、`questions_for(route, capability_tag)`。

- [ ] **Step 1: 写失败测试**

```python
def test_new_route_contains_three_innovation_dimensions() -> None:
    policy = routes.get("new_winning_mechanism")
    text = " ".join(policy.question_chain)
    assert all(term in text for term in ["制胜机制", "作战运用打法", "体系组合"])

def test_traditional_route_requires_current_equipment_comparison() -> None:
    policy = routes.get("traditional_gap")
    assert "equipment_baseline" in policy.required_outputs
    assert "gap_matrix" in policy.required_outputs

def test_war_case_route_requires_timeline_and_lessons() -> None:
    policy = routes.get("war_case_learning")
    assert {"case_timeline", "new_tactics", "lessons", "future_directions"} <= set(policy.required_outputs)
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_route_policies.py -q`

Expected: FAIL。

- [ ] **Step 3: 写三条精确问题链**

新制胜机理路线按“形势 -> 威胁 -> 场景 -> 防御/制胜 -> 新机制/新打法/新组合 -> 装备功能”组织；传统缺口按“传统场景/制胜/战法 -> 当前装备 -> 目标能力 -> 差距/空白 -> 升级功能”组织；战例路线按“时间线 -> 参战方 -> 装备 -> 新打法 -> 效果 -> 不足 -> 可迁移方向”组织。

- [ ] **Step 4: 运行路线策略测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_route_policies.py -q`

Expected: PASS。

- [ ] **Step 5: 验证 presets 与 routes 一致**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_route_policies.py -q -k consistency`

Expected: required capability tags 无冲突。

### Task 2: 实现查询规划与查询去重

**Files:**
- Create: `src/equipment_deep_research/orchestration/query_planning.py`
- Test: `tests/equipment_deep_research/unit/test_query_planning.py`

**Interfaces:**
- Produces: `ResearchQuery`、`QueryPlanner.plan_round()`、`QueryHistory.should_run()`。

- [ ] **Step 1: 写失败测试**

```python
def test_round_two_queries_are_driven_by_evidence_gap() -> None:
    queries = planner.plan_round(
        route="traditional_gap", round_index=2,
        open_questions=["当前型号在强干扰条件下探测距离是多少？"],
        conflicts=[], prior_queries=["低空探测装备 参数"],
    )
    assert any("强干扰" in q.query and "探测距离" in q.query for q in queries)
    assert all(q.query != "低空探测装备 参数" for q in queries)
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_query_planning.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现查询生成规则**

每个问题生成 2-4 个查询变体：中文核心查询、英文术语查询、参数/试验查询、反证查询。归一化后去重；同一 query 最多执行一次，除非新增时间过滤或目标域提示。

- [ ] **Step 4: 运行查询测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_query_planning.py -q`

Expected: PASS。

- [ ] **Step 5: 验证反证查询**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_query_planning.py -q -k counter_evidence`

Expected: 高影响 claim 至少生成一个限制、失败、争议或反例方向查询。

### Task 3: 实现多轮 ResearchLoop 与停止条件

**Files:**
- Create: `src/equipment_deep_research/orchestration/research_loop.py`
- Modify: `src/equipment_deep_research/domain/models.py`
- Test: `tests/equipment_deep_research/integration/test_research_loop.py`

**Interfaces:**
- Produces: `ResearchRoundSummary`、`ResearchLoop.run(task, route_policy)`、`StopDecision`。

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_loop_runs_second_round_for_open_question() -> None:
    tools = ScriptedResearchTools([
        round_result(evidence=["ev-1"], open_questions=["q-gap"], new_high_quality=1),
        round_result(evidence=["ev-2", "ev-3"], open_questions=[], new_high_quality=2),
    ])
    result = await ResearchLoop(max_rounds=5).run(task(), policy(), tools)
    assert result.round_count == 2
    assert result.stop_reason == "coverage_and_quality_met"

@pytest.mark.asyncio
async def test_loop_stops_on_low_marginal_gain() -> None:
    result = await loop_with_three_zero_gain_rounds().run(task(), policy(), scripted_tools())
    assert result.stop_reason == "low_marginal_gain"
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_research_loop.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现每轮状态机**

状态固定为 `plan_queries -> search -> fetch_read -> build_evidence -> synthesize_findings -> reflect -> checkpoint`。停止条件按优先级：取消、预算耗尽、覆盖与质量满足、连续两轮高质量新证据为 0、达到 max rounds。

- [ ] **Step 4: 运行 ResearchLoop 测试**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_research_loop.py -q`

Expected: PASS。

- [ ] **Step 5: 验证每轮 trace 完整**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_research_loop.py -q -k trace`

Expected: 每轮包含开始、查询计划、证据增量、反思、checkpoint 和停止判断事件。

### Task 4: 为四类默认 agent 实现差异化研究契约

**Files:**
- Create: `src/equipment_deep_research/agents/prompts.py`
- Modify: `configs/equipment_deep_research/agents.yaml`
- Test: `tests/equipment_deep_research/unit/test_baseline_agent_contracts.py`

**Interfaces:**
- Produces: `BaselinePromptBuilder.build(agent, route, task, context)`；四类默认 output schema。

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.parametrize("agent_id,required_keys", [
    ("international_situation", {"situation_assessment", "threat_assessment", "strategic_pattern", "opponent_moves"}),
    ("combat_scenario", {"scenario_framework", "enemy_coa", "critical_timeline", "environment_constraints"}),
    ("weapon_equipment", {"current_parameters", "development_models", "technology_readiness", "capability_constraints"}),
    ("operational_employment", {"operational_constraints", "force_coordination", "coa", "lessons"}),
])
def test_default_agent_output_contracts(agent_id, required_keys) -> None:
    schema = registry.get(agent_id).output_contract
    assert required_keys <= set(schema["properties"])
```

- [ ] **Step 2: 运行并确认配置缺少 output contract**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_baseline_agent_contracts.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现差异化 schema 与提示**

提示中只包含该 agent 的角色目标、route 问题、允许工具、证据规则、输出 schema 和覆盖限制。统一外层仍为 `BaselineFindingPacket`，专业字段写入 `structured_findings`。

- [ ] **Step 4: 运行契约测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_baseline_agent_contracts.py -q`

Expected: PASS。

- [ ] **Step 5: 验证自定义 agent 不依赖四类名称**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_baseline_agent_contracts.py -q -k custom`

Expected: 只要自定义 output contract 能映射到统一 packet 即通过。

### Task 5: 完成三路线 fake E2E

**Files:**
- Modify: `src/equipment_deep_research/orchestration/runner.py`
- Create: `tests/equipment_deep_research/e2e/test_new_winning_route_e2e.py`
- Create: `tests/equipment_deep_research/e2e/test_traditional_gap_route_e2e.py`
- Create: `tests/equipment_deep_research/e2e/test_war_case_route_e2e.py`
- Create: `docs/testing/phase-5-test-report.md`

**Interfaces:**
- Consumes: `ResearchLoop`、`RouteRegistry`、动态 scheduler。
- Produces: 三路线 `BaselineFindingPacket[]`、round summaries 和 checkpoints。

- [ ] **Step 1: 写三条 E2E 测试**

每条测试必须断言：至少 2 轮、路线专属 required outputs 存在、至少一个反证查询、packet 引用 evidence、round summary 有 stop reason。

- [ ] **Step 2: 运行并确认旧 runner 只有单轮**

Run: `python3 -m pytest tests/equipment_deep_research/e2e/test_*_route_e2e.py -q`

Expected: FAIL。

- [ ] **Step 3: 接入 ResearchLoop**

runner 为每个 baseline task 启动通用 ResearchLoop；fake provider/tool fixture 按路线返回确定性材料，确保测试不依赖模型随机性。

- [ ] **Step 4: 运行三路线 E2E**

Run: `python3 -m pytest tests/equipment_deep_research/e2e/test_new_winning_route_e2e.py tests/equipment_deep_research/e2e/test_traditional_gap_route_e2e.py tests/equipment_deep_research/e2e/test_war_case_route_e2e.py -q`

Expected: PASS。

- [ ] **Step 5: 生成 Phase 5 审查包**

Run: `python3 -m pytest -q`

Expected: 全部 PASS；报告附每条路线的问题链、两轮查询变化、证据增量和停止原因。
