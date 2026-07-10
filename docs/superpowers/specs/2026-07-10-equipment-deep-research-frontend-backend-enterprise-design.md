# 装备能力图像 Deep Research 前后端一体化企业级设计方案

## 1. 设计目标

在现有多智能体 Deep Research 架构上增加企业级服务端与 Web 研究工作台，使系统不仅能够通过 CLI 跑通算法闭环，还能面向甲方分析师、评审人员、审计人员和系统管理员提供统一、可视、可控、可追溯的业务系统。

首版交付目标：

- 分析师通过 Web 创建研究任务，选择研究路线、agent 组合、研究轮次和约束。
- 系统后台异步运行多 agent，不依赖浏览器持续在线。
- 前端实时展示计划图、agent 状态、研究轮次、预算、联网搜集、制胜机理门控和再调过程。
- 评审人员能够审阅证据、冲突、L1/L2/L3 结果和文字能力画像，并执行确认或退回。
- 所有用户操作、模型调用、工具调用、证据变化、门控和发布动作均可审计。
- 支持单机验收部署和企业生产部署，不改变核心研究算法契约。

## 2. 设计原则

### 2.1 核心算法与服务层解耦

`equipment_deep_research` 保持可独立测试的领域和运行时内核。API 层只通过 `ResearchApplicationService` 调用内核，不把 HTTP、数据库 ORM 或前端 DTO 混入 AgentLoop、Harness 和制胜机理推理代码。

### 2.2 长任务异步化

创建 run、启动 run、查看 run 分离。API 请求只负责校验和入队，worker 在独立进程执行研究任务。浏览器关闭、刷新或网络短暂中断不影响运行。

### 2.3 前端是业务工作台，不是营销页面

首屏直接进入研究任务列表与运行状态，不设置宣传型首页。页面强调扫描、比较、复核和重复操作效率，避免大面积装饰、卡片嵌套和高饱和背景。

### 2.4 单一领域真相

Web、CLI、API 和交付文件读取同一领域对象。前端不重新推导 coverage、gate、confidence 或审计状态；所有业务结论由后端返回。

### 2.5 审计优先

前端显示的关键结论都必须能展开查看来源对象。用户确认、退回、取消、恢复、配置变更使用独立审计事件记录，不覆盖历史数据。

## 3. 用户角色与权限

| 角色 | 主要权限 |
|---|---|
| `analyst` | 创建研究、选择 agent、启动、暂停、恢复、取消、查看证据和结果、提交评审 |
| `reviewer` | 查看全部研究、审阅 L1/L2/L3、确认关键假设、批准或退回报告 |
| `auditor` | 只读访问 run、trace、session 摘要、配置版本和导出 manifest |
| `admin` | 管理 agent/provider/tool/evidence 配置、用户角色、保留策略和部署状态 |

权限在 API 服务端强制执行。前端菜单隐藏只用于体验优化，不能代替服务端鉴权。

## 4. 总体架构

```text
Browser
  React Web Workbench
    |
    | HTTPS + JSON API + SSE
    v
Reverse Proxy / Gateway
    |
    v
FastAPI Service
  Auth / RBAC
  Run API
  Catalog API
  Evidence API
  Review API
  Export API
    |
    +--> PostgreSQL: run、task、domain object、audit、config revision
    +--> Redis: job queue、分布式锁、短期事件通知
    +--> Artifact Store: local filesystem 或 S3-compatible object storage
    |
    v
Research Worker
  DeepResearchRunner
  ResearchPlanGraph
  Scheduler / AgentHarness
  Network Tools
  Winning Mechanism Engine
    |
    v
Responses-compatible Model Provider / Public Web Sources
```

### 4.1 部署形态

| 环境 | 数据库 | 队列 | Artifact | 鉴权 |
|---|---|---|---|---|
| 开发 | SQLite | in-process | 本地目录 | 开发用户 |
| 甲方验收 | PostgreSQL | Redis | 本地持久卷 | 本地账号或 OIDC |
| 生产 | PostgreSQL 主备 | Redis Sentinel/Cluster | S3-compatible | OIDC/统一身份 |

## 5. 后端服务设计

### 5.1 目录结构

```text
src/equipment_deep_research/
  api/
    app.py
    dependencies.py
    errors.py
    middleware.py
    schemas/
      runs.py
      evidence.py
      winning.py
      capabilities.py
      configuration.py
    routes/
      auth.py
      catalog.py
      runs.py
      evidence.py
      winning.py
      capabilities.py
      reports.py
      configuration.py
      health.py
    sse.py
  application/
    run_service.py
    review_service.py
    configuration_service.py
    export_service.py
    dto.py
  persistence/
    database.py
    models.py
    repositories.py
    migrations/
  queue/
    base.py
    in_process.py
    redis_queue.py
    worker.py
```

### 5.2 运行状态机

```text
draft -> queued -> planning -> researching
  -> winning_l1 -> recalling -> winning_l1
  -> winning_l2 -> recalling -> winning_l2
  -> winning_l3 -> auditing -> review_required
  -> completed

任意运行态 -> pause_requested -> paused -> queued
任意运行态 -> cancel_requested -> cancelled
任意运行态 -> limited | failed
```

状态变化通过领域事件提交。API 不直接修改最终状态，只提交 command；worker 在 save point 处理暂停和取消。

### 5.3 API 约定

- Base path：`/api/v1`。
- JSON 字段保持领域对象的 `snake_case`，减少导出文件与 API 的转换差异。
- 所有写请求支持 `Idempotency-Key`。
- 配置更新使用 `revision` 和 `If-Match`，避免覆盖他人修改。
- 错误结构统一为 `code`、`message`、`details`、`request_id`。
- 列表接口统一支持 `page`、`page_size`、`sort`、`filter`。

主要接口：

```text
GET    /api/v1/auth/me
GET    /api/v1/catalog/routes
GET    /api/v1/catalog/agents
GET    /api/v1/catalog/providers

POST   /api/v1/runs
GET    /api/v1/runs
GET    /api/v1/runs/{run_id}
POST   /api/v1/runs/{run_id}/start
POST   /api/v1/runs/{run_id}/pause
POST   /api/v1/runs/{run_id}/resume
POST   /api/v1/runs/{run_id}/cancel
GET    /api/v1/runs/{run_id}/events
GET    /api/v1/runs/{run_id}/plan
GET    /api/v1/runs/{run_id}/agents
GET    /api/v1/runs/{run_id}/rounds

GET    /api/v1/runs/{run_id}/evidence
GET    /api/v1/runs/{run_id}/evidence/{evidence_id}
GET    /api/v1/runs/{run_id}/artifacts/{artifact_id}
GET    /api/v1/runs/{run_id}/winning
GET    /api/v1/runs/{run_id}/recalls
GET    /api/v1/runs/{run_id}/capabilities
GET    /api/v1/runs/{run_id}/report
GET    /api/v1/runs/{run_id}/audit
POST   /api/v1/runs/{run_id}/review
POST   /api/v1/runs/{run_id}/confirm
GET    /api/v1/runs/{run_id}/export

GET    /api/v1/configuration
PUT    /api/v1/configuration/{section}
GET    /api/v1/health/live
GET    /api/v1/health/ready
```

### 5.4 实时事件

`GET /runs/{run_id}/events` 使用 Server-Sent Events。事件包含单调递增 `sequence`，浏览器重连时通过 `Last-Event-ID` 补发，不依赖 Redis 消息是否仍存在。

前端可见事件类型：

- `run_status_changed`
- `plan_node_changed`
- `agent_status_changed`
- `round_completed`
- `evidence_added`
- `evidence_decision_changed`
- `winning_stage_changed`
- `recall_changed`
- `budget_changed`
- `audit_changed`
- `report_published`

事件 payload 不包含 API key、完整模型上下文、原始 session 或超长网页正文。

### 5.5 数据与存储

- PostgreSQL 保存 run、task、领域对象快照、trace、review、config revision 和文件索引。
- Redis 只保存队列、锁和短期通知，不作为审计真相源。
- ArtifactStore 采用统一接口，支持 local 与 S3-compatible 实现。
- CLI 输出的 JSONL/JSON/Markdown 由 ExportService 从同一领域数据生成。
- 每个对象保留 `schema_version`、`created_at`、`updated_at`、`created_by`、`run_id`。

## 6. 前端产品设计

### 6.1 技术栈

- React 19 + TypeScript。
- Vite。
- React Router。
- TanStack Query 管理服务端状态。
- Zustand 只保存本地界面状态。
- Ant Design 5 提供企业级表单、表格、抽屉、分页和反馈。
- `lucide-react` 提供按钮图标。
- React Flow 展示 ResearchPlanGraph 和追溯链。
- ECharts 展示轮次、证据质量和预算趋势。
- Vitest + Testing Library + Playwright。
- OpenAPI 生成 TypeScript 类型和 API client。

### 6.2 信息架构

```text
研究任务
  任务列表
  新建研究
  运行控制台
    总览
    Agent 研判
    证据中心
    制胜机理
    能力画像
    报告评审
    审计追踪

系统管理
  Agent 配置
  Provider 与模型
  工具与权限
  证据策略
  用户与角色
  系统状态
```

### 6.3 核心页面

#### A. 研究任务列表

- 表格列：主题、路线、状态、启用 agent、当前阶段、轮次、证据数、审计状态、创建人、更新时间。
- 筛选：状态、路线、创建人、时间、审计状态。
- 行操作使用图标按钮：查看、恢复、取消、导出；危险操作二次确认。
- 顶部只保留“新建研究”主操作，不设置大面积欢迎区。

#### B. 新建研究

- 研究主题和约束。
- 三条研究路线的分段控制，`auto` 单独提供。
- Agent 选择表格显示 capability tags、工具权限、上下文范围和覆盖贡献。
- 实时 coverage 面板显示已覆盖、缺失和替换建议。
- 高级设置包含轮次、并发、模型 profile、网络研究开关和预算。
- 提交前由后端执行预检并返回可执行计划摘要。

#### C. 运行控制台

- 顶部固定状态栏：run 状态、路线、轮次、预算、联网状态、暂停/取消/恢复。
- 主体第一层使用阶段导航：问题解析、基线研究、L1、L2、L3、审计、报告。
- ResearchPlanGraph 使用 React Flow，无装饰容器，节点颜色表示 pending/running/completed/limited/failed。
- Agent 状态采用紧凑表格：任务、工具调用数、证据增量、置信度、checkpoint、耗时。
- 右侧抽屉显示选中节点输入引用、输出对象、权限快照和 trace，不显示其他 agent 原始会话。

#### D. 证据中心

- 表格列：状态、标题、机构、时间、质量总分、直接支撑、独立印证、冲突、关联 claim、创建 agent。
- 可按 accepted/candidate/rejected、agent、轮次、claim、分数筛选。
- 详情抽屉并排显示正文摘录、来源元数据、评分分解、支撑 claim、反证和 artifact 信息。
- 冲突组使用差异表比较参数、时间和来源，不用颜色作为唯一状态信号。

#### E. 制胜机理

- 顶部展示六步串联：防御解构、制胜路径、效果链、能力映射、差距量化、图像生成。
- 下方使用 L1/L2/L3 tabs，每层显示输出对象、门控条件、通过状态、证据和再调记录。
- Recall 时间线显示来源层、目标 agent/tag、所需数据、尝试次数、return node 和结果。
- 未通过门控必须显示原因和受限影响，不允许只显示红色状态点。

#### F. 能力画像

- 默认使用密集表格，不使用重复大卡片。
- 列：能力编号、名称、装备类别、类型、优先级、差距、置信度、审计状态。
- 详情抽屉展示九字段全文、评分依据和完整追溯链。
- 新作战能力与现有装备升级使用 tabs 和类型标签区分。

#### G. 报告评审

- Markdown 报告预览与目录导航。
- 评审侧栏显示五判据、未解决冲突、缺失覆盖和待确认假设。
- reviewer 可填写评审意见并执行“批准”“退回补充”；analyst 可提交修订任务。
- 报告正文不直接自由编辑，避免编辑后与领域对象和证据链失配。

#### H. 系统配置

- Agent 配置：列表、capability、工具、context、读写 scope、启用状态、版本。
- 权限矩阵：agent × tools 和 agent × object scopes。
- Provider 配置：只展示模型、endpoint host、状态；密钥只允许重新设置，不回显。
- 配置修改先预览 diff，再创建新 revision；运行中的 run 继续使用启动时 snapshot。

### 6.4 视觉规范

- 主背景 `#F4F6F8`，内容背景 `#FFFFFF`，主文字 `#243447`。
- 主操作色使用克制青蓝 `#2F7185`。
- 成功 `#3F7D5A`，警告 `#A87820`，失败 `#B34A4A`，信息 `#4E6F9E`。
- L1 使用淡绿、L2 使用淡紫灰、L3 使用淡蓝，与架构图保持一致但降低饱和度。
- 卡片圆角不超过 8px；页面分区优先用留白、分隔线和 full-width band，不嵌套卡片。
- 顶栏高度 52px，侧栏展开 232px，表格行高 44px，工具栏按钮保持稳定尺寸。
- 图标按钮使用 lucide 图标并提供 tooltip。
- 字体使用系统中文字体栈；标题只用于页面层级，不在紧凑面板使用超大字号。

### 6.5 响应式与可访问性

- 核心工作台面向 1280px 以上桌面；1024px 时折叠侧栏、详情改抽屉。
- 小屏提供任务状态、报告和证据只读查看，不压缩复杂计划图到不可读尺寸。
- 颜色对比达到 WCAG AA；状态同时使用文本、图标和颜色。
- 表格、tabs、抽屉和操作支持键盘导航；实时更新使用非打断式 aria-live。

## 7. 前后端契约

### 7.1 OpenAPI 单一来源

FastAPI 生成 `openapi.json`，前端执行 `pnpm api:generate` 生成只读类型。CI 检查生成结果与后端 schema 一致，禁止手写重复 DTO。

### 7.2 关键 DTO

```typescript
export interface RunSummary {
  run_id: string;
  topic: string;
  research_route: ResearchRoute;
  status: RunStatus;
  current_stage: string;
  round_index: number;
  max_rounds: number;
  selected_agent_ids: string[];
  evidence_count: number;
  capability_count: number;
  audit_status: AuditStatus;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface RuntimeEventDto {
  sequence: number;
  event_type: string;
  run_id: string;
  agent_run_id?: string;
  object_refs: string[];
  payload: Record<string, unknown>;
  created_at: string;
}
```

### 7.3 实时一致性

SSE 只通知变化，不携带完整页面数据。前端收到事件后按对象类型精确刷新 TanStack Query cache；断线重连后先补事件，再执行一次 run summary 对账。

## 8. 企业安全设计

- OIDC/OAuth2 接入甲方统一身份，验收环境可使用本地账号适配器。
- API 使用 RBAC 与 run-level authorization。
- 浏览器永远不接触模型 provider key、搜索 key 或内部网络 header。
- 生产环境同源部署，限制 CORS；Cookie 模式启用 CSRF 防护。
- 反向代理终止 TLS，内部服务使用受控网络。
- 公网检索统一通过 worker 出口，可配置企业 HTTP proxy；前端不能直接抓取外部 URL。
- Artifact 下载执行权限检查、Content-Disposition 和内容类型约束。
- 日志、trace 和 session 执行敏感字段脱敏和长度限制。
- 配置、评审和导出行为写入不可覆盖审计日志。
- 数据保留策略按 run 状态、时间和 legal hold 配置。

## 9. 可观测性与运维

- 健康检查：liveness、readiness、数据库、Redis、artifact、provider 和搜索 provider。
- 指标：run 数、队列长度、平均轮次、agent 耗时、工具错误率、抓取成功率、证据接纳率、recall 次数、token 使用量。
- 结构化日志包含 request id、run id、task id、agent run id，不记录密钥和完整上下文。
- worker 使用 heartbeat；超时任务进入可恢复状态，不直接重复执行已提交 save point。
- 管理页面只显示状态摘要和诊断 id，详细日志由运维系统管理。

## 10. 测试方案

### 后端

- API schema、RBAC、幂等、状态机、SSE 重放、队列、worker 恢复、artifact 权限。
- FastAPI TestClient 覆盖错误结构和 OpenAPI。
- PostgreSQL/Redis 使用容器集成测试。

### 前端

- Vitest：表单、coverage、状态组件、权限显示、SSE reducer。
- Testing Library：按用户行为测试，不直接断言内部 state。
- Playwright：创建研究、实时运行、证据审阅、L1 recall、能力画像、报告批准和导出。
- 视觉测试覆盖 1440×900、1280×800、1024×768；检查文本溢出、遮挡和图表空白。

### 契约

- OpenAPI snapshot。
- 前端生成 client 无未提交差异。
- fake E2E 同时通过 CLI 与 Web 启动，输出领域对象和报告一致。

## 11. 企业交付物

- Python 多智能体内核源码和 CLI。
- FastAPI 服务、worker 和数据库迁移。
- React Web 工作台源码和构建产物。
- OpenAPI 文档和前端生成 client。
- Docker Compose 验收部署包。
- 生产部署参数模板、反向代理配置和环境变量说明。
- 默认 agent、provider、tool、evidence、route 配置。
- fake 与 real smoke 样例。
- 用户手册、管理员手册、运维手册、接口文档、测试报告和验收说明。
- 两张架构图 HTML/PDF 及新增前后端部署架构图。

## 12. 企业级验收标准

- 分析师可通过 Web 完成创建、启动、监控、暂停、恢复、取消、审阅和导出。
- 默认 agent、agent 子集和自定义 agent 在 Web 与 CLI 中结果一致。
- 浏览器刷新和 SSE 断线不影响任务，重连后状态一致。
- 关键结论可从 UI 追溯到制胜层、packet、claim、EvidenceCard 和 artifact。
- reviewer 未确认时不能发布 approved 报告。
- RBAC、配置 revision、审计日志和 artifact 权限测试通过。
- 单机 Docker Compose 可在目标环境完成安装、启动、健康检查和 fake 演示。
- 网络与凭据可用时 real smoke 完成公开资料检索、证据写入和能力画像生成；不可用时明确降级。
- Playwright 关键流程、后端测试、算法测试和交付 manifest 校验全部通过。
