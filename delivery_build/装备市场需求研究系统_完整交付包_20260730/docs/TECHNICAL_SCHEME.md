# 装备能力图像 Deep Research 多智能体系统技术方案

## 1. 交付定位

系统回答“需要发展具备什么功能的产品”，并给出来源制胜逻辑、关联场景、证据、能力差距和优先级。首版同时覆盖：新制胜机理牵引的新质能力、传统场景/战法下的能力不足与升级需求、局部战争案例牵引的未来布局方向。

## 2. 总体主链

```text
分析师输入
  -> 编排器解析问题与研究路线
  -> 动态选择 baseline agents
  -> 隔离上下文/权限的 subagent wave
  -> 汇总初检与 coverage
  -> 制胜机理四类资源 + 六步推理
  -> L1 制胜逻辑 -> L2 概念创新 -> L3 能力画像
  -> 定向再调并从门控断点恢复
  -> 五判据审计
  -> 文字能力画像、报告和审计产物
```

## 3. 多智能体设计

- 小内核、大 harness：`AgentLoop` 负责消息、工具和事件循环；Harness 负责 snapshot、权限、预算、session、save point、压缩与恢复。
- Registry 分离：Agent、Tool、Provider 独立配置；六类业务 Agent 组成候选池，由编排器按主题选择最小充分集合，支持子集和架构必需补充。
- 上下文差异化：agent 只看到任务约束、必要摘要、证据索引和允许的领域对象，不共享其他 agent 原始 session。
- 权限差异化：执行层依据 agent 和 task scope 强制工具权限，审计 agent 使用只读投影。
- 通信结构化：通过 MessageBus 传递 task、finding packet、recall request、stage output 和审计事件，不以共享长对话代替通信协议。
- Subagent 只用于真正可拆分的工作；调度器限制 wave 并发、失败传播和预算，不以 agent 数量作为价值指标。

baseline 业务候选池包括国际形势、作战场景、武器装备、作战运用、对手动向监测和体系对抗仿真。统一输出 `BaselineFindingPacket`，制胜机理消费 capability tags 与 packet 集合，不依赖固定 agent 名称。

## 4. 制胜机理

四类资源投影为理论工具、战例材料、前沿情报和问题链。六步推理依次为防御解构、制胜路径、效果链、能力映射、差距量化、图像生成。

L1/L2/L3 每层生成结构化输出并经过门控。低覆盖或低置信时，`RecallCoordinator` 使用 `target_agent_id` 或 `target_capability_tag` 路由补充任务；总轮次最多 5，同一目标最多 3 次，补充完成后从原层断点恢复。无法覆盖时生成 Agent 建议并在报告中明确限制。

## 5. 联网与证据

首版以公开联网检索为主，不设置来源域名白名单。Real 模式通过 Responses 内置 `web_search` 执行 agentic search，并导出搜索查询、引用和完整 sources。来源 URL 不直接成为正式证据：系统继续通过 URL/DNS/IP/重定向/TLS/响应大小控制阻断 SSRF 和不安全抓取，材料化原文与简化正文，从真实网页选择支撑段落并保存位置。

证据按相关性、来源透明度、时效性、直接支撑和提取质量评分。低质量、重复或抓取失败材料可保留为研究材料和诊断，但不能进入正式 evidence IDs。正式报告只引用已接受证据；冲突和覆盖限制显式呈现。

## 6. 企业运行时

- CLI：离线 fake、真实 Responses、子集 agent、恢复与配置覆盖。
- API：版本化 FastAPI 路由、任务创建/草稿更新/软归档/历史查询、运行状态、catalog、持久化实时事件、SSE replay、summary、证据、制胜阶段、能力画像、报告、trace、artifact 和 manifest。
- Worker：共享 SQL 队列跨实例领取任务，运行状态与结果持久化；完成后自动生成交付 manifest。
- Web：React/Vite 企业研究工作台，支持新建研究、草稿编辑、软归档、历史筛选、完整事件历史、动态 coverage、运行中 Agent/工具实时交互时间线和运行产物查看。Real 模式可直接配置模型名、Responses HTTPS URL 和 worker 密钥环境变量引用。
- 部署：API/worker/web Compose profile，共享持久卷；生产可将 SQLAlchemy URL 切换至 PostgreSQL，并在目标环境网关接入 OIDC、TLS 和出口代理。

模型执行支持两种运行配置：`fake` 用于离线交付与稳定回归；`real` 使用 Responses 兼容 HTTPS 模型端点。工作台可在创建任务时配置模型 URL、模型名和 worker 密钥环境变量名。API Key 不经浏览器传输，不写入 RunView、session、trace、报告或交付 manifest；worker 在启动环境中读取指定环境变量。模型连接元数据被纳入运行配置指纹，恢复任务时不能静默切换模型或端点。

基础 RBAC：analyst 可创建和查看研究对象；reviewer 可读报告与 artifact；auditor/admin 可读 trace 和 manifest。生产身份认证需由目标环境 OIDC/网关替换开发 header 身份边界。

## 7. 输出契约

每次完整运行输出一份深度研究主报告、分支专用收敛产物、能力画像、轮次摘要、领域流水、trace、独立 agent sessions、artifacts、checkpoint/run DB 和 SHA-256 manifest。B 分支额外输出需求卡片、能力全景图和推理回溯索引；需求卡片以与 query 直接匹配的具体待发展武器装备为主对象，优先覆盖无人作战平台、导弹/精确弹药及其他承担歼灭、打击、拒止、威慑任务的战斗装备，并包含装备构型、发展方式、关键指标、优先级、支撑场景和证据链。

报告综合中间专业 Agent 的实质研究结论与制胜分析 S1-S6，不写“哪个 Agent 做了什么”的过程性描述，而是按业务主题深度归纳核心规律、因果机制、未来场景、能力域与指标、装备形态、反证和适用边界。每项关键结论必须体现深度性、创新性、前瞻性和军事价值性：解释机制、说明相对基线的新增价值、标明未来触发条件与不确定性，并落到任务效能、体系韧性和建设优先级。Agent Packet、S1-S6 节点和证据关系仅作为 B 分支可回溯索引的一部分。

A 分支收敛目标为 3 种新战法、5 种战法组合、8 大能力域、30 项能力指标及关联装备形态；B 分支交付需求卡片、能力全景图和含可回溯推理链的深度报告；C 分支交付 6 条案例规律、3 类高置信未来场景和覆盖 4 大新兴装备类别的需求图像。D-H 依据技术、对手、体系、跨域或非传统安全驱动形成同等深度的规律—场景—能力—指标—装备形态组合。门槛未满足时披露真实完成度和补研缺口，禁止使用同义改写凑数。

## 8. 当前交付边界

离线 fake 闭环、SQLite 企业验收 profile、Web 构建和 Compose 配置可自动验收。真实模型/公网 smoke、PostgreSQL/Redis 高可用、OIDC、TLS、正式出口代理、容量压测和浏览器视觉基线必须在目标部署环境使用实际基础设施参数复验，系统不伪造这些环境性结论。

交付成熟度、投产前 P0 项和后续 P1/P2 演进见 `docs/ENTERPRISE_DELIVERY_AUDIT.md`。
