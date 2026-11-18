# 智能研究平台（Deep Research）

面向装备与技术创新研究的一体化平台，包含多智能体深度研究、需求 Query 生成、证据检索、知识库、知识图谱、创新简报、企业权限和可审计交付。仓库提供前端、后端、数据库迁移、Docker Compose、锁定依赖与测试，可从全新机器完成部署。

当前主分支以本地实现为准，更新日期为 **2026-11-18**。

## 核心能力

- 多智能体研究：任务拆解、动态编排、检查点、恢复、人工审批和报告交付。
- 装备研究：需求发现、Query 生成、技术路线、能力画像、制胜机理与创新方案。
- 统一检索：SearXNG、Open Websearch、AMiner（可选）及知识库检索，带缓存、限流和正文补全。
- 知识库：文档解析、OCR、分块、向量/BM25 混合检索、Rerank、评估和引用追踪。
- 知识图谱：实体关系抽取、跨文档关系、实体对齐、多跳检索、图谱治理、审阅和版本追踪。
- 企业能力：用户、租户、部门、角色权限、任务队列、SSE 回放、运行监控和审计。
- 内容采集：公众号、视频号、网页材料和学术论文的采集、转写与入库。

## 知识图谱实现边界

可部署版本的知识图谱固定为 **项目 LLM + LightRAG 风格轻量 RAG**：

1. `lightrag_primary` 使用平台中配置的 LLM 直接完成实体/关系初抽。
2. 通过 LightRAG gleaning、关系补全、跨文档关系、实体对齐和证据约束提升召回与可审计性。
3. 图谱与文本向量写入 Milvus，权威关系及治理状态写入 PostgreSQL，Neo4j 用于图查询与展示。
4. 本地和生产 Compose 均强制 `KNOWLEDGE_GRAPH_LIGHTWEIGHT_RAG_ONLY=true`，API 会拒绝其他抽取器类型。

部署不需要独立 IE sidecar、模型训练服务或本地模型权重。历史实验、训练包、真实语料和评测输出不属于部署源码，也不会进入 Git。

## 系统组成

```text
浏览器
  └─ Vue 3 / Vite Web
       └─ FastAPI API / SSE
            ├─ PostgreSQL：业务事实、权限、图谱治理与任务状态
            ├─ Redis / ARQ：任务投递和短期事件
            ├─ Milvus：向量及图谱投影
            ├─ Neo4j：图查询与可视化
            ├─ MinIO：文档与交付文件
            ├─ SearXNG + Open Websearch：公开检索
            └─ Sandbox：Agent 文件与代码执行
```

详细设计见 [系统架构](docs/ARCHITECTURE.md) 和 [运行维护](docs/RUNTIME_OPERATIONS.md)。

## 快速部署

### 环境要求

- Git（已配置 GitHub SSH Key）
- Docker Engine 24+ 或 Docker Desktop
- Docker Compose v2
- 建议 8 核 CPU、16 GB 内存、30 GB 以上可用磁盘
- 可访问 Docker Hub、GitHub Container Registry 和项目所使用的模型供应商

仅在脱离容器进行源码开发时需要 Python 3.12–3.13、Node.js 22+、pnpm 11 和 `uv`。

### 1. 克隆

```bash
git clone git@github.com:wangc219/deep-research.git
cd deep-research
git switch main
```

### 2. 首次启动

```bash
bash scripts/platform.sh start
```

首次执行会：

- 交互生成本机 `.env`；
- 为 JWT、API Key 派生、Sandbox 和 SearXNG 生成相互独立的随机密钥；
- 拉取基础镜像并构建当前源码；
- 执行数据库迁移并启动完整默认服务栈。

`.env` 只保存在部署机器，禁止提交到 Git。聊天模型、Embedding 模型、模型供应商地址和 API Key 在启动后通过「模型设置」页面配置。

### 3. 检查部署

```bash
bash scripts/platform.sh status
curl --fail http://localhost:5050/api/system/ready
```

默认入口：

- Web：<http://localhost:5173>
- API：<http://localhost:5050>
- Readiness：<http://localhost:5050/api/system/ready>

登录后至少完成以下配置：

1. 在「模型设置」中添加并测试一个聊天/研究模型。
2. 配置知识库使用的 Embedding 模型。
3. 新建知识库并上传文档；知识图谱构建时选择已配置的项目 LLM。
4. 如需 AMiner、公众号或视频号能力，再在对应管理页面配置凭据或本机采集端。

## 日常操作

```bash
# 启动已有镜像，不重新构建
bash scripts/platform.sh up

# 重新构建并切换到当前源码
bash scripts/platform.sh update

# 查看状态和最近日志
bash scripts/platform.sh status
bash scripts/platform.sh logs

# 停止服务（保留数据）
bash scripts/platform.sh stop

# 只验证 Compose 配置
bash scripts/platform.sh config
```

开发模式使用热加载：

```bash
PLATFORM_MODE=dev bash scripts/platform.sh start
```

## 生产部署

生产模式使用 `compose.prod.yaml`、独立 `.env.prod` 和可追踪的发布标识。先生成配置：

```bash
DEEP_RESEARCH_ENV_FILE=.env.prod bash scripts/init.sh
```

再构建并启动：

```bash
export DEEP_RESEARCH_RELEASE_ID="release-$(date +%Y%m%d-%H%M%S)"
export DEEP_RESEARCH_SOURCE_REVISION="$(git rev-parse --short=12 HEAD)"
PLATFORM_MODE=prod \
DEEP_RESEARCH_ENV_FILE=.env.prod \
bash scripts/platform.sh start
```

生产发布前应备份当前版本和持久化数据，并准备可执行回滚；不要在运行容器中修改源码。完整流程见 [本地开发与发布流程](docs/LOCAL_DEVELOPMENT_AND_RELEASE.md)。

## 配置说明

可公开的配置示例见 [.env.example](.env.example)。重要约定：

- 部署密钥写入 `.env` 或 `.env.prod`，两者均已被 Git 忽略。
- 模型 ID、供应商地址和 API Key 优先在 Web「模型设置」中维护。
- `DEEP_RESEARCH_STATE_DIR` 可将 PostgreSQL、Redis、Milvus、MinIO、Neo4j 等持久化目录迁到独立磁盘。
- `DEEP_RESEARCH_API_PORT` 和 `DEEP_RESEARCH_WEB_PORT` 可覆盖默认端口。
- `KNOWLEDGE_GRAPH_LIGHTWEIGHT_RAG_ONLY` 在官方 Compose 中固定为 `true`，不应关闭。
- 知识治理页面由 `VITE_ENABLE_KNOWLEDGE_GOVERNANCE` 控制，构建生产前端时需保持与后端功能开关一致。

修改配置后运行：

```bash
bash scripts/platform.sh config
bash scripts/platform.sh update
```

## 数据与备份

默认持久化数据位于 `docker/volumes/`，用户工作区、运行产物和上传文件位于部署状态目录及 `outputs/`。这些内容不属于源码仓库。

迁移部署时应单独备份：

- PostgreSQL 数据库；
- MinIO 对象存储；
- Milvus、Neo4j 和 Redis 持久化目录；
- 用户工作区、上传文件和运行交付物；
- `.env` / `.env.prod`（使用安全渠道传输）。

旧存储布局迁移会停止写入服务，执行前必须确认无活动任务并保留可恢复备份：

```bash
bash scripts/migrate-storage.sh --env-file .env.prod -f compose.prod.yaml
```

## 本地开发

安装锁定依赖：

```bash
uv sync --project backend --group test
pnpm --dir web install --frozen-lockfile
```

常用验证：

```bash
uv run --project backend --group test python -m pytest backend/test/unit -m "not slow" -q
uv run --project backend ruff check backend/package
uv run --project backend ruff format backend/package --check
pnpm --dir web lint:check
pnpm --dir web test:unit
pnpm --dir web build
docker compose --env-file .env -f compose.yaml -f compose.local.yaml config --quiet
```

集成与端到端测试需要先启动 PostgreSQL、Redis、Milvus、MinIO、Neo4j、Sandbox 等完整服务。进入 `backend/` 或 `web/` 修改代码前，请同时阅读对应目录的 `AGENTS.md`。

## 仓库结构

```text
backend/
  package/platform_core/            平台内核、知识库、LightRAG 图谱与服务
  package/equipment_deep_research/  装备研究领域与多智能体编排
  server/                            FastAPI 路由、依赖和 worker 入口
  test/                              单元、集成与端到端测试
web/                                 Vue 3 工作台
configs/                             检索与领域配置
docker/                              API、Web、Sandbox 等镜像定义
scripts/                             初始化、运行、迁移和发布检查
compose.yaml                         开发基础栈
compose.local.yaml                   默认本地覆盖层
compose.prod.yaml                    生产栈
docs/                                架构、运维、验收和开发文档
```

## 常见问题

### 启动时提示缺少安全变量

重新执行 `bash scripts/platform.sh start`。初始化脚本会补齐缺失或不安全的随机密钥，不会覆盖有效密钥。

### API 已启动但 Readiness 失败

```bash
bash scripts/platform.sh status
docker compose --env-file .env -f compose.yaml -f compose.local.yaml logs --tail=200 api postgres redis milvus graph minio
```

Readiness 会把核心依赖失败视为不可用；先处理报告中的具体组件，不要跳过检查直接对外提供服务。

### 知识图谱提示不支持抽取器

官方部署只允许 `lightrag_primary`。在知识图谱配置中选择 LightRAG，并确认已配置可用的项目 LLM。

### 更新后页面仍是旧版本

执行 `bash scripts/platform.sh update`，确认 Web 镜像完成重建，再检查浏览器缓存和 `/release.json` 中的源码版本。

## 安全与许可证

提交前请确认没有 `.env`、私钥、访问令牌、数据库、用户上传、模型权重或真实业务语料进入暂存区。第三方来源和许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
