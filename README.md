# 装备智能研究平台

本仓库是「装备智能研究平台」的完整单体仓库。`platform_core` 提供共享平台内核，`equipment_deep_research` 封装装备研究领域能力，二者共享同一身份、项目、知识、模型、任务、审计和交付体系。

平台将多智能体深度研究、装备需求 Query 生成、知识库、知识图谱、模型管理和企业权限整合在同一套 Web 工作台中。仓库同时保留当前产品源码、迁移工具、测试、设计文档、参考实现以及可公开的报告、截图和研究产物，便于在新设备上完整恢复开发与部署环境。

架构采用“产品一体化、领域高内聚、协作低耦合”：用户看到一条连续的 Query → 研究 → 证据 → 能力画像 → 深研 → 报告链路；代码内部通过稳定端口和事件契约隔离平台通用能力与装备研究规则。详见 [一体化系统架构](docs/ARCHITECTURE.md)。

## 主要能力

- 多路线装备需求研究：新制胜机理、传统能力缺口和局部战争案例。
- 动态 Agent 编排：独立上下文、工具权限、预算、检查点、失败交接和有界并发。
- 研究证据治理：公网检索、材料化、正文定位、质量评分、引用与交付清单。
- 企业级平台能力：用户、租户、部门、角色权限、任务队列、SSE 事件回放和运行监控。
- 知识基础设施：文档解析、混合检索、RAG 评估、知识图谱和知识导图。
- 可审计交付：研究报告、能力画像、运行摘要、追踪事件、检查点和 SHA-256 清单。

## 快速开始

### 环境要求

- Git
- Docker Desktop 或 Docker Engine（含 Compose v2）
- 建议至少 16 GB 内存和 30 GB 可用磁盘空间
- 仅做本地源码开发时：Python 3.12–3.13、Node.js 22+、pnpm

### 从 GitHub 完整恢复

```bash
git clone git@github.com:wangc219/deep-research.git
cd deep-research
bash scripts/platform.sh start
```

`start` 会在首次运行时生成本机 `.env`、补齐安全随机值、构建镜像并启动完整服务栈。真实模型的供应商、模型 ID 和 API Key 请在登录后的「模型设置」页面配置；密钥不应提交到 Git。

常用运维命令：

```bash
bash scripts/platform.sh status
bash scripts/platform.sh logs
bash scripts/platform.sh stop
bash scripts/platform.sh update
```

默认入口：

- Web 工作台：<http://localhost:5173>
- API：<http://localhost:5050>
- API 就绪检查：<http://localhost:5050/api/system/ready>

## 仓库布局

```text
backend/
  server/                         FastAPI HTTP/SSE 适配层
  package/
    platform_core/                平台内核
    equipment_deep_research/      装备研究领域与编排
    knowledgegraph/               需求发现与知识图谱
  test/
web/                              Vue 3 工作台（知识门户、对话、研究任务）
docker/                           镜像与沙盒
configs/                          装备研究 Harness 配置
scripts/migration/                SQLite 历史数据迁移
compose.yaml                      开发配置
compose.local.yaml                日常运行覆盖层（默认无热重载）
compose.prod.yaml                 生产环境配置
output/                           可版本化的展示与导出产物
artifacts/                        产品截图与验收素材
projects/                         项目级演示、报告和验证结果
report/                           设计、进展与交付报告
```

首次或代码更新后一键构建启动：`bash scripts/platform.sh start`。该入口会自动补齐首次初始化，无需再手工串联两个脚本。日常启动使用 `bash scripts/platform.sh up`，不强制重建。默认保留全部业务服务，前端使用静态资源、后端关闭热重载。开发时使用 `PLATFORM_MODE=dev bash scripts/platform.sh start`。登录后进入 `/knowledge` 领域知识总门户。聊天模型、装备研究、需求 Query 和深研对话统一在「模型设置」(`/models`) 配置，不要把模型 ID 或 API Key 写进 `.env`。

## 配置与运行模式

初始化模板位于 `.env.platform.example`。本地环境使用 `.env`，生产环境默认使用 `.env.prod`；二者均包含部署密钥，因此不会进入版本库。支持三种 Compose 模式：

```bash
PLATFORM_MODE=local bash scripts/platform.sh start  # 默认，适合日常使用
PLATFORM_MODE=dev bash scripts/platform.sh start    # 开发模式
PLATFORM_MODE=prod bash scripts/platform.sh start   # 生产模式，读取 .env.prod
```

如需更换端口、状态目录或 Compose 项目名，请先复制并修改环境模板。完整运行参数与资源建议见 [运行与资源优化](docs/RUNTIME_OPERATIONS.md)。

## 公网检索

智能对话、深研对话及其子智能体共用一个 `web_search` 工具。完整 Compose 默认随栈启动
[open-websearch](https://github.com/aas-ee/open-websearch) daemon，通过 Bing、DuckDuckGo 多引擎并发检索；
单个引擎失败时保留其他引擎结果，daemon 故障时继续切换豆包、Tavily（已配置密钥时）和内置公开检索。
结果缓存、重试、熔断和每轮调用预算会阻止子智能体在故障期间无限改写查询。

新设备迁移只需复制仓库与部署级 `.env` 后执行 `bash scripts/platform.sh start`。检索服务使用 Compose
服务名 `http://open-websearch:3210`，不依赖原设备 IP、绝对路径或宿主机浏览器。默认镜像按多架构 digest
锁定，可通过 `OPEN_WEBSEARCH_IMAGE` 显式升级；网络需走代理时设置
`OPEN_WEBSEARCH_USE_PROXY=true` 和 `OPEN_WEBSEARCH_PROXY_URL`。诊断命令：

```bash
docker compose exec open-websearch node build/index.js status --base-url http://127.0.0.1:3210 --json
docker compose exec api python -c "import httpx; print(httpx.get('http://open-websearch:3210/health').json())"
```

## 知识库能力

知识库是平台内建共享能力，与智能对话、需求 Query、装备研究和深研链路复用同一套身份授权、检索、引用和审计服务：

- 管理文件与真实目录，展示解析、分块、Chunk、Token 和向量入库状态；支持 PDF、Word、PPT、Excel、Markdown 等常用格式与多种 OCR/解析引擎。
- 支持向量、BM25 和混合检索，可配置相似度阈值、候选数量、融合权重、图检索与 Rerank，并在检索工作台查看分数、来源文件和 Chunk 引用。
- 支持上传或自动生成单跳、多跳问答基准，批量执行 RAG 评估并查看逐题结果与量化指标。
- 支持从知识块抽取实体与关系到 Neo4j、浏览子图与节点详情，并按目录和文件元数据生成知识导图。
- 支持本地 Milvus 知识库以及 Dify、Notion 等外部只读数据源；Agent、深研和装备研究任务通过统一检索端口调用。
- 知识库按所有者、租户、部门、指定用户和读写范围授权；每次工具调用重新解析实时权限，显式知识库范围只能收窄授权。

服务端就绪检查必须显示 `knowledge_base.status=ok`；检索质量可在知识库详情的「检索测试」和「评估」页持续验证。完整映射与验收命令见 [知识库能力对齐基线](docs/KNOWLEDGE_BASE_ALIGNMENT.md)。

企业管理入口为 `/enterprise`，提供租户与部门组织、成员管理、功能读写权限和运行监控。研究任务、Query、画像、报告、收藏和深研对话按个人隔离，超级管理员可查看全局。部署迁移、权限规则与验收说明见 [企业多用户与双工作台融合](docs/ENTERPRISE_MULTIUSER.md)。

历史 SQLite 导入：

```bash
python scripts/migration/import_legacy_sqlite.py dry-run
python scripts/migration/import_legacy_sqlite.py import \
  --owner-uid <uid> \
  --project-id <project> \
  --artifact-root <该项目在宿主机上的工作目录>
python scripts/migration/import_legacy_sqlite.py validate --batch-id <batch-id>
```

导入器以只读方式打开旧 SQLite，兼容 `application.db`、`query-library.db`，并自动补录只有
`outputs/runs/*/round_summary.json` 的早期任务。任务、Query、能力画像、收藏、深研记录及报告产物按
旧 ID 幂等迁移；未知旧状态归一为 `completed`，导入任务保持只读。请先执行 `dry-run`，并确认
`--owner-uid` 与 `--project-id` 的真实归属；导入器会拒绝把数据写入不属于该用户的项目。

## 开发与验证

后端依赖使用 `uv` 锁定，前端依赖使用 `pnpm` 锁定：

```bash
uv sync --project backend
pnpm --dir=web install --frozen-lockfile
```

常用检查：

```bash
uv run --project backend pytest backend/test/unit -q
pnpm --dir=web test:unit
pnpm --dir=web build
docker compose --env-file .env -f compose.yaml -f compose.local.yaml config --quiet
```

测试按 `backend/test/unit`、`backend/test/integration` 和 `backend/test/e2e` 分层；完整集成测试需要已启动的 PostgreSQL、Redis、Milvus、MinIO、Neo4j 和 Sandbox 服务。

## 产物与数据说明

仓库会版本化可公开、可复核且有交付价值的源码和产物，包括 `output/`、`outputs/runs/`、`outputs/deep-thinking/`、`outputs/evals/`、`artifacts/`、`projects/`、`report/` 和 `screenshots/`。研究报告、来源材料、证据索引、追踪事件、能力画像、检查点、运行数据库和交付清单均随版本保存。以下内容刻意不进入 Git：

- `.env*` 实际配置、私钥和第三方 API Key；
- `auth.json`、Codex 会话目录和本机登录状态；
- Docker 数据卷、服务级数据库、数据库 WAL/SHM、缓存、虚拟环境和 `node_modules`；
- `outputs/runtime/`、`outputs/runs/runtime/` 等进程锁、Codex Home 和临时 Agent 工作区。

这些目录属于设备状态而非可移植源码。全新克隆可通过初始化脚本重建；若要迁移正在运行的生产数据，请先停止写入，再按 [交付说明](docs/DELIVERY.md) 和 [企业多用户部署说明](docs/ENTERPRISE_MULTIUSER.md) 单独备份数据库、对象存储与状态目录，切勿把凭据直接提交到仓库。

## 文档索引

- [系统架构](docs/ARCHITECTURE.md)
- [快速上手](docs/QUICK_START.md)
- [集成指南](docs/INTEGRATION_GUIDE.md)
- [验收说明](docs/ACCEPTANCE.md)
- [模型运行时集成](docs/MODEL_RUNTIME_INTEGRATION.md)
- [平台知识库能力基线](docs/KNOWLEDGE_BASE_ALIGNMENT.md)
- [平台内核来源与融合记录](docs/migration/PLATFORM_CORE_PROVENANCE.md)
- [企业多用户与权限](docs/ENTERPRISE_MULTIUSER.md)
- [第三方来源与许可证](THIRD_PARTY_NOTICES.md)

第三方代码来源与许可证见 `THIRD_PARTY_NOTICES.md`。旧的 `docker-compose.yml`、`apps/web` 以及根目录 `src/` 下的迁移前实现仅作为历史源码和比对材料，不进入当前 Compose 在线运行；当前可执行包统一位于 `backend/package/`。研究任务、需求 Query 与深研对话统一由 Vue、`/api/equipment`、PostgreSQL 和平台 Durable Task Worker 承载；旧数据只读迁移后继续展示。

资源实测、启动模式、构建缓存与故障回退见 [运行与资源优化](docs/RUNTIME_OPERATIONS.md)。
