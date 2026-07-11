# Phase 0 验收说明

## 1. 验收范围

Phase 0 验收对象是可运行、可回归、可审计的研究基线，包括三类研究路线、可配置 baseline agent、受控公开 URL 材料化、失败材料隔离、L1/L2/L3 输出、工作区和稳定产物。

真实模型循环和真实搜索尚未接入。Web/API、持久化、恢复执行、分布式 worker 和生产部署不属于本阶段完成项。

## 2. 必验能力

### 2.1 路线与 Agent

- 三条研究路线均可在 `fake` 模式完成端到端运行。
- 默认运行四个 registry baseline agent：国际形势、作战场景、武器装备、作战运用。
- `--agents` 可运行任意子集；缺失能力标签必须进入 summary 和报告限制说明。
- 自定义配置可替换默认 baseline agent，runner 不依赖固定 agent ID 分支。
- 每个所选 agent 生成独立 session 文件。

### 2.2 模型与 Provider

- 默认模型配置精确为 `gpt-5.5`。
- `fake` provider 提供稳定离线验证数据。
- Phase 0 `real` provider 仍为模板占位，只验证受控 URL 材料化和证据治理边界。
- 不得把 `providers.yaml` 中的 Responses-compatible 配置描述为已经执行真实模型循环。

### 2.3 公开材料与正式证据

- 公开来源不按域名设置准入门槛。
- URL、DNS、IP、重定向、响应大小和 TLS 安全控制由材料化层强制执行。
- 成功抓取且允许形成正式证据的材料可进入 `EvidenceCard` 和 baseline packet。
- `fetch_failed`、`network_safety_rejected` 等失败材料必须保留诊断 artifact，但不得进入正式 evidence IDs。
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

同时必须创建 `checkpoints/` 预留目录。Phase 0 不要求写入 checkpoint，不创建 `run.db`，不支持 resume。

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
  --run-id phase-0-smoke \
  --output-root /tmp/equipment-deep-research-phase-0-task-4
```

smoke 必须核对：七类稳定产物、`checkpoints/`、agent session 数量、resolved route、audit status、所选 agent、来源材料数量和正式证据数量。

## 4. Phase 1 进入条件

只有同时满足以下条件，才可进入 Phase 1：

- 全量测试通过，严格一致性扫描零命中。
- `phase-0-smoke` 在独立输出根成功生成七类稳定产物和 `checkpoints/`。
- Phase 0 文档、配置、测试和运行行为对默认模型、来源策略、provider 边界及已知限制无矛盾。
- Task 1-4 审查结论均无阻断问题，遗留项已明确归入后续阶段。
- 后续实现承诺兼容现有领域对象、CLI 参数和七类稳定产物契约。

## 5. 后续阶段验收项

以下项目从 Phase 1 起另行设计和验收：

- 真实 Responses 模型循环与真实搜索 provider。
- checkpoint 持久化、`run.db`、resume、暂停、取消和故障恢复。
- 并行 worker、队列、数据库、Web/API、SSE、权限、审批和企业部署。
- 完整证据评分、去重、独立印证、冲突检测与反证推理。
