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
  自行抛出的 `CancelledError` 被隔离并计数，调用方真实取消继续传播。
- `Budget`：支持 `max_turns`、`max_tool_calls`、`max_seconds`、`max_tokens`；未知键
  显式 `ValueError`，非整数 turn/tool/token 和负数/非有限值被拒绝。
- `ToolAuthorizationPolicy.authorize()`：同时检查 active tool allowlist、required read
  scopes 和 required write scopes；scope 映射可注入覆盖，未覆盖项保留默认映射。
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

`search_sources` / `fetch_page` 不读取 domain store，因此默认无 object scope；Phase 2 可
通过构造参数注入 custom tool 的 read/write requirement。每轮在 provider 前预检全部
active tools，scope 缺失时 provider 和 handler 均不执行并可传播 `PermissionError`；
每个 wrapper handler 在真实 handler 前再次授权并原子消耗 tool-call budget。

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
-> SqliteRunStore.commit(domain proposals, tool traces, harness trace)
-> savepoint
-> ... next turn ...
-> task_completed
```

- `ToolResult` proposal 只在对应 `turn_end` 后按轮批量提交。
- 每个正常 turn 至少加入一条 `harness_turn` trace proposal；provider 失败、超时和取消
  若已开始 turn 但没有 `turn_end`，只提交 terminal harness trace，不提交未到
  `turn_end` 的 tool proposals。
- `savepoint` 仅在 store commit 成功后写 session；commit 失败不会进入下一 provider
  turn，也不会伪造 savepoint。
- handler 仅收到 `ToolCall` 与 `ToolExecutionContext`，不会获得 store。
- session 使用 `JsonlSessionStore(path, root_dir=trusted_sessions_root)`；任务正文、assistant
  正文和 tool result 正文只保存稳定引用/安全 projection。敏感 key 递归替换为
  `<redacted>`，terminal session error 使用安全类别文案，不保存 provider/store 原始错误。

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
18 passed in 0.09s
```

覆盖 snapshot 深不可变/下一轮切换、scope/provider/handler 拒绝、allowlist、逐调用预算、
并发 tool-call 原子消费、token usage、wall-clock timeout、proposal 批量提交、savepoint
顺序、commit 失败、session 脱敏、external listener 隔离、稳定结果 schema 和取消传播。

## 验证证据

```text
python3 -m pytest tests/equipment_deep_research -q -k "permission or scope or snapshot"
4 passed, 152 deselected

python3 -m pytest tests/test_deep_research_runner.py -q
23 passed

python3 -m pytest -q
179 passed

ruff check <owned implementation/test files>
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
  src/equipment_deep_research/tools/permissions.py

rg -n "store" \
  src/equipment_deep_research/tools/definitions.py \
  src/equipment_deep_research/harness/agent_loop.py
```

## 自审与关注点

- 仅修改任务所有权文件、允许的 `domain/messages.py` 兼容接口及本报告，未回退其他工作。
- `AgentHarness` 明确为 single-flight 实例；并发 task 应使用独立 harness 实例，避免
  `set_next_turn_tools` 在执行间串扰。
- 未配置 `max_turns` 时保留 loop 的 64-turn 防失控上限；显式 task budget 达限使用
  `budget_exhausted`，而不是 `max_turns`。
- 真实 provider token usage 依赖 `total_tokens`，或 input/output、prompt/completion token
  字段；未知 usage 字段不会猜测计费。
- 原子提交主题：`feat: add agent harness snapshots and authorization`；实际提交哈希在最终
  回复中报告，避免报告自引用改变提交内容。
