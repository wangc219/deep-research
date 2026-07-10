# Pi Agent Kernel 与 Coding-Agent Harness 设计分析

调研对象：`earendil-works/pi`，当前源码快照位于本仓库 `reference/pi/`，文件夹内容与调研源码一致，调研时 HEAD 为 `c5582102f51b143fadc05180e0f8aed050e923b3`。

本文聚焦两个层面：

1. `packages/agent` 中 agent kernel 的设计。
2. `packages/coding-agent` 如何围绕 kernel 构建 coding agent harness，并通过工程化优化支撑真实使用。

## 1. 总体判断

Pi 的核心特色不是“代码量很少”，而是“kernel 很克制”。它把 agent 的最小运行闭环放在 `pi-agent-core`：消息、事件、工具调用、上下文转换、队列、流式输出。面向真实 coding 场景的复杂度则留给 `pi-coding-agent` harness：会话、扩展、资源加载、模型认证、TUI/RPC/SDK、多模式运行、压缩、分支、项目 trust 等。

这是一种典型的分层设计：

```text
pi-ai
  多 provider LLM / streaming / tool schema / usage / OAuth

pi-agent-core
  Agent loop kernel: turn、tool call、event、context transform

packages/agent/src/harness
  通用 AgentHarness 方向：session + durable config + snapshot + hooks

pi-coding-agent
  产品级 harness: tools、sessions、resources、extensions、modes、TUI/RPC/SDK
```

从学习角度看，Pi 最值得借鉴的是：它没有把 coding agent 的所有问题塞进 agent loop，而是用一个小 kernel 加一层可替换、可恢复、可扩展的 harness 来组织复杂性。

## 2. Agent Kernel 的核心设计

### 2.1 Kernel 的职责边界

`packages/agent/src/agent-loop.ts` 是最小 agent loop。它不负责：

- 会话文件怎么存；
- skills/prompt templates 怎么加载；
- 工具权限怎么确认；
- UI 怎么渲染；
- provider API key 怎么刷新；
- 扩展从哪里发现。

它只关心：

- 当前上下文；
- 模型流式响应；
- 工具调用和工具结果；
- steering/follow-up 队列；
- turn/agent/message/tool 事件；
- 下一轮是否继续。

这种职责边界使 `agent-loop` 可以被 `Agent`、通用 `AgentHarness`、`coding-agent` 重用。

### 2.2 AgentMessage 与 LLM Message 分离

Pi kernel 的关键抽象之一是区分：

- `AgentMessage`：agent/harness 内部消息，可包含 custom、UI-only、branch summary、compaction summary 等非 provider 原生消息。
- `Message`：LLM provider 能理解的 `user` / `assistant` / `toolResult` 消息。

转换路径是：

```text
AgentMessage[]
  -> transformContext()
  -> AgentMessage[]
  -> convertToLlm()
  -> Message[]
  -> provider
```

`transformContext` 用于压缩、裁剪、注入上下文；`convertToLlm` 用于过滤或降级自定义消息。这个设计把“应用内部上下文治理”和“provider 协议兼容”拆开，避免 UI/扩展/会话结构污染 LLM 层。

### 2.3 事件流是 kernel 的主观察面

kernel 把一次运行抽象成标准事件：

- `agent_start`
- `turn_start`
- `message_start`
- `message_update`
- `message_end`
- `tool_execution_start`
- `tool_execution_update`
- `tool_execution_end`
- `turn_end`
- `agent_end`

这使 TUI、RPC、SDK、session persistence、extension hook 都可以挂在同一套事件上。尤其是 streaming 场景中，`message_update` 可以承载 provider 的增量事件，而 `message_end` 是消息落库和后处理的稳定点。

### 2.4 Tool Call 机制

Pi kernel 的工具调用有几个值得学习的细节：

1. 工具 schema 使用 TypeBox，便于验证和序列化。
2. 工具执行默认并行，工具自身可声明 `executionMode: "sequential"` 强制串行。
3. 工具调用前有 `beforeToolCall`，可阻断或修改参数。
4. 工具调用后有 `afterToolCall`，可改写结果、错误状态或 `terminate`。
5. 工具结果作为标准 `toolResult` 消息进入后续上下文，而不是只作为临时 side effect。

这套机制使工具调用既是 LLM 协议的一部分，也是 harness/extension 的控制点。

### 2.5 Steering 与 Follow-up 队列

Pi 区分两类排队消息：

- `steering`：运行中插入，用于影响下一次 assistant response。
- `follow-up`：agent 本来要停时，再追加新用户消息继续跑。

`agent-loop` 在安全点 drain 队列，而不是在任意 streaming 中断 provider 请求。这种设计避免了“用户新输入直接破坏当前 turn 状态”的问题。

### 2.6 `prepareNextTurn`：kernel 与 harness 的关键接口

`agent-loop` 在每个 `turn_end` 后调用 `prepareNextTurn`。这是 harness 更新下一轮状态的关键 save point：

- flush pending session writes；
- 重新读取 session/context；
- 重新生成 system prompt；
- 刷新 model/thinking/tools/stream options；
- 将新 snapshot 交回 kernel。

这个接口非常重要。它让 harness 可以在一个 agent run 内更新下一轮配置，同时保证当前 provider 请求不被中途篡改。

## 3. 通用 AgentHarness 的设计方向

Pi 在 `packages/agent/src/harness` 中实现/探索了一个更通用的 `AgentHarness`。它位于低层 loop 之上，目标是把 agent loop 包装成可恢复、可持久化、可 hook、可资源化的运行单元。

### 3.1 Harness 不是 loop，而是运行编排器

`AgentHarness` 的职责包括：

- session persistence；
- runtime config；
- resource resolution；
- operation phase locking；
- pending session writes；
- hook/event reduction；
- compaction 与 branch summary；
- queue draining；
- provider stream options snapshot。

这说明 Pi 的设计把“模型调用循环”和“agent 应用运行时”分开了。低层 loop 像内核调度器，harness 像进程运行环境。

### 3.2 四类状态模型

`agent-harness.md` 明确把状态分成四类：

1. Harness config：最新运行配置，如 model、thinking level、tools、active tools、resources、stream options、system prompt。
2. Turn snapshot：某一轮 LLM 调用实际使用的冻结视图。
3. Session：已持久化的 append-only 状态。
4. Pending session writes：运行中接受但需要按顺序落库的写入。

这个模型解决了一个常见 agent bug：运行中某个 hook 改了 model/tools/resources，当前 provider 请求到底应该不应该被影响？Pi 的答案是：不影响当前 turn，只影响下一次 turn snapshot。

### 3.3 Phase 与结构性操作

通用 harness 引入显式 phase：

```ts
type AgentHarnessPhase = "idle" | "turn" | "compaction" | "branch_summary" | "retry";
```

`prompt`、`compact`、`navigateTree` 这类结构性操作要求 idle。`steer`、`followUp`、runtime config setter 可以在 turn 中按规则进入队列或影响下一轮。这个设计避免多个结构性操作并发破坏 session tree 或 pending writes 顺序。

### 3.4 Semi-durable 设计

Pi 没有幻想“完整持久化 JS runtime”。`durable-harness.md` 很清楚地指出：工具实现、模型对象、扩展 handler、resource loader、system prompt callback 都是 host app 的运行时依赖，不能可靠序列化。

因此它选择 semi-durable：

- session 是 durable append-only state tree；
- harness 把自己拥有的可序列化状态写入 session；
- host app 在 resume 时重新提供工具、模型、扩展、资源加载器；
- provider stream 不可恢复，只能从 durable boundary 重启或标记 interrupted。

这个判断很务实，尤其适合 coding agent：文件系统和 shell side effect 不一定幂等，未完成 tool call 默认不应自动重跑。

## 4. Coding-Agent Harness 的实现优化

`pi-coding-agent` 并没有直接使用通用 `AgentHarness` 完成所有功能，而是有自己的产品级 `AgentSession` / `AgentSessionRuntime`。这部分是 Pi 当前最完整的 harness 实现。

### 4.1 `createAgentSession`：产品级装配入口

`createAgentSession()` 负责把下面组件装配起来：

- `SessionManager`
- `SettingsManager`
- `ModelRegistry`
- `AuthStorage`
- `DefaultResourceLoader`
- `Agent`
- built-in/custom/extension tools
- extension runner

它给底层 `Agent` 注入：

- `convertToLlm`
- `streamFn`
- `onPayload` -> `before_provider_request`
- `onResponse` -> `after_provider_response`
- `transformContext` -> extension `context`
- queue modes、transport、thinking budgets、retry settings

也就是说，`Agent` 仍然是 kernel，`AgentSession` 把真实 coding agent 的环境和策略注入 kernel。

### 4.2 `AgentSession`：coding harness 的中心

`AgentSession` 是当前 coding-agent 最重的类，承担产品级 harness：

- prompt 入口；
- slash command / prompt template / skill 展开；
- before-agent-start extension hook；
- agent event 到 session persistence 的映射；
- tool hook 安装；
- tool registry 刷新；
- model/thinking/tools 切换；
- compaction；
- branch navigation；
- bash execution；
- export/import；
- extension binding。

这种集中有维护成本，但也体现出产品 harness 的复杂性：真实 coding agent 不是只跑一个 LLM loop，而是要对接会话、工具、UI、资源、扩展和恢复。

### 4.3 消息落库放在 `message_end`

`AgentSession` 订阅 kernel event，在 `message_end` 时持久化：

- `custom` 消息写成 custom message entry；
- `user` / `assistant` / `toolResult` 写成 regular message entry；
- assistant message 同时用于 retry 和 compaction 判断。

这个点很关键：落库点选择 `message_end`，不是 streaming delta，也不是 turn end。这样既能保证最终消息完整，又能保持 transcript 顺序。

### 4.4 Tool Registry 优化

coding-agent 的工具来源有三类：

- built-in tools：`read`、`bash`、`edit`、`write`、`grep`、`find`、`ls`；
- SDK custom tools；
- extension registered tools。

`AgentSession._refreshToolRegistry()` 把它们统一成 tool definitions，再生成：

- `_toolDefinitions`
- `_toolPromptSnippets`
- `_toolPromptGuidelines`
- `_toolRegistry`
- active tools

同名 extension tool 可以覆盖 built-in tool。工具 prompt snippet/guidelines 只在工具 active 时进入 system prompt。这比“所有工具说明永远塞进 prompt”更节省上下文，也更符合可控 harness 的思想。

### 4.5 ResourceLoader：资源系统与 trust 分离

`DefaultResourceLoader` 负责加载：

- `AGENTS.md` / `CLAUDE.md`
- `SYSTEM.md` / `APPEND_SYSTEM.md`
- skills
- prompt templates
- themes
- extensions
- Pi packages

它还处理 project trust：project-local settings/extensions/packages 只有在信任后加载；全局和 CLI extension 可先加载，并可参与 `project_trust` 决策。

这体现了一个实用原则：项目配置不是天然可信输入。虽然 Pi 不提供 sandbox，但至少不让仓库静默加载本地 TS extension。

### 4.6 Extension 作为 harness 扩展面

Extension 并非只监听日志，而是进入 harness 的多个控制点：

- 修改 system prompt；
- 修改 context；
- 修改 provider payload；
- 拦截 tool call；
- 改写 tool result；
- 注册工具/命令/快捷键/flags；
- 注册 provider/OAuth；
- 修改 UI；
- 触发 compaction；
- append custom entries；
- 控制 active tools；
- 在 command context 中 new/fork/switch session。

这使 coding-agent harness 变成可编程运行时。Pi 选择不内置 MCP、plan mode、sub-agent、权限弹窗，而是让 extension 用这些 hook 自己实现。

### 4.7 `AgentSessionRuntime`：会话替换与 cwd-bound 服务

`AgentSessionRuntime` 负责当前 session 与 cwd-bound services 的生命周期。切换 session、new session、fork、import 时，它会：

1. 触发 `session_before_*`，允许 extension 取消；
2. 触发 `session_shutdown`；
3. invalidate 旧 extension context；
4. 创建新 cwd 的 services；
5. 创建新 `AgentSession`；
6. rebind UI/session。

这个设计解决了一个细节问题：coding agent 的资源加载、settings、project trust、extensions 都与 cwd 相关。切换到另一个 session 可能意味着另一个 cwd，必须重建整套 cwd-bound runtime，而不是只换一份消息历史。

### 4.8 多模式共享同一运行核心

Pi 支持：

- interactive TUI；
- print/text；
- JSON event stream；
- RPC；
- SDK。

这些模式不是各跑一套 agent，而是围绕 `AgentSession` / `AgentSessionRuntime` 绑定不同 UI context 和 command actions。这样可以让 extension、session、tool、model、resource 行为尽量一致。

## 5. 值得学习的设计模式

### 5.1 Small kernel, rich harness

不要把所有产品逻辑放进 agent loop。loop 只负责稳定的计算模型；harness 负责应用态复杂性。

### 5.2 Snapshot over mutation

运行中配置变更只影响下一轮 snapshot，而不是改当前 provider 请求。这能显著降低并发和 streaming bug。

### 5.3 Append-only session as source of truth

Pi 用 JSONL tree 记录消息、模型变化、thinking level、compaction、branch summary、labels、custom entries。它把 session 当作 durable state，而不仅是聊天记录。

### 5.4 Extension hooks need event-specific reducers

不同 hook 的返回语义不同：

- `context` 返回新 messages；
- `before_agent_start` 聚合 custom messages 和 chained system prompt；
- `tool_call` 可 block；
- `tool_result` 逐步 patch；
- `session_before_*` first cancel wins。

Pi 没有用一个通用 “plugin return any” 草率处理，而是每类事件有自己的 reducer 语义。

### 5.5 Runtime dependency 不强行持久化

工具实现、provider handler、extension code 不能可靠写入 session。Pi 只持久化可序列化配置和结果，恢复时由 host app 重新提供 runtime dependencies。这是 agent 框架里很重要的工程判断。

### 5.6 Resource provenance 与 conflict diagnostics

Pi 在资源加载时记录来源，包括 global/project/package/cli/extension，并报告冲突。这对于可扩展系统很重要，否则用户很难知道某个 skill/tool/command 到底从哪里来。

## 6. 局限与风险

### 6.1 通用 AgentHarness 与 coding-agent harness 仍有重叠

`packages/agent/src/harness` 显示了通用 harness 的方向，但 `pi-coding-agent` 当前仍主要依赖自己的 `AgentSession`。这说明项目正处在“抽象沉淀中”：产品层已有成熟实践，通用层正在把这些经验往 core harness 收敛。

### 6.2 `AgentSession` 和 Interactive Mode 体量偏大

`AgentSession` 和 `interactive-mode.ts` 都是大文件，说明产品 harness 复杂度已经集中到少数模块。短期有利于快速迭代，长期需要继续拆分边界。

### 6.3 Extension 能力强，安全边界弱

Extension 运行本地 TS/JS，具有当前用户权限。Project trust 只控制是否加载项目本地 extension，不是 sandbox。复杂自动化场景仍需 Docker/VM/OpenShell 等外部隔离。

### 6.4 不是 fully durable

Pi 明确承认 provider stream 不可恢复，未完成 tool call 也不能默认重跑。它选择保守恢复策略，这是正确但也意味着无法像 workflow engine 一样完整 replay 所有中间状态。

## 7. 对学习 Agent 设计的启发

如果要借鉴 Pi，可以按以下优先级学习：

1. 先学习 `agent-loop`：理解最小 agent kernel 应该包含什么、不包含什么。
2. 再学习 `Agent`：如何把 loop 包成 stateful runtime，提供 prompt/continue/subscribe/queue。
3. 再学习 `AgentHarness` 文档：理解 snapshot、phase、pending writes、durable session 的设计思想。
4. 最后学习 `AgentSession`：真实 coding agent 如何把 session、tools、extensions、resources、modes 接入 kernel。

Pi 的最大价值在于它证明了：一个 agent 项目可以既保持内核简洁，又在 harness 层提供产品级完整性。对于想设计 agent framework 的开发者，Pi 最值得复用的不是某个工具实现，而是“kernel 与 harness 的分工方式”。

## 8. 源码证据索引

以下路径均相对本仓库根目录。

- `reference/pi/packages/agent/src/agent-loop.ts`：低层 agent loop、turn 循环、tool execution、steering/follow-up、`prepareNextTurn`。
- `reference/pi/packages/agent/src/agent.ts`：stateful `Agent` wrapper、queue、event subscription、loop config 注入。
- `reference/pi/packages/agent/src/types.ts`：`AgentMessage`、`AgentEvent`、`AgentLoopConfig`、tool hooks、execution mode。
- `reference/pi/packages/agent/src/harness/agent-harness.ts`：通用 harness 实现，turn snapshot、pending writes、compaction、tree navigation、tools/resources update。
- `reference/pi/packages/agent/docs/agent-harness.md`：harness lifecycle、state model、save point、phase、hooks 设计说明。
- `reference/pi/packages/agent/docs/durable-harness.md`：semi-durable harness 与 session recovery 设计。
- `reference/pi/packages/coding-agent/src/core/sdk.ts`：`createAgentSession()` 装配入口，向 `Agent` 注入 stream/context/provider hooks。
- `reference/pi/packages/coding-agent/src/core/agent-session.ts`：coding-agent 产品级 harness 中心。
- `reference/pi/packages/coding-agent/src/core/agent-session-runtime.ts`：session replacement、fork/new/resume/import 的 runtime 生命周期。
- `reference/pi/packages/coding-agent/src/core/agent-session-services.ts`：cwd-bound services 创建，绑定 settings、model registry、resource loader。
- `reference/pi/packages/coding-agent/src/core/resource-loader.ts`：资源加载、project trust、packages/extensions/skills/prompts/themes。
- `reference/pi/packages/coding-agent/src/core/extensions/runner.ts`：extension event reducer 与 runtime binding。
- `reference/pi/packages/coding-agent/src/core/extensions/types.ts`：extension API、context、UI、tools、provider registration。
