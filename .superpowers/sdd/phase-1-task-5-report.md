# Phase 1 Task 5 实施报告

## 交付结论

Task 5 已将 checkpoint 恢复接入现有 runner/CLI，并保持 Phase 1 不伪造 Phase 2 真实模型能力。

## 实现摘要

- 新增稳定 `RunCheckpoint`，保存 run/task 状态、round、budget、topic/route/agents、source materials、worker reports、配置指纹、resume count、UTC 时间和 schema。
- `SqliteRunStore` 支持 `RunCheckpoint`，并提供领域对象读取用于恢复；`DomainStore` 可恢复 problem/evidence/packet/recall/recommendation/stage/image/audit/report。
- 新增 `RunWorkspace.open_existing()`，拒绝缺失、类型错误、顶层 symlink 和 root 外逃逸。
- 新增 `RecoveryManager.load(run_id)`：先处理 reconciliation marker，再恢复最后 checkpoint、领域态、trace、来源材料、worker report 与 session tail；topic/route/agents/config 不匹配明确失败。
- runner baseline agents 改为逐 agent 执行。task 开始保存 `running` checkpoint；task 完成时新增 evidence、packet、trace 和 completed task checkpoint 原子提交。
- 初始事务持久化 `ResearchProblem`，checkpoint 显式包含 `finalize:winning-report`；最后 baseline 后 finalize 保持 pending，engine 前提交 finalize running，最终领域对象与 finalize/run completed checkpoint 同事务提交。
- runner 构造器允许注入兼容 `AgentProvider`，用于 crash 测试；异常继续传播，之前已提交状态保持可恢复。
- resume 只重排 pending/running task，跳过 completed baseline；running finalize 会重新执行。completed resume 也先追加 `run_resumed` trace/savepoint，但不调用 provider。
- scheduler 使用 rooted `JsonlSessionStore`。DB commit 后 session savepoint 失败会自动提交 `session_write_failed` marker；恢复补 recovered savepoint 与幂等 `session_reconciled` 后才跳过 completed task。
- `RunWorkspace` 新增 dirfd 原子 writer，最终输出和 checkpoint latest/history 不再裸写；leaf symlink、检查后替换和缺失安全原语均 fail closed。
- 正常完成将 winning/report 领域对象、trace 与 completed checkpoint 写入 `run.db`，继续输出七类稳定产物，result 增加 `status=completed`。
- CLI 的 `--resume` 已实际执行恢复；输出增加 status，同时兼容旧式 runner 测试替身未返回 status 的情况。

## RED / GREEN

初始 RED：

```text
python3 -m pytest tests/equipment_deep_research/e2e/test_resume_run.py -q
ModuleNotFoundError: No module named 'equipment_deep_research.harness.recovery'
```

GREEN：

```text
python3 -m pytest tests/equipment_deep_research/e2e/test_resume_run.py -q
21 passed

python3 -m pytest \
  tests/equipment_deep_research/e2e/test_resume_run.py \
  tests/equipment_deep_research/integration/test_agent_harness.py -q
50 passed

python3 -m pytest -q
222 passed

最终安全 stat race 补强后：workspace writer/stat 8 passed；resume E2E + domain contracts 30 passed。
```

## 第二轮审查修复

- 新增项目自有 `SecureArtifactStore`，保持旧 `ArtifactStore` 的 content-addressed ref、扩展名和 metadata schema；runner 的 `EvidenceMaterializer` 通过 `RunWorkspace` 从 run dirfd 逐组件打开 `artifacts/`，不再裸写 artifact 路径。
- `JsonlSessionStore` 新增显式 `anchor_dir`，同时保留 Harness 使用的 `path + root_dir` 接口。runner/recovery 以 canonical output root 为锚，逐组件 no-follow 打开 `run_id/agent_sessions/session_ref`，不再把可变 `agent_sessions.resolve()` 当信任根。
- completed resume 在提交 `run_resumed` 后，无条件使用 SQLite 恢复的 domain/trace/checkpoint 状态安全重写五个稳定文件；`trace.jsonl` payload 与数据库 trace payload 保持一致，provider 调用仍为 0。
- 新增 artifact/session ancestor 替换 TOCTOU、reconciliation 外写阻断、安全原语缺失、SecureArtifactStore 兼容 metadata、completed resume 陈旧文件与审计链刷新测试。

本轮 fresh 结果：resume E2E `24 passed`；resume E2E + Harness `53 passed`；材料化/安全 artifact `52 passed`；Phase 0 组合 `72 passed`；全量 `229 passed`。

## Smoke

fresh smoke：`status=completed`、ResearchProblem=1、finalize completed、stage=3、report=1；七类产物、`run.db`、checkpoint snapshots 与 `latest.json` 齐全。

crash+resume smoke 覆盖 agent 中途、最后 baseline 后、engine 后最终事务前三个窗口。恢复分别只执行剩余 baseline 或仅 finalize；domain/trace key 唯一、`run_resumed=1`、completed checkpoint 与七类产物齐全。completed resume provider=0 且仍写审计 trace/savepoint。

## 文档

- 新增 `docs/testing/phase-1-test-report.md`，记录 schema、session、崩溃点、恢复结果、测试和真实 provider 未接入边界。
- 更新 README、技术方案和验收说明，从 Phase 0 的 resume 预留状态切换到 Phase 1 当前实现。
- Phase 1 Task 2 Ruff 证据范围更正为目标文件范围，不表述为全仓库 Ruff。

## 关注点

- 当前恢复粒度是现有顺序 baseline agent 与 winning/report 闭环，不宣称真正并行或分布式恢复。
- checkpoint JSON 文件是审计快照，SQLite `run.db` 是恢复权威来源。
- 安全 artifact/session 路径依赖 `O_NOFOLLOW`、`O_DIRECTORY` 与 dirfd 操作；平台缺少这些原语时明确 fail closed。
- `RealAgentProvider` 仍为模板占位，真实模型循环和真实搜索属于 Phase 2。
