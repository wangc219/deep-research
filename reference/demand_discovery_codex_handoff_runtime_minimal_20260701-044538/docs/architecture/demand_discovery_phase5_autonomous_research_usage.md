# Demand Discovery Phase 5 Autonomous Research Usage Guide

日期：2026-06-16

本文说明当前需求挖掘模块 Phase 5 的交付能力、运行方式、输出产物、门禁规则和打包内容。它面向后续接手开发、真实 smoke 和人工复盘使用，不包含 API Key、私有 endpoint 或运行产物全文。

## 1. 已完成能力

### 1.1 Topic-only 自治调研入口

用户只需要输入调研方向 `topic`，无需提供 seed URL。系统会从 `configs/demand_discovery/source_whitelist.yaml` 中选择 A/B 级公开 HTTP 信源，生成 source strategy，并进入 round-level controller。

入口函数：

```python
run_autonomous_research(
    mode,
    topic,
    output_root,
    run_id,
    max_rounds,
    seed_urls=None,
    allow_browser=False,
)
```

CLI：

```text
python scripts\demand_discovery_autonomous_research.py --mode fake --topic "<调研方向>" --run-id <run-id> --max-rounds 2
python scripts\demand_discovery_autonomous_research.py --mode real --topic "<调研方向>" --run-id <run-id> --max-rounds 2 --allow-browser --api-key-env DEMAND_DISCOVERY_API_KEY --base-url <endpoint> --model <model>
```

### 1.2 Phase 5 round-level controller

真实路径已经进入 Phase 5 controller，而不是旧的 seed URL runner 或 fake loop。流程为：

```text
source_strategy
-> ResearchRound
-> ReadingQueue / ResearchLead
-> network worker
-> worker report import
-> judge / JudgementReport
-> stop_or_continue
-> candidate_synthesis
-> audit
-> report gate
-> report
```

controller 支持：

- 至少两轮 fake loop 验证。
- real mode 调用 network worker round。
- 第二轮消费上一轮 `next_round_plan`。
- 程序化停止条件，包括 max rounds、无新增强证据、blind spot 需要人工、连续无新增 source 等。
- 停止后必须先执行 candidate synthesis，再进入 audit/report gate。

### 1.3 研究状态领域对象

新增并持久化：

- `ResearchLead`：文章、文献、入口、跳过 URL、失败 URL 的可审计线索。
- `ReadingQueue`：每轮 selected/skipped/failed lead 队列。
- `ResearchRound`：每轮 hypothesis、worker 报告、judge 结论、下一轮计划和停止原因。
- `JudgementReport`：跨 worker 综合，包括共识、矛盾、部分覆盖、独特见解、盲点、证据强度图、下一轮计划和停止/继续决策。

`DomainStore` 支持 JSONL export/load，context pack 会渲染近期轮次和 compact research state，不把全文 HTML 塞进上下文。

### 1.4 白名单与通用网络工具

白名单仍是网络访问边界。白名单外 URL 不抓取，只记录 skipped lead 或建议新增信源。

已复验可访问入口：

- 中国军网：`http://www.81.cn/`
- 现代防御技术：`https://www.xdfyjs.cn/CN/article/showBrowseTopList.do`
- RAND：`https://www.rand.org/topics/uncrewed-aerial-vehicles.html`
- CSIS：`https://www.csis.org/topics/defense-and-security`
- Defense News：`https://www.defensenews.com/unmanned/`

网络工具能力：

- `fetch_page` 使用浏览器形态通用请求头，避免公开网页因脚本 UA 返回 403。
- `search_sources` 支持本地 artifact、URL 模板搜索和通用 JS 后端 API 发现。
- 对 81.cn 的站内检索不是站点特化分支，而是通过搜索页 JS 发现 `mil-search.81.cn/api-surface/es/docSearchEasy`，解析请求参数对象后请求 JSON API。
- JSON API helper 使用通用浏览器头，并设置 `Accept: application/json,text/plain,*/*` 与 `X-Requested-With: XMLHttpRequest`。
- 搜索结果会按 query relevance、keyword gate、source tier 排序。
- source strategy 会为每个 selected source 生成 `planned_queries`，并按 `content_languages` 选择查询语言：中文站点使用中文 topic/压缩词，英文站点使用英文 topic 查询词。
- 默认白名单不再写入静态主题 `default_queries`。查询词必须由用户 topic、当前 hypothesis、worker findings 或上一轮 `next_round_plan` 派生，避免非 UAV topic 被配置兜底词拉回 UAV/防空方向。
- real worker 会收到 source guidance，包括 source name、URL、`content_languages` 和 `planned_queries`；寻找后续调研网站或文章线索时，也应按目标站点语言构造查询。

### 1.5 页面发现、文档下载和受控浏览器

工具面包括：

- `classify_source_page`：分类 article/listing/site_home/search_page/download_document/unknown。
- `discover_articles`：从栏目页发现白名单内文章，写 `ResearchLead` 和 `ReadingQueue`；白名单外链接写 skipped lead，不生成 EvidenceCard。
- `download_document`：支持 HTML/TXT/PDF 转 readable artifact；DOC/DOCX 首版只保存 raw artifact 和元数据。
- `read_document`：按段落窗口读取正文 artifact。
- `browser_observe`：扫描白名单页面或已登记 `OpenSourceLead`（且所属 `OpenSearchPlan` 仍 active）范围内的开放来源页面，返回压缩页面状态、候选正文/列表/下载/分页区域、same-site API candidate、风险 flags 和稳定 `observation_ref` / `target_id`。
- `browser_execute`：统一执行受控 target action 或审计型 JavaScript。target action 只能引用 observe 返回的 `target_id`；JavaScript 必须引用 `observation_ref`、说明 intent 和 expected_result，并由 runtime guard 强制 same-origin、no credentials、read-only 和 URL scope。
- `capture_current_document`：作为 `browser_execute` 的 target action 保存当前页面 artifact，不直接生成 EvidenceCard；后续仍需 `read_document`，开放来源还需 `SourceQualityAssessment`。
- `BrowserRecipeDraft`：成功的同源只读 JavaScript/API 探索会保存 script artifact、return artifact、sanitized network delta 和 draft recipe；人工审计通过前不能进入稳定 SourceProfile，也不能绕过证据门禁。

导航页、栏目页、搜索页不能直接形成强证据。`EvidenceCard` 必须来自文章正文或下载文献正文。

### 1.6 Judge、candidate synthesis、audit 和 report gate

judge 不替代 auditor。职责划分为：

- judge：跨 worker 综合，产出共识、矛盾、部分覆盖、独特见解、盲点和下一轮计划。
- candidate synthesis：只从已有 judgement 与 evidence 引用合成候选需求。
- auditor：逐条 EvidenceCard 判断是否语义支撑 candidate/report 核心结论。
- report gate：根据 audit 结论和 evidence-support scorecard 决定 `review_ready`、`needs_revision`、`watchlist` 或 `rejected`。

当前 gate：

- 必须有 stopped `JudgementReport`。
- `review_ready` 必须有 approved audit；`needs_revision` / `watchlist` 可携带非 approved semantic audit 落盘，但必须保留审计意见和必要返工。
- 必须有 `EvidenceCard`，且至少一条来自文章正文或下载文献正文。
- `review_ready` 需要 direct evidence，或两条以上来自不同 source/body artifact 的 partial evidence 且 audit 明确推理链。
- adjacent/weak/unassessed evidence 可以形成降级报告，但不能支撑正式核心结论。
- 未解释关键 contradiction 时，报告 `review_status` 降为 `needs_revision`，但仍可写报告。
- 因白名单尚不完善，source tier cap 已放宽为 A/B 级证据均可进入 `DemandReport`；C 级仍只能到 `researchable_signal`，D 级仍为 discard。
- `report.md` 用户可见正文使用中文标题和中文分析表述；外文 source title、excerpt 和 quoted text 可按来源原文保留，front matter 保留机器可读字段名。

### 1.7 Audit 语义证据审查

真实 autonomous path 不再程序化构造 approved audit。candidate synthesis 之后会调度 auditor worker，输入 AuditContextBundle，其中包含 candidate、judgement、EvidenceCard、source tier、开放来源质量、worker self-check 和报告核心结论草案。auditor 必须通过 `run_audit` 写入 `scorecard.evidence_support.evidence_reviews`。

`review_ready` 需要 direct evidence，或两条以上来自不同 source/body artifact 的 partial evidence 且 audit 明确推理链。adjacent/weak/unassessed evidence 可以形成 `needs_revision` 或 `watchlist` 报告，但不能支撑正式核心结论。fake mode 的 audit 是 fixture audit，trace 中标记 `audit_mode=fixture`。

### 1.8 真实 provider 连接恢复

真实 network worker 的 provider timeout 为 180 秒，`max_retries=2`。Streaming 请求在尚未向 agent loop 产出任何语义事件前，如果发生连接重置、远端关闭或同类 transient transport error，会按退避重试。若已经产出文本或工具调用事件，则不自动重试，避免重复执行工具。

真实 worker 的检索语言和分析语言分开处理：中文站点用中文查询，英文站点用英文查询；`findings`、`EvidenceCard.claim`、`EvidenceCard.evidence_summary`、`open_questions`、`risks` 等分析输出要求使用中文。若外文共识仍进入 candidate synthesis，候选需求会用 `ResearchRound.topic` 生成中文兜底表述，原始外文仍保留在证据和 worker 记录中。

已排查的 `WinError 10054` 发生在 LLM provider 请求阶段，不是网页抓取阶段。该问题通常来自远端服务、代理或网络链路重置；旧实现将 network worker provider 的 `max_retries` 固定为 0，导致一次瞬时连接重置直接终止。因此根因判断是：外部链路抖动触发，系统设计上缺少真实 worker provider 重试放大了失败。

## 2. 使用方式

### 2.1 离线 fake 验收

fake mode deterministic，不需要 API Key，也不访问真实网页：

```text
python scripts\demand_discovery_autonomous_research.py --mode fake --topic "低空小型无人机威胁下的探测、预警与防护能力缺口" --run-id phase5-autonomous-fake-001 --max-rounds 2
```

主要产物：

```text
outputs/runs/phase5-autonomous-fake-001/round_summary.json
outputs/runs/phase5-autonomous-fake-001/domain.jsonl
outputs/runs/phase5-autonomous-fake-001/trace.jsonl
outputs/runs/phase5-autonomous-fake-001/report.md
```

验收重点：

- 至少 2 个 `ResearchRound`。
- `ReadingQueue` 有 selected/skipped/failed 可审计记录。
- `JudgementReport` 包含共识、矛盾、部分覆盖、独特见解、盲点和下一轮计划。
- trace 可重建 `judgement -> candidate_synthesis -> audit -> report`。

### 2.2 真实 real smoke

real mode 需要真实 provider 配置和网络访问。不要把 API Key 写入仓库；用环境变量或 `.env`。

当前需求挖掘真实链路默认按 `gpt-5.5` 使用：`DEMAND_DISCOVERY_MODEL` 未设置时 fallback 为 `gpt-5.5`；Responses-compatible 请求默认携带 `reasoning.effort=xhigh`；默认角色 token budget 为 240000，报告上下文 `ContextPack.token_budget` 为 200000，默认 compaction window 为 256000。若 endpoint 不支持 `xhigh`，应显式覆盖 provider 配置或在兼容层处理，而不是把主线默认降回低思考强度。

```text
python scripts\demand_discovery_autonomous_research.py --mode real --topic "低空小型无人机威胁下的探测、预警与防护能力缺口" --run-id phase5-autonomous-real-smoke-<n> --max-rounds 2 --allow-browser --api-key-env DEMAND_DISCOVERY_API_KEY --base-url <from env> --model <from env> --endpoint-mode <from env> --endpoint-path <from env or empty>
```

`--allow-browser` 会把受控 `browser_observe` / `browser_execute` 下传给真实 network worker。不开启时仍可使用 HTTP 抓取、搜索、下载和正文读取。浏览器工具的 URL scope 来自白名单入口、已登记 `OpenSourceLead`（且所属 `OpenSearchPlan` 仍 active）或人工 seed；JS 只能作为审计型升级路径使用，成功后生成可审计 script artifact、return artifact、trace 和 `BrowserRecipeDraft`。

### 2.3 主链路入口

旧 Phase 3 seed URL runner 和 `scripts/demand_discovery_network_research.py` 已移除，不再作为兜底入口保留。Phase 5 统一通过 `scripts\demand_discovery_autonomous_research.py` 进入，真实取证轮由 `src\knowledgegraph\demand_discovery\network_research.py::run_network_worker_round` 执行。

### 2.4 Reporter Agent 与 ReportContextPipeline

真实 autonomous report 不再由 `_render_autonomous_report_body()` 拼接正文。流程为：audit 之后构建 `ReportContextCandidatePool`，`context_curator` agent 做材料策展，`ContextVerifier` 校验引用和 audit 权限，`reporter` agent 使用 `generate_demand_report` 写中文报告，随后由 consistency gate 和 `ReportPublisher` 发布。

模型/工具调用失败、context verifier 失败或 consistency gate 失败时，真实 path 直接失败报告阶段，不生成 `DemandReport`。audit 不通过、证据不足或矛盾未解决属于正常业务结果，仍由 reporter 生成解释性报告，并以 `needs_revision/rejected/watchlist` 等既有状态入库。

`ReportPublisher` 只发布已经入库且通过 gate 的报告：`report.md` 是面向人读的正文，不默认堆叠 report id、candidate id、evidence ids、trace ids 等控制字段；`report_manifest.json` 记录机器审计字段、状态、引用 id 和 lineage refs。publisher 不写结论、不润色正文、不把不足证据改写成通过。

## 3. 输出与审计

每个 autonomous run 默认写入：

- `round_summary.json`：source strategy、轮次摘要、candidate synthesis、audit/report 摘要、network worker run 列表。
- `domain.jsonl`：SourceRecord、EvidenceCard、CandidateDemand、AuditReport、DemandReport、ResearchLead、ReadingQueue、ResearchRound、JudgementReport、DomainTraceEvent。
- `trace.jsonl`：可程序化重建 lineage 的领域事件。
- `report.md`：最终人读报告正文。
- `report_manifest.json`：report id、candidate/audit/context/evidence/trace refs、review_status 和发布时间等机器审计字段。
- `run_config.json`：脱敏运行配置。

追溯路径应能看到：

```text
source_strategy
-> leads
-> reading_queue
-> evidence
-> worker_reports
-> judgement
-> candidate_synthesis
-> audit
-> report_context_indexed
-> report_context_curated
-> report_context_verified
-> report
-> report_published
```

## 4. 白名单维护

配置文件：

```text
configs/demand_discovery/source_whitelist.yaml
```

新增或修正信源时至少关注：

- `source_name`
- `source_tier`
- `source_type`
- `hosts`
- `path_prefixes`
- `fetch_transport`
- `entry_urls`
- `topic_tags`
- `content_languages`
- `interaction_profile`
- `requires_login`
- `max_discovery_depth`
- `search`

维护规则：

- 入口 URL 必须能被 `SourceRegistry.match()` 命中。
- 白名单外 URL 不能抓取。
- 首批 topic-only source strategy 优先选择 A/B 级、公开 HTTP、无需登录、有 entry URL 的信源。
- source strategy 以 topic match 排序为主，不再为了 source type 多样性牺牲主题相关性。
- `topic_tags` 描述信源的通用覆盖面，不能把所有信源都标成某一个默认需求方向。
- `content_languages` 描述站点正文和站内检索的主要语言，当前支持 `zh` / `en`；该字段会影响 planned query 语言。
- 默认白名单不配置静态 `default_queries`；如果未来需要临时 fallback query，应由 source strategy / worker 根据当前 topic 和上一轮 judgement 动态生成。
- 真实可访问性只做人工 smoke，不进 CI。

## 5. 验证命令

定向测试：

```text
python -m unittest tests.test_demand_discovery_source_registry tests.test_demand_discovery_autonomous_research_runner tests.test_demand_discovery_tool_fetch_page tests.test_demand_discovery_tool_search -v
```

全量需求挖掘测试：

```text
python -m unittest discover -s tests -p "test_demand_discovery*.py" -v
```

编译检查：

```text
python -m compileall -q src\knowledgegraph\demand_discovery scripts\demand_discovery_autonomous_research.py
```

## 6. 打包内容

建议压缩包包含：

```text
src/knowledgegraph/demand_discovery/
scripts/demand_discovery_autonomous_research.py
configs/demand_discovery/
tests/test_demand_discovery*.py
tests/fixtures/demand_discovery_pages/
docs/architecture/demand_discovery_phase5_autonomous_research_loop_plan.md
docs/architecture/demand_discovery_phase5_autonomous_research_usage.md
docs/experiment-artifacts/demand_discovery_phase5_autonomous_research_smoke.md
docs/README.md
src/README.md
tests/README.md
configs/README.md
```

不建议包含：

- `outputs/runs/` 真实运行产物。
- API Key、私有 endpoint、cookies、浏览器 profile。
- `.git/`、`__pycache__/`、`.pytest_cache/`。

## 7. 当前限制

- 白名单仍不完整，部分甲方表中来源还缺少已复验公开入口。
- 真实报告质量仍取决于 A/B 级正文证据覆盖；B 级可出报告不代表自动通过人工复核。
- DOC/DOCX 首版只保存 raw artifact 和元数据，不从中生成强证据。
- 浏览器工具是受控 observe/execute，不是开放浏览器自动化代理。
- 真实 provider 的输出质量、搜索策略和网页可用性会影响 round 结果；真实 smoke 必须人工复盘。
