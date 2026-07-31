# Codex 多智能体接入模式

## 目标

系统新增 `codex` Real 执行后端。该模式参考 OpenOPC 的 Codex adapter：由本地运行时负责进程隔离、上下文投影、证据治理、保存点和门控；Codex CLI 只承担各角色的独立推理任务。

项目保留两种 Real Agent 接入模式：`responses` 对应自定义 Agent 适配器，`codex` 对应 Codex CLI 作为细化 Agent。`fake` 仅用于离线验收和回归测试；默认 Real provider 为 `codex`，但用户可以在任务界面切换到自定义 Agent 模式。

## 调用边界

每次模型回合执行一个独立的 `codex exec --json --ephemeral` 进程：

- 工作目录固定为项目根目录；
- 默认使用 `read-only` Codex sandbox，提示词同时禁止修改文件和系统状态；
- Prompt 通过 stdin 传入，不进入命令行或运行快照；
- 清除父 Codex 运行时的 `CODEX_THREAD_ID`、网络沙箱和 originator 环境变量，避免嵌套会话污染；
- 在 `outputs/runtime/codex-home` 建立可写的隔离 `CODEX_HOME`，API Key 模式写入权限为 `0600` 的隔离 `auth.json`，不修改用户全局 Codex 配置；
- 每次 `codex exec` 通过 `skills.config` 显式装载项目原生 Skill `js-equipment-agent-runtime`，再由 `agent_runtime` 注入当前角色的细化 Skill、Tool 与 Harness 契约；
- 制胜、批判和动态专用角色同时装载 `js-winning-shared-layer`，共享 Tree-of-Warfare 节点协议、DeepSearch/DeepResearch、证据治理、结构化交接与知识包访问规则；
- 严格 JSON 回合把仓库紧凑输出契约转换为 JSON Schema，并通过 Codex CLI 原生 `--output-schema` 约束最终消息，不再只依赖提示词要求；
- 需要公开资料检索的回合在 CLI 命令中显式设置 `web_search="live"` 和高上下文搜索，不依赖提示词自行决定是否联网；
- 解析 Codex JSONL，只接受最终 `agent_message`，线程 ID 和 usage 作为脱敏元数据保存；
- 每个业务 Agent、制胜子 Agent、批判 Agent、审计 Agent 和报告 Agent 均为独立会话，不共享原始消息。

## Agent 覆盖

Codex 模式覆盖：

1. 编排器：问题解析、路线判断和最小充分 Agent 选择。
2. 基线 Agent：国际形势、作战场景、武器装备、作战运用。
3. A-H 发现路径专业 Agent：
   - C 案例研究；
   - D 技术雷达；
   - E 对手动向监测；
   - F 体系对抗仿真；
   - G 跨域融合；
   - H 非传统安全；
   - 智能模式额外启用场景发散 Agent。
4. 跨背景、跨场景、跨分支的收敛融合 Agent。
5. 制胜机理核心与六个细化子 Agent：
   - S1 对手分析；
   - S2 作战运用审查；
   - S3 突破口思考；
   - S4 装备能力映射；
   - S5 装备现状与差距；
   - S6 能力图像综合。
6. 批判 Agent：步骤批判与中循环批判。
7. 审计 Agent、报告 Agent。

## 共享 Skill 与知识包层

所有 Codex CLI 角色接收四个共享 Skill：`codex_deep_search_shared`、`codex_deep_research_shared`、`codex_evidence_governance_shared`、`codex_structured_handoff_shared`。共享 Skill 不扩大权限；有效 Tool 仍取 Agent、Task、Skill 和 Harness Phase 的交集。

知识包包括公开证据索引、军事知识框架、装备本体、条令库、案例库、前沿技术库、短期运行记忆和经审计长期记忆。知识包是上下文投影与检索边界，不是事实权威；正式事实仍必须引用本次运行中真实存在的 EvidenceCard。短期/长期记忆只保存结构化、可追溯状态，不共享其他 Agent 原始会话。

## 按需动态专用子 Agent

主控仅在固定 Agent 无法覆盖一个可独立、上下文隔离有收益、可结构化合并且预算允许的专业缺口时生成动态角色，最多三个。每个动态角色都必须绑定：唯一任务、触发缺口、能力标签、共享 Skill、知识包、受治理 Tool、合并目标、输出字段、质量门槛、token 预算与停止条件。

动态角色使用固定的 `winning_dynamic_specialist` 治理模板启动独立 `codex exec --ephemeral` 会话，可并行执行；它不能招募新的 Agent、修改蓝图或扩大权限。结果只合并到声明的 S1-S6/convergence 节点，完成或耗尽预算后立即回收，Trace 保留实例 ID、Skill、知识包、合并目标和停止理由。

## A-H 动态发现蓝图

编排器先生成可执行 `discovery_blueprint`，包含主分支、最多两个次分支、专业 Agent、必需能力标签、交付物、执行波次和循环上限：

- A 新战法发现；
- B 传统能力缺口发现；
- C 局部战争案例经验；
- D 技术驱动发现；
- E 对手动向牵引发现；
- F 体系对抗博弈发现；
- G 跨域融合发现；
- H 非传统安全牵引。

专家模式尊重显式分支；智能模式由 Codex 元编排选择主次分支并先执行场景发散。蓝图会写入运行目录和 `round_summary.json`，恢复运行复用同一蓝图。

## 循环机制

### 内循环

每个 S1-S6 子 Agent 完成后，`winning_step_critic` 独立调用 Codex，检查输入遗漏、证据越界、跨步跳跃、结论空泛和安全边界。未通过时，反馈返回原步骤重跑；首版最多 2 次。

### 中循环

S1-S6 完成后，`winning_round_critic` 检查跨步骤因果连续性、路线侧重、覆盖和能力图像可追溯性。若发现断点，返回 `rerun_from_step`，从指定步骤重跑至 S6；首版最多 2 个中循环。

### 外循环

现有 L1/L2/L3 门控继续作为外循环：覆盖或置信度不足时生成定向 Recall，补证 Agent 完成后从 L1、L2 或 L3 指定节点恢复。外循环受任务 `max_rounds`、同目标 Recall 上限和证据门控约束。

运行 Trace 会记录 `winning_subagent_completed`、`winning_inner_loop_evaluated`、`winning_middle_loop_evaluated`、Recall 和恢复事件，前端交互页可按 Agent 查看。

### 元循环

元循环负责 A-H 主次分支选择、专业 Agent 波次生成和跨分支重规划。第 1 周期形成初始蓝图；基线 Agent 完成后，`convergence_fusion` 对不同背景、场景和分支的发现进行聚类、去重、冲突保留、优先级排序和跨分支关联；第 2 周期由 Codex 编排器复核跨分支线索、冲突、开放问题与覆盖缺口，可新增最多两个有效次分支，并把 S1-S6 调整为 `skip/light/standard/deep`。Harness 只接受 A-H、S1-S6 和合法强度，越界或不可执行建议会被拒绝。更新后的蓝图写回运行目录并进入制胜机理输入。Trace 记录 `discovery_meta_loop_evaluated`、`discovery_convergence_completed`、`replan_required` 和步骤调整。

S1-S6 不再固定全量串行执行。A-H 蓝图为每步生成图式计划，允许重点、标准、弱化和跳步；中循环回溯会自动定位到下一个仍处于 active 状态的步骤。

每个 S 节点统一输出 `{recognition, evidence_refs, confidence, next_action}`。`next_action` 只能是 continue、parallel、backtrack、recall 或 stop，并给出目标步骤与可审计理由；这使回溯、跳步、并行辅助和停止决策可以由 Harness 校验，而不是依赖隐藏思维过程。

## 配置与运行

确认 worker 主机已安装 Codex CLI：

```bash
codex --version
```

CLI 启动：

```bash
python3 scripts/run_deep_research.py \
  --mode real \
  --provider codex \
  --topic "低空无人体系装备能力缺口" \
  --research-route traditional_gap \
  --run-id codex-gap-demo
```

Web 工作台统一显示为“Agent”，不暴露 Codex CLI 或自定义 Agent 的技术接入名称；新建任务当前固定使用 Codex Agent 后端。后端仍保留 Responses-compatible 兼容代码，但暂不在前端提供切换入口。任务只保存模型名、API URL 和密钥环境变量名，明文密钥只存在于 API/Worker 部署环境；底层 Codex CLI 每次运行仍使用输出目录中的隔离 `CODEX_HOME`。

本轮细化能力只进入 `codex` 模式：编排器、发现分支、收敛、S1-S6、批判、审计和报告的正式 Skill/Harness 由 Codex CLI 运行时读取；`responses` 自定义 Agent 适配器保留原有调用路径。

本地真实 Codex 模式可直接运行：

```bash
./scripts/start-local.sh
```

`start-local.sh` 默认优先读取 gitignored 的 `.env.codex`，并可设置 `EQUIPMENT_DR_CODEX_INHERIT_CONFIG=0`，避免继承全局 `config.toml` 中的 Provider 或 Base URL；仅当 `.env.codex` 不存在时才回退到 `.env`。前端不再提供执行模式、模型、URL、密钥变量或自定义 Agent 的配置入口，所有新建和草稿更新任务均采用服务端环境配置。

首次使用时填写：

```dotenv
EQUIPMENT_DR_MODE=real
EQUIPMENT_DR_PROVIDER=codex
EQUIPMENT_DR_CODEX_BASE_URL=https://api.openai.com/v1
EQUIPMENT_DR_CODEX_API_KEY_ENV=EQUIPMENT_DR_CODEX_API_KEY
EQUIPMENT_DR_CODEX_API_KEY=你的服务端密钥
EQUIPMENT_DR_CODEX_INHERIT_CONFIG=0
```

运行时适配器从 `EQUIPMENT_DR_CODEX_API_KEY_ENV` 指定的服务端环境变量取值，在隔离 `CODEX_HOME/auth.json` 中建立 `apikey` 认证，并通过 Codex CLI 的 `openai_base_url` 配置覆盖传入 Base URL。Base URL 必须为 HTTPS，且不能携带用户名、密码、查询参数或片段。

只要任务配置了 API Key 或 Base URL，适配器会自动停止继承用户全局 `config.toml`，防止个人 `model_provider`、Base URL 或其他 Provider 配置覆盖项目任务。未配置 API/URL 且显式选择设备登录兼容模式时，才允许继承用户配置。

工作台从 API Catalog 读取 Agent 默认 URL、密钥环境变量名和运行组件可用状态，不在前端重复维护另一套配置。Agent 配置页一次只编辑一个专用 Agent 的模型、URL 和密钥环境变量，避免同时渲染全部角色。任务启动前，API 会同时检查默认 Provider 和所有逐 Agent 覆盖所引用的密钥环境变量；缺失时任务保持草稿状态，并把缺失的环境变量名返回工作台，不会进入 Worker 队列。

设备登录仅作为兼容性回退：当直接通过 CLI 启动、未配置 Codex API Key 环境变量并显式设置 `EQUIPMENT_DR_CODEX_SOURCE_HOME` 时，适配器可复用该目录中的 `auth.json`。Web/API 新建的 Codex 任务默认走 API Key + Base URL 模式。

## 六业务 Agent 性能编排

真实 Codex CLI 模式采用阶段级流水线，而不是等待一个 Agent 完成检索、分析和证据处理后才启动下游：

1. 所有被选中的业务 Agent 提前启动检索阶段，并受全局自适应并发门控约束。
2. 依赖关系只阻塞结构化分析阶段；作战场景、武器装备、作战运用和体系对抗可提前完成各自检索。
3. 检索分为已知来源快车道和开放搜索通道；两路结果按规范化 URL 合并，共享材料化缓存，但每个 Agent 保持独立分析。
4. Codex Prompt 使用紧凑 RoleCard，Skill、Tool、Harness 和输出契约由运行时编译一次，任务调用只传递任务差异、目标化上游 Packet 和证据。
5. 正式停止由证据充分度决定：最低证据数、独立来源域、反证或限制、材料化和角色结构门控必须同时满足；目标数量是软目标。
6. 结构化结果只缺少局部字段时执行无联网局部修复，不重新运行完整检索和分析。
7. 六类增量知识库保存经接受 Packet 的紧凑投影、来源 URL、版本和最后核验时间，只用于导航和变化检测，不能替代本轮正式证据。

核心业务分析保持 `gpt-5.5/high`；来源导航使用较低输出冗余和中等推理预算，格式修复使用中等预算。全局调用并发默认从 4 开始，根据网关延迟和失败在 2–6 之间调整，避免高并发导致第三方网关排队。

## 安全与部署注意事项

- 隔离 Home 必须位于 worker 可写目录；容器部署需为 `outputs/runtime` 提供持久写权限。
- Codex 的认证密钥由 Worker 环境变量提供；任务、Trace、快照和 API 响应不会复制密钥值。
- Base URL 只以完整配置进入执行参数，运行审计快照仅记录主机名。
- 若用户 Codex 配置指向自定义模型端点，生产部署必须单独完成端点信任、网络出口和数据出境审查。
- Codex 搜索结果仍只是待材料化线索，必须经过本地抓取、SSRF 防护、正文定位、质量评分与正式证据门控。
