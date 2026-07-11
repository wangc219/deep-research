# Phase 0/Phase 1 基础验收说明

## 1. 验收范围

当前验收对象是可运行、可回归、可审计、可从已提交 checkpoint 恢复的研究基线，包括三类研究路线、可配置 baseline agent、受控公开 URL 材料化、失败材料隔离、L1/L2/L3 输出、安全工作区、SQLite savepoint 和稳定产物。这仍不等于甲方首版完成。

真实模型循环和真实搜索尚未接入。Web/API、真正并行调度、分布式 worker 和生产部署不属于本阶段完成项。

## 2. 必验能力

### 2.1 路线与 Agent

- 三条研究路线均可在 `fake` 模式完成端到端运行。
- 默认运行四个 registry baseline agent：国际形势、作战场景、武器装备、作战运用。
- `--agents` 可运行任意子集；缺失能力标签必须进入 summary 和报告限制说明。
- 自定义配置可替换默认 baseline agent，runner 不依赖固定 agent ID 分支。
- 每个所选 agent 生成独立 session 文件。
- `agent_id` 必须符合受限 ASCII 内部标识符契约；路径分隔符、绝对路径、`.`、`..`、控制字符和超长值必须在 registry 入站时拒绝，scheduler 构造 session 路径时必须再次校验并拒绝已存在 symlink。

### 2.2 模型与 Provider

- 默认模型配置精确为 `gpt-5.5`。
- `fake` provider 提供稳定离线验证数据。
- Phase 0 `real` provider 仍为模板占位，只验证受控 URL 材料化和证据治理边界。
- 不得把 `providers.yaml` 中的 Responses-compatible 配置描述为已经执行真实模型循环。

### 2.3 公开材料与正式证据

- 公开来源不按域名设置准入门槛。
- URL、DNS、IP、重定向、响应大小和 TLS 安全控制由材料化层强制执行。
- SSRF/网络安全拒绝和抓取失败材料必须隔离；成功抓取的材料当前会进入 `EvidenceCard` 和 baseline packet。
- `fetch_failed`、`network_safety_rejected` 等失败材料必须保留诊断 artifact，但不得进入正式 evidence IDs。
- `evidence.yaml` 已定义质量阈值和相关性、透明度、时效性、直接支撑、提取质量五维权重，但 runner 尚未加载执行质量评分。
- Phase 0 不验收运行时质量阈值门控；该能力属于甲方首版后续进入条件。
- 公网不可达时允许 `real` smoke 降级，不得伪造抓取成功。

### 2.4 产物与工作区

每个成功运行目录必须包含七类稳定产物：

- `report.md`
- `capability_images.json`
- `round_summary.json`
- `domain.jsonl`
- `trace.jsonl`
- `agent_sessions/`
- `artifacts/`

同时必须创建 `run.db` 与 `checkpoints/`，正常完成必须写入 completed `RunCheckpoint`。`resume=False` 不得复用任何已存在的同名 run 目录；第二次同 `run-id` 必须在写入前失败，旧产物和 session 保持不变。

### 2.5 恢复

- 每个 baseline agent 完成后，新增 `EvidenceCard`、`BaselineFindingPacket`、`TraceEvent` 与最新 `RunCheckpoint` 必须在一个 SQLite savepoint 中提交。
- 崩溃后 `--resume` 必须跳过 completed agent，仅继续 pending/running agent，且不得重复 evidence、packet、session 前缀或 idempotency key。
- 恢复前必须先完成 unresolved session reconciliation；`session_reconciled` trace 顺序早于 `run_resumed`。
- topic、请求/解析路线、selected agents 或配置指纹不一致，以及不存在、损坏或 symlink 逃逸的 workspace，必须拒绝恢复。
- completed run 再次 resume 必须幂等，不重新调用 provider。
- 正常结果必须返回 `status=completed`，并保持七类稳定产物不变。

`domain.jsonl`、`trace.jsonl` 和 `round_summary.json` 中实际持久化的领域 dataclass payload 必须可 JSON 序列化，并包含稳定 ID、UTC `created_at` 与 `schema_version="1.0"`；新增尾部默认字段不得破坏旧位置或关键字构造。

## 3. 必验命令

全量测试：

```bash
python3 -m pytest -q
```

严格一致性扫描按 Task 4 brief 指定的退役模型名、旧来源配置字段、旧阻断状态和旧中文表述执行，范围覆盖 README、技术文档、源码、脚本、配置和测试。扫描必须零命中；`rg` 在零命中时返回退出码 1，属于预期结果。

独立输出根 smoke：

```bash
python3 scripts/run_deep_research.py \
  --mode fake \
  --topic "低空无人机探测预警能力缺口" \
  --research-route auto \
  --run-id phase-1-fresh-smoke \
  --output-root /tmp/equipment-deep-research-phase-1
```

另需执行一次 crash+resume smoke。smoke 必须核对：七类稳定产物、`run.db`、completed checkpoint、agent session 数量、`run_resumed`、resolved route、audit status、所选 agent、来源材料数量和正式证据数量。

## 4. 甲方首版规划入口

- [装备能力图像 Deep Research 多智能体系统总实施计划](superpowers/plans/2026-07-10-equipment-deep-research-master-plan.md)
- [装备能力图像 Deep Research 前后端一体化企业级设计方案](superpowers/specs/2026-07-10-equipment-deep-research-frontend-backend-enterprise-design.md)

两份规划文件定义首版完整范围；本文件只验收 Phase 0 与 Phase 1 harness 基础阶段。

## 5. 后续阶段进入条件

只有同时满足以下条件，才可进入 Phase 1：

- 全量测试通过，严格一致性扫描零命中。
- fresh+resume smoke 在独立输出根成功生成七类稳定产物、`run.db` 和 completed checkpoint。
- Phase 0 文档、配置、测试和运行行为对默认模型、来源策略、provider 边界及已知限制无矛盾。
- Task 1-4 审查结论均无阻断问题，遗留项已明确归入后续阶段。
- 已明确运行时加载 `evidence.yaml` 并执行质量评分的设计、测试和正式证据准入规则。
- 后续实现承诺兼容现有领域对象、CLI 参数和七类稳定产物契约。

## 6. 首版后续验收项

以下项目从 Phase 1 起另行设计和验收：

- 真实 Responses 模型循环与真实搜索 provider。
- 真实检索和模型驱动的多轮研究、再调与收敛。
- 运行时质量评分、去重、独立印证、冲突检测与反证推理。
- 真正并行调度、暂停、取消、分布式 worker 和跨进程调度恢复。
- Web 工作台、API、SSE、队列、数据库、权限、审批和企业部署。
