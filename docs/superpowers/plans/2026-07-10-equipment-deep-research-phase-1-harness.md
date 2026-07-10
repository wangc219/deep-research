# Phase 1 通用 Harness 与存储恢复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现可供所有智能体复用的 AgentLoop/Harness，具备 turn snapshot、逐调用权限、proposal/save point、append-only session、预算和断点恢复。

**Architecture:** `AgentLoop` 只处理 provider 消息和工具调用；`AgentHarness` 持有上下文、预算、权限、session 和 save point。领域写入先形成 proposal，再由 SQLite 事务提交并导出 JSONL，避免并发 worker 直接修改共享状态。

**Tech Stack:** asyncio、sqlite3、JSONL、pytest-asyncio（加入依赖）。

## Global Constraints

- `AgentLoop` 不得导入 orchestration 或制胜机理模块。
- 每个 agent run 使用独立 session 文件。
- turn 开始后上下文、工具和模型配置冻结到该轮结束。
- 工具不得直接写 `DomainStore`。
- 每次 save point 要么完整提交 domain/trace proposal，要么全部回滚。
- RuntimeEvent 必须具有 run 内单调递增 sequence，支持 Phase 8 SSE 持久化和断线补发。
- session 原文不通过 API 暴露，后续 Web 只读取脱敏事件、对象引用和 checkpoint 摘要。

---

### Task 1: 定义运行时消息、工具和事件内核

**Files:**
- Create: `src/equipment_deep_research/tools/definitions.py`
- Create: `src/equipment_deep_research/harness/events.py`
- Create: `src/equipment_deep_research/harness/event_bus.py`
- Create: `src/equipment_deep_research/domain/proposals.py`
- Test: `tests/equipment_deep_research/unit/test_runtime_types.py`

**Interfaces:**
- Produces: `ToolCall`、`ToolResult`、`ToolDefinition`、`RuntimeEvent`、`EventBus.publish()`、`DomainWriteProposal`、`TraceProposal`。

- [ ] **Step 1: 写失败测试**

```python
def test_event_bus_redacts_credentials_and_truncates_payload() -> None:
    bus = EventBus(max_string_length=32)
    seen = []
    bus.subscribe(seen.append)
    bus.publish(RuntimeEvent("tool", "called", "run-1", payload={
        "authorization": "Bearer secret", "text": "x" * 100,
    }))
    assert seen[0].payload["authorization"] == "<redacted>"
    assert seen[0].payload["text"].endswith("<truncated>")

def test_tool_result_keeps_domain_and_trace_proposals_separate() -> None:
    domain = DomainWriteProposal("p1", "EvidenceCard", "upsert", {"evidence_id": "ev-1"}, "ev-1")
    trace = TraceProposal("t1", "evidence_created", "agent-a", {"evidence_id": "ev-1"})
    result = ToolResult(call_id="c1", content="ok", domain_proposals=[domain], trace_proposals=[trace])
    assert len(result.domain_proposals) == 1
    assert len(result.trace_proposals) == 1
```

- [ ] **Step 2: 运行并确认导入失败**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_runtime_types.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现最小运行时类型**

```python
@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[ToolCall, ToolExecutionContext], Awaitable[ToolResult]]

@dataclass(frozen=True)
class DomainWriteProposal:
    proposal_id: str
    object_type: str
    operation: Literal["upsert", "append"]
    payload: dict[str, Any]
    idempotency_key: str

@dataclass(frozen=True)
class TraceProposal:
    proposal_id: str
    event_type: str
    actor: str
    payload: dict[str, Any]
```

- [ ] **Step 4: 运行单元测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_runtime_types.py -q`

Expected: PASS。

- [ ] **Step 5: 检查内核依赖方向**

Run: `rg -n "equipment_deep_research\.orchestration" src/equipment_deep_research/harness src/equipment_deep_research/tools/definitions.py`

Expected: 无结果。

### Task 2: 实现 append-only session 与事务型 save point

**Files:**
- Create: `src/equipment_deep_research/harness/session.py`
- Rewrite: `src/equipment_deep_research/domain/store.py`
- Test: `tests/equipment_deep_research/unit/test_store_savepoint.py`

**Interfaces:**
- Consumes: `DomainWriteProposal`、`TraceProposal`。
- Produces: `JsonlSessionStore.append()`、`SqliteRunStore.commit()`、`SqliteRunStore.recover()`、`SqliteRunStore.export_domain_jsonl()`、`SqliteRunStore.export_trace_jsonl()`。

- [ ] **Step 1: 写失败测试覆盖事务与幂等**

```python
def test_savepoint_is_atomic_and_idempotent(tmp_path: Path) -> None:
    store = SqliteRunStore(tmp_path / "run.db", run_id="run-1")
    domain = [DomainWriteProposal("p1", "EvidenceCard", "upsert", {"evidence_id": "e1"}, "e1")]
    trace = [TraceProposal("t1", "evidence_saved", "agent-a", {"evidence_id": "e1"})]
    checkpoint_1 = store.commit(domain, trace)
    checkpoint_2 = store.commit(domain, trace)
    assert checkpoint_1 == checkpoint_2
    assert store.count("EvidenceCard") == 1
    assert store.trace_count() == 1

def test_invalid_object_rolls_back_whole_savepoint(tmp_path: Path) -> None:
    store = SqliteRunStore(tmp_path / "run.db", run_id="run-1")
    with pytest.raises(StoreValidationError):
        store.commit([valid_evidence, invalid_packet], [trace])
    assert store.object_count() == 0
    assert store.trace_count() == 0
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_store_savepoint.py -q`

Expected: FAIL。

- [ ] **Step 3: 建立 SQLite schema 和提交算法**

```sql
CREATE TABLE IF NOT EXISTS domain_objects (
  run_id TEXT NOT NULL,
  object_type TEXT NOT NULL,
  object_id TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (run_id, object_type, object_id)
);
CREATE TABLE IF NOT EXISTS trace_events (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  proposal_id TEXT NOT NULL UNIQUE,
  event_type TEXT NOT NULL,
  actor TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS savepoints (
  checkpoint_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  proposal_keys_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

`commit()` 使用 `BEGIN IMMEDIATE`，先校验所有 proposal，再写领域对象、trace 和 savepoint，异常时 rollback。

- [ ] **Step 4: 运行存储测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_store_savepoint.py -q`

Expected: PASS。

- [ ] **Step 5: 验证 JSONL 导出可被逐行解析**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_store_savepoint.py -q -k export`

Expected: PASS，每行是一个合法 JSON 对象。

### Task 3: 实现无领域状态 AgentLoop

**Files:**
- Create: `src/equipment_deep_research/providers/base.py`
- Create: `src/equipment_deep_research/harness/agent_loop.py`
- Test: `tests/equipment_deep_research/unit/test_agent_loop.py`

**Interfaces:**
- Consumes: `ModelProvider.stream(messages, tools, options)`、`ToolDefinition`。
- Produces: `AgentLoop.run(messages, provider, tools, config) -> AgentLoopResult`。

- [ ] **Step 1: 写失败测试覆盖工具顺序和无工具终止**

```python
@pytest.mark.asyncio
async def test_loop_executes_parallel_calls_but_appends_results_in_call_order() -> None:
    provider = ScriptedProvider([
        assistant_with_calls([call("c1", "slow"), call("c2", "fast")]),
        assistant_text("done"),
    ])
    result = await AgentLoop().run([user("start")], provider, [slow_tool, fast_tool], config())
    tool_messages = [m for m in result.messages if m.role == "tool"]
    assert [m.tool_call_id for m in tool_messages] == ["c1", "c2"]
    assert result.turn_count == 2
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_agent_loop.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现循环**

循环顺序固定为：冻结本轮输入 -> provider stream -> 收集 assistant message -> 并发执行工具 -> 按 call 顺序追加结果 -> 发出 `turn_end` -> 下一轮。达到 `max_turns`、预算停止或 assistant 无工具调用时结束。

- [ ] **Step 4: 运行 AgentLoop 测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_agent_loop.py -q`

Expected: PASS。

- [ ] **Step 5: 检查 AgentLoop 不持有 store/session**

Run: `rg -n "DomainStore|SqliteRunStore|SessionStore|ResearchRoute" src/equipment_deep_research/harness/agent_loop.py`

Expected: 无结果。

### Task 4: 实现 AgentHarness、turn snapshot 和逐调用权限

**Files:**
- Create: `src/equipment_deep_research/harness/budget.py`
- Create: `src/equipment_deep_research/harness/agent_harness.py`
- Rewrite: `src/equipment_deep_research/tools/permissions.py`
- Test: `tests/equipment_deep_research/integration/test_agent_harness.py`

**Interfaces:**
- Consumes: `TaskEnvelope`、`AgentLoop`、`SqliteRunStore`、`JsonlSessionStore`。
- Produces: `AgentHarness.execute(task) -> AgentExecutionResult`、`TurnSnapshot`、`ToolAuthorizationPolicy.authorize()`。

- [ ] **Step 1: 写失败测试覆盖 snapshot 和 scope**

```python
@pytest.mark.asyncio
async def test_active_tool_change_applies_next_turn_only(harness) -> None:
    first = asyncio.Event()
    harness.on_event(lambda event: first.set() if event.event_type == "turn_started" else None)
    task_run = asyncio.create_task(harness.execute(task(allowed_tools=["search_sources"])))
    await first.wait()
    harness.set_next_turn_tools(["fetch_page"])
    result = await task_run
    assert result.snapshots[0].active_tool_names == ["search_sources"]
    assert result.snapshots[1].active_tool_names == ["fetch_page"]

@pytest.mark.asyncio
async def test_tool_write_scope_is_enforced_before_handler(harness, spy_handler) -> None:
    with pytest.raises(PermissionError):
        await harness.execute(task(object_write_scopes=["BaselineFindingPacket"], allowed_tools=["create_evidence_card"]))
    spy_handler.assert_not_called()
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_agent_harness.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现 Harness**

`TurnSnapshot` 必须冻结：`message_refs`、`context_hash`、`active_tool_names`、`model_name`、`model_options`、`budget_remaining`。工具返回的 proposal 在 `turn_end` 后交给 `store.commit()`；session 依次追加 `task_received`、`turn_snapshot`、`assistant_message`、`tool_result`、`savepoint`、`task_completed`。

- [ ] **Step 4: 运行 Harness 测试**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_agent_harness.py -q`

Expected: PASS。

- [ ] **Step 5: 执行权限拒绝专项回归**

Run: `python3 -m pytest tests/equipment_deep_research -q -k "permission or scope or snapshot"`

Expected: PASS。

### Task 5: 实现 checkpoint 恢复并接入 runner

**Files:**
- Create: `src/equipment_deep_research/harness/recovery.py`
- Modify: `src/equipment_deep_research/orchestration/runner.py`
- Modify: `src/equipment_deep_research/interfaces/cli.py`
- Test: `tests/equipment_deep_research/e2e/test_resume_run.py`
- Create: `docs/testing/phase-1-test-report.md`

**Interfaces:**
- Consumes: `SqliteRunStore.recover()`、`RunWorkspace`。
- Produces: `RecoveryManager.load(run_id)`、可执行 `--resume`。

- [ ] **Step 1: 写中断恢复失败测试**

```python
def test_resume_continues_after_last_committed_savepoint(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, provider=CrashAfterFirstSavepointProvider())
    with pytest.raises(InjectedCrash):
        runner.run(mode="fake", topic="恢复测试", research_route="new_winning_mechanism", run_id="resume-1")
    resumed = build_runner(tmp_path, provider=CompletingProvider()).run(
        mode="fake", topic="恢复测试", research_route="new_winning_mechanism",
        run_id="resume-1", resume=True,
    )
    rows = read_domain_rows(Path(resumed["run_dir"]) / "domain.jsonl")
    assert len([row for row in rows if row["type"] == "EvidenceCard"]) == 1
    assert resumed["status"] == "completed"
```

- [ ] **Step 2: 运行并确认恢复尚未实现**

Run: `python3 -m pytest tests/equipment_deep_research/e2e/test_resume_run.py -q`

Expected: FAIL，显示 Phase 0 的 `NotImplementedError`。

- [ ] **Step 3: 实现恢复规则**

恢复时读取最后 savepoint、已完成 task、各 agent session 尾记录和预算；只重新排队 `pending/running` task，不重复已提交 idempotency key。追加 `run_resumed` trace 事件，不改写旧 session 行。

- [ ] **Step 4: 运行恢复与全量测试**

Run: `python3 -m pytest tests/equipment_deep_research/e2e/test_resume_run.py tests/equipment_deep_research/integration/test_agent_harness.py -q`

Expected: PASS。

- [ ] **Step 5: 生成 Phase 1 审查包**

Run: `python3 -m pytest -q`

Expected: 全部 PASS；测试报告记录 SQLite schema、session 示例、崩溃注入点、恢复结果和仍未接入的真实 provider。
