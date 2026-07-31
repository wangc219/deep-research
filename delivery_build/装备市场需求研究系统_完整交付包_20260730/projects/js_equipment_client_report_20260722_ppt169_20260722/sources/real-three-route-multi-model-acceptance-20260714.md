# Real 三路线多模型验收报告（2026-07-14）

## 验收结论

三条业务路线均在 Real 模式下完成真实模型调用、公开来源检索、材料化、结构化基线 Packet、制胜核心六步推理、L1/L2/L3 门控、定向再调、独立审计、报告生成和交付清单闭环。

三次运行均满足：

- `status=completed`
- `runtime_complete=true`
- `release_ready=true`
- `audit_status=approved`
- `formal_evidence_present=true`
- 编排器、制胜核心、审计和报告四类核心 Session 均存在
- 六个制胜推理节点与 L1/L2/L3 三阶段完整
- 生成两项九字段能力画像
- `delivery-manifest.json` 完整

## 多模型配置

| Agent | Real 模型 |
| --- | --- |
| 编排器 | `gpt-5.4-mini` |
| 国际形势 | `gpt-5.4` |
| 作战场景 | `gpt-5.5` |
| 武器装备 | `gpt-5.6-terra` |
| 作战运用 | `gpt-5.4` |
| 制胜核心 | `gpt-5.6-sol` |
| 审计 | `gpt-5.4-mini` |
| 报告 | `gpt-5.4` |

模型快照保存在每次运行的 `round_summary.json` 中，只记录模型名、API Key 环境变量名和 URL 主机，不记录密钥值。

## 路线结果

### 1. 新制胜机理

- Run ID：`run-ef59c312-8b97-41ea-b5ba-016717b30dd4`
- 主题：面向强电磁干扰与低空蜂群威胁的新型分布式探测预警制胜机理与装备能力需求
- 路线：`new_winning_mechanism`
- 基线 Agent：国际形势、作战场景、武器装备、作战运用
- 正式/材料化证据：10 / 10
- 推理节点：6
- L1/L2/L3：全部通过，置信度均为 0.715
- Recall：0
- 能力画像：2
- 核心 Session 行数：编排器 1、制胜核心 2、审计 1、报告 1
- Manifest 文件数：101
- 输出目录：`outputs/real-acceptance-v11/runs/run-ef59c312-8b97-41ea-b5ba-016717b30dd4`

### 2. 传统能力缺口

- Run ID：`run-2ebc8344-5484-41ef-86ee-57a3cf56f692`
- 主题：复杂地形条件下现役低空无人机探测预警体系的传统能力缺口与升级需求
- 路线：`traditional_gap`
- 基线 Agent：作战场景、武器装备、作战运用
- 正式/材料化证据：8 / 8
- 推理节点：12（首轮 6 + Recall 恢复轮 6）
- L1/L2/L3：全部通过，置信度均为 0.723
- Recall：1 次，定向武器装备补证并从 L1 恢复
- 能力画像：2
- 核心 Session 行数：编排器 1、制胜核心 7、审计 1、报告 1
- Manifest 文件数：140
- 输出目录：`outputs/real-acceptance-v11/runs/run-2ebc8344-5484-41ef-86ee-57a3cf56f692`

### 3. 战例学习

- Run ID：`run-63db8d9c-4590-4689-9e3c-6968a77acff3`
- 主题：近年局部战争无人机攻防战例对低空预警、协同处置与体系韧性装备布局的启示
- 路线：`war_case_learning`
- 基线 Agent：作战场景、武器装备、作战运用
- 正式/材料化证据：5 / 5
- 推理节点：12（首轮 6 + Recall 恢复轮 6）
- L1/L2/L3：全部通过，置信度均为 0.718
- Recall：1 次，定向武器装备补证并从 L1 恢复
- 能力画像：2
- 核心 Session 行数：编排器 1、制胜核心 3、审计 1、报告 1
- Manifest 文件数：94
- 输出目录：`outputs/real-acceptance-v11/runs/run-63db8d9c-4590-4689-9e3c-6968a77acff3`

## 架构门禁

三条路线的 `architecture-acceptance.json` 均确认以下检查为真：

- 动态 Agent 选择已记录，计划图完整，coverage 显式
- Agent Session 相互隔离，核心 Agent Session 完整
- 四类制胜知识资源已投影
- 六步推理、L1/L2/L3 和九字段能力画像完整
- 正式证据、五判据审计和最终报告存在
- Real/Fake 模式快照存在

## 自动化验证

- Python：Harness 改造后全量回归 `391 passed`（1 条第三方弃用警告）
- 前端：Vite 生产构建通过
- Compose：配置校验通过

说明：本报告中的三次 Real 运行按交付顺序先于差异化 Harness 改造完成。改造后未重复向外部端点发送 Real 数据；已另行完成三路线 Fake E2E，三条路线均 `runtime_complete=true`、`release_ready=true`、`audit=approved`，产物位于 `outputs/fake-harness-acceptance-v1/`。

## 已知限制

- 外部 Responses 兼容端点和部分公开网站存在偶发超时、403 或 TLS 中断；模型请求具备最多三次有界重试，网页材料化失败不会被提升为正式证据。
- Worker 进程中断后的恢复入口已修复：检测到已有运行目录时自动以 `resume=true` 打开检查点，避免重复创建运行目录。
- 传统缺口路线曾在补证后的外部模型请求阶段遇到网络失败；最终从同一运行检查点恢复并通过，未新建替代运行。

## 交付文件

每条路线目录均包含：

- `report.md`
- `capability_images.json`
- `round_summary.json`
- `domain.jsonl`
- `trace.jsonl`
- `architecture-acceptance.json`
- `delivery-manifest.json`
- `run.db`
- `agent_sessions/`
- `artifacts/`
- `checkpoints/`
