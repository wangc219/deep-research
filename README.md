# 装备能力图像 Deep Research 多智能体系统

本项目面向装备能力图像需求生成，当前交付范围为 **Phase 0 可运行基线**。该基线用于验证多智能体研究编排、公开材料受控材料化、证据隔离、制胜机理三层分析和可审计产物契约，不代表生产级真实 Deep Research 服务已经完成。

## Phase 0 已完成

- 支持三类研究路线：
  - `new_winning_mechanism`：新制胜机理、新体系组合、新作战样式牵引的新能力方向。
  - `traditional_gap`：传统场景和战法下的能力不足与装备升级需求。
  - `war_case_learning`：局部战争案例复盘牵引的未来能力布局方向。
- 提供四个默认 baseline agent：国际形势、作战场景、武器装备、作战运用。
- 四路 agent 是 registry 预设，可通过 `--agents` 选择子集，也可在 `configs/equipment_deep_research/agents.yaml` 中替换或新增。
- 支持制胜机理 L1 制胜逻辑、L2 概念创新、L3 能力图像三层输出。
- 输出包含能力编号、名称、装备类别、类型、来源制胜逻辑、关联场景、优先级、能力差距、能力画像九个字段。
- 默认模型配置为 `gpt-5.5`。
- 公开来源采用广泛搜集、网络安全控制、质量阈值过滤和失败材料隔离策略，不按来源域名设置准入门槛。

## 当前实现边界

- `fake` 模式提供稳定的离线闭环，用于回归测试和交付演示。
- `real` 模式当前仍使用模板占位 provider，可对受控 URL 执行材料化并记录成功、失败或网络安全拒绝状态。
- 真实模型循环和真实搜索尚未接入。`providers.yaml` 和 `tools.yaml` 已预留 Responses-compatible provider 与搜索工具配置边界，但当前 runner 尚未加载并执行真实 Responses 模型循环或真实搜索 provider。
- `--resume` 仅建立接口边界，调用时会明确返回未实现；`run.db` 不会创建，SQLite 持久化和恢复执行属于后续阶段。
- 七类稳定产物保持不变，`checkpoints/` 仅作为后续恢复点目录预留。

## 运行

离线闭环：

```bash
python3 scripts/run_deep_research.py \
  --mode fake \
  --topic "低空无人机探测预警能力缺口" \
  --research-route auto \
  --run-id fake-full
```

子集 agent：

```bash
python3 scripts/run_deep_research.py \
  --mode fake \
  --topic "低空无人机探测预警能力缺口" \
  --agents combat_scenario,weapon_equipment \
  --run-id fake-subset
```

Phase 0 real smoke：

```bash
python3 scripts/run_deep_research.py \
  --mode real \
  --topic "低空无人机探测预警能力缺口" \
  --research-route auto \
  --run-id real-smoke
```

`real` smoke 只验证占位 provider、受控 URL 材料化和证据治理边界。公网不可达或材料不满足准入条件时，系统会在 `artifacts/` 中保留诊断信息，并禁止失败材料进入正式证据集，不会伪造联网成功。

## 证据策略

1. 广泛接收公开网络线索，不按域名预先筛除。
2. 在网络层校验 HTTP(S)、目标地址、DNS 解析、重定向、响应大小、TLS 和超时边界。
3. 在证据层按相关性、透明度、时效性、直接支撑和提取质量执行阈值判断。
4. 抓取失败、网络安全拒绝或质量不达标的材料只保留候选、拒绝或诊断记录，不进入正式 `EvidenceCard` 支撑链。

## 输出

每次运行写入 `outputs/runs/<run-id>/`。七类稳定产物为：

- `report.md`：甲方可读能力画像报告。
- `capability_images.json`：能力画像结构化数据。
- `round_summary.json`：研究摘要、agent 覆盖、来源材料和 trace 摘要。
- `domain.jsonl`：领域对象流水。
- `trace.jsonl`：可审计事件链。
- `agent_sessions/`：所选 baseline agent 的独立会话。
- `artifacts/`：网页、正文、元数据或失败诊断材料。

同时创建 `checkpoints/` 预留目录；Phase 0 不写入恢复点。

## 验证

```bash
python3 -m pytest -q
```

Phase 0 测试结论见 `docs/testing/phase-0-test-report.md`，验收边界见 `docs/ACCEPTANCE.md`。
