# Phase 6 制胜机理引擎与定向再调实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完整实现架构图要求的四类资源、六步串联推理、L1/L2/L3 分层门控、定向再调和九字段文字能力画像生成。

**Architecture:** 制胜机理 agent 不依赖固定四路名称，只消费已接纳的 `BaselineFindingPacket[]`、coverage、冲突、证据索引和路线策略。六步推理生成中间领域对象；每层门控可通过、受限或请求再调；RecallCoordinator 将请求转成真实任务并在回传后从 `return_node` 恢复。

**Tech Stack:** dataclasses、JSON schema、通用 AgentHarness、pytest scripted provider。

## Global Constraints

- 四类资源是面向本次 run 的动态投影，不引入额外持久化知识系统。
- 每个关键推理节点必须关联 evidence id、claim id、confidence 和 assumptions。
- L1 未通过不得静默进入 L2；允许在达到轮次上限后以 `limited` 状态继续。
- 同一 recall target 最多 3 次，总研究轮次最多 5 次。
- 能力画像必须是可读文字，且九字段完整。
- 六步对象、L1/L2/L3、GateDecision 和 RecallEnvelope 必须包含稳定节点 id、输入/输出引用和前端可展示摘要，不能要求 Web 解析模型原文。

---

### Task 1: 实现四类资源投影

**Files:**
- Create: `src/equipment_deep_research/orchestration/winning/__init__.py`
- Create: `src/equipment_deep_research/orchestration/winning/resources.py`
- Test: `tests/equipment_deep_research/unit/test_winning_resources.py`

**Interfaces:**
- Produces: `TheoryToolResource`、`CaseResource`、`FrontierResource`、`QuestionChainResource`、`WinningResourcePackBuilder.build()`。

- [ ] **Step 1: 写失败测试**

```python
def test_resource_pack_routes_evidence_by_semantics() -> None:
    pack = builder.build(route="war_case_learning", packets=packets(), evidence=evidence_cards())
    assert pack.theory_tools.defense_layers == ["感知", "决策", "拦截", "冗余"]
    assert pack.case_evidence
    assert pack.frontier_evidence
    assert pack.question_chain.questions[:2] == ["敌方重心是什么？", "制胜逻辑怎样构建？"]
    assert all(item.evidence_ids for item in pack.case_evidence)
```

- [ ] **Step 2: 运行并确认模块不存在**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_winning_resources.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现资源构造**

理论工具包含防御分层、重心识别、击败机制、效果链、效果-功能-性能映射和五档差距；战例资源从 case/lessons 标签证据投影；前沿资源从 technology/concept/trend 标签投影；问题链根据 route、coverage 和 open questions 动态扩展。

- [ ] **Step 4: 运行资源测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_winning_resources.py -q`

Expected: PASS。

- [ ] **Step 5: 验证资源包不含 raw session**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_winning_resources.py -q -k visibility`

Expected: PASS。

### Task 2: 实现六步推理领域对象和执行器

**Files:**
- Create: `src/equipment_deep_research/orchestration/winning/reasoning.py`
- Modify: `src/equipment_deep_research/domain/models.py`
- Test: `tests/equipment_deep_research/unit/test_six_step_reasoning.py`

**Interfaces:**
- Produces: `DefenseDecomposition`、`WinningPathSet`、`EffectChain`、`CapabilityMapping`、`GapMatrix`、`CapabilityImageDraft`、`SixStepReasoner.run()`。

- [ ] **Step 1: 写失败测试固定六步依赖**

```python
def test_six_steps_are_linked_by_object_refs() -> None:
    result = reasoner.run(input_pack())
    assert result.winning_paths.input_refs == [result.defense_decomposition.object_id]
    assert result.effect_chain.input_refs == [result.winning_paths.object_id]
    assert result.capability_mapping.input_refs == [result.effect_chain.object_id]
    assert result.gap_matrix.input_refs == [result.capability_mapping.object_id]
    assert result.image_drafts[0].input_refs == [result.gap_matrix.object_id]

def test_each_critical_node_has_evidence_and_confidence() -> None:
    result = reasoner.run(input_pack())
    for node in result.critical_nodes():
        assert node.evidence_ids
        assert 0 <= node.confidence <= 1
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_six_step_reasoning.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现结构化推理执行器**

每一步通过 winning agent 的结构化模型调用生成 schema，执行器负责输入引用、字段校验、证据存在性校验、confidence 聚合和 proposal。fake provider 使用固定 fixture 返回完整六步对象。

- [ ] **Step 4: 运行六步测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_six_step_reasoning.py -q`

Expected: PASS。

- [ ] **Step 5: 验证三路线推理路径文本**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_six_step_reasoning.py -q -k routes`

Expected: 新机制路线强调创新牵引，传统路线强调装备对比，战例路线强调经验迁移。

### Task 3: 实现 L1/L2/L3 输出与门控

**Files:**
- Create: `src/equipment_deep_research/orchestration/winning/gates.py`
- Create: `src/equipment_deep_research/orchestration/winning/engine.py`
- Delete: `src/equipment_deep_research/orchestration/winning.py`
- Test: `tests/equipment_deep_research/integration/test_winning_engine.py`

**Interfaces:**
- Produces: `GateDecision`、`WinningMechanismEngine.run_until_gate()`、`resume_from()`。

- [ ] **Step 1: 写失败测试**

```python
def test_l1_gate_requires_confidence_coverage_and_no_unresolved_critical_gap() -> None:
    decision = gates.evaluate_l1(l1_output(confidence=0.71), coverage=full_coverage(), unresolved=[])
    assert decision.status == "passed"
    assert gates.evaluate_l1(l1_output(confidence=0.69), coverage=full_coverage(), unresolved=[]).status == "recall_required"

def test_l2_gate_requires_feasibility_and_l1_consistency() -> None:
    assert gates.evaluate_l2(l2_output(feasibility=3, consistent=True)).status == "passed"
    assert gates.evaluate_l2(l2_output(feasibility=2, consistent=True)).status == "recall_required"

def test_l3_gate_requires_nine_fields_and_bidirectional_trace() -> None:
    assert gates.evaluate_l3(valid_images(), trace_index()).status == "passed"
```

- [ ] **Step 2: 运行并确认模板引擎无法满足**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_winning_engine.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现门控**

L1 输出弱点地图、制胜路径、效果链、关键能力、假设；L2 输出概念扫描、类比创新、跨域移植、2-3 个方向、可行性；L3 输出去重归并、类别映射、五档差距、优先级和能力画像。门控结果为 `passed|recall_required|limited|failed`，并写精确 reasons。

- [ ] **Step 4: 运行引擎测试**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_winning_engine.py -q`

Expected: PASS。

- [ ] **Step 5: 检查旧模板字符串不再驱动结果**

Run: `rg -n "体系化快速感知-决策-处置能力|传统战法缺口牵引的新能力补位" src/equipment_deep_research`

Expected: 无结果。

### Task 4: 实现 RecallCoordinator 和再调状态机

**Files:**
- Create: `src/equipment_deep_research/orchestration/recall.py`
- Modify: `src/equipment_deep_research/orchestration/runner.py`
- Test: `tests/equipment_deep_research/integration/test_recall_state_machine.py`

**Interfaces:**
- Consumes: `GateDecision`、`RecallEnvelope`、`AgentRegistry`、`DiscoveryScheduler`。
- Produces: `RecallCoordinator.route()`、`execute_pending()`、`merge_result()`、`resume_node()`。

- [ ] **Step 1: 写失败测试覆盖真实执行**

```python
@pytest.mark.asyncio
async def test_l1_recall_runs_target_agent_and_resumes_l1() -> None:
    runtime = scripted_runtime(l1_first_status="recall_required", recall_packet="packet-threat-2")
    result = await runtime.run(topic="测试", selected_agents=default_agents())
    events = result.trace_events
    assert event_types(events).index("recall_requested") < event_types(events).index("recall_task_completed")
    assert event_types(events).index("recall_task_completed") < event_types(events).index("winning_stage_resumed")
    assert result.l1.attempt == 2
    assert "packet-threat-2" in result.l1.input_refs

def test_recall_limits_same_target_to_three_attempts() -> None:
    fourth = coordinator.route(recall(target="threat", attempt=4), state_with_three_attempts())
    assert fourth.status == "limited"
```

- [ ] **Step 2: 运行并确认当前系统只记录 recall**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_recall_state_machine.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现再调路由**

优先 `target_agent_id`，否则按 capability tag 从当前选中 agent 匹配；无匹配时生成 `AgentRecommendation` 并把 gate 降级为 limited。Recall task 只包含缺口、已有证据索引和 return node，不携带完整 winning session。

- [ ] **Step 4: 运行再调测试**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_recall_state_machine.py -q`

Expected: PASS。

- [ ] **Step 5: 验证轮次与恢复节点**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_recall_state_machine.py -q -k "limit or return_node"`

Expected: PASS。

### Task 5: 生成九字段文字能力画像

**Files:**
- Create: `src/equipment_deep_research/orchestration/winning/capability.py`
- Test: `tests/equipment_deep_research/unit/test_capability_image.py`

**Interfaces:**
- Consumes: L1/L2/L3 对象和 GapMatrix。
- Produces: `CapabilityImageBuilder.build()`、`CapabilityImageItem.validate_traceability()`。

- [ ] **Step 1: 写失败测试**

```python
def test_capability_image_has_nine_fields_and_functional_text() -> None:
    item = builder.build(valid_l3_draft())[0]
    item.validate()
    assert item.capability_type in {"new_capability", "upgrade"}
    assert any(word in item.capability_image for word in ["具备", "支持", "能够", "实现"])
    assert item.source_winning_logic
    assert item.related_scenario
    assert item.evidence_ids

def test_new_and_upgrade_items_are_separated() -> None:
    items = builder.build(mixed_drafts())
    assert {item.capability_type for item in items} == {"new_capability", "upgrade"}
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_capability_image.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现去重、分类和排序**

按功能目标、任务对象和效果链节点去重；类型来源规则为 L2 创新方向/新组合 -> `new_capability`，现有装备差距 -> `upgrade`。优先级依据关键性、紧迫性、可行性各 1-5 分，并保留分数依据。

- [ ] **Step 4: 运行画像测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_capability_image.py -q`

Expected: PASS。

- [ ] **Step 5: 验证文字画像不依赖图形输出**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_capability_image.py -q -k textual`

Expected: PASS。

### Task 6: 完成制胜机理 E2E

**Files:**
- Modify: `src/equipment_deep_research/orchestration/runner.py`
- Create: `tests/equipment_deep_research/e2e/test_winning_mechanism_e2e.py`
- Create: `docs/testing/phase-6-test-report.md`

**Interfaces:**
- Consumes: Phase 5 packets、四类资源、六步推理、gates、recall、capability builder。
- Produces: 完整 stage objects、recall history、capability images。

- [ ] **Step 1: 写 E2E 测试**

测试必须断言：六步对象均存在；L1/L2/L3 顺序正确；首次 L1 触发 recall；目标 agent 回传后 L1 通过；能力画像含新能力和升级；每条能力可追溯到 evidence。

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/e2e/test_winning_mechanism_e2e.py -q`

Expected: FAIL。

- [ ] **Step 3: 接入总 runner**

runner 在 baseline reduce 后构建 resource pack，运行 winning engine；遇 recall 暂停 stage，调用 scheduler，提交新 packet，再从 return node 恢复。

- [ ] **Step 4: 运行 E2E 和全量测试**

Run: `python3 -m pytest tests/equipment_deep_research/e2e/test_winning_mechanism_e2e.py -q`

Expected: PASS。

- [ ] **Step 5: 生成 Phase 6 审查包**

Run: `python3 -m pytest -q`

Expected: 全部 PASS；报告附一条完整“EvidenceCard -> packet -> L1 -> L2 -> L3 -> capability”追溯链和一次真实再调 trace。
