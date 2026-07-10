# Demand Discovery Phase 4: Autonomy Loop Implementation Plan

日期：2026-06-11

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**定位：** 本文是 `demand_discovery_long_run_evolution_plan.md` Phase 4 的细粒度实施计划，对应里程碑门禁 M-LR4。在演进计划的任务之外，新增 **P4.4（人工审核记录与推送分级）** 与 **P4.6（分层留痕与清理）**，补齐讨论文档 §8/§12/§13 的实现覆盖。P4.5 的 baseline/gold 建设自 Phase 2 P2.3 完成后即可启动；可重复 replay 依赖 P3.4 与 M-LR3，不等待本阶段其余任务。

**Goal:** 形成完整自治闭环：定时扫描自主选题 → 长任务可人工监察纠偏 → 选题不重复 → 产出经人工审核分级落地 → 质量有评测基线。本阶段完成后，需求挖掘模块成为可无人值守运行的完整 agent。

**Architecture:** 常驻进程只有一个轻量 runner；所有 agent run 都是有界子任务（带预算与 CancelToken）。人工交互全部走文件系统（inbox / progress / review queue），不引入服务端与 UI——本地工作区即界面（讨论文档 §13 报告本地查看共识）。

**Tech Stack:** Python standard library + 既有依赖。无新增依赖。测试离线（注入 fake clock / fixture run）。

**参考实现总表：**

| 参考 | 借鉴点 | 对应 Task |
|---|---|---|
| `reference/GenericAgent-main/reflect/scheduler.py` + `memory/scheduled_task_sop.md` | 任务 JSON（schedule/repeat/enabled/max_delay_hours）+ 60s 轮询 + done 报告文件判重防重复执行 + health_check；"once 执行后永久冷却"语义 | P4.1 |
| APScheduler（对照后**拒绝引入**） | 完整 cron 库的能力边界确认：本项目仅需 daily/every_N/once，文件判重比持久 job store 更可审计 | P4.1 |
| `reference/GenericAgent-main/memory/subagent.md` 干预协议 | `_stop` / `_keyinfo` / `_intervene` 文件干预 → 映射到本项目 abort/steer/next_turn 队列；"主 agent 监察输出、禁止无脑 sleep"纪律 | P4.2 |
| Manus context engineering 博客 | recitation：进度文件反复重写对抗长任务目标漂移（progress.md 已在 P2.4 落地，本阶段闭环消费侧） | P4.2 |
| Claude Code（steering 队列 + 后台任务通知形态） | 运行中注入用户输入的交互范式；人工输入异步到达、save point 边界消费 | P4.2 |
| rank_bm25 / simhash（对照） | 相似度公式参考；本项目标题级查重选 bigram Jaccard + BM25 双信号，simhash 留作大库量替换点 | P4.3 |
| Anthropic 多 agent 研究系统博客 | "并行 worker 易重复劳动 → 共享 registry + 程序查重"的动机佐证 | P4.3 |
| GPT Researcher 等成熟 deep research 工具 | 作为 silver case 的 reference baseline（讨论文档 §10 763-770 行流程：多系统同题调研 → 本地规范化 → 人工审定） | P4.5 |
| 本仓库 `docs/benchmarks/route_discovery_benchmark_design.md` | 项目内 benchmark 文档的既有组织惯例（case 定义/指标/不存放已验证事实） | P4.5 |
| 讨论文档 §8（推送分级）§12（人工审核记录）§13（状态管理/敏感标记/分层保留） | 领域规则唯一事实源 | P4.4 / P4.6 |

---

## 1. Scope

| Task | 交付物 | 依赖 |
|---|---|---|
| P4.1 | 定时任务 runner + horizon scan 任务 + watchlist 复查任务 | M-LR3 |
| P4.2 | 文件 inbox 干预通道 + 监察闭环 | P2.4（EventBus/progress） |
| P4.3 | 程序化查重（dedup.py）替换临时实现 | P2.1；BM25 增强依赖 P3.4，可先用 bigram/Jaccard |
| P4.4 | 人工审核记录 + 报告状态管理 + 敏感标记 + 推送分级 | P2.5 |
| P4.5 | silver case 评测基座（**自 P2.3 后并行启动**） | baseline/gold 依赖 P2.3；replay 依赖 P3.4 与 M-LR3 |
| P4.6 | 分层留痕保留配置与清理脚本 | P4.1 |

完成判定（M-LR4）：定时扫描连续 ≥7 天无人值守运行，产出进 registry 且查重生效；人工经 inbox 完成一次在跑任务纠偏；首批 silver case 对照评测出分；人工审核流转一份报告至 approved 并产生推送清单。

---

## 2. Task P4.1: 定时任务 runner

**Files:**

- Create: `src/knowledgegraph/demand_discovery/harness/scheduled_runner.py`
- Create: `configs/demand_discovery/scheduled_tasks/horizon_scan_daily.json`
- Create: `configs/demand_discovery/scheduled_tasks/watchlist_recheck_weekly.json`
- Create: `scripts/demand_discovery_scheduler.py`
- Test: `tests/test_demand_discovery_scheduled_runner.py`

### 设计要点

**任务定义**（GA 格式直接沿用，字段语义逐项对齐 `scheduled_task_sop.md`）：

```json
{"task_name": "horizon_scan_daily",
 "schedule": "08:00", "repeat": "daily", "enabled": true,
 "max_delay_hours": 6,
 "task_brief": "对白名单 A/B 级 http 信源做一轮 horizon scanning：采集近 3 日新文章，分流登记 raw_signal/researchable_signal，对高分线索补一轮扩检。不生成正式报告。",
 "budget": {"max_tokens": 200000, "max_tool_calls": 120, "max_wall_clock_ms": 3600000},
 "source_filter": {"tiers": ["A", "B"], "transports": ["http"]}}
```

`repeat` 支持 `daily | weekday | weekly | once | every_Nh | every_Nd`（GA 全集裁掉 monthly，需要时再加）。

**Runner 循环**（`scheduled_runner.py`）：

```python
class ScheduledRunner:
    def __init__(self, tasks_dir, done_dir, run_factory, *,
                 clock: Callable[[], datetime] = now_local,
                 poll_interval_s: int = 60, single_flight: bool = True) -> None: ...
    async def run_forever(self) -> None: ...
    async def tick(self) -> list[str]: ...          # 单次轮询，测试入口
    def health_check(self) -> list[dict]: ...        # HEALTHY|OVERDUE|DISABLED|NEVER_RUN|ERROR
```

- 触发条件（与 GA 一致）：enabled + `clock() >= 当日 schedule` + 冷却已过（依据 `done_dir` 内 `YYYY-MM-DD_{task_name}.md` 最新时间戳）+ 未超 `max_delay_hours`。`once` 执行后写 done 即永久冷却。
- `run_factory(task) -> awaitable`：构造一次完整 orchestrator run（Phase 2 运行时 + 预算 + 独立 run_id `sched-{date}-{task_name}` + CancelToken 带 `max_wall_clock_ms` 超时派生）。run 结束（含失败/超时）后 runner 写 done 报告：run 摘要、候选/信号增量、预算消耗、progress.md 终态拷贝。**失败也写 done**（带 FAILED 标记）防当日反复重试风暴；`health_check` 暴露 ERROR 状态。
- `single_flight=True`：同一时刻至多一个 scheduled run（信源限速与浏览器约束的全局保护）。
- 崩溃恢复：runner 重启后凭 done 文件自然去重；被中断的 run 不自动续跑（horizon scan 幂等性弱，宁可下周期重扫——决策记录于 docstring；专题调研类任务可手动 `from_session` 续跑）。
- 日志：runner 自身事件（触发/跳过/错误）写 `outputs/scheduled/runner.log`（GA 同款）。

**watchlist 复查任务**：`run_factory` 对 `task_type: "watchlist_recheck"` 的任务走特化 brief 构造——程序先调 `DomainStore.watchlist_view()`（P2.5）取 parked 信号与复查条件，再扫描自上次复查以来新增 SourceRecord 与各条件的 keyword_gate 命中交集，仅将有新证据迹象的信号列入本次 brief（无命中则跳过本次 run 并在 done 报告注明）——对应讨论文档 1010 行"weak_signal 仅在新证据出现时复查"。

### Steps

- [ ] **Step 1: 写失败测试**（注入 fake clock）：到点触发/未到点不触发；冷却判重；max_delay 过期跳过；disabled/once 语义；失败写 FAILED done；single_flight 并发拒绝；health_check 五状态；watchlist 任务无新证据时跳过。
- [ ] **Step 2: 实现 runner 与 done 报告生成。**
- [ ] **Step 3: 实现两个任务定义与 run_factory 接线；`scripts/demand_discovery_scheduler.py`（前台运行，Ctrl+C 优雅退出=cancel 当前 run）。**
- [ ] **Step 4: Run** 测试 → PASS；本机挂机 24h 演练（fake provider 模式可先行），runner.log 与 done 报告存档。

---

## 3. Task P4.2: 文件 inbox 干预与监察闭环

**Files:**

- Create: `src/knowledgegraph/demand_discovery/harness/intervention.py`
- Modify: `scripts/demand_discovery_demo.py`、`scripts/demand_discovery_scheduler.py`
- Test: `tests/test_demand_discovery_intervention.py`

### 设计要点

```python
class FileInbox:
    def __init__(self, inbox_dir: Path) -> None: ...
    def poll(self) -> list[Intervention]: ...
    # 识别三类文件（GA 协议 → 本项目队列语义映射）：
    #   stop          -> harness.abort()            （P1.1 真中断）
    #   steer.md      -> harness.steer(正文)         （本轮纠偏）
    #   next_turn.md  -> harness.next_turn(正文)     （后续任务前置约束）
    # 消费后移入 inbox/processed/{timestamp}_{name}，并发 RuntimeEvent intervention_consumed
```

- **接线方式解耦**：harness 不感知文件系统。运行入口（demo / scheduler 的 run_factory）创建 `FileInbox` 并订阅 EventBus 的 `save_point` 事件，事件到达时 `poll()` 并调用对应 harness 方法——干预消费点天然落在 save point 边界（与队列注入语义一致，无竞态）。
- inbox 路径约定 `outputs/runs/{run_id}/inbox/`；progress.md（P2.4 已落）在同级，构成"看 progress → 写 inbox"的人工监察闭环。
- steer 文案模板与监察纪律写入 `docs/` 操作说明（runner 的 README 小节）：先读 progress 与最近 trace 再干预；干预正文给目标与约束、不给步骤（GA subagent SOP 原则）。
- 多 worker 场景：inbox 作用于 orchestrator（worker 由 orchestrator 经 spawn 工具间接管理）；run 级 stop 经 CancelToken 级联全部 worker（P1.1/P2.1 已保证）。

### Steps

- [ ] **Step 1: 写失败测试**：三类文件在 save point 被消费并触发对应行为（fake 慢工具制造多 save point 窗口）；processed 移动与事件留痕；空 inbox 零开销；非法文件忽略并告警。
- [ ] **Step 2: 实现 FileInbox 与入口接线。**
- [ ] **Step 3: Run** → PASS；人工演练一次"运行中 steer 纠偏"，产物（progress 前后 + processed 文件 + trace）存档。

---

## 4. Task P4.3: 程序化查重

**Files:**

- Create: `src/knowledgegraph/demand_discovery/domain/dedup.py`
- Modify: `src/knowledgegraph/demand_discovery/harness/scheduler.py`（替换 P2.1 临时 dedup_check）
- Modify: `src/knowledgegraph/demand_discovery/domain/tools.py`（create_or_update_candidate 接入）
- Test: `tests/test_demand_discovery_dedup.py`

### 设计要点

```python
def normalize_title(text: str) -> str: ...
# 全半角统一、去标点/空白、小写化英文；中文不分词

def similarity(a: str, b: str) -> float: ...
# 首版必须支持字符 bigram Jaccard；P3.4 完成后再接入 BM25 互检分

@dataclass
class DedupResult:
    near_duplicates: list[tuple[str, float]]   # ≥ NEAR_DUP_THRESHOLD (0.85)
    similar: list[tuple[str, float]]           # ≥ SIMILAR_THRESHOLD (0.60)

def check_candidate(store: DomainStore, title: str, statement: str) -> DedupResult: ...
# 比对维度：title×title 为主，statement×statement 加权辅助
```

- **接入点 1** `create_or_update_candidate`：结果写 `details.similar_candidates`；`near_duplicates` 非空时在 `content` 提示模型"存在高度相似候选 {ids}，请先 read 后决定合并（merge_candidate）或差异化改写，而非直接新建"；**不硬拒**——查重只服务选题管理，不定义新颖性（讨论文档 661 行边界，写入 docstring）。每次比对发 `duplicate_checked` trace proposal（§12 577-584 行）。
- **接入点 2** scheduler spawn 前置检查：替换 P2.1 的标题字符串临时实现，task_brief 与在跑/已完成 worker brief 相似度 ≥ NEAR_DUP 即跳过并发 `worker_dedup_skipped`。
- 阈值为模块常量并在测试中以真实样例标定（取 5 组同义改写标题 + 5 组不同主题标题作回归集）；如果 P3.4 的 `bm25.py` 尚未落地，本任务不得阻塞在 BM25 上，先以 bigram/Jaccard 形成可用版本并在 P3.4 后补一轮增强测试；大库量性能（>1k 候选）留 simhash 替换点注释。

### Steps

- [ ] **Step 1: 写失败测试**：同义改写命中 near_dup、不同主题不误伤（标定集）；trace 留痕；工具 content 提示语出现；scheduler 跳过路径。
- [ ] **Step 2: 实现并替换两处接入点。**
- [ ] **Step 3: Run** → PASS。

---

## 5. Task P4.4: 人工审核记录、状态管理与推送分级

**Files:**

- Modify: `src/knowledgegraph/demand_discovery/domain/models.py`（HumanReviewRecord；DemandReport 扩展字段）
- Modify: `src/knowledgegraph/demand_discovery/domain/store.py`
- Create: `scripts/demand_discovery_review.py`
- Test: `tests/test_demand_discovery_human_review.py`

### 设计要点

**数据对象**（字段集 = 讨论文档 954-963 行，逐字段实现）：

```python
@dataclass
class HumanReviewRecord:
    review_id: str; report_id: str; reviewer: str; review_time: datetime
    decision: str          # approved | approved_with_changes | needs_revision |
                           # rejected | watchlist
    decision_reason: str
    accepted_claims: list[str]; rejected_claims: list[str]
    requested_changes: list[str]; notes: str
```

`DemandReport` 扩展两个实现层字段（核心四对象 schema 不动）：`review_status`（`draft → review_ready → approved | rejected | watchlist`，§13 1040-1045 行）与 `sensitive_review_required: bool`（触发条件 §13 1047 行：候选装备形态/参数指标类表述/模型综合设想/高不确定高影响——由 auditor 量表新增一项 `sensitive_flag` 判定回填，P2.3 量表追加该 check 项）。

**审核 CLI**（`scripts/demand_discovery_review.py`，文件即界面）：

```text
list                # 列出 review_ready 报告（标题/候选/审核结论/敏感标记）
show <report_id>    # 渲染报告 markdown + 证据回溯链接（artifact 路径）
decide <report_id> --decision approved --reviewer 张三 --reason "..." \
       [--accepted-claims ...] [--requested-changes ...]
```

`decide` 落库路径：写 HumanReviewRecord → DemandReport.review_status 更新 → 候选状态走 P2.5 状态机（approved → `human_reviewed`；needs_revision → 回 `candidate_demand` 并带 rollback trace）→ 全程 DomainTraceEvent `human_reviewed`（actor=reviewer，经"人工录入接口写 domain trace"通道，对应讨论文档 565 行）。

**推送分级**（§8 683-690 行规则的程序化，输出 = 本地待阅清单，不接外部平台）：

```python
def push_priority(report, audit, review) -> str:
    # immediate | digest | hold_for_evidence | watch_pool | none
```

scheduled run 与 review decide 后调用，重写 `outputs/push/inbox.md`（immediate 区 + 周期摘要区）与 `outputs/push/watchlist.md`。

### Steps

- [ ] **Step 1: 写失败测试**：review 记录往返；五种 decision 的状态流转（含回炉 rollback trace 配对）；sensitive 标记从量表回填；推送分级规则全表；CLI decide 端到端（tmp store）。
- [ ] **Step 2: 实现模型/store/状态接线。**
- [ ] **Step 3: 实现 CLI 与推送清单生成。**
- [ ] **Step 4: Run** → PASS。

---

## 6. Task P4.5: Silver case 评测基座（自 P2.3 后并行启动）

**Files:**

- Create: `docs/benchmarks/demand_discovery_silver_cases_v0.md`
- Create: `data/demand_discovery/silver_cases/`（case 素材目录约定）
- Create: `scripts/demand_discovery_replay_case.py`
- Create: `src/knowledgegraph/demand_discovery/tools/snapshot_search.py`
- Test: `tests/test_demand_discovery_case_replay.py`

### 设计要点

**Case 目录约定**（schema 不固化，遵守讨论文档 774 行决议；目录即结构）：

```text
data/demand_discovery/silver_cases/{case_id}/
  brief.md          # 选题输入（与系统 task brief 同文）
  snapshot/         # 该专题的信源快照（artifact 格式，复用 ArtifactStore）
  baselines/        # 成熟 deep research 工具输出（GPT Researcher 等，含可见检索路径）
  gold.md           # 人工审定的关键缺口/需求点/反证清单（v0 由人工从 baselines+本地输出合成）
  runs/             # 历次本地系统回放输出
  scores.md         # 人工评分表（四维度）
```

- **依赖拆分**：P2.3 后即可启动 case 选题、外部 baseline 保存和人工 gold 初稿；`SnapshotSearchAdapter`、`replay_case.py` 与完整本地系统回放依赖 P3.4 的 `SearchAdapter`/BM25 与 P3.2 artifact 缓存，故不作为 P2.3 后立即交付项。
- **可重复回放**：`SnapshotSearchAdapter` 实现 P3.4 的 `SearchAdapter` 协议但只检索 snapshot 目录（BM25）；`replay_case.py` 用它替换真实检索适配器 + 固定 prompt 版本号跑完整 orchestrator run——同 case 同 prompt 可比，隔离信源漂移。fetch_page 在回放模式命中 snapshot artifact（P3.2 缓存机制天然支持）。
- **评分四维度**（先人工，不做自动评分）：关键缺口命中（对 gold.md 逐条）/ 证据链可审计（`get_report_trace` 重建成功率 + 抽查 excerpt 回原文）/ 需求-趋势-热点区分正确率 / 反证与不确定性保留度。`scores.md` 模板含逐条对照表。
- **基线采集流程**（写入 benchmark 文档）：同题投给 ≥2 个成熟 deep research 工具 → 保存输出与可见引用 → 本地系统将多源输出规范化为 CaseDraft（这一步本身可用本系统跑）→ 人工审定为 gold.md。
- **负样本沉淀**：P4.4 的 rejected/needs_revision 记录（rejected_claims、decision_reason）定期归集到对应 case 的 `negatives.md`——讨论文档 776 行"从审核过程自然沉淀"。
- 节奏：P2.3 完成 → 立刻建第 1 个 case（先 baselines+gold）；M-LR3 后补本地 replay 与 scores；每次角色 prompt 大改后重放并追加 scores。

### Steps

- [ ] **Step 1: P2.3 后先选定 2 个专题，保存外部 baselines，人工合成 gold.md 初稿。**
- [ ] **Step 2: P3.4 后实现 SnapshotSearchAdapter 与 replay 脚本 + 离线回放测试（mini case fixture）。**
- [ ] **Step 3: M-LR3 后首轮回放与人工评分；结论写入 benchmark 文档并更新 `docs/README.md`。**

---

## 7. Task P4.6: 分层留痕保留与清理

**Files:**

- Create: `configs/demand_discovery/retention.yaml`
- Create: `scripts/demand_discovery_cleanup.py`
- Test: `tests/test_demand_discovery_retention.py`

### 设计要点

讨论文档 §13 1030-1035 行三层保留的配置化（时长全部可配，不写死）：

```yaml
long_term:   # 永不自动清理：domain JSONL（Source/Evidence/Candidate/Report/Audit/
             # HumanReview）、trace JSONL、done 报告、silver case
mid_term:    {keep_days: 90}    # worker session JSONL、WorkerReport、progress 终态
short_term:  {keep_days: 14}    # artifact 原始 HTML（被 EvidenceCard source_location
             # 引用的 text artifact 除外——清理前反查引用，被引用者升级保留）
runtime_log: {keep_days: 7}     # runner.log、processed inbox
```

`cleanup.py` 默认 `--dry-run`（打印将删清单与回收量），`--apply` 才执行；被引用 artifact 的反查保护是唯一非平凡逻辑，单测锁定。可作为 scheduled task 周跑（`repeat: every_7d`）。

### Steps

- [ ] **Step 1: 写失败测试**：分层规则；被引用 artifact 保护；dry-run 不删。
- [ ] **Step 2: 实现并注册为可选 scheduled task。**
- [ ] **Step 3: Run** → PASS。

---

## 8. 验收门禁（M-LR4）

- [ ] 全量离线测试 PASS。
- [ ] 7 天无人值守演练：scheduler 前台挂机（真 provider、小预算 horizon scan），done 报告序列完整、无重复执行、健康检查全程 HEALTHY/OVERDUE 可解释；产物存 `outputs/scheduled/`。
- [ ] 一次完整人工闭环：扫描产出 → review CLI 审核一份报告至 approved → 推送清单更新 → 候选 `human_reviewed` 终态且 trace 链完整。
- [ ] 首批 2 个 silver case 完成基线对照评分，结论入 benchmark 文档。
- [ ] 干预演练：在跑任务被 steer 纠偏一次，留痕完整。

## 9. Self-Review

- 常驻面最小化（一个轮询 runner + 文件界面）是本阶段的核心取舍：放弃实时性与远程访问，换取零服务端依赖、全程文件可审计、崩溃恢复语义简单。后续若需 Web 工作台，EventBus 与文件产物即是其数据源。
- 失败也写 done 是防重试风暴的关键决定，代价是失败日不补跑——horizon scan 的连续性损失可接受（次日重扫覆盖）。
- 评测维持人工评分不做自动 judge：当前样本量下自动评分的校准成本高于收益；负样本沉淀机制为未来自动化预留了数据。

---

## 附录：讨论文档实现覆盖矩阵（四阶段汇总）

| 讨论文档章节 | 实现位置 |
|---|---|
| §4 需求对象建模 / 显式与推断需求 / 触发与缺口类型 | P2.3 prompt（思维框架不落字段，遵 §7 决议）；report 骨架 demand_type（P2.5） |
| §5 信源分级与白名单 | P3.1 registry + tier cap；白名单外阻断（P3.2） |
| §5 粗筛最小字段 / collection_decision | P3.2 fetch_page 自动填充 |
| §5 摘要字段 / summary_source 分级 | P3.4 extract_summary 标记 + 校验 |
| §5 递进式阅读 / 全文触发 / 停止条件 | P3.4 read_document + P2.3 reader prompt |
| §5 阅读中登记/扩检/拆分 | P2.3 orchestrator+reader prompt + P2.5 状态机 |
| §5 关键词门禁 | P3.4 keyword_gate |
| §6 程序/模型分工 | 全计划工程原则（检索/去重/聚类/调度程序化，判断模型化） |
| §6 Orchestrator/Scheduler/Worker/AgentRun | P2.1/P2.2；进度接口 = WorkerReport |
| §6 分级 Context | 既有 ContextPack + P1.4 compaction |
| §6 Horizon Scanning | P4.1 定时扫描 + watchlist 复查 |
| §7 四对象与 trace 分离 / proposal 落盘 | 既有实现（Pi 复刻阶段已交付） |
| §8 评审量表 / 一票否决 / 最低证据 | P2.3 audit_rubric + run_audit 校验 |
| §8 推送分级 | P4.4 push_priority |
| §9 报告骨架 / 方案线索附属栏目 / 来源审计 | P2.5 report.py |
| §11 需求/趋势/热点区分与升级门禁 | P2.3 orchestrator prompt 六问 + auditor 量表 |
| §12 状态流 / debate / 人工审核状态 / 粒度审核 | P2.5 状态机；P2.3 debater；P4.4 review |
| §12 拆分合并去重 trace 化 | P4.3 dedup + duplicate_checked / 既有 candidate_merged |
| §13 本地查看 / 留痕分层 / 敏感标记 | P4.4 sensitive 标记 + 推送本地化；P4.6 retention |
| §10 Gold/Silver case | P4.5 |
| 未覆盖（显式延期） | SOP/skill 自动沉淀（长程演进计划远期方向，不占用 P4 编号）；外部平台分发；Web 工作台；负样本自动评测 |
