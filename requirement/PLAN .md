# 装备能力图像 Deep Research 多智能体系统技术方案

## 1. 方案定位
建设一个面向甲方“市场需求挖掘、制胜机理研判、装备能力图像生成”的 Deep Research 多智能体系统。首版目标是形成可运行、可审计、可演示的初期交付闭环：用户输入研究主题后，系统可配置选择多个 agent，联网检索公开资料，完成多轮研判与再调，最终输出能力画像报告。

明确删除：知识图谱 V0.1 种子暂不做，不进入首版实现、测试和交付范围。

## 2. 项目要求对应
- 新制胜机理路线：研判国际形势、威胁力量和对抗场景，从新制胜机制、新作战打法、新体系组合中提出新装备能力需求。
- 传统能力缺口路线：基于传统场景、传统制胜、传统战法，与当前装备能力对比，挖掘能力不足、空白领域和装备升级需求。
- 局部战争案例路线：对国际局部战争案例进行多轮联网检索，总结新能力、新打法、经验不足，研判未来可布局方向。
- 架构图主流程：分析师输入 -> 编排器问题解析 -> 基线 agent 池并发研判 -> 编排器汇总初检 -> 制胜机理 L1/L2/L3 -> 再调迭代 -> 五判据检查 -> 作战能力图像需求输出。
- 最终回答的问题：需要发展具备什么功能的产品，以及这些能力来自哪条制胜逻辑、哪类场景、哪些证据和哪些缺口。

## 3. 参考项目设计吸收
- Pi 借鉴：
  - 小内核、大 harness：`AgentLoop` 只负责消息、工具、事件循环；`Harness` 负责 session、上下文、权限、预算、压缩和恢复。
  - turn snapshot：每轮冻结上下文、工具和模型配置，运行中变更只影响下一轮，避免多 agent 并发状态错乱。
  - save point：工具结果先形成 proposal，统一在安全点写入 `DomainStore` / `TraceStore`。
  - append-only session：每个 agent 独立 JSONL session，便于复盘、恢复和审计。
- Nanobot 借鉴：
  - MessageBus / AgentLoop / AgentRunner 分层，后续可扩展 CLI、API、WebUI 或服务化 gateway。
  - Provider registry、Tool registry、Agent registry 分离，方便替换模型、工具和 agent。
  - config 与 workspace 分离：配置定义可用能力，workspace 保存 session、artifact、trace 和运行产物。
- GenericAgent 借鉴：
  - 上下文信息密度优先：每个 agent 只看必要摘要、证据索引和任务约束，不共享原始长上下文。
  - 最小原子工具集：检索、抓取、阅读、材料化、写证据、写阶段输出，避免给 agent 过宽工具面。
  - working checkpoint：长流程持续记录进度、开放问题、下一步，防止多轮研究目标漂移。
  - subagent map-reduce：只有任务可拆、上下文应隔离、结果可汇总时才并发使用子 agent。

## 4. 总体架构
- `interfaces`：CLI 入口，后续可扩展 API。
- `orchestration`：问题解析、研究路线选择、agent 选择、并发调度、门控、再调、最终判据。
- `harness`：通用运行时，包括 loop、scheduler、context pack、event bus、session、budget、save point。
- `agents`：可配置 agent registry，默认提供国际形势、作战场景、武器装备、作战运用、制胜机理、审计、报告 agent。
- `domain`：研究问题、研究路线、证据卡、基线发现、制胜阶段输出、再调请求、能力画像、报告对象。
- `tools`：公开检索、网页抓取、正文简化、文档读取、artifact 落盘、白名单校验。
- `outputs`：`report.md`、`capability_images.json`、`round_summary.json`、`domain.jsonl`、`trace.jsonl`、`agent_sessions/`、`artifacts/`。

## 5. Agent 设计
默认四类基线 agent 只是预设，不写死。系统通过 `AgentRegistry` 管理 agent：
- `agent_id`
- `display_name`
- `capability_tags`
- `input_contract`
- `output_contract`
- `tools`
- `context_policy`
- `enabled`

默认预设：
- 国际形势 agent：`situation`、`threat`、`strategy`
- 作战场景 agent：`scenario`、`coa`、`environment`
- 武器装备 agent：`equipment`、`capability_gap`、`technology_readiness`
- 作战运用 agent：`operation`、`coordination`、`lessons`

统一输出 `BaselineFindingPacket`：`agent_id`、`capability_tags`、`findings`、`evidence_ids`、`confidence`、`coverage_notes`、`open_questions`、`handoff_summary`。编排器可按 `--agents` 只选择其中几个 agent；缺失能力必须在报告中显式标注，不允许伪造全覆盖结论。

## 6. 制胜机理核心
制胜机理智能体不依赖固定四路名称，而消费 `BaselineFindingPacket[]` 和 capability 覆盖度。

实现四库：
- 理论工具库
- 战例库
- 前沿情报库
- 问题链

实现六步推理：
- 防御解构
- 制胜路径
- 效果链
- 能力映射
- 差距量化
- 图像生成

实现三层分析：
- L1 制胜逻辑分析：弱点地图、制胜路径、效果链、关键能力清单、假设。
- L2 概念创新评估：新概念、新技术、新手段、跨域移植、创新方向。
- L3 能力图像生成：去重归并、类别映射、差距量化、优先级、能力画像条目。

## 7. 再调与多轮机制
- 再调对象使用 `target_agent_id` 或 `target_capability_tag`，不写死四路 agent。
- 再调格式包含：来源层、目标、原因、所需数据、回传节点、紧迫度。
- 约束：总轮次最多 5 轮；同一目标最多 3 次；补充后从断点继续。
- 如果当前启用 agent 无法覆盖所需能力，生成 `AgentRecommendation`，提示启用或新增 agent，并在报告中标记限制。

## 8. 证据与联网检索
- 首版以公开联网检索为主，本地检索仅预留接口。
- 证据必须来自白名单或允许范围内公开来源。
- 白名单外来源只能记录为“建议新增信源”，不能进入正式证据。
- 每条 `EvidenceCard` 包含：来源、URL/路径、摘录、位置、质量评估、支撑 claim、创建 agent。
- 网页和文档落入 `artifacts/`，报告引用证据卡，不引用模型口述来源。

## 9. 输出与交付物
首版甲方交付：
- 可运行源码和 CLI。
- 默认 agent 配置和可替换 agent 配置说明。
- 离线 fake 示例运行产物。
- 真实联网 smoke 示例产物。
- 技术方案文档。
- 测试报告与验收说明。

运行产物：
- `report.md`：甲方可读报告。
- `capability_images.json`：能力画像结构化数据。
- `round_summary.json`：本次研究摘要。
- `domain.jsonl`：领域对象流水。
- `trace.jsonl`：可审计事件链。
- `agent_sessions/`：各 agent 独立会话。
- `artifacts/`：网页、文档、正文材料化结果。

能力画像九字段：
- 能力编号
- 名称
- 装备类别
- 类型
- 来源制胜逻辑
- 关联场景
- 优先级
- 能力差距
- 能力画像

## 10. 分阶段实施
- Phase 0：项目骨架、CLI、配置体系、输出目录规范、删除 Codex CLI 链路回归检查。
- Phase 1：Pi 风格通用 harness：loop/harness 分层、turn snapshot、save point、独立 session。
- Phase 2：Nanobot 风格 registry：agent/tool/provider registry，config/workspace 分离。
- Phase 3：GenericAgent 风格上下文治理：context policy、checkpoint、摘要压缩、证据索引。
- Phase 4：动态 agent 编排：默认四 agent、部分 agent、自定义替换 agent 均可运行。
- Phase 5：三条研究路线：新制胜机理、传统能力缺口、局部战争案例。
- Phase 6：制胜机理引擎：四库、六步推理、L1/L2/L3、门控、再调。
- Phase 7：联网检索与证据治理：白名单、fetch/read、artifact、证据卡、真实 smoke。
- Phase 8：能力画像与报告：五判据检查、报告生成、交付样例和测试报告。

## 11. 验收标准
- 默认四 agent 可跑，任意子集 agent 可跑，自定义替换 agent 可跑。
- agent 原始上下文隔离，工具权限由执行层强制。
- 三条研究路线均有 fake E2E。
- real smoke 至少完成一次公开资料检索、材料化、证据写入和能力画像生成。
- L1/L2/L3 门控、再调、五判据均可在 trace 中审计。
- 报告明确区分新作战能力方向和现有装备升级需求。
- 报告能回答“需要发展具备什么功能的产品”。
- 正式源码不包含旧 Codex CLI 调用链。
