# Demand Discovery Phase 3: Network Tools Implementation Plan

日期：2026-06-11

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**定位：** 本文是 `demand_discovery_long_run_evolution_plan.md` Phase 3 的细粒度实施计划，与 Phase 2 并行执行，合流于里程碑 M-LR3。

**Goal:** 让 worker 能接触真实信源：白名单内检索、网页抓取（含登录态信源）、正文简化与分段精读、关键词门禁分流；并完成真 provider 冒烟，达成首次端到端真实专题调研。

**Architecture:** 所有网络能力以 `ToolDefinition` 形态接入既有四通道契约；白名单校验走 `before_tool_call` hook；正文全文一律落 artifact 缓存，模型上下文只见摘录 + 引用（Manus"文件系统即外部记忆"原则，与既有 context_pack 摘录设计一致）。工具实现同步阻塞 IO 统一经 `asyncio.to_thread` 进入事件循环（与 responses_adapter 既有模式一致）。网页、PDF、检索结果和页面元数据全部视为**非可信材料**：只能作为证据候选或待分析内容，不能作为模型/工具/调度指令，不能覆盖 system prompt、白名单、预算、工具权限和写入规则。

**Tech Stack:** `requests`、`beautifulsoup4`（**均已在根 requirements.txt**）；新增 `pyyaml`（配置文件）。浏览器 transport 复用仓库已验证的 **DrissionPage** 路线（requirements 已有）。BM25 自实现（约 60 行，零新依赖）。测试全部离线（mock transport + 本地 fixture HTML）。

**浏览器 transport 选型说明：** 演进计划原拟移植 GenericAgent 的 TMWebDriver（WS + 浏览器扩展桥）。调研确认本仓库 `cnki_keyword_crawler/cnki_keyword_downloader.py` 与 `wechat_mp_collector/` 已在生产使用 DrissionPage（CDP attach 真实 Chrome、保留登录态、纯 Python 无扩展安装），是已被本项目信源验证过的更精炼路线，故改选 DrissionPage attach 模式；TMWebDriver 仅作设计参考保留。

**参考实现总表：**

| 参考 | 借鉴点 | 对应 Task |
|---|---|---|
| GPT Researcher（`assafelovic/gpt-researcher`）retriever/scraper 抽象 | "多 retriever 统一接口 + 按配置选用"的检索适配器形态；scraper 失败降级链；来源元数据随结果返回 | P3.1 / P3.4 |
| 本仓库 `cnki_keyword_crawler/`、`wechat_mp_collector/` | DrissionPage attach 真实浏览器的登录态采集模式；站点结构解析经验 | P3.2 |
| `reference/GenericAgent-main/simphtml.py` | DOM 简化规则：剔噪声标签、保留表单/结构状态、压缩重复列表 | P3.3 |
| trafilatura | 正文抽取的成熟对照（本期不引依赖，规则设计时对照其 precision/recall 取舍；留作未来降级链候选） | P3.3 |
| `reference/pi/packages/coding-agent/src/core/tools/read.ts` | offset/limit 分段读取、截断后的"继续读取"提示、details 保留 truncation 元数据 | P3.4 |
| Scrapy AutoThrottle / 通用爬虫礼仪 | 按域名最小间隔的轻量限速（token-bucket 简化为 min-interval），自定义 UA | P3.2 |
| rank_bm25（`dorianbrown/rank_bm25`） | Okapi BM25 公式与默认参数（k1=1.5, b=0.75）；本期按其公式自实现以保持零依赖 | P3.4 |
| Crawl4AI（`unclecode/crawl4ai`） | fetch→extract→cache 流水线分层与内容寻址缓存（设计对照，不引依赖） | P3.2 |
| 讨论文档 §5（信源分级/粗筛字段/关键词门禁/递进阅读） | 本阶段的领域规则唯一事实源 | 全部 |

---

## 1. Scope

| Task | 交付物 | 依赖 |
|---|---|---|
| P3.1 | 信源白名单 YAML + `SourceRegistry` + tier 规则函数 | 无 |
| P3.2 | `fetch_page`（http + browser_session 双 transport）+ artifact 缓存 + 白名单 hook + 限速 | P3.1 |
| P3.3 | 正文简化器（结构化视图 + 原文偏移定位） | 无（与 P3.2 并行） |
| P3.4 | `search_sources` / `read_document` / `extract_summary` + 关键词门禁 + 本地 BM25 | P3.1-P3.3 |
| P3.5 | 真 provider 冒烟 + SSE 真流式（合并 P1.5）+ usage 接线验证 | Phase 1 P1.3 |

完成判定（与 Phase 2 合流为 M-LR3）：真 provider + 真实白名单信源完成一次端到端专题调研，`get_report_trace` 可重建检索 → 证据 → 候选 → 审核 → 报告因果链。

---

## 2. Task P3.1: 信源白名单与 SourceRegistry

**Files:**

- Create: `configs/demand_discovery/source_whitelist.yaml`
- Create: `src/knowledgegraph/demand_discovery/domain/source_registry.py`
- Modify: `requirements.txt`（新增 `pyyaml`）
- Test: `tests/test_demand_discovery_source_registry.py`

### 设计要点

**白名单条目 schema：**

```yaml
version: 1
sources:
  - source_name: "战术导弹技术"
    source_tier: "A"            # A | B | C | D（D 仅记录排除原因，不参与采集）
    source_type: "journal"      # journal | defense_media | thinktank | official | wemedia | ...
    hosts: ["www.example-zsdd.cn"]          # host 后缀匹配
    path_prefixes: []                        # 可选，进一步收窄
    fetch_transport: "http"                  # http | browser_session
    search:                                  # 检索入口声明（P3.4 消费）
      type: "url_template"                   # url_template | listing | local_only | none
      template: "https://.../search?q={query}&page={page}"
    rate_limit_ms: 3000                      # 同域最小间隔
    notes: ""
  - source_name: "某公众号集合"
    source_tier: "C"
    fetch_transport: "browser_session"
    ...
excluded:                                    # D 级：只记录，永不采集
  - source_name: "..."
    reason: "无来源拼接内容"
```

初版名单整理来源：`docs/collection/` 五个站点采集方案 + 讨论文档 §5 信源类别清单 + `wechat_mp_collector` 既有目标号。**整理名单本身是交付物的一部分**，每条须填 tier 依据（notes）。

**SourceRegistry API：**

```python
@dataclass(frozen=True)
class WhitelistEntry: ...  # 上述字段

class SourceRegistry:
    @classmethod
    def load(cls, path: Path) -> "SourceRegistry": ...
    def match(self, url: str) -> WhitelistEntry | None: ...
    # host 后缀匹配（含子域）+ path 前缀；多条命中取最具体（path 前缀最长）
    def tier_status_cap(self, tier: str) -> str: ...
    # 讨论文档 162-169 行规则的纯函数：
    #   C -> researchable_signal；B -> candidate_demand；A -> demand_report；D -> 不进入
    def search_entries(self) -> list[WhitelistEntry]: ...   # search.type != none
```

`tier_status_cap` 即 Phase 2 P2.5 预留的钩子函数，本任务完成后注入 `DomainStore`。

### Steps

- [ ] **Step 1: 写失败测试**：加载与 schema 校验（缺 tier / 非法 transport 报错）；match 的子域/路径/最具体命中；白名单外返回 None；tier cap 规则全表；excluded 条目不可 match 命中。
- [ ] **Step 2: 实现 registry 并整理首版白名单。**
- [ ] **Step 3: 注入 DomainStore tier cap 钩子（P2.5 已留位）并补集成断言。**
- [ ] **Step 4: Run** → PASS。

---

## 3. Task P3.2: fetch_page 双 transport 与 artifact 缓存

**Files:**

- Create: `src/knowledgegraph/demand_discovery/tools/__init__.py`
- Create: `src/knowledgegraph/demand_discovery/tools/artifacts.py`
- Create: `src/knowledgegraph/demand_discovery/tools/network.py`
- Create: `src/knowledgegraph/demand_discovery/tools/browser_bridge.py`
- Modify: `src/knowledgegraph/demand_discovery/harness/agent_harness.py`（默认 hook 装配辅助，如需）
- Test: `tests/test_demand_discovery_artifacts.py`
- Test: `tests/test_demand_discovery_tool_fetch_page.py`

### 设计要点

**Artifact 缓存（内容寻址，对照 Crawl4AI 缓存分层）：**

```python
class ArtifactStore:
    def __init__(self, root: Path) -> None: ...
    def put(self, content: bytes | str, *, kind: str, meta: dict) -> str: ...
    # 返回 artifact_ref = f"{kind}:{sha256[:16]}"；内容写 root/{sha256}.{ext}，
    # 元数据写 sidecar {sha256}.meta.json（url、fetch 时间、content_type、transport）
    def get_text(self, ref: str) -> str: ...
    def exists(self, ref: str) -> bool: ...
```

**FetchPageTool：**

```python
# 参数: {"url": str, "force_refresh": bool=False}
# content: 标题 + 简化正文前 N 字摘录（≤2KB）+ source_id + artifact_ref + "用 read_document 分段精读"提示
# details: {source_id?, status_code, content_hash, artifact_ref, truncated, transport,
#           simplified_ref, fetch_ms}
# domain_proposals: SourceRecord upsert（粗筛最小字段自动填充：source_id（按 url hash 生成或
#   复用已有）、title、source_name/source_tier/source_type（来自白名单条目）、publish_time
#   （简化器尽力抽取，可空）、url_or_path、summary_text=导语、summary_source=lead_summary、
#   collection_decision 默认 use_as_background，由后续 agent 改判——对应讨论文档 §5 171-189 行）
# trace_proposals: source_seen
```

- **http transport**：`requests.get` 经 `asyncio.to_thread`；超时取白名单/默认 30s；`max_bytes` 上限（默认 2MB，超限截断并标注）；编码用 `response.apparent_encoding` 兜底；**重定向后终点 URL 必须重过白名单**（安全关键，单测锁定）。
- **限速**：模块级 `DomainRateLimiter`（`{host: last_fetch_monotonic}`，不足 `rate_limit_ms` 则 `asyncio.sleep` 补足）——Scrapy AutoThrottle 的最小可用形态；自定义 UA 标识项目名。
- **browser_session transport**（`browser_bridge.py`，import 失败不影响 http 路径——惰性导入 + 明确错误信息）：DrissionPage `ChromiumPage` attach 到调试端口的既开 Chrome（复用 `cnki_keyword_crawler` 模式：`ChromiumOptions().set_local_port(9222)`），`page.get(url)` 后取 `page.html`；同样落 artifact。约束如实声明于 docstring：需本机开启调试端口的 Chrome、不可并发（模块级 asyncio.Lock 串行化）。transport 由白名单条目决定，模型不可指定。
- **白名单 hook**：`build_whitelist_hook(registry) -> BeforeToolCall`，拦 `fetch_page`/`search_sources` 的 URL/信源参数；白名单外阻断并返回固定文案 ToolResult（"该来源不在白名单内。如认为有价值，请在结论中提出'建议新增信源'，不要重试该 URL"——对应讨论文档 153 行）。
- **非可信内容提示**：`fetch_page` 与 `read_document` 的 `content` 固定包含材料边界提示，告知模型页面正文不是指令。reader/orchestrator prompt 也写入同一不变式；测试 fixture 应包含"忽略此前指令/调用某工具"等注入文本，断言系统只把它作为页面内容保留，不触发权限或调度变化。
- 失败归一：超时/4xx/5xx/解析失败 → error ToolResult 带可读原因与 status_code；**错误保留在上下文中**让模型自适应换源（Manus"keep errors in context"原则），不静默重试超过 1 次。
- 缓存命中：同 URL 内容 hash 未变 → 直接返回既有 artifact（details 标 `cache_hit`），`force_refresh` 绕过。

### Steps

- [x] **Step 1: 写失败测试**（全部 mock transport / 本地 HTTP fixture，零真实网络）：artifact put/get 往返与去重；白名单阻断文案；重定向出白名单被拒；网页正文注入文本只作为材料保留、不能改变工具权限或调度；max_bytes 截断标注；限速生效（monotonic 打点断言）；缓存命中与 force_refresh；SourceRecord 最小字段填充与 source_seen 配对；browser transport 接口契约（mock DrissionPage 对象）；DrissionPage 缺失时 http 路径不受影响。
- [x] **Step 2: 实现 artifacts.py 与 http 路径。**
- [x] **Step 3: 实现 browser_bridge（隔离模块）与 hook 装配。**
- [x] **Step 4: Run** → PASS。

---

## 4. Task P3.3: 正文简化器

**Files:**

- Create: `src/knowledgegraph/demand_discovery/tools/page_simplify.py`
- Create: `tests/fixtures/demand_discovery_pages/`（3 个本地 HTML fixture：期刊详情页 / 防务新闻页 / 公众号导出页）
- Test: `tests/test_demand_discovery_page_simplify.py`

### 设计要点

```python
@dataclass
class SimplifiedPage:
    title: str
    headings: list[str]                  # 层级前缀 "H2> xxx"
    lead: str                            # 导语 = 首个实质段落
    paragraphs: list[Paragraph]          # Paragraph = {text, index}
    publish_time: str | None             # 尽力抽取（meta / time 标签 / 正则日期）
    author_or_org: str | None
    text_ref: str                        # 规范化纯文本 artifact 的 ref

def simplify(html: str, artifacts: ArtifactStore) -> SimplifiedPage: ...
```

- bs4 解析；噪声剔除规则移植 simphtml（script/style/noscript/nav/footer/aside、隐藏元素、超短重复列表压缩）；正文主块启发式（最大文本密度块，规则设计对照 trafilatura 的取舍但不引依赖）。
- **偏移定位**：简化后的规范化纯文本（段落以 `\n\n` 连接）落为独立 artifact（`text_ref`）；段落以 `index` 定位。`EvidenceCard.source_location` 约定格式 `"{text_ref}#para:{index}"`——证据回溯 = 取 text_ref 第 index 段比对 excerpt，使讨论文档 250 行"关键判断必须回到原文片段"成为可程序校验的操作。
- 解析失败降级：`soup.get_text()` 全文 + 单段，`degraded=True` 标注。
- 公众号导出页 fixture 取自 `wechat_mp_collector` 实际产物结构（脱敏改写）。

### Steps

- [x] **Step 1: 写失败测试**：三 fixture 的标题/导语/段落抽取快照断言；publish_time 抽取；偏移往返（按 source_location 取回段落 == 原段）；异常 HTML 降级不抛。
- [x] **Step 2: 实现简化器；fetch_page 接线（simplified_ref 进 details，content 摘录来自 lead）。**
- [x] **Step 3: Run** → PASS。

---

## 5. Task P3.4: 检索、精读与摘要工具 + 关键词门禁

**Files:**

- Create: `src/knowledgegraph/demand_discovery/tools/search.py`
- Create: `src/knowledgegraph/demand_discovery/tools/documents.py`
- Create: `src/knowledgegraph/demand_discovery/tools/keyword_gate.py`
- Create: `src/knowledgegraph/demand_discovery/tools/bm25.py`
- Create: `configs/demand_discovery/keyword_gate.yaml`
- Modify: `src/knowledgegraph/demand_discovery/domain/tools.py`（新增 `build_all_tools(store, registry, artifacts, ...)` 总装入口）
- Test: `tests/test_demand_discovery_tool_search.py`
- Test: `tests/test_demand_discovery_tool_read_document.py`
- Test: `tests/test_demand_discovery_keyword_gate.py`

### 设计要点

**search_sources（GPT Researcher retriever 抽象的本地化）：**

```python
class SearchAdapter(Protocol):
    async def search(self, query: str, page: int) -> list[SearchHit]: ...
# SearchHit = {title, url, snippet, source_id?, source_tier, published?}

# 适配器实现：
# - UrlTemplateAdapter：白名单 search.template 渲染 → fetch（走 P3.2 限速/缓存）→
#   结果页解析器（每信源一个解析函数，置 search.py 内 SITE_PARSERS 表；
#   docs/collection/ 各站点方案是解析器的规格来源）
# - LocalCorpusAdapter：BM25 检索 data/raw/ 已采集库 + artifact 文本库
# 工具行为：按白名单 search_entries 并发查询（≤3 信源/次）→ 归一化合并 →
#   keyword_gate 打分排序 → content 输出 top-N 行（title｜tier｜date｜score｜url），
#   details 全量；不产生 domain proposal（SourceRecord 由 fetch_page 建立）
```

**BM25（`bm25.py`，约 60 行，按 rank_bm25 的 Okapi 公式自实现，k1=1.5、b=0.75）**：中文分词不引 jieba，用字符 bigram 词元（标题/短文本场景下精度足够，docstring 注明取舍与未来替换点）。

**read_document（pi read.ts 形态）：**

```python
# 参数: {"artifact_ref": str, "offset": int=0, "limit": int=40}   # 段落粒度
# content: 第 offset..offset+limit 段正文 + 每段 source_location + 截断时"剩余 N 段，可带 offset 继续"提示
# details: {total_paragraphs, returned_range, truncated}
# 不产生 proposal；trace 由证据卡创建时回指 source_location
```

**extract_summary：** 对 artifact 生成模型摘要时，工具在 details 强制 `summary_source="model_generated"`；若用于回填 SourceRecord.summary_text，domain proposal 同步带该标记。配套校验（落在 `create_evidence_card`）：`excerpt` 为空 ⇒ details 加 `warning: no_excerpt`（auditor 量表 `evidence_traceable` 项据此审，工具层不硬拒——保留弱证据登记能力，符合讨论文档"model_generated 仅作阅读辅助"的分级而非禁止）。

**keyword_gate（讨论文档 232-247 行的程序化）：**

```yaml
# configs/demand_discovery/keyword_gate.yaml
categories:
  demand:   ["需求", "能力需求", "亟需", "迫切", "牵引"]
  gap:      ["短板", "不足", "瓶颈", "难以", "受限", "制约", "挑战"]
  scenario: ["作战运用", "任务场景", "演训", "对抗", "复杂环境"]
  change:   ["演变", "趋势", "新威胁", "新样式", "新形态"]
  equipment:["装备现状", "体系建设", "能力生成", "保障", "部署"]
  residual: ["仍然", "尚未", "难以满足", "有待提升", "局限"]
```

`score(text) -> {"score": int, "hits": {category: [词]}}`；用于 search 结果排序与 fetch 后的分流提示（details.keyword_hits），**只作低成本门禁信号，不做硬过滤**（讨论文档明示"不能作为唯一标准"）。

**工具→角色挂载**：`build_all_tools()` 注册全集；reader agent 定义（P2.2）的 tools 列表此时回填真实工具名。

### Steps

- [x] **Step 1: 写失败测试**：BM25 排序正确性（人工小语料）；UrlTemplateAdapter mock fetch 解析；多信源合并排序与 keyword 加权；read_document 分页/越界/继续提示；extract_summary 标记传导；keyword_gate 命中分类。
- [x] **Step 2: 实现 bm25 / keyword_gate / search / documents。**
- [x] **Step 3: build_all_tools 总装 + reader.md 工具名回填 + 全量回归。**
- [x] **Step 4: Run** → PASS。

---

## 6. Task P3.5: 真 provider 冒烟、SSE 真流式与 usage 接线

**Files:**

- Modify: `src/knowledgegraph/demand_discovery/llm/responses_adapter.py`（P1.5 真流式在此落地）
- Modify: `scripts/demand_discovery_demo.py`
- Create: `docs/experiment-artifacts/demand_discovery_real_provider_smoke.md`
- Test: `tests/test_demand_discovery_responses_adapter.py`（追加）

### 设计要点与执行清单

1. **真流式**：按 Phase 1 计划 P1.5 设计实现（线程逐行 → `call_soon_threadsafe` → asyncio.Queue → 增量解析即时 push）。
2. **usage 接线**：SSE `response.completed` 的 usage（input/output/cached tokens）写入 `AssistantMessage.usage`，离线 mock 断言 RunBudget 计费正确（cached 区分，不与 input 重复计——复用分析 7.5 节测试要求）。
3. **最小冒烟前置（人工触发，非 CI）**：不等待 P3.1-P3.4 全部完成；P1.3 预算接口与 adapter 离线测试具备后，即先验证真实 endpoint 的基本兼容性，避免在站点工具完成后才发现协议不兼容。按序执行并将结果写入冒烟记录文档：
   - `--dry-run-provider-request` 两种 mode 的 URL/payload key/脱敏检查；
   - `responses_compatible` 一次无工具真实响应；
   - `responses_compatible` 一次最小工具调用响应（fake/local 工具即可，验证工具调用、流式、usage）；
   - `codex_backend` 验证第三方 URL 对 `/codex/responses` 规范化与 Codex 专属 header 的真实兼容性（复用分析 7.5 节的全部假设逐条打勾/打叉）；不兼容项回改 adapter 并补离线回归测试。
4. **完整端到端冒烟**：P3.1-P3.4 与 P2 worker 主链路具备后，再跑真实白名单信源专题调研，作为 M-LR3 证据。
5. 冒烟记录文档模板：endpoint mode / 模型 / 各假设验证结果 / 截获的差异 / adapter 修改清单 / 留存的脱敏请求摘要。完成后更新 `docs/README.md` 实验过程产物索引。

### Steps

- [x] **Step 1: 真流式 + usage 离线测试 → PASS。**
- [x] **Step 2: 冒烟执行与记录文档入库。**
- [x] **Step 3: 全量离线测试回归 → PASS。**

---

## 7. 验收门禁（M-LR3，与 Phase 2 合流）

- [x] 全量离线测试 PASS；新增 fixture 与 mock 不触网（CI 可重复）。
- [x] 端到端真实调研演练（人工触发）：真 provider + 白名单信源，orchestrator 派发 reader 完成一个小专题（如低空探测），产出含骨架报告；`DomainTraceStore.get_report_trace(report_id)` 重建 source→evidence→candidate→audit→report 链；演练产物（报告 + trace 导出 + progress.md）存 `outputs/runs/`，结论补记到冒烟记录文档。已完成修正后复跑 `outputs/runs/phase3-mlr3-real-fixture-006`，`trace.jsonl` 10 条，report trace 9 条，3 条 evidence 均使用 `src-f62b271ccaa5` 与 `text:4df8a10fb70bf552#para:0`。修正要求：同一 `audit_id` 不允许改写不同结论，report trace 对重复 `audit_completed` 只保留最新事件；fetched page 证据必须使用 `fetch_page` 返回的 `source_id` 和 `simplified_ref#para:n`。
- [x] 演练中验证：白名单外 URL 被阻断且模型按文案提出"建议新增信源"而非重试。已完成 fake harness 演练 `outputs/runs/phase3-whitelist-external-url-exercise-001/whitelist_external_url_exercise.json`：`fetch_attempt_count=1`，`suggested_source=true`。

## 8. Self-Review

- transport 选型从 TMWebDriver 移植改为 DrissionPage attach，依据是仓库内已有两个生产采集器的成功先例——少移植 280 行外部代码，且与既有采集 SOP 经验连续。
- 站点解析器（SITE_PARSERS）是本阶段最大的持续维护面，已通过"每信源一个纯函数 + docs/collection 方案作规格"控制散度；解析失败降级为 LocalCorpus 检索，不阻塞调研。
- BM25 字符 bigram 是精度/依赖的折中，检索质量若成瓶颈，替换点已隔离在 `bm25.py` 单文件。
- 全文不进上下文、错误保留在上下文、白名单硬边界——三条不变式均有测试锁定。
