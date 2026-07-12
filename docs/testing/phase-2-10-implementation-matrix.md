# Phase 2-10 实施对照矩阵

本矩阵以 `docs/superpowers/plans/` 为验收清单，不启用 Superpowers 执行工作流。

| 阶段 | 已实现基础 | 当前需贯通/补齐 | 状态 |
|---|---|---|---|
| Phase 2 | Agent/Tool/Provider Registry、Responses SSE | Provider/Tool Registry 接入 Runner | 进行中 |
| Phase 3 | ContextProjector、Checkpoint、Compactor | 每轮 Harness 投影与 context trace | 进行中 |
| Phase 4 | PlanGraph、MessageBus、SubagentPolicy | 有界并发 wave 与 Runner 计划图 | 进行中 |
| Phase 5 | 三路线配置、QueryPlanner、ResearchLoop | baseline agent 多轮执行与 round summary | 进行中 |
| Phase 6 | 六步对象、L1/L2/L3、RecallCoordinator | 六步/门控/真实再调统一进入 Runner | 进行中 |
| Phase 7 | SSRF 安全材料化、搜索聚合、证据评分 | 搜索/正文简化/评分进入 ResearchLoop | 进行中 |
| Phase 8 | ApplicationService、FastAPI、SQLite/SQLAlchemy 仓储、worker、SSE、基础 RBAC | PostgreSQL/Redis 环境适配与 OIDC | 开发态完成 |
| Phase 9 | React/Vite 任务、agent coverage、运行/证据/制胜/画像/报告/配置视图 | 自动化视觉回归与生成式 OpenAPI client | 开发态完成 |
| Phase 10 | CLI 七类产物、审计报告、交付 manifest、Docker Compose、交付文档 | 甲方环境部署压测与正式签收 | 开发态完成 |

完成标准：对应阶段测试通过，且功能从 CLI/API 主链可达，不以“存在孤立模块”视为完成。
