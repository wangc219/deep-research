# 云端并发容量

所有生产命令使用 `scripts/cloud.sh`，统一叠加生产和云端 Compose 配置。容量参数可在 `.env.prod` 中覆盖，凭据继续只保存在 `.env.prod`。

| 参数 | 4 核 / 8 GB 基础档位 | 当前 4 核 / 16 GB | 8 核 / 16 GB 初始档位 |
| --- | ---: | ---: | ---: |
| `CLOUD_DURABLE_MAX_RUNNING` | 12 | 20 | 24 |
| `CLOUD_ARQ_MAX_JOBS` | 16 | 24 | 32 |
| `CLOUD_API_WORKERS` | 2 | 2 | 3 |
| PostgreSQL 最大连接 | 100 | 160 | 160 |

`DURABLE_TASK_MAX_RUNNING` 是通用持久任务共享的数据库执行槽位，多个通用任务类型共同使用这一上限。当前 4 核 / 16 GB 档位将普通聊天、新版深研、子智能体及通用后台任务拆成独立的 Docker Worker；`CLOUD_ARQ_MAX_JOBS` 只限制通用后台池。研究与 Query 继续使用其领域容量；视频语音识别保留单任务模型容量。

| 执行池 | 全局接纳上限 | 每位用户同时执行上限 |
| --- | ---: | ---: |
| 普通聊天 | 16 | 3 |
| 新版深研对话 | 4 | 2 |
| 子智能体 | 8 | 4 |
| 通用后台任务 | ARQ 24；通用数据库槽 20 | 按既有业务规则 |

用户配额通过 PostgreSQL 事务级 advisory lock 与有效 lease 计数实现，跨线程、跨 Worker 实例仍执行同一上限。超额请求保留 pending，不占执行槽；当前用户任务结束后立即补发，后台每 30 秒恢复未投递意图。每个用户拥有独立调度配额和既有私有数据、工作目录；固定数量的 Worker 执行这些任务，不为每位登录用户常驻一个容器。子智能体使用独立执行池，避免父任务占满槽位后等待无法启动的子任务。

分池通过 `CLOUD_SPLIT_AGENT_QUEUES=true`、`CLOUD_BACKGROUND_WORKER_KIND=background` 和 `COMPOSE_PROFILES=agent-pools` 一同启用；普通聊天、深研、子任务分别使用独立 Redis 队列和独立健康 lease，任一执行池失联都会影响 readiness。未启用分池的其他环境继续使用原统一队列。切换前必须排空 AgentRun 和 Task，保留原镜像、容量配置与源码备份。

当前主机没有额外设置容器 CPU 或内存硬上限，各服务可使用可用资源。API 与普通聊天的 CPU 相对权重为 1024，深研、子任务和后台池为 512；权重在 CPU 竞争时起作用，不是独占核心或绝对延迟保证。内存用于常驻 Worker、解析、模型进程、数据库和文件缓存；以吞吐、延迟及突发内存余量确定并发，不以占满 16 GB 为目标。建议保留至少 4 GB 可用内存用于大型文件、索引和识别峰值。

云端 API 与主 Worker 启动前最多等待 120 秒，确认 Milvus 健康后再启动业务进程；超时退出，业务自身的数据库、配置和权限启动校验仍保留。该等待也适用于 Docker 守护进程在整机重启后恢复容器的场景。

## 升级容量配置

2026-10-27 实测云机已扩充到约 15.1 GiB 可用物理内存，逻辑 CPU 仍为 4 个。当前部署将 `configs/cloud/4c16g.env.example` 的容量键合并到 `.env.prod`，普通运维命令即可保留生效档位。配置提升 I/O 型通用任务上限，语音识别及本地 OCR 的重计算容量保持受控。

硬件升级后，先核实 `getconf _NPROCESSORS_ONLN` 和 `free -m`，再选择不包含凭据的容量文件。仅扩大内存时使用 `configs/cloud/4c16g.env.example`；CPU 同时升级到 8 核后才使用 `configs/cloud/8c16g.env.example`。先仅检查解析结果，不启动容器：

```bash
CLOUD_CAPACITY_ENV_FILE=configs/cloud/4c16g.env.example bash scripts/cloud.sh config --quiet
```

维护窗口先备份数据库和 `.env.prod`，等待运行任务结束，再应用升级档位：

```bash
CLOUD_CAPACITY_ENV_FILE=configs/cloud/4c16g.env.example bash scripts/cloud.sh up -d --wait postgres
CLOUD_CAPACITY_ENV_FILE=configs/cloud/4c16g.env.example bash scripts/cloud.sh up -d --no-deps --wait worker chat-worker deep-worker subagent-worker equipment-worker equipment-query-worker api
```

应用第二份环境文件后，后续运维命令继续携带相同 `CLOUD_CAPACITY_ENV_FILE`，或将已验收的容量键合并进 `.env.prod`。省略叠加文件会恢复默认档位，因此不要混用不同档位执行重建命令。

按当前 2 个 API 进程、4 个执行池及 2 个领域 Worker 预算，异步 SQL/LangGraph 池上限合计约 112 个连接；另为同步模型计量及运维预留余量，PostgreSQL 上限设为 160。新增 Worker 副本或独立子进程时，必须重新核对实际进程树的连接预算。LangGraph 池必须至少为 4。连接池按需创建，最大值不代表常态连接数。

运行清单准备完成配置与知识库开关读取后，先结束只读事务，再进入独立资源解析；资源解析进入独立知识库查询前同样归还外层读取连接。输出、Run ownership、manifest 和终态仍由原事务 Owner 提交。这样避免 16 个对话各持有一个连接、再等待同一连接池第二个连接形成超时。

默认智能体及配置页的知识库资源选项复用调用方 Session，知识库仓储支持显式传入 Session；用户与知识库权限过滤保持一致。该路径以真实 PostgreSQL 的单连接池测试验证，避免大量用户同时打开智能体时再次嵌套申请连接。

## 动态 CPU 与内存预算

4 核 / 16 GB 档位通过 `CLOUD_RESOURCE_GOVERNOR_ENABLED=true` 启用。通用后台 Worker 每 2 秒读取主机 CPU、可用内存、正在执行的交互和研究任务。ASR 自身的 CPU 时间从竞争负载中扣除，防止有效识别计算被误判成其他任务拥塞。预算原子写入 `outputs/runtime/resource-budget.json`，不含用户正文或凭据。

ASR 仍一次处理一个任务，模型初始化显式传入 CPU 线程数，并在音频块边界按预算调整 Torch 池。4 核完全空闲时可用 4 个线程，有交互或其他计算竞争时收敛到 1–3 个线程；升档需连续三个安全样本，降档在后续块边界生效。此策略调整资源，不改变模型、音频、识别精度设置或已经开始的任务终态。

研究的系统设置仍是硬上限（当前 4），动态预算只降低新接纳量：交互运行且其他负载 CPU 超过 80% 时最多新接纳到 2 个；可用内存低于 4 GiB 时研究上限降到 1、通用任务降到 4，并暂缓新的 ASR。低于 2.5 GiB 时研究和通用任务暂缓新接纳。已有任务继续执行，预算恢复后补发 pending 意图。快照超过 12 秒未更新时采用保守档，同时读取当前内存保护边界。

Worker 健康检查直接验证 Redis 的独立健康租约，不导入整个 Agent 后端。Neo4j 以认证后的 HTTP 事务执行 `RETURN 1`，避免每 20 秒启动一个 Java 命令行进程。所有项目容器共享主机可用 CPU 和内存，保留相对 CPU 权重保障交互；该策略不等于单独为每个容器保留四个核心。

2026-10-27 的混合验收覆盖一项完整研究、121 秒真实模型音频识别及 16 个普通账户的 25 个短对话。它验证代表性混合负载，不代表 16 项完整长研究可以同时无等待交付。验收后删除测试身份、研究、画像、视频任务、知识库、向量、对象及临时文件，仅保留不含正文或音频的汇总。

## 验收与回退

调整前检查活动任务、CPU、可用内存、Swap 换入换出和 PostgreSQL 当前连接。任务仍在运行时先排空再重建 Worker。调整后执行真实队列的解析、入库、检索及 API 并发测试，记录同时 running 的任务数、终态、耗时、网页延迟和资源峰值；测试资料及任务记录验收后删除。

若持续内存压力、OOM、数据库连接接近上限，或网页延迟显著恶化，应回退已备份的容量配置，在任务排空后重建相应容器。8 核 / 16 GB 的 24 槽档位是升级后的起始配置，仍需结合实际文档大小与外部模型限速验收。
