# Pi Harness Python Replication Runtime Design

本文说明 `knowledgegraph.demand_discovery` 的当前运行时设计。它是 `pi_harness_python_replication_implementation_plan.md` 的落地说明，重点记录已经实现的 Python 版 Pi harness 复刻边界、demo 执行方式、输出位置和当前尚未迁移的能力。

## 1. Runtime 定位

当前 runtime 是需求挖掘模块的一条最小端到端竖切：

```text
provider stream
-> AgentLoop
-> DiscoveryHarness
-> domain tools
-> save point
-> DomainStore / trace
-> DemandReport summary
```

它证明真实或 fake provider 可以通过工具调用驱动领域对象写入，并在 save point 处形成可追溯的 source -> evidence -> candidate -> audit -> report 链路。

这条竖切不是完整需求挖掘产品能力。当前 demo 的 real mode 使用固定 task brief 要求模型按顺序调用工具；它不从真实资料中自动发现需求，也不把模型生成内容视为可采信结论。

## 2. 模块边界

代码入口位于 `src/knowledgegraph/demand_discovery/`：

- `harness/`：Pi-style agent runtime 复刻层。负责事件流、agent loop、phase、queue、save point、session、trace、context pack 和轻量 scheduler。该层不理解需求挖掘领域对象。
- `llm/`：provider 边界。包含 fake provider、Responses-compatible / Codex backend 请求构造、SSE 事件解析、模型配置和 `.env` 读取。该层不写领域状态。
- `domain/`：需求挖掘领域对象和工具。包含 `SourceRecord`、`EvidenceCard`、`CandidateDemand`、`AuditReport`、`DemandReport`、`DomainStore` 和 domain tools。
- `workers/`：worker role 标识和基础 prompt。当前用于 scheduler/context 复用测试，还不是完整多 agent 业务流程。
- `demo.py`：Python API 级 demo 编排。

CLI 入口位于 `scripts/demand_discovery_demo.py`。脚本只调用 `src` 中的核心能力，不承载核心 runtime 逻辑。

## 3. Pi 概念到 Python 的映射

| Pi / AgentHarness 概念 | Python 实现 | 说明 |
| --- | --- | --- |
| Provider stream | `llm.fake_provider.FakeProvider`, `llm.responses_adapter.ResponsesProvider` | 将 provider SSE 归一为 `ProviderEvent`，最终生成 `AssistantMessage`。 |
| Agent loop | `harness.agent_loop.AgentLoop` | 驱动 message lifecycle、provider request、tool execution 和 turn loop。 |
| Harness phase | `harness.agent_harness.DiscoveryHarness.phase` | 控制 `idle` / `turn` 生命周期，并在异常路径回到 `idle`。 |
| Runtime events | `harness.events.AgentEvent`, `harness.event_stream.AsyncEventStream` | 输出 agent/turn/message/tool/save point/settled 等运行事件。 |
| Active tools | `DiscoveryHarness.set_active_tools()` | turn 内更新只影响下一次 provider request。 |
| Injection queues | `steer()`, `follow_up()`, `next_turn()` | 保留 Pi-style 当前轮、停止后补充和下一 prompt 注入语义。 |
| Save point | `DiscoveryHarness._save_point()` | 在 `turn_end` 后 flush pending domain/trace proposals，并重建 context snapshot。 |
| Session store | `harness.session_store.*` | append-only 记录 message、active tools 和 save point。 |
| Domain trace | `harness.trace_store.DomainTraceStore`, `domain.store.DomainStore.trace_events` | 记录领域因果链，不与 UI/runtime event 混用。 |
| Context pack | `harness.context_pack.ContextPackBuilder` | 从 run state/domain/trace 摘要构造角色化上下文。 |
| Scheduler / worker | `harness.scheduler.DiscoveryScheduler`, `workers.roles` | 当前是轻量 worker run registry 和事件相关性骨架。 |

## 4. Fake Demo 执行

fake demo 不调用远程服务，也不需要 API key。它使用固定 fake provider 响应，按 source、evidence、candidate、audit、report 的顺序生成 tool call。

```powershell
python scripts\demand_discovery_demo.py --mode fake
```

默认输出：

- 控制台：候选需求标题、candidate id、evidence ids、audit conclusion、report title、trace event count、trace path。
- JSONL：`outputs/demand_discovery_demo.jsonl`。

该模式用于验证 provider stream、tool call、domain write、save point、audit、report generation 和 trace lineage 的离线闭环。

## 5. Optional Real Provider 执行

real mode 默认不执行，只有显式传入 `--mode real` 且配置 API key 后才会调用远程 provider。

推荐使用 Responses-compatible endpoint：

```powershell
python scripts\demand_discovery_demo.py `
  --mode real `
  --endpoint-mode responses_compatible `
  --base-url "https://your-compatible-host" `
  --model "your-model" `
  --output outputs\demand_discovery_real.jsonl
```

配置来源优先级：

1. 命令行参数。
2. 当前进程环境变量。
3. 仓库根目录 PowerShell 风格 `.env`。
4. 代码默认值。

支持的 `.env` 示例：

```powershell
$env:DEMAND_DISCOVERY_API_KEY="your-token"
$env:DEMAND_DISCOVERY_BASE_URL="https://your-compatible-host"
$env:DEMAND_DISCOVERY_MODEL="your-model"
$env:DEMAND_DISCOVERY_ENDPOINT_MODE="responses_compatible"
```

可先执行 dry run 检查脱敏后的 provider request 摘要：

```powershell
python scripts\demand_discovery_demo.py --mode real --dry-run-provider-request
```

dry run 只打印 endpoint mode、model、URL、payload keys 和 API key 环境变量名，不打印 API key、Authorization header、完整 prompt 或请求体。

## 6. Trace 与 Report 输出

当前 demo 输出为本地 JSONL，不写数据库：

- fake mode 默认写入 `outputs/demand_discovery_demo.jsonl`。
- real mode 可通过 `--output` 指定，例如 `outputs/demand_discovery_real.jsonl`。

JSONL 中包含领域对象和 trace 事件。领域 trace 用于重建 source -> evidence -> candidate -> audit -> report 的因果链；runtime event 只用于调试和 UI 进度，不应作为报告证据。

## 7. 当前没有迁移或未完成的能力

以下能力不在当前 runtime 竖切中：

- Pi 前端 UI、浏览器交互、完整会话树可视化和人工审核界面。
- 真实资料接入、网页/PDF/Markdown 阅读、RAG 检索和来源白名单治理。
- Horizon scanning 的持续扫描、弱信号聚类和主题演化。
- reader/synthesizer/audit worker 的真实 agent 编排和异步执行。
- debate、反证、补证任务生成和证据不足时的自动回退。
- 正式数据库持久化、恢复、并发锁和跨进程 session 管理。
- Markdown/HTML/PDF 正式报告发布器和引用格式渲染。
- Silver/Gold case、负样本、质量指标和专家评审量化门禁。

这些能力应在当前竖切稳定后逐步接入，避免把 harness 迁移、provider 适配和真实需求挖掘业务问题混在同一层处理。

## 8. 验证命令

需求挖掘 runtime 的核心回归命令：

```powershell
python -m unittest discover -s tests -p "test_demand_discovery*.py" -v
python scripts\demand_discovery_demo.py --mode fake
python -m unittest tests.test_src_extraction_package -v
```

文档索引检查：

```powershell
rg -n "pi_harness_python_replication_runtime_design|demand_discovery_demo|knowledgegraph.demand_discovery" docs src tests
```
