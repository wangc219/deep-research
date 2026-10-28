# 智能研究平台

本仓库保留完整装备研究平台源码，并整合面向通用软件研发的文档解析研究入口和 AMiner 学术检索。文档入口的合并变化见 [来源与差异说明](CHANGES_FROM_DEEP_RESEARCH.md)，实际通过、失败和未验证项见 [文档研究验收记录](docs/DOCUMENT_RESEARCH_ACCEPTANCE.md) 和 [AMiner 最终测试记录](artifacts/aminer-integration/final-validation.json)。

本仓库是「装备智能研究平台」的完整单体仓库。`platform_core` 提供共享平台内核，`equipment_deep_research` 封装装备研究领域能力，二者共享同一身份、项目、知识、模型、任务、审计和交付体系。

平台将多智能体深度研究、装备需求 Query 生成、知识库、知识图谱、模型管理和企业权限整合在同一套 Web 工作台中。仓库同时保留当前产品源码、迁移工具、测试、设计文档、参考实现以及可公开的报告、截图和研究产物，便于在新设备上完整恢复开发与部署环境。

架构采用“产品一体化、领域高内聚、协作低耦合”：用户看到一条连续的 Query → 研究 → 证据 → 能力画像 → 深研 → 报告链路；代码内部通过稳定端口和事件契约隔离平台通用能力与装备研究规则。详见 [一体化系统架构](docs/ARCHITECTURE.md)。

## 主要能力

- 多路线装备需求研究：新制胜机理、传统能力缺口和局部战争案例。
- 动态 Agent 编排：独立上下文、工具权限、预算、检查点、失败交接和有界并发。
- 智能体模块化配置：组合模型、提示词、知识库、工具与专用子智能体；Skills/MCP 按需加载，支持在线安装、源码编辑、依赖和角色权限管理。见 [智能体能力对照与验收](docs/AGENT_CAPABILITIES.md)。
- 沙盒工作区与文件交付：智能体读写授权范围内的文件，生成文档、表格、图表、交互网页和代码；支持浏览器预览、Markdown 编辑保存、聊天交付卡片及目录 ZIP 下载。
- 通用文档研究：本地资料问答、连续追问、转为深研方案、BM25 检索排序、候选证据覆盖与关系筛选，以及 Markdown/HTML/CSV/JSON 交付。
- 研究证据治理：公网检索、材料化、正文定位、质量评分、引用与交付清单。
- AMiner 学术检索：智能对话、深研对话及技术攻关舱共享论文发现、摘要补证与一层参考文献追溯；父子智能体共享费用预算。
- 企业级平台能力：用户、租户、部门、角色权限、任务队列、SSE 事件回放和运行监控。
- 视频号转 DOCX：自动复用微信连接、后台识别、Word 下载及文字稿入库。见 [使用与云部署](docs/VIDEO_CHANNELS.md)。
- 知识基础设施：文档解析、混合检索、RAG 评估、知识图谱和知识导图。
- 可审计交付：研究报告、能力画像、运行摘要、追踪事件、检查点和 SHA-256 清单。

## 快速开始

### 环境要求

- Git
- Docker Desktop 或 Docker Engine（含 Compose v2）
- 建议至少 16 GB 内存和 30 GB 可用磁盘空间
- 仅做本地源码开发时：Python 3.12–3.13、Node.js 22+、pnpm

### 从 GitHub 完整恢复

2026-10-12 验收状态：现有完整开发栈的 API、PostgreSQL、Redis 和 Worker 就绪检查通过，AMiner 的应用侧检索链路已验证；本轮未覆盖新设备首次冷安装。通用文档入口的可选 Docker 部署与独立启动方式见 [使用说明](docs/DOCUMENT_RESEARCH.md)。

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
调研探索员按单个子问题建立“核心对象/实体 + 作用或指标 + 场景/约束”的短查询；对同名或易漂移主题可用
`required_terms` 指定最多三个必须命中的核心锚点。平台在多引擎结果合并后再次执行锚点过滤和标题优先排序，
减少只命中泛词、相邻领域或错误对象的结果进入主智能体上下文。

新设备迁移只需复制仓库与部署级 `.env` 后执行 `bash scripts/platform.sh start`。检索服务使用 Compose
服务名 `http://open-websearch:3210`，不依赖原设备 IP、绝对路径或宿主机浏览器。默认镜像按多架构 digest
锁定，可通过 `OPEN_WEBSEARCH_IMAGE` 显式升级；网络需走代理时设置
`OPEN_WEBSEARCH_USE_PROXY=true` 和 `OPEN_WEBSEARCH_PROXY_URL`。诊断命令：

```bash
docker compose exec open-websearch node build/index.js status --base-url http://127.0.0.1:3210 --json
docker compose exec api python -c "import httpx; print(httpx.get('http://open-websearch:3210/health').json())"
```

## AMiner 学术检索

管理员或超级管理员在「模型设置」(`/models`) 的「AMiner 学术检索」卡片填写 AMiner 用户 ID 和 API Key，保存后使用「测试连接」验证免费标题搜索，再启用并保存。也可以先测试当前表单；测试输入不会被保存。新配置默认停用，普通用户使用平台提供的检索能力。密钥只返回脱敏状态，编辑时留空保留原密钥，替换或清除使用对应操作；不要将凭证写入仓库或 `.env`。免费连接测试不代表已经取得所有付费接口权限。

凭证框同时接受原始 API Key 和 AMiner 控制台「一键生成 Token」得到的 JWT（也兼容带 `Bearer` 前缀粘贴）。原始 API Key 由服务端自动签发短期 JWT；控制台 Token 直接用于鉴权，到期后需在控制台重新生成并替换。若控制台展示的 Key 无法通过自动签名鉴权，可改用官方生成的 Token，并以免费连接测试结果为准。

两类对话共用以下内置工具，调研探索员和事实核查员也可使用：

| 工具 | 使用方式 |
| --- | --- |
| `academic_search` | 主题发现使用 Pro 搜索，已知论文标题使用免费标题搜索；可通过 `related_queries` 增加最多两个中英文术语或互补角度，合并去重后补齐免费题录与部分摘要。 |
| `academic_get_papers` | 筛选拟引用论文后，按需获取完整摘要；支持仅补齐免费题录。 |
| `academic_get_references` | 追溯核心论文引用的参考文献，只扩展一层；不是后续引用者列表。 |

论文、研究进展和技术路线比较问题优先使用 AMiner，技术攻关舱预加载深研技能时也遵循这一策略。一般问答保持原流程，其他公开事实使用网页检索，内部事实使用已授权知识库。只向 AMiner 发送简短公开科研检索词，禁止发送完整会话、内部文档或能力画像原文。题录、部分摘要和完整摘要均不等于论文全文；精确实验数据只能引用实际取得的证据，同一论文经多个渠道找到仍只算一个独立来源。

联合检索的每个不同检索词分别计入原有搜索限额，重复术语在发请求前消除。结果交错保留各角度候选，最终最多返回 `limit` 篇，并提供逐词覆盖、下一页提示、未执行查询和摘要缺口；跨查询总量不相加冒充独立论文数。`order=recent` 在各查询中按年份检索进展，`order=cited` 查找经典工作。题录或详情补全失败时保留已取得的更完整证据；未返回的论文、缺失的完整摘要及参考文献截断均显式标记。2026-10-16 真实接口验证见 [AMiner 检索验证记录](artifacts/aminer-retrieval-20261016/live-validation.json)。

管理员可在高级设置中调整以下每轮共享限额。主智能体、子智能体和恢复运行使用同一父 Run 账本；外部请求发送前通过 PostgreSQL 事务预占次数和费用，重试也计入限额，缓存命中不占付费预算。

| 默认限额 | 智能对话 | 深研对话（含技术攻关舱） |
| --- | ---: | ---: |
| Pro 搜索次数 | 2 | 6 |
| 完整摘要详情次数 | 3 | 10 |
| 参考文献查询次数 | 1 | 2 |
| 预估费用上限 | 0.20 元 | 0.50 元 |

预估账本按 Pro 搜索、详情各 0.01 元/次，参考文献 0.10 元/次计算，实际价格和权限以 [AMiner 官方文档](https://www.aminer.cn/open/board?tab=doc) 为准。搜索缓存 1 小时，题录、详情和参考文献缓存 24 小时。每次请求超时 10 秒，临时网络或服务错误最多重试一次。配置修改后后续调用读取新配置；鉴权失败、限流、停用或额度耗尽时，模型使用网页、知识库和已有证据继续完成回答。

2026-10-12 应用侧验收：116 项后端相关回归、10 个真实模型自动调用场景、529 项前端测试以及前端 Lint 和构建通过。场景覆盖智能对话、深研、技术攻关舱全部技能预加载、研究子智能体、参考文献追溯、故障降级和引用来源核对。浏览器确认论文卡片和正文 URL/DOI 引用可点击。**本轮没有配置 AMiner 凭证，供应商响应采用模拟数据；真实鉴权、付费权限、检索质量和延迟仍需配置后验证。**具体运行边界见 [最终测试记录](artifacts/aminer-integration/final-validation.json)。

2026-10-15 已使用控制台 Token 完成真实免费标题搜索、Pro 搜索、完整摘要和参考文献接口验收，并验证实际 PostgreSQL 费用预占链路。该次验证记录见 [AMiner 实接口接入记录](artifacts/aminer-live-20261015/validation.json)；原始 API Key 和 Token 仅保存在部署数据库中，不随仓库分发，新部署仍需自行配置。

2026-10-19 增加围绕当前问题的学术证据筛选：普通对话与研究子智能体预加载轻量检索技能，明确要求论文检索/摘要来源时先执行首次检索，再以强相关候选的完整摘要支撑技术解释。仅关键词重合或同属宽泛领域的论文不作为核心证据；摘要未支持的性能与适用性推论需另行标注。误把 arXiv 编号、DOI 或 URL 当作 AMiner ID 时，在请求发出前返回可恢复的定位提示。

调研探索员的交付定位是服务主智能体，而不是独立生成固定格式的小报告：优先返回能改变判断、补齐关键链条、揭示约束或推翻弱假设的高价值发现，并说明其对主研究的意义。技术原理、材料/器件、算法、工程可行性、性能边界或成熟度类子问题在未禁用且缺少既有论文证据时，运行时优先触发 AMiner 主题发现；一般公开事实仍走 Open Websearch。

面向未来需求的装备创新研究以用户目标为主线，论文检索仅作按需辅助，不规定对话步骤、章节或固定推演链条，不要求先有现成装备或已知技术瓶颈。涉及技术实现且需要新证据、原理启发或可行性核实时，可用强相关论文启发、补证或修正构想，不为每个构想强行匹配论文，也不以取得或引用摘要作为完成标准。论文结论、类比迁移、工程推断和待验证假设应分开表达；摘要未覆盖的实现细节不得补写为事实，论文级结果不表示已验证装备级可用性。

官方 MCP 连接已预置于「知识库 · 技能 → MCP」（`/extensions?tab=mcp`），地址为 `https://mcp.aminer.cn/mcp`，运行时复用模型设置中的 AMiner 凭证，不另存密钥。该连接默认停用，避免向普通技术研究加载学者、机构等旁支工具；管理员有明确需求时可启用。主题搜索、标题定位和完整摘要的三轮同条件实测中，REST 与 MCP 内容相同，REST 单请求中位耗时约 0.20 秒、MCP 约 0.97–1.03 秒，因此论文主路径保留已有 REST 工具、共享缓存与费用预算，MCP 默认关闭五个重复论文工具。该耗时只适用于本机本轮接口对比，不代表端到端回答稳定提速。记录见 [MCP 与相关性验证](artifacts/aminer-mcp-20261019/validation.json)。

相关验证命令（需已启动完整开发栈并安装测试依赖）：

```bash
docker compose exec api python -m pytest \
  test/unit/services/test_aminer.py \
  test/integration/services/test_academic_retrieval.py \
  test/integration/api/test_aminer_api.py -q
docker compose exec web pnpm run lint:check
docker compose exec web pnpm run test:unit
docker compose exec web pnpm run build
```

真实模型探针默认跳过。显式设置下面两个环境变量时会调用平台已配置的模型，产生模型服务用量；AMiner 仍使用隔离模拟响应，不修改在线凭证配置：

```bash
docker compose exec \
  -e RUN_AMINER_MODEL_PROBE=1 \
  -e AMINER_PROBE_MODEL='<供应商ID>:<已配置模型ID>' \
  api python -m pytest test/integration/services/test_academic_retrieval.py -k live_model -q
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
uv sync --project backend --group test
pnpm --dir=web install --frozen-lockfile
```

常用检查：

```bash
uv run --project backend --group test python -m pytest backend/test/unit -m "not slow" -q
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

旧存储布局升级需要维护窗口和可恢复备份。云端使用 `sudo bash scripts/migrate-storage.sh --env-file .env.prod -f compose.prod.yaml -f docker/document-research/compose.yaml -f compose.cloud.yaml`，脚本停止应用写入者，等待动态沙盒全部退出，再为一次性迁移器签发停机证明；任一步失败都不会放行迁移。完成后应用保持停止，使用相同 Compose 配置的 `sudo bash scripts/cloud.sh up -d` 启动并检查 readiness。此入口会终止活动任务，应先确认没有仍需保留的运行中任务。

## 文档索引

- [简洁使用说明](docs/研究平台简洁使用说明.docx)
- [管理员与普通用户详细使用手册](docs/研究平台使用说明-详细版.docx)
- [装备智能研究平台简洁使用说明](docs/装备智能研究平台简洁使用说明.docx)
- [系统功能测试说明](系统功能测试说明.docx)
- [AMiner 最终测试记录与场景明细](artifacts/aminer-integration/final-validation.json)
- [文档研究合并验收记录](artifacts/main-sync-validation-20261012/results.json)
- [文档研究最新同步与可选公网检索验收](docs/validation/document-research/followup-sync-20261012/README.md)
- [沙盒工作区与文件交付验收](docs/validation/document-research/delivery-20261012/README.md)
- [文档研究配置与启动说明](docs/DOCUMENT_RESEARCH.md)
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

## 通用文档解析研发入口

入口位于“知识库 · 技能 → 知识库 → 文档解析与研究”（`/extensions?tool=document-research`），原 `/document-research` 自动跳转到该分区，不再占用独立主导航。它用于普通软件文档解析研究：上传 PDF、DOCX、TXT、Markdown 需求或失败样本，先预览检索证据，再获取带原文引用的回答或生成比较方案、实验步骤与拟定验收指标。完成后可继续追问，或据此细化深研方案；每轮重新检索，最多沿用三个用户问题，重新确认外发范围。常规知识库文档的 OCR、解析、分块和索引仍在“资料库 → 对应知识库”中完成。两条流程的作用、数据边界和限制见[完整功能分析](docs/DOCUMENT_RESEARCH.md#功能作用与知识库的关系)。

| 来源或产物 | 使用方式 |
| --- | --- |
| 本地资料 | 按本次任务勾选资料库；无需智谱知识库配置即可问答和研究。 |
| 智谱知识库 | 可选的只读来源；配置后仅检索当前任务勾选且授权的库，未配置或未勾选可跳过。 |
| Open Websearch | 默认公网搜索提供商，无需智谱密钥；按需勾选“启用公开网络检索”，只发送单独填写的公开关键词。管理员可设置地址、搜索引擎，也可显式切换为智谱公开搜索。 |
| 模型设置 | 连接专用服务后在页面配置地址、模型名、密钥和思考强度；密钥不回显，留空保留，显式清除才删除。 |
| 研究文件交付 | 预览和下载 Markdown、HTML、CSV、JSON，支持 ZIP 打包；Markdown 可编辑保存，编辑副本不改变原报告及其他格式。 |

此入口使用专用服务、数据、访问令牌和模型配置，与原平台 `/models` 设置分别管理。默认 `scripts/platform.sh start` 不启用该服务；需按 [配置与启动说明](docs/DOCUMENT_RESEARCH.md) 启动本机服务，或启用可选 `docker/document-research/compose.yaml` 覆盖层及专用搜索服务，再连接页面。原智能对话、沙盒工作区和其他路由继续使用原平台。

2026-10-12 最新同步验收：文档研究 373 项、前端 530 项、浏览器 20 场景通过，真实 Open Websearch 公网检索和独立生产容器接线通过。生成模型使用合成提供商；该结果不等于真实模型报告质量、候选解析器性能或当前完整平台部署已验收。此处前端数量对应文档研究同步版本，AMiner 的验收范围单独记录于上文。

功能边界、实际失败过程和测试证据见 [最新同步验收](docs/validation/document-research/followup-sync-20261012/README.md) 与 [完整验收历史](docs/DOCUMENT_RESEARCH_ACCEPTANCE.md)。
