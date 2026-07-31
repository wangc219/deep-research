# 装备能力图像 Deep Research 多智能体系统

面向国防武器装备市场需求挖掘、制胜机理研判和文字能力画像生成的可配置多智能体系统。当前版本已形成 CLI、API、持久化 worker、React 工作台和可审计交付产物的首版闭环。

## 已实现能力

- 三条研究路线：新制胜机理、传统能力缺口、局部战争案例。
- 动态 Agent Registry：默认四路 agent 可全选、选子集或通过配置替换，不在编排器中写死。
- 差异化执行：每个 agent 使用独立上下文投影、工具权限、预算、session 和 checkpoint。
- Subagent map-reduce：任务具备可拆分、上下文需隔离、结果可汇总条件时执行有界并发 wave。
- 失败可恢复交接：同一 wave 的成功结果先行 checkpoint；失败 Agent 回到 pending，并生成脱敏、带恢复节点和候选接收方的结构化 handoff。
- 制胜机理：四类资源投影、六步推理、L1/L2/L3 门控、定向再调与断点恢复。
- 证据治理：公开来源聚合、SSRF 防护、正文简化、位置索引、材料化、质量评分与正式证据门控；不设置来源域名白名单。
- 企业运行时：FastAPI、SQLite/SQLAlchemy 持久化队列、独立 worker、SSE replay、基础 RBAC。
- Web 工作台：研究创建、草稿编辑、软归档、状态筛选、执行历史、动态 coverage、证据、制胜机理、能力画像、报告与配置视图。
- 实时交互：持久化 SSE 展示 Agent 委派、搜索、抓取、证据评分、保存点、推理、再调、审计和报告事件，支持断线重放。
- Real 搜索：Codex CLI 强制启用 live web search；Codex/Responses 返回的来源都必须经过本地材料化、段落定位和证据质量门控。
- Codex 接入模式：编排器、A-H 专业发现、四个基线 Agent、收敛融合、制胜机理 S1-S6 子 Agent、内/中/外/L4 循环、审计和报告均可通过独立 `codex exec` 会话运行。
- 路线差异化输出：新制胜机理、传统能力缺口和局部战争案例分别生成对应的产品功能画像、升级方向和制胜机理问题链。
- 交付完整性：运行完成自动生成 `delivery-manifest.json` 和 SHA-256 校验信息。

默认模型为 `gpt-5.5`。离线验收使用确定性 fake provider；真实执行可使用 Codex CLI 或 Responses-compatible provider，并要求 Worker 环境具备相应 API 凭据与网络出口。

Real 模式提供两种 Agent 接入：`codex` 表示 Codex CLI 作为架构 Agent，`responses` 表示自定义 Agent 适配器。默认使用 Codex CLI；隔离方式、S1-S6 子 Agent 和多层循环说明见 `docs/CODEX_ADAPTER_MODE.md`。

当前 Web 工作台统一显示为“Agent”，不展示底层 Codex CLI 名称，也暂不提供自定义 Agent 切换入口；`responses` 仅作为后端兼容路径保留。

## 快速运行

### 环境准备

- Python 3.11+（容器运行时使用 Python 3.12）
- Node.js 22+ 与 npm 10+
- 如需真实 Agent 执行，还需要 Codex CLI；仅运行 `fake` 模式和测试时不需要 API 密钥

首次 clone 后安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
npm ci --prefix apps/web
```

macOS 自带的 Python 3.9 不满足项目版本要求。可将 Python 3.11+ 的解释器显式传给启动脚本：

```bash
EQUIPMENT_DR_PYTHON_BIN=/path/to/python3.12 ./scripts/start-local.sh
```

不希望安装本地运行时依赖时，可直接使用 Docker：

```bash
docker compose up --build
```

Web 默认地址为 `http://127.0.0.1:8080`。

### CLI 烟测

```bash
python3 scripts/run_deep_research.py \
  --mode fake \
  --topic "低空无人机探测预警能力缺口" \
  --research-route traditional_gap \
  --run-id acceptance-fake
```

选择部分 agent：

```bash
python3 scripts/run_deep_research.py \
  --mode fake \
  --topic "低空无人机探测预警能力缺口" \
  --agents combat_scenario,weapon_equipment \
  --run-id acceptance-subset
```

使用 Codex 执行完整业务流程：

```bash
python3 scripts/run_deep_research.py \
  --mode real \
  --provider codex \
  --topic "低空无人体系装备能力缺口" \
  --research-route traditional_gap \
  --run-id codex-gap-demo
```

## 企业工作台

推荐一键启动完整本地闭环：

```bash
./scripts/start-local.sh
```

`start-local.sh` 会优先读取 gitignored 的 `.env.codex`，由服务端统一管理 Codex CLI、模型、URL 和密钥环境变量；只有 `.env.codex` 不存在时才回退到 `.env`：

```dotenv
EQUIPMENT_DR_CODEX_BASE_URL=https://api.openai.com/v1
EQUIPMENT_DR_CODEX_API_KEY_ENV=EQUIPMENT_DR_CODEX_API_KEY
EQUIPMENT_DR_CODEX_API_KEY=你的服务端密钥
```

然后直接运行：

```bash
./scripts/start-local.sh
```

Codex CLI 会在项目隔离的 `CODEX_HOME` 中使用 API Key 认证，不需要设备登录。前端不展示或提交执行配置；API 在创建和编辑草稿时直接投影 `.env.codex` 中的服务端默认值，任务只保存必要的执行快照，不保存密钥值。

脚本同时启动 API、持久化队列 worker 和 Web。工作台会检查 worker 心跳；worker 未在线时会阻止任务进入无人消费的队列。

也可以分别启动：

```bash
python3 -m uvicorn equipment_deep_research.api.app:create_app --factory --app-dir src --host 127.0.0.1 --port 8000
PYTHONPATH=src python3 -m equipment_deep_research.interfaces.worker --project-root . --output-root outputs/runs
pnpm --dir apps/web dev --host 127.0.0.1
```

API 创建并启动任务后，由独立 worker 从共享数据库领取任务。worker 完成研究、报告与 manifest 后，Web 可读取证据、L1/L2/L3、九字段能力画像和报告。

工作台默认使用紧凑交互投影：任务列表每页 12 项；交互页只显示五段业务主链、最多 12 个 Agent 摘要和最多 60 个关键事件；完整事件、契约和运行产物仍保留在后端审计数据中。

## 运行产物

- `report.md`
- `capability_images.json`
- `round_summary.json`
- `domain.jsonl`
- `trace.jsonl`
- `agent_sessions/`
- `artifacts/`
- `run.db`、`checkpoints/`
- `delivery-manifest.json`
- `architecture-acceptance.json`（含 Registry、会话隔离、权限预算、有界并发、map-reduce、checkpoint 与 handoff 的运行时符合性检查）

## 验证

```bash
python3 -m pytest -q
npm --prefix apps/web run build
docker compose config
```

完整测试包含 API 创建、持久化队列、独立 worker 消费、制胜机理、能力画像、报告、交互审计和重启后产物读取。详细方案、验收边界和部署说明见 `docs/TECHNICAL_SCHEME.md`、`docs/ACCEPTANCE.md`、`docs/DELIVERY.md`。

企业交付成熟度、投产前必做项和长期演进建议见 `docs/ENTERPRISE_DELIVERY_AUDIT.md`。
