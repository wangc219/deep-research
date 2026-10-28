# 启动、构建与资源使用

## 推荐入口

首次部署、代码更新后的完整构建与启动统一使用：

```bash
bash scripts/platform.sh start
```

`start` 会在需要时自动执行首次初始化，然后构建并启动所有 Deep Research 服务。

平台基础设施变量统一使用 `DEEP_RESEARCH_*` 前缀。启动入口会将历史 `.env` 中对应的旧键原值迁移；新键与旧键同时存在时始终以新键为准。迁移不改变端口、数据目录、实例标识或安全密钥的值。

模型 API Key 在启动后的 `/models` 页面配置。初始化不再强制索取 SiliconFlow 密钥；不会覆盖数据库中已有模型配置。

日常 `up` 不强制构建；源码更新后执行 `bash scripts/platform.sh update`。停止服务用 `stop`，查看状态用 `status`，日志用 `logs api worker`。脚本从任意工作目录调用都定位到仓库根目录。默认最多并行构建两个目标，可用 `COMPOSE_PARALLEL_LIMIT` 调整。

`start-local.sh` 默认转到同一融合入口，不再意外启动第二套旧 API 和前端。确需独立历史项目时才设置 `EQUIPMENT_DR_STANDALONE=1`。

## 三种运行方式

| 模式 | 命令前缀 | 前端 | 后端 |
|---|---|---|---|
| 日常运行（默认） | `bash scripts/platform.sh` | Nginx 静态资源，端口 5173 | 无热重载，保留源码挂载，更新后需重建/重启 |
| 开发 | `PLATFORM_MODE=dev bash scripts/platform.sh` | Vite/HMR | API 与平台 Worker 文件监听 |
| 生产 | `PLATFORM_MODE=prod bash scripts/platform.sh` | 静态资源 | 镜像内源码，不依赖开发挂载 |

生产使用 `.env.prod`；`DEEP_RESEARCH_ENV_FILE` 可指定其他配置文件。不要将普通本地开发密钥直接当作生产部署方案。运行 `bash scripts/platform.sh config` 只校验配置，不输出凭据。

开发与日常模式复用同一项目名、端口、数据库和研究输出，不会同时启动两套环境。前端使用独立镜像标签，切换模式不会把开发镜像误当成静态镜像。需要回到开发模式时执行 `PLATFORM_MODE=dev bash scripts/platform.sh up`。

## 调研探索员三源互补（2026-10-20）

探索员围绕同一子问题综合 Open Websearch、AMiner 与本轮已授权启用的知识库，以互补性、新颖性和对新质武器装备的启发价值筛选资料。网页侧重新进展、案例与反常现象，论文侧重新原理、新方法和实验发现，本地知识库侧重研究积累、领域联系与未解问题；每类来源都可以提供启发或反例。综合不同认识、差异和矛盾，识别单一来源未呈现的可能性，区分取得的事实、创新联想、跨域类比与待验证假设。已有成熟案例不构成创新方向上限，不要求每个启发都有现成装备对应，也不强求三源结论一致。

运行时确保已启用知识库贡献本地视角；其权限与显式启用规则沿用现有边界。论文技术结论读取强相关候选的完整摘要，本地关键事实按需打开原文；同一论文跨渠道命中不增加独立来源数。单个网页渠道连续两次无增量或达到网页整理阈值，只停止网页发现，仍允许补齐论文摘要和授权本地原文；总工具次数、耗时和每批调用上限继续生效。网页最多 8 次是上限，达到研究目的即可提前交付。

Open Websearch 明确返回的 CAPTCHA、反爬、访问验证或 HTTP 403，以及直连兜底 HTTP 200 的挑战页，会进入按引擎共享的 Redis 冷却。`WEB_SEARCH_ANTIBOT_COOLDOWN_SECONDS` 默认 300 秒，边界为 30–3600 秒；daemon 与直连兜底共享同一引擎的冷却，健康引擎继续可用，受挑战引擎不在同一次调用内等待重试。所有可用网页入口均失败时转为本子任务的网页降级，继续使用 AMiner、授权知识库和已有信息。真正的空命中与反爬分开处理；daemon 把挑战吞成空数组且未提供失败信息时，后端仍只能识别为空命中，依靠无增量停止规则收敛。

源码更新后的 API、Worker 与内置预设同步按常规更新流程生效。单元测试和真实 Redis 协调测试验证检索边界与故障切换，不能据此推断真实供应商持续可用或模型的创新质量提升幅度；实际启发质量仍需真实研究样本评审。

## 已做的资源优化

1. 日常模式关闭 API reload、Worker watchfiles，前端由静态 Nginx 提供。全部业务服务保留，不通过停用知识库或研究 Worker 来降低资源。
2. 启动和健康检查直接使用已安装的 Python/ARQ，运行期关闭 uv 字节码批量编译。Docker Worker 健康检查间隔为 30 秒；内部 Worker heartbeat 未放宽。
3. 本地平台任务并发默认 8，连接池默认 12、额外连接 8，Redis 连接默认 64；可通过 `LOCAL_*` 参数调整。此限制不改写动态蜂群的阶段顺序、质量门禁或具体 Agent 工作内容。
4. Python 依赖层只取决于锁文件和包元数据；业务源码复制在安装外部依赖之后。BuildKit 复用 uv 缓存，不再在每次代码变化时重装所有依赖。
5. 前端开发与构建共享依赖层，构建时包含旧 React 工作台源码；最终镜像只保留静态产物。
6. 构建上下文排除运行输出、node_modules、虚拟环境、缓存和 `.env` 凭据。排除不删除本地数据，也不执行 Docker prune。
7. 生产 Compose 补齐原研究 Worker、Query Worker 及输出目录挂载；平台 Worker 与 API 共享研究交付物，避免容器替换后丢失文件或门户读不到报告。
8. 静态网关保留 SSE 无缓冲转发、长连接超时和知识库文件上传容量；网关上限 128 MiB，实际文件限制仍由后端 100 MiB/附件 5 MiB 规则执行。

## 本机实测（2026-09-24）

Mac 为 10 核、24 GiB 内存；Colima 为 4 vCPU、10 GiB 上限，使用 ARM 原生、VZ、virtiofs，没有 Rosetta 模拟。未修改或重启全局 Colima，以免影响其他工作负载。

| 观测项 | 切换前 | 切换后 |
|---|---:|---:|
| 前端容器内存 | 1.895 GiB | 4.75 MiB |
| API 容器内存 | 481.8 MiB | 423.9 MiB |
| 平台 Worker 内存 | 221.9 MiB | 212.8 MiB |
| 全部 12 个业务容器内存之和 | 约 3.7 GiB | 约 1.7 GiB |
| 相同源码前后端再次构建 | 未测 | 0.83 秒，命中缓存 |

这是本会话的观测样本，切换前开发容器已有测试/构建活动，不代表每台机器的固定占用。容器 CPU 样本合计约为一个核心的 9%–11%，未观测到持续满载；macOS 的 VM 进程当时约占单核三分之一，不能把它直接理解成整机 33%。

构建、首次导入、图谱计算或并行研究可能出现短时峰值。虚拟机的宿主 RSS 还包含 guest 文件缓存，构建后不会必然立即回落到容器内存之和。因此目前证实的是常驻前端和容器内存下降、重复构建命中缓存；没有据此声称 Colima CPU 已下降某个固定百分比。

## 运维检查

### 云端页面加载（2026-10-15）

研究任务列表支持 `GET /api/equipment/runs?compact=true`，返回列表所需的状态、权限、模型标签和产物计数，完整摘要由任务详情接口读取。能力画像列表支持 `compact=true`，合并重复的历史 `snapshot` 正文。两项参数默认关闭，以兼容原 API 客户端；Web 已使用精简投影。门户最近任务仅返回展示字段。

容器 Nginx 对 JavaScript、CSS、JSON 等开启 gzip；`/assets/` 使用一年不可变缓存，HTML 使用 `no-cache` 以便发现新版本。找不到的静态资源返回 404。API 不设置共享响应缓存，SSE 保留无缓冲转发，`text/event-stream` 不参与 gzip。

deepquest.space 的宿主 HTTPS 网关直接将 `/api/` 转发到 API，因此还必须配置宿主压缩。当前站点配置保存在 `docker/nginx/cloud.conf`，对应服务器 `/etc/nginx/sites-available/deepquest`；更新后先运行 `sudo nginx -t`，成功后再 reload Nginx。该配置包含当前域名与证书路径，其他部署需按实际值调整。

本次公网单次样本：任务列表传输量从 5,092,390 降至 4,991 字节，门户从 4,631,521 降至 7,817 字节，能力画像从 6,898,637 降至 820,809 字节。前值为原未压缩响应，后值为精简接口加 gzip；记录数与详情正文一致。具体请求耗时及验证范围见 `artifacts/cloud-performance-20261015/`，单次样本不代表所有网络或并发负载。

```bash
bash scripts/platform.sh status
curl http://127.0.0.1:5173/api/system/ready
docker stats --no-stream
```

研究领域代码更新时，应同步更新 API、平台 Worker、原研究 Worker 和 Query Worker。原研究队列使用版本签名隔离；只重启 API 可能让任务无法被旧 Worker 领取。

模型计量补写队列位于 `/app/outputs/model-call-outbox.db`，由 API 和三个 Worker 通过共享 `outputs` 持久卷访问。不要在服务运行时手工删除该文件；数据总览的“待同步调用”持续大于 0 时，应先检查 PostgreSQL 健康与磁盘权限。

已通过静态网关访问的真实 HTTP 企业隔离与 fake 研究队列验收，以及统一模型账本/趋势验收。API、PostgreSQL、Redis、Worker readiness 正常。完整真实研究的质量和供应商可用性仍以 [统一运行时验收记录](MODEL_RUNTIME_INTEGRATION.md) 为准。

2026-09-24 追加空闲样本：约 30 秒的四次容器采样，总 CPU 分别为 5.54%、11.22%、13.75%、13.65%（Docker 按单核 100% 口径）；API 为 0.25%–2.66%，内存约 476 MiB。此前一次启动后瞬时 API 为 29.21%，随后回落；这些样本未显示持续满载，但不代表并行研究或生产负载测试。整组容器内存约 1.8 GiB，前端约 5 MiB。

### 性能与恢复核查（2026-10-15）

Query 生成每批 2 个维度、最多并发 2 批，通过质量校验后立即保存。重试复用已保存候选，仅补齐缺失维度；规划检查点按模型、生成策略及输入指纹匹配，固定有效期 1 小时，旧版无指纹检查点重新规划。任务返回 `batch_progress`，记录本次执行耗时、生成请求批次、修复批次、恢复数量及最近校验拒绝原因；`model_seconds` 为各批生成请求耗时之和，并行时可能大于墙钟耗时。模型的内部传输重试不计作新的生成批次。

研究事件每 100 条共用一个 PostgreSQL 事务，在 Run 行锁下分配连续序号，提交后使用 Redis pipeline 按批内顺序发布；事件查询仍以 PostgreSQL 为准。研究、Query 与深研等长模型任务使用可配置的 `EQUIPMENT_TASK_LEASE_SECONDS`（默认 600 秒）作为单次阻塞调用的安全余量，心跳仍每 10 秒续租；普通短任务继续使用 30 秒 lease，避免扩大其失联恢复窗口。研究任务继续通过显式参数隔离模型、接口和密钥，无需全局环境锁。知识库维持按需调用、每次重验可见范围，搜索继续使用多引擎、共享协调、缓存、有限重试与每轮预算。

Query、研究任务、任务详情和报告页面共用一个刷新调度器，隐藏标签页暂停，刷新完成后才安排下一轮；相同资源及参数的在途请求合并，不同筛选的旧响应不覆盖新结果。研究列表观察到终态变化后刷新画像、报告、收藏与深研会话。日常运行保持 Nginx 静态前端和关闭热重载，构建上下文排除临时目录、参考仓库与研究产物。逐项结论、测试与部署证据见 `artifacts/performance-audit-20261015/validation.json`。

### 云端多用户并发（2026-10-15）

云端实测为 4 个 vCPU、7.4 GiB 内存，调整前可用约 4.3 GiB，PostgreSQL 最大连接 100、当时共 28 个连接。平台 Worker 原总并发 4，会同时限制聊天、子任务及装备任务。`compose.cloud.yaml` 现单独设置 Worker 总并发 16、研究任务默认槽位 6、Query 生成任务 4、深研轮次 8、普通持久任务 4；这些是独立任务类型上限，仍共用 Worker 总并发，并不保证每类同时达到上限。每个 Query 任务仍最多并发 2 个生成批次。

API/Worker PostgreSQL 池分别为 12+4，检查点池分别为 4/12，Redis 连接上限分别为 64；不增大 PostgreSQL 的 `max_connections`。这些连接池按需建立连接，不能将任务槽位当作 CPU 核数或数据库连接数。研究槽位同时写入平台系统设置，后续可通过研究任务页面热调整。`CLOUD_*` 环境变量可覆盖云端默认值；旧 `.env.prod` 的 `ARQ_MAX_JOBS=4` 不再压住云端覆盖层。修改后使用 `bash scripts/cloud.sh up -d --no-deps --no-build api worker`，不需要重建镜像。

`scripts/cloud.sh` 固定按 `compose.prod.yaml` → `docker/document-research/compose.yaml` → `compose.cloud.yaml` 的顺序叠加。这样云端 Web 同时保留 `/document-research-api` 代理与专用网络，并由最后一层继续把入口限制在 `127.0.0.1:8088`。全新的 `document-research-data` 卷需先执行一次 `bash scripts/cloud.sh document-init`；已有配置的卷不要重复初始化。随后用 `bash scripts/cloud.sh up -d` 启动平台、`document-websearch`、`document-research` 与 Web。

内核为 Linux 7.0.0-14-generic，`somaxconn=4096`，采样未见内存 PSI 压力或持续 swap in/out，保留原内核参数。API/Worker 原文件句柄软上限仅 1024，同步调整为软上限 8192、硬上限 65536，给多用户连接与工具子进程保留余量。此次是有余量的初步扩容，未以付费模型进行满载压测；内存、CPU 和模型限流仍需以真实业务负载观察。核查与验证记录保存在 `artifacts/cloud-capacity-20261015/`。

### 知识抽取与解析性能（2026-10-20）

图谱默认均衡参数为并发 8、整次调用时限 180 秒、正文输出预算 8192 tokens。SiliconFlow 保留思考，默认思考预算 2048 tokens；稳定方案使用 4096，快速方案明确关闭思考。参数位于知识图谱 → 索引管理 → 调整。Schema、相邻上下文和受控假设不随性能预设缩减。SiliconFlow 实际请求使用 `max_tokens`，避免 LangChain 自动转换成供应商未按预期处理的 `max_completion_tokens`。模型和自有 HTTP 连接按构建任务复用，任务结束后关闭。

供应商明确返回输出截断时才扩大预算补跑，最多三次、上限 32768；截断内容不写入图谱。SDK 隐式重试关闭，分块统一重试超时、网络错误、429 和 5xx，JSON/Schema 确定性错误直接记录为失败，供失败重跑组件处理。新增事实原文引用核验：未匹配当前 chunk 原句的事实降为待复核推断，并保留关系和原文引用；任务进度显示核验和待复核数量。这是可追溯性检查，不等同于语义正确率或召回率评测。

上传和批量解析默认同时处理 2 个文件，界面可选 1/2/4；索引仍按原顺序执行。RapidOCR 在独立进程中运行，默认全局最多 4 个进程，部署环境可用 `KNOWLEDGE_OCR_WORKERS` 调整（1–8）。ONNX 每个实例设置 2 个计算线程、1 个跨算子线程。PDF 优先读取有效文字层；低文本量、乱码、图像占主导的扫描页继续 OCR，复杂混合版面可在界面关闭文字层优先。图像原生传入 OCR，省去每页 PNG 压缩、落盘和重新解码。取消任务时先收敛解析子任务，再释放下载文件。

真实样本中，保留 2048 思考预算的三个 chunk 耗时约 95/83/44 秒（平均约 74 秒），历史 52 个样本平均约 163 秒；两份 PDF 共四页从强制串行 OCR 的 17.09 秒降到文字层优先并行解析的 2.44 秒，含进程冷启动。样本并非同负载大规模 A/B 评测，供应商仍可能超时；不能据此保证固定提速倍数或语义质量等价。关闭思考的抽样更快，但观察到关系遗漏，因此不作为均衡默认值。

可复测真实模型与上传文件（会产生模型调用费用，不覆盖现有抽取结果）：

```bash
docker compose exec api python scripts/benchmark_knowledge_pipeline.py \
  --kb-id YOUR_KB_ID --model-samples 3 --ocr-files 2 --ocr-pages 2 \
  --output /app/runtime/api/knowledge-performance.json
```

更新 Worker 前先通过 Task Service 正常取消对应构建，等待终态，再加载新代码；重新提交“构建待处理 Chunk”，复用已保存的抽取结果和已建图谱，避免重置整个知识库。仅更新前端或 API 不会改变已运行 Worker 的模型实例和配置快照。


## 验收后本地优化与质量门禁

本轮优化将模型排队改为跨线程、跨事件循环通知；取消与并发上限变更也会唤醒等待者。
学术工具返回来源的终态校验会拒绝不存在的引用，并通过最多两次正常模型轮次纠正；
技术取证请求必须实际检索，用户明确限制渠道时优先遵循用户限制。
重排请求任一批次失败时向知识检索层传播异常，由该层保留原召回排序并返回
`rerank_status=degraded`，不再构造中性分数。检索页面与来源列表会显示降级提示。

来源整理阶段从进度上下文补齐 `source_anchor_reasoning`，传入供应商与调用计量；
对 Chat Completions 的该短阶段关闭隐藏推理，保留原来的 20 秒请求时限。
排队后生效的限时参数通过返回元数据记录，不再写回调用者参数，避免复用参数时串入阶段、
运行标识与审计字段。调用指标优先读取实际生效的推理和输出预算。

仓库质量检查：

```bash
uv run --project backend python scripts/check_backend_quality.py
uv run --project backend pytest -q backend/test/unit/config/test_quality_ratchet.py
```

该门禁是历史告警基线的严格差异检查，不代表全仓 Ruff 已零告警。2026-10-25 的本地复核
由 1079 项降至 241 项；剩余以长提示文本和兼容性写法为主，明细见
`configs/quality/backend-lint-baseline.json`。新增问题不能用其他告警数量下降抵消，
已解决问题也必须缩减基线。更新基线需要显式使用 `--refresh-baseline` 并审阅文件差异；
CI 不自动扩大豁免。前端 CI 同时执行只读 `pnpm lint:check`。

根据用户本轮顺序要求，云部署于 2026-10-25 19:50（北京时间）移除：容器与 Compose 项目均为零，
Nginx 已停止并禁用，项目端口关闭，活动目录 `/opt/deep-research` 不再存在。
完整部署目录和持久化数据、最新 PostgreSQL 导出及独立文档数据备份保存在
`/var/backups/deepquest/offline-before-local-optimization-20261025`（父目录权限 0700）。
此前的验收报告记录的是移除前状态，不能作为当前在线状态证明。
重新上线应使用本地完成验证后的完整源码与新镜像；业务数据须先确认以本地、原云端还是合并结果为准，
配置从受保护位置迁移，不能直接启动备份中的旧部署。不同架构间 PostgreSQL 使用逻辑导出和恢复。
协议与未开通外部模型继续按用户决定暂缓处理。
