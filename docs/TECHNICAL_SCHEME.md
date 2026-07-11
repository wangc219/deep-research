# 装备能力图像 Deep Research 多智能体系统技术方案

## 1. 方案定位

当前交付为 Phase 0 研究运行基线，目标是固化领域契约、配置边界、运行工作区、公开材料安全材料化、证据隔离、三层制胜机理输出和审计产物，为后续接入真实模型、真实搜索、持久化与企业应用提供稳定接口。

本方案严格区分两类范围：

- **Phase 0 已完成**：当前仓库已经实现且可由自动化测试和 smoke 验证的能力。
- **后续阶段**：已经定义接口或目录边界，但尚未接入的能力，不作为本阶段验收完成项。

## 2. Phase 0 已完成

### 2.1 研究路线与领域输出

- 支持 `new_winning_mechanism`、`traditional_gap`、`war_case_learning` 三类研究路线。
- 支持 L1 制胜逻辑分析、L2 概念创新评估、L3 能力图像生成。
- 能力图像固定输出九字段：能力编号、名称、装备类别、类型、来源制胜逻辑、关联场景、优先级、能力差距、能力画像。
- 领域对象、计划节点、任务消息、召回消息、trace 和报告对象具备稳定序列化契约。

### 2.2 Agent 设计

默认提供国际形势、作战场景、武器装备、作战运用四个 baseline agent。四路 agent 由 `AgentRegistry` 和配置文件管理，不在 runner 中按固定 ID 分支：

- 默认可运行全部四路。
- `--agents` 可选择任意子集。
- `agents.yaml` 可替换或新增 agent。
- 每个 agent 声明能力标签、工具、上下文策略和领域对象读写范围。
- 每个所选 agent 生成独立 `agent_sessions/<agent-id>.jsonl`，其他 agent 原始会话不进入其上下文。

Phase 0 scheduler 已建立统一调度契约和覆盖度计算；生产级并行执行、弹性 worker 和分布式队列属于后续阶段。

### 2.3 Provider 与模型边界

- 默认模型配置为 `gpt-5.5`。
- `providers.yaml` 定义 Responses-compatible HTTP provider 的模型、地址环境变量、密钥环境变量和超时字段。
- `fake` provider 提供稳定离线闭环。
- `real` provider 当前为模板占位实现：生成受控公开 URL 线索并进入材料化流程，未执行真实模型推理循环。

真实模型循环和真实搜索尚未接入。现阶段不得将 `real` 模式描述为生产级联网研究能力。

### 2.4 公开材料与证据治理

公开来源采用“广泛搜集 + 网络安全 + 质量阈值 + 失败材料隔离”策略：

- 不按来源域名设置准入门槛，公开 HTTP(S) 线索可进入统一抓取流程。
- 网络层拒绝非 HTTP(S)、本机地址、私网/保留地址和解析到非公网地址的目标。
- DNS 校验后的数值 IP 与实际 TCP 连接绑定；HTTPS 保留原 hostname 执行 SNI 和证书校验。
- 每次重定向重新执行 URL、DNS 和地址安全检查，并限制重定向次数和响应大小。
- 证据配置预留相关性、透明度、时效性、直接支撑和提取质量权重及阈值。
- 抓取失败和网络安全拒绝材料保留诊断 artifact，设置为不可进入正式证据集。
- scheduler 只把允许形成正式证据的材料写入 `EvidenceCard`，并同步修正 baseline packet 的 evidence IDs。

Phase 0 已验证材料化安全与失败隔离；配置驱动的完整搜索、质量评分、去重、独立印证和冲突推理将在后续阶段接入。

### 2.5 工作区与产物契约

`RunWorkspace` 为每次运行创建独立目录，并校验 `run-id` 不得逃逸输出根目录。七类稳定产物为：

- `report.md`
- `capability_images.json`
- `round_summary.json`
- `domain.jsonl`
- `trace.jsonl`
- `agent_sessions/`
- `artifacts/`

新增 `checkpoints/` 预留目录，但 Phase 0 不写入恢复点。`database_path` 只定义未来 `run.db` 的稳定位置，Phase 0 不创建数据库文件，也不提供恢复执行。

### 2.6 审计与限制呈现

- trace 记录运行启动、baseline agent 完成、覆盖度、三层分析和审计结果。
- agent 子集运行时，缺失能力标签和召回请求进入 summary、trace 与报告限制说明。
- 失败材料不被报告引用为正式支撑。
- `analyst_confirmed` 当前只记录到 trace 和 summary，不构成发布门控。

## 3. Phase 0 运行结构

```text
CLI
  -> DeepResearchRunner
      -> AgentRegistry / preset policy
      -> RunWorkspace
      -> DiscoveryScheduler
          -> fake provider 或模板 real provider
          -> EvidenceMaterializer
          -> agent_sessions / artifacts
      -> WinningMechanismEngine (L1/L2/L3)
      -> audit_run / render_report
      -> 七类稳定产物 + checkpoints 预留目录
```

## 4. 后续阶段

以下能力尚未完成，不纳入 Phase 0 完成声明：

- 真实 Responses 模型循环和真实搜索 provider。
- 配置驱动的搜索查询规划、质量评分、去重、独立印证、冲突检测和反证推理闭环。
- 持久化 checkpoint、`run.db`、resume、暂停、取消和故障恢复。
- 真正并行的 agent 执行、独立 worker、任务队列和资源治理。
- FastAPI、SSE、RBAC/OIDC、PostgreSQL、Redis、React Web、报告审批与企业部署。

上述能力进入实施前必须保持 Phase 0 七类产物和领域对象契约兼容，新增能力不得破坏现有 CLI 和离线回归基线。

## 5. 技术验收原则

- 以自动化测试、严格残留扫描和独立输出根 smoke 为验收证据。
- 文档中的“已完成”必须能在当前代码和测试中定位。
- 后续能力只能标为预留、规划或进入条件，不得写成当前已交付。
- 公网不可达时允许 `real` smoke 降级并保留诊断，但不得伪造抓取成功或正式证据。
