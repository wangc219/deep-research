# 融合目标验收状态

审计日期：2026-09-24。本轮统一模型、研究编排、企业知识检索和多用户权限的工程融合基线已完成并部署；以下证据分别说明已验证范围，不能用局部回归替代所有真实供应商、长时运行和生产负载验收。

| 原始要求 | 当前证据 | 结论及缺口 |
| --- | --- | --- |
| 统一模型配置 | Query 生成模型血缘；研究、深研与 Query Worker 的平台解析器；两个工作台的平台模型选择器；模型路由回归 | 已统一到平台 `model_spec`，运行时解析凭据且不在任务中保存密钥。MiniMax 的供应商 `403 Model disabled` 仍属于外部账户能力限制。 |
| 动态研究、能力画像报告、反馈自进化完整闭环 | 原 S1-S6/动态蜂群编排保持；fake 模型真实队列交付；执行参数、卡片/深研上下文、终态竞争和恢复回归 | 软件链路与既有功能契约已通过回归；本轮未用全部真实供应商重跑长时完整研究与反馈闭环，不能把离线回归解释为所有外部模型的质量或可用性承诺。 |
| 平台知识库能力深度复用 | 共享检索服务、原生工具、Durable Task 及旧 `/api/v1/runs` → `equipment-worker` 接入；真实 PostgreSQL 撤权三场景；Worker 组合回归 | 已按资源 owner 每次重新授权，显式知识库 ID 只能收窄范围；有界并行检索、单库降级、引用保留和无正文审计事件均已接入。 |
| 多用户隔离与超级管理员全局管理 | 真实 HTTP 企业隔离与超级管理员管理测试；原生深研详情权限；结构化 attempt/success 审计 | 普通用户和普通管理员保持 owner-only；超级管理员可全局读、创建、修改、发布、分支和删除。代管执行仍使用资源 owner 的 Conversation、知识权限及工作目录。 |
| 所有模型调用进入总览 | 真实 HTTP＋PostgreSQL 12 次请求、72 Token、3 次失败一致；嵌入、重排、OCR 单测；登录态页面验收；持久队列故障恢复 | 已接入可观测入口并可补写 PostgreSQL 短暂故障；第三方内部调用不可见，缺失历史 Token 无法恢复，本地卷与数据库同时故障仍非零丢失承诺。 |
| 高内聚、低耦合 | 领域不得反向导入平台的 AST 检查；模型端口、共享账本和知识检索服务边界 | 有明确架构边界；原领域 SQLite 与平台 PostgreSQL 仍并存，未宣称完全合库。 |
| 启动构建及资源优化 | 日常 Nginx 静态模式、关闭开发监听、镜像缓存；约 1.8 GiB 容器内存，空闲 CPU 多次采样 | 已验证本机日常运行改善；未做代表性生产并发容量或长时间负载验收。 |

## 继续工作的边界

本轮修改限定在企业身份权限、统一模型路由、知识检索复用、任务编排基础设施、卡片/深研衔接和可观测性，没有新增目标打击、武器设计或作战优化能力。真实供应商的长时质量验收仍应使用合法、非伤害性的企业研究场景。

## 验收依据

- [模型运行时与统计记录](MODEL_RUNTIME_INTEGRATION.md)
- [多用户与权限记录](ENTERPRISE_MULTIUSER.md)
- [运行方式与资源记录](RUNTIME_OPERATIONS.md)
- `backend/test/integration/api/test_model_usage_ledger_live.py`
- `backend/test/integration/api/test_knowledge_tool_revocation_live.py`
- `backend/test/integration/api/test_enterprise_isolation_live.py`
- `backend/test/integration/api/test_equipment_superadmin_management_live.py`
- `backend/test/unit/architecture/test_equipment_domain_boundaries.py`

本轮最终复验：后端融合专项 91 项、旧 Worker＋统一模型组合 37 项、Query 25 项、真实知识撤权 3 项、真实 HTTP 企业隔离 1 项、真实 HTTP 超级管理员管理 1 项通过；旧工作台 83 项、平台前端 362 项、完整 lint 与两个生产构建通过。API readiness 为 `ready` 且 `degraded=false`，平台 Worker、研究 Worker、Query Worker 和静态 Web 已重启/重建。不同批次的回归数量存在重叠，不应相加作为独立覆盖率。
