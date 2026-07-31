# 企业交付与运行说明

## 本地开发

推荐统一启动：

```bash
./scripts/start-local.sh
```

前端通过 `/api/v1/runtime-health` 展示 worker 在线状态、当前任务和队列待执行数量，避免仅启动 API 时任务长期停留在“已排队”。

分别启动时使用：

```bash
python3 -m uvicorn equipment_deep_research.api.app:create_app --factory --app-dir src --host 127.0.0.1 --port 8000
PYTHONPATH=src python3 -m equipment_deep_research.interfaces.worker --project-root . --output-root outputs/runs
pnpm --dir apps/web dev --host 127.0.0.1
```

以上三个命令分别启动 API、常驻 worker 和前端开发服务器。未将项目安装到当前 Python 环境时，worker 命令必须保留 `PYTHONPATH=src`。

## 容器部署

```bash
docker compose build
docker compose up -d
```

Web 默认地址为 `http://127.0.0.1:8080`。真实模型凭据通过环境变量 `EQUIPMENT_DR_API_KEY` 注入，不写入镜像、配置、trace 或 session。

默认 Compose profile 使用 `fake` worker，便于离线验收。真实模型环境通过以下变量切换：

```bash
EQUIPMENT_DR_MODE=real \
EQUIPMENT_DR_PROVIDER=responses \
EQUIPMENT_DR_API_KEY='由密钥管理系统注入' \
docker compose up -d --build
```

API 只负责任务与产物服务，研究执行始终由独立常驻 worker 从共享队列领取。

## Real 模式模型配置

工作台新建研究时可选择“Real 模式”，配置 Responses 兼容模型 URL、模型名和 worker 的密钥环境变量名。API 仅持久化以下非敏感运行元数据：

- `mode=real`
- `provider=responses`
- HTTPS 模型 URL
- 模型名
- 密钥环境变量名

API Key 绝不经浏览器传输，也不写入数据库、session、trace、报告或 delivery manifest。必须在 worker 进程的部署环境中设置该环境变量，例如：

```bash
export CLIENT_MODEL_KEY='由目标环境密钥管理系统注入'
export EQUIPMENT_DR_MODE=real
export EQUIPMENT_DR_PROVIDER=responses
docker compose up -d --build
```

在工作台填写 `CLIENT_MODEL_KEY` 作为“Worker 密钥环境变量”后，worker 会读取该变量并调用填写的 HTTPS Responses 兼容端点。模型 URL、模型名和环境变量名被纳入运行配置指纹，恢复任务时发生变化会被拒绝，避免混用不同执行后端。

## 验收产物

每次完整运行只生成一份面向决策的 `report.md`，以及精简的支撑产物：`branch_deliverables.json`、`capability_images.json`、`round_summary.json`、`domain.jsonl`、`trace.jsonl`、`agent_sessions/` 和 `artifacts/`。

`report.md` 综合已调用专业 Agent 的结论和 S1-S6 研判，直接说明规律、机制、创新点、未来场景、军事价值、能力需求和装备形态；不复述 Agent 执行过程。每项关键结论均需体现深度性、创新性、前瞻性和军事价值性，并区分已证实事实与带前提的预测。

仅 B 分支额外生成 `demand_cards.json`、`capability_panorama.json` 和 `reasoning_traceability.json`，以满足需求卡片、能力全景图和可回溯推理链的硬要求。

其中 A 分支要求 3 种新战法、5 种战法组合、8 大能力域、30 项能力指标及关联装备形态；B 分支要求需求卡片、能力全景图和可回溯深度报告；C 分支要求 6 条案例规律、3 类高置信未来场景和 4 大新兴装备类别。D-H 按各自驱动源形成同等深度的规律/场景/能力/指标/装备形态组合。数量或证据不足时必须在 `branch_deliverables.json` 中显式标记缺口，不得凑数。

`DeliveryExporter` 生成 `delivery-manifest.json`，记录文件大小和 SHA-256，用于交付完整性复核。

## 当前部署边界

开发模式使用 SQLite 持久化任务队列，API 与 worker 可跨进程共享任务和运行状态；PostgreSQL/Redis 高可用部署仍需结合目标环境基础设施参数完成环境化配置。
