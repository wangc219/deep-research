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

```bash
bash scripts/platform.sh status
curl http://127.0.0.1:5173/api/system/ready
docker stats --no-stream
```

研究领域代码更新时，应同步更新 API、平台 Worker、原研究 Worker 和 Query Worker。原研究队列使用版本签名隔离；只重启 API 可能让任务无法被旧 Worker 领取。

模型计量补写队列位于 `/app/outputs/model-call-outbox.db`，由 API 和三个 Worker 通过共享 `outputs` 持久卷访问。不要在服务运行时手工删除该文件；数据总览的“待同步调用”持续大于 0 时，应先检查 PostgreSQL 健康与磁盘权限。

已通过静态网关访问的真实 HTTP 企业隔离与 fake 研究队列验收，以及统一模型账本/趋势验收。API、PostgreSQL、Redis、Worker readiness 正常。完整真实研究的质量和供应商可用性仍以 [统一运行时验收记录](MODEL_RUNTIME_INTEGRATION.md) 为准。

2026-09-24 追加空闲样本：约 30 秒的四次容器采样，总 CPU 分别为 5.54%、11.22%、13.75%、13.65%（Docker 按单核 100% 口径）；API 为 0.25%–2.66%，内存约 476 MiB。此前一次启动后瞬时 API 为 29.21%，随后回落；这些样本未显示持续满载，但不代表并行研究或生产负载测试。整组容器内存约 1.8 GiB，前端约 5 MiB。
