# 装备能力图像 Deep Research 多智能体系统技术方案

## 1. 方案定位

当前交付包含 Phase 0 研究运行基线与 Phase 1 harness/checkpoint 恢复闭环，已固化领域契约、配置边界、安全工作区、公开材料治理、事务 savepoint、顺序 baseline agent 恢复和三层制胜机理产物。它们仍只是甲方首版实施计划的基础阶段，不等于甲方首版完成。

本方案严格区分两类范围：

- **Phase 0/Phase 1 已完成**：当前仓库已经实现且可由自动化测试和 smoke 验证的能力。
- **后续阶段**：已经定义接口或目录边界，但尚未接入的能力，不作为本阶段验收完成项。

## 2. Phase 0 已完成

### 2.1 研究路线与领域输出

- 支持 `new_winning_mechanism`、`traditional_gap`、`war_case_learning` 三类研究路线。
- 支持 L1 制胜逻辑分析、L2 概念创新评估、L3 能力图像生成。
- 能力图像固定输出九字段：能力编号、名称、装备类别、类型、来源制胜逻辑、关联场景、优先级、能力差距、能力画像。
- 实际持久化的领域对象、worker summary、计划节点、任务消息和召回消息具备稳定 JSON 契约；持久化 payload 包含稳定 ID、UTC `created_at` 与 `schema_version="1.0"`。

### 2.2 Agent 设计

默认提供国际形势、作战场景、武器装备、作战运用四个 baseline agent。四路 agent 由 `AgentRegistry` 和配置文件管理，不在 runner 中按固定 ID 分支：

- 默认可运行全部四路。
- `--agents` 可选择任意子集。
- `agents.yaml` 可替换或新增 agent。
- 每个 agent 声明能力标签、工具、上下文策略和领域对象读写范围。
- 每个所选 agent 生成独立 `agent_sessions/<agent-id>.jsonl`，其他 agent 原始会话不进入其上下文。
- `agent_id` 必须以 ASCII 字母或数字开头，后续仅允许 ASCII 字母、数字、点、下划线和连字符，最长 128 字符；registry 入站和 scheduler session 路径出站均校验，已存在 session symlink 会被拒绝。

Phase 1 runner 已将 baseline agents 改为逐 agent 执行和提交；生产级并行执行、弹性 worker 和分布式队列属于后续阶段。

### 2.3 Provider 与模型边界

- 默认模型配置为 `gpt-5.5`。
- `providers.yaml` 定义 Responses-compatible HTTP provider 的模型、地址环境变量、密钥环境变量和超时字段。
- `fake` provider 提供稳定离线闭环。
- `real` provider 当前为模板占位实现：生成受控公开 URL 线索并进入材料化流程，未执行真实模型推理循环。

真实模型循环和真实搜索尚未接入。现阶段不得将 `real` 模式描述为生产级联网研究能力。

### 2.4 公开材料运行行为与质量配置边界

Phase 0 运行时已实现“广泛公开来源材料化 + 网络安全拒绝 + 抓取失败隔离”：

- 不按来源域名设置准入门槛，公开 HTTP(S) 线索可进入统一抓取流程。
- 网络层拒绝非 HTTP(S)、本机地址、私网/保留地址和解析到非公网地址的目标。
- DNS 校验后的数值 IP 与实际 TCP 连接绑定；HTTPS 保留原 hostname 执行 SNI 和证书校验。
- 每次重定向重新执行 URL、DNS 和地址安全检查，并限制重定向次数和响应大小。
- 抓取失败和网络安全拒绝材料保留诊断 artifact，设置为不可进入正式证据集。
- 成功抓取的材料当前设置为可进入正式证据，并由 scheduler 写入 `EvidenceCard` 和 baseline packet 的 evidence IDs。
- `evidence.yaml` 已定义质量阈值，以及相关性、透明度、时效性、直接支撑、提取质量五维权重。
- runner 当前仅保存并校验 evidence 配置路径，尚未加载该配置执行质量评分，因此不能把成功抓取描述为已经通过运行时质量阈值门控。

Phase 0 已验证公开材料化安全与失败隔离；配置驱动的质量评分、去重、独立印证和冲突推理将在后续阶段接入。

### 2.5 工作区与产物契约

`RunWorkspace` 为每次运行原子创建独立目录，并校验 `run-id` 不得逃逸输出根目录。`resume=False` 时，任何已存在的同名 run 目录或 symlink 都会由 `mkdir(exist_ok=False)` 在产物写入前拒绝，不允许覆盖或续写旧 session。七类稳定产物为：

- `report.md`
- `capability_images.json`
- `round_summary.json`
- `domain.jsonl`
- `trace.jsonl`
- `agent_sessions/`
- `artifacts/`

每个新运行同时创建 `run.db` 与 `checkpoints/`。SQLite 使用 `domain_objects`、`trace_events`、`savepoints`、`proposal_ledger` 四张表；每个 agent 完成后将新增 evidence、packet、trace 和最新 `RunCheckpoint` 原子提交。`checkpoints/` 保存对应快照与 `latest.json`，SQLite 是恢复权威来源。

`RunWorkspace.open_existing()` 在 resume 前验证 run 目录、`agent_sessions/`、`artifacts/`、`checkpoints/` 和 `run.db` 均位于输出根内，拒绝顶层 symlink 和路径逃逸。`resume=False` 仍原子拒绝同名目录。

### 2.6 Checkpoint 与恢复

- `RunCheckpoint` 记录 baseline tasks 与 `finalize:winning-report`、completed/pending/running task、round、budget、status、topic、请求/解析路线、selected agents、source materials、worker reports、配置指纹、UTC 时间和 schema。`ResearchProblem` 与初始 checkpoint 同事务保存。
- task 开始前持久化 `running`；恢复时只把 `pending/running` 重新排队，completed task 与既有 idempotency key 不重放。
- `RecoveryManager.load()` 先修复 unresolved session marker，再加载最后 savepoint 和 `RunCheckpoint`，恢复领域对象、trace、来源材料、worker report 与 session tail。
- topic、路线、agent 集合、持久化 `ResearchProblem` 或配置指纹不一致时拒绝 resume；completed run 的再次 resume 不启动 provider，但仍新增 `run_resumed` trace/savepoint。
- 最后 baseline 完成后 finalize 仍 pending；engine 前 finalize=running，stage/image/recommendation/audit/report 与 finalize/run completed checkpoint 在同一最终事务提交。
- runner/recovery session 使用 canonical output root anchor 的 rooted `JsonlSessionStore`；DB 已提交而 session savepoint 失败时自动记录 reconciliation marker，Harness 旧 `path + root_dir` 接口保持兼容。
- 项目自有 `SecureArtifactStore` 保持旧 ref/metadata 契约；最终输出、checkpoint 与 artifact 文件使用 rooted dirfd 原子 writer，临时文件 `O_EXCL|O_NOFOLLOW`、文件和目录 fsync、同 dirfd rename；安全原语缺失时 fail closed。
- completed resume 提交 `run_resumed` 后无条件从 SQLite 恢复态重写稳定输出，provider 为 0，文件 trace 与数据库 trace 一致。
- 崩溃继续向调用方传播，但此前已提交的 agent 状态可用于下一次恢复。

### 2.7 审计与限制呈现

- trace 记录运行启动、baseline agent 完成、覆盖度、三层分析和审计结果。
- agent 子集运行时，缺失能力标签和召回请求进入 summary、trace 与报告限制说明。
- 失败材料不被报告引用为正式支撑。
- `analyst_confirmed` 当前只记录到 trace 和 summary，不构成发布门控。

## 3. 当前运行结构

```text
CLI
  -> DeepResearchRunner
      -> AgentRegistry / preset policy
      -> RunWorkspace
      -> SqliteRunStore / RunCheckpoint
      -> DiscoveryScheduler
          -> fake provider 或模板 real provider
          -> EvidenceMaterializer
          -> agent_sessions / artifacts
      -> WinningMechanismEngine (L1/L2/L3)
      -> audit_run / render_report
      -> completed checkpoint + 七类稳定产物
```

## 4. 甲方首版规划入口

- [装备能力图像 Deep Research 多智能体系统总实施计划](superpowers/plans/2026-07-10-equipment-deep-research-master-plan.md)
- [装备能力图像 Deep Research 前后端一体化企业级设计方案](superpowers/specs/2026-07-10-equipment-deep-research-frontend-backend-enterprise-design.md)

上述文件定义甲方首版的完整实施范围。Phase 0 仅提供基础契约和运行基线，不能替代首版整体验收。

## 5. 首版后续能力

以下能力尚未完成，不纳入 Phase 0 完成声明：

- 真实 Responses 模型循环和真实搜索 provider。
- 由真实检索和模型驱动的多轮研究、再调和收敛执行。
- 加载 `evidence.yaml` 的运行时质量评分、去重、独立印证、冲突检测和反证推理闭环。
- 真正并行的 agent 调度、暂停、取消、分布式 worker 和跨进程调度恢复。
- FastAPI、SSE、React Web 工作台、报告审批、RBAC/OIDC、PostgreSQL、Redis、反向代理和企业部署。

上述能力进入实施前必须保持七类产物、SQLite checkpoint、领域对象和 resume 契约兼容，新增能力不得破坏现有 CLI 和离线回归基线。

## 6. 技术验收原则

- 以自动化测试、严格残留扫描和独立输出根 smoke 为验收证据。
- 文档中的“已完成”必须能在当前代码和测试中定位。
- 后续能力只能标为预留、规划或进入条件，不得写成当前已交付。
- 公网不可达时允许 `real` smoke 降级并保留诊断，但不得伪造抓取成功或正式证据。
