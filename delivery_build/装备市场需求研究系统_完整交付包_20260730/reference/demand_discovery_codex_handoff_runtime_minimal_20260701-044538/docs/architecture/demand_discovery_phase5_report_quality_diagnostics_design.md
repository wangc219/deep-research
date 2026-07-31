# Demand Discovery Phase 5 报告质量诊断与补强设计

日期：2026-06-23

## 1. 背景

Phase 5 真实调研已经能进入 round-level controller，调用网络工具，生成 judgement、candidate synthesis、audit 和 report trace。但非默认主题真实 run 暴露出报告质量问题：证据覆盖不足、相邻主题证据被过度使用、judge 下一轮计划泛化、worker 缺少自主补证循环、报告正文过短，以及真实 provider/network failure 难以归因。

这些问题不适合拆成分散文档。本文件统一记录七个诊断方向，每个方向包含问题、设计、测试和验收，作为后续实施计划输入。

## 2. 诊断一：开放搜索与准入治理

### 问题

当前系统主要依赖白名单入口、站内搜索和本地 artifact。非默认 topic 容易只找到相邻材料，或被少数可访问 source 牵引。白名单的价值是提供优先可信源和质量基准，但它不应成为唯一资料边界；否则白名单不足时，agent 无法完成广度优先资料搜集。

### 设计

新增开放搜索能力，但它不是默认第一步。系统必须先进行白名单内调研；当白名单内已无法获取更多有效正文证据，且候选需求仍不足以完成证据搜集时，controller 才触发开放搜索。

开放搜索路径允许读取公开网页正文，但读取后不能直接形成正式证据，必须先通过来源质量评估，并在 audit 中完成语义证据支撑审查：

```text
whitelist_first_research
-> judge confirms evidence gap
-> OpenSearchPlan
-> open_search_sources
-> OpenSourceLead
-> fetch/read public body
-> SourceQualityAssessment
-> audit evidence-support review
-> accepted/provisional/background/rejected
```

`open_search_sources` 返回：

- title
- url
- snippet
- source_domain
- search_provider
- query_used
- provisional_relevance_reason
- source_scope: `whitelisted | open_web | excluded`
- broad_search_trigger_id

规则：

- `whitelisted` URL 进入现有白名单 fetch/read 流程。
- `open_web` URL 可在 OpenSearchPlan 范围内抓取公开正文，但必须通过 `SourceQualityAssessment` 后才能作为证据候选。
- `excluded` URL 只记录，不抓取，不进入候选。

新增 `OpenSourceLead`：

- `candidate_id`
- `run_id`
- `topic`
- `url`
- `domain`
- `source_name_guess`
- `reason`
- `search_query`
- `seen_in_round_id`
- `source_scope`: `open_web`
- `quality_status`: `pending | accepted | provisional | background_only | rejected`，这是 lead 级 bucket/cache；权威质量等级以最新 `SourceQualityAssessment.quality_level` 为准。

新增 `SourceQualityAssessment`：

- `assessment_id`
- `url`
- `domain`
- `source_identity`
- `publisher_or_org`
- `author`
- `publish_time`
- `is_original_source`
- `citation_or_reference_signal`
- `content_type`
- `quality_level`: `trusted | usable | provisional | low_quality | rejected`
- `risk_flags`
- `reason`

质量规则：

- 白名单 A/B source 默认进入 `trusted/usable` 起点，但仍要检查正文可追溯性。
- 开放来源必须明确 publisher、正文、日期或来源链；无法识别发布者、论坛传闻、社媒碎片、转载拼接、营销页、聚合页进入 `low_quality/rejected`。
- `trusted/usable` 可进入正式证据候选。
- `provisional` 必须交叉验证后才能支撑核心结论。
- `background_only` 只能写背景，不支撑 candidate。
- `rejected` 不进入 evidence refs。

白名单内调研优先级：

1. QueryPlanner 读取 SourceProfileIndex 和选中 source profile。
2. worker 优先完成白名单 source 的 search/fetch/read。
3. judge 判断是否仍缺 direct/partial 正文证据。
4. 若缺口存在且白名单内 route/query 已无新增有效结果，生成 OpenSearchPlan。
5. 广搜结果进入开放来源质量评估，而不是被无条件信任。

### 测试

- 未满足 OpenSearchPlan 触发条件时，open search 不会执行。
- whitelisted result 可进入 ReadingQueue，但不能直接生成 EvidenceCard。
- open_web result 可抓取公开正文，但必须先生成 SourceQualityAssessment。
- low_quality/rejected source 不能生成 EvidenceCard。
- provisional source 只能生成 provisional evidence，不能单独支撑 core conclusion。
- open search failure 不终止 run，judge 记录 blind spot。
- trace 能重建 whitelist research -> evidence gap -> broad search -> source quality gate -> audit evidence-support review。

### 验收

非默认 topic 会优先使用白名单资料；当白名单内无法补足证据时，系统能启动广搜并读取公开正文，同时通过来源质量评估过滤低质信息。报告必须区分白名单证据、开放来源可信证据、provisional evidence 和 background signal。

## 3. 诊断二：通用浏览器调研能力

### 问题

现有 `browser_observe` / `browser_action` 是受控工具，但还不是强研究型浏览器 agent。真实网站中的 JS 请求、动态列表、异步搜索、状态页和下载流程，不能靠每个网站写特化方法长期维护。

更深层问题是工具设计没有充分利用强模型的页面理解能力。当前工具把模型限制在少数预设动作里，导致 worker 即使看到了搜索框、动态按钮、分页、XHR 线索，也无法主动写小段脚本验证页面行为、抽取动态结果或归纳通用访问方法。结果是系统只能在“HTTP 抓取成功”和“站点专用适配器已存在”之间二选一，缺少可审计、可复用、可逐步沉淀的通用浏览器探索层。

### 设计

#### 3.0 修复结论：模型自主决策 + 最小硬边界

诊断二的修复方向不是继续扩展固定 `js_use_case` 枚举，也不是把浏览器 JS 做成不断补丁式的安全规则库。最新共识是：worker 应拥有更大的网页研究决策权，系统负责把当前研究现场、页面状态、授权范围和证据门禁清晰呈现给模型，让模型自行决定搜索、点击、翻页、回退、换关键词、下载、使用 browser 或写 JS。

系统仍保留少量不可协商的运行边界：

- 不读取或返回 cookie、localStorage、sessionStorage、IndexedDB、password/hidden auth 字段等凭证或身份数据。
- 不绕过登录、验证码、付费墙、robots、反爬或访问控制。
- 不执行写操作、destructive HTTP method、批量 endpoint 探测或越权跨域访问。
- 不允许 DOM 篡改后把篡改页面保存为正文 artifact。
- 不允许 JS 返回值、搜索摘要、动态列表或 API JSON 直接生成 EvidenceCard。
- 不允许越过白名单、已登记 OpenSourceLead（且所属 OpenSearchPlan 仍 active）或人工 seed 形成的 URL scope。

JS 的控制重点从“枚举模型能写哪类脚本”转为“模型为什么需要 JS、当前基于什么页面事实、预期得到什么、结果进入哪条后续链路、是否留下可审计记录”。因此第一版不强制新增封闭 `js_use_case` 字段；如需结构化归档，工具层可以从 `intent`、`expected_result`、`network_delta` 和输出类型推断少数 `allowed_effect` bucket，例如 DOM 只读、同源公开 API 探测、页面状态诊断、动态链接发现或 recipe 草稿。该 bucket 只用于统计和审计，不作为模型行动空间的主要限制。

为了让模型能自我约束，`browser_execute(javascript)` 调用前后必须让模型看到并记录：

- 当前 worker objective、acceptance criteria、证据缺口和剩余预算。
- 当前页面类型、可见正文摘要、搜索框/按钮/分页/下载目标、same-origin API candidate、access/status 风险信号。
- 已尝试的 HTTP/search/read/browser 路径，以及为什么普通工具或 `target_action` 不足。
- `observation_ref`、可选 target/api/form refs、当前 URL scope 和 source/open-search plan/lead 归因。
- 本次 JS 的 `intent`、`expected_result`、失败后的 fallback，以及结果只能进入 lead/artifact/diagnosis/recipe，不能直接进入 EvidenceCard。
- `script_ref`、`script_hash`、`return_artifact_ref`、`network_delta`、before/after URL/title、页面变化摘要和模型对结果的解释。

这使 JS 成为“可审计研究动作”：模型负责决策和解释，工具负责执行、压缩反馈和写 trace，harness 负责保存状态、预算和底线约束，judge/auditor/reporter 通过 trace 判断该路径是否可信。

#### 3.1 设计原则

吸收 GenericAgent 的经验：浏览器工具面保持很小，但每次观察和动作反馈必须足够强。GA 的核心不是为每个网页写专用函数，而是用 `web_scan` 压缩页面状态，用 `web_execute_js` 执行模型生成的 JS，并返回 DOM 变化、URL 变化、新 tab、瞬时文本和错误信息，让模型在多轮中自我修正。

本模块采用相同方向，但加上需求挖掘的证据治理：

- 默认先走 HTTP/search/download/read_document；需要真实交互时再进入 browser。
- browser 工具只负责发现、交互、捕获正文或下载入口，不直接生成强 EvidenceCard。
- 通用工具优先于站点特化方法；SourceProfile 只描述网站路由、搜索方式和证据规则，不写不可迁移的 scraper。
- 模型可以在工具不足时写真实 JS，但 JS 是审计型升级路径，不是默认动作。
- 模型是否写 JS 由当前研究状态和页面观察决定；系统不把 JS 用途做成封闭枚举，而是要求模型说明意图、预期结果、普通工具不足的原因和结果去向。
- 成功的 JS 探索要沉淀为 `BrowserRecipeDraft`，经人工审计后进入 SourceProfile 或被抽象成新通用工具。

#### 3.2 工具面收敛

浏览器层保留两个核心工具，避免 `click/fill/select/extract/api_probe` 等大量重叠 schema 挤占上下文。

`browser_observe` 相当于页面扫描：

`browser_observe` 增加：

- `observation_ref`
- `url`
- `title`
- `visible_text_digest`
- `article_candidates`
- `listing_candidates`
- `forms`
- `buttons`
- `download_targets`
- `pagination_targets`
- `network_api_candidates`
- `access_status`
- `top_targets`
- `page_risk_flags`
- `suggested_interaction_modes`

`network_api_candidates` 只暴露 method、same-site URL、query/body keys、response content type、sample result count 和 inferred purpose，不暴露 cookies、authorization headers、完整响应体或敏感 header。

`browser_execute` 替代扩大后的 `browser_action`，统一承载两类动作：

```json
{
  "session_id": "string",
  "observation_ref": "string",
  "intent": "用中文说明本次动作要验证什么",
  "mode": "target_action | javascript",
  "target_action": {
    "action": "click_link | fill_input | submit_form | next_page | download_link | activate_button | capture_current_document",
    "target_id": "string",
    "value": "string?"
  },
  "javascript": {
    "script": "string",
    "expected_result": "string",
    "allow_network_probe": false
  },
  "max_wait_ms": 5000,
  "max_return_chars": 4000
}
```

`target_action` 仍然只允许引用上一次 `browser_observe` 返回的 `target_id`：

- `click_link`
- `fill_input`
- `submit_form`
- `next_page`
- `download_link`
- `activate_button`
- `capture_current_document`

`capture_current_document` 用于把当前文章正文、搜索结果页或下载页保存为 artifact。它不能直接生成 EvidenceCard；后续仍要走 `read_document`，开放来源还要走 `SourceQualityAssessment`，最终由 audit 进行 evidence-support review。

#### 3.3 审计型 JS 升级通道

允许模型写真实 JS 的触发条件：

- 已经有一次 `browser_observe`，模型看到了页面结构和可交互目标。
- HTTP 抓取、站内搜索、`target_action` 无法完成任务，或页面明显依赖动态 JS/XHR。
- worker 明确给出 `intent` 和 `expected_result`，例如“识别搜索表单提交后结果列表的 DOM 区域”。
- worker 说明普通工具不足的原因、结果后续去向和失败后的 fallback；这三项可以是自然语言，不要求维护封闭枚举。
- 当前 URL 处于选中的白名单 source、已登记 OpenSourceLead（且所属 OpenSearchPlan 仍 active）的 URL scope，或人工 seed URL 约束范围内。
- 运行处于公开资料调研场景，不涉及登录、付费、访问控制绕过或凭证读取。

JS 能做的事：

- 读取当前可见 DOM、表单状态、链接和按钮文本。
- 触发用户可见的公开只读检索、输入、滚动、加载更多和分页类交互。
- 观察页面内已有的公开 JSON 数据、`script[type=application/json]`、SSR hydration state。
- 对 same-origin 公开 endpoint 做小预算探测；默认使用 `credentials: "omit"`，不能携带 cookie、authorization 或本地存储 token。
- 返回结构化结果、候选链接、候选正文区域、下载 URL 或 API pattern。

JS 禁止事项：

- 读取或返回 cookie、localStorage、sessionStorage、IndexedDB 中的凭证、token、用户身份数据。
- 读取 password/hidden auth 字段，绕过验证码、登录、付费、robots 或访问控制。
- 发起不受控跨域 fetch，批量扫描 endpoint，或执行破坏性 HTTP 方法。
- 修改白名单、预算、系统提示、工具权限或本地文件。
- 把导航页、搜索页、列表页内容直接升级为强证据。

执行层必须强制：

- 脚本长度、运行时间、网络请求数、返回字符数上限。
- 在页面 runtime 内包装 `fetch`、`XMLHttpRequest`、cookie/storage 和 password/hidden 敏感表单字段等高风险能力；字符串 denylist 只能作为提前失败优化，不能作为安全边界。首版不继续追逐完整 JS sandbox 逃逸封堵，导航/DOM 副作用必须通过 URL scope 复验、trace 审计和证据链隔离处理。
- `fetch` 默认并强制 `credentials: "omit"`；即使模型写 `fetch("/api")`，也不得携带 same-origin cookie。XHR 首版直接阻断，后续若开放也必须同源、GET/HEAD、no credentials。
- 当前 URL scope 必须来自白名单、已登记 `OpenSourceLead`（且所属 `OpenSearchPlan` 仍 active）或人工 seed；开放来源浏览器补证必须把 plan/lead ref 写入 trace。
- 只返回 JSON-serializable 结果；超长结果落 artifact，只给 preview。
- 记录 `script_hash`、`intent`、当前 URL、before/after URL/title、network delta、DOM delta、artifact refs。
- 记录 `result_sink` 或等价 trace 标记：JS 结果只能进入候选、diagnosis、artifact 或 recipe draft；EvidenceCard 必须来自后续 `read_document` 的正文/PDF 正文。
- 即使 JS 返回或造成 `html_after`，该 HTML 也只能用于 delta 摘要，不得替换 observation 的可捕获正文 artifact；需要正文证据时必须重新通过 `browser_observe`/`capture_current_document` 或网络文档读取链路。
- JS runtime error 返回 line/column、error name、message、partial result 和建议下一步，而不是只返回失败。
- 连续 JS 失败达到阈值时，本 worker 降级为 blind spot 或请求人工 profile。

#### 3.4 动作反馈 schema

`browser_execute` 每次返回的重点不是“stdout”，而是告诉模型动作是否改变了页面，以及下一步该观察哪里：

```json
{
  "status": "success | failed | blocked | needs_observe",
  "execution_mode": "target_action | javascript",
  "script_hash": "sha256?",
  "return_preview": "string",
  "return_artifact_ref": "artifact?",
  "url_before": "string",
  "url_after": "string",
  "title_after": "string",
  "new_tabs": [
    {"tab_id": "string", "url": "string", "title": "string"}
  ],
  "reload": false,
  "delta_summary": "新增结果列表 10 条；搜索词出现在标题区",
  "top_changed_region": {
    "selector_hint": "main .result-list",
    "text_digest": "string",
    "candidate_count": 10
  },
  "transient_text": ["加载中", "共找到 12 条结果"],
  "network_delta": [
    {
      "method": "GET",
      "host": "www.example.org",
      "path": "/api/search",
      "query_keys": ["keyword", "page"],
      "status": 200,
      "content_type": "application/json",
      "purpose_guess": "search_results"
    }
  ],
  "document_candidate_refs": ["artifact?"],
  "download_targets": [],
  "next_observation_ref": "artifact?",
  "suggested_next_actions": ["capture_current_document", "next_page"]
}
```

这类反馈让模型能基于真实页面变化写下一步，而不是盲目重复点击。对 JS 编写错误，也要返回足够信息让模型修正：语法错误、运行时异常、找不到目标、跨域被拒、结果为空、页面无变化都应分类。

#### 3.5 Token 预算与返回信息密度

工具设计必须把“足够模型决策”和“不把网页全文塞进上下文”同时做到：

- `browser_observe` 只返回 top-N targets、正文摘要、候选区域和风险 flags；完整压缩 DOM 落 `observation_ref` artifact。
- 浏览器 HTML artifact 落盘前必须移除或脱敏 password/hidden 敏感表单字段，避免 `read_document` 通过 artifact_ref 形成凭证读取旁路。
- 目标 ID 稳定引用可见元素，避免每轮返回完整 selector 和 HTML。
- `browser_execute` 默认只返回 delta，不重复上一轮完整页面。
- JS 返回只给 preview，完整 JSON/文本落 artifact。
- `network_api_candidates` 只暴露 method/host/path/query keys/body keys/content type/purpose，不暴露完整 headers/body。
- 长列表先返回数量、标题样本和排序信号，再由模型选择是否翻页或捕获 artifact。
- WorkerReport 只引用 observation/action artifact，不内嵌全文。

#### 3.6 和 QueryPlanner / SourceProfile 的配合

QueryPlanner 在选择 source 后读取 SourceProfile，生成 worker assignment：

- 初始 route：从 profile 的 route map 进入首页、栏目、检索页、专题页或报告库。
- 查询语言：根据 source language 生成关键词，中文站用中文，英文站用英文，必要时生成双语等价查询。
- 工具策略：优先 HTTP；profile 标记 `browser_required`、`js_api_discoverable` 或 HTTP 结果为空时启用 browser。
- 风险边界：profile 指明哪些页面只能产 lead，哪些正文或 PDF 读完后可进 evidence gate。

worker 执行时可以自主小循环：

```text
observe
-> choose target_action or JS probe
-> inspect delta/network/document candidate
-> capture article/PDF/search result leads
-> self_check evidence gap
-> follow-up query/page/action
-> final WorkerReport
```

下一轮 `next_round_plan` 可以明确要求某个 source 使用 browser/JS 路径，例如“上一轮 HTTP 未发现检索结果；请在中国军网站内搜索页用中文关键词观察 XHR search endpoint 并捕获文章 lead”。

#### 3.7 Recipe 沉淀机制

模型写 JS 的价值不应停留在一次 run。只要 JS 成功解决了通用交互问题，系统生成 `BrowserRecipeDraft`：

```yaml
recipe_id: browser_recipe_...
source_id: chinamil_81cn
domain: www.81.cn
intent: 站内搜索并提取结果文章链接
trigger_condition: HTTP search route returns empty or search page is JS-driven
script_hash: sha256:...
script_ref: artifacts/browser_scripts/...
return_artifact_ref: artifacts/browser_returns/...
inputs:
  - query
  - page
outputs:
  - article_leads
  - api_candidate
observed_success_signal: result list contains title/date/url and links pass SourceRegistry.match()
safety_notes:
  - same-origin only
  - no credentials
  - read-only GET
review_status: draft
```

沉淀规则：

- source-specific recipe 经人工审计后进入对应 SourceProfile 的 `search_methods` 或 `interaction_guidance`。
- 多个站点反复成功的 recipe 抽象成通用工具能力，例如 `discover_dynamic_search_api`、`extract_load_more_results`、`capture_hydrated_article_json`。
- 失败 recipe 不丢弃，记录失败类别：selector stale、network blocked、remote closed、access denied、empty result、topic mismatch。
- 未审计 recipe 只能在同一 run 或人工指定 replay 中使用，不能默认影响生产 planner。

#### 3.8 长程调研支持

通用浏览器能力必须服务多轮 research loop，而不是单次页面操作：

- 每次 observe/execute 写 DomainTraceEvent，WorkerReport 引用关键 observation/action refs。
- `WorkerSelfCheck` 记录浏览器尝试、失败原因、是否需要 JS、是否发现 API candidate。
- 浏览器相关指标由 trace 派生到 `RunQualityFacts`：observe/execute/JS 调用次数、成功率和失败分类分布不另建权威状态。
- provider/network failure 要区分：工具本身失败、浏览器 session 中断、目标网站 403/404、远端关闭、页面设计导致不可观察。
- controller 可根据连续失败、无新增 lead、JS blocked 或需要人工审计 recipe 决定 stop/continue/human_needed。

#### 3.9 与证据门禁的关系

浏览器工具提高“发现和读取”的能力，不降低证据标准：

- 首页、栏目页、搜索页、动态列表和 API result 只能生成 ResearchLead 或 background signal。
- 当前页面被 `capture_current_document` 保存后，仍需 `classify_source_page` 和 `read_document` 读取正文。
- 白名单外开放来源只有在 OpenSearchPlan 范围内、通过 `SourceQualityAssessment`，并由 audit 确认可支撑 candidate/report 后，才能进入正式证据候选。
- JS 观察到的 API response 不能直接作为强证据，除非它对应可追溯公开正文、PDF、公告或报告 artifact。
- 报告必须披露浏览器/JS 路径产生的证据链：source -> observation/action -> lead -> document artifact -> evidence -> audit evidence-support review。

`api_candidate_to_search_adapter` 不作为常驻独立工具膨胀工具面，而是作为 `browser_execute` 发现 API 后的 planner proposal。只有 same-site、public、read-only、可解释 query 参数的候选，才能被提升为受控 search adapter；提升前写 trace 和 recipe draft。

### 测试

- fixture 页面能 observe 搜索框、分页和下载按钮。
- action 只能使用 observe 返回的 target_id。
- observe 能提取 mock XHR API candidate，但不泄露敏感 headers。
- API candidate outside whitelist 被拒绝。
- JS mode 必须要求已有 observation_ref、intent 和 expected_result。
- JS 读取 cookie/localStorage/sessionStorage 或跨域 fetch 被拒绝。
- JS 执行失败返回 error class、line/column 和页面未变化摘要。
- JS 成功触发动态搜索后返回 delta_summary、network_delta、document_candidate_refs 或 lead candidates。
- 超长 JS 返回落 artifact，只把 preview 放入工具结果。
- 成功 JS 生成 BrowserRecipeDraft，但 draft 未人工审计前不会进入稳定 SourceProfile。
- capture_current_document 只能生成 artifact/lead，不能直接生成 EvidenceCard。

### 验收

worker 能用同一套 observe/execute 工具处理普通搜索页、JS 搜索页、分页列表、加载更多、下载按钮和公开 same-origin API；81.cn 这类站点不需要站点专用分支也能先通过页面理解发现可用入口，再把成功路径沉淀为 SourceProfile recipe。真实 run 的 trace 可以重建模型为什么写 JS、JS 做了什么、页面发生了什么变化、哪些结果进入 lead/document/evidence gate，以及哪些失败是网络波动、网站限制还是工具设计缺陷。

## 4. 诊断三：Worker 自主补证循环

### 问题

worker 当前更像一次性读取器：搜索、读取、写发现后结束。它缺少显式的“发现缺口 -> 继续找材料 -> 验证或反驳自己判断”的 micro-loop。

### 设计

#### 4.1 从 GA / Pi 吸收的经验

GenericAgent 的多轮自主能力来自两个组合，而不是来自复杂的站点适配器：

- 工具面很少：`web_scan` 提供压缩页面观察，`web_execute_js` 允许模型主动操作页面。
- 每次动作都返回高信息量反馈：JS return、错误位置、页面是否刷新、新 tab、瞬时文本、DOM diff 和“页面无明显变化”提示。
- 模型不被要求一次想完。它可以“观察 -> 操作 -> 看反馈 -> 修正脚本或下一步”，形成多轮试错。
- 成功经验通过 SOP、checklist、report、script 或 memory 沉淀，下一次不必重新摸索。

Pi / AgentHarness 的经验在运行时层：

- `AgentLoop` 只负责 turn / tool call / tool result / next provider request，不写业务判断。
- `DiscoveryHarness` 负责 phase、save point、context rebuild、session、trace、budget 和三类注入队列。
- `steer` 用于当前工作中的纠偏，`follow_up` 用于 agent 本来要停时继续补一段，`next_turn` 用于下一次 prompt 的任务延续。
- save point 让外部策略可以在工具结果落库后读取领域状态，再决定是否继续。

本项目应吸收的是“模型自主决定手段，程序化策略决定是否允许结束”。也就是说，worker 可以自己选择 query、网页、PDF、browser/JS 路径，但结束前必须经过领域 self-check；self-check 不通过时，由 `DiscoveryHarness` 的 apparent-stop follow-up policy 注入新的目标，而不是依赖 worker 自觉继续，也不新增一套外层 worker loop。

#### 4.2 层次边界

诊断三不再新增外层 worker loop。worker 的自主小循环已经由 `AgentLoop` 的 turn/tool/tool-result 机制承载；补证机制只作为 `DiscoveryHarness` apparent-stop 阶段的停止门禁和目标式 follow-up 注入：

```text
WorkerAssignment
-> DiscoveryHarness / AgentLoop 执行工具循环
-> save point 后读取 DomainStore / trace / WorkerReport 草稿
-> WorkerSelfCheck
-> pass: 输出 WorkerReport
-> fail: apparent-stop policy 生成 FollowUpInstruction，继续同一 worker
-> exhausted/blocked: 输出带 blind_spots 的 WorkerReport
```

职责边界：

- `AgentLoop`：执行模型 turn 和工具调用。
- `DiscoveryHarness`：保存消息、工具结果、domain proposals、trace、预算和 context，并在 apparent stop 时调用 worker stop policy。
- `WorkerStopPolicy`：判断单个 worker 是否有资格结束，并把失败原因转换为目标式 `FollowUpInstruction`；它不调用模型、不执行工具、不生成报告。
- `Judge`：跨 worker 综合共识、冲突、盲点和下一轮计划。
- `Auditor`：对 candidate/report 做最终门禁。

`WorkerStopPolicy` 不生成 CandidateDemand，不批准报告，不跨 worker 裁决矛盾，不把弱证据提升为强证据，也不替模型决定 query、网页、selector 或 JS 脚本。

#### 4.2A 请求组装边界：DemandDiscoveryPromptBuilder

仅有 harness 状态机还不够。当前实现容易把角色 prompt、ContextPack JSON、network worker brief、open-search/browser 禁止事项和输出格式要求拼成一个杂糅请求。强模型虽然能解析，但长程联网调研时容易漏掉完成条件、授权范围或证据门禁。

参考 Codex CLI 的运行时分层经验：Codex 源码中 `Prompt` 独立承载 conversation input、tools、base instructions、output schema 和 parallel tool call 设置，再由统一 client 构造 Responses request；compaction 后还会重新注入 canonical initial context，避免历史摘要吞掉基础约束。本项目应吸收的是“请求组装集中化”和“上下文选择与可读渲染分离”，而不是把更多规则塞进 agent markdown。

新增 `DemandDiscoveryPromptBuilder`，输出接近 Codex `Prompt` 的领域对象：

- `AgentLoop` / `DiscoveryHarness`：只负责 turn、tool call、session、trace、save point、follow-up。
- `ContextPackBuilder`：只负责从 DomainStore、trace、artifact index 和 WebResearchSession 选择哪些状态进入上下文。
- `DemandDiscoveryPromptBuilder`：负责组装 `ModelPrompt(base_instructions, input, tools, output_schema, parallel_tool_calls)`。
- `AgentDef.system_prompt`：只保留稳定角色职责。
- `ToolDefinition.schema`：只描述工具局部输入输出和局部安全边界。

`WebResearchSession` 在这里是 worker-local working memory，不是第二套工作流数据库。它只保存 typed refs、compact summaries、attempted routes、active acceptance criteria、self-check/follow-up refs 和 blocked reasons；候选、正文、来源质量、正式证据和浏览器观察仍以既有 `ResearchLead`、`OpenSourceLead`、artifact、`SourceQualityAssessment`、`EvidenceCard`、`BrowserObservation` 和 trace 为权威。

`input` 统一为四类内容，不再使用自造九段 schema：

```text
# Objective
# Working Memory
# Constraints
# Recent Observations
```

`Recommended Next Actions` 不作为固定字段。模型下一步如何搜索、点击、翻页、下载、写 JS 或放弃，由模型依据当前观察自主决定。系统只能在 `Recent Observations` 中注入可追溯的 `observed_affordances/action_hints`，来源包括工具结果、`WorkerSelfCheck`、`FollowUpInstruction`、`judge.next_round_plan`、`SourceProfile` 和 controller 授权边界；`DemandDiscoveryPromptBuilder` 不能自行生成行动计划。

这层不新增 agent，不做语义裁决，也不替模型决定网页操作。诊断三首版只强制 worker/reader 请求走这个 builder，让 worker 请求像一个清楚的工作单，而不是状态 dump。后续 WebResearchSession、OpenSearchPlan、BrowserObservation、WorkerSelfCheck、JudgementReport、AuditReport 和 ReportContextBundle 都应通过同一个 builder 协议投影给对应角色。

四类角色后续复用同一外壳，但替换 role-specific 内容：

| Role | `base_instructions` | `input` 重点 | `tools` | `output_schema` | `parallel_tool_calls` |
|---|---|---|---|---|---|
| worker/reader | 稳定阅读职责、证据规则、外部内容不作为指令 | Objective、Working Memory、Constraints、Recent Observations；包含 active acceptance criteria 和 observed affordances | search/fetch/read/browser/evidence 工具子集 | WorkerReport 或 final sections | HTTP/search/read 可谨慎开启；browser/action/JS 默认关闭并行 |
| judge | 跨 worker 综合，不替代 auditor | worker reports、evidence map、contradictions、blind spots、open questions | `record_judgement` | JudgementReport 和 next_round_plan v1 | 关闭 |
| auditor | 审查 candidate/report 证据支撑，不做新调研 | candidate、EvidenceCard、body spans、rubric、judgement contradictions | `run_audit` 或 audit 写入工具 | AuditReport scorecard | 关闭 |
| reporter | 生成中文报告，不发明 unsupported claim | approved candidate、curated evidence windows、judgement、audit caveats、blocked claims、trace refs | `generate_demand_report`、只读 context expansion | DemandReport/report draft schema | 关闭 |

#### 4.3 Worker 内部状态机

每个 WorkerAssignment 执行可恢复的小型状态机：

```text
assignment_loaded
-> initial_search
-> lead_selection
-> body_reading
-> provisional_findings
-> evidence_sufficiency_check
-> if insufficient: follow_up_planning
-> follow_up_execution
-> second_self_check
-> final_worker_report | blocked_worker_report
```

状态含义：

- `assignment_loaded`：读取 QueryPlanner 给出的 source、route、query language、evidence policy。
- `initial_search`：优先按 source profile 的 route/search guidance 搜索，不使用 topic-specific default query 偏置。
- `lead_selection`：将栏目页、搜索页、API result 产出的候选写入 ResearchLead/ReadingQueue。
- `body_reading`：只读取文章正文或下载文献正文，导航页不能变成强证据。
- `provisional_findings`：worker 可以形成临时判断，但必须标注证据 refs 和未验证 claim。
- `evidence_sufficiency_check`：程序化 self-check 判断是否允许结束。
- `follow_up_planning`：由模型选择下一步，但必须引用 self-check 失败原因。
- `follow_up_execution`：换 query、换 route、翻页、下载 PDF、使用 browser/JS 或转向同 source 内其他入口。
- `blocked_worker_report`：预算耗尽、来源不可访问、需要人工 profile 或开放搜索时，明确写 remaining blind spots。

#### 4.4 WorkerSelfCheck

增加 `WorkerSelfCheck`：

- `check_id`
- `assignment_id`
- `round_id`
- `topic_alignment`: `direct | adjacent | weak`
- `body_evidence_count`
- `direct_evidence_count`
- `partial_evidence_count`
- `adjacent_evidence_count`
- `source_diversity`
- `article_body_read_count`
- `downloaded_document_read_count`
- `listing_or_search_only_count`
- `queries_used`
- `routes_used`
- `browser_actions_used`
- `javascript_actions_used`
- `unverified_claims`
- `discarded_findings`
- `contradiction_candidates`
- `follow_up_required`
- `follow_up_reason`
- `follow_up_actions_taken`
- `remaining_blind_spots`
- `allowed_to_finish`

`topic_alignment=weak` 时，worker 不能输出 strong finding，只能作为 blind spot 或 weak signal。

`allowed_to_finish=true` 的最低条件：

- 至少读取过一条文章正文或下载文献正文。
- 没有把 listing/search/home/access-status 当作强证据。
- 若输出 strong finding，至少有 `direct` evidence，或两条来自不同正文 artifact 的 `partial` evidence。
- 所有 `unverified_claims` 要么被补证，要么进入 `remaining_blind_spots`。
- 如果只得到 adjacent/weak evidence，必须输出 `blocked_worker_report` 或 `need_more_sources=true`。

#### 4.5 FollowUpInstruction

self-check 不通过时，apparent-stop policy 生成 `FollowUpInstruction` 注入给同一 worker：

```yaml
instruction_id: followup_...
assignment_id: assignment_...
trigger_check_id: selfcheck_...
reason: direct_evidence_missing
allowed_tools:
  - search_sources
  - fetch_page
  - discover_articles
  - read_document
target_source_id: chinamil_81cn
query_revisions:
  - language: zh
    query: "..."
route_revisions:
  - "站内搜索页"
  - "专题页"
expected_outputs:
  - "至少一个正文 artifact"
  - "解释上一条 evidence 为什么是 adjacent 或 direct"
stop_after:
  max_follow_up_turns: 3
  max_new_pages: 5
```

follow-up 不应该把具体步骤写死到“点哪个 CSS selector”。它只给目标、约束和期望产物，让强模型自己决定工具组合。若上一轮 `browser_observe` 已发现 XHR/API/下载按钮，可允许 follow-up 指向 `browser_execute`，但仍要求 artifact/evidence gate。

#### 4.6 与 harness 的接入方式

不重写 `AgentLoop` / `DiscoveryHarness` 内核，也不新增外层 worker loop。直接复用 `AgentLoopConfig.get_follow_up_messages` 已有语义，在 agent apparent stop 时让 `DiscoveryHarness` 调用轻量 `WorkerStopPolicy`：

```text
before_next_turn(context_snapshot, domain_delta, trace_delta)
  -> if current evidence is drifting: append steering message before next provider request

on_apparent_stop(last_assistant, store_snapshot)
  -> if self_check fails: return FollowUpInstruction
  -> else: allow stop
```

`before_next_turn` 可复用当前 `prepare_next_turn` 时机：上一轮工具结果已经落到 save point，下一次 provider 请求尚未发出，适合注入“你刚读到的是列表页，不要生成证据，继续进入正文”这类过程纠偏。

`on_apparent_stop` 的位置应在 `AgentLoop` 发现 assistant 没有 tool call、准备 drain follow-up 时调用。这样 worker stop policy 可以把补证任务放进 harness 的 `follow_up` 语义里，形成同一次 worker run 内的连续多轮决策。

#### 4.7 模型自主性的保留方式

worker stop policy 只控制“是否允许结束”和“继续要解决哪个缺口”，不替模型决定所有操作。注入文本应保持目标式：

```text
Self-check failed: current evidence is adjacent-only.
Continue within source_id=...
Goal: find article/PDF body evidence that directly discusses ...
You may revise query language, use source profile routes, inspect browser/API candidates,
or mark blocked with reason after exhausting the budget.
Do not create evidence from listing/search pages.
```

这样吸收 GA 的自主试错优势：模型仍可自己选 query、翻页、JS、下载或放弃；系统只把明显不充分的终止拉回继续。

#### 4.8 预算与停止条件

worker stop policy 的停止条件必须程序化：

- `self_check.allowed_to_finish=true`。
- worker follow-up 次数达到 `max_follow_ups_per_assignment`。
- worker 页面/下载/JS/tool-call 预算耗尽。
- 连续两次 follow-up 没有新增 ResearchLead 或正文 artifact。
- 当前 source 访问失败、搜索失效或需要登录，且无可用 fallback route。
- self-check 判断需要跨 source、开放搜索或人工 source profile，交给 judge/controller，而不是 worker 继续硬搜。

停止不是失败。若由于预算或信源限制停止，WorkerReport 必须写清：

- 已尝试 query/route/tool。
- 哪些 findings 被丢弃。
- 哪些 blind spots 留给 judge 下一轮。
- 是否建议 OpenSearchPlan、人工 profile 或换 source。

#### 4.9 WorkerReport 扩展

`WorkerReport` 增加：

- `assignment_id`
- `source_id`
- `queries_used`
- `routes_used`
- `self_check`
- `follow_up_instructions`
- `follow_up_attempt_count`
- `browser_attempts`
- `artifact_refs`
- `discarded_findings`
- `evidence_quality_notes`
- `blocked_reason`
- `next_round_suggestions`

`WorkerReport.partial_findings` 中的每条 strong finding 必须引用 `evidence_refs`。没有 evidence refs 的判断只能进入 `open_questions`、`risks` 或 `discarded_findings`。

#### 4.10 Trace 事件

新增 DomainTraceEvent：

- `worker_assignment_started`
- `worker_initial_search_completed`
- `worker_self_check_recorded`
- `worker_follow_up_planned`
- `worker_follow_up_started`
- `worker_follow_up_completed`
- `worker_blocked`
- `worker_report_finalized`

trace 必须能重建：

```text
assignment -> search/observe/read/download -> provisional findings
-> self_check -> follow_up instruction -> follow_up actions
-> second self_check -> WorkerReport
```

这条 trace 给 judge 使用，但不替 judge 做跨 worker 结论。

### 测试

- fake worker 第一条证据偏题时会执行 follow-up search。
- self_check 弱相关时 WorkerReport 不输出 strong finding。
- worker 预算耗尽时输出 remaining blind spots。
- trace 能看到 initial_search -> self_check -> follow_up_planned -> follow_up_completed。
- apparent-stop follow-up 复用同一 session/domain store，第二次 provider request 能看到第一次读到的 lead/evidence。
- self_check 缺少正文 evidence 时，`allowed_to_finish=false`。
- listing/search/home artifact 不能让 worker 通过 self_check。
- 连续两次 follow-up 无新增正文 artifact 时，worker 输出 blocked report。
- `on_apparent_stop` hook 能在 assistant 无 tool call 时注入 FollowUpInstruction。
- WorkerReport 的 strong finding 没有 evidence refs 时被降级到 open_questions 或 discarded_findings。

### 验收

单个 worker 能在同一 source 或同一 assignment 范围内自主完成至少一次补证尝试：第一次证据偏题或不足时，系统不会允许它直接结束，而是注入目标式 follow-up，让模型自行选择搜索、阅读、浏览器或 JS 路径继续验证。最终 WorkerReport 能解释已尝试路径、被丢弃判断、剩余盲点和下一轮建议，不会把相邻主题证据包装成直接需求结论。

## 5. 诊断四：Audit 语义证据审查

### 问题

当前 gate 更关注是否有 EvidenceCard、是否来自正文、是否有 audit，但真实 autonomous path 中 audit 仍偏程序化：系统直接写入 approved audit，并把 rubric item 统一标记为 pass。这样 report gate 虽然能确认“有证据、有正文、有 judgement、有 audit”，却没有让 audit agent 真正判断每条 evidence 是否语义上支撑 topic、candidate demand 和报告核心结论。

因此主要问题不是缺少一个新的兜底字段，而是 audit 没有在真实链路中发挥职责。`EvidenceCard.evidence_assessment` 已经存在，应先把它从自由文本收敛为轻量受控等级，并让 audit agent 基于 EvidenceCard、judgement、candidate synthesis 和 source quality 做逐证据审查。只有当未来需要多评审人、多版本复核历史时，再考虑把审查记录拆成独立 assessment 对象。

### 设计

#### 5.1 复用现有 EvidenceCard

首版不新增独立相关性评估 schema。复用并规范 `EvidenceCard.evidence_assessment`，将其含义从泛化强弱描述收敛为 evidence-support level：

- `direct`：正文明确支撑 candidate demand 或 capability gap。
- `partial`：正文支撑需求链条中的一段，需要 judge/audit 补足推理。
- `adjacent`：主题相邻或提供背景，不能单独支撑核心结论。
- `weak`：弱信号，只能进入 open questions、risks 或 background。
- `irrelevant`：不支撑当前 topic/candidate，不能进入 evidence refs。
- `unassessed`：尚未完成语义支撑审查。

兼容规则：

- 旧值 `strong` 暂按 `direct` 或 `partial` 候选处理，但必须在 audit 中重新说明。
- 旧值 `weak` 按 `weak` 处理。
- 缺失或未知值按 `unassessed` 处理，不能直接进入 `review_ready`。

#### 5.2 Audit Agent 的输入

真实 audit agent 输入不应只是 candidate 和 scorecard，还必须包含紧凑 evidence bundle：

- candidate demand statement。
- judgement consensus、contradictions、blind spots、next_round_plan。
- 每条 EvidenceCard 的 claim、summary、excerpt、source_location、source tier、collection_decision。
- SourceQualityAssessment（仅开放来源需要）。
- worker self-check 和 discarded findings 摘要。
- report core conclusion draft。

audit prompt 必须要求逐条回答：

- 这条 evidence 支撑的是 explicit demand、inferred gap、context only 还是 counter evidence？
- 它与 candidate demand 的关系是 direct、partial、adjacent、weak 还是 irrelevant？
- 它是否来自正文/下载文献正文，而不是 listing/search/home？
- 它是否被报告用于 core conclusion？如果是，是否足够？
- 还缺哪一步推理或哪类补证？

实际运行中 auditor worker 复用标准 `ModelPrompt` composer：`AuditContextBundle` 进入 `input.Working Memory.audit_context`，authorized scope 和 hard prohibitions 进入 `input.Constraints`，`output_schema` 使用 AuditReport-oriented schema，`parallel_tool_calls=false` 通过 `DiscoveryHarness -> AgentLoop -> ResponsesProvider` 进入模型请求。agent markdown 只保留稳定角色原则，工具 schema 和 report gate 负责结构化约束。

#### 5.3 Audit 输出与 scorecard

不新增首版 schema，但扩展 `AuditReport.scorecard` 的约定，让现有 audit 结构承载证据审查：

```json
{
  "evidence_support": {
    "verdict": "pass | doubt | fail",
    "reason": "核心结论至少有 direct/partial 正文证据支撑",
    "recommended_report_status": "review_ready | needs_revision | watchlist | rejected",
    "status_reason": "推荐报告状态的简要理由",
    "recheck_conditions": ["watchlist 后续复查条件；非 watchlist 可为空"],
    "evidence_reviews": {
      "ev-1": {
        "support_level": "direct",
        "support_type": "inferred_gap",
        "used_for_core": true,
        "reason": "...",
        "missing_link": ""
      },
      "ev-2": {
        "support_level": "adjacent",
        "support_type": "context_only",
        "used_for_core": false,
        "reason": "...",
        "missing_link": "未说明能力缺口"
      }
    }
  }
}
```

rubric 增加或强化检查项：

- `evidence_supports_candidate`：证据是否支撑 candidate demand。
- `core_conclusion_supported`：报告核心结论是否有 direct/partial evidence。
- `adjacent_evidence_limited`：相邻证据是否只被用作背景。
- `unassessed_evidence_handled`：未评估证据是否导致降级或进入补证计划。

#### 5.4 Gate 规则

- listing/search/home evidence 一律拒绝。
- `irrelevant` 不能进入 report evidence refs。
- `weak` 只能作为背景、风险或 open question，不支撑 core conclusion。
- `adjacent` 可以帮助说明场景，但不能单独支撑 `review_ready`。
- `partial` 可以支撑 candidate synthesis；若没有 direct evidence，audit 必须解释推理链。
- `direct` 可以支撑 core conclusion。
- `unassessed` 不阻断 report 产出，但 report review_status 必须是 `needs_revision`，并写明补证计划。
- 开放来源 EvidenceCard 必须通过 `SourceQualityAssessment`；`provisional` 来源只能支撑 provisional/background conclusion。

报告状态分级：

- `review_ready`：audit 结论 approved，核心结论有 direct evidence，或有两条以上不同 source 的 partial evidence 且 audit 解释推理链。
- `needs_revision`：只有 adjacent/weak/unassessed evidence、关键 contradiction 未解释、或 audit scorecard 存在 doubt。
- `watchlist`：证据不足但存在有价值弱信号，且 audit 在 `scorecard.evidence_support.recommended_report_status` 明确推荐 `watchlist`，同时给出非空 `recheck_conditions`；缺少复查条件时回落 `needs_revision`。
- `rejected`：audit veto fail、irrelevant evidence 支撑核心结论、低质开放来源冒充证据。

当前实现中 `watchlist` 是 report gate 可消费的结构化状态，不再依赖 audit comments 自然语言推断。`irrelevant` 或 `unassessed` evidence 若被标为 core support，不允许进入 watchlist；其中 irrelevant core support 直接进入 `rejected`。

2026-06-30 追加补强：real autonomous path 不再把第一次 `needs_revision` audit 只当作最终降级报告。若 audit 结论不是 `approved/pass/通过`，且 `required_rework`、`scorecard.evidence_support.recheck_conditions`、`status_reason` 或 audit comments 给出补证方向，runner 会在剩余 round budget 内生成 audit-repair `OpenSearchPlan`，启动一轮带开放搜索权限的 network worker，导入新证据后重新 judgement、candidate synthesis 和 audit。只有 audit 通过、repair 触达安全上限或 repair 后仍无法合成 candidate 时，才进入报告生成或降级报告。

候选合成和报告门禁分层处理证据强度：`candidate_synthesis` 可以用 `direct` 或 `partial` 正文 evidence 形成候选，真实 worker 常用的 `moderate` 会规范化为 `partial`；`weak/adjacent/irrelevant/unassessed` 仍不能支撑候选合成。严格 `review_ready` 不因此放宽，仍由 audit evidence-support scorecard 和 report gate 判断 direct/partial 是否足够支撑最终核心结论。

#### 5.5 程序化 audit 的替代

真实 autonomous path 不能再直接构造 approved audit 作为默认成功路径。应改为：

```text
candidate_synthesis
-> audit_worker_assignment
-> audit agent reads candidate/judgement/evidence bundle
-> run_audit tool records conclusion + scorecard
-> report gate reads audit conclusion and evidence_support scorecard
-> reporter writes review_status and downgrade reason
-> ReportPublisher publishes report.md + report_manifest.json
```

fake mode 可以保留 deterministic audit fixture，但必须显式标记为 fixture audit，不能冒充真实语义审查。

#### 5.6 Trace

每次 audit 写 DomainTraceEvent：

- event_type: `audit_completed`
- input_refs: CandidateDemand + JudgementReport + EvidenceCard ids + SourceQualityAssessment ids
- output_refs: AuditReport id
- decision: audit conclusion
- payload: evidence support summary、downgrade reason、required_rework

### 测试

- autonomous real path 不允许直接构造 approved audit；必须经过 audit worker 或显式 fixture path。
- audit scorecard 缺少 `evidence_supports_candidate` / `core_conclusion_supported` 时，report gate 降级为 `needs_revision`。
- adjacent-only evidence 可以生成 `needs_revision/watchlist` 报告，但不能 `review_ready`。
- audit 推荐 `watchlist` 且写入 `recheck_conditions` 时，机械 gate 产出 `watchlist`；缺少复查条件时产出 `needs_revision`；irrelevant core support 产出 `rejected`。
- direct body evidence 加 approved audit 可以进入 `review_ready`。
- weak evidence 可出现在 open questions/background，但不能支撑 core conclusion。
- open_web evidence 缺少 SourceQualityAssessment 时 audit 必须 fail 或 doubt。
- unassessed evidence 不阻断报告产出，但必须降级并写 required_rework。
- auditor worker 的标准 prompt composer 输出包含 `audit_context`、audit output schema 和 `parallel_tool_calls=false`，并能进入 provider request options。

### 验收

报告不能仅凭“读过正文”和程序化 approved audit 通过。真实链路中必须有 audit agent 对 evidence 是否支撑 candidate/report 进行语义审查；报告可在证据不足时产出，但 review_status、audit comments、required_rework 或 watchlist recheck_conditions 必须清楚说明降级原因与补证方向。

## 6. 诊断五：Judge 下一轮计划质量

### 问题

实施前 `next_round_plan` 只有 `plan_version=1` 和 `tasks[]` 的雏形，真实 run 会生成“继续补充白名单正文材料交叉验证能力缺口”这类泛化计划。问题不在于缺少更多字段，而在于缺少最小可执行契约、计划质量检查、结构化权限字段和面向 worker 的清晰自然语言任务书。

当前代码已切到诊断五主路径：judge 是模型 agent，必须通过 `record_judgement` 写入 `JudgementReport`，其中 `next_round_plan` 输出 `controller_tasks + worker_briefs`。controller 通过 helper 校验/修复后只消费结构化层，network worker prompt 接收自然语言 planned tasks。旧 `tasks[]` 不再作为 controller 主路径；只在 `judgement_plan` helper 中作为 repair 输入被转换。旧的程序化 `run_judge_for_round()` / `synthesize_judgement_from_worker_reports()` 已删除。

### 设计

首版不新增持久化的“下一轮计划”领域对象。继续使用 `JudgementReport.next_round_plan: dict[str, Any]`，但把它拆成两个用途不同的层：

- `controller_tasks`：给 controller 消费的轻结构化任务。它只保留权限、路由、引用、query 和完成检查所必需的字段。
- `worker_briefs`：给 worker 阅读的自然语言任务书。它可以更像人工任务说明，但不能授权结构化层没有允许的 source、query、open search、browser/JS 或写入动作。

helper 以脚本实现，负责构造、校验、修复、降级和一致性检查。模型可以一次性生成 `controller_tasks` 和 `worker_briefs`，但 controller 只信 `controller_tasks`；若自然语言 brief 与结构化任务不一致，以结构化任务为准并写 trace。

#### 6.1 next_round_plan 最小契约

`next_round_plan` 必须保持轻量，不把给 worker 的说明重复拆成多层字段：

```json
{
  "plan_version": 1,
  "round_id": "round-1",
  "summary": "下一轮补足低能见度探测预警的直接证据",
  "controller_tasks": [
    {
      "task_id": "task-1",
      "objective": "补充低能见度条件下探测预警不足的 direct/partial 正文证据",
      "gap_type": "missing_direct_evidence",
      "routing_hint": "same_source_followup",
      "source_scope": "whitelist_first",
      "input_refs": {
        "worker_report_ids": ["agent-1"],
        "evidence_ids": ["ev-1"],
        "lead_ids": ["lead-3"]
      },
      "query_revisions": [
        {"language": "zh", "query": "低能见度 探测 预警 能力不足"}
      ],
      "completion_check": "新增 direct/partial 正文证据，或说明该路径已耗尽"
    }
  ],
  "worker_briefs": {
    "task-1": "本轮优先补充低能见度条件下探测预警不足的正文证据。上一轮 ev-1 只能部分支撑，请优先使用中文查询并读取 article/PDF 正文；若只能找到相邻材料，请标为 partial/adjacent，不要写成 direct。"
  },
  "remaining_open_questions": ["处置链路材料仍不足"],
  "stop_candidate_reason": ""
}
```

必要字段说明：

- `objective` 合并旧 `question` 与 `action_intent`，避免同义重复。
- `routing_hint` 合并旧 `routing_decision_hint`，只表达建议路由，不直接授权。
- `source_scope` 取代嵌套 `source_constraints.allowed_scope`；只有需要限定具体 source/url 时才加可选 `preferred_source_ids` 或 `preferred_urls`。
- `completion_check` 合并旧 `done_criteria` 和 `expected_outputs`，细节放入 `worker_briefs`。
- 不再把 `risk_flags`、`expected_outputs`、长 `source_constraints` 作为必填字段；这些属于 worker brief 或 audit/report gate 的表达层。

受控 `gap_type` 保留最少集合：

- `missing_direct_evidence`
- `partial_only`
- `contradiction`
- `source_gap`
- `route_failed`
- `open_search_candidate`
- `human_profile_needed`
- `report_ready_with_limits`

受控 `routing_hint`：

- `same_source_followup`
- `different_whitelist_source`
- `open_search_candidate`
- `human_profile_needed`
- `stop_for_report`

#### 6.2 Judge 的职责

judge 负责把 worker 发现转成可追溯缺口任务，并同时给出 worker 可读的自然语言任务书：

- 每个 controller task 必须引用 `worker_report_ids`，并尽量引用 `evidence_ids` 或 `lead_ids`。
- 每个 task 必须说明一个具体 evidence gap、contradiction 或 route failure，不能只写“继续补证”。
- `query_revisions` 必须是 controller 可直接授权给搜索工具的 query；worker brief 中出现的新 query 必须能在 `query_revisions` 中找到。
- `worker_briefs` 用自然语言说明背景、上一轮不足、优先路径和降级口径，但不产生额外权限。
- 即使 judge 建议 stop，也要写 remaining open questions 和报告限制。

judge 不直接决定是否开放搜索、是否人工停止、是否可发布报告、是否新增白名单 source。这些决定由 controller 和 audit/report gate 根据 budget、source policy、open search policy 和 audit 结果做。

#### 6.3 Controller 与 helper 的消费规则

controller 校验的是“能否转译成下一步动作”，不是只校验字段是否存在：

- `same_source_followup` -> 同 source 或同 whitelist scope 的 worker assignment。
- `different_whitelist_source` -> 重新选白名单 source 或调整 query。
- `open_search_candidate` -> 只有当白名单路径耗尽、证据仍不足、预算允许时，生成 OpenSearchPlan。
- `human_profile_needed` -> 只在需要人工审计 source profile、访问边界或敏感边界判断时触发。
- `stop_for_report` -> 进入 candidate synthesis，但报告限制和 open questions 必须传给 audit/report gate。

helper 需要做三类检查：

- schema check：必要字段、受控枚举、refs、query 格式。
- policy check：source scope、白名单外 URL、open search 预算、browser/JS 权限。
- consistency check：`worker_briefs` 不能包含未授权 query、source、browser/JS、open search 或证据写入要求。

当前实现补充：`OpenSearchPlan` 可以通过 `open_search_sources_batch` 一次消费多个 plan query，工具内部并发调用 provider adapter、按 URL/lead 去重并统一扣 `allowed_result_count`。诊断五只负责把 judge 的补证意图变成更精确的 authorized queries 和 worker brief，不重新设计 open search 工具链。

代码落点：

- `domain/judgement_plan.py`：提供 `assess_next_round_plan()`、`build_repaired_next_round_plan()`、`compile_worker_brief()` 和 `check_worker_brief_consistency()`。
- `harness/judge_plan_routing.py`：从 judgement plan 生成 ephemeral worker assignments、open search queries 和 human profile requests。
- `domain/judgement.py`：只保留 `JudgementReport` / `JudgementItem` schema 与反序列化，不再合成 judge 结论。
- `harness/judge_agent.py`：运行模型 judge agent，把 worker reports、EvidenceCard、SourceRecord、OpenSearchPlan/OpenSourceLead/SourceQualityAssessment 摘要交给模型，并要求其调用 `record_judgement`。
- `harness/research_loop.py`：每轮 worker reports 后调用 judge agent；judgement 后写 `judge_plan_validated`、`judge_plan_repaired`、`judge_plan_needs_revision` 或 `judge_plan_brief_mismatch` trace；下一轮开始前写 `worker_assignments_planned`，并只用 controller task 触发 OpenSearchPlan。
- `network_research.py` / `autonomous_research.py`：`planned_tasks` 透传到 network worker prompt 的 `Planned judge follow-up tasks` 小节。
- `domain/tools.py` / `workers/agents/judge.md`：`record_judgement` schema 和 judge prompt 使用新契约。

#### 6.4 泛化计划的处理

泛化 `next_round_plan` 不应直接让 run 硬失败。应按质量分级处理：

- `valid_executable`：直接转译为 worker assignment 或 OpenSearchPlan candidate。
- `generic_but_repairable`：helper 从 blind_spots、contradictions、partial_coverage 和 worker open questions 生成最小 controller task，并编译默认 worker brief，写 `judge_plan_repaired` trace。
- `invalid_unusable`：写 `judge_plan_needs_revision` trace；若还有预算可让 judge 重写，否则以 `needs_revision` 报告收尾。

质量检查规则：

- 没有 refs 的 task 不能驱动 worker，只能进入 remaining open questions。
- 没有 objective 或 query 的 task 不能调度。
- source target 不在 whitelist/profile 中时，不能直接调度；controller 可转成 `open_search_candidate` 或 `human_profile_needed`。
- “继续补充材料”“进一步调研”等空泛任务必须修复或降级。

### 测试

- 泛化 next_round_plan 不硬失败，而是写 `judge_plan_repaired` 或 `judge_plan_needs_revision`。
- 无 refs 的 task 不能生成 worker assignment，只能进入 remaining open questions。
- worker brief 中出现未授权 query/source/browser/open search 时，helper 标记不一致并以 controller task 为准。
- 白名单外 target 不能直接抓取；只能转为 OpenSearchPlan candidate 或 human_profile_needed。
- 第二轮 ResearchRound hypothesis 和 worker prompt 包含具体 objective 与自然语言 worker brief，而不是重复第一轮 topic。
- `open_search_candidate` 只有在白名单路径耗尽且预算允许时才生成 OpenSearchPlan。

### 验收

第二轮不是重复第一轮；每个 worker 都知道自己要补哪个证据缺口或解决哪个矛盾。controller plan 保持轻量、可校验、可审计；worker brief 保持自然语言、可执行、但不扩权。judge 的计划如果泛化，controller 能修复、要求重写或降级收尾，而不是靠增加字段数量假装计划质量已经解决。

## 7. 诊断六：报告生成器质量

### 问题

`report.md` 过短、模板感强，原因不只是 gate 降级。当前 autonomous path 里 `_render_autonomous_report_body()` 由代码程序化拼接 front matter、标题、candidate statement、evidence id 和 open questions；这只是流程产物包装，不是报告写作。已有 `generate_demand_report` 工具可以让 agent 写正文，但 Phase 5 autonomous path 没有把 reporter agent 放回链路。

报告质量不能靠发布层兜底。最后报告应由 agent 负责综合表达，但 reporter agent 不能只看一个短 `ReportBrief`，否则会丢失调研链路、工具尝试、材料窗口、矛盾由来和审计限制。它需要利用 harness 保存的上下文、DomainTraceEvent、worker session 摘要、EvidenceCard、artifact 文本窗口、judgement、audit scorecard 和 source profile 信息，才能生成有证据链解释的中文报告。

### 设计

#### 7.1 职责边界

新增受限 `reporter` agent，而不是让发布层生成内容。

- reporter agent：负责中文叙事、证据链解释、矛盾处理、可信度说明、限制与下一步建议。
- ReportContextPipeline：由机械索引、context curator agent 和程序化 verifier 组成；负责把 trace/harness/domain/artifact 上下文整理成 reporter 可用材料，但不直接写最终报告结论。
- report gate：负责一致性校验，禁止新增事实、越过 audit 限制或引用未批准证据。
- ReportPublisher：只负责发布已经入库且通过 gate 的报告，输出人读 `report.md`、机器审计 `report_manifest.json` 和可选 appendix；不写正文、不润色、不补结论。

`ReportBrief` 只作为约束摘要存在，不能成为 reporter 的唯一输入。

本诊断按以下边界收敛：

- `context_curator`、`ContextVerifier`、`reporter`、`generate_demand_report` 或 consistency gate 调用/校验失败时，真实 path 失败报告阶段并写 trace/summary，不生成 `DemandReport`。
- audit 不通过、证据不足或矛盾未解决不是链路失败，而是正常业务结果；仍由 reporter 生成解释性报告，并使用 `needs_revision/rejected/watchlist` 等既有 `review_status`。
- 人读 `report.md` 不承载大量控制字段；`report_id/candidate_id/audit_id/judgement_id/report_context_bundle_id/evidence_ids/domain_trace_ids/review_status` 等进入 `report_manifest.json`。
- 多轮 worker artifact 必须通过 multi-root artifact resolver 解析，不能只取最后一轮 `artifact_dir`。
- `context_curator` 和 `reporter` 复用标准 prompt composer，不新增第二套 prompt 拼接体系。

#### 7.2 ReportContextBundle

controller 在 audit 之后启动 `ReportContextPipeline`，产出 `ReportContextBundle`，作为 reporter agent 的主要输入：

- `control_brief`
  - topic、candidate_id、judgement_id、audit_id、review_status。
  - allowed_claims、blocked_claims、required_caveats、required_rework。
  - report scope 复用现有状态：`draft | review_ready | needs_revision | approved | rejected | watchlist`。
- `lineage_trace`
  - source_strategy -> query_plan -> reading_queue -> leads -> artifacts -> evidence -> worker_reports -> judgement -> candidate_synthesis -> audit。
  - 每个节点保留 id、summary、decision、rationale、input_refs、output_refs。
- `harness_context`
  - worker session compact summaries。
  - ContextPack 中最近轮次、selected/skipped/failed leads、tool calls、budget/failure summary。
  - compaction memory 中与结论相关的摘要。
- `material_windows`
  - 每条 approved/provisional EvidenceCard 的 source_location 前后段落窗口。
  - article/PDF/txt artifact 的标题、日期、段落片段、下载/读取元数据。
  - browser observe/execute delta、network_api_candidate 摘要、document capture refs。
  - 从所有相关 `network_worker_runs[].artifact_dir` 构造 multi-root artifact resolver 后解析，不只读取最后一轮 artifact。
  - 不包含 raw HTML 全文，不把导航页/搜索页作为正文证据。
- `worker_judge_audit_bundle`
  - WorkerReport findings、self_check、discarded_findings、remaining_blind_spots。
  - JudgementReport consensus、contradictions、partial_coverage、unique_insights、next_round_plan。
  - AuditReport scorecard，尤其是 evidence_support、required_rework、comments。
- `source_audit_bundle`
  - whitelist tier、source type、SourceQualityAssessment、open source quality status。
  - skipped/failed leads 和访问失败原因。

#### 7.3 ReportContextPipeline

单靠机械代码去重和校验不可靠，因为近义发现、材料重要性、矛盾边界、弱信号价值和报告取舍都需要模型判断。`ReportContextPipeline` 拆成三层：

1. `ContextIndexer`：程序化索引。
   - 从 DomainStore、DomainTraceEvent、harness session、ContextPack 和 artifact index 中收集候选材料。
   - 读取 artifact 时使用所有 worker round 的 artifact roots；部分目录缺失只记录 warning，required refs 无法解析才失败。
   - 按 id、source/artifact/location、trace edge 做确定性去重。
   - 构建可追溯候选池，不做语义取舍。
2. `context_curator` agent：模型参与上下文策展。
   - 阅读候选池、agent report notes、worker self-check、judge/audit 输出和材料窗口。
   - 合并近义 findings，识别主证据链、背景材料、反证、弱信号、被丢弃判断和缺口。
   - 为每个保留/降级/排除的材料写 `curation_reason`，并标注 `report_use`: `core | support | background | limitation | open_question | exclude`。
   - 不得新增 evidence/source/candidate/audit/judgement id，不得重新判定 audit 结论。
3. `ContextVerifier`：程序化校验。
   - 校验 curator 输出中的所有 id 都存在且可追溯。
   - 校验 core/support 材料没有越过 audit allowed/blocked 范围。
   - 校验 material windows 不包含 raw HTML 全文，引用位置能回到 artifact。
   - 校验 token budget，必要时把低优先级内容转成 artifact refs。

curator agent 的输入不是全量日志，而是 `ContextIndexer` 产出的候选池；curator 的输出也不能直接给 reporter，必须先经过 `ContextVerifier`。这样保留模型对语义取舍的能力，同时用代码保证引用、权限和预算边界。

`ReportContextPipeline` 的原则：

- 模型负责语义归并、重要性排序和取舍解释；代码负责索引、引用校验、权限标记和上下文裁剪。
- 长材料只给窗口和 artifact refs，必要时允许 reporter 调用只读 context expansion 工具读取更多段落。
- 保留负面信息：skipped leads、failed fetch、弱相关证据、未解决矛盾、audit 降级原因。
- 同一事实由 curator 选择主证据链，重复来源进入附录；verifier 只检查主证据链 refs 是否存在和允许。

#### 7.4 Reporter Agent

新增 `workers/agents/reporter.md`：

- 输入：`ReportContextBundle`。
- 可用工具：`generate_demand_report`，可选只读 `expand_report_context`。
- 禁止工具：search/fetch/browser/write candidate/audit/judgement。
- 输出：中文报告 sections 或 markdown body，并调用 `generate_demand_report`。

reporter 规则：

- 不得新增未在 trace/material/audit 中出现的核心事实。
- 不得引入新的 evidence id 或 source id。
- 不得把 open question、blind spot、adjacent/weak evidence 写成确定结论。
- 每个核心结论必须引用 evidence id、judgement id 或 audit scorecard item。
- 未解决 contradiction 必须进入“矛盾与限制”。
- `needs_revision/watchlist` 报告也要完整解释：已确认内容、不能正式回答的原因、缺失证据、优先补证 source/route。
- 用户可见正文使用中文分析；外文标题、机构名、原文短引可保留原文。

#### 7.5 一致性门禁

reporter 生成后，report gate 做程序化一致性校验：

- report.evidence_ids 必须来自 ReportContextBundle 的 allowed evidence。
- core conclusion 中引用的 evidence 必须通过 audit evidence-support review。
- blocked_claims 不得出现在确定性结论中。
- unresolved contradictions 必须在正文中解释或导致 `needs_revision`。
- required_caveats 必须出现。
- review_status 必须与 audit conclusion、evidence_support scorecard 和 tier cap 一致，并复用既有状态枚举。
- report 的 domain_trace_ids 必须覆盖 candidate_synthesis、audit、report_generated，并能追溯到 evidence/source。

如果校验失败，不让 ReportPublisher 自行改写正文。真实 path 应写 `report_consistency_failed` trace/summary 并停止报告阶段，不生成 `DemandReport`；如果未来引入 reporter revision，也必须在重新通过 consistency gate 后才允许入库。

#### 7.6 生成流程

真实 autonomous path 调整为：

```text
candidate_synthesis
-> audit agent
-> ContextIndexer builds candidate context pool from DomainStore + trace + harness context + artifacts
-> context_curator agent selects, merges, explains, and ranks report materials
-> ContextVerifier validates refs, audit permissions, lineage, and token budget
-> ReportContextBundle
-> reporter agent
-> generate_demand_report tool
-> report consistency gate
-> ReportPublisher publishes human-readable report.md
-> ReportPublisher writes report_manifest.json and optional appendices
```

fake mode 可保留 deterministic report fixture，但必须标记为 fixture report，不能代表真实报告质量。

正式 `review_ready` 报告至少包含核心判断、场景边界、能力缺口推理链、证据链、反证/限制、可信度评级和下一步补证建议。`needs_revision/rejected/watchlist` 报告也必须说明已确认内容、不能定论的原因、audit 意见、缺失证据、矛盾限制和下一步补证计划。

2026-06-30 实施状态：真实 autonomous path 已接入 `ContextIndexer -> context_curator agent -> ContextVerifier -> reporter agent -> generate_demand_report -> consistency gate -> ReportPublisher`。`context_curator` 和 `reporter` 均复用 `DemandDiscoveryPromptBuilder`，分别只暴露 `record_report_context_curation`、`generate_demand_report/expand_report_context` 受限工具；`ReportPublisher` 只写 `report.md` 与 `report_manifest.json`，不生成或润色正文。`_render_autonomous_report_body()` 只保留给 fake fixture path，真实 runner 使用所有 `network_worker_runs[].artifact_dir` 构造 multi-root artifact resolver 后进入 ReportContextPipeline。

2026-07-01 配置修正：需求挖掘真实链路默认模型按 `gpt-5.5` / 256k context window 设计，不再沿用 demo 级小预算。默认 agent `max_tokens` 为 240000，报告链路 `ContextPack.token_budget` 为 200000；默认 compaction window 为 256000，reserve 为 32000，recent retention 为 40000；Responses-compatible 请求默认带 `reasoning.effort=xhigh`。这些值是对模型能力的默认利用上限，不改变工具白名单、引用校验、audit/report gate 或 publisher 职责边界。

### 测试

- autonomous real path 不允许调用 `_render_autonomous_report_body()` 作为真实报告正文生成器。
- ContextIndexer 能收集 source_strategy、leads、artifacts、evidence、worker reports、judgement、audit 和 trace refs。
- context_curator agent 能把近义 findings 合并为主证据链，并为保留/排除写 curation_reason。
- ContextVerifier 能拒绝 curator 输出中的不存在 id、未授权 evidence 或 raw HTML 窗口。
- ReportContextBundle 能保留 curator 的 report_use、curation_reason 和 verifier warnings。
- reporter agent 只能调用 `generate_demand_report` 和只读 context expansion 工具。
- reporter 新增未授权 evidence id 时，report consistency gate 拒绝。
- blocked_claims 出现在确定性结论中时，真实 path 不生成 `DemandReport`，并记录 consistency failure。
- unresolved contradiction 必须进入报告正文并降级 review_status。
- needs_revision/rejected/watchlist 报告仍有完整降级原因、audit 意见、缺失证据和补证计划。
- ReportPublisher 写出 `report.md` 和 `report_manifest.json`；`report.md` 不堆叠 id 清单、trace dump 或 JSON control block。
- `report_manifest.json` 包含 report/candidate/audit/judgement/context/evidence/trace/status 等机器字段。
- 外文 evidence 输入时，报告分析段落为中文。
- context expansion 只能读取 artifact 窗口，不返回 raw HTML 全文。

### 验收

报告不再只是固定 section 的短文本或 candidate statement 包装；reporter agent 能利用经过模型策展和程序化校验的完整 trace、harness context 和材料窗口解释“为什么这么判断”“证据链从哪里来”“为什么还不能定论”。程序化代码不独自决定哪些材料最重要；它负责索引、校验、一致性门禁和发布。真实调用/校验失败与业务降级必须分开：前者失败报告阶段且不生成 `DemandReport`，后者生成可读解释性报告。人读 `report.md` 只承载正文和必要自然语言证据说明，控制字段由 `report_manifest.json` 承载。

## 8. 诊断七：质量指标与运行可靠性

### 问题

真实 run 需要区分 provider/network 波动、工具能力不足、planner 选源错误、worker 未补证、gate 正确降级、context index 不足、context curator 取舍错误、ContextVerifier 拦截、reporter 草稿不一致和 publisher 发布问题。如果没有统一指标，复盘只能看最终 report。

### 设计

#### 8.1 分层设计

质量诊断不能只靠一个大 `RunQualitySummary` schema，也不能在真实失败样本不足时依赖模型复盘 agent 做根因判断。首版拆成三步演进：

1. 当前必须实现：`RunQualityFacts` 和 `ProviderAttemptLog`。它们只记录事实，从 DomainStore、trace、harness session、artifact index 和 provider stream 派生。
2. 当前必须执行：人工 smoke 复盘记录。真实 run 失败后由人工根据 facts、attempt log、trace/session/artifact refs 判断最可能原因，并写入 smoke 文档或 run-local review note。
3. 后续引入：`RunQualityReview` 和 `QualityReviewVerifier`。只有在积累足够真实失败样本和人工复盘标签后，`quality_reviewer` 才以 shadow mode 运行，用于对照人工判断，不影响 gate、报告结论或自动重试。

事实源仍然是 DomainStore、DomainTraceEvent、harness session、provider attempt log 和 artifact store。`RunQualityFacts` 只是便于人和模型快速复盘的结束快照，不作为新的权威事实源。

新增字段遵循最小化原则：

- 能从单个 domain object 读取的状态，不在 quality 层另存一份；只在 `status_snapshot` 中保留结束时快照和原始 ref。
- 能从分布字段求和得到的计数，不再单独增加字段，避免趋势统计和明细不一致。
- 语义判断不新增平行 schema；证据是否支撑 topic / candidate demand 继续由真实 audit 的 evidence-support review 负责，quality 层只引用其结果。
- 质量复盘不替代 judge、audit、reporter；它只解释运行为什么产出当前质量。
- `quality_reviewer` 不进入首版验收；样本不足时宁可输出人工未定结论，也不能生成看似完整但不可验证的模型归因。

#### 8.2 RunQualityFacts

保留低冗余、可计算的事实快照：

- `round_count`
- `worker_count`
- `tool_call_counts`
- `source_counts`
  - selected / skipped / failed
  - whitelist / open_web
- `body_evidence_count`
- `evidence_count`
- `audit_evidence_support_distribution`
  - direct / partial / adjacent / weak / irrelevant / unassessed
- `source_tier_distribution`
- `language_distribution`
- `judgement_counts`
  - consensus / contradiction / unresolved_contradiction / blind_spot
- `status_snapshot`
  - candidate_status
  - audit_conclusion
  - report_review_status
- `phase_metrics`
  - source_strategy / query_plan / search / fetch / read / worker / judge / audit / context_index / context_curator / context_verifier / reporter / consistency_gate / publisher / provider

不保留 `direct_relevance_evidence_count`、`weak_relevance` 这类暗示独立 relevance gate 的字段；证据支撑分布从 audit evidence-support review 派生。

搜索质量按 round 记录为派生明细，而不是单独事实源：

- queries used
- matched whitelist hits
- outside-whitelist hits
- selected/skipped/failed leads
- body reads
- evidence cards
- audit evidence-support distribution
- open_search triggered / not triggered reason

#### 8.3 ProviderAttemptLog

provider 可靠性不塞进 `RunQualityFacts` 的字段列表，而是每次请求写独立 attempt log：

- `provider_attempt_id`
- `agent_run_id`
- `phase`
- `model`
- `endpoint_mode`
- `request_size`
- `attempt_index`
- `retry_reason`
- `http_status`
- `response_event_count`
- `last_event_type`
- `last_tool_call_id`
- `first_semantic_event_emitted`
- `semantic_progress_made`
- `failure_before_or_after_semantic_event`
- `elapsed_before_failure_ms`
- `adapter_error`
- `retry_headers_summary`

`ProviderAttemptLog` 是 provider 调用事实记录，不是根因结论。它应作为 trace event 或 artifact 写入，并用 ref 被人工 smoke 复盘和后续 shadow review 引用；不要在 attempt log 里直接写“网络波动”“设计缺陷”这类语义结论。

`RunQualityFacts` 只聚合：

- `provider_attempt_count`
- `provider_failure_count`
- `provider_failure_distribution`
- `last_provider_failure_ref`

远程关闭原因首版由人工 smoke 复盘结合 attempt log、trace 和 harness session 判定，而不是由 adapter 直接下结论。后续 shadow `RunQualityReview` 只能提出待验证建议。首版人工判断规则：

- `remote_closed_before_semantic_event` 且无工具调用、重试成功：优先判为 provider/network transient。
- 多次在同一 endpoint、同一 request size 附近关闭：判为 provider instability 或超时/限流配置问题，需要引用多条 attempt log。
- 已产生工具调用后关闭：不自动重试；review 需要检查 tool result、adapter stream parser 和 duplicate-tool 风险，可能判为 adapter/tool orchestration 设计问题。
- 只在超大 context 或 reporter 阶段出现关闭：优先检查 context packing、artifact window 和请求体规模。
- browser/search/fetch 工具持续失败但 provider 正常返回：不归因 provider，应归入工具能力、站点阻断或 planner 选路问题。

#### 8.4 人工 smoke 复盘记录

真实失败样本不足时，优先保留人工复盘，而不是马上新增 `quality_reviewer` agent。每次真实 smoke 或真实失败 run 至少记录：

- run id、topic、mode、provider endpoint mode、model、是否允许 browser/open search。
- `RunQualityFacts` ref。
- 关键 `ProviderAttemptLog` refs。
- 关键 trace/session/artifact refs。
- 失败发生阶段：provider / source_strategy / query_plan / search / fetch / browser / read / worker / judge / audit / context / reporter / publisher。
- 人工判断：最可能原因、贡献因素、证据依据、不能确定的部分。
- 下一步验证动作：例如缩小 context 重跑、更换 endpoint 重跑、复用同一 artifact 只重跑 reporter、单独重放 adapter parser、补充 SourceProfile 后重跑。

人工复盘允许写 `insufficient_evidence_to_diagnose`。这比强行归因更有价值，因为它能暴露当前 trace/attempt log 仍缺什么。

#### 8.5 后置 RunQualityReview

`quality_reviewer` agent 后置到失败样本积累之后，并且先以 shadow mode 运行。

启用条件：

- 已有一批真实失败 run，覆盖 provider remote close、403/404/JS 动态页、白名单耗尽、worker 未补证、audit 降级、reporter unsupported claim 等类别。
- 每类失败至少有人工复盘记录和可引用的 trace/session/artifact/attempt log。
- `RunQualityFacts` 和 `ProviderAttemptLog` 已稳定，不再频繁改字段。

输入：

- `RunQualityFacts`
- `ProviderAttemptLog` refs
- `DomainTraceEvent` compact view
- harness session summaries
- worker self-check、judge、audit、report context、reporter consistency gate 输出
- final report status 和降级原因
- 对应人工 smoke 复盘记录，作为对照而不是 prompt 中的唯一答案

输出：

```yaml
primary_failure:
  phase: report_context
  class: report_context_insufficient
  rationale: "..."
  refs: ["dt-...", "worker-session:...", "artifact:..."]
contributing_factors:
  - phase: source_strategy
    class: whitelist_exhausted
    rationale: "..."
    refs: [...]
  - phase: provider
    class: provider_remote_closed_after_tool_call
    rationale: "..."
    refs: [...]
confidence: medium
recommended_actions:
  - "补充 SourceProfile ..."
  - "重跑第 2 轮并允许 OpenSearchPlan ..."
```

shadow 复盘 agent 不能只输出标签，必须解释因果链：

```text
哪个阶段出现问题 -> 证据是什么 -> 对后续链路造成什么影响 -> 推荐修复/重跑动作
```

`RunQualityReview` 只能提出“最可能主因”和“贡献因素”。如果事实不足以区分网络波动和设计缺陷，应输出 `insufficient_evidence_to_diagnose` 或 `confidence: low`，并把 recommended actions 写成可验证动作，例如“缩小 reporter context 后重跑”“更换 provider endpoint 重跑”“保留同一 context 仅重放 adapter parser 单测”。

shadow mode 期间，`RunQualityReview` 不参与：

- report gate
- candidate status
- 自动重试策略
- smoke 是否通过
- 正式报告结论

它的价值只通过和人工复盘对照来评估。若多次输出漂亮但不可验证的解释，应继续禁用。

#### 8.6 Failure Taxonomy

`failure_class` 不再是单个字段，而是 `primary_failure.class` 和 `contributing_factors[].class` 的受控枚举：

- provider: `provider_timeout`、`provider_remote_closed_before_semantic_event`、`provider_remote_closed_after_tool_call`、`provider_auth_failed`、`adapter_parse_error`
- source/search: `no_whitelist_match`、`whitelist_exhausted`、`open_source_quality_rejected`、`search_query_language_mismatch`
- fetch/read/browser: `http_403`、`http_404`、`no_body_evidence`、`browser_action_failed`、`javascript_blocked`
- worker/judge: `worker_no_followup`、`worker_adjacent_only`、`judge_plan_too_generic`、`judge_plan_invalid_unusable`
- audit/report: `audit_evidence_support_failed`、`report_context_insufficient`、`context_curator_failed`、`context_verifier_rejected`、`reporter_unsupported_claim`、`report_consistency_failed`、`report_gate_degraded`

#### 8.7 后置 QualityReviewVerifier

程序化校验：

- `primary_failure.refs` 和每个 contributing factor refs 必须存在。
- provider 失败归因必须引用 ProviderAttemptLog。
- source/search/read/browser 失败必须引用 ResearchLead、tool trace 或 artifact ref。
- judge/audit/report 失败必须引用对应 JudgementReport、AuditReport、ReportContextBundle 或 DemandReport trace。
- 没有 refs 的复盘结论降级为 `diagnosis_unverified`，不能作为验收证据。

`QualityReviewVerifier` 只校验引用存在性、类型匹配和时间顺序，不判断复盘语义是否正确。语义正确性由人工复盘或后续对照实验验证，避免把机械代码伪装成根因分析。

在 `quality_reviewer` 未启用前，verifier 不需要作为独立组件实现；同类校验先落在 smoke 记录检查和 trace artifact 完整性检查中。

重试规则：

- 尚未产出语义事件时，transient remote close 可重试。
- 已产出文本或工具调用后，不自动重试，避免重复工具执行。
- 所有重试写 ProviderAttemptLog 和 trace。

### 测试

- fake run 生成 RunQualityFacts，但不把它当权威事实源。
- provider remote close before semantic event 写 ProviderAttemptLog 并可重试。
- remote close after tool call 不重试，并能从 ProviderAttemptLog 看出关闭发生在语义事件/工具调用之后。
- no body evidence run 能在 RunQualityFacts、trace 和人工 smoke 复盘记录中定位到 failed/read trace。
- report gate 降级写入 `report_gate_degraded`，人工 smoke 复盘必须说明是证据、audit、context、reporter 还是 consistency gate 导致，不能只写泛化原因。
- 真实 smoke 文档包含命令、脱敏配置、run dir、trace count、round count、provider attempt 摘要、人工复盘结论和下一步验证动作。
- 后置 fixture 才覆盖：quality_reviewer shadow 输出无 refs 时，QualityReviewVerifier 标记 `diagnosis_unverified`；unsupported reporter claim、whitelist exhausted then open search、provider close before semantic event、context curator 误排除核心证据等样本用于对照人工复盘。

### 验收

每次真实 run 都能回答“差在哪里”，但不是靠单个 failure_class、冗余统计字段或过早引入的模型复盘兜底。当前验收必须同时提供可计算事实、provider attempt 原始记录、可追溯 trace/session/artifact refs 和人工 smoke 复盘记录。质量趋势可以跨 run 比较，单次失败也能追溯到具体 trace/session/artifact，并能说明远程关闭更像网络/provider 波动、上下文规模问题、adapter 设计缺陷还是工具链问题；不能判断时必须明确写 `insufficient_evidence_to_diagnose`。

## 9. 总体验收

- 7 个诊断方向全部有可测 schema、trace 或 gate 变化。
- 所有真实网页与真实 provider 调用仍只做人工 smoke，不进入 CI。
- 白名单内调研必须优先执行；开放搜索只在白名单内无新增有效正文证据且证据仍不足时触发。
- 开放来源可读取公开正文，但必须经过 SourceQualityAssessment，并由真实 audit 的 evidence-support review 决定能否进入正式证据链。
- 报告质量不足时，系统能给出可审计降级原因和下一轮补证建议。
