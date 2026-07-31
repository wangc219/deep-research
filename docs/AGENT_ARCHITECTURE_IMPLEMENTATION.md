# 智能体架构落实与交互审计说明

本说明以 `output/pdf/编排器与动态智能体_总体架构图.pdf` 和 `output/pdf/制胜机理智能体_详细架构图.pdf` 为实现约束，记录当前首版可运行闭环中每个智能体的职责、输入输出、上下文边界、工具权限与可视化审计方式。

## 编排主链

```text
分析师输入 -> 编排器问题解析/路线与能力规划 -> 动态选择基线 Agent
  -> 受限上下文的子任务执行 -> Packet/证据汇总初检
  -> 制胜机理四类资源、六步推理、L1/L2/L3
  -> 定向再调 -> 五判据审计 -> 报告与九字段文字能力画像
```

编排器不共享其他 Agent 的原始 session；它仅基于研究问题、coverage、结构化 handoff packet、证据索引和 trace 摘要委派任务、设置门控和再调回传节点。

## Agent 责任矩阵

| Agent | Harness Profile | 任务与固定输出 | 可见上下文 | 代表性专用工具 |
|---|---|---|---|---|
| 编排器 | `orchestration_v1` | 问题解析、A-H 路径、Agent 波次、循环进入/回溯/停止 | research problem、coverage、packet 摘要、trace 摘要 | 任务解析、发现蓝图、执行波次、循环转移 |
| 国际形势 | `strategic_research_v1` | 态势判断、威胁评估、战略格局、对手动向、预警指标、替代假设 | task、证据策略、自身 checkpoint、recall request | 事件时间线、行为体立场比较、预警指标登记、竞争假设检验 |
| 作战场景 | `scenario_research_v1` | 场景框架、敌方 COA、关键时间窗、环境约束、场景分支、能力压力点 | 国际形势 typed Packet（若路线允许），不读取原始会话 | 场景图构建、分支生成、关键时间窗、环境约束映射、压力测试 |
| 武器装备 | `equipment_research_v1` | 国外装备全景、型号档案、参数冲突、成熟度、体系依赖、能力边界、防御性反制、现役升级、新研需求和验证计划 | 已完成的形势/场景 typed Packet（若可用），不读取原始会话 | 型号批次归一、参数观测抽取、冲突调和、成熟度评估、能力比较、反制映射、需求形成 |
| 作战运用 | `operational_synthesis_v1` | 作战约束、任务链、协同依赖、三类 COA、持续保障、失败模式和功能要求 | 当前路线已选择的场景与装备 typed Packet | 任务能力映射、协同依赖图、COA 比较、保障评估、战例迁移 |
| 制胜机理（核心 Agent） | `winning_core_v1` | 独立 LLM 推导四类资源投影、六步推理、L1/L2/L3、能力画像、再调请求；确定性引擎负责契约、证据门控与安全回退 | typed payload、证据索引、coverage、冲突、开放问题、checkpoint | 输入包准备、四库投影、推理节点、阶段输出、定向再调、能力画像 |
| 审计 | `audit_v1` | 证据、覆盖、门控、追溯、轮次五判据 | task、证据索引、stage outputs、capability images、trace summary | 发布就绪评估、write audit |
| 报告 | `report_v1` | 研究报告、能力需求卡片、限制说明、能力画像结论 | task、证据索引、能力画像、audit、coverage、trace summary | 需求卡片生成、write report |

默认四路是可替换预设，而不是编排器硬编码。`agents.yaml` 定义 agent ID、能力标签、输入输出契约、上下文可见区、对象读写 scope、工具权限和启用状态；任意子集运行时，coverage 缺口会进入再调、审计和报告限制。

## Harness 配置与契约落实

`harness.yaml` 已声明 16 套 `HarnessProfile` 和 50 个命名 `SkillDefinition`，覆盖编排、四路基线、A-H 专业发现、收敛、制胜核心、S1-S6、步骤/中循环批判、审计和报告。各 Agent 共享 AgentLoop、Session、SavePoint、恢复、上下文压缩、取消和证据治理基础设施，但具有独立的上下文策略、预算、停止条件、技能、工具与输出契约。`TaskEnvelope` 冻结 `runtime_profile_id`、`active_skill_ids` 和 `phase_id`，执行结果及 Trace 可审计实际 Profile、Skills、Tools 和停止原因。

工具权限按四重交集计算：`Agent allowlist ∩ Task allowlist ∩ Active Skill allowlist ∩ Phase allowlist`。所有领域工具均具有显式 JSON 输入 Schema、允许写入的对象类型和 `domain_tool_invoked` Trace，不是仅存在于提示词中的动作名称。配置中的未知 Profile、Skill、Tool、对象 Scope、预算项或非法依赖会在加载时失败。

Baseline map wave 由蓝图依赖划分，并由 `runtime_budgets.codex_concurrency` 或 `EQUIPMENT_DR_BASELINE_WAVE_CONCURRENCY` 强制施加物理并发上限；检索预取与正式 Agent 执行共用该上限。每个 `baseline_wave_started` Trace 明确记录 wave 大小、最大并发、物理批次数和 bounded 标记，避免逻辑上标记为 wave、运行时却无界创建线程。

同一 wave 内的 Agent 失败不会抹去其他并行 Agent 已完成的成果。运行时先提交成功 Packet、证据、独立 Session savepoint 和 RunCheckpoint，将失败任务恢复为 pending，再生成 `handoff-failed-*.json`。该 handoff 只包含脱敏错误、对象引用、能力标签、候选接收方、恢复节点和 committed savepoint，不包含原始消息或其他 Agent Session；随后保留原始异常类型退出，使 `--resume` 能从最新 checkpoint 继续。

新运行统一写 `BaselineFindingPacket v2`，公共信封之外使用角色专用 typed payload，并同步生成 `StrategicAssessment`、`ScenarioModel`、`EquipmentObservation` 或 `OperationalSynthesis`。旧 v1 Packet 保持读取、恢复和执行兼容，但不会被错误套用 v2 专用结构停止条件。

## Codex 场景运行画像

每次独立 Codex 调用都会注入 `agent_runtime`，统一声明当前 Agent、执行阶段、场景目标、适用 Skills、相关受治理 Tools、方法步骤、质量门槛、输出重点、安全边界和工具执行规则。工具名称不是提示词中的自由动作：Codex 只按其语义规划和输出，本地 Harness 仍是实际执行、权限校验、材料化和 Trace 登记的唯一主体。

Codex CLI 同时通过 `skills.config` 显式装载项目原生 Skill `configs/equipment_deep_research/codex_skills/js-equipment-agent-runtime/SKILL.md`。该 Skill 负责强制读取当前 `agent_runtime`、执行四级循环纪律、遵守停止与恢复策略，并禁止虚构 Harness Tool 已被直接执行。角色细化 Skill 仍由 Registry 动态选择，避免把 50 个专业 Skill 全量塞入每个会话。

运行画像覆盖编排器、A-H 发现分支、国际形势、作战场景、武器装备、作战运用、场景发散、案例研究、技术雷达、对手监测、体系对抗、跨域融合、非传统安全、收敛融合、制胜核心、S1-S6、步骤批判、中循环批判、审计和报告。A-H 蓝图中的主分支、次分支、路线、S 步骤侧重、必需输出和循环策略会随任务上下文一并注入，避免不同场景继续共用泛化提示。

S1-S6 的专门方法为：S1 使用对手装备、OODA 环和体系脆弱性分析；S2 使用条令、演习复盘、战法本体和任务链审查；S3 使用反事实、TRIZ、效果链和简化推演；S4 使用能力-任务矩阵、DOTMLPF 和体系接口映射；S5 使用现役/在研装备、参数、成熟度和体系效能比较；S6 使用融合去重、多准则排序、需求卡片和九字段能力图像。每步后批判 Agent 检查证据、因果、覆盖、分支侧重与安全边界，失败时给出最小重试或定向 Recall 指引。

## 制胜机理落实

制胜机理不是单纯的确定性规则模块，而是拥有独立模型、独立 append-only session 和固定结构化输出契约的核心 Agent。Real 模式由该 Agent 消费基线 packet、正式证据、coverage 与冲突集，完成防御解构、制胜路径、效果链、能力映射、五档差距和能力画像建议；确定性引擎保留为治理层，负责对象契约、证据门控、L1/L2/L3 编排、定向再调、安全回退和审计追溯。

核心 Agent 按架构图执行四类资源投影：理论工具、战例材料、前沿情报、问题链。六步按防御解构、制胜路径、效果链、能力映射、差距量化、能力画像草案串联；每一步均在 trace 中记录输入/输出引用、证据 ID、置信度与假设。定向再调后，核心 Agent 使用更新后的 packet 和证据从指定节点恢复，而不是仅复用首轮规则结果。

L1 输出弱点地图、制胜路径、效果链和关键能力；L2 输出新概念、新技术、新手段、跨域移植与可行性；L3 负责去重归并、类别映射、五档差距、优先级和九字段文字能力画像。低置信或 coverage 不足会通过 `target_agent_id` 或 `target_capability_tag` 发起定向再调，补充结果写入 save point 后从目标层恢复。

## 交互过程可视化

工作台的“交互过程”页调用：

```text
GET /api/v1/runs/{run_id}/interactions?compact=true
```

页面通过持久化 SSE 在运行中实时更新，并在断线后按事件序号重放。紧凑投影保留五段业务主链、关键循环/门控事件、最多 12 个 Agent 摘要和最多 60 个前端事件卡片；完整审计数据仍保留在后端。页面提供：

- 编排器及活跃 Agent 的角色、Harness 和核心 Skill 摘要；
- Agent 筛选；
- 时间线展示任务启动、编排委派、任务接收、工具调用、工具结果、证据评分、保存点、基线 handoff、六步推理、L1/L2/L3、再调、审计和报告；
- 逐事件展开查看脱敏参数、质量评分、输入/输出对象引用、artifact refs、checkpoint ID 和结果状态。

接口从 trace 与独立 session 做白名单投影，使用统一脱敏器，不返回模型原始消息或其他 Agent 原始 session。

## Real 模式执行边界

Real 模式新增 Codex CLI 接入，默认由 Codex 承担编排器、四个基线 Agent、制胜机理核心、S1-S6 细化子 Agent、步骤/中循环批判、审计和报告的独立推理调用。每个回合使用隔离且 ephemeral 的 Codex 会话；本地 Harness 继续负责上下文投影、工具执行、证据材料化、对象契约、保存点和门控。Responses-compatible provider 保留为可选后端。

Codex 模式显式实现四层循环：S1-S6 每步经过批判 Agent 并最多重试一次形成内循环；有效步骤完成后由中循环批判 Agent 指定回溯点并最多重跑一轮；L1/L2/L3 的定向 Recall、补证与断点恢复构成受 `max_rounds` 约束的外循环；L4 在收敛后由编排器复核并有界调整 A-H 次分支和 S1-S6 执行强度。交互 Trace 分别记录子 Agent 完成、内循环、中循环、Recall、恢复节点和元循环重规划结果。

模型执行配置属于研究任务的受控元数据。工作台统一显示“Agent”，当前不暴露自定义 Agent 切换入口；新建真实任务固定进入 Codex Agent 后端。底层使用 API Key、兼容 HTTPS Base URL 和项目隔离 Home，不要求设备登录；Responses-compatible 代码仅作为后端兼容路径保留。API Key 只在 worker 环境读取。公开来源都会进入后续 `fetch_page`、证据评分和证据写入，模型原始消息不进入实时事件表。运行启动 trace 只记录 provider、模型名、URL 主机和环境变量名，不记录完整密钥或密钥值。

编排器、四个基线 Agent、核心制胜机理 Agent、审计 Agent 和报告 Agent 均可配置独立模型、Responses URL 与 API Key 环境变量名。任务创建时保存脱敏模型快照，Worker 按 Agent ID 路由真实调用；配置缺失或调用失败不会静默降级到 Fake。基线 Agent 使用“两阶段真实调用”：先以短请求执行 Hosted Web Search 并发现来源，再由该 Agent 的独立模型基于发现结果完成结构化专业推理，避免把长篇 JSON 生成与搜索流绑定在同一连接。Responses SSE 在收到终态事件时立即结束读取，并对可重试网络故障执行最多三次有界指数退避重试。

分析师必须在启动正式任务前确认研究主题、边界和关键假设。未确认时可以形成过程产物，但发布结论保持受限。每次运行额外生成 `architecture-acceptance.json`，分别给出运行结构完整性 `runtime_complete` 与交付发布条件 `release_ready`。

`architecture-acceptance.json` 当前还会逐次验证：独立 Agent Session、任务级工具/对象权限与预算记录、baseline wave 有界并发、结构化 map-reduce Packet、checkpoint/run.db 恢复链路，以及发生过失败时 handoff 文件是否实际持久化。

## 验收

自动验证覆盖各 Agent 的固定 output contract、Codex 场景运行画像、A-H 分支注入、Codex live search、S1-S6 图式计划、L4 有界重规划、国外装备分批深搜、Responses Web Search 来源适配、两阶段检索与推理、SSE 终态处理与读取超时/远端断连重试、网页正文段落引用、跨进程 API/worker 闭环、紧凑交互投影、工具事件、保存点、核心制胜机理 Agent、审计 Agent、报告 Agent 以及原始 session 不泄露。当前验证：`446 passed`；前端生产构建通过。

工作台任务管理支持创建、草稿更新、软归档、状态筛选和完整事件历史。草稿更新重新校验路线、Agent、轮次与 Real 执行配置；启动后的任务禁止修改，归档不删除证据、报告或审计产物。
# 制胜机理架构兼容实现

制胜机理链路同时落实详细架构图和三条核心业务路线。编排器在基线 Agent 汇总后生成可审计的 `WinningMechanismInput`，只包含问题框架、结构化 packet、证据索引、覆盖度、冲突、开放问题和轮次预算，不暴露其他 Agent 原始会话。

每次首轮或定向再调恢复都会动态生成 `WinningKnowledgeProjection`：理论工具库、战例库、前沿情报库和问题链均为本次运行投影，不建设额外知识系统。六步推理由 `WinningReasoningNode` 串联防御解构、制胜路径、效果链、能力映射、差距量化和能力画像生成；每个节点持久化输入引用、claim/evidence、置信度、假设和路线。

三条路线分别约束推理目标：

- 新制胜机理：从国际形势、潜在威胁和对抗场景出发，以新机制、新打法、新体系组合推导新质装备功能。
- 传统能力缺口：以传统场景、传统制胜、传统战法为基线，对比当前装备并形成能力补位与升级需求。
- 局部战争案例：多轮检索案例中的新能力、新模式、效果和不足，研判可迁移的未来布局方向。

专用接口 `GET /api/v1/runs/{run_id}/winning-mechanism` 返回输入包、四类资源投影、六步节点、L1/L2/L3 和再调请求。前端“制胜机理”页按同一结构展示门控与追溯关系。

## 四路基线 Agent 专业 Harness

四路 Agent 复用同一小内核，但拥有不同的技能、检索分轨、模型预算、证据关注点、停止条件和上下文可见性：

| Agent | 核心技能 | 重点产出 | 接收的上游交接 |
| --- | --- | --- | --- |
| 国际形势 | 战略 OSINT、威胁预测、力量态势跟踪 | 态势、威胁、战略格局、对手动向、预警指标与替代假设 | 无，保持独立研判 |
| 作战场景 | 场景工程、现代战场分析、敌方 COA 分析 | 场景框架、阶段演化、关键时间窗、环境约束和能力压力点 | 国际形势摘要 |
| 武器装备 | 装备 OSINT、能力对比、防御性反制分析 | 国外现役/在研装备、参数区间、成熟度、体系接口、局限和防御能力需求 | 国际形势、作战场景摘要 |
| 作战运用 | 综合运用、COA 比较、联合协同、经验迁移 | 作战约束、力量协同、备选方案、部署原则、失败模式和装备功能要求 | 国际形势、作战场景、武器装备摘要 |

路线执行波次由 `routes.yaml` 按 capability tag 声明，不再由 `accept_from` 隐式决定等待关系。新制胜路线执行 `国际形势 -> 作战场景与武器装备并发 -> 作战运用 -> 制胜核心`；传统缺口和战例学习路线执行 `可选国际形势 -> 作战场景与武器装备并发 -> 作战运用 -> 制胜核心`。`accept_from` 只控制 typed Packet 可见性，不授予原始模型消息或其他 Agent session 的读取权限。

每个 Agent 的 `research_policy` 约束多轨检索、目标信源数量、信源类型多样性、反证搜索、时间范围和停止条件。`model_profile` 独立控制 reasoning effort、输出预算和搜索上下文；`context_policy` 独立控制可见区段和 token budget。前端交互页可展开查看技能、工具、上游依赖、研究策略和输出契约。

## 2026-07-14 Real 三路线验收结果

三条路线已使用独立多模型配置完成 Real 闭环：

| 路线 | Run ID | 正式证据 | Recall | L1/L2/L3 | Audit | Release |
| --- | --- | ---: | ---: | --- | --- | --- |
| 新制胜机理 | `run-ef59c312-8b97-41ea-b5ba-016717b30dd4` | 10 | 0 | 全部通过（0.715） | approved | ready |
| 传统能力缺口 | `run-2ebc8344-5484-41ef-86ee-57a3cf56f692` | 8 | 1 | 全部通过（0.723） | approved | ready |
| 战例学习 | `run-63db8d9c-4590-4689-9e3c-6968a77acff3` | 5 | 1 | 全部通过（0.718） | approved | ready |

三次运行的 `runtime_complete` 与 `release_ready` 均为 `true`，且均具备编排器、制胜核心、审计、报告独立 Session、六步推理、九字段能力画像和完整 Delivery Manifest。详细记录见 `docs/testing/real-three-route-multi-model-acceptance-20260714.md`。

Real 三路线验收按用户要求先于本轮差异化 Harness 改造完成。Harness 改造后未重复向外部端点发送 Real 数据；改造后的验证由完整自动化回归和三路线 Fake E2E 承担，原 Real 产物与结果保持不变。

## Harness 改造后验收

- Python 全量回归：`442 passed`，仅 1 条 Starlette 第三方弃用警告。
- 前端：Vite 生产构建通过。
- Compose：配置校验通过。
- 三路线 Fake E2E：`new_winning_mechanism`、`traditional_gap`、`war_case_learning` 均 `completed`、`runtime_complete=true`、`release_ready=true`、`audit=approved`。
- 新制胜路线写入四种 typed 领域对象；传统缺口与战例路线按策略不强制国际形势，其余三种 typed 对象完整。
- 并发探针确认场景与装备在同一波次真实重叠执行，而非仅在计划中标记并发。
- 制胜核心的 `winning_core_v1`、激活 Skills、活动 Tools、phase 和停止结果均写入 Trace。

Fake E2E 产物位于 `outputs/fake-harness-acceptance-v1/`。
