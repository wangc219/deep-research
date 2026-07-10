# Demand Discovery Phase 5 信源画像与 QueryPlanner 设计

日期：2026-06-23

## 1. 背景

Phase 5 已经支持 topic-only 自治调研，但 source selection 仍然偏浅：planner 主要看到白名单元数据、语言、少量 topic tags 和动态生成 query。这个输入不足以让系统理解“每个网站应该怎么用”，也容易把真实调研拖向少数已有默认主题。

本设计新增稳定、人工审计通过的信源画像。每个白名单信源分为两层资料：

- 简化索引：供 QueryPlanner 粗筛所有信源。
- 完整 profile：只在信源被选中后细读，用于生成路由、检索和 worker 任务。

## 2. 目标

- `source_whitelist.yaml` 只保留准入信息：host、path、tier、transport、entry URL 和安全边界。
- 每个核心信源补充网站路由、内容结构、搜索方式、证据规则和已知限制。
- QueryPlanner 先读全量简化索引，再只读取选中信源的完整 profile，避免上下文膨胀。
- 系统调研后可输出 draft profile，人工审计通过后再成为稳定配置。
- 取消 topic-specific default query 偏置；query 必须由用户 topic、source language、route guidance 和上一轮 judgement plan 派生。

## 3. 非目标

- 不做定期爬虫或自动后台刷新 profile。
- 不默认开放任意网页 JS、任意 selector 或白名单外抓取；白名单内调研耗尽且证据仍不足时，可进入受控开放搜索与开放来源评估路径。
- 不为每个网站写特化 scraper。profile 描述使用方式，通用工具负责搜索、抓取、观察、动作、下载和读取。
- 不允许从首页、栏目页、搜索页、导航文本、404/access-status 页面直接生成 EvidenceCard。

## 4. 文件位置

稳定配置：

- `configs/demand_discovery/source_whitelist.yaml`
- `configs/demand_discovery/source_profiles/index.yaml`
- `configs/demand_discovery/source_profiles/<source_id>.yaml`

运行产物：

- `outputs/runs/<run_id>/source_profile_drafts/<source_id>.yaml`
- `outputs/runs/<run_id>/source_profile_drafts/review_manifest.json`

实现模块：

- `src/knowledgegraph/demand_discovery/domain/source_profile.py`
- `src/knowledgegraph/demand_discovery/domain/query_planner.py`
- `src/knowledgegraph/demand_discovery/domain/source_strategy.py`
- `src/knowledgegraph/demand_discovery/harness/research_loop.py`
- `src/knowledgegraph/demand_discovery/network_research.py`

## 5. SourceProfileIndex

`index.yaml` 是 QueryPlanner 的粗筛目录，必须足够短，可以一次性进入 context。它不使用 `best_for` / `weak_for` 这类枚举，因为真实 query 多变，固定枚举会带来偏置。核心字段改为简短内容总结。

示例：

```yaml
version: 1
profiles:
  - source_id: chinamil_81cn
    source_name: 中国军网
    whitelist_source_name: 中国军网
    tier: A
    source_type: official_media
    languages: [zh]
    profile_status: human_reviewed
    content_summary: >
      中国官方军事新闻与评论网站，覆盖军队动态、训练演训、装备应用、
      政策表述、专题报道和部分理论文章；适合作为官方公开表述、
      事件线索和正文证据入口，但深度学术论文和技术参数通常需要转向期刊或报告类信源。
    routing_summary:
      - 首页与栏目页用于发现文章线索。
      - 站内检索适合中文关键词。
      - 专题页适合按事件、任务或能力方向追踪系列报道。
    search_capabilities:
      site_search: true
      browser_required: false
      js_api_discoverable: true
    evidence_hint:
      strong_after_article_read: true
      listing_only_as_lead: true
```

## 6. SourceProfile

完整 profile 只在 QueryPlanner 选中信源后加载。

建议字段：

- `identity`：source id、名称、白名单绑定、tier、语言和 profile 状态。
- `site_content_model`：网站内容结构和信息密度说明。
- `route_map`：入口、栏目、检索页、期刊目录、报告库、英文版等路由。
- `search_methods`：站内搜索模板、表单行为、可观察 JS/XHR API、fallback route。
- `query_guidance`：如何把用户 topic 转成该网站语言下的查询。
- `interaction_guidance`：什么时候用 HTTP、browser observe/action、分页、下载按钮或 API 发现。
- `document_guidance`：HTML/TXT/PDF/DOC/DOCX 的处理预期。
- `evidence_policy`：哪些页面只能生成 lead，哪些页面读取正文后可生成 EvidenceCard。
- `known_limits`：403、404、登录、搜索质量差、route stale、rate limit 等。
- `review_metadata`：draft run id、生成时间、审计人、审计时间和审计说明。

默认只使用 `profile_status: human_reviewed` 的 profile。`draft` profile 只能作为运行产物供人工复盘，不进入正常规划。

## 7. QueryPlanner

输入：

- 用户 topic。
- 可选 seed URL。
- SourceRegistry。
- SourceProfileIndex。
- 上一轮 judgement 的 `next_round_plan`。
- 运行约束：max workers、allowed tiers、allow_browser、transport、预算。

规划流程：

1. 从 topic 和上一轮 plan 生成 2-4 个调研方向。
2. 基于 `content_summary`、`routing_summary`、语言、tier、transport 和 search capability 粗筛信源。
3. 优先选择多样化 source，而不是同一网站多个入口。
4. 读取选中 source 的完整 profile。
5. 根据 topic 和 `query_guidance` 生成 source-language query set。
6. 生成 `ResearchPlan` 和多个 `WorkerAssignment`。
7. 当 judge 确认白名单内无新增有效正文证据、候选需求仍缺少 direct/partial evidence，且预算允许时，生成 `OpenSearchPlan`，进入广度优先开放搜索路径。

`default_queries` 只能作为兼容旧逻辑的 legacy hint，不能作为 Phase 5 主查询来源。

## 8. 开放搜索触发条件

开放搜索不是默认第一步。系统必须先完成白名单内 source profile 驱动调研，再由 controller 程序化判断是否触发广搜。

触发条件：

- 至少完成一轮白名单内 ResearchPlan。
- 白名单内 selected source 已执行主要 route 或 search guidance。
- 本轮新增 direct/partial 正文证据不足以支撑 candidate synthesis。
- judge 的 `next_round_plan` 标记 `need_broad_search=true` 或包含 `open_search_candidate` task，并说明缺口。
- 预算允许继续 search/read。

开放搜索输出不再简单按“白名单外跳过”处理，而是进入开放来源评估路径：

```text
open_search
-> open_source_lead
-> fetch/read public body
-> SourceQualityAssessment
-> audit evidence-support review
-> accepted/provisional/background/rejected evidence usage
```

白名单内来源默认审查成本较低；白名单外来源必须通过更严格的 `SourceQualityAssessment`，并在报告中明确标识来源等级和审计状态。

## 9. ResearchPlan 与 WorkerAssignment

`ResearchPlan` 必须持久化，便于 trace 重建“为什么选择这些网站”。

核心字段：

- `plan_id`
- `topic`
- `round_id`
- `research_directions`
- `selected_source_ids`
- `held_source_ids`
- `worker_assignments`
- `planner_rationale`

`WorkerAssignment` 字段：

- `assignment_id`
- `round_id`
- `direction_id`
- `source_id`
- `source_name`
- `entry_routes`
- `query_set`
- `language`
- `allowed_tools`
- `route_instructions`
- `evidence_policy`
- `expected_outputs`
- `coverage_expectation`
- `budget_hint`

默认一个 worker 对应一个网站。只有小型且高度相关的 source 才允许组合。

## 10. Controller 集成

round-level controller 流程调整为：

```text
source_strategy
-> query_plan
-> workers
-> judge
-> optional_open_search_plan
-> open_source_quality_gate
-> continue/stop
-> candidate_synthesis
-> audit/report gate
```

不重写 `AgentLoop`、`DiscoveryHarness` 和 `Scheduler` 内核；新增行为放在 planner state、assignment brief 和 round-level orchestration。

## 11. Draft Profile 与人工审计

真实 run 可以在 `outputs/runs/<run_id>/source_profile_drafts/` 产出 draft profile，记录：

- 可访问 route。
- 可用搜索 URL 或 browser search flow。
- 观察到的 JS/XHR endpoint pattern。
- 文档下载行为。
- 内容类型。
- evidence eligibility。
- 访问失败和 fallback。

draft profile 不自动更新配置。人工审计通过后，才合入 `configs/demand_discovery/source_profiles/` 并同步 `index.yaml`。

人工审计检查：

- route 是否仍命中白名单 host/path。
- route 是否公开且可安全访问。
- search guidance 是否 topic-neutral。
- evidence policy 是否保持 lead/body separation。
- known limits 是否明确记录。
- 是否包含私有凭证、cookie、API key 或敏感 header。

## 12. 验收

- topic-only fake run 能生成至少两个 source-specific WorkerAssignment。
- real worker brief 只包含被选中 source 的完整 profile guidance。
- draft profile 不会影响默认 planner 行为。
- profile route URL 都能通过 SourceRegistry 校验。
- 白名单不再积累 topic-specific default query 偏置。
- 白名单内证据不足时，controller 能触发 OpenSearchPlan，并对开放来源执行 SourceQualityAssessment 后再决定是否进入证据链。
