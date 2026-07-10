# Phase 3 上下文治理与智能体差异化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通过 ContextProjector、对象 scope、摘要压缩和 working checkpoint，让不同 agent 只看到完成自身任务所需的信息，并在多轮研究中保持高信息密度。

**Architecture:** 原始领域对象留在 store，agent 输入只包含对象引用和投影摘要。ContextProjector 按 agent policy、task scope 和 token budget 生成不可变 `ContextPack`；压缩时必须保留证据索引、开放问题、冲突和 checkpoint。

**Tech Stack:** dataclasses、JSON、token 估算、pytest。

## Global Constraints

- baseline agent 不能读取其他 agent 原始消息或 session。
- 制胜机理 agent 只能看到已接纳 packet、证据索引、coverage、冲突和 checkpoint。
- reporter 不能看到原始网页正文，只看到证据卡和能力画像引用。
- 压缩不得删除 evidence id、claim id、open question、coverage limit 或 recall 状态。

---

### Task 1: 重构 ContextPack 与可见性矩阵

**Files:**
- Rewrite: `src/equipment_deep_research/harness/context.py`
- Create: `configs/equipment_deep_research/context_policies.yaml`
- Test: `tests/equipment_deep_research/unit/test_context_visibility.py`

**Interfaces:**
- Produces: `ContextPack`、`ContextPolicy`、`ContextProjector.project(task, agent, store)`。

- [ ] **Step 1: 写失败测试**

```python
def test_baseline_agent_cannot_see_other_raw_sessions(store, registry) -> None:
    store.put_raw_session("combat_scenario", [{"role": "assistant", "content": "secret"}])
    pack = projector.project(task_for("international_situation"), registry.get("international_situation"), store)
    serialized = json.dumps(pack.sections, ensure_ascii=False)
    assert "secret" not in serialized
    assert "raw_sessions" not in pack.sections

def test_winning_agent_receives_handoff_not_raw_messages(store, registry) -> None:
    seed_packet_and_session(store)
    pack = projector.project(task_for("winning_mechanism"), registry.get("winning_mechanism"), store)
    assert pack.sections["baseline_packets"][0]["handoff_summary"]
    assert "messages" not in pack.sections["baseline_packets"][0]
```

- [ ] **Step 2: 运行并确认旧 context builder 不满足测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_context_visibility.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现投影规则**

`ContextPolicy` 包含 `visible_sections`、`visible_object_types`、`field_masks`、`max_items_per_section`、`token_budget`、`hide_raw_sessions`。投影顺序为 task 固有约束 -> policy -> object read scope -> field mask -> 数量限制 -> token 压缩。

- [ ] **Step 4: 运行可见性测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_context_visibility.py -q`

Expected: PASS。

- [ ] **Step 5: 输出默认可见性快照**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_context_visibility.py -q -k snapshot`

Expected: PASS，fixture 明确列出四类 baseline、制胜机理、审计、报告 agent 的 section。

### Task 2: 实现 WorkingCheckpoint 和研究状态摘要

**Files:**
- Modify: `src/equipment_deep_research/domain/models.py`
- Create: `src/equipment_deep_research/harness/checkpoint.py`
- Test: `tests/equipment_deep_research/unit/test_working_checkpoint.py`

**Interfaces:**
- Produces: `WorkingCheckpoint`、`CheckpointManager.update()`、`CheckpointManager.project_for_agent()`。

- [ ] **Step 1: 写失败测试**

```python
def test_checkpoint_preserves_progress_open_questions_and_next_actions() -> None:
    checkpoint = WorkingCheckpoint(
        checkpoint_id="cp-1", agent_id="weapon_equipment", round_index=2,
        completed_steps=["检索现有型号"], accepted_evidence_ids=["ev-1"],
        rejected_lead_ids=["lead-9"], open_questions=["抗干扰参数范围？"],
        conflicts=["公开口径不一致"], next_actions=["检索试验报告"],
        return_node="equipment_compare",
    )
    restored = WorkingCheckpoint.from_dict(checkpoint.to_dict())
    assert restored == checkpoint
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_working_checkpoint.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现 checkpoint 对象和 merge 规则**

更新必须追加完成步骤、去重证据和问题；状态只能按 `pending -> active -> completed|limited|failed` 转移；`return_node` 只能被当前 task 或 recall 修改。

- [ ] **Step 4: 运行 checkpoint 测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_working_checkpoint.py -q`

Expected: PASS。

- [ ] **Step 5: 接入 save point 回归**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_store_savepoint.py -q -k checkpoint`

Expected: PASS。

### Task 3: 实现 token 预算与保真压缩

**Files:**
- Create: `src/equipment_deep_research/harness/compaction.py`
- Modify: `src/equipment_deep_research/harness/context.py`
- Test: `tests/equipment_deep_research/unit/test_context_compaction.py`

**Interfaces:**
- Produces: `estimate_tokens()`、`ContextCompactor.compact(pack, budget)`、`CompactionRecord`。

- [ ] **Step 1: 写失败测试**

```python
def test_compaction_keeps_domain_index_and_drops_low_value_repetition() -> None:
    pack = oversized_context_pack(repeated_notes=50, evidence_ids=["ev-1", "ev-2"], open_questions=["q1"])
    compacted, record = ContextCompactor().compact(pack, token_budget=500)
    text = json.dumps(compacted.sections, ensure_ascii=False)
    assert estimate_tokens(compacted) <= 500
    assert "ev-1" in text and "ev-2" in text and "q1" in text
    assert record.removed_item_count > 0
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_context_compaction.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现分层压缩策略**

优先保留：task constraints、recall、checkpoint、open questions、coverage、conflicts、evidence/claim ids。其次保留高质量 evidence 摘要和最新发现。先去重，再裁剪低分材料，最后按 section 生成确定性摘要；压缩记录写入 trace。

- [ ] **Step 4: 运行压缩测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_context_compaction.py -q`

Expected: PASS。

- [ ] **Step 5: 验证压缩确定性**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_context_compaction.py -q -k deterministic`

Expected: 相同输入生成相同 hash 和 CompactionRecord。

### Task 4: 把 ContextProjector 接入 Harness

**Files:**
- Modify: `src/equipment_deep_research/harness/agent_harness.py`
- Modify: `src/equipment_deep_research/harness/session.py`
- Test: `tests/equipment_deep_research/integration/test_context_harness_integration.py`
- Create: `docs/testing/phase-3-test-report.md`

**Interfaces:**
- Consumes: `ContextProjector`、`ContextCompactor`、`WorkingCheckpoint`。
- Produces: 每轮 `TurnSnapshot.context_hash` 和 session `context_projection` 记录。

- [ ] **Step 1: 写失败集成测试**

```python
@pytest.mark.asyncio
async def test_each_agent_gets_distinct_context_hash_for_same_topic(runtime) -> None:
    situation = await runtime.execute(task_for("international_situation"))
    equipment = await runtime.execute(task_for("weapon_equipment"))
    assert situation.snapshots[0].context_hash != equipment.snapshots[0].context_hash
    assert "equipment_parameters" not in situation.projected_sections
    assert "strategic_context" not in equipment.projected_sections
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_context_harness_integration.py -q`

Expected: FAIL。

- [ ] **Step 3: 接入每轮投影和压缩**

Harness 在 turn snapshot 前调用 projector；下一轮如 store 发生变化，重新投影，但当前 snapshot 不变。session 只记录 section 名、对象引用、token 数和 hash，不重复写完整敏感上下文。

- [ ] **Step 4: 运行集成与全量测试**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_context_harness_integration.py tests/equipment_deep_research/unit/test_context_visibility.py -q`

Expected: PASS。

- [ ] **Step 5: 生成 Phase 3 审查包**

Run: `python3 -m pytest -q`

Expected: 全部 PASS；报告附可见性矩阵、两个 baseline agent 的 context diff、压缩前后 token 数和保留索引证明。
