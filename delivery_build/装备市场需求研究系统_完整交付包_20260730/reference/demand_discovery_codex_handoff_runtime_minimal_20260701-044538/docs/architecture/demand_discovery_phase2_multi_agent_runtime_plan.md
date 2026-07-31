# Demand Discovery Phase 2: Multi-Agent Runtime Implementation Plan

日期：2026-06-11

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**定位：** 本文是 `demand_discovery_long_run_evolution_plan.md` Phase 2 的细粒度实施计划，对应里程碑门禁 M-LR2。在演进计划的 4 个 Task 之外，新增 **P2.5（候选状态机、registry 视图与报告骨架）**，以补齐 `demand_discovery_module_discussion.md` 第 9/12 节共识的实现覆盖。

**Goal:** 把空壳 scheduler 变成真实多 agent 运行时：orchestrator 模型通过 `spawn_worker` 工具派发并发 worker；三角色 prompt 与审核量表落库；候选状态流与报告骨架可被程序校验。

**Architecture:** worker = 进程内独立 `DiscoveryHarness` 实例（独立 session JSONL、独立 ContextPack、角色裁剪工具集、独立预算、共享 DomainStore/DomainTraceStore）。不引入子进程、不引入消息队列中间件；并发由单事件循环 + 信号量管理。

**Tech Stack:** Python standard library（`asyncio.Semaphore`、`dataclasses`）。agent 定义 frontmatter 用自实现的扁平解析器（约 30 行），不引入 PyYAML（YAML 依赖留给 Phase 3 配置文件）。

**参考实现总表：**

| 参考 | 借鉴点 | 对应 Task |
|---|---|---|
| Anthropic 多 agent 研究系统工程博客（2025-06） | orchestrator-worker 拓扑；worker 回传"压缩后发现"而非原文；task brief 必含 objective / 输出格式 / 工具指引 / effort 预算；"按问题复杂度伸缩投入"写进 orchestrator prompt | P2.1 / P2.3 |
| `reference/pi/packages/coding-agent/examples/extensions/subagent/index.ts` | 三种调用模式（single/parallel/chain + `{previous}` 占位）；parallel 上限 8 任务 4 并发；回传截断（50KB）而 details 保全量；abort 传播终止全部子任务 | P2.2 |
| `reference/pi/packages/coding-agent/examples/extensions/subagent/agents.ts` + agents/*.md | markdown + frontmatter 的 agent 定义与目录发现；每次调用重新读取（运行中可调优） | P2.2 |
| Claude Code subagents（`.claude/agents/*.md`：name/description/tools/model） | frontmatter 字段集；description 用于路由（写给"调度者"看）；工具子集即权限边界 | P2.2 / P2.3 |
| Claude Code Task 工具 | "一条消息并发多个 Task 调用"的并发形态；子 agent 结果作为 tool result 回父上下文 | P2.2 |
| OpenAI Agents SDK（`Runner`、agents-as-tools、tracing spans） | run 循环返回结构化 `RunResult`；agent 封装为工具暴露给上级；span 按 run 层级关联——对应 WorkerReport 与事件 correlation | P2.1 / P2.4 |
| `reference/pi/packages/coding-agent/src/core/event-bus.ts` | 单 bus 多订阅、按类型过滤、事件即数据（无行为耦合） | P2.4 |
| Manus context engineering 博客 | recitation（把任务清单/进度反复写回可见文件）防长任务目标漂移——progress 快照设计 | P2.4 |
| `reference/GenericAgent-main/memory/subagent.md` | "input 只给目标与约束、禁写步骤"（subagent 同等智能原则）；主 agent 监察纪律 | P2.3 |
| GPT Researcher（`assafelovic/gpt-researcher`）report publisher | 结构化报告骨架 + 引用/来源追踪自动拼装，正文与来源审计分离 | P2.5 |

---

## 1. Scope

| Task | 交付物 | 依赖 |
|---|---|---|
| P2.1 | `WorkerRuntime` + 实化 `DiscoveryScheduler` + `WorkerReport` 提取 | Phase 1 全部 |
| P2.2 | markdown agent 定义 + `spawn_worker` 工具（single/parallel/chain） | P2.1 |
| P2.3 | orchestrator/reader/auditor(+debater) prompt + `audit_rubric.yaml` 接线 | P2.2 |
| P2.4 | `EventBus` 收口 + `--watch` 进度 + progress 快照 | P2.1 |
| P2.5 | 候选状态机 + registry 视图 + 报告骨架渲染 | 无（可最先做） |

完成判定（M-LR2）：orchestrator 模型通过 `spawn_worker` 派发 ≥2 个并发 worker，进度摘要回传，全程 fake provider 离线测试通过；三角色 prompt 与审核量表落库；非法状态流转被程序拒绝。

---

## 2. Task P2.5: 候选状态机、registry 视图与报告骨架

> 排序说明：本任务无依赖且被 P2.3 的 prompt 引用（状态流定义、报告骨架），故先行。

**Files:**

- Create: `src/knowledgegraph/demand_discovery/domain/state_machine.py`
- Create: `src/knowledgegraph/demand_discovery/domain/report.py`
- Modify: `src/knowledgegraph/demand_discovery/domain/store.py`
- Modify: `src/knowledgegraph/demand_discovery/domain/tools.py`
- Test: `tests/test_demand_discovery_state_machine.py`
- Test: `tests/test_demand_discovery_report_skeleton.py`

### 设计要点

**状态机**（状态集合来自讨论文档第 12 节，逐字采用）：

```python
STATUSES = {"raw_signal", "researchable_signal", "weak_signal", "discarded_signal",
            "candidate_demand", "demand_report", "human_reviewed"}

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "raw_signal": {"researchable_signal", "weak_signal", "discarded_signal", "candidate_demand"},
    "researchable_signal": {"candidate_demand", "weak_signal", "discarded_signal"},
    "weak_signal": {"researchable_signal", "discarded_signal"},        # 复查升级
    "candidate_demand": {"demand_report", "researchable_signal", "weak_signal",
                          "discarded_signal"},                          # 审核降级/回退
    "demand_report": {"human_reviewed", "candidate_demand"},           # 驳回回炉
    "discarded_signal": set(),  # 默认终态；复活仅经人工触发，走专用 API 并留 trace
    "human_reviewed": set(),
}
```

- `validate_transition(old, new) -> None | raise InvalidTransition`，纯函数。
- `DomainStore.upsert_candidate` 接线：候选已存在且 status 变化时调用校验；回退类流转（如 `demand_report → candidate_demand`）额外要求本批 trace proposal 中存在 `candidate_status_rolled_back` 事件（沿用既有 domain/trace 配对校验机制，扩展 `_expected_trace` 表）。
- `create_or_update_candidate.status` 的工具参数 schema 必须以 JSON Schema `enum` 暴露同一组 `STATUSES`，使 provider 在工具选择时能看到状态机硬约束。prompt 约束不能作为唯一防线；工具执行层仍保留常见自然语言别名（如 `proposed` → `candidate_demand`）的兼容归一，并对真正未知状态返回可恢复的 tool error，不允许未知状态进入 save point。
- 信源分级钩子：`DomainStore.__init__` 增加可选 `tier_status_cap: Callable[[str], str] | None`；非空时按候选挂的证据→来源最高 tier 限制可达状态（讨论文档 162-169 行规则）。Phase 3 P3.1 落地该函数后注入；本阶段默认 None（宽松），用 stub 函数测试钩子本身。

**Registry 视图**（不新增 Signal 实体，遵守讨论文档 §9"过程信号经既有对象 + 视图管理"决议）：

```python
class DomainStore:
    def list_signals(self, statuses: set[str] | None = None) -> list[CandidateDemand]: ...
    def watchlist_view(self) -> list[dict]: ...
    # weak_signal 候选 + 其最近一条 event_type=signal_parked 的 trace
    # （payload.recheck_conditions 记录复查条件），供 Phase 4 复查任务消费
```

`signal_parked` 进入 trace 事件类型白名单；复查条件存 trace payload，不污染 CandidateDemand schema（四核心对象字段不漂移的硬约束）。

**报告骨架**（讨论文档 §9：强约束骨架 + 弹性论证空间）：

`generate_demand_report` 工具参数从自由 `body: str` 升级为结构化 sections（兼容期保留 body 作为 fallback，标记 deprecated）：

```python
REQUIRED_SECTIONS = ["core_conclusion", "task_scenario", "threat_or_environment",
                     "capability_gap", "existing_solutions_and_residual_gaps",
                     "counter_evidence_and_limits", "risks_and_constraints",
                     "open_questions", "next_steps"]
# demand_type(显式/推断)、相关技术方向、方案线索为可选附属栏目
```

`domain/report.py::render_demand_report(store, report) -> str`：按骨架顺序渲染 markdown；**支撑证据与来源审计两节由程序从 store 自动拼装**（evidence claim + excerpt 引用 + SourceRecord 简化来源信息：名称/标题/时间/tier/位置），模型不手写引用——借鉴 GPT Researcher publisher 的"正文与 citation 分离拼装"，杜绝幻觉引用。工具校验：REQUIRED_SECTIONS 全部非空、`demand_type ∈ {explicit, inferred}`；方案线索类内容只能出现在附属栏目（程序只校验栏目存在性，内容判断留给 auditor）。

### Steps

- [ ] **Step 1: 写失败测试**：合法/非法流转矩阵抽样（全终态、回退需 trace 配对、discarded 不可复活）；tier cap stub 注入后 C 级证据候选无法进入 `demand_report`；watchlist_view 返回 parked 条件；报告缺必填节被拒；渲染输出含自动拼装的证据与来源审计节、引用 id 与 store 一致。
- [ ] **Step 2: 实现 state_machine.py（纯函数）+ store 接线 + `_expected_trace` 扩展。**
- [ ] **Step 3: 实现 report.py 渲染器与工具参数升级**（demo 的 fake responses 同步改为 sections 形式）。
- [ ] **Step 4: Run** 全量测试 → PASS。

---

## 3. Task P2.1: scheduler 实化——worker 即子 harness

**Files:**

- Rewrite: `src/knowledgegraph/demand_discovery/harness/scheduler.py`
- Create: `src/knowledgegraph/demand_discovery/harness/worker_report.py`
- Modify: `src/knowledgegraph/demand_discovery/harness/agent_harness.py`（构造参数已在 P1 收口，此处仅核对）
- Test: `tests/test_demand_discovery_scheduler.py`（重写为行为级）

### 设计要点

```python
@dataclass
class WorkerSpec:
    role: str                 # agent 定义名（P2.2 起从 markdown 解析）
    task_brief: str
    tools: list[str]          # 工具名子集
    budget: RunBudget
    context_pack: ContextPack

class DiscoveryScheduler:
    def __init__(self, run_id: str, *, provider_factory: Callable[[WorkerSpec], Any],
                 tool_registry_factory: Callable[[WorkerSpec], list[ToolDefinition]],
                 domain_store: DomainStore, trace_store: DomainTraceStore,
                 sessions_dir: Path, cancel_token: CancelToken,
                 max_concurrency: int = 4) -> None: ...
    async def spawn_worker(self, spec: WorkerSpec, parent_event_id: str = "") -> str: ...
    async def run_until_idle(self) -> list[WorkerReport]: ...
    async def run_workers(self, specs: list[WorkerSpec]) -> list[WorkerReport]: ...
    async def cancel_worker(self, agent_run_id: str) -> None: ...
    def list_worker_states(self) -> list[WorkerState]: ...
```

- **隔离**：每 worker 一个 `DiscoveryHarness`（session 路径 `sessions_dir / f"{agent_run_id}.jsonl"`，token 从 scheduler 的 `cancel_token.derive()` 派生——父 abort 级联全部 worker，P1.1 语义）。**共享**：`domain_store` / `trace_store` 直接传引用；单事件循环内 save point flush 天然串行，无需锁（该不变式写入模块 docstring；若未来引入多进程则升级 SQLite，决策点已在复用分析 7.2 节预留）。
- **并发**：`asyncio.Semaphore(max_concurrency)`；单 worker 异常 → `WorkerReport(status="failed", error=...)`，不拖垮批次（对齐 pi subagent 的失败诊断回传）。
- **WorkerReport**（字段集 = 讨论文档 14.6 进度接口，逐字段实现）：

```python
@dataclass
class WorkerReport:
    agent_run_id: str; role: str; status: str       # completed | failed | cancelled
    partial_findings: list[str]                      # 来自 worker 最终 assistant 文本的要点行
    new_evidence_cards: list[str]                    # flush 前后 store diff 提取 id
    new_registry_entries: list[str]
    candidate_updates: list[str]
    open_questions: list[str]
    need_more_sources: bool
    risk_or_conflict: list[str]
    usage: dict                                      # 预算消耗摘要
    session_path: str
    error: str = ""
    def to_digest(self, limit_chars: int = 2000) -> str: ...  # 回传父模型的压缩摘要
```

提取实现在 `worker_report.py`：`new_*` 三项由 spawn 前后 store 快照 diff 机械提取（不信任模型自报）；`partial_findings`/`open_questions`/`risk_or_conflict` 从最终 assistant 消息的轻量结构约定解析（worker prompt 要求结尾输出固定小节，解析失败则整段截断塞入 partial_findings——容错优先）。

- **查重**：spawn 前对 `task_brief` 调用临时的标题规范化比对（接口 `dedup_check(brief) -> str | None` 预留，Phase 4 P4.3 替换实现），命中返回已有 agent_run_id 并发 `worker_dedup_skipped` 事件。

### Steps

- [ ] **Step 1: 写失败测试**：2 个 reader 并发（各自 fake provider 队列），session 文件隔离、store 写入全部过 save point 校验、报告 diff 提取正确；`max_concurrency=1` 退化为串行（用完成时间戳断言）；`cancel_worker` 仅终止目标；父 token cancel 级联全部；单 worker 抛错批次完整返回且 failed 报告含 error。
- [ ] **Step 2: 实现 scheduler 与 worker_report。**
- [ ] **Step 3: 事件关联测试**：所有 worker 事件含 `run_id`/`agent_run_id`/`parent_event_id`。
- [ ] **Step 4: Run** 全量测试 → PASS。

---

## 4. Task P2.2: spawn_worker 工具与 markdown agent 定义

**Files:**

- Create: `src/knowledgegraph/demand_discovery/workers/agent_defs.py`
- Create: `src/knowledgegraph/demand_discovery/workers/agents/reader.md`
- Create: `src/knowledgegraph/demand_discovery/workers/agents/auditor.md`
- Create: `src/knowledgegraph/demand_discovery/domain/orchestration_tools.py`
- Test: `tests/test_demand_discovery_agent_defs.py`
- Test: `tests/test_demand_discovery_spawn_worker_tool.py`

### 设计要点

**agent 定义**（形态对齐 Claude Code `.claude/agents/*.md` 与 pi subagent `agents/*.md`）：

```markdown
---
name: reader
description: 围绕给定调研问题做检索式阅读并产出证据卡
tools: search_sources, fetch_page, read_document, extract_summary, create_source_record, create_evidence_card
model: default
budget: {"max_tokens": 60000, "max_tool_calls": 40}
---
（system prompt 正文，P2.3 撰写）
```

frontmatter 解析器自实现（`agent_defs.py`，约 30 行）：仅支持扁平 `key: value`，`tools` 按逗号切分，`budget` 值为内联 JSON——**不引入 YAML 依赖**，格式约束写入模块 docstring。`discover_agents(dir) -> dict[str, AgentDef]` 每次 spawn 时重新调用（运行中可编辑调优，pi 同款行为）；解析失败的文件跳过并告警，不炸全局。工具名此时允许引用 Phase 3 未落地的名字（注册时缺失的工具自动从 active 集剔除并在 details 标注，保证两轨道并行不互锁）。

**spawn_worker 工具**（注册给 orchestrator，`execution_mode="sequential"`）：

```python
# 参数 schema（自实现 JSON-schema 子集无 oneOf，三模式互斥在 execute 内校验）：
# single:   {"agent": "reader", "task": "..."}
# parallel: {"tasks": [{"agent": ..., "task": ...}, ...]}   # ≤8 任务，并发 4
# chain:    {"chain": [{"agent": ..., "task": "...{previous}..."}, ...]}
```

- 执行：构造 `WorkerSpec`（预算取 agent 定义，task_brief = task 文本）交 scheduler；chain 模式逐步执行，`{previous}` 替换为上一步 `to_digest()`，任一步失败即停并报告步号（pi 行为）。
- 返回四通道：`content` = 各 WorkerReport 的 `to_digest()` 拼接（单任务 ≤2KB，对齐 pi"截断回传、details 保全量"）；`details` = 完整报告列表 + session 路径；`domain_proposals`/`trace_proposals` 为空——worker 的领域写入已经其自身 save point 落库，spawn 工具不重复提案（此边界写入工具 docstring 与测试）。
- abort：执行期间父 harness abort → scheduler 级联 → 工具返回 cancelled 状态的报告集。

### Steps

- [ ] **Step 1: 写失败测试**：frontmatter 解析（含 budget JSON、坏文件跳过、缺失工具剔除）；single/parallel/chain 三模式 fake 剧本；`{previous}` 注入内容正确；>8 任务被拒；互斥参数被拒；content 截断而 details 全量；父 abort 全员 cancelled。
- [ ] **Step 2: 实现 agent_defs 与 orchestration_tools。**
- [ ] **Step 3: Run** 两个新测试模块 + 全量 → PASS。

---

## 5. Task P2.3: 角色 prompt 工程与审核量表

**Files:**

- Create: `src/knowledgegraph/demand_discovery/workers/agents/orchestrator.md`
- Create: `src/knowledgegraph/demand_discovery/workers/agents/debater.md`（可选角色）
- Rewrite: `src/knowledgegraph/demand_discovery/workers/prompts.py`（改为资源加载 + 模板变量注入）
- Create: `configs/demand_discovery/audit_rubric.yaml`
- Modify: `src/knowledgegraph/demand_discovery/domain/tools.py`（run_audit 接量表）
- Test: `tests/test_demand_discovery_prompts.py`
- Test: `tests/test_demand_discovery_audit_rubric.py`

### 设计要点

**prompt 是本任务的工作量主体。** 撰写时逐节对照讨论文档，每份 prompt 头部注释标注对应章节号，便于后续同步修订。骨架要求：

- `orchestrator.md`：职责 = 制定研究计划 → 派发 reader（含 task brief 规范）→ 汇总 WorkerReport → 自行 synthesis（创建/更新候选，承担一期 synthesizer 职责）→ 判断补证/拆分/触发 debate/送审 → 生成报告。必含内容：
  - task brief 四要素（objective / 期望输出格式 / 工具与信源指引 / 预算），来自 Anthropic 多 agent 博客的 delegation 教训；
  - "按问题复杂度伸缩 worker 数量与深度"的显式指引（同上）；
  - 升级门禁六问（讨论文档 §11 832-839 行）与需求陈述七要素（§4 93-101 行）；
  - debate 触发规则（§12 935-941 行：推断需求/技术牵引/高新颖低证据/证据冲突/方案争议/高优报告）；
  - 状态流定义与各状态进入条件（P2.5 状态机的自然语言版）；
  - GA subagent SOP 的"给目标不给步骤"派发纪律与空闲监察纪律。
- `reader.md`：检索式阅读工作流（§6 388-403 行逐步骤展开）+ 递进式阅读四层与全文触发信号（§5）+ 停止条件按 claim 定义（§5 259-266 行）+ 结尾固定输出小节（findings / open_questions / need_more_sources / risks，供 WorkerReport 解析）。
- `auditor.md`：按量表逐项输出 `结论（通过/存疑/不通过）+ 理由 + 建议`；一票否决单列；粒度判断（过泛/过碎/重复/上下位，§12 994-1001 行）；只挂载读候选/读证据/写审核报告工具。
- `debater.md`（可选角色，挂 spawn 可用列表但 orchestrator 按触发规则使用）：职责限定 §12 924-932 行（找反证、查方案残余、指证据断点、提补证问题），输出 `debate_summary`，**不输出通过/不通过**；debate_summary 经 `record_debate` 小工具写 trace（event_type=`debate_completed`）。

**审核量表**（`audit_rubric.yaml`，PyYAML 在 Phase 3 引入前先用 JSON 同构文件 `audit_rubric.json`，P3.1 引入 yaml 后迁移——避免本阶段加依赖）：

```json
{"version": 1,
 "veto_items": [
   {"id": "no_traceable_source", "question": "是否无可回溯来源？"},
   {"id": "d_tier_only", "question": "是否仅由 D 级信源支撑？"},
   {"id": "no_scenario", "question": "是否无法落到任何任务/应用场景？"},
   {"id": "solution_slogan_only", "question": "是否纯方案/技术口号而无缺口表达？"},
   {"id": "out_of_safety_boundary", "question": "是否超出公开资料与安全边界？"}],
 "check_items": [
   {"id": "scenario_clear", "question": "场景是否明确？"},
   {"id": "gap_clear", "question": "能力缺口或新能力空间是否明确？"},
   {"id": "evidence_traceable", "question": "证据是否可回溯原文？"},
   {"id": "not_mere_trend", "question": "是否只是普通趋势？"},
   {"id": "not_mere_hotspot", "question": "是否只是技术热点？"},
   {"id": "residual_gap_checked", "question": "已有方案是否仍存残余缺口？"},
   {"id": "min_evidence_met", "question": "是否满足最低证据要求（至少一条非 C 级支撑核心 claim）？"}]}
```

`run_audit` 接线：scorecard 必须覆盖全部 item id，每项值为 `{"verdict": "pass|doubt|fail", "reason": str}`；任一 veto 项 `fail` → conclusion 强制 `rejected`；缺项 → 工具报错。量表加载提供 `load_rubric(path)`，路径可配置（测试注入精简量表）。默认治理路径为 `build_domain_tools(store)` 加载 `configs/demand_discovery/audit_rubric.json` 并把必填 scorecard item 写入工具 schema；只有低层测试或受控兼容路径可显式传 `rubric=None` 关闭量表。

**prompts.py 重构**：角色正文以 agents/*.md 为唯一事实源；`prompts.py` 只保留程序使用的模板（WRAP_UP_PROMPT、COMPACTION_PROMPT、task brief 骨架）与变量注入函数 `render_system_prompt(agent_def, run_context)`（注入信源白名单摘要、关键词门禁表、当日日期——白名单未落地前注入占位说明）。

### Steps

- [ ] **Step 1: 写量表测试**：加载、缺项拒绝、veto 强制 rejected、注入精简量表可替换。
- [ ] **Step 2: 撰写四份 prompt**，每份完成后对照检查表自查（检查表 = 上述"必含内容"列表，落在测试中以关键句存在性断言粗校验——防止后续编辑误删关键纪律）。
- [ ] **Step 3: fake 剧本测试**：auditor 调用 `create_or_update_candidate` 被工具子集 + before_tool_call 双重阻断；debate_summary 写 trace。
- [ ] **Step 4: Run** 全量测试 → PASS。

---

## 6. Task P2.4: EventBus 收口与进度可观测

**Files:**

- Create: `src/knowledgegraph/demand_discovery/harness/event_bus.py`
- Modify: `src/knowledgegraph/demand_discovery/harness/agent_harness.py`
- Modify: `src/knowledgegraph/demand_discovery/harness/scheduler.py`
- Modify: `scripts/demand_discovery_demo.py`（`--watch`）
- Test: `tests/test_demand_discovery_event_bus.py`

### 设计要点

```python
@dataclass
class RuntimeEvent:
    category: str        # provider_stream | agent_runtime | harness | scheduler
    event_type: str
    run_id: str; agent_run_id: str = ""; parent_event_id: str = ""
    payload: dict = field(default_factory=dict)
    timestamp: int = 0

class EventBus:
    def publish(self, event: RuntimeEvent) -> None: ...
    def subscribe(self, handler, *, categories=None, run_id=None) -> Callable[[], None]: ...
    # 返回退订函数；handler 同步调用、异常吞掉并计数（观测平面不得影响主流程，
    # 对齐 pi observability "hook 是控制平面、listener 是被动平面"原则）
```

- harness `_broadcast` 与 scheduler `self.events` 改为同一 bus 适配（既有 `subscribe(handler)` 公开接口保持兼容，内部桥接）。
- **脱敏不变式提升到 bus 层**：publish 前经 `redact(payload)`（剥 api_key/authorization/headers/超长文本字段截断），并以测试锁定（沿用既有 demo 的 no-secret 断言模式）。
- `--watch`：订阅 bus，渲染 worker 状态行（`⏳ reader agent-xx fetching… / ✓ auditor done / 预算余量`）。
- **progress 快照**（Manus recitation 思路）：每 save point 把 run 状态摘要重写到 `outputs/runs/{run_id}/progress.md`（任务 brief、worker 列表与状态、候选/证据计数、预算余量、最近事件 N 条）——同一份文件即 Phase 4 P4.2 的人工监察界面，本任务先落写入器 `ProgressWriter`。

### Steps

- [ ] **Step 1: 写失败测试**：过滤订阅、退订、listener 抛错不影响发布方、脱敏断言、progress.md 内容完整性。
- [ ] **Step 2: 实现 bus 与两端适配（旧接口兼容）。**
- [ ] **Step 3: 实现 ProgressWriter 与 --watch。**
- [ ] **Step 4: Run** 全量测试 → PASS。

---

## 7. 验收门禁（M-LR2）

- [ ] 全量离线测试 PASS。
- [ ] 端到端 fake 剧本：orchestrator（fake provider 剧本驱动）调用 `spawn_worker` parallel 派发 2 个 reader → 汇总 digest → 创建候选 → spawn auditor → run_audit（量表）→ generate_demand_report（骨架）→ 状态流 `raw_signal → candidate_demand → demand_report` 全程合法；该剧本固化为 `tests/test_demand_discovery_e2e_fake.py`，其完整事件流 JSONL 存入 `outputs/runs/` 作为阶段演进证据。
- [ ] `python scripts/demand_discovery_demo.py --mode fake --watch` 可见 worker 进度行与 progress.md。

## 8. Self-Review

- worker 用进程内 harness 而非子进程：放弃了硬隔离，换取共享 store 零序列化成本与单事件循环的无锁不变式；上下文隔离（独立 messages/session/context pack）已满足"防污染"目标（GA map 模式的核心诉求）。
- spawn 工具不产生 domain proposal 是关键边界：避免同一写入被父子两级 save point 重复提案。
- 一期收敛三角色 + 可选 debater：synthesizer 职责并入 orchestrator 是实施决策；Worker/AgentRun 抽象保证后续拆分零内核改动。
- frontmatter 自实现解析器是为零依赖；若 Phase 3 引入 PyYAML 后觉得受限，可平滑替换（格式向 YAML 兼容子集看齐）。
