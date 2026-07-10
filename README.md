# 装备能力图像 Deep Research 多智能体系统

本项目是面向装备能力图像需求生成的 Deep Research 多智能体初期交付版本。

实现基于 `reference/demand_discovery_codex_handoff_runtime_minimal_20260701-044538` 的
领域对象、harness、scheduler、trace、tools 等框架思想进行改造，并移除旧的演示执行链路。

## 能力范围

- 支持三类研究路线：
  - `new_winning_mechanism`：新制胜机理、新体系组合、新作战样式牵引的新能力方向。
  - `traditional_gap`：传统场景、传统制胜、传统战法下的能力不足和升级需求。
  - `war_case_learning`：局部战争案例复盘牵引的未来能力布局方向。
- 支持动态 agent 池：
  - 默认 agent：国际形势、作战场景、武器装备、作战运用。
  - 支持 `--agents` 只选择部分 agent。
  - 支持通过 `configs/equipment_deep_research/agents.yaml` 替换或新增 agent。
- 支持制胜机理三层分析：
  - L1 制胜逻辑分析。
  - L2 概念创新评估。
  - L3 能力图像生成。
- 输出能力画像九字段：
  - 能力编号、名称、装备类别、类型、来源制胜逻辑、关联场景、优先级、能力差距、能力画像。

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

真实模式 smoke：

```bash
python3 scripts/run_deep_research.py \
  --mode real \
  --topic "低空无人机探测预警能力缺口" \
  --research-route auto \
  --run-id real-smoke
```

首版 `real` 模式保留联网工具接入边界，运行链路和证据治理产物可审计；后续可将 provider 替换为真实联网检索和模型调用实现。
如果当前环境无法访问公网，`real` 模式会把抓取失败原因写入 `artifacts/` 诊断文件，并将审计状态标记为 `limited`，不会伪造成联网成功。
白名单外来源只会记录为建议新增信源诊断，不进入正式证据集，也不会被报告当作支撑材料引用。

## 输出

每次运行写入 `outputs/runs/<run-id>/`：

- `report.md`：甲方可读能力画像报告。
- `capability_images.json`：能力画像结构化数据。
- `round_summary.json`：研究摘要、agent 覆盖、trace 摘要。
- `domain.jsonl`：领域对象流水。
- `trace.jsonl`：可审计事件链。
- `agent_sessions/`：各 agent 独立会话。
- `artifacts/`：网页、文档、正文或诊断材料化结果。

## 验证

```bash
python3 -m pytest
rg -n "旧演示执行链路入口标识" src scripts tests configs
```

第二条命令应无结果，表示正式源码不包含旧演示执行链路。
