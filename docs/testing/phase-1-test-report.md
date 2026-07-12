# Phase 1 Harness 与恢复测试报告

## 1. 范围

本报告覆盖 Phase 1 的 runtime types、append-only session、事务型 SQLite savepoint、agent loop/harness、session reconciliation，以及 Task 5 的 runner/CLI checkpoint 恢复接入。

当前 Phase 1 不接入 Phase 2 的真实 `ModelProvider`、真实 Responses 模型循环或真实搜索 provider。runner 继续使用现有高层 `FakeAgentProvider` / `RealAgentProvider` 闭环；`RealAgentProvider` 仍是受控 URL 材料化占位实现。

## 2. SQLite Schema 与 RunCheckpoint

`run.db` 继续使用四张表：

- `domain_objects`：按 `(run_id, object_type, object_id)` 保存严格 JSON 领域对象。
- `trace_events`：保存 run 内单调 sequence、proposal ID、event type、actor 和严格 JSON payload。
- `savepoints`：保存事务 ordinal、request fingerprint、proposal keys 和 UTC 时间。
- `proposal_ledger`：保存 proposal ID 与 domain idempotency key 的内容 hash，用于幂等和冲突拒绝。

Task 5 将 `RunCheckpoint` 加入受支持领域类型，固定对象 ID 为单 run 的稳定 workflow checkpoint，按 savepoint upsert 最新快照。字段包括：

- run status、completed/pending task IDs 与每个 task 的 `pending/running/completed` 状态；
- baseline tasks 加显式 `finalize:winning-report` task；round index、剩余 round/baseline/finalize task budget；
- topic、请求路线、解析路线、selected agents 和 mode；
- source materials、worker reports、resume count；
- agents/presets/providers/evidence 配置内容与运行参数形成的 SHA-256 指纹；
- UTC `created_at` 与 `schema_version="1.0"`。

初始事务同时保存 `ResearchProblem`、初始 `RunCheckpoint` 和 `run_started`。每个 baseline agent 完成时，新增 `EvidenceCard`、`BaselineFindingPacket`、`TraceEvent` 与新 `RunCheckpoint` 在同一个 SQLite savepoint 中提交。最后一个 baseline 完成后 finalize 仍为 pending、run 仍为 running；进入 engine 前先提交 finalize running。L1/L2/L3、capability images、recommendations、audit、report、相关 trace、finalize completed 与 run completed checkpoint 在同一个最终事务中提交。

## 3. Session 与 Checkpoint 样例

baseline session 只追加，不覆盖旧行。典型尾记录为：

```json
{"event_type":"baseline_result","agent_id":"international_situation","packet_id":"packet-international_situation","evidence_ids":["ev-international_situation-1"]}
{"event_type":"savepoint","agent_id":"international_situation","checkpoint_id":"checkpoint-...","packet_id":"packet-international_situation"}
```

Harness 继续使用兼容接口 `JsonlSessionStore(path, root_dir=...)`。runner/recovery 使用 `JsonlSessionStore(run_id/agent_sessions/session_ref, anchor_dir=canonical_output_root)`，从不可变锚逐组件 no-follow 打开，不把可变 `agent_sessions.resolve()` 当信任根。若数据库已提交但 runner/harness session savepoint 写入失败，runner 自动提交含 agent/task/checkpoint/batch/session ref 的 `session_write_failed` marker 并传播原异常。恢复先消费 marker：补写 `recovered=true` savepoint、追加 `session_reconciled`，再提交同 marker 的幂等 reconciliation trace。`session_reconciled` 的 trace sequence 必须早于本次 `run_resumed`。

项目自有 `SecureArtifactStore` 保持旧 store 的 `kind:sha256[:16]` ref、content 文件扩展名和 metadata 字段。runner 的全部材料化 artifact 通过 `RunWorkspace` 从 run dirfd 进入 `artifacts/`。所有 `report/json/domain/trace/checkpoint latest/history/artifact` 写入均由 rooted dirfd writer 完成：逐组件拒绝 symlink，临时文件使用 `O_EXCL|O_NOFOLLOW`，写入后 fsync 文件，以同一 parent dirfd 原子 rename 并 fsync 目录。缺少安全原语时 fail closed。

## 4. 崩溃注入与恢复结果

E2E 使用构造器注入兼容 `AgentProvider`。第一 agent 正常完成并提交 savepoint，第二次 provider 调用抛出 `InjectedCrash`，异常向调用方传播。

崩溃后数据库保持：

- 1 个 `EvidenceCard`；
- 1 个 `BaselineFindingPacket`；
- 1 个最新 `RunCheckpoint`，第一 task completed、第二 task running、其余 pending；
- 第一 agent session 已追加 result/savepoint。

恢复时：

1. `RunWorkspace.open_existing()` 验证 run 目录、sessions、artifacts、checkpoints 和 `run.db` 均在输出根内且不是逃逸 symlink。
2. session reconciliation 先完成。
3. `RecoveryManager.load()` 从最后 savepoint 和 `RunCheckpoint` 恢复 `DomainStore`、`TraceStore`、source materials、worker reports 与 session tails。
4. `running` 归一为 `pending`，按原 selected agent 顺序继续；completed task 和已提交 idempotency key 不重放。
5. 无论 checkpoint 是 running 还是 completed，resume 都先提交一次 `run_resumed` 与新 savepoint；running 继续未完成 baseline/finalize，completed 无条件从 SQLite 恢复态重写稳定输出后返回。

恢复结果验证：首 agent 未重复调用，旧 session 字节前缀不变；剩余 agent 完成；evidence IDs 无重复；最后 baseline 后崩溃时 finalize pending，engine 后最终事务前崩溃时 finalize running，二者恢复后均执行 finalize 且不重复 domain/trace；completed resume 不启动 provider但会增加 `run_resumed` trace/savepoint，并刷新 `trace.jsonl`、`round_summary.json` 及其余稳定输出。topic、路线、agent 集合、配置指纹、持久化 `ResearchProblem`、不存在 run、损坏 SQLite 和 symlink workspace 均校验；source materials 与 worker reports 恢复时去重。artifact/session 目录在初始化或 `open_existing()` 后被替换为 symlink 时，后续写入在外部文件产生前失败。

## 5. 测试与 Smoke

专项测试：

```text
python3 -m pytest tests/equipment_deep_research/e2e/test_resume_run.py -q
24 passed

python3 -m pytest \
  tests/equipment_deep_research/e2e/test_resume_run.py \
  tests/equipment_deep_research/integration/test_agent_harness.py -q
53 passed
```

核心回归：

```text
python3 -m pytest tests/test_deep_research_runner.py \
  tests/equipment_deep_research/integration/test_cli_workspace.py \
  tests/equipment_deep_research/unit/test_configuration.py \
  tests/equipment_deep_research/unit/test_domain_contracts.py \
  tests/equipment_deep_research/unit/test_http_transport.py -q
99 passed
```

全量：

```text
python3 -m pytest -q
229 passed
```

最终 no-follow stat race 补强后的受影响范围：

```text
python3 -m pytest tests/equipment_deep_research/integration/test_cli_workspace.py \
  -q -k 'atomic_writer or secure_primitives or safe_stat'
8 passed

python3 -m pytest tests/equipment_deep_research/e2e/test_resume_run.py \
  tests/equipment_deep_research/unit/test_domain_contracts.py -q
33 passed
```

第二轮材料化与 Phase 0 fresh 回归：

```text
python3 -m pytest -q tests/equipment_deep_research/unit/test_http_transport.py \
  tests/equipment_deep_research/unit/test_secure_artifacts.py \
  tests/test_deep_research_runner.py
52 passed

python3 -m pytest -q tests/equipment_deep_research/unit/test_domain_contracts.py \
  tests/equipment_deep_research/unit/test_configuration.py \
  tests/equipment_deep_research/integration/test_cli_workspace.py \
  tests/test_deep_research_runner.py
72 passed
```

fresh smoke：`status=completed`、`ResearchProblem=1`、finalize completed、3 stage、1 report，七类产物、`run.db` 和 completed checkpoint 齐全。

crash/resume smoke 覆盖三窗口：第二 agent 调用崩溃、最后 baseline 后崩溃、engine 后最终事务前崩溃。恢复分别只执行剩余 baseline 或仅 finalize；最终 domain/trace key 唯一、`run_resumed=1`、checkpoint completed、七类稳定产物齐全。completed resume 额外验证 provider 调用为 0 且 `run_resumed=1`。

## 6. Ruff 范围更正

Phase 1 Task 2 报告中的 Ruff 结论是目标文件范围，不是全仓库 Ruff 证明。准确范围为当时修改的 `domain/store.py`、`harness/session.py` 与对应 Task 2 测试；Task 5 使用显式 touched-file Ruff 命令，并另行执行全量 pytest、compileall、`git diff --check` 和依赖/残留扫描。

## 7. 仍未接入

- Phase 2 真实 `ModelProvider`、Responses API 模型循环与真实搜索 provider。
- 真正并行 baseline 调度、暂停、取消、分布式 worker 和跨进程队列恢复。
- `evidence.yaml` 驱动的运行时质量评分、去重、独立印证和冲突推理。
- Web/API/SSE、权限、审批和企业部署。
