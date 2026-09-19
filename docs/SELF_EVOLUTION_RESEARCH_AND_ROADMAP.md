# S1–S6 文本型自进化：调研、架构与实施路线

> 版本：v1.0 · 2026-09-13  
> 范围：仅优化 S1–S6 的 Prompt、Memory、检索策略和文本化评测配置；不更新模型权重、不修改代码拓扑、不在线自动改生产配置。

## 1. 结论先行

当前最适合本项目的方案不是“让 Agent 自己改自己的 Prompt”，而是建设一个**证据驱动、可归因、可回滚的文本策略实验平台**：

```text
S1–S6 执行 Trace / Critic / 专家反馈
        ↓
Residual（残差）与问题分类
        ↓
候选 Lesson / Memory + 最小 Prompt Section Patch
        ↓
静态契约检查
        ↓
固定 Query / Evidence / Seed 的 Champion–Challenger 回放
        ↓
局部消融 + 全链路盲评 + 成本/时延检查
        ↓
人工审核 → Shadow → Canary
        ↓
Promote 为 Champion 或自动 Rollback
        ↓
把“采用、效果、误导、过期”写回 Memory 与 Evolution Ledger
```

必须坚持四个语义边界：

| 状态 | 含义 | 能否进入线上 S1–S6 |
| --- | --- | --- |
| `processed` | 反馈已被压缩、去重或路由 | 否 |
| `applied` | 某次运行实际注入了该 Prompt/Memory | 不是质量证明 |
| `validated` | 在固定回放和门禁上通过 | 仍需审核/灰度 |
| `effective` | 在目标分布的线上或灰度运行中持续带来净收益 | 是，但仍可撤回 |

核心原则是：**单条专家评语只能产生候选；只有可重复的离线证据才能产生晋级资格。**

## 2. 当前实现审计

### 2.1 已有能力

| 能力 | 当前位置 | 当前行为 | 评价 |
| --- | --- | --- | --- |
| 任务级反馈持久化 | `src/equipment_deep_research/expert_feedback.py` | 保存原始反馈，压缩学习信号，关键词路由到最多三个阶段 | 适合作为入口，但还没有效果闭环 |
| 反馈去重 | `src/equipment_deep_research/expert_feedback.py` | 字符归一化后保留 canonical，重复项进入审计 | 可保留；需要语义近重复和冲突处理 |
| 定向反馈注入 | `src/equipment_deep_research/agents/workflows/winning_flows/helpers.py` | 按 S 阶段筛选 | 还缺 route、适用域、TTL、可信度过滤 |
| Prompt 提案 | `src/equipment_deep_research/prompt_evolution.py` | Codex 生成完整阶段 Prompt，状态为 `pending_review` | 已有人工审核入口；粒度过粗 |
| Prompt 版本与回滚 | `src/equipment_deep_research/prompt_evolution.py` | 审核后替换 Markdown 的 `system` 段并保存快照 | 能回滚；缺少先评测后发布 |
| 动态 Prompt 片段 | `src/equipment_deep_research/agents/dynamic_prompt_resources.py` | S1–S6 和 `common.md` 已有大量 section 标记 | 是实施 section-level 演化的基础 |
| 评测注册表 | `evals/evolution.py` | 有 Champion/Challenger profile、Residual、回滚 | 与 Prompt/Memory 运行 Trace 尚未统一关联 |
| 评测模型 | `evals/models.py` | 有 `QueryResidual`、`AgentContributionObservation` 等观测结构 | 可扩展为 Evolution Ledger 的底层契约 |

### 2.2 当前关键缺口

1. `learning_status="processed"` 不能表示反馈有效；历史反馈可能未经验证就进入未来上下文。
2. `normalize_feedback()` 没有严重度、置信度、问题分类、作用域、版本快照和效果状态。
3. `load_feedback_knowledge()` 主要依赖主题词重叠，未按 profile/route/TTL/冲突和 utility 过滤。
4. Prompt 演化一次替换完整 `system` 段；一个小建议可能误伤同一文件中的契约、示例或共享逻辑。
5. 没有锁定 Query、证据快照、上游 Packet、模型和随机种子的 paired replay，无法可靠比较前后版本。
6. 没有 Prompt fragment / Memory → S-step → capability card → final report 的归因链，S6 的问题可能被错误归因给 S6 Prompt。
7. 没有 `selected / applied / adopted / outcome` 级别的 Retrieval Event，无法计算 Memory 的命中率、采用率和误导率。
8. 当前评测注册表与生产 Prompt/Memory 版本不共享一个不可变 Bundle ID，审计时难以回答“当时到底运行了什么”。

## 3. 调研：可借鉴的自进化机制

以下工作作为研究启发，不作为本项目的运行时依赖。适配时优先保留可审计、可回放、可回滚的部分。

### 3.1 反思与定向修复

| 机制/代表工作 | 主要思想 | 对本项目的适配 |
| --- | --- | --- |
| Reflexion（[arXiv:2303.11366](https://arxiv.org/abs/2303.11366)） | 执行后生成语言化反思，作为后续尝试的非参数反馈 | 用于同一 Query 内的短期 working memory；不得直接写入长期规则 |
| Self-Refine（[arXiv:2303.17651](https://arxiv.org/abs/2303.17651)） | 生成→批评→修订的迭代 | 给 S3/S4/S6 增加字段级 critic 和一次定向修复，限制轮数和 Token |
| CRITIC | 使用外部工具/证据进行批评，而非只依赖模型自评 | 让证据边界、JSON、候选身份、引用等硬检查优先于 LLM Judge |

适配结论：反思是“生成残差”的方法，不是“发布策略”的方法；必须将反思和长期 Memory 晋级拆开。

### 3.2 轨迹经验与分层 Memory

| 机制/代表工作 | 主要思想 | 对本项目的适配 |
| --- | --- | --- |
| ExpeL（[arXiv:2308.10144](https://arxiv.org/abs/2308.10144)） | 从成功/失败轨迹抽取自然语言经验，推理时检索，不更新参数 | 把完整 Trace 编译成带适用条件的 Lesson；保留来源 Run 和验证证据 |
| Voyager（[arXiv:2305.16291](https://arxiv.org/abs/2305.16291)） | 自动课程、可验证技能库、环境反馈和技能复用 | 将“阶段 checklist / playbook”视为 procedural fragment，只有通过回放才可激活 |
| MemoryBank / A-MEM / Memento | 分层记忆、链接、更新、衰减、冲突与上下文管理 | 建立 episodic→semantic→procedural 三层；支持 supersede、TTL、冲突惩罚 |
| Mem0（[arXiv:2504.19413](https://arxiv.org/abs/2504.19413)） | 动态抽取、巩固和检索；图记忆表达实体关系 | 借鉴抽取/巩固流程，但领域反馈只能先成为候选，不能自动覆盖人工事实 |
| LifelongAgentBench（[arXiv:2505.11942](https://arxiv.org/abs/2505.11942)） | 长期经验回放受无关信息和上下文限制影响 | 把 Memory precision、误导率和 Token 占用纳入正式评测；使用 group self-consistency 检查冲突 |
| ACL 2026 经验跟随研究（[论文](https://aclanthology.org/2026.acl-long.27/)） | 高相似输入会导致 Agent 强烈复用相似输出，错误经验可能传播 | 相似度不能作为唯一召回条件；必须有适用域、反例、后验成功率和“不要使用时机” |

适配结论：Memory 的价值不是“记得更多”，而是**在正确场景以最小 Token 召回正确的规则，并能证明没有误导**。

### 3.3 Prompt 优化与文本梯度

| 机制/代表工作 | 主要思想 | 对本项目的适配 |
| --- | --- | --- |
| OPRO（[arXiv:2309.03409](https://arxiv.org/abs/2309.03409)） | LLM 根据历史候选和分数迭代优化 Prompt | 作为离线候选生成器；输入必须包含失败残差和验收条件，不只给总分 |
| PromptBreeder（[arXiv:2309.16797](https://arxiv.org/abs/2309.16797)） | 用变异 Prompt 产生新的变异 Prompt，自反式进化 | 二期用于候选多样性；设置预算、停滞检测和最大代数 |
| PromptWizard（[arXiv:2405.18369](https://arxiv.org/abs/2405.18369)） | 反馈批评与综合同时优化指令和示例 | 适合 S6 五栏少量正/负例；必须在 holdout 回归后才可采用 |
| MIPROv2（[arXiv:2406.11695](https://arxiv.org/abs/2406.11695)） | 多阶段 LM 程序的模块指令、示例和跨模块 credit assignment | 将 S3/S4 作为耦合 Change Unit，避免只看局部平均分 |
| GEPA（[arXiv:2507.19457](https://arxiv.org/abs/2507.19457)） | 将轨迹文字反馈视为文本梯度，生成可解释更新并维护 Pareto 候选 | 首选的二期候选搜索思想；以质量、成本、时延、硬失败率维护 Pareto frontier |

适配结论：本项目应优化“最小可解释 Section Patch”，而不是每次生成完整 Prompt 文件；所有候选都要带假设、反例和验收条件。

### 3.4 多智能体/工作流级演化的边界

| 机制/代表工作 | 可借鉴点 | 本项目当前是否采用 |
| --- | --- | --- |
| AFlow（[arXiv:2410.10762](https://arxiv.org/abs/2410.10762)） | 把工作流视为可搜索图，用执行反馈优化 | 仅借鉴候选搜索与反馈记录；暂不改 S1–S6 拓扑 |
| EvoAgentX（[arXiv:2507.03616](https://arxiv.org/abs/2507.03616)） | 模块化的 evolving/evaluation 层，可组合多种优化器 | 可借鉴模块边界；Prompt/Memory 先行，工具和拓扑后置 |
| EvolveR（[arXiv:2510.16079](https://arxiv.org/abs/2510.16079)） | offline self-distillation→结构化原则→online 检索 | 适合把离线反馈编译成 semantic lesson，再在线只读检索 |
| FLEX（[arXiv:2511.06449](https://arxiv.org/abs/2511.06449)） | 无梯度连续经验库、成功/失败反思和经验继承 | 借鉴成功/失败双向更新与继承；加入领域人工审核门禁 |
| AgentEvolver（[arXiv:2511.10395](https://arxiv.org/abs/2511.10395)） | self-questioning、self-navigating、self-attributing | 借鉴主动生成评测 Query 和轨迹贡献归因；不让生产 Agent 自主扩张任务边界 |
| CORAL（[arXiv:2604.01658](https://arxiv.org/abs/2604.01658)） | 异步共进化、共享记忆、heartbeat、健康和资源管理 | 可借鉴异步演化服务、独立 evaluator、资源限额；生产 Prompt 仍隔离 |
| MMPO（[arXiv:2605.30159](https://arxiv.org/abs/2605.30159)） | 用 Belief Entropy 观察中间 Memory 退化，而非只看最终成功 | 在每个 S-step Packet 增加字段完整度/不确定性探针，提前发现摘要丢失 |
| TraceElephant（[arXiv:2604.22708](https://arxiv.org/abs/2604.22708)） | 完整执行轨迹显著改善多智能体失败归因 | 保存输入、检索证据、Prompt 片段、输出、工具和 critic 的哈希关联 |

明确不纳入首期：自动修改源码、模型权重/RL、自由 DAG 拓扑演化、未经验证的在线长期写入、单一 LLM Judge 直接发布。

## 4. 目标架构

### 4.1 三类不可混淆的输入

1. **Immutable contract**：角色、输入输出 Schema、证据边界、安全规则、候选身份冻结、阶段依赖。不可由自进化器修改。
2. **Mutable policy**：方法步骤、检查清单、反例、少量示例、Memory selector。只允许 section/module 级演化。
3. **Runtime context**：当前 Query、证据、上游 Packet、阶段预算。每次运行锁定快照，不写回 Prompt 文件。

### 4.2 演化服务的职责边界

| 组件 | 输入 | 输出 | 生产权限 |
| --- | --- | --- | --- |
| Trace Collector | S1–S6 调用、工具、Packet、critic | `TraceEvent`、哈希和耗时 | 只追加 |
| Feedback Normalizer | 专家评语、维度、评分 | `Feedback`、taxonomy、severity、confidence | 只追加 |
| Residual Miner | Trace、Judge、硬门禁 | `ResidualCard` | 只追加 |
| Lesson Compiler | Residual + 反馈 + 反例 | `Lesson` 候选 | 不可激活 |
| Prompt Challenger | Lesson + 当前 Bundle | section patch / candidate | 不可写生产 |
| Static Contract Checker | candidate | 检查结果 | 阻断非法候选 |
| Replay Evaluator | 固定数据集和两套 Bundle | 质量、成本、CI、硬失败 | 不可发布 |
| Reviewer | 评测证据、diff、风险 | approve/reject | 人工权限 |
| Canary Controller | approved candidate | shadow/canary 结果 | 可回滚 |
| Promotion Ledger | canary 结果 | champion pointer、effect status | 原子切换 |

## 5. 统一数据契约

### 5.1 Feedback

```json
{
  "feedback_id": "feedback-...",
  "run_id": "run-...",
  "profile_id": "legacy_v1",
  "stage_scope": ["S4", "S6"],
  "route": "traditional_gap",
  "taxonomy": ["evidence_binding", "unsupported_precision"],
  "severity": "high",
  "confidence": 0.9,
  "raw_comment_ref": "run-local://expert_feedback/feedback-...",
  "learning_signal": "把指标、验证方法和证据边界绑定到同一能力链。",
  "source_run_ids": ["run-..."],
  "status": "pending_validation",
  "effect_status": "pending_validation",
  "created_at": "2026-09-13T00:00:00Z"
}
```

原始专家评语保留在任务审计文件；未来 Agent 只接收有界的 `learning_signal` 或已验证 Lesson，不直接注入完整 transcript。

### 5.2 Lesson / Memory

```json
{
  "memory_id": "lesson-...",
  "layer": "semantic",
  "stage_scope": ["S4", "S6"],
  "route": "traditional_gap",
  "trigger": "出现能力指标但没有验证条件",
  "lesson": "将任务、功能、性能、体系接口、验证方法写成闭合链。",
  "anti_pattern": "不要用公开参数直接推断未公开的作战效果。",
  "when_not_to_use": "仅做概念发散且没有可验证指标时不强行套用。",
  "source_feedback_ids": ["feedback-..."],
  "source_run_ids": ["run-...", "run-..."],
  "confidence": 0.84,
  "utility_ema": 0.12,
  "retrieval_count": 8,
  "adoption_count": 5,
  "misleading_count": 0,
  "ttl_days": 90,
  "status": "candidate"
}
```

建议分层：

- `working`：当前步骤短期 critic，随任务结束失效。
- `episodic`：一次运行的轨迹、失败样例和证据快照。
- `semantic`：至少两个独立 Run 或专家确认后形成的规则。
- `procedural`：阶段 checklist、Prompt fragment、验证套路。
- `negative`：已验证的失败模式，带适用条件和反例。

只有 `validated`/`active` 的 semantic、procedural、negative 条目可以进入线上检索；旧记录没有状态时按 `pending_validation` 处理。

### 5.3 PromptCandidate / EvolutionCycle

```json
{
  "cycle_id": "cycle-...",
  "hypothesis": "在 S4 的能力—指标—验证链增加显式闭合检查，可降低 unsupported_precision。",
  "parent_bundle_hash": "sha256:...",
  "change_units": ["common:s3_s4.creative_contract"],
  "section_patches": [
    {
      "section_id": "s4.capability_validation_checklist",
      "old_hash": "sha256:...",
      "new_text": "...",
      "rationale": "...",
      "counterexamples": ["..."],
      "acceptance_tests": ["每条性能结论必须有验证方式"]
    }
  ],
  "impacted_stages": ["S4", "S6"],
  "static_checks": {"schema": "pass", "protected_sections": "pass"},
  "replay_refs": ["evaluation-..."],
  "review_status": "pending_review",
  "canary_status": "not_started"
}
```

一个 Cycle 只解决一个可证伪假设，最多三个 Change Unit；S3/S4 视为耦合单元，不能只优化其中一个而不做联动评测。

### 5.4 Evaluation 与 RetrievalEvent

每次正式比较必须锁定：

```text
query_hash
evidence_snapshot_hash
upstream_packet_hash
seed
model_profile
prompt_bundle_hash
memory_snapshot_hash
```

Memory 采用事件级归因：

```json
{
  "retrieval_event_id": "retrieval-...",
  "run_id": "run-...",
  "stage": "S6",
  "memory_id": "lesson-...",
  "selected": true,
  "applied": true,
  "adopted": true,
  "contradicted": false,
  "outcome": "improved",
  "quality_delta": 0.06,
  "token_cost": 182
}
```

## 6. Memory 检索与治理

### 6.1 检索顺序

```text
Stage / Profile / Route / 作用域硬过滤
→ BM25（可选向量召回）
→ confidence × utility × recency × stage_fit
→ 冲突惩罚 + 负例覆盖 + MMR 多样性
→ top-k 与 Token budget 截断
→ 输出 lesson、anti-pattern、when-not-to-use 和来源摘要
```

不要只按语义相似度召回；相似但不适用的旧案例是错误传播的主要来源之一。

### 6.2 晋级与衰减

- 单条人类反馈：`candidate`，不直接成为长期规则。
- 两个独立 Run 同方向、固定回放改善且无硬失败：可进入 `validated`。
- 通过人工审核和至少一次 Shadow：进入 `active`。
- 连续误导、冲突或过期：`quarantined`/`retired`，保留审计记录。
- `utility_ema` 按采用后的目标阶段质量变化更新；未采用不等于失败，误导必须单独计数。
- TTL 只影响召回权重，不删除原始证据；重新验证可恢复。
- 同一事实发生冲突时，保留两条来源，使用 `supersedes`/`contradicts` 关系，不静默覆盖。

### 6.3 防止 Memory poisoning

1. 专家原文与派生摘要分离，派生条目标注 `derived`。
2. 反馈、Lesson、Prompt Patch 均有来源 Run 和 hash。
3. 检索输出有界，不注入完整历史对话。
4. 线上 Agent 无法写入 semantic/procedural 层。
5. 发现证据边界、身份冻结、安全契约冲突时立即 quarantine。

## 7. Prompt 演化设计

### 7.1 可变与保护区域

建议建立 `section_dependency_manifest`（可先作为 JSON/YAML 文件，后续再接代码）：

| 类型 | 示例 | 策略 |
| --- | --- | --- |
| protected | 角色职责、输出 Schema、证据边界、安全规则、候选身份冻结 | 禁止自动修改 |
| coupled | `common:s3_s4.creative_contract`、S3/S4 联动规则 | 必须成对回放 |
| leaf-mutable | 阶段 checklist、反例、少量示例、检索 selector | 允许最小 patch |
| runtime-only | Query、证据、上游 Packet、预算 | 不落盘为 Prompt 版本 |

`common.md` 含大量跨调用点 section；即使文件名相同，也不能把整个文件视为一个可变单元。每个 patch 必须记录 `section_id`、`old_hash`、`new_hash`、影响阶段和依赖关系。

### 7.2 Candidate 生成约束

Codex CLI 只负责生成候选，不直接写生产目录。输入包含：

- 一个明确假设和目标 taxonomy；
- 当前 immutable contract 摘要；
- 失败 Trace 的最小脱敏片段；
- 正例、负例和验收条件；
- 目标 section 的当前 hash；
- Token、成本、时延预算。

输出只允许结构化 JSON：`hypothesis`、`section_patches`、`counterexamples`、`acceptance_tests`、`expected_tradeoffs`。静态检查失败的候选不得进入回放。

### 7.3 不应使用的优化方式

- 让 Codex 返回完整 S1–S6 Prompt 并直接覆盖文件。
- 以一次专家评分或单一 Judge 的总分作为发布依据。
- 只优化 S6 最终文案，不检查上游 Packet 和候选身份来源。
- 通过增加长篇规则解决所有问题，忽略 Token、延迟和规则冲突。
- 让线上运行把临时反思直接写进共享长期 Memory。

## 8. S1–S6 问题分类与指标

| 阶段 | 一级问题分类 | 关键质量指标 | 典型可演化文本单元 |
| --- | --- | --- | --- |
| S1 | `opponent_model_gap`、`evidence_boundary`、`adaptation_relation` | 对手体系矛盾覆盖、证据边界正确率、装备泄漏率 | 对手约束 checklist、反适应反例 |
| S2 | `mission_timing_gap`、`resource_exchange_gap` | 任务时序、资源交换、效应窗口、与 S1 独立性 | 时序模板、资源/授权检查 |
| S3 | `weapon_concreteness`、`novelty`、`json_contract` | 候选独立性、武器本体闭合、创新机理、直接战果、JSON 合规 | 候选生成规则、拒绝例、少量高质量示例 |
| S4 | `mechanism_feasibility`、`interface_gap` | 任务→功能→性能→体系接口→验证闭合 | 能力映射 checklist、验证反例 |
| S5 | `duplicate_selection`、`portfolio_diversity` | retain/merge/reject 一致性、去重、组合多样性、优先级 | 组合决策规则、冲突处理片段 |
| S6 | `identity_freeze`、`causal_chain`、`technical_boundary`、`template_repetition` | 五栏完整性、候选身份冻结、因果链、跨栏一致性、证据边界、模板重复率 | 五栏检查、压缩策略、正负例 |
| 跨阶段 | `evidence_binding`、`semantic_consistency`、`unsupported_precision`、`overlong` | 全链路质量、硬失败率、Token、p95 延迟、成本 | shared lesson、handoff contract 的叶子片段 |

评测必须同时看阶段局部指标和全链路指标，禁止用局部改善掩盖下游回退。

## 9. 评测闭环与发布门禁

### 9.1 数据集分层

- `train/dev`：允许用于生成候选和调参。
- `pilot`：允许人工审查、Shadow 和小比例 Canary。
- `holdout`：只用于确认候选泛化。
- `test`：只做正式报告，不得反哺 Prompt、Memory 或阈值。

Query 按难度、路线、阶段触发类型和领域分层；首个 MVP 至少准备 12 个 pilot 样例，并覆盖 S1–S6 与跨阶段问题，不以单一简单 Query 代表全链路。

### 9.2 Champion–Challenger paired replay

对每个 Query 固定 Query、证据、上游结果、模型配置和 seed；随机化 A/B 展示顺序；Judge 看不到系统身份。至少执行：

1. Champion vs Challenger 全链路比较。
2. 目标阶段局部 counterfactual replay。
3. Prompt-only、Memory-only、Both 三臂消融；资源允许时增加 `neither` 基线。
4. 负例和硬门禁回归。
5. 成本、Token、p95 延迟和重试次数比较。

### 9.3 建议门槛

默认门槛可作为初始配置，需用 pilot 数据校准：

- 目标质量提升的 bootstrap CI 下界 ≥ `+0.03`；
- 非目标阶段回退 ≤ `0.02`；
- Schema、证据越界、候选身份、安全硬失败为 `0`；
- Token、成本、p95 延迟增幅 ≤ `15%`；
- Judge 分歧超过阈值时标记 `inconclusive`，不得自动发布；
- Memory 误导率不得高于当前 Champion，且采用率不能靠强制注入制造；
- 至少两个独立 Run 支持同一 Lesson，或由领域专家明确确认。

门槛应记录在 Evaluation manifest，不要散落在 UI 或 Prompt 文本中。

### 9.4 归因

完整归因链：

```text
feedback → residual → prompt section / memory
→ S-step claims → capability card → final report section
```

使用 leave-one-unit-out、缓存回放或 counterfactual 评估单个 Prompt/Memory 单元；不能把 S6 的改善简单归因于 S6，因为上游 S3–S5 的 Claim 可能已改变。

### 9.5 S1–S6 的效率优化原则

效率优化不能以减少必要证据或跳过质量门为代价。建议使用“残差驱动预算”：

```text
expected_gain = residual_severity × stage_fit × uncertainty
priority = expected_gain / (estimated_tokens + estimated_latency)
```

实际执行时：

- S1/S2：优先复用同一证据快照和时间线索引，只为新残差补查，不重复抓取已验证材料。
- S3：开放创新席位有界并行；先做静态本体/身份/JSON 检查，再把预算给通过者，避免把完整回放浪费在明显不合格候选上。
- S4：只对进入候选池的装备执行深度能力—指标—接口—验证映射；相同上游 Packet 使用缓存，不因不同 Prompt 重跑检索。
- S5：先增量去重和冲突检测，再做组合排序；未改变的候选不重复评分。
- S6：先检查五栏缺口和证据边界，再做定向修复；不为格式润色重新生成整张画像。
- 跨阶段：阶段依赖不变时可并行评测；共享 section 或上游 Packet 变化时自动扩大影响面，不能用局部缓存掩盖依赖回归。

每个阶段应有 `max_tokens`、`max_calls`、`max_seconds`、`early_stop_reason` 和 `cache_hit` 观测。连续两轮无新证据、质量增益低于 `0.03` 或重复同一 Residual 时停止扩张并记录原因。这样可以同时提升吞吐、成本可解释性和质量稳定性。

## 10. Codex CLI 执行隔离

每个 Challenger 通过独立 Codex CLI 回合运行：

1. 输入只读 manifest、脱敏 Trace、目标 section 和 schema。
2. 工作目录是评测专用临时目录，禁止读取或写入生产 Prompt 目录。
3. 输出必须是 JSON candidate；解析失败、越权路径或缺少 hash 直接拒绝。
4. 生成阶段不调用线上 S1–S6；回放阶段由固定 harness 调用。
5. 所有候选、日志和结果写入 `outputs/evals/<evaluation_id>/` 或对应运行的知识目录。
6. 发布只更新一个原子 Bundle pointer，失败时回到上一个 Champion。

这样可以让“生成候选”和“决定是否采用”由不同回合、不同权限和不同证据链承担，降低 Prompt injection、Judge hacking 和误发布风险。

## 11. 分阶段实施路线

### P0：观测与路径治理（先做）

目标：不改变线上行为，先能回答“这次运行用了什么、哪里失败”。

- 在每次 S1–S6 调用记录 `prompt_bundle_hash`、`prompt_section_ids`、`memory_snapshot_hash`、`memory_ids`。
- 扩展 Trace，保存输入 Packet、检索证据、输出、critic、工具调用、耗时和 Token 的 hash 关联。
- 把 `processed` 与 `effect_status=pending_validation` 分离。
- 所有代码和文档中的项目资源使用相对路径；运行时由项目根目录推导，环境变量只作为覆盖入口。
- 验收：同一 Run 可重建 Prompt/Memory 快照；运行目录迁移后无需修改代码。

建议涉及：`src/equipment_deep_research/expert_feedback.py`、`src/equipment_deep_research/orchestration/runner.py`、`evals/models.py`、`evals/web_api.py`。

### P1：离线 Replay 与消融

目标：先评估，不自动发布。

- 增加固定 `evals/fixtures/s1_s6_evolution_pilot.jsonl`，按难度、路线、阶段分层。
- 复用 `evals/pairwise.py`、`evals/judging.py`、`evals/aggregate.py` 构建 paired replay。
- 支持 Prompt-only、Memory-only、Both 三臂和硬门禁统计。
- 验收：能输出质量 delta、置信区间、硬失败、Token、成本和 p95 延迟。

### P2：Lesson 生命周期与检索评测

目标：让 Memory 可验证、可衰减、可归因。

- 新增 `taxonomy`、`severity`、`confidence`、`profile_id`、`effect_status`、`utility_ema`、TTL 和冲突关系。
- `load_feedback_knowledge()` 默认只返回 `validated/active`；旧记录按 pending 处理。
- 写入 `RetrievalEvent`，计算 precision、adoption、utility、misleading、conflict 和 stale 指标。
- 验收：单条错误经验不会直接进入长期线上上下文；可撤回并追踪受影响 Run。

### P3：Section Patch、Shadow、Canary 与原子回滚

目标：把现有整段 Prompt 提案升级为可控实验。

- 建立 section dependency manifest，保护 Schema/角色/安全段。
- `prompt_evolution.py` 记录 `EvolutionCycle` ledger，不再把审核等同于有效。
- 先 static check + replay，再人工 review；批准后先 Shadow，再 10% Canary。
- 原子切换 Bundle pointer，任一硬门禁或显著回退立即 rollback。

### P4：多候选搜索与主动学习

目标：在数据和归因稳定后提高搜索效率。

- 借鉴 GEPA 的 Pareto 候选、MIPRO 的模块/示例优化、PromptBreeder 的受控多样性。
- 借鉴 AgentEvolver 的主动生成 Query 和轨迹贡献奖励。
- 只在实验环境评估 workflow/topology 变异；生产 S1–S6 拓扑仍需单独审批。

## 12. 风险与控制

| 风险 | 表现 | 控制 |
| --- | --- | --- |
| Memory poisoning | 错误反馈长期传播 | 候选层、来源链、双 Run、人工审核、quarantine |
| Prompt drift | 规则越来越长、互相冲突 | section patch、Token budget、冲突图、TTL、停滞检测 |
| Judge hacking | 只优化评测措辞或格式 | 多 Judge、硬门禁、holdout、随机顺序、人工抽样 |
| 错误归因 | 把下游问题归给错误阶段 | 完整 Trace、LOAO、counterfactual、Claim adoption 链 |
| 过度个性化 | 只对某条 Query 变好 | 分层 pilot、holdout、跨路线回归 |
| 并发写损坏 | 多进程丢失 Ledger/Memory 更新 | 原子写、版本 hash、进程间锁或单写入队列 |
| 成本失控 | 反思/回放调用过多 | 每 Cycle 预算、缓存回放、早停和最大候选数 |

## 13. 完成定义（Definition of Done）

自进化模块达到可投入生产的最低标准时，应能回答以下问题：

1. 哪条专家反馈触发了哪个 Residual？
2. 哪个 Prompt section 或 Memory 被改变，旧/新 hash 是什么？
3. 候选在相同 Query、证据、模型和 seed 下是否优于 Champion？
4. 改善来自 Prompt、Memory，还是二者交互？
5. S1–S6 哪个阶段真正产生了可被下游采用的 Claim？
6. 成本、Token、延迟和非目标阶段是否退化？
7. 谁审核、何时 Canary、何时晋级，如何一键回滚？
8. 运行目录迁移到另一台机器后，所有 Prompt/反馈/评测路径是否仍可解析？

如果其中任一问题无法由 Ledger 和 Trace 回答，该候选只能保持 `pending_validation`，不能称为“自进化成功”。

## 14. 研究参考资料

- Reflexion: [arXiv:2303.11366](https://arxiv.org/abs/2303.11366)
- Self-Refine: [arXiv:2303.17651](https://arxiv.org/abs/2303.17651)
- Voyager: [arXiv:2305.16291](https://arxiv.org/abs/2305.16291)
- ExpeL: [arXiv:2308.10144](https://arxiv.org/abs/2308.10144)
- OPRO: [arXiv:2309.03409](https://arxiv.org/abs/2309.03409)
- PromptBreeder: [arXiv:2309.16797](https://arxiv.org/abs/2309.16797)
- PromptWizard: [arXiv:2405.18369](https://arxiv.org/abs/2405.18369)
- MIPRO: [arXiv:2406.11695](https://arxiv.org/abs/2406.11695)
- AFlow: [arXiv:2410.10762](https://arxiv.org/abs/2410.10762)
- Mem0: [arXiv:2504.19413](https://arxiv.org/abs/2504.19413)
- LifelongAgentBench: [arXiv:2505.11942](https://arxiv.org/abs/2505.11942)
- EvoAgentX: [arXiv:2507.03616](https://arxiv.org/abs/2507.03616)
- GEPA: [arXiv:2507.19457](https://arxiv.org/abs/2507.19457)
- ELL: [arXiv:2508.19005](https://arxiv.org/abs/2508.19005)
- EvolveR: [arXiv:2510.16079](https://arxiv.org/abs/2510.16079)
- FLEX: [arXiv:2511.06449](https://arxiv.org/abs/2511.06449)
- AgentEvolver: [arXiv:2511.10395](https://arxiv.org/abs/2511.10395)
- TraceElephant: [arXiv:2604.22708](https://arxiv.org/abs/2604.22708)
- CORAL: [arXiv:2604.01658](https://arxiv.org/abs/2604.01658)
- MMPO: [arXiv:2605.30159](https://arxiv.org/abs/2605.30159)
- How Memory Management Impacts LLM Agents: [ACL Anthology](https://aclanthology.org/2026.acl-long.27/)

企业工程模式的官方资料：

- [OpenFeature](https://openfeature.dev/docs/reference/intro/)
- [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- [MLflow Model Registry](https://mlflow.org/docs/latest/ml/model-registry/)
- [Open Policy Agent](https://www.openpolicyagent.org/docs/latest/)
- [OpenLineage](https://openlineage.io/docs/)

## 15. 企业级多用户交付设计

### 15.1 租户与策略层级

将“谁能看到/修改/使用什么经验”作为一等数据属性，而不是靠调用方约定。推荐四层作用域：

```text
平台安全契约（Platform Contract）
        ↓
组织/租户基线（Tenant Baseline）
        ↓
工作区/项目策略（Workspace Policy）
        ↓
单次运行上下文（Run Context）
```

合并规则是从上到下只允许收窄约束：下层可以增加更严格的检查、预算和领域 Lesson，但不能放宽平台安全契约，也不能静默覆盖上层事实。每一层均使用不可变版本号和 hash；运行时只解析一份已经冻结的 `EffectiveBundle`。

所有演化实体至少包含以下字段：

```json
{
  "tenant_id": "tenant-...",
  "workspace_id": "workspace-...",
  "project_id": "project-...",
  "visibility": "private|workspace|tenant|platform",
  "owner_id": "user-...",
  "created_by": "user-...",
  "approved_by": ["user-..."],
  "data_classification": "internal|confidential|restricted",
  "retention_policy": "90d"
}
```

默认可见性为 `private` 或 `workspace`；跨工作区、跨租户提升可见性必须经过脱敏、管理员批准和审计。不同租户的原始专家评语、工具输出、Query、候选名称和运行 Trace 不得在检索层混合。

### 15.2 RBAC 与职责分离

推荐最小角色集合：

| 角色 | 可做 | 不可做 |
| --- | --- | --- |
| `operator` | 启动回放、查看本租户运行状态 | 发布/回滚、读取其他租户原文 |
| `domain_reviewer` | 标注问题、审核领域 Lesson 和质量证据 | 修改平台契约、单独发布高风险 Prompt |
| `prompt_engineer` | 生成/修改 Challenger、查看脱敏 Trace | 单独批准自己的候选 |
| `tenant_admin` | 批准租户策略、配置配额、发起 Canary/回滚 | 修改平台安全契约 |
| `platform_admin` | 管理全局基线、保护 section、审计和紧急回滚 | 绕过不可变审计 |
| `auditor` | 只读查看 Ledger、评测和审批链 | 修改任何演化对象 |
| `service_account` | 按最小权限执行固定服务动作 | 读取 UI 会话和跨租户数据 |

高风险变更（protected/coupled section、证据边界、身份规则、跨租户共享）必须满足双人审批或 quorum；提案作者与最终批准人不能是同一主体。紧急回滚可由平台管理员执行，但必须在事后补齐原因和复核。

当前 API 的 `X-Role`/`X-User-ID` 仅能视为开发阶段兼容输入，不能作为企业身份边界。E1 交付应改为 OIDC/JWT 服务端校验，把主体、租户、工作区、权限和会话过期时间从可信身份提供方注入请求上下文；客户端传入的角色字段不能提升权限。

### 15.3 多专家反馈的原子化与共识

企业多用户场景不能把多条自由评论直接拼接后让 LLM “总结多数意见”。应先把每条评语编译为可独立投票和验证的 `FeedbackClaim`：

```json
{
  "claim_id": "feedback-claim-...",
  "proposition": "S6 技术实现必须区分公开证据与推演结论",
  "polarity": "support|oppose|revise",
  "scope": "workspace",
  "target_stages": ["S4", "S6"],
  "artifact_ref": "capability-card-...",
  "evidence_refs": ["claim-..."],
  "expected_behavior": "每个未公开参数标注验证方式或不确定性",
  "anti_pattern": "把估计参数写成已验证事实",
  "acceptance_test": "unsupported_precision=0",
  "actor_role": "domain_reviewer",
  "trust_tier": "verified_domain_expert",
  "severity": "high",
  "confidence": 0.9,
  "temporal_validity": {"from": "2026-09-13", "to": null},
  "applicable_routes": ["traditional_gap"],
  "conflict_group_id": "conflict-...",
  "consensus_status": "open"
}
```

冲突按性质处理：

- 安全、Schema、候选身份和证据边界冲突：硬阻断并升级人工裁决。
- 事实冲突：按证据、时间和 route 拆分适用条件，不做无条件平均。
- 标量评分：可使用加权中位数或 trimmed mean，降低极端票影响。
- A/B 偏好：可用 Bradley–Terry/Thurstone 聚合；噪声标注可评估 Dawid–Skene/MACE，但模型输出只是辅助证据。
- 风格/业务偏好：保留租户分支或 Pareto 候选，不强制形成平台统一 Prompt。
- 少数意见：必须保留原始票据与理由，不能被共识摘要覆盖。

专家权重只用于冲突排序，不代表绝对真值。可综合角色权限、领域资质、历史校准、任务相关性和时效性；同时公开 `consensus_method`、`vote_set`、`adjudicator_id` 和少数意见。建议监控 Krippendorff's alpha / Fleiss' kappa、共识率、未解决冲突数、少数意见保留率和 claim→effective lesson 转化率。

### 15.4 数据隔离与隐私

- 存储键必须以 `tenant_id/workspace_id` 分区，服务端再次校验资源归属；不能仅依赖 UI 过滤。
- Trace 进入 Challenger 前先脱敏：去除凭证、个人信息、未授权 Query、内部 URL 和不应跨域的候选身份。
- 原始反馈与派生 Lesson 分开存储；派生内容保留 `source_hash`，不能反向伪装成人工事实。
- 共享平台基线只接收经过批准的匿名化 Lesson，不接收完整 Transcript 或租户私有 Prompt。
- 支持租户级删除/导出/保留策略；删除派生 Lesson 时保留合规审计所需的不可逆 hash 和删除事件。
- 加密传输、静态加密、密钥轮换和备份恢复由部署层提供；自进化模块至少记录加密/密钥配置版本。

### 15.5 并发、一致性与租户公平性

文件版原型可继续用于单机，但企业部署必须迁移到支持事务和条件更新的存储（例如 PostgreSQL 或等价服务），而不是让多个 Worker 直接改同一 JSON 文件。最低要求：

1. `EvolutionCycle`、Bundle、Lesson、Review、Canary 是 append-only 事件或带版本的实体。
2. 发布使用 compare-and-swap：只有 `parent_bundle_hash` 仍为当前 Champion 时才允许切换。
3. 失败重试使用 idempotency key，不重复生成或重复扣配额。
4. Ledger、Memory 和审计事件采用 outbox/队列保证跨服务最终一致。
5. 每租户有独立并发、Token、回放、存储和 Canary 配额；调度器使用加权公平队列，避免大租户饿死小租户。
6. 评测任务和线上请求隔离资源池，回放峰值不能拖慢生产 S1–S6。

## 16. 面向服务的 API 与事件契约

### 16.1 推荐的生命周期 API

首期可以继续兼容现有端点；企业版建议增加明确的资源边界：

```text
POST   /api/v1/tenants/{tenant_id}/evolution/cycles
GET    /api/v1/tenants/{tenant_id}/evolution/cycles/{cycle_id}
POST   /api/v1/tenants/{tenant_id}/evolution/cycles/{cycle_id}/evaluate
POST   /api/v1/tenants/{tenant_id}/evolution/cycles/{cycle_id}/reviews
POST   /api/v1/tenants/{tenant_id}/evolution/cycles/{cycle_id}/shadow
POST   /api/v1/tenants/{tenant_id}/evolution/cycles/{cycle_id}/canary
POST   /api/v1/tenants/{tenant_id}/evolution/cycles/{cycle_id}/promote
POST   /api/v1/tenants/{tenant_id}/evolution/cycles/{cycle_id}/rollback
GET    /api/v1/tenants/{tenant_id}/evolution/audit
GET    /api/v1/tenants/{tenant_id}/evolution/metrics
```

所有写操作要求 `Idempotency-Key`、操作者身份和 `expected_parent_hash`；服务端返回 `cycle_id`、当前状态、下一步所需权限和评测引用。旧的 `/api/v1/prompt-evolution/*` 端点作为兼容 facade，内部转换为同一 Cycle/Bundle Ledger，避免产生两套事实源。

### 16.2 事件流

可采用本地 outbox 起步，事件名保持稳定：

```text
feedback.normalized
residual.created
lesson.candidate.created
prompt.candidate.generated
candidate.static_checked
candidate.replay_completed
review.approved / review.rejected
bundle.shadow_started / bundle.canary_started
bundle.promoted / bundle.quarantined / bundle.rolled_back
memory.retrieved / memory.adopted / memory.misleading
```

事件载荷必须包含 `event_id`、`occurred_at`、`tenant_id`、`workspace_id`、`actor_type`、`trace_id`、`entity_id`、`entity_version` 和相关 hash；消费者按 `event_id` 幂等处理。

## 17. 企业级可观测性、SLO 与成本治理

### 17.1 指标分层

| 层级 | 关键指标 | 告警示例 |
| --- | --- | --- |
| 运行健康 | S1–S6 成功率、重试率、p50/p95 延迟、队列等待、Codex CLI 错误 | p95 超预算、某阶段连续失败 |
| 质量 | 各阶段 rubric、全链路盲评、硬失败、证据越界、身份漂移 | 硬失败 > 0 或质量 CI 下界回退 |
| Memory | retrieval precision、adoption、utility EMA、misleading、conflict、stale、Token 占用 | 误导率上升、冲突集中爆发 |
| 演化 | Cycle lead time、候选通过率、回滚率、重复假设率、停滞代数 | 连续候选无提升、频繁回滚 |
| 企业运营 | 每租户用量、配额命中、成本、审计延迟、数据保留 | 单租户异常消耗或审计缺失 |

### 17.2 建议 SLO（初始值）

- 线上请求不因演化服务不可用而失败：演化服务降级为上一份有效 Bundle。
- Bundle 解析/加载成功率 ≥ 99.99%，解析失败自动回退上一 Champion。
- 审计事件写入成功率 ≥ 99.9%；写入失败时阻断发布而不是静默放行。
- Canary 结果在约定窗口内可查询；超时状态为 `inconclusive`，不自动晋级。
- 每租户 Token/成本预算有硬上限，评测工作池与生产工作池隔离。

SLO 不应通过降低硬质量门禁来达成；宁可暂停演化或回退，也不能用无证据的候选维持吞吐。

### 17.3 成本效率策略

1. 先用缓存的上游 Packet 做局部回放，只有必要时再跑全链路。
2. 对同一 `query_hash + evidence_hash + prompt_bundle_hash + memory_hash` 去重。
3. 使用小模型/低成本 Judge 做初筛，边界样本和发布前样本使用高质量多 Judge；初筛不能绕过硬门禁。
4. 每个 Cycle 设置最大候选数、最大代数、最大 Token 和停滞早停。
5. 评测结果按 tenant/workspace 计费归属，避免共享缓存导致成本无法解释。

### 17.4 灰度策略与错误预算

Prompt Bundle 与 Memory Policy 使用独立的 deterministic feature flag，避免二者同时切换后无法归因。推荐每个租户按稳定 cohort 逐级推进：

```text
shadow → 1% → 5% → 25% → 50% → 100%
```

每一级必须满足最小样本量和观察窗口；禁止把不同租户的总体 uplift 混在一起掩盖某个租户的退化。任一阶段出现 Schema/安全/证据/身份硬失败、质量置信区间回退、p95 或成本越界时触发 stage kill switch 和自动回滚。

为质量、可靠性、延迟和成本分别设置错误预算。错误预算耗尽时冻结该租户的 Prompt/Memory 演化，只允许稳定性修复与回滚，不继续消耗生产流量试验新候选。

## 18. 企业交付验收矩阵

| 验收域 | 必须证明 | 证据 |
| --- | --- | --- |
| 功能 | 反馈→Residual→Candidate→Replay→Review→Canary→Promote/Rollback 可闭环 | Cycle Ledger、API 测试 |
| 质量 | 目标质量提升、非目标不回退、硬失败为零 | paired replay、bootstrap CI、消融报告 |
| 归因 | 能区分 Prompt-only、Memory-only 和交互贡献 | Trace、RetrievalEvent、LOAO/counterfactual |
| 安全 | protected section、Schema、证据边界、身份冻结不可被候选改写 | 静态检查和恶意候选测试 |
| 隔离 | 租户/工作区数据和 Prompt 不串读、不串写 | RBAC、越权、脱敏和并发测试 |
| 可回滚 | 任意 Canary 失败可恢复上一 Champion，运行继续服务 | 故障演练、CAS、Bundle pointer 记录 |
| 可运维 | 有 SLO、配额、告警、审计、备份和恢复说明 | 运维手册、指标面板、审计抽样 |
| 可迁移 | 换机器/容器/项目目录后相对路径仍有效 | clean checkout + relocation smoke |

### 18.1 发布前最小测试集

```text
静态：schema / protected section / path traversal / prompt injection
数据：租户越权 / 脱敏 / 过期 Memory / 冲突 Memory
评测：paired replay / 三臂消融 / holdout / 多 Judge 分歧
可靠性：重复提交 / 并发发布 / Worker 重启 / 存储暂时不可用
回滚：Canary 失败 / Bundle hash 冲突 / 旧版本恢复 / 审计完整性
```

## 19. 面向企业交付的推荐落地顺序

### 版本 E0：单租户、文件存储、只读线上

交付目标是可解释和不误发布：P0 埋点、相对路径、effect status、固定 pilot、基础 paired replay。文件 Ledger 只允许单写入进程，线上只读有效 Bundle。

### 版本 E1：组织内多工作区

增加 tenant/workspace 字段、RBAC、双人审核、配额、脱敏、审计和 Shadow。旧 API 通过 facade 进入统一 Cycle Ledger。

### 版本 E2：企业生产

迁移事务存储与 outbox，加入 CAS 原子发布、10% Canary、自动回滚、SLO/告警、备份恢复和租户级成本归属。通过完整验收矩阵后才允许 active Memory 自动参与线上检索。

### 版本 E3：规模化自进化

在数据量和归因稳定后再启用 GEPA Pareto、MIPRO 模块搜索、主动学习、跨工作区匿名 Lesson 贡献和实验性 workflow 演化。任何跨租户共享或拓扑变化仍需要更高等级审批。

## 20. 可借鉴的企业工程范式

这些系统不等同于本项目的技术依赖，但其职责划分适合企业化设计：

| 工程范式 | 可借鉴能力 | 在本项目中的映射 |
| --- | --- | --- |
| LangSmith / Braintrust / Humanloop | Prompt registry、Dataset、Evaluator、Experiment、人工 review | 将 Prompt/Memory 候选、固定数据集和评测证据放入统一 Cycle |
| [MLflow Model Registry](https://mlflow.org/docs/latest/ml/model-registry/) | immutable artifact、alias/champion、promotion/rollback | PromptBundle 作为发布工件，Champion pointer 原子切换 |
| [OpenFeature](https://openfeature.dev/docs/reference/intro/) / LaunchDarkly | 确定性 cohort、逐级 rollout、kill switch | tenant/workspace/route/stage 级 Shadow 与 Canary |
| [OpenTelemetry GenAI conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) | provider/model/token/latency/tool 的统一 Trace | S1–S6、Codex CLI、Judge 和检索事件使用统一 trace/correlation ID |
| [W3C PROV](https://www.w3.org/TR/prov-overview/) / [OpenLineage](https://openlineage.io/docs/) | 产物、运行、输入、派生关系的 lineage | Prompt→Run→S-step Claim→反馈→评测→发布/回滚 |
| [OPA](https://www.openpolicyagent.org/docs/latest/) + PostgreSQL RLS + Kubernetes namespace | 策略门禁、行级安全、运行隔离 | protected section、租户数据 ACL、评测/生产资源池隔离 |
| SLSA / in-toto / WORM audit | 工件来源、审批证明、不可抵赖日志 | Bundle hash、审批链、评测证明和追加写审计 |

采用这些思想时应保持产品中立：先定义稳定的 Bundle、Cycle、Trace、Review 和 Audit 契约，再选择具体基础设施，避免将自进化逻辑绑定到单一供应商。

## 21. 项目内参考实现的可迁移经验

仓库中已有的参考实现也能帮助降低落地风险：

- `reference/nanobot-main/docs/memory.md` 采用 session 短期记忆、append-only `history.jsonl` 和定时 Dream/consolidation，再通过 GitStore 做版本与恢复。可迁移为“反馈先记事件，批量编译 Lesson，按 diff/restore 发布”。
- `reference/OpenOPC-main/opc/layer5_memory/memory_manager.py` 与 `employee_evolution.py` 展示了 global/project/session 多层作用域、成功/部分成功/失败计数和达到阈值后学习技能。可迁移为“按租户/工作区隔离，重复验证后才晋级 playbook”。
- `reference/GenericAgent-main/memory/memory_management_sop.md` 强调 `Action-Verified Only` 和 `No Execution, No Memory`，并把原始会话与任务 SOP 分层。可迁移为“没有成功工具结果、独立评测或专家确认的猜测，不能写入 semantic/procedural Memory”。

这些本地参考与 GEPA、ExpeL、MIPRO 等研究的共同启示是：**记忆的默认动作是追加、验证、链接和衰减，而不是覆盖；Prompt 的默认动作是生成 Challenger，而不是改写 Champion。**

## 22. 最小企业数据表（从文件版迁移时使用）

进入 E1/E2 时可以将以下逻辑实体映射到事务数据库；字段名保持稳定，底层可按部署规模拆表或分区：

| 实体 | 核心字段 |
| --- | --- |
| `tenant` | `tenant_id`, `policy_id`, `retention`, `data_classification` |
| `prompt_bundle` | `bundle_id`, `scope_type/id`, `parent_id`, `stage_sections`, `protected_hash`, `content_hash`, `status`, `created_by`, `approved_by` |
| `memory_item` | `memory_id`, `scope`, `layer`, `claim`, `provenance`, `trust`, `validity_from/to`, `conflict_group`, `status`, `supersedes` |
| `feedback_claim` | `claim_id`, `feedback_id`, `proposition`, `polarity`, `artifact_ref`, `evidence_refs`, `consensus_status` |
| `feedback_vote` | `claim_id`, `voter_role`, `weight_snapshot`, `vote`, `rationale` |
| `evolution_eval` | `eval_id`, `bundle_id`, `dataset_snapshot`, `baseline_id`, `metrics`, `ci`, `cost`, `latency`, `verdict` |
| `rollout` | `rollout_id`, `bundle_id`, `cohort_rule`, `percent`, `kill_switch`, `rollback_reason` |
| `audit_event` | `event_id`, `tenant_id`, `actor`, `action`, `object/version`, `hashes`, `correlation_id`, `timestamp`, `retention/legal_hold` |

文件版 `outputs/knowledge/*.json` 可以作为 E0 的只读兼容层；迁移时先双写/校验，再切换读取指针，禁止一次性删除历史审计数据。
