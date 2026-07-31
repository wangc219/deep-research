# tests 目录导航

本目录用于存放当前项目新增脚本和流程的自动化测试。

## 当前文件

- `test_mineru_api_batch.py`：验证 MinerU API 结果 zip 的本地归档行为，不调用远程服务。
- `test_llm_client.py`：验证 A 组真实 LLM 配置可从 PowerShell 风格 `.env` 读取，并规范化 DeepSeek 模型名，不打印密钥。
- `test_llm_adapter_governance.py`：验证 A 组 LLM 适配器的 evidence quote 容错定位、缺失 SourceClaim 自动补全和弱表达治理字段归一。
- `test_analyze_stability.py`：验证抽取稳定性报告按 chunk 汇总结构有效性、claim 覆盖和弱表达覆盖。
- `test_evaluator.py`：验证评价器将结构校验 warning 与模型自报 warning 分离，并保留 trace 中的模型和 prompt 信息。
- `test_baseline_and_comparison.py`：验证 B/C 对照路径代理输出可通过统一结构校验，并验证结构评分在无弱表达样例下不会误扣分。
- `test_neo4j_kg_builder_adapter.py`：验证真实 Neo4j KG Builder 原始图适配为项目统一 `ExtractionResult` 时会过滤 lexical graph，把关系属性转换为 `SourceClaim` 与精确 evidence span，并在证据 quote 无法匹配时回退到 full chunk。
- `test_run_all_chunks.py`：验证 Phase 1 全量抽取脚本能在离线模式下写入 7 字段 SQLite 单表，并能跳过已有 chunk 结果。
- `test_phase3_migration.py`：验证 Phase 3 结构化 SQLite 迁移能生成可查询 schema、保留 attempt request/response hash 与路径、归一非法 `assertion_strength`、结构化 `Issue`，派生 chunk `content_type`，并用真实 Phase 1 数据做表计数回归。
- `test_entity_resolution.py`：验证 Phase 4 Entity Resolution v0.5 能用规则和内置别名表合并明显同义实体、标记文本自指噪声，并在真实 Phase 3 SQLite 上报告 coverage、真实合并率、singleton 占比和 canonical 数量等退出条件。
- `test_material_entity_governance.py`、`test_stage2_entity_governance_v2.py`：验证 Stage 2 Entity Governance v2 的清噪规则样例族、分类优先级、规则 alias 归一、输出库 schema、run audit 字段、规则/embedding/LLM 候选生成、模型 review 写入、Source guardrail、v2 same-entity merge audit、concept links、annotation snapshot 和 pairwise review 不直接覆盖实体级排除；不调用远程 LLM。
- `test_stage2_model_governance.py`、`test_stage2_apply_governance_merges.py`：验证 Stage 2.5 embedding/LLM 候选治理不会自动合并实体、可限制 embedding 实体池，并验证 Stage 2.6 只应用 `same_entity` review、保留非零 merge group 审计统计、写入实体路线参与资格和权重标注；不调用远程 LLM。
- `test_stage2_relation_data_enhancement.py`：验证 Stage 2.7 会为关系写治理标注、记录 dangling endpoint issue、按 canonical source/relation/target 聚合边、保留支撑 document/chunk provenance，并生成 relation review queue；不调用远程 LLM。
- `test_stage2_canonical_relation_review.py`：验证 Stage 2.8 canonical relation review 会按队列并发调用 reviewer、带入 chunk evidence context、写入 `canonical_relation_edge_reviews` 和 run 记录，并防止模型 raw_response 自引用导致 JSON 写库失败；不调用远程 LLM。
- `test_stage2_relation_review_corrections.py`：验证 Stage 2.9 会把 review 结果保守投影为改正后的 candidate relation edge：正确边保留、wrong_type 可安全改类型、reversed 可反向、context/unsafe 边不进入投影；不调用远程 LLM。
- `test_relation_quality.py`：验证 Relation Schema v2 新关系、`inference_eligible`、`trigger_text`、`extraction_rule_version` 和 relation quality validator 的最小行为。
- `test_relation_quality_ab.py`：验证 200 条分层样本采样逻辑、prompt/schema A/B 结构指标统计逻辑，以及人工标签 gate 的阈值计算和未标注失败行为；不调用远程 LLM。
- `test_relation_quality_v3_jsonl.py`：验证 Phase 1 风格 SQLite 可导出为标准 `ExtractionResult` JSONL，并验证 v3 JSONL 抽样会保留 `trigger_text`、`inference_eligible` 和规则版本等人工审核字段；不调用远程 LLM。
- `test_seven_relation_prompt_v4.py`：验证 v4 七类局部关系 prompt 只暴露七类关系、保持 route-blind 约束、包含实体类型边界与抽检暴露的关键负例、runner 能选择 v4 adapter，并验证 v3/v4 A/B evaluator 的结构指标和 prediction sanity check 报告；不调用远程 LLM。
- `test_prepare_route_discovery_benchmark_chunks.py`：验证路线发现 benchmark 可见来源预处理会清理 HTML 导航/侧栏噪声、保留正文，并确保 chunk 生成只读取 visible source、写入 `route-visible-preprocess-v2` 标记；不调用远程 LLM。
- `test_route_discovery_gold_layers.py`：验证路线发现 gold case 的 `evaluation_layers`、slot visibility/stage、edge stage/evidence policy 等分层标注会被脚本级 validator 检查；不调用远程 LLM。
- `test_route_discovery_extraction_coverage.py`：验证路线发现覆盖评估会拆分 input slot presence、extracted slot hit、slot stage hit、same-chunk endpoint co-occurrence、candidate endpoint readiness 和 direct edge relation hit，避免把路线级任务误判为 chunk 抽取失败；不调用远程 LLM。
- `test_stage3_route_candidate_generation.py`：验证 Stage 3 候选槽位/候选边生成不把候选标为事实、不泄漏 hidden/gold selection context、保留上下文实体关系，并验证实体治理标注会过滤 `excluded` 端点和降低泛称类候选边权重；不调用远程 LLM。
- `test_stage3_reviewed_edge_route_aggregation.py`：验证 Stage 3 reviewed-edge 路线聚合会从 Stage 2.9 `reviewed_canonical_relation_edges` 生成 literal slots、concept edges 和多跳路线，同时默认过滤非 `path_safe`、显式泛词和启发式泛词端点；不调用远程 LLM。
- `test_stage3_route_model_governance.py`：验证 Stage 3 路线模型治理会通过 Codex CLI reviewer 契约复核路线、拒绝异常路线、补充短边潜在路线、生成节点聚合和子图，并支持失败批次重试与只重审失败路线；单元测试使用 fake/recording reviewer，不调用真实模型。
- `test_material_governance_imports.py`、`test_material_runtime_codex_exec.py`、`test_material_runtime_utils.py`、`test_material_extraction_runner.py`：验证材料治理重组后的 runtime/material_governance 包导入、Codex exec 公共 transport、provider/retry/SQLite/manifest 工具，以及 Phase 1 SQLite 与 Codex chunk runner 迁移契约；不调用真实模型。
- `test_material_relation_governance.py`、`test_material_relation_codex_review.py`：验证 Stage 2.7-2.9 relation governance 已迁入 `material_governance/relation_governance`，并验证 canonical relation review 的 Codex CLI reviewer 契约和默认主线；单元测试使用 fake runner，不调用真实模型。
- `test_material_route_governance.py`：验证 Stage 3 route governance 已迁入 `material_governance/route_governance`，覆盖 reviewed-edge aggregation public API、route model review public API、gap review、node clusters、route subgraphs 和 Codex CLI reviewer 契约；单元测试使用 fake/recording reviewer，不调用真实模型。
- `test_material_projection_audit.py`：验证材料治理最终候选投影审计会统计 binary projection graph shape、route/subgraph 数量、泛词泄漏、Source subtype 混合和 broader/narrower 误合并门禁；缺失可选表时返回 `not_applicable`，不调用真实模型。
- `test_material_governance_pipeline.py`：验证材料治理 pipeline config schema、unknown stage fail-fast、required/completion table 校验、stage range、skip/force、projection audit 双 DB 校验、manifest 落盘、filter/entity_normalization 默认 runner、默认 runner 端到端 smoke 和 dry-run CLI；测试使用 fake stage runner、临时 SQLite 或 fake review provider，不调用真实模型。
- `test_hypothesis_prediction_v0.py`：验证 v3 十五类关系到七类预测边的保守投影、`addresses` 反向映射为 `DRIVES`、上下文关系降级，以及 2/3-hop 规则能生成带证据路径并按文档去重的 `HypothesisLink`；不调用远程 LLM。
- `test_demand_discovery_imports.py`、`test_demand_discovery_types.py`、`test_demand_discovery_event_stream.py`、`test_demand_discovery_fake_provider.py`、`test_demand_discovery_tools.py`、`test_demand_discovery_agent_loop.py`、`test_demand_discovery_agent_harness.py`：验证需求挖掘模块的 Python 版 Pi harness 复刻基础能力，包括导入契约、类型、离线 fake provider、事件流、工具执行、agent loop 生命周期和 harness phase/queue/save point 行为；不调用远程 LLM。
- `test_demand_discovery_session_trace.py`、`test_demand_discovery_context_pack.py`：验证需求挖掘 harness 的 append-only session/domain trace store、save point trace flush、角色化 context pack、trace compaction 和 context snapshot rebuild；不调用远程 LLM。
- `test_demand_discovery_domain_models.py`、`test_demand_discovery_domain_tools.py`、`test_demand_discovery_responses_adapter.py`、`test_demand_discovery_demo.py`、`test_demand_discovery_manual_source_pack.py`、`test_demand_discovery_scheduler.py`：验证需求挖掘领域对象/store/domain tools、Responses/Codex 请求构造与 SSE 解析、离线 fake demo、manual source pack runner、real-mode dry-run 配置、本地 SSE stub 的 real-mode CLI 回归和 scheduler/worker 子 harness 调度；不调用远程 LLM。
- `test_demand_discovery_agent_defs.py`、`test_demand_discovery_spawn_worker_tool.py`、`test_demand_discovery_event_bus.py`、`test_demand_discovery_audit_rubric.py`、`test_demand_discovery_prompts.py`、`test_demand_discovery_e2e_fake.py`：验证 Phase 2 多 agent runtime，包括 markdown agent 定义、`spawn_worker` 工具、EventBus/progress、审核量表、角色 prompt 和 orchestrator fake 端到端链路；不调用远程 LLM。
- `test_demand_discovery_source_registry.py`：验证 Phase 3.1 信源白名单与 `SourceRegistry`，包括 schema 校验、URL host/path 匹配、甲方军事需求数据源首版覆盖、tier 状态上限与 `DomainStore` 钩子；不调用远程网络。
- `test_demand_discovery_source_strategy.py`、`test_demand_discovery_research_state.py`、`test_demand_discovery_context_pack_research_state.py`：验证 Phase 5 自治调研的 source strategy metadata、ResearchLead/ReadingQueue/ResearchRound JSONL 往返和 context pack compact 投影；不调用远程网络。
- `test_demand_discovery_artifacts.py`、`test_demand_discovery_page_simplify.py`、`test_demand_discovery_tool_fetch_page.py`、`test_demand_discovery_keyword_gate.py`、`test_demand_discovery_tool_read_document.py`、`test_demand_discovery_tool_search.py`：验证 Phase 3.2-3.4 的 artifact 缓存、白名单抓取与重定向复验、浏览器形态通用请求头、正文简化、段落精读、关键词门禁、BM25、本地 artifact 搜索、URL 模板搜索解析和通用 JS 后端 search API 发现；全部离线，不调用真实网络。
- `test_demand_discovery_tool_classify_source_page.py`、`test_demand_discovery_tool_discover_articles.py`、`test_demand_discovery_tool_download_document.py`、`test_demand_discovery_browser_actions.py`：验证 Phase 5 页面分类、文章发现、文档下载和基础浏览器 target action 兼容行为。栏目页只生成 ResearchLead / ReadingQueue，白名单外链接记录 skipped lead，HTML/TXT/PDF 生成可读 artifact，DOC/DOCX 只保存 raw artifact；legacy target action 只允许使用 observe 返回的 `target_id`，全部离线。
- `test_demand_discovery_browser_observe_scan.py`、`test_demand_discovery_browser_execute.py`、`test_demand_discovery_browser_javascript.py`、`test_demand_discovery_browser_recipe.py`、`test_demand_discovery_browser_worker_integration.py`：验证诊断二通用浏览器调研能力，包括高信息密度 observe、统一 `browser_execute`、`capture_current_document` 伪 target、审计型 JS、runtime safety policy、`BrowserRecipeDraft` 和 worker 工具面；全部离线，不调用真实浏览器或真实网络。
- `test_demand_discovery_autonomous_research_runner.py`、`test_demand_discovery_judgement.py`、`test_demand_discovery_judge_agent.py`、`test_demand_discovery_judge_synthesis.py`、`test_demand_discovery_judgement_plan_contract.py`、`test_demand_discovery_judge_plan_controller.py`、`test_demand_discovery_network_worker_planned_tasks.py`、`test_demand_discovery_research_loop.py`、`test_demand_discovery_candidate_synthesis.py`、`test_demand_discovery_autonomous_report_gate.py`、`test_demand_discovery_autonomous_e2e_fake.py`、`test_demand_discovery_open_search_adapters.py`、`test_demand_discovery_open_search_e2e_fake.py`：验证 Phase 5 topic-only 自治调研闭环，包括 source strategy、模型 judge agent 通过 `record_judgement` 写入结构化结果、诊断五 judge plan 契约、controller 停止条件、candidate synthesis、audit/report gate、受控开放搜索 adapter 配置和 trace 重建；real runner 测试用 patch 的 network worker 与 fake model provider 验证真实路径进入 round-level controller，不调用真实 API 或真实网页。
- `test_demand_discovery_evidence_support_policy.py`、`test_demand_discovery_audit_evidence_support.py`、`test_demand_discovery_audit_context.py`、`test_demand_discovery_model_prompt_builder.py`、`test_demand_discovery_autonomous_real_audit_worker.py`、`test_demand_discovery_autonomous_report_gate_evidence_support.py`、`test_demand_discovery_autonomous_audit_semantic_e2e_fake.py`：验证 audit 语义证据审查、prompt context 接入、report gate 降级和 fixture/real audit 边界；全部离线，不调用真实模型或真实网页。
- `test_demand_discovery_web_research_session.py`、`test_demand_discovery_context_pack_web_research_session.py`、`test_demand_discovery_model_prompt_builder.py`、`test_demand_discovery_worker_request_readability.py`、`test_demand_discovery_worker_self_check.py`、`test_demand_discovery_worker_research_store.py`、`test_demand_discovery_worker_report_self_check.py`、`test_demand_discovery_worker_stop_policy.py`、`test_demand_discovery_worker_stop_policy_hook.py`、`test_demand_discovery_scheduler_worker_stop_policy.py`、`test_demand_discovery_network_research_worker_loop.py`、`test_demand_discovery_context_pack_worker_research.py`：验证诊断三 worker 自主补证循环，包括 WebResearchSession compact working memory、DomainStore 全路径持久化、ModelPrompt 组装、WorkerSelfCheck/FollowUpInstruction、apparent-stop policy hook、重复注入/预算/无新增正文 artifact 门禁和 scheduler 接入；全部离线。
- `test_demand_discovery_network_research_runner.py`：验证 Phase 5 `run_network_worker_round` 取证执行器，离线执行 fetch/classify/read/evidence，确保 worker round 只导出 SourceRecord/EvidenceCard 而不生成 candidate/audit/report，覆盖 `allow_browser`、provider retry、开放搜索工具下传、`OpenSearchPlan -> OpenSourceLead -> fetch_open_source_page -> read_document` 工具链；不调用真实网络或真实 provider。
- `test_demand_discovery_report_context_models.py`、`test_demand_discovery_report_context_indexer.py`、`test_demand_discovery_report_context_curator.py`、`test_demand_discovery_report_consistency_gate.py`、`test_demand_discovery_reporter_agent.py`、`test_demand_discovery_reporter_agent_contract.py`、`test_demand_discovery_report_publisher.py`、`test_demand_discovery_autonomous_real_reporter_path.py`、`test_demand_discovery_autonomous_reporter_e2e_fake.py`：验证诊断六报告链路，包括 ReportContextBundle 往返、multi-root artifact 窗口索引、context_curator agent 工具策展、reporter prompt 看到完整 bundle、一致性门禁、publisher 人读/机器 manifest 分离，以及真实 autonomous path 不再调用模板正文；全部离线，不调用真实模型或真实网页。
- `test_demand_discovery_main_chain_cleanup.py`：验证旧 Phase 3 seed URL runner 导出和 `scripts/demand_discovery_network_research.py` 已移除，避免主链路外旧入口继续引发歧义。
- `test_demand_discovery_scheduled_runner.py`、`test_demand_discovery_intervention.py`、`test_demand_discovery_dedup.py`、`test_demand_discovery_human_review.py`、`test_demand_discovery_retention.py`：验证 Phase 4 非 silver case 的定时任务、文件 inbox 干预、程序化查重、人工审核/推送分级和分层留痕清理；全部离线，不调用真实网络或真实 provider。
- 需求挖掘 runtime 的完整回归入口可使用 `python -m unittest discover -s tests -p "test_demand_discovery*.py" -v`；运行时设计说明见 `docs/architecture/pi_harness_python_replication_runtime_design.md`。
- `test_cnki_keyword_crawler_paths.py`：验证知网关键词 crawler 默认把采集产物写入 `data/raw/cnki/`，且不打开浏览器、不访问知网。
- `test_journal_download_common.py`：验证期刊下载公共模块能从 manifest 识别成功记录、跳过失败记录，按已有非空 PDF 做文件去重，在重定向链路内保留服务端设置的 cookie，并对远端断连做有限重试。
- `test_download_wanfang_journals.py`：验证万方期刊脚本能解析权限跳转中的论文标题，按年份期号枚举整期论文 ID，跟随下载信息页中的 `NewFulltext` PDF 链路，对探测和下载瞬断有限重试，并通过《信息对抗技术》包装脚本进入 dry-run。
- `test_download_all_journals.py`：验证期刊批量采集编排脚本能解析万方 yearIssue grpc-web 响应、按刊目和年份过滤目标期次，并按 `data/raw/<journal>/<YYYY-II>/papers/` 生成单刊脚本调用参数。
- `test_download_hkxb.py`：验证航空学报脚本能按年份期号选择过刊 URL、解析期次页论文、规整 `showArticleFile.do` 返回的 PDF URL、下载瞬断重试，并保证控制台 JSON 输出不会被 Windows GBK 编码阻断。
- `test_literature_diagnostic_sampling.py`：验证 100 篇文献诊断样本的 Markdown 发现、按来源和覆盖标签分层抽样、chunk 可追溯性以及每篇代表 chunk 选择逻辑；不调用远程 LLM。
- `test_document_relevance_filtering.py`：验证文献级无关信息过滤会排除 `信息动态`、`征稿启事`、`专题征文` 等非研究输入，同时保留“发展动向分析/综述”等研究类标题，并确保过滤后 manifest/chunk 可追溯；不调用远程 LLM。
- `test_web_monitor_live_animation.py`、`test_web_evidence_safe_close.py`、`test_web_evidence_route_graphs.py`：验证 `web/` 静态前端的数据监控动效、证据研判悬浮层安全关闭、前三候选路线图数据、层级高亮、边详情和报告跳转契约。
- `test_web_report_generation.py`、`test_web_review_workflow.py`：验证创意报告生成过程、正式报告内容、专家评审队列状态同步、核验详情和来源状态柱状图契约。

## 维护约定

- 新增脚本行为时优先补充对应单元测试。
- 测试不得依赖真实 API Key、远程服务或用户本地私有路径。
- 如测试需要读取样例文件，应使用临时目录或仓库内明确的测试夹具。
