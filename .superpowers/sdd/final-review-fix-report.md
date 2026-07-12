# Phase 0 最终整体审查修复报告

## 状态

DONE

## 修复提交

- 实现与测试：`7d5de5eae711f96e77ea3d4663623538a969c91a` (`fix: harden phase 0 persistence boundaries`)

## 变更文件

- `src/equipment_deep_research/domain/identifiers.py`
- `src/equipment_deep_research/domain/models.py`
- `src/equipment_deep_research/domain/workspace.py`
- `src/equipment_deep_research/agents/registry.py`
- `src/equipment_deep_research/harness/scheduler.py`
- `tests/equipment_deep_research/unit/test_domain_contracts.py`
- `tests/equipment_deep_research/unit/test_configuration.py`
- `tests/equipment_deep_research/integration/test_cli_workspace.py`
- `tests/test_deep_research_runner.py`
- `README.md`
- `docs/TECHNICAL_SCHEME.md`
- `docs/ACCEPTANCE.md`
- `docs/testing/phase-0-test-report.md`
- `.superpowers/sdd/final-review-fix-report.md`

## 设计与实现

### 1. agent_id 路径边界

- 新增复用函数 `validate_internal_identifier()`：最长 128 字符，首字符必须为 ASCII 字母或数字，后续仅允许 ASCII 字母、数字、点、下划线和连字符。
- 明确拒绝空值、`.`、`..`、绝对路径、正反斜杠、控制字符、非 ASCII 字符和超长值。
- `AgentRegistry.load()` 在接受 YAML 配置时校验。
- scheduler 在构造 session 文件路径时调用 `safe_identifier_path()` 再次校验，并确认 session 父目录与候选路径未通过 symlink 逃逸。
- 已存在的 session 文件 symlink 在 provider 调用和文件写入前抛出 `ValueError`。

### 2. run_id 复用污染

- `RunWorkspace.create()` 使用 `run_dir.mkdir(exist_ok=False)` 原子抢占 run 目录。
- 已存在的空目录、非空目录、普通文件或 symlink 均由同一原子语义拒绝。
- 子目录只在 run 目录成功独占后创建，不再对旧目录使用 `exist_ok=True`。
- 集成测试连续两次使用相同 `run_id`，第二次改用单 agent 子集；第二次在任何写入前失败，第一次的七类产物、目录集合和所有文件字节保持不变。
- `resume=True` 仍在 workspace 创建前抛出既有 `NotImplementedError("resume is enabled in Phase 1")`。

### 3. 完整版本契约

- 为 `EvidenceCard`、`RecallRequest`、`AgentRecommendation`、`WinningMechanismStageOutput`、`CapabilityImageItem`、`AuditResult`、`ResearchReport`、`TraceEvent` 追加尾部默认字段 `schema_version="1.0"`。
- `BaselineFindingPacket` 保留既有 schema 字段和位置兼容性。
- `ResearchProblem` 追加默认工厂生成的 `problem_id` 与 schema，保留 UTC `created_at` 和旧第五位置参数语义。
- `WorkerReport` 确认写入 `round_summary.json`，因此追加默认工厂生成的 `worker_report_id`、UTC `created_at` 和 schema。
- `AgentRunRequest`、`AgentRunResult`、`ContextPack`、`PresetPolicy` 等仅内部临时对象未扩张。
- 单元测试对每种持久化对象执行 `to_plain()`、`json.dumps()`、稳定 ID、UTC 时间和 schema 断言；旧位置和关键字构造继续通过。
- fake E2E 实际解析 `domain.jsonl`、`trace.jsonl` 和 `round_summary.json`，验证落盘 payload，而非只检查 dataclass 内存状态。

## TDD 证据

RED：

```text
python3 -m pytest -q tests/equipment_deep_research/unit/test_domain_contracts.py tests/equipment_deep_research/unit/test_configuration.py tests/equipment_deep_research/integration/test_cli_workspace.py tests/test_deep_research_runner.py
.......FF...FFFFFFF.........FFF.........FF..................FF.          [100%]
16 failed, 47 passed in 0.43s
```

失败分别命中缺失 `problem_id`/schema、registry 未拒绝恶意 agent ID、工作区复用、fake E2E 缺少版本字段，以及 scheduler 未执行二次路径和 symlink 校验。

GREEN：

```text
python3 -m pytest -q tests/equipment_deep_research/unit/test_domain_contracts.py tests/equipment_deep_research/unit/test_configuration.py tests/equipment_deep_research/integration/test_cli_workspace.py tests/test_deep_research_runner.py
................................................................         [100%]
64 passed in 0.35s
```

## 定向测试原始结果

```text
python3 -m pytest -q tests/equipment_deep_research/unit/test_domain_contracts.py
.........                                                                [100%]
9 passed in 0.06s
```

```text
python3 -m pytest -q tests/equipment_deep_research/unit/test_configuration.py
............                                                             [100%]
12 passed in 0.02s
```

```text
python3 -m pytest -q tests/equipment_deep_research/integration/test_cli_workspace.py
....................                                                     [100%]
20 passed in 0.11s
```

```text
python3 -m pytest -q tests/test_deep_research_runner.py
.......................                                                  [100%]
23 passed in 0.26s
```

## 全量测试

```text
python3 -m pytest -q
........................................................................ [ 79%]
...................                                                      [100%]
91 passed in 0.36s
```

编译检查：

```text
python3 -m compileall -q src/equipment_deep_research tests/equipment_deep_research tests/test_deep_research_runner.py
```

结果：零输出，退出码 0。

## 严格残留扫描

退役配置和行为：

```text
rg -n "gpt-5\.6-sol|source_whitelist|allowed_domains|blocked_unapproved_source" src/equipment_deep_research scripts configs/equipment_deep_research tests/equipment_deep_research tests/test_deep_research_runner.py
```

结果：零输出，退出码 1；`rg` 无匹配时返回 1，符合预期。

旧不安全路径构造：

```text
rg -n "f\"\{agent\.agent_id\}\.jsonl\"|session_path = self\.sessions_dir /|run_dir\.mkdir\([^\n]*exist_ok=True|for path in \(run_dir" src/equipment_deep_research
```

结果：零输出，退出码 1，符合预期。

`git diff --check`：零输出，退出码 0。

## 随机 /tmp Smoke

命令：

```text
python3 scripts/run_deep_research.py --mode fake --topic 低空无人机探测预警能力缺口 --research-route auto --run-id phase-0-smoke --output-root /tmp/equipment-deep-research-phase-0-final.ScfUWB
```

原始结果：

```text
Run dir: /tmp/equipment-deep-research-phase-0-final.ScfUWB/phase-0-smoke
Route: traditional_gap
Audit status: approved
Report: /tmp/equipment-deep-research-phase-0-final.ScfUWB/phase-0-smoke/report.md
Capability images: /tmp/equipment-deep-research-phase-0-final.ScfUWB/phase-0-smoke/capability_images.json
Summary: /tmp/equipment-deep-research-phase-0-final.ScfUWB/phase-0-smoke/round_summary.json
```

复核结果：

- 七类稳定产物齐全：`report.md`、`capability_images.json`、`round_summary.json`、`domain.jsonl`、`trace.jsonl`、`agent_sessions/`、`artifacts/`。
- 4 个 agent session；4 份正文和 4 份 metadata artifact。
- `checkpoints/` 存在且为空；`run.db` 不存在。
- `domain.jsonl`：4 EvidenceCard、4 BaselineFindingPacket、3 WinningMechanismStageOutput、2 CapabilityImageItem、1 AuditResult、1 ResearchReport；全部 schema `1.0` 且 ID 非空。
- `trace.jsonl`：11 条 TraceEvent；全部 schema `1.0`、event ID 非空、UTC 时间。
- `round_summary.json`：4 个 worker 均 `completed`；ResearchProblem 和 4 个 WorkerReport 均有稳定 ID、UTC 时间和 schema `1.0`。

## 自审

- 范围仅覆盖用户授权的领域模型、工作区、registry、scheduler、相关测试和事实同步文档；未回退或改写其他提交。
- 兼容性：所有新增 dataclass 字段均位于既有字段之后并提供默认值；旧位置和关键字构造有自动化覆盖。
- 路径安全：配置入口和文件路径出口采用同一标识符函数；run 目录使用原子独占创建；现有 symlink 不会被跟随写入。
- 持久化事实：版本测试同时覆盖内存投影和三个真实落盘输出，避免只验证构造器。
- Phase 0 边界未扩张：未实现 resume、SQLite、真实模型循环或运行时证据质量评分。

## 关注点

- 无阻断关注点。
- `FileExistsError` 现在是 `resume=False` 同名 run 目录冲突的明确失败信号；调用方需要为每次新运行提供唯一 `run-id`。

## 最终复审证据修正

- 在当前 HEAD `ef3b07cf389647fd2dffbfd7f86a0f9627818983` 精确重跑四个指定测试文件，原始结果为 `64 passed in 0.35s`。
- 先前较小的组合测试计数产生于追加 129 字符超长 `agent_id` 配置用例之前，现已全部修正为当前 HEAD 的精确结果。
- 本轮仅修正文档证据，未修改实现，按要求未重跑 smoke 或全量测试。
- 本文档提交哈希：`<DOCUMENTATION_COMMIT_SHA>`。该值由包含本文档的提交生成，无法在同一提交内容中自引用回填；实际哈希以最终回复和 `git log -1 --format=%H` 为准。

## Phase 1 最终整体审查修复

### 修复范围

- AgentLoop 对 timeout、外部取消与 sibling failure 采用有限 grace drain；不合作 tool task 被 quarantine，并在完成时消费异常。
- AgentHarness 在取消开始时关闭 execution gate，隔离迟到 provider/tool callback；zero timeout 直接过期，subsecond deadline 保持精度；harness loop task 同样有有限 drain/quarantine。
- 每个 execution 及 reconciliation session 都在 `finally` 关闭；`last_session_store` 不再暴露已关闭 handle。`JsonlSessionStore` 的 path-lock entry 以 owner refcount 管理，最后 owner 关闭后移除。
- EventBus 对 SQLite store 绑定 durable runtime sequence allocator；旧数据库首次迁移以 trace high-water 作为兼容下界，之后 runtime high-water 与 trace sequence 独立推进。
- custom `project_root` 可省略 Phase 2 的 `providers.yaml`/`evidence.yaml`；文件缺失是确定 fingerprint 输入，后续出现文件会安全地拒绝 resume。

### 威胁与耐久性合同

trusted root 的前提是当前 UID 控制且非 shared-writable。实现不声称抵御恶意同 UID 进程持续竞速 `mkdir`/`open` 私有 namespace。SQLite 的单一持久 connection 与 committed SQLite state 是运行权威；安全 workspace 使用 MEMORY journal/no-sidecar，不提供 WAL 等价的 process-kill 或 power-loss durability。

### 精确验证证据

```text
python3 -m pytest -q tests/equipment_deep_research/integration/test_agent_harness.py
39 passed in 0.40s

python3 -m pytest -q tests/equipment_deep_research/unit/test_agent_loop.py
25 passed in 0.20s

python3 -m pytest -q tests/equipment_deep_research/unit/test_runtime_types.py tests/equipment_deep_research/unit/test_store_savepoint.py
67 passed in 0.12s

python3 -m pytest -q tests/equipment_deep_research/unit -k budget
1 passed, 141 deselected in 0.04s

python3 -m pytest -q tests/equipment_deep_research/e2e/test_resume_run.py
29 passed in 0.81s

python3 -m pytest -q tests/equipment_deep_research/integration/test_cli_workspace.py
45 passed in 0.24s

python3 -m pytest -q
278 passed in 1.98s
```

- Scoped Ruff: `All checks passed!`.
- `python3 -m compileall -q src/equipment_deep_research tests`: zero output, exit 0.
- `git diff --check`: zero output, exit 0.
- 本地 security scan 未发现 dynamic execution、shell subprocess、unsafe YAML/pickle 或 TLS-verification bypass API。
- `codex --help` 成功；`codex review --uncommitted` 因 workspace sandbox 不允许向外部服务发送未提交代码而未执行，属于唯一外部审查限制。
- Fresh 和 completed-resume CLI smoke 均返回 `Status: completed`。completed resume 的 checkpoint 为 `completed`、`resume_count=1`；trace 中 `run_resumed=1`、`baseline_agent_completed=4`；七类稳定产物、`run.db` 和 checkpoints 齐全，且无 `run.db-wal`、`run.db-shm` 或 rollback-journal sidecar。

## Phase 1 最后两项修复续作（2026-07-12）

### 状态

DONE

最终实现提交哈希无法在同一提交内容中自引用，精确 SHA 见最终回复与 `git log -1 --format=%H`。

### 修复内容

- 新增 `runtime_event_state(run_id, last_sequence)`，`SqliteRunStore.allocate_runtime_event_sequence()` 使用 `BEGIN IMMEDIATE` 原子分配。多个 store/EventBus 实例并发 publish 时 SQLite 串行化分配，不产生重复 sequence。
- 旧 `run.db` 缺少新表时，以该 run 已有 trace high-water 初始化一次；已有 runtime state 不会因后续 trace commit 或 reopen 被抬升，避免混淆 TraceEvent 与 RuntimeEvent sequence。
- `AgentHarness` 优先把 EventBus 绑定到 store 的 durable allocator；只有不提供 allocator 的兼容 store 才保留旧 trace seed fallback。
- 外部 async listener 在父任务取消时统一 cancel，并在 `0.1s` grace 内 drain；仍未完成的 task 进入 quarantine，done callback 消费迟到结果/异常，不向 event loop 泄漏未处理异常。
- listener task 从收到 cancel 前即进入 mutation-blocked 集合，并在 grace drain/quarantine 全程保持；其调用 `set_next_turn_tools()` 会被拒绝，即使新的 harness execution 已开始。listener outcome 不再回写 harness error state。execution `finally` 在返回前关闭 session，测试直接验证 root fd 已失效。

### TDD RED 证据

```text
python3 -m pytest -q tests/equipment_deep_research/integration/test_agent_harness.py tests/equipment_deep_research/unit/test_store_savepoint.py
ERROR tests/equipment_deep_research/integration/test_agent_harness.py
ImportError: cannot import name 'EXTERNAL_LISTENER_CANCELLATION_GRACE_SECONDS'
1 error in 0.08s
```

```text
python3 -m pytest -q tests/equipment_deep_research/unit/test_store_savepoint.py
3 failed, 45 passed in 0.12s
```

三个失败分别命中缺失 `EventBus.bind_sequence_allocator()`、`SqliteRunStore.last_runtime_event_sequence()` 与 `SqliteRunStore.allocate_runtime_event_sequence()`。

最终边界自审追加 RED：listener 抑制 `CancelledError` 后在 grace 窗口立即调用 `set_next_turn_tools()`，原实现出现 `1 failed in 0.21s`；在 cancel 前标记 mutation-blocked 后，该用例 `1 passed in 0.14s`。

### 精确定向与回归结果

```text
python3 -m pytest -q tests/equipment_deep_research/integration/test_agent_harness.py::test_new_harness_bus_continues_after_all_prior_runtime_events tests/equipment_deep_research/integration/test_agent_harness.py::test_trace_commits_do_not_reseed_runtime_event_sequence tests/equipment_deep_research/integration/test_agent_harness.py::test_parent_cancellation_is_bounded_for_resistant_early_listener tests/equipment_deep_research/integration/test_agent_harness.py::test_parent_cancellation_is_bounded_for_resistant_terminal_listener tests/equipment_deep_research/integration/test_agent_harness.py::test_cooperative_async_listener_still_observes_terminal_event tests/equipment_deep_research/unit/test_store_savepoint.py::test_concurrent_event_buses_allocate_unique_durable_runtime_sequences tests/equipment_deep_research/unit/test_store_savepoint.py::test_runtime_sequence_state_migrates_existing_database_and_survives_reopen tests/equipment_deep_research/unit/test_store_savepoint.py::test_runtime_sequence_allocation_does_not_change_domain_trace_atomicity
8 passed in 0.29s
```

```text
python3 -m pytest -q tests/equipment_deep_research/integration/test_agent_harness.py
43 passed in 0.67s

python3 -m pytest -q tests/equipment_deep_research/unit/test_agent_loop.py
25 passed in 0.19s

python3 -m pytest -q tests/equipment_deep_research/unit/test_runtime_types.py tests/equipment_deep_research/unit/test_store_savepoint.py
70 passed in 0.11s

python3 -m pytest -q tests/equipment_deep_research/unit -k budget
1 passed, 144 deselected in 0.04s

python3 -m pytest -q tests/equipment_deep_research/e2e/test_resume_run.py
29 passed in 0.79s

python3 -m pytest -q tests/equipment_deep_research/integration/test_cli_workspace.py
45 passed in 0.24s

python3 -m pytest -q
285 passed in 2.18s
```

### 静态检查与扫描

```text
python3 -m ruff check src/equipment_deep_research/domain/store.py src/equipment_deep_research/harness/event_bus.py src/equipment_deep_research/harness/agent_harness.py tests/equipment_deep_research/integration/test_agent_harness.py tests/equipment_deep_research/unit/test_store_savepoint.py
All checks passed!
```

- `python3 -m compileall -q src/equipment_deep_research tests`：零输出，退出码 0。
- `git diff --check`：零输出，退出码 0。
- dynamic execution、shell subprocess、unsafe YAML/pickle、TLS verification bypass API 扫描：零匹配，`rg` 退出码 1，符合预期。

### Fresh 与 Completed-Resume Smoke

workspace：`tmp/phase-1-final-two-fixes.BXHeni`。

```text
python3 scripts/run_deep_research.py --mode fake --topic 低空无人机探测预警能力缺口 --research-route auto --run-id phase-1-final-two-fixes --output-root tmp/phase-1-final-two-fixes.BXHeni
Status: completed

python3 scripts/run_deep_research.py --mode fake --topic 低空无人机探测预警能力缺口 --research-route auto --run-id phase-1-final-two-fixes --output-root tmp/phase-1-final-two-fixes.BXHeni --resume
Status: completed
```

- completed checkpoint：`status=completed`、`resume_count=1`，五个 task 均在 `completed_task_ids`。
- SQLite trace：`baseline_agent_completed=4`、`run_resumed=1`、`last_trace_sequence=12`。
- CLI 路径未发布 RuntimeEvent，因此独立的 `runtime_event_state.last_sequence=0`，证明 reopen/resume 未以 trace sequence 持续抬升 runtime high-water。
- `report.md`、`capability_images.json`、`round_summary.json`、`domain.jsonl`、`trace.jsonl`、四个 agent session、八个 artifact 文件、`run.db` 与 checkpoint history 齐全。
- 未发现 `run.db-wal`、`run.db-shm` 或 `run.db-journal` sidecar。

### 关注点

- 无阻断关注点。
- runtime sequence 分配与 RuntimeEvent payload 的持久化仍是两个不同合同：本轮保证 durable high-water 和无重复分配，不新增 RuntimeEvent 表或 SSE replay 存储。
