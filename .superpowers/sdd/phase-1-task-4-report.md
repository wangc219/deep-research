# Phase 1 Task 4 实施报告

## 结论

已实现 `AgentHarness`、深冻结 `TurnSnapshot`、原子预算账本和逐调用
`ToolAuthorizationPolicy`。实现保持 `AgentLoop` 的无领域状态边界：loop、provider 和
tool handler 均不接触 store/session，harness 通过 `prepare_turn` 与 typed loop event
完成快照、session 时序和逐轮事务提交。

## 稳定接口

- `AgentHarness.execute(task) -> AgentExecutionResult`
- `AgentHarness.set_next_turn_tools(names)`：仅在下一次 `prepare_turn` 消费，不修改已
  开始的 snapshot。
- `AgentHarness.on_event(callback)`：返回 unsubscribe；普通 listener 异常及 listener
  自行抛出的 `CancelledError` 被隔离并计数，调用方真实取消继续传播。回调实际订阅
  harness 接受或创建的 `EventBus`，不存在第二条 RuntimeEvent 发布通道。
- `EventBus` 隔离 `CancelledError`、`GeneratorExit` 等非进程级 `BaseException`；
  `KeyboardInterrupt/SystemExit` 在当前 run queue 完成清理/交棒后重抛。每个 delivery 的
  completion 与 drainer state 均在 finally/空队列临界区完成，listener 失败不会使后续
  publisher 永久等待。
- `Budget`：支持 `max_turns`、`max_tool_calls`、`max_seconds`、`max_tokens`；未知键
  显式 `ValueError`，非整数 turn/tool/token 和负数/非有限值被拒绝。
- `ToolAuthorizationPolicy.authorize()`：同时检查 active tool allowlist、required read
  scopes 和 required write scopes；scope 映射可注入覆盖，未覆盖项保留默认映射。
- `ToolAuthorizationPolicy.authorize_result()`：真实 handler 返回后逐项校验 domain proposal
  object type，并重建受控 actor/tool identity 的 trace proposal。
- 旧 `ToolPermissionRegistry.default()`、`validate_agent_tools()`、
  `enforce_active_tool()` API 原样保留。

`AgentExecutionResult` 包含 `execution_id/task_id/agent_id/status/output_refs/
evidence_ids/checkpoint_id/error/snapshots/created_at/schema_version`。snapshot 包含
`snapshot_id/turn_index/message_refs/context_hash/active_tool_names/model_name/
model_options/budget_remaining/created_at/schema_version`，所有 sequence/mapping 深冻结。

## Snapshot 与哈希

- 每个实际开始的 turn 在 `AgentLoop.prepare_turn` 中创建并持久化 snapshot。
- `message_refs` 对每条 `ModelMessage.to_plain()` 使用 sorted-key、无 NaN、紧凑分隔符
  的 canonical strict JSON 后计算 SHA-256，不依赖 Python `hash()`。
- `context_hash` 对完整 provider message context 使用同一 canonical strict JSON 算法。
- provider 可见 tools/options 与结果 snapshot 来源于同一 prepared input；下一轮工具
  切换只会在下一次 prepare 时生成新的 wrapper definitions。
- snapshot 中的预算余额是 turn 原子预扣后的值；token usage 在 assistant event 后原子
  记录，因此已开始 snapshot 不会被后续 usage 或配置变化改写。

## 权限与预算

默认写 scope：

- `create_evidence_card -> EvidenceCard`
- `write_stage_output -> WinningMechanismStageOutput`
- `create_recall_request -> RecallRequest`
- `create_capability_image -> CapabilityImageItem`
- `write_audit -> AuditResult`
- `write_report -> ResearchReport`

`search_sources` / `fetch_page` 不读取 domain store，因此默认无 object scope 且不允许
domain write；Phase 2 可通过构造参数注入 custom tool 的 read/write requirement 与
`allowed_write_types`。

每轮 prepare 对候选 active tools 逐个授权，只向 provider 暴露当前 task scopes 下可调用
的子集；一个未授权候选不会阻断其他合法候选，只有原 active set 全部不可授权时才在
provider 前传播 `PermissionError`。每个 wrapper 在真实 handler 前再次检查 allowlist、
read/write scopes 并原子消耗 tool-call budget；传给 handler 的新
`ToolExecutionContext.permissions` 来自当前 snapshot，而不是 AgentLoop 初始 context。

handler 返回后执行第二层授权：每个 `DomainWriteProposal.object_type` 必须同时存在于
task `object_write_scopes` 和该工具 `allowed_write_types`。任一违规会丢弃整个 result、
传播 `PermissionError`，不产生 tool_result session event，不进入 pending 或 store。
`TraceProposal` 可写，但 actor 强制为当前 agent，payload 中 `tool_name/tool_call_id` 由
harness 覆盖，工具不能伪造调用身份。

预算达到上限时，下一次 turn admission 返回 `budget_exhausted`。`max_seconds` 同时使用
monotonic admission 检查和 `asyncio.wait_for` wall-clock 限制；超时取消内部 loop、写入
当前 turn 的 harness trace/savepoint，再以 `budget_exhausted` 完成任务。

## Session 与事务时序

正常工具轮严格为：

```text
task_received
-> turn_snapshot
-> assistant_message
-> tool_result (provider call order) x N
-> savepoint_pending(turn, canonical batch hash)
-> SqliteRunStore.commit(domain proposals, tool traces, harness trace)
-> savepoint
-> ... next turn ...
-> task_completed
```

- `ToolResult` proposal 只在对应 `turn_end` 后按轮批量提交。
- 每个正常 turn 至少加入一条 `harness_turn` trace proposal；provider 失败、超时和取消
  若已开始 turn 但没有 `turn_end`，只提交 terminal harness trace，不提交未到
  `turn_end` 的 tool proposals。
- `savepoint_pending` 在 commit 前写 session，保存 turn、canonical strict JSON batch hash
  和 proposal counts；`savepoint` 仅在 store commit 成功后写 session。
- commit 失败不会进入下一 provider turn，也不会伪造 savepoint。若 DB commit 已成功但
  session `savepoint` append 失败，harness 立即向 DB 提交 `session_write_failed` trace，
  记录原 committed checkpoint、batch hash、turn、session event 和
  `recovery_status="reconcile_required"`，并使执行失败。
- handler 仅收到 `ToolCall` 与 `ToolExecutionContext`，不会获得 store。
- session 使用 `JsonlSessionStore(path, root_dir=trusted_sessions_root)`；任务正文、assistant
  正文和 tool result 正文只保存稳定引用/安全 projection。敏感 key 递归替换为
  `<redacted>`；`context_refs/evidence_refs` 只写 count 和 SHA-256 ref IDs。所有 session
  字符串与 external event payload 共用公共 `sanitize_runtime_payload()`，覆盖敏感 key、
  access token/API key/token/password/secret/cookie 字符串、URL query credentials、Bearer、
  PEM private key 和统一截断。terminal session error 使用安全类别文案，result/external
  terminal error 也经过同一 sanitizer。

### RecoveryManager 识别规则

1. `SqliteRunStore.unresolved_session_writes(agent_id, task_id)` 在当前 run trace 中配对
   `session_write_failed` 与 `session_reconciled` marker；`recover()` 同时返回
   `unresolved_session_writes`，包含 marker/checkpoint/batch/turn/task/agent/execution/
   session ref 和 trace sequence。
2. `AgentHarness.execute()` 创建当前 session 后、写 `task_received` 前查询同 run/agent/task
   未解决 marker。若 marker 缺少稳定字段或原 session 不可读写，执行返回 failed，provider
   不启动。
3. 对每个 marker，harness 打开受 trusted sessions root 约束的原 `session_ref`。若缺失
   matching savepoint，追加 `recovered=true` 的 savepoint；若缺失 session-level
   `session_reconciled`，再追加该记录。已有部分记录会被识别，不重复追加。
4. session 修补完成后提交确定性 proposal id 的 `session_reconciled` trace；其 payload
   包含 marker/checkpoint/batch/turn/task/agent/session ref 和
   `recovery_status="reconciled"`。store 查询据此关闭 marker。
5. 若 session 行已写但 trace commit 失败，下一次启动只重试幂等 trace；若 trace 已提交，
   后续启动不再打开原 session，不重复行或 trace。领域 proposal 永不重放。

此闭环只消费 session write marker，不恢复 pending task、messages、预算或 provider turn，
未提前实现 Task 5。

失败策略：provider/loop/store/session 普通失败返回 `AgentExecutionResult(status="failed")`
并尽力追加 `task_failed`；权限拒绝先追加安全 `task_failed` 再传播 `PermissionError`；
调用方 `CancelledError` 在尽力写 terminal trace/savepoint 和 `task_cancelled` 后原样传播。

## RED / GREEN

初始 RED：

```text
python3 -m pytest tests/equipment_deep_research/integration/test_agent_harness.py -q
ModuleNotFoundError: No module named 'equipment_deep_research.harness.agent_harness'
```

listener 取消策略补充 RED：

```text
1 failed, 17 passed
CancelledError: listener-only
```

修复后聚焦结果：

```text
25 passed
```

审查修复 RED 首次运行：`10 failed, 14 passed`，分别复现候选工具整轮拒绝、恶意 domain
proposal 入库、动态 context 过期、EventBus 未接入、trace identity 可伪造、原始 refs
泄漏、缺少 savepoint pending/reconciliation marker。公共 sanitizer RED 为 import error。

覆盖 snapshot 深不可变/下一轮切换、scope/provider/handler 拒绝、混合候选过滤、返回后
proposal 授权、trace identity、动态 context、EventBus sequence/脱敏、逐调用预算、并发
tool-call 原子消费、token usage、wall-clock timeout、proposal 批量提交、savepoint
pending/commit/reconciliation、session 脱敏、external listener 隔离、稳定结果 schema 和
取消传播。

第二次复审 RED：EventBus `CancelledError` 直接逃逸，`SystemExit` 后 drainer 残留使 sequence
2 不派发；reconciliation restart 测试因 `recover()` 缺少 unresolved marker 查询失败。
GREEN 后 listener error 计数、fatal rethrow/cleanup、跨实例自动 session 修补、domain 不重放、
重复启动幂等和 session 持续不可写 provider=0 均有回归覆盖。

## 验证证据

```text
python3 -m pytest tests/equipment_deep_research/integration/test_agent_harness.py -q
25 passed

python3 -m pytest tests/equipment_deep_research -q -k "permission or scope or snapshot"
6 passed, 160 deselected

python3 -m pytest tests/test_deep_research_runner.py -q
23 passed

python3 -m pytest -q
189 passed

ruff check src/equipment_deep_research/harness/event_bus.py \
  src/equipment_deep_research/harness/agent_harness.py \
  src/equipment_deep_research/harness/agent_loop.py \
  src/equipment_deep_research/tools/permissions.py \
  tests/equipment_deep_research/unit/test_runtime_types.py \
  tests/equipment_deep_research/integration/test_agent_harness.py
All checks passed!

python3 -m compileall -q src/equipment_deep_research
exit 0

git diff --check
exit 0
```

依赖扫描无命中：

```text
rg -n "equipment_deep_research\.(orchestration|interfaces)|DomainStore|TraceStore" \
  src/equipment_deep_research/harness/budget.py \
  src/equipment_deep_research/harness/agent_harness.py \
  src/equipment_deep_research/harness/event_bus.py \
  src/equipment_deep_research/tools/permissions.py

rg -n "store" \
  src/equipment_deep_research/tools/definitions.py \
  src/equipment_deep_research/harness/agent_loop.py
```

## 自审与关注点

- 审查修复额外修改公共 `event_bus.py` sanitizer、`agent_loop.py` 的 PermissionError 传播和
  对应 runtime tests；未回退其他工作。
- `AgentHarness` 明确为 single-flight 实例；并发 task 应使用独立 harness 实例，避免
  `set_next_turn_tools` 在执行间串扰。
- 未配置 `max_turns` 时保留 loop 的 64-turn 防失控上限；显式 task budget 达限使用
  `budget_exhausted`，而不是 `max_turns`。
- 真实 provider token usage 依赖 `total_tokens`，或 input/output、prompt/completion token
  字段；未知 usage 字段不会猜测计费。
- 原子修复提交主题：`fix: harden agent harness authorization and recovery`；实际提交哈希在
  最终回复中报告，避免报告自引用改变提交内容。
