# 装备能力图像 Deep Research 多智能体系统技术方案

## 1. 方案定位

本系统面向“市场需求挖掘、制胜机理研判、装备能力图像生成”场景，首版交付一个可运行、可审计、可演示的 Deep Research 多智能体闭环。用户输入研究主题后，系统可配置选择多个 agent，检索和材料化公开资料，完成多轮研判、门控和再调，最终输出能力画像报告。

## 2. 项目要求对应

- 新制胜机理路线：研判国际形势、威胁力量和对抗场景，从新制胜机制、新作战打法、新体系组合中提出新装备能力需求。
- 传统能力缺口路线：基于传统场景、传统制胜、传统战法，与当前装备能力对比，挖掘能力不足、空白领域和装备升级需求。
- 局部战争案例路线：对局部战争案例进行多轮检索，总结新能力、新打法、经验不足，研判未来可布局方向。
- 架构图主流程：分析师输入 -> 编排器问题解析 -> 基线 agent 池并发研判 -> 编排器汇总初检 -> 制胜机理 L1/L2/L3 -> 再调迭代 -> 五判据检查 -> 作战能力图像需求输出。

## 3. 参考项目设计吸收

- Pi：小内核、大 harness；turn snapshot；save point；append-only session。
- Nanobot：MessageBus / AgentLoop / AgentRunner 分层；provider/tool/agent registry 分离；config 与 workspace 分离。
- GenericAgent：上下文信息密度优先；最小原子工具集；working checkpoint；任务可拆时再使用 map-reduce 式 subagent。

## 4. 总体架构

- `interfaces`：CLI 入口，与 Web/API 共享 application service。
- `api/application`：FastAPI、版本化 API、业务用例服务、RBAC、SSE 和导出。
- `queue/persistence`：独立 worker、任务队列、PostgreSQL/SQLite 仓储、配置 revision 和恢复。
- `orchestration`：问题解析、研究路线选择、agent 选择、并发调度、门控、再调、最终判据。
- `harness`：通用运行时，包括 scheduler、context pack、session、artifact materialization。
- `agents`：可配置 agent registry，默认提供国际形势、作战场景、武器装备、作战运用、制胜机理、审计、报告 agent。
- `domain`：研究问题、研究路线、证据卡、基线发现、制胜阶段输出、再调请求、能力画像、报告对象。
- `tools`：工具权限、证据材料化、公开 URL 抓取、artifact 落盘。
- `apps/web`：React 企业研究工作台，覆盖研究发起、实时监控、证据审阅、制胜机理、能力画像、报告评审和系统配置。

## 5. Agent 设计

默认四类基线 agent 只是预设，不写死。系统通过 `AgentRegistry` 管理：

- `agent_id`
- `display_name`
- `capability_tags`
- `input_contract`
- `output_contract`
- `tools`
- `context_policy`
- `enabled`

统一输出 `BaselineFindingPacket`，编排器可以按 `--agents` 只选择其中几个 agent。缺失能力必须在报告中显式标注，不允许伪造全覆盖结论。

## 6. 制胜机理核心

制胜机理智能体消费 `BaselineFindingPacket[]` 和 capability 覆盖度，不依赖固定四路名称。

四库：

- 理论工具库
- 战例库
- 前沿情报库
- 问题链

六步推理：

- 防御解构
- 制胜路径
- 效果链
- 能力映射
- 差距量化
- 图像生成

三层分析：

- L1 制胜逻辑分析。
- L2 概念创新评估。
- L3 能力图像生成。

## 7. 再调与多轮机制

- 再调对象使用 `target_agent_id` 或 `target_capability_tag`。
- 再调格式包含来源层、目标、原因、所需数据、回传节点、紧迫度。
- 总轮次最多 5 轮；同一目标最多 3 次；补充后从断点继续。
- 首版在缺失 capability 覆盖时生成 `RecallRequest`，并写入 `round_summary.json` 与 `trace.jsonl`，保证再调原因、目标和所需数据可审计。

## 8. 证据与联网检索

- 公开网络搜索不使用来源域名硬门控，以扩大有效信息搜集范围。
- 网络层执行 URL/SSRF、响应大小、重定向、超时和限速安全控制。
- 证据层执行相关性、透明度、时效性、直接支撑、提取质量评分，并进行去重、独立印证、冲突检测和反证保留。
- 未达到质量阈值的材料保留为 candidate/rejected 及诊断记录，不进入正式 claim 支撑。
- 每条 `EvidenceCard` 包含来源、URL/路径、摘录、位置、质量评估、支撑 claim、创建 agent、artifact 引用。
- 网页和文档落入 `artifacts/`，报告引用证据卡和 artifact，不引用模型口述来源。
- 材料化失败的材料只保留诊断 artifact，不写入正式证据集。

## 9. 输出与交付物

运行产物：

- `report.md`
- `capability_images.json`
- `round_summary.json`
- `domain.jsonl`
- `trace.jsonl`
- `agent_sessions/`
- `artifacts/`

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

## 10. 验收标准

- 默认四 agent 可跑，任意子集 agent 可跑，自定义替换 agent 可跑。
- agent 原始上下文隔离，工具权限由执行层强制。
- 三条研究路线均有 fake E2E。
- real smoke 能生成联网材料化状态；公网不可达时必须降级为 `limited` 并保留诊断 artifact。
- L1/L2/L3 门控、再调、五判据均可在 trace 中审计。
- 报告明确区分新作战能力方向和现有装备升级需求。
- 正式源码不包含旧演示执行链路入口。
- 默认模型为 `gpt-5.5`，模型调用通过 Responses-compatible HTTP provider，不调用外部模型命令行。
- Web、CLI、API 和导出文件消费同一领域对象，关键结论可追溯到 evidence 与 artifact。
- Web 支持创建、启动、暂停、恢复、取消、证据审阅、L1/L2/L3 复核、能力画像、报告评审和导出。
- 企业部署包含 FastAPI、worker、PostgreSQL、Redis、React Web、反向代理、RBAC/OIDC、健康检查和审计日志。

## 11. 前后端企业级设计

详细设计见：[装备能力图像 Deep Research 前后端一体化企业级设计方案](superpowers/specs/2026-07-10-equipment-deep-research-frontend-backend-enterprise-design.md)。

实施计划见：[装备能力图像 Deep Research 多智能体系统总实施计划](superpowers/plans/2026-07-10-equipment-deep-research-master-plan.md)。
