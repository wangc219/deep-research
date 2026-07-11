# Phase 1 Task 5 实施报告

## 交付结论

Task 5 已将 checkpoint 恢复接入现有 runner/CLI，并保持 Phase 1 不伪造 Phase 2 真实模型能力。

## 实现摘要

- 新增稳定 `RunCheckpoint`，保存 run/task 状态、round、budget、topic/route/agents、source materials、worker reports、配置指纹、resume count、UTC 时间和 schema。
- `SqliteRunStore` 支持 `RunCheckpoint`，并提供领域对象读取用于恢复；`DomainStore` 可恢复 problem/evidence/packet/recall/recommendation/stage/image/audit/report。
- 新增 `RunWorkspace.open_existing()`，拒绝缺失、类型错误、顶层 symlink 和 root 外逃逸。
- 新增 `RecoveryManager.load(run_id)`：先处理 reconciliation marker，再恢复最后 checkpoint、领域态、trace、来源材料、worker report 与 session tail；topic/route/agents/config 不匹配明确失败。
- runner baseline agents 改为逐 agent 执行。task 开始保存 `running` checkpoint；task 完成时新增 evidence、packet、trace 和 completed task checkpoint 原子提交。
- runner 构造器允许注入兼容 `AgentProvider`，用于 crash 测试；异常继续传播，之前已提交状态保持可恢复。
- resume 只重排 pending/running task，跳过 completed；追加 `run_resumed`，继续 winning/report。completed resume 不调用 provider，不新增 DB/session/trace。
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
12 passed

python3 -m pytest \
  tests/equipment_deep_research/e2e/test_resume_run.py \
  tests/equipment_deep_research/integration/test_agent_harness.py -q
41 passed

python3 -m pytest -q
205 passed
```

## Smoke

fresh CLI smoke：`status=completed`、4 sessions、4 evidence、16 DB domain objects；七类产物、`run.db`、checkpoint snapshots 与 `latest.json` 齐全。

crash+resume smoke：第一 agent savepoint 后第二 provider 调用抛出；resume 未重复第一 agent，仅执行剩余 agent；最终 evidence 唯一、`run_resumed=1`、completed checkpoint 与七类产物齐全。

## 文档

- 新增 `docs/testing/phase-1-test-report.md`，记录 schema、session、崩溃点、恢复结果、测试和真实 provider 未接入边界。
- 更新 README、技术方案和验收说明，从 Phase 0 的 resume 预留状态切换到 Phase 1 当前实现。
- Phase 1 Task 2 Ruff 证据范围更正为目标文件范围，不表述为全仓库 Ruff。

## 关注点

- 当前恢复粒度是现有顺序 baseline agent 与 winning/report 闭环，不宣称真正并行或分布式恢复。
- checkpoint JSON 文件是审计快照，SQLite `run.db` 是恢复权威来源。
- `RealAgentProvider` 仍为模板占位，真实模型循环和真实搜索属于 Phase 2。
