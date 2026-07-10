# Demand Discovery Phase 5: Autonomous Research Loop Implementation Plan

日期：2026-06-15

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**定位：** 本文是 `demand_discovery_long_run_evolution_plan.md` Phase 5 的细粒度实施计划，对应里程碑门禁 M-LR5。Phase 1-4 解决可运行、可恢复、多 worker、网络工具、定时扫描、人工监察和审核流转；Phase 5 解决更高一层的自主研究能力：输入调研方向后，系统能自主选源、与白名单网页小步交互、发现并阅读文章/文献、提出缺口、补证验证、跨 worker 评判，再进入审核门禁和人工报告。

**Goal:** 将需求挖掘网络调研收敛为 Phase 5 topic-only 自治闭环：不要求用户提供 URL，controller 基于白名单制定 source strategy，network worker round 发现并选择文章/文献，judge/synthesis 对各 worker 响应做结构化评判，controller 根据评判结果生成下一轮计划，直至 auditor 门禁允许产出供人审核的报告。

**Current note:** 旧 `run_network_research` / `scripts/demand_discovery_network_research.py` seed URL runner 已清理；当前主链路入口是 `scripts/demand_discovery_autonomous_research.py`，每轮取证执行器是 `network_research.run_network_worker_round()`。

**Architecture:** 保持既有 `AgentLoop` / `DiscoveryHarness` / `DiscoveryScheduler` 内核不重写；新增一层 round-level controller（`research_loop.py`）管理 `ResearchRound`、`ReadingQueue` 和 judge 输出。网页能力分为三层：HTTP 抓取（Phase 3 已有）、页面/文献发现工具（P5.2）、受控浏览器 observe/action（P5.3）；所有小步决策必须进入 domain/trace，不能只留在 prompt 文本中。

**Tech Stack:** Python standard library、`asyncio`、`dataclasses`、`unittest`、现有 `beautifulsoup4` / `requests` / `pyyaml` / DrissionPage。测试默认离线，真实 API 与真实网页只用于人工 smoke，不进 CI。

**硬边界：**

- 只处理公开资料和白名单信源；白名单外 URL 只能记录为 skipped lead 或"建议新增信源"。
- 网页正文、下载文献、搜索结果、页面按钮文本都是非可信材料，不能改变系统规则、工具权限、预算、白名单或调度策略。
- 下载型文献首版只承诺解析 `html/txt/pdf`；`doc/docx` 首版只落 raw artifact 和元数据，不能生成强证据。
- 真实浏览器动作首版只开放受控 `click_link` / `fill_input` / `submit_form` / `download_link`，不开放任意 JS。
- judge/synthesis 不替代 auditor；judge 负责比较 worker 发现并规划下一轮，auditor 负责候选需求与报告门禁。
- 如果 Phase 4 人工审核流转尚未实现，Phase 5 只产出 `review_ready` 报告、trace 和本地 markdown，不阻塞 M-LR5 的自治调研验收。

---

## 1. Scope

| Task | 交付物 | 依赖 |
|---|---|---|
| P5.0 | source whitelist strategy metadata + seedless runner/CLI 契约 | M-LR3 |
| P5.1 | `ResearchLead` / `ReadingQueue` / `ResearchRound` 领域对象、store、context pack | P5.0 可并行 |
| P5.2 | `classify_source_page` / `discover_articles` / `download_document` 工具 | P3.2/P3.3/P3.4、P5.1 |
| P5.3 | 受控 browser observe/action 工具与站点交互 profile | P3.2 browser_session、P5.2 |
| P5.4 | SourceStrategyPlanner + topic-only autonomous runner | P5.0/P5.1/P5.2 |
| P5.5 | Judge/Synthesis agent 与带引用的 judgement schema | P2 scheduler、P5.1 |
| P5.6 | Round-level ResearchLoop controller、candidate synthesis 与停止条件 | P5.4/P5.5 |
| P5.7 | Autonomous report gate、Phase 4 降级路径、CLI、fake/fixture/real smoke 验收 | P5.6 |

完成判定（M-LR5）：不传 `--seed-url`，仅输入 topic，系统至少完成两轮 `plan -> research workers -> judge -> next_round_plan`；产物包含 `ResearchRound` JSONL、ReadingQueue 选择/跳过记录、judge 结构化评判、最终 auditor 门禁结果、报告和完整 trace。真实 smoke 至少覆盖一个静态 HTML 站点入口（如 81.cn）和一个下载型文献入口。

---

## 2. 参考实现与迁移原则

| 参考 | 借鉴点 | 对应 Task |
|---|---|---|
| `reference/GenericAgent-main/ga.py` 的 `web_scan` / `web_execute_js` | 小步 observe/action 循环；观察结果压缩，动作后返回页面变化反馈 | P5.3 |
| `reference/GenericAgent-main/simphtml.py` | 主体内容、列表和可见文本压缩；避免 raw HTML 直接进入上下文 | P5.2/P5.3 |
| Phase 3 `fetch_page` / `read_document` / `ArtifactStore` | 全文落 artifact，模型只见摘要和段落窗口 | P5.2 |
| Phase 2 `WorkerReport` / `DiscoveryScheduler` | worker 并发、进度与报告基础 | P5.5/P5.6 |
| Anthropic multi-agent research 设计经验 | 并行 worker 之后必须有 synthesis/judge 归并，避免重复劳动和冲突被掩盖 | P5.5 |
| GPT Researcher / deep research runner | topic -> source selection -> iterative research -> synthesis 的外部 baseline 形态 | P5.4/P5.6/P5.7 |

迁移原则：GA 的任意 JS 能力不直接开放给需求挖掘模型。首版只开放受控 `browser_observe` 与有限 `browser_action`，复杂站点动作通过站点 profile 白名单脚本表达，避免模型任意执行网页 JS。

---

## 3. Task P5.0: Source Strategy Metadata 与 Seedless Runner 契约

**Files:**

- Modify: `src/knowledgegraph/demand_discovery/domain/source_registry.py`
- Modify: `configs/demand_discovery/source_whitelist.yaml`
- Modify: `src/knowledgegraph/demand_discovery/network_research.py`
- Modify: `scripts/demand_discovery_autonomous_research.py`
- Test: `tests/test_demand_discovery_source_strategy.py`
- Test: `tests/test_demand_discovery_autonomous_research_runner.py`

### 设计要点

入口契约应为 topic-first，允许 seed URL 作为人工约束而不是必需条件。当前实现不再保留旧 seed URL runner，topic-only 契约由 autonomous runner 承载。

`source_whitelist.yaml` 在不破坏现有字段的前提下增加可选字段：

```yaml
entry_urls:
  - "http://www.81.cn/"
topic_tags: ["low_altitude", "uav", "air_defense", "command_control"]
default_queries: ["低空 无人机 探测 预警", "反无人机 低空 防护"]
interaction_profile: "static_listing"   # static_listing | site_search | browser_listing | browser_search | none
requires_login: false
max_discovery_depth: 1
```

`SourceRegistry` 增加：

```python
def discoverable_entries(
    self,
    *,
    tiers: set[str] | None = None,
    transports: set[str] | None = None,
    topic: str = "",
) -> list[WhitelistEntry]: ...
```

排序规则首版必须程序化且可测：A/B tier 优先、`entry_urls` 非空优先、`interaction_profile != "none"` 优先、`topic_tags` 命中 topic 关键词优先、`requires_login=false` 优先。

`network_research.py` 变更：

- `seed_urls: list[str] | None = None`。
- 当 `seed_urls` 为空时不再报错，而是由 P5.4 的 `SourceStrategyPlanner` 生成入口 URL 和 worker 任务。
- 保留 seed URL 模式作为 `manual_seed` 路径，用于回归与人工指定信源。

CLI 变更：

- `--seed-url` 改为可选。
- 新增 `--autonomous`，启用 topic-only path；`--seed-url` 存在时仍作为约束传入。
- fake mode 必须支持无 seed URL 的 deterministic fixture。

### Steps

- [ ] **Step 1: 写失败测试**：无 `--seed-url --autonomous` 不再返回 2；`SourceRegistry.discoverable_entries(topic="低空无人机")` 至少返回中国军网等已配置入口；所有 `entry_urls` 仍需通过 `match()` 白名单校验。
- [ ] **Step 2: 扩展 `WhitelistEntry` 和 YAML parser**，字段缺省保持旧配置可读。
- [ ] **Step 3: 整理首批可自主入口**：配置 3-5 个 A/B 级 http 核心信源的 `entry_urls/default_queries/interaction_profile`；中国军网必须包含 `http://www.81.cn/`。首批每个 `interaction_profile != "none"` 的信源必须有一个最小 fixture 或 smoke 记录；非首批 30 个白名单源不要求一次性补齐。
- [ ] **Step 4: 在 autonomous runner 中实现 topic-first source strategy**，seed URL 只作为人工约束输入。
- [ ] **Step 5: Run** `python -m unittest tests.test_demand_discovery_source_strategy tests.test_demand_discovery_autonomous_research_runner -v` → PASS。

---

## 4. Task P5.1: ResearchLead / ReadingQueue / ResearchRound

**Files:**

- Modify: `src/knowledgegraph/demand_discovery/domain/models.py`
- Modify: `src/knowledgegraph/demand_discovery/domain/store.py`
- Modify: `src/knowledgegraph/demand_discovery/harness/context_pack.py`
- Create: `src/knowledgegraph/demand_discovery/domain/research_state.py`
- Test: `tests/test_demand_discovery_research_state.py`
- Test: `tests/test_demand_discovery_context_pack_research_state.py`

### 设计要点

小步决策必须从自然语言上下文搬到领域状态层。新增对象不替代 Source/Evidence/Candidate，而是记录进入 Source/Evidence 前的调研线索和轮次决策。

```python
@dataclass
class ResearchLead:
    lead_id: str
    round_id: str
    source_name: str
    source_tier: str
    url: str
    title: str
    snippet: str
    page_type: str              # article | listing | site_home | search_page | download_document | unknown
    download_kind: str          # none | pdf | doc | html_attachment | unknown
    relevance_score: float
    importance_score: float
    credibility_score: float
    status: str                 # discovered | selected | fetched | read | downloaded | skipped | failed
    selection_reason: str
    skip_reason: str
    artifact_refs: list[str]
    created_at: datetime
    updated_at: datetime
```

```python
@dataclass
class ReadingQueue:
    queue_id: str
    round_id: str
    topic: str
    lead_ids: list[str]
    selected_lead_ids: list[str]
    skipped_lead_ids: list[str]
    failed_lead_ids: list[str]
    budget_snapshot: dict[str, Any]
    created_at: datetime
    updated_at: datetime
```

```python
@dataclass
class ResearchRound:
    round_id: str
    run_id: str
    index: int
    topic: str
    hypothesis: str
    source_strategy_id: str
    worker_report_ids: list[str]
    judgement_id: str | None
    next_round_plan: dict[str, Any]
    stop_reason: str | None
    status: str                 # planned | running | judged | stopped | failed
    created_at: datetime
    updated_at: datetime
```

`DomainStore` 增加 append/upsert 方法和 JSONL export/load 支持。`ContextPackBuilder` 渲染 compact view：

- 最近 2 轮 ResearchRound。
- 每轮 selected/skipped/failed lead 摘要。
- 待读 open questions 和 next_round_plan。
- 不渲染全文，不渲染完整 HTML。

### Steps

- [ ] **Step 1: 写失败测试**：ResearchLead 状态流转、unknown status 拒绝、JSONL export/load 往返、context snapshot 包含 selected/skipped lead 但不包含原文全文。
- [ ] **Step 2: 实现 dataclass 与 store 方法**：`upsert_research_lead()`、`upsert_reading_queue()`、`upsert_research_round()`。
- [ ] **Step 3: 实现 trace proposal 支持**：工具可写 `ResearchLead`、`ReadingQueue`、`ResearchRound`。
- [ ] **Step 4: 更新 `ContextPackBuilder` compact view**，让后续 worker 能看到已读/已跳过状态。
- [ ] **Step 5: Run** `python -m unittest tests.test_demand_discovery_research_state tests.test_demand_discovery_context_pack_research_state -v` → PASS。

---

## 5. Task P5.2: 页面分类、文章发现与下载文献工具

**Files:**

- Create: `src/knowledgegraph/demand_discovery/tools/discovery.py`
- Modify: `src/knowledgegraph/demand_discovery/tools/documents.py`
- Modify: `src/knowledgegraph/demand_discovery/domain/tools.py`
- Test: `tests/test_demand_discovery_tool_classify_source_page.py`
- Test: `tests/test_demand_discovery_tool_discover_articles.py`
- Test: `tests/test_demand_discovery_tool_download_document.py`
- Fixture: `tests/fixtures/demand_discovery_pages/listing_with_articles.html`
- Fixture: `tests/fixtures/demand_discovery_pages/article_with_pdf.html`

### 设计要点

新增三个工具，均注册到 reader/researcher 工具面。

**`classify_source_page`**

参数：

```json
{"url": "string?", "artifact_ref": "string?", "topic": "string"}
```

返回：

```json
{
  "page_type": "article|listing|site_home|search_page|download_document|unknown",
  "title": "...",
  "candidate_link_count": 12,
  "download_link_count": 2,
  "reason": "has h1/date/article body paragraphs"
}
```

规则首版以启发式为主：正文段落数量、标题/日期、链接密度、下载链接比例、URL 扩展名、meta article 标记。必须可解释，不调用模型。

**`discover_articles`**

参数：

```json
{"seed_url": "string", "topic": "string", "round_id": "string", "max_candidates": 20, "depth": 1}
```

行为：

- fetch/read seed page。
- 抽取 `<a href>` 链接、标题、附近文本、日期。
- 只保留 `SourceRegistry.match(url) != None` 的链接；白名单外链接写 skipped lead。
- 按 `topic` 关键词、source tier、链接上下文、URL 类型、发布时间排序。
- 产出 `ResearchLead` domain proposals；不直接产出 EvidenceCard。

**`download_document`**

参数：

```json
{"url": "string?", "lead_id": "string?", "force_refresh": false}
```

行为：

- URL 必须白名单内。
- content-type 或扩展名首版强支持 `html/txt/pdf`；超出类型返回 error ToolResult，`doc/docx` 只保存 raw artifact 和 metadata，状态标记为 `failed` 或 `skipped_pending_parser`，不能生成强证据。
- 下载原始 artifact；若能解析文本，生成 text artifact 并把 `ResearchLead.status` 更新为 `downloaded`。
- PDF 解析优先使用 `pypdf`；若依赖缺失或解析失败，返回可读错误并保留原始 artifact，不生成强证据。

### Steps

- [ ] **Step 1: 写分类测试**：文章 fixture 判为 `article`，栏目 fixture 判为 `listing`，PDF URL 判为 `download_document`，空页面判为 `unknown`。
- [ ] **Step 2: 实现 `classify_source_page`**，复用 `ArtifactStore` 与 `SourceRegistry`。
- [ ] **Step 3: 写发现测试**：栏目 fixture 中 3 个白名单内链接生成 `ResearchLead`，白名单外链接生成 skipped lead，排序稳定。
- [ ] **Step 4: 实现 `discover_articles`**，返回候选摘要并写 domain/trace proposals。
- [ ] **Step 5: 写下载测试**：PDF/html/txt fixture 落 artifact，text 解析成功时可被 `read_document` 读取；doc/docx fixture 只落 raw artifact 和 metadata；解析失败不生成 EvidenceCard。
- [ ] **Step 6: 实现 `download_document` 并接入 `build_all_tools()`。**
- [ ] **Step 7: Run** `python -m unittest tests.test_demand_discovery_tool_classify_source_page tests.test_demand_discovery_tool_discover_articles tests.test_demand_discovery_tool_download_document -v` → PASS。

---

## 6. Task P5.3: 受控 Browser Observe/Action 与站点交互 Profile

**Files:**

- Create: `src/knowledgegraph/demand_discovery/tools/browser_actions.py`
- Modify: `src/knowledgegraph/demand_discovery/tools/browser_bridge.py`
- Modify: `src/knowledgegraph/demand_discovery/domain/tools.py`
- Test: `tests/test_demand_discovery_browser_actions.py`

### 设计要点

当前 `browser_session` 只做 `page.get(url)` + `page.html`，适合读取登录态页面，不足以支持搜索框、翻页、下载按钮和动态列表。Phase 5 首版不暴露任意 JS，而是提供受控 observe/action。

**`browser_observe`**

参数：

```json
{"url": "string?", "session_id": "string?", "max_chars": 12000, "include_links": true}
```

返回：

- 当前 URL、标题、压缩正文。
- 可点击链接列表：`link_id/title/url/text_context/download_kind`。
- 表单摘要：`form_id/inputs/buttons/action/method`。
- `observation_ref` artifact。

**`browser_action`**

参数：

```json
{
  "session_id": "string",
  "action": "click_link|fill_input|submit_form|next_page|download_link",
  "target_id": "string",
  "value": "string?"
}
```

约束：

- action 必须作用于上一次 `browser_observe` 返回的 `target_id`。
- 下载动作必须走 `download_document` 或返回 `download_url`，不能直接把文件塞进上下文。
- 每次 action 后返回页面变化摘要：URL 是否变化、标题变化、主要新增文本、下载 URL。
- browser_session 工具串行化，沿用 `_BROWSER_LOCK`。
- 禁止任意 JS、任意 CSS selector、任意 URL 跳转；所有 target 必须来自 `browser_observe` 返回的 allowlisted target list。

站点 profile：

```yaml
interaction_profile: "site_search"
site_profile:
  search_input_hints: ["q", "keyword", "searchword"]
  next_page_hints: ["下一页", "next"]
  article_link_patterns: ["/content/", "/news/"]
```

profile 只用于提高目标识别，不赋予越权能力。

### Steps

- [ ] **Step 1: 写 mock DrissionPage 测试**：observe 返回链接/表单摘要；action 只能使用 observe 中的 target_id；action 后返回变化摘要；任意 JS/未观察 target 被拒绝。
- [ ] **Step 2: 扩展 `browser_bridge.py`**：保留 `fetch_with_browser_session()`，新增 session 管理与 observe/action 内部 API。
- [ ] **Step 3: 实现 `browser_observe` / `browser_action` ToolDefinition**，接入白名单 hook。
- [ ] **Step 4: 将 `discover_articles` 在 `browser_listing/browser_search` profile 下可选择 browser observe 路径。**
- [ ] **Step 5: 增加 fixture 化浏览器交互 smoke**：本地 fixture 页面覆盖搜索框提交、下一页、下载按钮三类动作；`allow_browser=true` 的真实站点 smoke 只作为人工验收，不进入 CI。
- [ ] **Step 6: Run** `python -m unittest tests.test_demand_discovery_browser_actions -v` → PASS。

---

## 7. Task P5.4: SourceStrategyPlanner 与 Topic-only Runner

**Files:**

- Create: `src/knowledgegraph/demand_discovery/domain/source_strategy.py`
- Create: `src/knowledgegraph/demand_discovery/autonomous_research.py`
- Create: `scripts/demand_discovery_autonomous_research.py`
- Modify: `src/knowledgegraph/demand_discovery/network_research.py`
- Modify: `src/knowledgegraph/demand_discovery/workers/agents/orchestrator.md`
- Test: `tests/test_demand_discovery_source_strategy.py`
- Test: `tests/test_demand_discovery_autonomous_research_runner.py`

### 设计要点

`SourceStrategyPlanner` 程序化生成首轮 source strategy，模型不能跳过这个阶段直接报告。

```python
@dataclass
class SourceStrategy:
    strategy_id: str
    topic: str
    selected_sources: list[SelectedSource]
    held_sources: list[HeldSource]
    seed_urls: list[str]
    rationale: str
```

选择规则：

- 至少 2 个 A/B 级 http source，除非 registry 中无可用项。
- 至少 1 个不同 source_type 的补充视角，例如 official + thinktank / journal。
- `browser_session` source 首轮占比不超过 30%，除非用户显式允许。
- topic_tags 命中优先；无命中时选择通用 A 级入口。
- selected/held 都写理由。

新增 runner `run_autonomous_research()`：

```python
async def run_autonomous_research(
    *,
    mode: str,
    topic: str,
    output_root: Path,
    run_id: str,
    max_rounds: int = 2,
    seed_urls: list[str] | None = None,
    allow_browser: bool = False,
    ...
) -> AutonomousResearchResult: ...
```

CLI：

```powershell
python scripts\demand_discovery_autonomous_research.py `
  --mode real `
  --topic "低空小型无人机威胁下的探测、预警与防护能力缺口" `
  --run-id phase5-autonomous-cuas-001 `
  --max-rounds 2
```

旧 `scripts/demand_discovery_network_research.py` M-LR3 seed URL runner 已删除；Phase 5 CLI 是唯一主入口，worker 取证能力收敛在 `network_research.run_network_worker_round()`。

### Steps

- [ ] **Step 1: 写 source strategy 测试**：topic 命中时选择带 topic_tags 的 A/B 入口；无 seed URL 时生成 seed_urls；browser source 默认受限。
- [ ] **Step 2: 实现 `source_strategy.py` 并把 strategy 写入 DomainStore/trace。**
- [ ] **Step 3: 写 runner fake 测试**：只传 topic，fake provider 能收到 source strategy 和首轮 worker task。
- [ ] **Step 4: 实现 `autonomous_research.py` 和 CLI。**
- [ ] **Step 5: 更新 orchestrator prompt**：明确先读 source strategy，再派发 reader，不得凭空造 URL。
- [ ] **Step 6: Run** `python -m unittest tests.test_demand_discovery_source_strategy tests.test_demand_discovery_autonomous_research_runner -v` → PASS。

---

## 8. Task P5.5: Judge/Synthesis Agent 与 Judgement Schema

**Files:**

- Create: `src/knowledgegraph/demand_discovery/domain/judgement.py`
- Create: `src/knowledgegraph/demand_discovery/workers/agents/judge.md`
- Modify: `src/knowledgegraph/demand_discovery/harness/worker_report.py`
- Modify: `src/knowledgegraph/demand_discovery/harness/scheduler.py`
- Test: `tests/test_demand_discovery_judgement.py`
- Test: `tests/test_demand_discovery_judge_synthesis.py`

### 设计要点

judge 是跨 worker 响应的综合评判 agent，不是 auditor。

`JudgementReport` schema：

```python
@dataclass
class JudgementItem:
    text: str
    worker_report_ids: list[str]
    evidence_ids: list[str]
    lead_ids: list[str]

@dataclass
class JudgementReport:
    judgement_id: str
    round_id: str
    consensus_points: list[JudgementItem]
    contradictions: list[JudgementItem]
    partial_coverage: list[JudgementItem]
    unique_insights: list[JudgementItem]
    blind_spots: list[JudgementItem]
    evidence_strength_map: dict[str, str]
    next_round_plan: dict[str, Any]
    stop_or_continue: str          # stop | continue | needs_human_steer
    rationale: str
    created_at: datetime
```

`judge.md` 输出必须使用固定 JSON block 或工具调用 `record_judgement`。首版推荐工具调用，避免解析自由文本。

每条 `JudgementItem` 至少要引用一个 `worker_report_id`，并在能追溯时附 `evidence_ids` 或 `lead_ids`。无法引用具体证据的 judgement 只能进入 `blind_spots` 或 `partial_coverage`，不能作为报告结论支撑。

`WorkerReport` 增加：

- `report_id` 或 `agent_run_id` 作为 judgement input refs。
- `evidence_refs` compact view。
- `lead_refs` compact view。

judge 输入不得包含 artifact 全文，只包含：

- WorkerReport digest。
- ResearchLead compact view。
- EvidenceCard claim/summary/source_location。
- CandidateDemand 摘要。

### Steps

- [ ] **Step 1: 写 `JudgementReport` store 往返测试**：每条 consensus/contradiction/blind_spot 都保留 worker/evidence/lead 引用；缺少引用的 consensus 被拒绝或降级。
- [ ] **Step 2: 实现 judgement dataclass、store 方法和 `record_judgement` 工具。**
- [ ] **Step 3: 写 judge fake provider 测试**：两个 worker 一个支持、一个冲突，judge 输出 consensus/contradictions/blind_spots/next_round_plan。
- [ ] **Step 4: 实现 `judge.md` 和 scheduler 调用辅助 `run_judge_for_round()`。**
- [ ] **Step 5: Run** `python -m unittest tests.test_demand_discovery_judgement tests.test_demand_discovery_judge_synthesis -v` → PASS。

---

## 9. Task P5.6: Round-level ResearchLoop Controller

**Files:**

- Create: `src/knowledgegraph/demand_discovery/harness/research_loop.py`
- Create: `src/knowledgegraph/demand_discovery/domain/candidate_synthesis.py`
- Modify: `src/knowledgegraph/demand_discovery/autonomous_research.py`
- Modify: `src/knowledgegraph/demand_discovery/harness/event_bus.py`
- Test: `tests/test_demand_discovery_research_loop.py`
- Test: `tests/test_demand_discovery_candidate_synthesis.py`

### 设计要点

新增 controller，负责把 WorkerReport 和 JudgementReport 转成下一轮计划，而不是让 orchestrator prompt 自己决定一切。

流程：

```text
build_source_strategy
  -> create ResearchRound(index=1)
  -> build reader/researcher WorkerSpec list
  -> scheduler.run_workers()
  -> run_judge_for_round()
  -> evaluate_stop_conditions()
  -> if continue: create ResearchRound(index+1) from next_round_plan
  -> if stop: synthesize or update CandidateDemand from judgement + evidence + worker reports
  -> spawn auditor/report path
```

停止条件必须程序化：

- `round_index >= max_rounds`。
- `budget.exhausted()` 或进入 wrap-up。
- 本轮新增强证据数为 0 且 judge 没有高优先级 next_round_plan。
- `blind_spots` 全部是白名单外或需人工信源。
- auditor 判断可生成报告。
- 连续两轮 `need_more_sources=true` 但无新增 discoverable entries。

controller 输出：

- `round_summary.json`。
- `progress.md` 增加 round 状态、judge 摘要、下一轮计划。
- DomainTraceEvent：`research_round_started`、`research_round_judged`、`research_loop_stopped`。

停止后必须经过 candidate synthesis，不允许直接让 orchestrator 自由生成报告。首版使用程序化 helper：

```python
@dataclass
class CandidateSynthesisDraft:
    candidate_id: str
    title: str
    demand_statement: str
    evidence_ids: list[str]
    open_questions: list[str]
    solution_signals: list[str]
    judgement_id: str
    rationale: str

def synthesize_candidate_from_judgement(
    judgement: JudgementReport,
    store: DomainStore,
) -> CandidateSynthesisDraft: ...
```

helper 只允许引用已存在 EvidenceCard；如果 judgement 的共识点没有足够 evidence refs，则输出 `needs_more_evidence` stop reason，不生成 `CandidateDemand`。

### Steps

- [ ] **Step 1: 写 fake loop 测试**：两轮 research，第一轮 judge 返回 continue，第二轮 stop；round_summary 写出。
- [ ] **Step 2: 写停止条件测试**：max_rounds、无新增强证据、白名单外 blind spot、预算收尾均能 stop。
- [ ] **Step 3: 写 candidate synthesis 测试**：只从 judgement/evidence refs 生成 CandidateDemand；无 evidence refs 时拒绝生成并返回 `needs_more_evidence`。
- [ ] **Step 4: 实现 `ResearchLoopController` 与 `candidate_synthesis.py`。**
- [ ] **Step 5: 接入 `run_autonomous_research()`。**
- [ ] **Step 6: Run** `python -m unittest tests.test_demand_discovery_research_loop tests.test_demand_discovery_candidate_synthesis -v` → PASS。

---

## 10. Task P5.7: Autonomous Report Gate、CLI 与 E2E 验收

**Files:**

- Modify: `src/knowledgegraph/demand_discovery/domain/report.py`
- Modify: `src/knowledgegraph/demand_discovery/domain/audit_rubric.py`
- Modify: `src/knowledgegraph/demand_discovery/autonomous_research.py`
- Test: `tests/test_demand_discovery_autonomous_report_gate.py`
- Test: `tests/test_demand_discovery_autonomous_e2e_fake.py`
- Create: `docs/experiment-artifacts/demand_discovery_phase5_autonomous_research_smoke.md`

### 设计要点

报告门禁必须引用最终 approved audit、支撑 EvidenceCard、judge 的结构化输出和未解决问题。

新增报告前置检查：

- 至少一个 `JudgementReport.stop_or_continue == "stop"` 或 auditor 明确要求进入报告。
- 若 `JudgementReport.contradictions` 存在未解释关键矛盾，报告只能进入 `needs_revision` 或 `watchlist`。
- EvidenceCard 必须回指文章正文或下载文献正文的 `source_location`；导航页标题证据只能作为背景弱证据。
- `DemandReport` body 不再重复 `Candidate Demand / Demand Report Body` 包装；元信息写 front matter 或附录。
- Phase 4 人工审核流转已实现时，report gate 将报告状态置为 `review_ready` 并交给 `scripts/demand_discovery_review.py`；Phase 4 未实现时，只写 `review_ready` front matter、trace 和本地 markdown，不尝试更新 HumanReviewRecord。

E2E 验收分三层：

1. Fake provider：完全离线，topic-only，两轮 loop，产出 judge + report。
2. Fixture HTTP：用栏目页 fixture 和文章/PDF fixture，验证 discover/read/download/report trace。
3. Browser fixture smoke：`allow_browser=true`，本地 fixture 覆盖搜索框/翻页/下载按钮，证明 observe/action 闭环。
4. Real smoke：小预算真实 API + 1 个白名单入口；若开启 `allow_browser=true`，只作为人工验收，记录产物，不进 CI。

### Steps

- [ ] **Step 1: 写报告 gate 测试**：无 judgement 拒绝、未解释 contradiction 降级、导航页证据不能单独通过。
- [ ] **Step 2: 实现 autonomous report gate。**
- [ ] **Step 3: 写 fake E2E 测试**：topic-only，两个 worker，judge，第二轮，auditor，report。
- [ ] **Step 4: 写 fixture HTTP E2E 测试**：listing -> discover_articles -> article/PDF -> evidence -> judgement -> report。
- [ ] **Step 5: 实现 smoke 文档模板并运行一次 fake/fixture smoke；browser fixture smoke 必须覆盖搜索框/翻页/下载按钮；真实 smoke 人工触发。**
- [ ] **Step 6: Run** `python -m unittest tests.test_demand_discovery_autonomous_report_gate tests.test_demand_discovery_autonomous_e2e_fake -v` → PASS。

---

## 11. 执行顺序

推荐顺序：

```text
P5.0 -> P5.1 -> P5.2 -> P5.4 -> P5.5 -> P5.6 -> P5.7
                 └──── P5.3 可在 P5.2 后并行，先不阻塞 HTTP fixture 路径
```

说明：

- P5.3 browser action 是真实网页能力上限，但首个 M-LR5 fake/fixture 验收可先走静态 HTML 与下载 fixture。
- P5.4 需要 P5.0 的 source metadata 和 P5.1 的 domain state；否则 seedless 只能靠 prompt 记忆。
- P5.6 之前不要做真实大规模 API 调用，因为没有 controller 停止条件时容易放大成本。

---

## 12. 验收门禁（M-LR5）

- [ ] 全量离线测试 PASS。
- [ ] `python scripts/demand_discovery_autonomous_research.py --mode fake --topic "...低空无人机..." --max-rounds 2` 不传 `--seed-url` 可完成。
- [ ] `outputs/runs/{run_id}/round_summary.json` 至少包含 2 个 ResearchRound。
- [ ] ReadingQueue 中至少有 selected/skipped/failed 三类状态的可审计记录。
- [ ] JudgementReport 包含 `consensus_points`、`contradictions`、`partial_coverage`、`unique_insights`、`blind_spots`、`next_round_plan`，且每条 judgement item 带 worker/evidence/lead refs。
- [ ] ResearchLoop stop 后必须经过 candidate synthesis；报告 trace 中能看到 `judgement -> candidate_synthesis -> audit -> report`。
- [ ] 报告 trace 能重建 `source strategy -> leads -> reading queue -> evidence -> worker reports -> judgement -> audit -> report`。
- [ ] Fixture E2E 验证导航页不会单独作为强证据，至少一条 EvidenceCard 来自文章正文或下载文献正文。
- [ ] Browser fixture smoke 覆盖搜索框提交、翻页、下载按钮三类动作；真实 `allow_browser=true` smoke 为人工验收项。
- [ ] 真实 smoke 记录写入 `docs/experiment-artifacts/demand_discovery_phase5_autonomous_research_smoke.md`，包含命令、配置脱敏摘要、run dir、trace count、round count、人工复盘结论。

---

## 13. 风险与回退

| 风险 | 缓解 / 回退 |
|---|---|
| Topic-only source strategy 选源质量差 | 先程序化限制 A/B tier、entry_urls、source_type 多样性；真实运行后用 silver case 调整 topic_tags 和 default_queries |
| discover_articles 把导航噪声当候选 | ResearchLead 只作为候选，不直接生成证据；必须经 fetch/read/download 后才能创建 EvidenceCard |
| browser_action 引入不稳定和越权风险 | 首版受控 action，不暴露任意 JS；默认 `allow_browser=false`，真实 smoke 显式开启 |
| judge 过度综合掩盖冲突 | JudgementReport schema 强制 contradictions/blind_spots；report gate 对未解释关键矛盾降级 |
| 多轮 loop 成本失控 | `max_rounds`、RunBudget、stop conditions 三层硬约束；预算进入 wrap-up 后阻断新检索/新下载 |
| 下载文献解析失败 | 首版只强解析 html/txt/pdf；doc/docx 只保留 artifact 和 metadata；不生成强证据；下一轮计划可要求人工解析或换源 |
| 首批白名单配置膨胀 | M-LR5 只要求 3-5 个 A/B 级核心源具备 fixture/smoke；其余白名单源保留访问边界，不要求一次性补齐策略数据 |

---

## 14. Self-Review

- 四个用户明确缺口均已落成任务：topic-only 自主选源在 P5.0/P5.4，程序化再规划与 candidate synthesis 在 P5.6，带引用的 judge/synthesis 在 P5.5，真实网页小步交互在 P5.3。
- 计划避免把导航页直接升级为证据：P5.2 只产 ResearchLead，P5.7 report gate 强制至少一条正文/下载文献证据。
- browser 能力先做受控 observe/action，不直接复刻 GA 任意 JS，符合本项目白名单与公开资料安全边界；真实 browser smoke 作为人工验收，不污染离线 CI。
- 白名单策略范围已收缩为 3-5 个核心源先行，不要求一次性为全部白名单源补 fixture。
- 真实 API 和真实网页调用只作为 smoke；核心验收依赖 fake/fixture，保证可重复。
