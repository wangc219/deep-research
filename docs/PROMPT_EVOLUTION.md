# S1–S6 提示词演化运行规范

完整的调研、Memory 设计、评测门禁和企业级实施路线见
[`docs/SELF_EVOLUTION_RESEARCH_AND_ROADMAP.md`](SELF_EVOLUTION_RESEARCH_AND_ROADMAP.md)。本文档保留当前 API 的兼容说明，并规定迁移到新流程时的治理边界。

## 1. 当前兼容流程

当前 API 仍支持以下人工审核流程：

1. `POST /api/v1/prompt-evolution/proposals` 生成 `pending_review` 候选，默认目标为 S3、S4、S5、S6。
2. `GET /api/v1/prompt-evolution/proposals` 查看反馈、修改前和修改后内容。
3. `POST /api/v1/prompt-evolution/proposals/{proposal_id}/review` 提交 `approved` 或 `rejected`。
4. 批准后更新对应 Markdown 的 `system` 段，并在 `src/equipment_deep_research/agents/prompts/dynamic_winning/versions/Sx/vNNNN.md` 保存快照。
5. 运行记录默认写入 `outputs/knowledge/prompt-evolution.json`；批准或回退后清理 Worker 的提示词缓存。

版本可通过 `GET /api/v1/prompt-evolution/versions?stage=S6` 查看，并通过 `POST /api/v1/prompt-evolution/versions/S6/v0003/rollback` 回退。审核和回退接口仍需要开发者/管理员角色及审核密码。

带有 `tenant_id`、`workspace_id`、`project_id`、`profile_id`、`route` 或
`stage_scope` 的候选属于 scoped proposal。普通审核可以记录
`approved + publish_status=deferred_scoped`，但不会写入共享的动态 Prompt；只有
平台管理员同时携带 `X-Evolution-Cross-Scope=true` 才能显式重试发布。scoped
版本回退同样需要该授权。这样可以保留租户内实验审计，又避免一个租户改写其他
租户正在使用的共享 Markdown。

这条兼容流程解决了“未经人工确认不能直接覆盖生产文件”，但**人工批准不等于候选已被验证有效**。在新治理流程完成前，所有现有提案都应视为候选实验记录。

## 2. 目标流程：Replay-first

```text
反馈 / Trace / Residual
    → taxonomy + hypothesis
    → section-level PromptCandidate
    → 静态契约检查
    → paired replay + 局部消融
    → 多人审核
    → shadow / canary
    → promote 或 rollback
```

`review` 未来只允许通过静态检查和离线回放的候选；没有评测引用时保持 `pending_validation`，不能直接发布。

### 2.1 Candidate 最小契约

每个候选必须带 `cycle_id`、可证伪 `hypothesis`、目标 taxonomy、`parent_bundle_hash`，以及 `section_patches[]`。每个 patch 至少包含 `section_id`、`old_hash`、`new_text`、修改理由、反例和验收条件，并记录 `impacted_stages`、依赖关系、静态检查、评测引用和成本/时延预估。

单个 Cycle 只验证一个假设，最多三个 Change Unit。S3/S4 的共享创意与能力边界视为耦合单元，必须联动回放；不能只因 S6 最终文字变好就判定 S6 Prompt 有效。

### 2.2 可修改与保护区域

| 区域 | 示例 | 规则 |
| --- | --- | --- |
| protected | 角色职责、输出 Schema、证据边界、安全规则、候选身份冻结、阶段依赖 | 自动演化禁止修改 |
| coupled | `common:s3_s4.creative_contract`、S3/S4 联动规则 | 成对评测 |
| leaf-mutable | checklist、反例、少量示例、Memory selector | 允许最小 section patch |
| runtime-only | Query、证据、上游 Packet、预算 | 不写入 Prompt 版本 |

`common.md` 和 S6 文件包含多个带标记的 section；文件级 `system` 替换仅作为兼容回退，长期方案应使用 section dependency manifest。所有候选必须记录影响阶段和 hash，防止共享片段引起隐性回归。

## 3. 企业级多用户治理

演化对象必须带 `tenant_id`、`workspace_id`、`visibility` 和 `owner_id`。默认策略是：

- 组织级 baseline 由管理员发布；团队/工作区只能派生 challenger，不得覆盖其他租户；
- 专家原文、Run Trace 和候选 Memory 默认租户内可见，跨租户复用必须显式脱敏并经管理员批准；
- 评审采用双人或 quorum 规则，提案作者不能单独批准；高风险 patch 需要领域专家 + 平台管理员；
- 每次读取/注入/发布/回滚都写入不可变审计事件，记录 actor、理由、旧新 hash、IP/请求 ID（如可用）；
- 每租户设置并发、Token、Codex CLI 调用、回放和 Canary 配额；超额自动排队或降级，不影响其他租户；
- 生产请求只读取租户有效 Bundle 和有效 Memory，禁止把另一租户的反馈拼接进 Prompt。

## 4. Prompt 与 Memory 的版本绑定

每次 S1–S6 调用应记录：

```text
tenant_id / workspace_id
prompt_bundle_hash / prompt_section_ids
memory_snapshot_hash / memory_ids
query_hash / evidence_snapshot_hash / upstream_packet_hash
model_profile / seed / trace_id
```

线上运行只读取不可变 Prompt Bundle 和 `validated/active` Memory。运行中的临时反思属于 working/episodic memory，任务结束后不会自动升级为长期规则。

## 5. 评测与发布门禁

候选必须在相同 Query、证据、上游 Packet、模型和 seed 下与 Champion 成对回放，随机化 A/B 顺序并隐藏系统身份。至少执行全链路比较、目标阶段 counterfactual、Prompt-only/Memory-only/Both 三臂消融、硬门禁回归以及 Token/成本/p95 延迟比较。

默认晋级门槛：目标质量提升的 bootstrap CI 下界 ≥ `+0.03`，非目标阶段回退 ≤ `0.02`，Schema/证据/身份/安全硬失败为 `0`，Token/成本/p95 增幅 ≤ `15%`。Judge 分歧过大时标记 `inconclusive`，不自动发布。企业租户可收紧门槛，但不能放宽硬失败门禁。

## 6. 状态语义

```text
Feedback: queued → normalized → routed → candidate
Lesson: candidate → replay_pending → provisional/validated → active
PromptCandidate: draft → static_failed/replay_failed → pending_review
                → shadow → canary → champion/quarantined
```

`processed` 只表示反馈已压缩或路由；`applied` 只表示实际注入；`validated` 表示固定回放通过；`effective` 表示灰度/线上有净收益。任何状态都必须保留来源反馈、Run、Prompt/Memory hash 和审核记录。

## 7. Codex CLI 隔离规则

Codex CLI 只生成结构化候选，不直接写入生产 Prompt 目录：

- 使用评测专用临时工作目录和独立输入快照；
- 禁止读取未授权的生产运行上下文；
- 只返回 JSON；路径越权、缺少 hash、缺少反例或不符合 Schema 时拒绝；
- 生成、评测、审核使用分离权限；
- 候选产物写入 `outputs/evals/<evaluation_id>/`，生产只通过原子 Bundle pointer 切换；
- 任一硬门禁失败立即 quarantine 或 rollback。

## 8. 迁移顺序

1. **P0**：保留现有 API，补齐 `effect_status=pending_validation`、Prompt/Memory snapshot ID 和 Trace 埋点。
2. **P1**：增加固定 pilot、paired replay、三臂消融；`review` 前强制检查评测引用。
3. **P2**：把完整 Prompt 提案改成 section patch，新增依赖清单和原子 Bundle。
4. **P3**：加入 Shadow/10% Canary、utility/TTL/冲突管理、租户配额和自动回滚。
5. **P4**：再考虑 GEPA Pareto 候选、MIPRO 模块优化、主动学习和实验性拓扑搜索。

在 P2 以前，旧的整段 `system` 版本接口应标记为 legacy，并禁止把其“批准”解释为“已证明有效”。
