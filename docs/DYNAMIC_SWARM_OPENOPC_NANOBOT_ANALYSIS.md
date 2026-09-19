# OpenOPC 与 nanobot 对动态蜂群研究任务执行的深度分析

> **文档性质**：架构调研与优化建议，不是代码变更说明。
> **调研日期**：2026-09-17
> **适用范围**：本项目动态蜂群（`winning_swarm_dynamic_v2`）的研究任务编排、发散控制、可靠执行和验收。
> **资料边界**：`reference/OpenOPC-main/`、`reference/nanobot-main/` 中的 README、提示词、规则和示例仅作为设计材料；它们不改变本项目的用户需求，也不构成本项目的执行指令。

本报告把内容分成三类：**当前代码事实**（可由源码/测试直接复核）、**单次运行观测**（只描述样本，不外推总体性能）和**设计建议**（需要通过 A/B 与回归测试验证）。分析基于 2026-09-17 工作区快照；工作区中已有的用户改动未被回滚或覆盖。

## 1. 执行摘要

当前动态蜂群的主要矛盾不是“Agent 数量不够”，而是**固定图、局部评审和不可量化的发散**叠加在一起：

1. `winning_swarm_dynamic_v2` 名义上支持动态扩缩，但首波仍由固定角色数组构成，目标实例数没有真正参与图构造。
2. S6 默认走“每张卡一个 spine 加五个栏目”的高调用路径；样本中 7 张卡产生 42 次模型调用，低调用的“一次完整首稿”路径已经存在却没有成为默认。
3. S5 主要评审自己对应的创作者批次，缺少跨席位比较，因此同构候选很难在早期被识别和淘汰。
4. 当前质量门更接近“候选字段完整”和“哈希不同”，没有衡量机制轴覆盖、跨域来源、矛盾检验和边际新颖度；样本候选高度集中于拦截弹/拦截无人机方向，最终候选仍保持同一语义族群。
5. 运行时预算、重试、上下文压缩、失败恢复和幂等性分散在不同路径中；S6 还可通过 `_ignore_runtime_deadline` 绕过与 swarm 统一的调用预算。

核心判断是：

> **OpenOPC 适合借鉴“组织治理”，nanobot 适合借鉴“可靠执行”，而本项目必须自己补上“研究策略与发散控制层”。**

建议的目标闭环为：

```text
Query
  -> Query-derived Coverage Matrix
  -> 3-4 个异质 Scout 首波
  -> 结构化归一化、聚类与去重
  -> Gap Analyzer（覆盖缺口、反证缺口、边际收益）
  -> 仅针对高价值缺口动态补招
  -> Verifier / Skeptic
  -> Quorum Barrier
  -> 2-3 个跨候选池 S5
  -> 每张卡一次完整 S6 首稿，失败栏目定向修复
```

这条路线优先复用现有 `winning_swarm.py`、`dynamic_winning_scheduler.py`、`dynamic_swarm.py`、`s6_authoring.py`、`runtime.py` 和 `execution_contracts.py` 的边界，不引入没有明确责任和验收指标的新模块。

## 2. 现状与证据

### 2.1 动态 v2 实际仍是固定 16 实例图

`src/equipment_deep_research/orchestration/winning_swarm.py` 中：

- `default_winning_swarm_policy()` 将 dynamic-v2 的 `mission_graph_min_instances` 和 `mission_graph_target_instances` 都设为 16（`winning_swarm.py:249-267`）。
- `build_mission_graph()` 虽然计算了 `target_instances`、`minimum` 和 `maximum`，但 dynamic-v2 分支随后直接建立固定数组：2 个 S1、2 个 S2、3 个 S3、3 个 S4 和 6 个 S5（`winning_swarm.py:736-793`）。因此 `target` 不能决定首波实例数；这一点也被 `tests/equipment_deep_research/unit/test_winning_swarm.py:1313-1330` 的 target=8/11/15 仍为 16 个实例断言锁定。
- `dynamic_swarm.py:257-282` 确实计算并把 `target_instances` 传给构图器，但构图器的固定 dynamic-v2 分支没有消费该值。`dynamic_swarm.py:3759` 起的逻辑只是固定图内的依赖就绪排序，不是按覆盖缺口扩缩容。
- `recruit_into_mission_graph()` 已有容量检查、依赖解析、wave 写入和 ledger 更新（`winning_swarm.py:1006-1075`），但截至本次调研对全仓库生产代码搜索只发现定义，没有发现调用点。它目前是“可用的接口”，不是“闭环中的控制器”。

这意味着当前所谓动态行为主要发生在固定图内部：根据依赖就绪、失败或回溯决定先后，而不是根据覆盖缺口决定“是否需要新的异质研究席位”。

### 2.2 调度器的并行动作仍未落地

`src/equipment_deep_research/orchestration/dynamic_winning_scheduler.py` 的 `StepAction.PARALLEL` 仍标注为未实现（`dynamic_winning_scheduler.py:35-41`）。依赖波次规划本身可以并行 ready units，但“由研究结果触发新的并行探索”尚未形成可执行动作、预算扣除、合并和取消语义。

### 2.3 S6 存在低调用路径，但动态路径默认走高调用路径

`src/equipment_deep_research/agents/workflows/winning_flows/s6_authoring.py` 同时包含：

- 每卡一次完整首稿的低调用路径（`s6_authoring.py:1225-1261`）；
- spine 加五个栏目 fan-out 的高调用路径（`s6_authoring.py:935-1082`）。

`src/equipment_deep_research/agents/workflows/winning.py` 将 `parallel_portrait_modules` 在动态路径中开启（`winning.py:1667-1669`），因此实际运行优先选择高调用 fan-out。S6 的运行选项在 `runtime.py:1438-1450` 设置了 `_ignore_runtime_deadline=True`，并在 `runtime.py:1725-1734` 按 phase 落入 `critical` 优先级；只有 `winning_swarm_*` 才进入 `swarm` 分支的计数门（`runtime.py:320-334`）。这不是“完全没有超时或并发保护”，而是**S6 与 swarm 的计费/预算分区不一致**，容易使完整链路低估调用量。

### 2.4 样本运行暴露出效率瓶颈

样本目录：`outputs/runs/swarm-gpt-20260909-v5`。以下是一次样本运行的统计，不代表稳定的 P50、单位成本或所有题型的平均表现；模型、provider、网络、并发和失败重试都会影响结果。

| 指标 | 观测值 | 解释 |
|---|---:|---|
| 蜂群 session | 16 | 与固定图一致 |
| 候选数 | 24 | 主要由 6 个创作席位产生 |
| `winning_model_call_started` | 42 | 7 张 S6 卡，每卡 spine + 5 栏目 |
| S6 卡数 | 7 | 每卡理论上可用 7 次完整首稿调用替代 42 次 fan-out |
| 蜂群累计工作时长 | 约 1291.856 秒 | 包含并发 session 的累计耗时，不等于墙钟时间 |
| S5 累计工作时长 | 约 382.282 秒 | 一对一席位带来的重复上下文与比较成本 |
| 最慢单个 creative session | 约 168.551 秒 | 造成尾部延迟 |

这些数字不是所有题目的基准线，而是当前实现的一个可复现实例。它们足以说明：先减少无效 fan-out 和重复评审，再增加 Agent 数量，通常能获得更确定的收益。

同一目录的 `winning_s5_parallel_score_started` 事件还显示，主要 S5 批次的 `producer_instance_ids` 与 `candidate_scope` 绑定到单个创作者席位；这解释了为什么当前 S5 更像“席位内筛选”，而不是跨席位的候选池比较。

统计口径可用以下命令复核（对 `agent_sessions` 与其他 JSONL 一并扫描，并按事件类型过滤）：

```bash
RUN=outputs/runs/swarm-gpt-20260909-v5

# 24 个去重候选、其中 17 个名称含拦截弹/拦截无人机
find "$RUN" -type f -name '*.jsonl' -print0 | xargs -0 jq -r \
  'select(.event_type == "winning_candidate_branch_created") |
   [.hypothesis_id, (.primary_equipment_identity // .title // "")] | @tsv' |
  sort -u | wc -l
find "$RUN" -type f -name '*.jsonl' -print0 | xargs -0 jq -r \
  'select(.event_type == "winning_candidate_branch_created") |
   (.primary_equipment_identity // .title // "")' |
  rg -c '拦截弹|拦截无人机'

# 42 次模型调用、7 张 S6 卡；session elapsed 总和 1291.856s，最大 168.551s
find "$RUN" -type f -name '*.jsonl' -print0 | xargs -0 jq -s \
  '[.[] | select(.event_type == "winning_model_call_started")] | length'
find "$RUN" -type f -name '*.jsonl' -print0 | xargs -0 jq -s \
  '[.[] | select(.event_type == "winning_s6_card_authoring_started")] | length'
find "$RUN" -type f -name '*.jsonl' -print0 | xargs -0 jq -s \
  '[.[] | select(.event_type == "winning_agent_session_completed" and
     .elapsed_seconds != null) | .elapsed_seconds] |
   {count: length, sum: add, max: max}'
```

### 2.5 发散不足不是“temperature 不够高”

样本 24 个候选中，17 个名称直接包含“拦截弹”或“拦截无人机”；最终 7 个候选仍集中在这两类。质量门报告的多个 `semantic:*` 家族更像逐候选哈希唯一，并不能证明机制空间独立。

目前缺失的可观测量包括：

- 机制轴覆盖率；
- 跨域来源熵；
- 同构候选比率；
- 反证/矛盾覆盖率；
- 每次调用带来的边际新颖度；
- 角色历史收益与调用成本的关系。

因此，继续复制相同 archetype 或单纯提高并发，会把“更多同类答案”误认为“更高发散”。

## 3. OpenOPC 的可迁移设计

### 3.1 值得借鉴的部分

| OpenOPC 设计 | 参考位置 | 迁移到本项目的含义 |
|---|---|---|
| DAG 与 runnable frontier | `task_graph.py:16-118` | 把任务依赖、可运行前沿和完成条件作为一等数据，而不是散落在 prompt 或回调中 |
| 权威 Phase 状态机 | `phase.py:303-522` | 每个研究席位只能通过一个状态转换入口推进，统一传播成功、失败、阻塞和取消 |
| 单一转换入口 | `work_item_transition.py:46-400, 780+` | 依赖唤醒、失败传播、重试和审计事件应拥有同一条写路径 |
| 按需求/类别/经验招聘 | `recruiter.py:362-414, 584+` | 以“缺哪条覆盖轴”招募角色，而不是按固定席位复制角色 |
| 运行中组织调整 | `reorg_manager.py:31-223` | 把动态补招、降级、合并和停止视为受治理的决策，而不是临时 spawn |
| 经验与反思沉淀 | `employee_evolution.py:23-332` | 记录 archetype 的收益、失败原因、成本和适用条件，供后续探索排序 |

### 3.2 不应直接照搬的部分

- OpenOPC 的 DAG 调度器偏基础执行，没有研究任务所需的优先级、token/调用预算、Coverage Matrix、质量门和边际收益判断。
- recruiter 主要是执行前招聘；本项目需要的是“运行中根据 Coverage Gap 招募”。
- reorg 更接近提案/审批式治理，不能直接当作自动策略控制器。
- 仅按历史次数或经验分排序会造成角色锁定，降低探索性；本项目必须保留探索下限和时间衰减。

### 3.3 应吸收的组织原则

1. **状态单一写入**：一个任务的状态、依赖唤醒和失败传播不能由多个 workflow 各自修改。
2. **图是事实，prompt 是视图**：研究缺口、依赖和预算先进入结构化图，再渲染给 Agent。
3. **招聘必须有理由**：每次补招记录触发的覆盖缺口、预期收益、成本和停止条件。
4. **经验可解释且可衰减**：记录“在什么题型、什么缺口、用多少调用取得什么收益”，不把角色永久固定在单一任务上。

## 4. nanobot 的可迁移设计

### 4.1 值得借鉴的部分

| nanobot 设计 | 参考位置 | 迁移到本项目的含义 |
|---|---|---|
| session 内串行、session 间并发 | `agent/loop.py:1392-1420` | 保持单个研究任务的上下文顺序，同时用显式 Semaphore 控制跨席位并发 |
| background/inline 子任务 | `agent/subagent.py:150, 227-342` | 明确哪些任务阻塞主闭环、哪些可以后台补证；不要让所有 spawn 都隐式阻塞 |
| 只并发 `concurrency_safe` 工具 | `agent/tools/execution.py:56-82, 292-306` | 工具调用按副作用分类；写 ledger、提交 artifact 等操作默认串行或带幂等键 |
| H/Delta 上下文治理 | `agent/context_governance.py:316-376, 709-756` | 长工具结果落盘，主上下文只保留摘要、引用和未解决缺口 |
| 工具前后 checkpoint | `agent/runner.py:498-576, 1346+` | 在不可逆外部调用前记录 attempt、输入摘要、lease 和恢复点 |
| 恢复时不重放不确定副作用 | `session/recovery.py:214-374` | 重启后先查询调用结果/幂等键，再决定重试，不盲目重复模型或工具副作用 |
| retry/fallback/熔断 | `providers/fallback_provider.py:102-114, 327-443, 515+` | provider 失败与研究失败分开处理；重试耗尽后降级或切换 provider，并留下可审计原因 |

### 4.2 不应直接照搬的部分

- nanobot 的 spawn 接口主要是自由文本 `task`、`label`、`temperature`、`wait`，没有研究所需的 DAG、Coverage Matrix、质量门、候选去重和预算合同。
- 子任务状态清理后没有完整的持久任务/结果 ledger；本项目不能把内存中的子任务列表当作研究事实。
- nanobot 的发散主要依赖 prompt 和 temperature；本项目需要显式的机制轴、异质 archetype 和边际收益控制。

### 4.3 应吸收的执行原则

1. **每个 attempt 都可恢复**：记录输入摘要、provider、模型、开始/结束时间、结果引用和状态。
2. **并发有边界**：并发额度按研究阶段、工具副作用和剩余预算共同决定。
3. **结果与长文本分离**：ledger 保存结构化摘要和 artifact 引用，完整输出落盘。
4. **重试不改变语义**：重试使用同一幂等键；需要换策略时新建 attempt，而不是覆盖旧结果。

## 5. 目标闭环设计

### 5.1 Coverage Matrix：把“发散”变成可计算对象

Coverage Matrix 由 Query 派生，不由固定装备类别列表派生。建议至少包含六个正交轴：

1. **战场断点**：感知、决策、部署、接敌、持续压制、恢复/再生等。
2. **改变的作用机制**：物理毁伤、结构失效、空间拒止、时间错位、资源交换、行为诱导等。
3. **载体/物化形态**：弹体、无人平台、材料/介质、基础设施嵌入、群体/网络化形态等。
4. **接敌几何与时间尺度**：点目标、通道、区域、边界迁移；瞬时、持续、分阶段。
5. **成本、暴露和资源交换**：单次成本、可消耗性、暴露窗口、对手交换比。
6. **对手反制与证伪条件**：对手如何适应、哪条假设最脆弱、如何做最小验证。

每个候选至少提交：

```text
candidate_id
mechanism_axes[]
carrier_form
engagement_geometry
time_scale
resource_exchange
counter_adaptation
falsification_condition
source_domains[]
confidence
```

没有这些字段的候选可以保留为草稿，但不能计入“覆盖已达标”。

### 5.2 首波、补招和验证的职责

| 阶段 | 目标 | 允许的行为 | 停止条件 |
|---|---|---|---|
| 异质 Scout 首波 | 快速覆盖不同机制轴 | 3-4 个不同 archetype，各自独立生成小批候选 | 首波预算耗尽或达到最低轴覆盖 |
| 归一化/聚类 | 判断是否真正不同 | 结构化抽取、语义聚类、机制轴冲突检查 | 形成候选族群与未覆盖轴清单 |
| Gap Analyzer | 只补高价值缺口 | 为缺口选择新 archetype、指定输入域和输出字段 | 预期边际收益低于成本 |
| Verifier/Skeptic | 主动找反例 | 反证、对手适应、最小验证路径 | 反证覆盖达到阈值或预算耗尽 |
| Quorum Barrier | 统一质量门 | 只允许字段完整、机制独立、反证可追踪的候选进入 S5 | 未达门槛的候选退回定向修复 |

### 5.3 自适应决策函数

策略层应是纯函数，便于单测、回放和多人协作：

```text
AdaptiveSwarmDecision(
  coverage_gaps,
  duplicate_ratio,
  marginal_novelty,
  contradiction_gaps,
  remaining_calls,
  remaining_tokens,
  remaining_time,
  queue_latency,
  role_historical_yield
) -> EXPAND | VERIFY | REVIEW | STOP
```

建议的初始规则（先作为可配置策略，不硬编码成不可解释的模型判断）：

- `coverage < 0.75`：`EXPAND`；优先切换 archetype 和来源域，不复制同类创作者。
- 覆盖足够但 `contradiction_coverage < 0.70`：`VERIFY`；招募 skeptic 或反事实角色。
- 覆盖和反证均达标，且连续两批 `marginal_novelty < 0.08`：`STOP`。
- `duplicate_ratio` 高于阈值：必须改变机制轴/载体/接敌几何至少一项，不能只更换名称。
- 剩余调用、token、时间任一不足：降级为 `REVIEW` 或 `STOP`，并记录被放弃的缺口。

## 6. 效率优化方案

### 6.1 S6 采用“整卡首稿 + 定向修复”

第一步将每张卡的默认路径切换到 `s6_authoring.py` 已有的一次完整首稿路径：

- 7 张卡的 S6 首稿从理论上的 42 次调用降到 7 次，减少约 83%。
- 只有质量门明确指出缺失/矛盾的栏目才发起定向修复。
- 每次修复必须引用失败字段和原始 artifact，禁止重新生成整张卡。

这项改动先解决确定性的调用浪费，再评估是否需要进一步并行化；不要把“并行”误当作“更高效”。

### 6.2 让 `target_instances` 真正控制首波

保留现有 `build_mission_graph()` 和 `recruit_into_mission_graph()` 的边界，调整 dynamic-v2 构图逻辑：

1. 首先固定不可缺少的 S1/S2 和最小验证席位。
2. 根据 `target_instances` 从异质 archetype 候选池中选择首波席位。
3. 把剩余容量留给 Gap Analyzer 触发的补招，而不是一次性创建 6 个同质创作者和 6 个一对一评审。
4. 每次补招写入 `hypothesis_id`、触发缺口、预期收益和成本；超过 `maximum_instances` 立即停止。

### 6.3 将 S5 从“按席位评审”改为“跨候选池评审”

把 6 个一对一 S5 改为 2-3 个跨候选池 reviewer：

- 每个 reviewer 同时看到去重后的候选族群和 Coverage Matrix；
- 输出排序、淘汰理由、同构关系和需要验证的脆弱假设；
- 控制器对多 reviewer 结果做 quorum/加权合并，而不是简单拼接。

这样可以在减少 session 数的同时增加真正的横向比较。

### 6.4 统一调用预算

`execution_contracts.py:680-690` 当前把 dynamic-v2 的 `maximum_swarm_model_calls` 设为 48，并将 `maximum_quality_judge_model_calls` 设为 0；注释还按六个创作者、两次创作和六个配对 S5 估算。这个 ceiling 只覆盖 `runtime.py:320-334` 的 `priority == "swarm"` 计数，不会自动覆盖被标为 `critical` 的 S6 全链路调用。因此预算合同必须覆盖完整闭环，而不只是名字中带 `winning_swarm_*` 的调用。建议预算维度至少包括：

```text
total_model_calls
calls_by_phase (S1...S6)
total_tokens
wall_clock_deadline
in_flight_sessions
retry_reserve
```

S6 的 `_ignore_runtime_deadline` 只能用于明确标记的恢复/收尾场景，不能成为常规路径绕过预算的开关。

## 7. 可靠性与可恢复执行

在策略正确之后，吸收 nanobot 的执行护栏：

1. **attempt ledger**：每个模型/工具调用记录唯一 `attempt_id` 和幂等键。
2. **lease**：并发 worker 获取带过期时间的任务租约，超时后可安全回收。
3. **checkpoint**：调用前保存输入摘要和预算快照，调用后保存结果引用与状态。
4. **artifact-first**：长输出落盘，状态事件只携带摘要、hash 和路径。
5. **provider fallback**：区分瞬时 provider 失败、内容质量失败和预算失败，分别重试、降级或停止。
6. **恢复不重放不确定副作用**：重启时先根据幂等键查询已有结果，再决定是否创建新 attempt。

这些能力应优先扩展现有 `runtime.py`、`execution_contracts.py` 和 ledger，而不是新建一个与现有 runtime 平行的“可靠性框架”。

## 8. 实施路线（不增加无用模块）

### 8.1 最小模块边界约束

Coverage Matrix、Gap Analyzer 和边际收益判断首先应作为现有 controller/ledger/quality-gate 中的**纯函数与结构化字段**，而不是独立服务或新的 Agent 层。每项改动在合入前都要能回答四个问题：

| 设计项 | 首选落点 | 最小输入/输出 | 必须有的测试 | 回滚方式 |
|---|---|---|---|---|
| Coverage Matrix | `dynamic_swarm.py` 的策略数据 | Query + 候选 -> 轴覆盖快照 | 轴归一化、缺失字段、稳定排序 | 关闭指标计算，保留候选 schema |
| Gap Analyzer | `dynamic_swarm.py`/现有 controller | 覆盖快照 + 预算 -> 缺口与决策 | 阈值边界、预算不足、重复率高 | 固定首波、禁用补招 |
| 补招入口 | `winning_swarm.py` 的 `recruit_into_mission_graph()` | 缺口 + role contract -> 新 graph 版本 | 容量、依赖、幂等和失败传播 | 只允许初始图 |
| 调用记账 | `runtime.py` + `execution_contracts.py` | attempt + phase -> 统一预算快照 | 并发扣减、重试 reserve、S6 归属 | 回退旧预算字段 |
| 质量门 | 现有 S5/closeout ledger | 候选池 + Coverage Matrix -> quorum 结果 | 跨池排序、反证覆盖、拒绝原因 | 使用旧字段门槛 |

只有当上述纯函数造成明确的文件职责冲突，才考虑抽出一个小模块；新模块必须有唯一调用者、稳定输入输出、单元测试和删除/回滚路径。这样可以避免把“策略缺失”误解成“需要更多目录”。

### 阶段 0：基线与可观测性

- 在现有事件流中补齐 `coverage_axes`、`duplicate_cluster_id`、`marginal_novelty`、`contradiction_coverage`、`decision_reason`。
- 固化当前样本运行的调用、耗时和候选分布，建立 A/B 基线。
- 保留现有兼容字段，先增加指标，不改变业务语义。

### 阶段 1：先降 S6 成本

- 修改 `s6_authoring.py` 的默认选择，默认整卡首稿。
- 失败栏目走定向修复，记录修复前后差异。
- 更新锁定“spine + 五栏目”的旧测试，保留输出 schema 和质量门不变量。

### 阶段 2：修正 dynamic-v2 图构造

- 修改 `winning_swarm.py` 的 dynamic-v2 选择逻辑，使 `target_instances` 直接控制首波。
- 将 `recruit_into_mission_graph()` 接到 Gap Analyzer 的唯一补招入口。
- 完善 `dynamic_winning_scheduler.py` 的 PARALLEL 动作：预算预留、并发上限、合并、取消和失败传播必须一并实现。

### 阶段 3：加入 Coverage/Gap 策略

- 优先把纯函数和结构化数据放入现有 `dynamic_swarm.py` 或现有 orchestration 边界；只有当文件职责确实无法维持时，才抽出一个有明确输入/输出/测试的 coverage 模块。
- 将 archetype 选择、去重、缺口分析和停止判断与 provider 调用解耦。
- 先支持 3-4 个异质首波和有限补招，不做无限递归 spawn。

### 阶段 4：跨池 S5 与统一预算

- 让 S5 接收候选池快照和 Coverage Matrix，而不是单个 producer 的局部列表。
- 把 S6、重试和 provider fallback 纳入同一 execution contract。
- 对每阶段设置最小质量门和最大调用份额，保留 retry reserve。

### 阶段 5：可靠恢复与经验更新

- 在现有 runtime/ledger 中加入 attempt、lease、checkpoint 和幂等恢复。
- 角色收益使用时间衰减、题型条件化和探索下限，避免历史高分角色永久垄断。
- 运行故障注入和中断恢复测试，再扩大并发。

## 9. 验收指标与实验设计

### 9.1 目标指标

| 指标 | 目标 |
|---|---:|
| S6 首稿调用 | 7 张卡从 42 降至约 7 |
| 总调用成本 / 最终候选 | 下降至少 35% |
| P50 墙钟时间 | 下降至少 25% |
| 候选机制重复率 | 相对下降至少 30% |
| 有效覆盖率 `C` | `>= 0.80` |
| 反证覆盖率 `K` | `>= 0.70` |
| 盲评最终研究质量 | 不低于基线 2 个百分点以上 |
| 恢复正确性 | 中断后不重复提交已确认副作用 |

### 9.2 指标定义

建议将指标写成可重放的纯计算：

```text
C = sum(weight[d] for d in covered_dimensions) / sum(weight[d] for d in all_dimensions)
D = duplicate_candidates / max(1, total_candidates)
N_t = new_mechanism_clusters_at_batch_t / max(1, candidates_at_batch_t)
K = contradiction_checks_passed_or_recorded / max(1, required_contradiction_checks)
H = entropy(source_domains) / log(max(2, number_of_source_domains))
```

“语义 hash 不同”只能作为去重的一个信号，不能替代 `C`、`D`、`N_t`、`K` 和 `H`。

### 9.3 A/B 方案

- 选择至少 20 个分层研究题，覆盖不同战场断点、机制和约束。
- 每题运行 3 次配对实验：基线固定 swarm vs. 自适应 swarm。
- 固定 provider、模型、最大 token 和质量盲评流程；记录调用数、token、墙钟、覆盖、重复、反证和最终质量。
- 先做离线 replay，再做真实 provider 运行；任何策略变化都必须能从事件 ledger 重放。

### 9.4 必须更新的测试不变量

当前测试中有两类旧假设会阻断新架构：

- `tests/.../test_winning_swarm.py` 锁定 16 实例、6 creator、6 S5；应改为验证最小/目标/最大边界、动态补招和容量守恒。
- `tests/.../test_codex_provider.py` 锁定每卡 1 spine + 5 栏（5 卡 31 次，含单栏重试）；应改为验证整卡首稿、定向修复和总预算。

应保留的兼容不变量包括：角色合同可审计、依赖不越级、候选 schema 不丢字段、失败可传播、同一幂等键不重复提交。

## 10. 风险与防护

| 风险 | 触发原因 | 防护 |
|---|---|---|
| 目标扩缩容与硬编码漂移 | policy、controller 和测试各自保留旧的 16 实例假设 | 用边界测试验证 `minimum/target/maximum`，事件中记录实际 graph size |
| 预算绕过 | S6 的 `_ignore_runtime_deadline` 或优先级边界使调用不进入统一 ceiling | 所有 phase 使用同一 attempt/accounting contract，绕过必须显式标记并扣预算 |
| 发散指标驱动“凑覆盖” | Agent 为填空生成弱候选 | 质量门同时检查可证伪性、机制差异和最小验证路径 |
| 动态补招失控 | 缺口计算噪声或阈值过低 | 每次补招消耗明确预算，设置最大 wave、最大实例和 retry reserve |
| 历史收益造成角色锁定 | 只按历史平均分排序 | 时间衰减、题型条件化、探索下限和随机小比例探索 |
| 并行导致 ledger 竞态 | 多 worker 同时写状态 | 单一转换入口、lease、幂等键和版本化提交 |
| 上下文压缩丢失证据 | 只保留自然语言摘要 | artifact 引用、hash、未解决缺口和原始输出路径必须保留 |
| 恢复重放/重复副作用 | worker 在不确定状态重试或幂等键缺失 | checkpoint 前后查询结果，副作用操作必须带 lease 和幂等键 |
| 参考设计语义错配 | OpenOPC reorg 的审批语义被误当成自动策略，或 nanobot 的 `concurrency_safe` 元数据配置错误 | 迁移前写适配层契约和故障注入测试，不直接复制实现 |
| 降低调用后质量下降 | 过早把 fan-out 全部关闭 | 先保留定向修复和质量门，以盲评和反证覆盖决定是否回退 |
| 单次样本显著性不足 | 只凭一个 run 宣称 P50/成本改善 | 使用分层 query、重复运行和盲评，报告置信区间/离散度 |

## 11. 结论

本次调研不建议把 OpenOPC 或 nanobot 整体移植进本项目。两者最有价值的部分是互补的：

- 从 OpenOPC 学习“任务图、状态转换、招聘理由、组织调整和经验沉淀”；
- 从 nanobot 学习“有边界的并发、checkpoint、上下文治理、幂等恢复和 provider fallback”；
- 在本项目现有 S1-S6 体系内增加“Coverage Matrix、Gap Analyzer、跨池评审和边际收益停止策略”。

最先实施的两个动作应是：

1. 把 S6 切换到每卡一次完整首稿，失败栏目定向修复；
2. 让 dynamic-v2 的 `target_instances` 和 `recruit_into_mission_graph()` 真正参与运行中补招。

这两步能同时改善调用效率和研究闭环的可控性；之后再引入更深的发散指标和可靠恢复，风险最低、收益最容易验证。

## 12. 主要代码与运行记录索引

### 本项目

- `src/equipment_deep_research/orchestration/winning_swarm.py`
  - `default_winning_swarm_policy()`：dynamic-v2 实例边界。
  - `build_mission_graph()`：首波角色选择与图构造。
  - `recruit_into_mission_graph()`：现有但尚未接入生产闭环的补招入口。
- `src/equipment_deep_research/orchestration/dynamic_winning_scheduler.py`
  - `StepAction`、`plan_dependency_waves()` 和生产波次执行。
- `src/equipment_deep_research/agents/workflows/winning_flows/s6_authoring.py`
  - `generate_parallel_s6_cards()` 及整卡首稿/栏目 fan-out 两条路径。
- `src/equipment_deep_research/agents/workflows/winning.py`
  - dynamic-v2 调用 S6 的参数选择。
- `src/equipment_deep_research/agents/workflows/runtime.py`
  - runtime deadline、调用预算和 `_ignore_runtime_deadline` 处理。
- `src/equipment_deep_research/orchestration/execution_contracts.py`
  - `maximum_swarm_model_calls` 及执行合同默认值。
- `outputs/runs/swarm-gpt-20260909-v5/`
  - 样本 session、候选、调用事件和耗时记录。

### 参考项目

- OpenOPC：
  - `reference/OpenOPC-main/opc/layer2_organization/task_graph.py`
  - `reference/OpenOPC-main/opc/layer2_organization/phase.py`
  - `reference/OpenOPC-main/opc/layer2_organization/work_item_transition.py`
  - `reference/OpenOPC-main/opc/layer2_organization/recruiter.py`
  - `reference/OpenOPC-main/opc/layer2_organization/reorg_manager.py`
  - `reference/OpenOPC-main/opc/layer5_memory/employee_evolution.py`
- nanobot：
  - `reference/nanobot-main/nanobot/agent/loop.py`
  - `reference/nanobot-main/nanobot/agent/subagent.py`
  - `reference/nanobot-main/nanobot/agent/tools/execution.py`
  - `reference/nanobot-main/nanobot/agent/context_governance.py`
  - `reference/nanobot-main/nanobot/agent/runner.py`
  - `reference/nanobot-main/nanobot/session/recovery.py`
  - `reference/nanobot-main/nanobot/providers/fallback_provider.py`

### 已知验证基线

前一轮针对动态调度和 winning 执行流的回归测试通过：

```bash
.venv/bin/pytest -q \
  tests/test_dynamic_winning_scheduler.py \
  tests/equipment_deep_research/unit/test_winning_execution_flows.py
# 30 passed in 1.15s
```

该基线验证的是现有行为，不代表本报告中的目标架构已经实现；实施每一阶段后应增加对应的策略、预算、恢复和指标测试。
