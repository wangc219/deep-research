# 平台知识库能力基线

审计日期：2026-09-27。本文定义装备智能研究平台内建知识能力的验收基线。知识库不是外挂子系统，而是 `platform_core` 共享数据平面的一部分，由智能对话、需求 Query、装备研究和深研 Agent 通过同一授权检索端口使用。

初始能力核对曾参考第三方公开实现；来源版本与许可证只记录在 [平台内核来源与融合记录](migration/PLATFORM_CORE_PROVENANCE.md)，不构成当前产品的模块边界。

## 能力矩阵

| 平台知识能力 | 统一实现入口 | 验证重点 |
| --- | --- | --- |
| 多格式入库、解析、分块、Chunk/Token 状态 | `platform_core.knowledge.parser`、`chunking`、知识库文件管理页 | 格式白名单、文件大小、解析状态、失败重试、统计修复 |
| Embedding、BM25、混合检索、Rerank | `MilvusKB.retrieve`、知识库检索配置与检索测试页 | 阈值、候选数、融合权重、最终 Top K、引用字段 |
| RAG 评估、单跳与多跳 QA 生成 | `platform_core.knowledge.eval`、`knowledge_eval_router`、评估工作台 | 基准上传/生成、断点恢复、批量评估、逐题结果、导出 |
| 知识图谱构建与检索 | `platform_core.knowledge.graphs`、`graph_router`、知识图谱页 | 实体/关系抽取、索引状态、子图、节点详情、图向量融合 |
| 知识导图 | `mindmap_utils`、文件管理页思维导图入口 | 真实目录层级、文件元数据、异步渲染清理 |
| Milvus、Dify、Notion 等统一知识库 | `knowledge.factory`、`implementations`、创建流程 | 类型能力声明、凭据脱敏、只读连接器限制 |
| Agent 使用知识库 | `knowledge_retrieval_service`、知识库 Tool、研究任务知识范围 | 实时授权、范围只收窄、有界并发、单库故障隔离、引用保留 |
| 多租户、用户、部门与共享范围 | `platform_core.permissions`、知识库路由、权限配置页 | 所有者管理、共享只读/管理、管理员代管、撤权即时生效 |
| 知识库运维统计 | `knowledge_dashboard_service`、Dashboard | 文件、Chunk、Token、检索调用与模型调用统计 |

## 质量与效率约束

- 未通过资源授权的请求必须在 Embedding、Rerank 或外部知识库调用前失败。
- 多知识库检索使用有界并发；单库故障不得抹掉其他知识库的有效证据。
- 检索结果保留知识库、文件、Chunk、分数与重排分数，供回答引用和评估追踪。
- 文件列表和统计采用批量读取及缓存失效策略，避免逐文件数据库往返。
- 解析、索引、图谱与评估均为可观察后台任务；前端区分 loading、empty、error 与完成状态。
- 普通用户可管理自己的个人知识库；评估数据集的下载与删除复用所属知识库权限，不额外要求管理员角色。

## 验证命令

```bash
cd backend
.venv/bin/pytest test/unit/knowledge \
  test/unit/repositories/test_knowledge_base_repository_cache.py \
  test/unit/repositories/test_knowledge_chunk_repository.py \
  test/unit/services/test_knowledge_retrieval_service.py \
  test/unit/routers/test_knowledge_resource_permission.py \
  test/unit/routers/test_knowledge_router_cleanup.py \
  test/unit/routers/test_evaluation_resource_permission.py

cd ../web
node --test \
  test/unit/database_create_flow.test.js \
  test/unit/database_store.test.js \
  test/unit/file_upload_folder.test.js \
  test/unit/knowledge_detail_layout.test.js \
  test/unit/knowledge_evaluation_workspace.test.js \
  test/unit/knowledge_file_mutations.test.js

curl --fail http://127.0.0.1:5050/api/system/ready
```

真实检索验收至少使用一个完成向量入库的知识库，确认返回结果包含来源文件、文件 ID、
Chunk 索引和相似度；若启用 Rerank，还应显示重排分数。知识图谱和自动生成评估基准依赖
已配置的抽取或聊天模型，未配置时页面必须给出可执行的配置指引，不能伪造成功。
