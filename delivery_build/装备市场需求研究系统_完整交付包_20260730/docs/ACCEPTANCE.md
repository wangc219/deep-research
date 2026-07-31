# 首版企业交付验收说明

## 功能验收

- 三条研究路线均完成 fake E2E。
- 默认四路、任意子集和自定义替换 agent 均可运行；缺失 coverage 明确呈现。
- agent 原始上下文隔离，工具权限由执行层强制，session 独立追加。
- 六步推理、L1/L2/L3 门控、定向再调与恢复节点可在 trace 审计。
- 证据经过网络安全、材料化和质量门控；失败/低质量材料不进入正式支撑链。
- 报告综合中间专业研究结果与制胜分析 S1-S6，按业务主题深度撰写规律、场景、因果机制、能力需求、指标边界和装备形态；每项关键结论均体现深度性、创新性、前瞻性和军事价值性，并区分事实与预测；正文不得退化为 Agent 过程描述或字段罗列。
- A 分支核对 3 种新战法、5 种战法组合、8 大能力域和 30 项能力指标；B 分支核对以具体待发展武器装备为主对象的需求卡片、能力全景图和可回溯深度报告，需求卡片优先覆盖与 query 匹配的无人、导弹、弹药及其他歼灭、打击、拒止、威慑装备；C 分支核对 6 条案例规律、3 类高置信未来场景和 4 大新兴装备类别。未满足项必须显式披露，禁止凑数。
- 报告按新制胜机理、传统能力缺口、局部战争案例三条路线输出差异化产品功能画像，并直接回答“需要发展什么功能的产品”。
- API 创建任务后不直接执行研究；独立 worker 可跨 service/数据库连接领取、执行并持久化结果。
- 应用重启后可读取 summary、证据、制胜阶段、能力画像、报告、trace 和 manifest。
- 工作台生产构建通过，领域页面读取真实运行产物而非静态占位。
- 工作台支持任务增删改查：创建、草稿编辑、详情/筛选查询、软归档和完整执行历史；启动后的研究配置不可被静默改写。
- Real 草稿可配置模型、HTTPS URL 和密钥环境变量引用，明文 API Key 不进入浏览器请求、数据库和运行产物。
- 运行中可通过持久化 SSE 查看 Agent 委派、搜索、抓取、工具结果、证据评分、推理和再调，断线后可重放且不暴露原始模型消息。
- Codex CLI 强制启用 live web search；Codex/Responses 搜索来源只有在本地材料化和证据门控通过后才能关联到正式 packet 和报告。
- Codex CLI 专用 Agent 覆盖编排器、A-H、收敛、S1-S6、批判、审计和报告，并记录内循环、中循环、L1-L3 外循环与 L4 元循环。
- L4 在收敛后由 Codex 编排器执行有界复核，可调整最多两个 A-H 次分支和 S1-S6 的执行强度；非法调整由 Harness 拒绝并保留原蓝图。
- 工作台任务列表分页，交互接口支持 `compact=true`，前端仅渲染关键阶段、Agent 摘要和关键事件。

## 自动验收命令

```bash
python3 -m pytest -q --ignore=tests/test_responses_adapter.py
pnpm --dir apps/web build
docker compose config
```

重点 E2E：

```bash
python3 -m pytest \
  tests/equipment_deep_research/integration/test_enterprise_runtime.py \
  tests/equipment_deep_research/e2e \
  -q
```

CLI smoke：

```bash
python3 scripts/run_deep_research.py \
  --mode fake \
  --topic "低空无人机探测预警能力缺口" \
  --research-route traditional_gap \
  --run-id delivery-acceptance
```

## 必查产物

运行目录必须包含 `report.md`、`branch_deliverables.json`、`capability_images.json`、`round_summary.json`、`domain.jsonl`、`trace.jsonl`、`agent_sessions/`、`artifacts/`、`run.db`、`checkpoints/`。B 分支还必须包含 `demand_cards.json`、`capability_panorama.json` 和 `reasoning_traceability.json`。worker 企业闭环还必须生成可通过 SHA-256 复核的 `delivery-manifest.json`。

## 环境验收项

以下项目需在目标部署环境复验：真实模型凭据与公网搜索、PostgreSQL/Redis profile、OIDC、TLS、反向代理、出口代理、备份恢复、容量与并发压测、指定浏览器终端视觉基线。网络或凭据不可用时只允许记录降级结果，不得伪造真实联网成功。

`tests/test_responses_adapter.py` 是仓库内 legacy `knowledgegraph.demand_discovery` 链路测试，不属于本项目验收范围，且本次实施不修改该文件。

本地前后端真实生命周期验收记录见 [企业前后端统一交付测试报告](testing/enterprise-frontend-backend-delivery-report.md)。

智能体职责、信息流、工具权限与交互可视化的架构对照见 [智能体架构落实与交互审计说明](AGENT_ARCHITECTURE_IMPLEMENTATION.md)。
