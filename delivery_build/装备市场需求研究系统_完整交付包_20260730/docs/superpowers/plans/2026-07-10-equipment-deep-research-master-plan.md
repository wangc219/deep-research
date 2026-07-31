# 装备能力图像 Deep Research 多智能体系统总实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于现有 `equipment_deep_research` 骨架，交付一个支持动态多智能体、真实联网多轮研究、制胜机理 L1/L2/L3 推理、定向再调、证据审计、文字装备能力画像以及企业级 Web 研究工作台的前后端一体化系统。

**Architecture:** 采用“小 AgentLoop、大 Harness”的通用运行时，所有智能体复用同一执行内核，但通过独立上下文投影、工具权限和领域对象读写权限形成真实差异。编排器以能力标签生成 `ResearchPlanGraph`，按 Map-Reduce-Refine 波次运行可拆分 subagent，通过结构化对象流转信息。FastAPI 服务通过 application service 调用研究内核，独立 worker 执行长任务，React 工作台通过 JSON API 和可重放 SSE 完成研究发起、过程监控、证据审阅、制胜机理复核、报告确认与导出。

**Tech Stack:** Python 3.11+、FastAPI、Pydantic 2、SQLAlchemy 2、Alembic、PostgreSQL、Redis、PyYAML、requests、BeautifulSoup4、pytest、Responses-compatible HTTP API、默认模型 `gpt-5.5`；React 19、TypeScript、Vite、Ant Design 5、TanStack Query、Zustand、React Flow、ECharts、Vitest、Playwright。

## Global Constraints

- 正式运行入口位于 `src/equipment_deep_research/` 与 `scripts/run_deep_research.py`，`reference/` 只读。
- 默认模型固定为 `gpt-5.5`，允许通过环境变量或 provider 配置覆盖。
- 正式源码不保留旧演示执行链路，也不通过外部命令行代理模型调用。
- 首版必须支持 `new_winning_mechanism`、`traditional_gap`、`war_case_learning` 三条研究路线。
- 默认四类基线 agent 是可替换预设；必须支持全量、任意子集和自定义 agent。
- 智能体差异必须由执行层强制落实：上下文可见性、工具 allowlist、领域对象读写 scope。
- 智能体间只交换结构化消息和对象引用，不共享原始 session，不允许无边界 peer chat。
- 只有任务可拆、上下文隔离有收益、结果存在合并契约、预算允许时才创建 subagent。
- 公开网络搜索不使用来源白名单硬门控；必须执行 SSRF 防护、质量评分、去重、独立交叉印证、冲突检测和反证保留。
- 总研究轮次默认最多 5 轮，同一再调目标默认最多 3 次，补充后从 `return_node` 恢复。
- 能力画像以文字描述为主，九个展示字段必须完整，并区分新作战能力方向与现有装备升级需求。
- `trace.jsonl`、`domain.jsonl`、`agent_sessions/`、`artifacts/` 必须可复盘，正式结论必须关联证据卡。
- Web、CLI、API 和导出文件必须消费同一领域对象，不允许前端重复计算 coverage、gate、confidence 或审计状态。
- 长任务必须由独立 worker 执行；浏览器断开、刷新或 API 进程重启不能破坏已提交 save point。
- API 使用 `/api/v1`、统一错误结构、幂等键、配置 revision 和可重放 SSE。
- 前端是工作型研究控制台，首屏直接显示任务列表；核心功能面向 1280px 以上桌面，并支持 1024px 折叠布局。
- 企业交付必须包含 RBAC、OIDC 适配、审计日志、健康检查、Docker Compose 验收部署和生产参数模板。
- 当前工作区不是 Git 仓库；每个任务以测试通过、变更清单和阶段审查包作为检查点。执行前若初始化 Git，再按任务粒度提交。

---

**Design Reference:** [前后端一体化企业级设计方案](../specs/2026-07-10-equipment-deep-research-frontend-backend-enterprise-design.md)

## 1. 当前基线与整改范围

### 已有可复用能力

- CLI、运行目录、fake/real 模式入口。
- `AgentRegistry` 和默认四类 agent 配置。
- 三条路线名称、coverage 计算、L1/L2/L3 数据结构。
- `report.md`、`capability_images.json`、`round_summary.json`、`domain.jsonl`、`trace.jsonl`、`agent_sessions/`、`artifacts/` 输出骨架。
- 8 个现有测试覆盖默认运行、agent 子集、自定义 agent、三路线、证据材料化、再调记录和工具拒绝。
- `knowledgegraph.demand_discovery` 中可提炼的 loop、harness、scheduler、session、event bus、Responses adapter、网页抓取和正文简化实现。
- 当前没有后端 HTTP 服务、异步任务 worker、前端应用、鉴权、企业部署和浏览器 E2E。

### 必须完成的实质性整改

| 当前状态 | 首版目标 | 所属阶段 |
|---|---|---|
| 默认模型配置仍为旧值 | 配置、测试、文档统一为 `gpt-5.5` | Phase 0 |
| real provider 仅生成模板线索 | 真实 Responses 模型循环和工具调用 | Phase 2、7 |
| baseline agent 串行运行 | 有界并发 Map-Reduce-Refine | Phase 4 |
| tool 权限只做声明校验 | 每次工具调用前强制 allowlist 与 scope | Phase 1、2 |
| 上下文只按 section 名过滤 | 结构化可见性、证据索引、摘要预算和 checkpoint | Phase 3 |
| 再调只记录不执行 | `RecallEnvelope` 路由、次数控制、断点续跑 | Phase 6 |
| 制胜机理输出主要为固定模板 | 四类资源、六步推理、L1/L2/L3 schema 与门控 | Phase 6 |
| 来源白名单阻断公开资料 | 广泛搜集 + 强过滤，保留安全网络边界 | Phase 0、7 |
| 存储为运行结束后一次性写文件 | save point 事务写入、恢复和导出 | Phase 1 |
| 五判据审计较粗 | 对象级追溯、门控记录和分析师确认状态 | Phase 10 |
| 只有 CLI 和文件产物 | FastAPI、异步 worker、版本化 API 和实时事件 | Phase 8 |
| 没有业务前端 | React 研究工作台和完整评审流程 | Phase 9 |
| 缺少企业部署与安全 | RBAC、OIDC、PostgreSQL/Redis、容器和运维验收 | Phase 8、10 |

## 2. 目标目录与职责

```text
src/equipment_deep_research/
  agents/
    registry.py              # AgentDef、AgentRegistry、配置校验
    contracts.py             # agent 输入输出 schema 映射
    prompts.py               # 基线、制胜机理、审计、报告提示构造
  domain/
    models.py                # 领域对象与枚举
    messages.py              # TaskEnvelope、RecallEnvelope、AgentMessageEnvelope
    planning.py              # ResearchPlanNode、ResearchPlanGraph
    proposals.py             # DomainWriteProposal、TraceProposal
    store.py                 # 内存视图、SQLite save point、JSONL 导出
  harness/
    events.py                # 运行时事件
    event_bus.py             # 发布订阅、脱敏
    budget.py                # token/turn/tool/time/round 预算
    session.py               # append-only JSONL session
    context.py               # ContextPack、ContextProjector、压缩
    agent_loop.py            # 无领域状态的消息/模型/工具循环
    agent_harness.py         # snapshot、权限、proposal、save point、恢复
    scheduler.py             # 有界并发 worker/subagent 调度
    recovery.py              # checkpoint 和运行恢复
  providers/
    base.py                  # ModelProvider 协议
    fake.py                  # 可编程 fake provider
    responses.py             # Responses-compatible HTTP provider
    registry.py              # ProviderRegistry
  tools/
    definitions.py           # ToolDefinition、ToolCall、ToolResult
    registry.py              # ToolRegistry 与执行前权限钩子
    security.py              # URL/SSRF/大小/重定向安全边界
    search.py                # SearchProvider 与聚合搜索
    fetch.py                 # 网页抓取、缓存、限速
    simplify.py              # HTML 正文简化和位置索引
    evidence_filter.py       # 质量评分、去重、印证、冲突、反证
    materialization.py       # artifact 与 EvidenceCard 材料化
  orchestration/
    planning.py              # 问题解析、路线解析、ResearchPlanGraph
    routes.py                # 三路线研究问题链与停止条件
    coverage.py              # capability coverage
    communication.py         # 结构化消息总线
    recall.py                # 再调状态机
    runner.py                # 总闭环入口
    winning/
      resources.py           # 四类资源投影
      reasoning.py           # 六步推理
      gates.py               # L1/L2/L3 门控
      engine.py              # 制胜机理总控
      capability.py          # 九字段文字能力画像
    reporting.py             # 五判据审计与报告
  interfaces/
    cli.py                   # CLI
  api/
    app.py                   # FastAPI 应用
    routes/                  # 版本化 API
    schemas/                 # API DTO
    sse.py                   # 可重放运行事件
  application/
    run_service.py           # 用例服务与状态机
    review_service.py        # 分析师/评审动作
    export_service.py        # 统一导出
  persistence/
    database.py              # SQLite/PostgreSQL 适配
    repositories.py          # 领域仓储
    migrations/              # Alembic
  queue/
    base.py                  # 任务队列协议
    in_process.py            # 开发执行器
    redis_queue.py           # 企业队列实现
    worker.py                # 独立研究 worker
configs/equipment_deep_research/
  agents.yaml
  providers.yaml
  presets.yaml
  evidence.yaml
  tools.yaml
tests/equipment_deep_research/
  unit/
  integration/
  e2e/
  fixtures/
apps/web/
  src/
    app/                     # 路由、布局、权限
    api/                     # OpenAPI 生成 client
    features/                # runs/evidence/winning/capabilities/reports/admin
    components/              # 通用紧凑型工作台组件
    styles/                  # design tokens
  tests/
deploy/
  compose/                   # 项目验收部署
  nginx/                     # TLS/反向代理配置
  production/                # 生产参数模板
```

## 3. 跨阶段稳定接口

以下接口在 Phase 0 定义后视为稳定契约，后续阶段只能向后兼容扩展。

```python
@dataclass(frozen=True)
class TaskEnvelope:
    task_id: str
    run_id: str
    round_index: int
    parent_task_id: str | None
    target_agent_id: str
    target_capability_tags: list[str]
    objective: str
    research_questions: list[str]
    context_refs: list[str]
    evidence_refs: list[str]
    allowed_tools: list[str]
    object_read_scopes: list[str]
    object_write_scopes: list[str]
    budget: dict[str, int]
    return_contract: str
    return_node: str

@dataclass(frozen=True)
class RecallEnvelope:
    recall_id: str
    source_layer: str
    target_agent_id: str | None
    target_capability_tag: str | None
    reason: str
    required_data: list[str]
    evidence_gaps: list[str]
    return_node: str
    urgency: str
    attempt: int
    status: str

@dataclass(frozen=True)
class AgentExecutionResult:
    task_id: str
    agent_id: str
    status: str
    output_refs: list[str]
    evidence_ids: list[str]
    checkpoint_id: str
    error: str = ""

@dataclass(frozen=True)
class RunCheckpoint:
    run_id: str
    checkpoint_id: str
    completed_task_ids: list[str]
    pending_task_ids: list[str]
    round_index: int
    budget_remaining: dict[str, int]

class AgentRuntime(Protocol):
    async def execute(self, task: TaskEnvelope) -> AgentExecutionResult:
        raise NotImplementedError

class Scheduler(Protocol):
    async def run_wave(self, tasks: list[TaskEnvelope]) -> list[AgentExecutionResult]:
        raise NotImplementedError

class SavePointStore(Protocol):
    def commit(self, domain: list[DomainWriteProposal], trace: list[TraceProposal]) -> str:
        raise NotImplementedError

    def recover(self, run_id: str) -> RunCheckpoint:
        raise NotImplementedError
```

## 4. 分阶段交付总览

| 阶段 | 可验收的软件增量 | 核心验收 |
|---|---|---|
| Phase 0 | 基线契约、配置、CLI、目录和偏差整改 | 模型、路线、输出规范统一；硬白名单链路移除 |
| Phase 1 | 通用 AgentLoop/Harness、save point、session、budget、恢复 | snapshot 与事务写入可测试，崩溃后可恢复 |
| Phase 2 | agent/tool/provider registry、真实 Responses provider | fake 与真实 provider 可互换，工具权限逐调用强制 |
| Phase 3 | ContextProjector、信息密度治理、checkpoint、压缩 | agent 看不到未授权上下文，长流程不丢关键索引 |
| Phase 4 | ResearchPlanGraph、动态 agent、并发 subagent、结构化通信 | 默认、子集、自定义 agent 均并发闭环 |
| Phase 5 | 三条研究路线和多轮 Deep Research 控制器 | 三路线分别完成检索-阅读-发现-缺口-再研究 |
| Phase 6 | 四类资源、六步推理、L1/L2/L3、再调状态机 | 再调真实执行并从断点继续，能力画像可追溯 |
| Phase 7 | 广泛联网搜索、抓取、正文简化、强证据过滤 | real smoke 至少形成一个被接纳证据和 artifact |
| Phase 8 | FastAPI、application service、任务队列、SSE、RBAC、PostgreSQL | CLI 与 API 使用同一内核，长任务独立运行并可恢复 |
| Phase 9 | React 企业研究工作台、OpenAPI client、关键业务页面 | 分析师和评审人员可通过 Web 完成端到端流程 |
| Phase 10 | 五判据审计、前后端联调、容器部署、文档、样例和交付包 | 完成企业级交付验收矩阵 |

详细计划：

1. [Phase 0：基线整改与稳定契约](./2026-07-10-equipment-deep-research-phase-0-foundation.md)
2. [Phase 1：通用 Harness 与存储恢复](./2026-07-10-equipment-deep-research-phase-1-harness.md)
3. [Phase 2：Registry 与模型执行后端](./2026-07-10-equipment-deep-research-phase-2-registries-providers.md)
4. [Phase 3：上下文治理与智能体差异化](./2026-07-10-equipment-deep-research-phase-3-context.md)
5. [Phase 4：动态多智能体编排与通信](./2026-07-10-equipment-deep-research-phase-4-orchestration.md)
6. [Phase 5：三条 Deep Research 研究路线](./2026-07-10-equipment-deep-research-phase-5-routes.md)
7. [Phase 6：制胜机理引擎与定向再调](./2026-07-10-equipment-deep-research-phase-6-winning-mechanism.md)
8. [Phase 7：联网工具与证据治理](./2026-07-10-equipment-deep-research-phase-7-network-evidence.md)
9. [Phase 8：企业后端服务与异步任务](./2026-07-10-equipment-deep-research-phase-8-enterprise-backend.md)
10. [Phase 9：企业前端研究工作台](./2026-07-10-equipment-deep-research-phase-9-web-workbench.md)
11. [Phase 10：前后端联调与企业交付验收](./2026-07-10-equipment-deep-research-phase-10-delivery.md)

## 5. 总里程碑与进入条件

### M1：可恢复的单 agent 真实执行内核

- 包含 Phase 0-2。
- fake provider 全测试通过。
- 使用 mock HTTP 验证 `gpt-5.5` Responses 请求、SSE 解析和工具调用。
- 每轮可生成 snapshot、session、save point 和 trace。
- 进入 M2 前，任何未授权工具调用都必须在执行前被拒绝并记录事件。

### M2：真正差异化的动态多 agent 闭环

- 包含 Phase 3-4。
- 四个默认 agent 只看到各自任务上下文和获准证据摘要。
- 自定义综合 agent 可替换多个默认 agent。
- scheduler 有界并发，失败 worker 不破坏其他 worker 已提交 save point。
- 缺失 capability 必须形成 coverage limit 或 `AgentRecommendation`。

### M3：三路线 Deep Research 与制胜机理闭环

- 包含 Phase 5-6。
- 每条路线至少完成两轮 fake 研究，其中第二轮由证据缺口或冲突驱动。
- L1/L2/L3 都使用结构化输出、门控和证据引用。
- 再调必须真实创建目标 task、执行、合并新 packet，并从指定节点恢复。

### M4：真实联网研究内核

- 包含 Phase 7。
- 网络可用时，real smoke 至少完成搜索、抓取、正文简化、证据评分、证据卡写入和能力画像生成。
- 网络不可用时，系统输出明确的 `limited`/`failed` 状态和诊断 artifact，不伪造证据。
- 研究内核已经形成可供报告层消费的产品功能结论、来源逻辑、场景、证据、缺口和限制对象。

### M5：企业级前后端交付

- 包含 Phase 8-10。
- API 与 CLI 对同一输入生成一致的领域对象和报告。
- worker 独立执行长任务，SSE 断线重连后状态一致。
- analyst、reviewer、auditor、admin 四类角色权限由后端强制执行。
- Web 完成创建、启动、监控、证据审阅、L1/L2/L3 复核、能力画像、报告确认和导出。
- Docker Compose 在项目验收环境完成安装、迁移、健康检查、fake 演示和 real smoke。

## 6. 测试策略

### 单元测试

- 领域对象校验、配置校验、权限矩阵、URL 安全、评分公式、去重和冲突判定。
- turn snapshot 不可变性、proposal save point、budget、session append-only、checkpoint 恢复。
- 路线解析、coverage、subagent 适用判定、再调次数和 return node。
- 六步推理输入输出 schema、三层门控、九字段完整性。

### 集成测试

- FakeProvider + ToolRegistry + AgentHarness 完整工具循环。
- 多 worker 并发、部分失败、取消、恢复、save point 顺序。
- 三路线多轮 research loop。
- L1 触发 recall、目标 agent 回传、L1 恢复并进入 L2/L3。
- 搜索命中、网页抓取、正文定位、证据接纳/拒绝/冲突。
- FastAPI 状态机、RBAC、幂等、OpenAPI、SSE 重放、队列和 worker 恢复。

### E2E

- 默认四 agent fake 全闭环。
- 任意子集 agent 受限闭环。
- 自定义替换 agent 闭环。
- 三条路线 fake E2E。
- real smoke E2E。
- 中断后 `--resume` E2E。
- Web 创建研究到报告确认的 Playwright E2E。
- SSE 断线重连、浏览器刷新、RBAC 和 artifact 下载 E2E。
- Docker Compose 服务健康与前后端 smoke。

### 每阶段统一回归命令

```bash
python3 -m pytest -q
cd apps/web && pnpm test --run && pnpm build
cd apps/web && pnpm playwright test
python3 scripts/run_deep_research.py --mode fake --topic "低空无人机探测预警能力缺口" --research-route auto --run-id phase-regression
rg -n "codex exec|RUN_CODEX_WORKFLOW|source_whitelist|blocked_unapproved_source|gpt-5.6-sol" src/equipment_deep_research scripts configs/equipment_deep_research tests/equipment_deep_research README.md docs/TECHNICAL_SCHEME.md docs/ACCEPTANCE.md
```

预期：测试全部通过；fake 运行生成完整产物；最后一条命令在 Phase 0 完成后无结果。

## 7. 最终验收矩阵

| 项目要求 | 实现位置 | 自动验收 |
|---|---|---|
| 国际形势、威胁、场景、制胜机制、打法、体系组合推导新能力 | Phase 4-6 | `test_new_winning_route_e2e.py` |
| 传统场景/制胜/战法与当前装备对比形成缺口 | Phase 5-6 | `test_traditional_gap_route_e2e.py` |
| 局部战争案例多轮检索和未来布局 | Phase 5、7 | `test_war_case_route_e2e.py` |
| 默认四 agent 可选、可少选、可替换 | Phase 2、4 | `test_dynamic_agents.py` |
| 上下文和权限差异化 | Phase 2-3 | `test_context_visibility.py`、`test_tool_scope.py` |
| 多轮深度检索 | Phase 5、7 | `test_research_loop.py` |
| 四类资源、六步推理、L1/L2/L3 | Phase 6 | `test_winning_engine.py` |
| 定向再调和断点继续 | Phase 6 | `test_recall_state_machine.py` |
| 五判据检查 | Phase 10 | `test_final_audit.py` |
| 文字能力画像及九字段 | Phase 6、9-10 | `test_capability_image.py`、`capability-image.spec.ts` |
| 来源、场景、逻辑、证据、缺口可追溯 | Phase 7、9-10 | `test_traceability.py`、`traceability.spec.ts` |
| Web 研究发起、监控、评审和导出 | Phase 8-10 | `research-lifecycle.spec.ts` |
| RBAC、异步任务、SSE 与恢复 | Phase 8 | `test_api_rbac.py`、`test_sse_replay.py`、`test_worker_recovery.py` |
| 企业部署与健康检查 | Phase 10 | `test_compose_smoke.py` |
| 可运行、可审计、可演示企业交付 | 全阶段 | `test_delivery_bundle.py`、`delivery.spec.ts` |

## 8. 执行顺序与审查方式

- 严格按 Phase 0 到 Phase 10 执行；同一阶段内按任务顺序执行。
- 每个任务遵循：写失败测试、确认失败原因、最小实现、局部测试、全量回归、生成变更清单。
- 每阶段结束生成 `docs/testing/phase-N-test-report.md`，记录命令、结果、已知限制和样例 run-id。
- 阶段审查只批准可独立运行的软件增量；未通过门槛不得进入下一阶段。
- 对 Responses API 和真实搜索服务的测试使用录制 fixture 或 mock transport；密钥不得写入仓库、trace、session 或 artifact。
- Phase 8 生成 OpenAPI 后，Phase 9 只使用生成 client；后端 schema 改动必须同步通过契约检查。
- Phase 9 每个核心页面完成后执行桌面与 1024px 视口截图检查，禁止文本溢出、控件重叠和空白图表。

## 9. 总计划完成定义

- `python3 -m pytest -q` 全部通过。
- fake 模式覆盖三路线、默认/子集/自定义 agent、再调、恢复和受限报告。
- real smoke 在网络和凭据可用时形成至少一个正式证据卡；不可用时形成可审计降级结果。
- 运行目录包含规定的七类产物，并额外包含 `run.db`、`checkpoints/` 和 `progress.json`。
- 报告同时列出新作战能力方向和现有装备升级需求，不以固定模板伪造结论。
- 每个能力条目可回溯到 L3、L2、L1、基线 packet、claim、EvidenceCard 和 artifact。
- Web 与 CLI 结果一致，SSE 重连和浏览器刷新不影响长任务。
- 四类企业角色权限、分析师确认、配置 revision 和审计日志均通过测试。
- `docker compose up` 可启动 Web、API、worker、PostgreSQL 和 Redis，健康检查通过。
- 架构图、前后端设计方案、技术方案、接口文档、用户/管理员/运维手册、测试报告、验收说明和示例产物与实际代码一致。
