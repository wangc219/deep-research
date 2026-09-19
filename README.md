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

Docker Web 默认地址为 `http://内网主机IP:8080`；端口映射会监听所有主机网卡。

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

`start-local.sh` 读取统一的 gitignored `.env`（由 `.env.example` 复制而来），
管理 Codex CLI、各网关 URL/模型/密钥。可选的 `.env.local` 只保存 UI 选择的
model profile，不含密钥。旧的 `.env.codex*` 拆分文件已弃用，仅作兼容叠加载。

```dotenv
# GPT / 中转站（动态蜂群 Codex CLI）
EQUIPMENT_DR_MODEL=gpt-5.5
EQUIPMENT_DR_CODEX_BASE_URL=https://api.openai.com/v1
EQUIPMENT_DR_CODEX_API_KEY_ENV=EQUIPMENT_DR_CODEX_API_KEY
EQUIPMENT_DR_CODEX_API_KEY=你的服务端密钥

# DeepSeek（官方或中转）
EQUIPMENT_DR_DEEPSEEK_MODEL=deepseek-chat
EQUIPMENT_DR_DEEPSEEK_BASE_URL=https://api.deepseek.com/v1/chat/completions
DEEPSEEK_API_KEY=你的 DeepSeek 密钥

# Queen / Qwen（可选）
EQUIPMENT_DR_QUEEN_MODEL=qwen3.8-flash
EQUIPMENT_DR_QUEEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EQUIPMENT_DR_QUEEN_API_KEY_ENV=QUEEN_API_KEY
QUEEN_API_KEY=
```

然后直接运行：

```bash
cp .env.example .env   # 首次
./scripts/start-local.sh
```

Web 默认监听 `0.0.0.0:5173`。启动成功后脚本会打印
`http://内网主机IP:5173`，同一局域网内的设备或内网穿透工具可直接使用该地址。
如需修改监听地址或端口，可在 `.env` 或启动命令中设置：

```dotenv
EQUIPMENT_DR_WEB_HOST=0.0.0.0
EQUIPMENT_DR_WEB_PORT=5173
EQUIPMENT_DR_WEB_ALLOWED_HOSTS=12738agqw5541.vicp.fun
```

多个内网穿透域名可使用英文逗号分隔。修改后需重启前端服务。

生产部署应启用可信身份边界：

```dotenv
EQUIPMENT_DR_AUTH_MODE=trusted_headers
EQUIPMENT_DR_REQUIRE_TRUSTED_IDENTITY=1
```

此模式要求反向代理先剥离客户端伪造的 `X-Authenticated-*`、`X-Role` 和
`X-Tenant-ID`，再注入经 OIDC/JWT 校验的 `X-Authenticated-Tenant-ID`、
`X-Authenticated-Roles` 等声明。前端只发送最低权限的分析员请求；审核和
跨范围操作由可信身份中的 reviewer/auditor/admin 角色授权，不能通过浏览器
修改 `X-Role` 冒充审核员。未开启严格模式时，`X-*` 仍可用于本地集成测试，
不应作为公网身份边界。

Codex CLI 会在项目隔离的 `CODEX_HOME` 中使用 API Key 认证，不需要设备登录。前端不展示或提交执行配置；API 在创建和编辑草稿时直接投影 `.env` 中的服务端默认值，任务只保存必要的执行快照，不保存密钥值。

模型解析以服务端环境 + 任务所选 model profile 为准：
`EQUIPMENT_DR_MODEL` / `EQUIPMENT_DR_DEEPSEEK_MODEL` / `EQUIPMENT_DR_QUEEN_MODEL`
是各网关的部署模型 ID；UI 选择 `codex-gpt` / `codex-deepseek` / `codex-queen`。
决定本任务走哪一套。动态蜂群默认继承该任务模型；仅在需要「同任务多模型」时
填写 `EQUIPMENT_DR_SWARM_AGENT_MODELS_JSON`。

Codex CLI 遇到 `Selected model is at capacity` 时，会在同一模型上按指数退避重试（默认最多 4 次）。若 GPT 重试仍耗尽，系统优先使用 Queen 兜底；未配置 `QUEEN_API_KEY` 时自动改用 DeepSeek。普通认证、参数或业务错误不会切换模型。

Codex CLI 的 Queen / Qwen 接入参数（模型 ID、URL、API Key）统一从 `.env` 读取；更换模型只需改 `.env`，不需要改编排代码。请按当前 DashScope 文档选择支持 Responses 的兼容端点。

动态蜂群可通过 `EQUIPMENT_DR_SWARM_AGENT_MODELS_JSON` 按蜂群角色配置不同
Codex CLI 模型。例如：

```dotenv
EQUIPMENT_DR_SWARM_AGENT_MODELS_JSON={"weak_signal_scout":"gpt-5.5","disruptive_mechanism_generator":"gpt-5.5","independent_portfolio_reviewer":"gpt-5.5"}
```

键可以使用蜂群 archetype、运行时 Agent ID（如 `winning_swarm_weak_signal_scout`）
或 `*` 通配符；配置在每个动态专家的隔离 Codex 会话创建时生效。留空 `{}` 时继承本任务 profile 的模型。

脚本同时启动 API、持久化研究队列 Worker、Query 生成 Worker 和 Web。工作台会检查研究 Worker 心跳；研究 Worker 未在线时会阻止任务进入无人消费的队列。研究任务首页可直接输入或选择推荐 Query，并通过“需求研究问题库”卡片进入独立的联网生成、草稿审核和来源追溯界面；已发布 Query 可一键带回研究任务。

也可以分别启动：

```bash
python3 -m uvicorn equipment_deep_research.api.app:create_app --factory --app-dir src --host 127.0.0.1 --port 8000
PYTHONPATH=src python3 -m equipment_deep_research.interfaces.worker --project-root . --output-root outputs/runs
pnpm --dir apps/web dev
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

S1–S6 Prompt/Memory 文本型自进化的调研、评测闭环、多租户治理和分阶段路线见
`docs/SELF_EVOLUTION_RESEARCH_AND_ROADMAP.md`；当前 Prompt API 的兼容与迁移规范见
`docs/PROMPT_EVOLUTION.md`。

独立的需求挖掘 Query 自动生成、草稿审核、来源追溯和 Query 库使用方式见 `docs/QUERY_LIBRARY.md`。
# 统一模型档案

生产环境用 `configs/equipment_deep_research/model-profiles.yaml` 描述档案路由，
模型 ID / URL / 密钥只写在统一 `.env`。档案：`codex-gpt`、`codex-deepseek`、`codex-queen`。

```bash
.venv/bin/python scripts/model-profile.py list
.venv/bin/python scripts/model-profile.py show codex-gpt
.venv/bin/python scripts/model-profile.py doctor codex-gpt
.venv/bin/python scripts/model-profile.py doctor codex-deepseek
.venv/bin/python scripts/model-profile.py doctor codex-queen
```

`use` 只会在 `.env.local` 写入档案 ID，不会写入 API key。研究任务更推荐在 UI
按任务选择模型；`doctor` 仅显示脱敏主机、凭据是否配置和模型可用性。

蜂群角色也可以独立路由到不同档案：

```bash
.venv/bin/python scripts/model-profile.py use-swarm '{"S3":"codex-gpt","S4":"codex-deepseek","S5":"codex-queen"}'
```

运行时会在 S Agent 隔离会话创建时解析角色档案；新增同协议模型只需增加 profile
并在 `.env` 增加对应 MODEL/URL/KEY，只有接入全新协议时才需要增加 provider adapter。
