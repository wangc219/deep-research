# 企业前后端统一交付测试报告

## 2026-07-17 Codex CLI 专用 Agent 补充验收

- 使用本地 API `127.0.0.1:18000` 与 Web `127.0.0.1:15173` 完成浏览器实页验收。
- 任务首页从一次渲染全部任务改为每页 12 项；交互页只保留 5 个业务阶段、最多 12 个 Agent 摘要和最多 60 个关键事件；Codex 配置页一次只编辑 1 个 Agent。
- 实测完成任务显示 5 个业务阶段、9 个活跃 Agent 摘要、38 个关键事件，并正确标识 6 个 S 步骤与审计交付完成。
- Codex CLI 命令强制启用 live web search；A-H 分支生成 S1-S6 的重点/标准/弱化/跳步计划；L4 收敛后可有界调整次分支和 S 步骤强度。
- 全量回归为 `446 passed`；Vite 生产构建、Compose 配置和本轮变更 Ruff 检查通过。

## 1. 验收范围

本次验收覆盖：React 工作台、Vite 代理、FastAPI、SQLAlchemy/SQLite 持久化、跨进程队列、常驻 worker、动态 Agent Registry、多智能体 fake 研究闭环、制胜机理 L1/L2/L3、证据/能力画像/报告接口和 delivery manifest。

验收日期：2026-07-12。

## 2. 已完成的实际浏览器生命周期

验收环境：

- Web：`http://127.0.0.1:5173/`
- API：`http://127.0.0.1:8000/api/v1`
- 数据库：隔离 SQLite 验收库
- Worker：独立常驻进程，`fake` 模式

浏览器从工作台执行以下步骤：

1. 健康状态显示“服务正常”。
2. 新建主题“低空无人机探测预警能力缺口企业验收”。
3. 选择“传统能力缺口”路线与四个默认 baseline agents。
4. 前端调用 API 创建并启动任务。
5. worker 从共享 SQL 队列领取任务，状态自动从“已排队”更新为“已完成”。
6. 证据中心读取 4 条 `EvidenceCard`。
7. 制胜机理页读取 L1、L2、L3 三层结构化输出。
8. 能力画像页读取 2 条九字段文字能力画像。
9. 报告评审页读取完整研究报告。

验收 run-id：`run-9ad303e4-a7e9-4e04-9dfb-a87b0b1b8e8d`。

上述浏览器生命周期验收针对前一版工作台完成。随后完成了企业工作台视觉重设计、Real/Fake 任务级配置和智能体交互详情增强；新版代码已通过生产构建和 API/worker 集成回归。本轮尝试重新启动隔离 API、worker 与 Vite 服务时，三个进程均可启动，但宿主浏览器安全策略拒绝访问 `http://127.0.0.1:5173/`，本机端口探测的环境审批又被外部审批服务 503 拒绝，因此未生成新版截图。未使用其他浏览器或自动化方式绕过该限制。

## 3. 联调发现与修复

- 修复 API 进程缓存覆盖仓储新状态的问题。worker 跨进程完成后，API 现在优先读取持久化仓储，因此运行详情和产物接口立即可见。
- 修复领域页快速切换时旧异步请求覆盖新页面状态的问题。请求 effect 现在丢弃过期响应，报告组件同时具备非字符串防御。
- API catalog 改为读取 `agents.yaml` 与 `presets.yaml`，前端 agent、上下文可见区和 coverage 不再硬编码。
- 前端增加真实健康探测、2 秒任务轮询、状态同步、搜索、筛选、最大轮次和启动失败反馈。
- Compose 将 `EQUIPMENT_DR_MODE` 与 `EQUIPMENT_DR_PROVIDER` 正确注入 worker，并保持 worker 常驻重启策略。

## 4. 产物完整性

worker 自动生成 `delivery-manifest.json`：

- `file_count=30`
- 4 个独立 `agent_sessions/*.jsonl`
- 8 个 artifact 内容/元数据文件
- `capability_images.json`
- `round_summary.json`
- `domain.jsonl`
- `trace.jsonl`
- `report.md`
- `run.db`
- checkpoint history 与 `latest.json`

manifest 为每个文件记录大小和 SHA-256，可用于交付后完整性复核。

## 5. 响应式检查

浏览器在 `390x844` 视口复验：

- 无页面横向溢出；
- 左侧导航按移动端规则隐藏；
- 主内容宽度 375px；
- 报告容器宽度 335px；
- 报告文本保持换行且不遮挡相邻内容。

## 6. 自动验证

```text
python3 -m pytest -q --ignore=tests/test_responses_adapter.py
359 passed, 1 upstream deprecation warning

ruff check src/equipment_deep_research tests/equipment_deep_research
PASS

pnpm --dir apps/web build
PASS

docker compose config
PASS

git diff --check
PASS
```

唯一告警来自 FastAPI TestClient 对 `httpx` 兼容层的上游弃用提示，不影响当前运行结果。

## 7. 结论

开发/项目验收 profile 已实现前后端统一闭环：前端可创建研究，独立 worker 可执行多智能体任务，完成状态可跨进程一致读取，证据、制胜机理、能力画像和报告可在工作台展示，交付产物可由 manifest 审计。新版工作台的生产构建和接口契约已验证；由于本轮宿主浏览器策略限制，视觉重设计后的截图验收仍需在允许访问本地服务的目标或开发环境补签。真实模型、公网检索、OIDC、PostgreSQL/Redis 高可用、TLS 与容量压测也需在目标部署环境使用正式基础设施参数复验。

## 8. Real 模式配置验证

新增的任务级 real 配置接受 `mode=real`、`provider=responses`、HTTPS 模型 URL、模型名和 worker API Key 环境变量名。API 自动拒绝 HTTP URL 和不合法环境变量名；测试验证 API 仅保存上述元数据，不接受也不保存 API Key 字段。worker 执行时将配置传递给 Responses Provider，密钥仅从该环境变量读取。

## 9. 实时交互与联网证据增强

runner 的 trace 和经过白名单裁剪的 session 工具事件会实时写入共享事件表。API 使用 SSE 按 sequence 推送并支持 `Last-Event-ID` 重放；工作台在任务运行中实时刷新交互时间线。自动测试验证跨进程事件至少包含委派、工具调用、工具结果和六步推理，且不含 `raw_message`。

Real Responses 请求现已使用内置 `web_search` 并导出完整 sources。工作台可看到 `search_sources -> fetch_page -> evidence_assessed -> create_evidence_card`。搜索来源仍需通过本地网络安全、正文材料化、段落定位和质量门控，未通过的来源不会关联到正式 packet。

## 10. 任务 CRUD、历史与路线差异化输出

任务 API 和工作台现支持创建、草稿更新、详情/筛选查询和软归档。草稿更新重新校验研究路线、Agent 子集、最大轮次与 Real 模型配置；任务启动后不可修改，运行中不可归档。归档只改变任务状态，不删除报告、证据、trace 和 manifest。任务详情抽屉读取完整持久化事件历史，并可跳转实时交互、证据、制胜机理和能力画像。

能力画像与报告不再使用同一套通用措辞。新制胜机理路线突出新机制、新打法和新体系组合；传统缺口路线突出当前装备对比、能力空白补位和现有装备升级；局部战争案例路线突出新能力、新模式、经验不足和未来布局。报告新增“制胜机理思考维度”和“最终需要发展什么功能的产品”。
# 2026-07-13 完整闭环补充验收

本次使用独立本地进程验证，不以 API 返回“已排队”作为通过条件：

1. API 使用独立 SQLite 应用数据库创建并启动任务。
2. 任务进入持久化队列，状态为 `queued`。
3. 独立 worker 进程从相同数据库领取任务。
4. 四路基线 Agent 完成独立 session、工具调用、证据与 savepoint。
5. 编排器生成制胜机理输入包和四类资源投影。
6. 六步推理与 L1/L2/L3 门控完成。
7. 审计 Agent 完成五判据检查，报告 Agent 生成交付报告。
8. API 重读任务状态为 `completed`，产物和交互接口均可读取。

实测结果：

- 任务状态：`completed`
- 审计状态：`approved`
- 基线 Agent：4
- 制胜机理推理节点：6
- L1/L2/L3 阶段：3
- 九字段文字能力画像：2
- 实时/历史交互事件：71
- 工具调用/结果：15/15
- Agent savepoint：4
- delivery manifest 文件：30
- 自动化测试：360 passed
- Ruff、前端生产构建、Compose 配置和 diff 检查：全部通过

为避免开发环境只启动 API 导致任务长期排队，系统新增 worker 心跳、`/api/v1/runtime-health`、前端离线告警以及 `scripts/start-local.sh` 一键启动脚本。前端在 worker 不在线时阻止创建并启动研究任务。

## Agent Harness 差异化验收

使用乱序选择 `作战运用、武器装备、国际形势、作战场景` 执行离线闭环，编排器实际执行顺序自动修正为：

`国际形势 -> 作战场景 -> 武器装备 -> 作战运用`

session 验证结果：国际形势无上游原始信息；作战场景仅接收国际形势交接；武器装备接收国际形势和作战场景交接；作战运用接收前三路交接。四路分别加载 3、3、3、4 项专业技能，且每路 `task_received` 事件均记录技能、研究策略、上下文区段、工具权限和上游 Agent ID。闭环状态为 `completed`，审计为 `approved`。
