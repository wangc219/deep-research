# Phase 2-10 实施对照矩阵

本矩阵以各阶段计划和 Deep Research 项目要求为验收基线，不启用 Superpowers 工作流。

| 阶段 | 主链实现 | 自动验证状态 | 生产环境边界 |
|---|---|---|---|
| Phase 2 | Agent/Tool/Provider Registry、Responses SSE、默认 `gpt-5.5` | 已覆盖 | 真实凭据由环境注入 |
| Phase 3 | ContextProjector、turn snapshot、checkpoint、compaction、独立 session | 已覆盖 | 长周期压缩阈值可环境化 |
| Phase 4 | 动态计划图、MessageBus、SubagentPolicy、有界并发 wave | 已覆盖 | 分布式并发规模需压测定标 |
| Phase 5 | 三路线、QueryPlanner、多轮 ResearchLoop、round summary | 已覆盖 | 真实检索效果依赖网络出口 |
| Phase 6 | 四类资源、六步推理、L1/L2/L3、门控、真实定向再调、九字段画像 | 已覆盖 | 领域 prompt 需持续评审 |
| Phase 7 | Responses `web_search`、来源导出、安全抓取、正文段落定位、证据评分、正式证据门控 | 代码、契约和材料化测试已覆盖 | 真实凭据/公网效果需目标环境 smoke |
| Phase 8 | FastAPI、持久化队列、独立 worker、持久化实时事件、SSE replay、基础 RBAC、运行产物 API | 已覆盖 SQLite 首版 profile | OIDC、迁移、PostgreSQL/Redis、worker 租约待生产化 |
| Phase 9 | React 工作台、任务 CRUD/软归档、执行历史、Real 配置、coverage、实时 Agent/工具时间线、证据/制胜/画像/报告视图 | 生产构建与 API 契约测试通过 | Vitest/Playwright 与目标终端视觉基线待补签 |
| Phase 10 | 五判据、报告、自动 manifest、Compose、交付文档、跨实例 E2E | 已覆盖首版交付 profile | TLS、备份恢复、高可用、安全与容量压测待部署验收 |

完成标准：功能必须从 CLI 或 API 主链可达，并具备领域产物和 trace 证据；仅存在孤立模块不计为完成。

完整成熟度审计和后续优先级见 `docs/ENTERPRISE_DELIVERY_AUDIT.md`。
