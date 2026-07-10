# scripts 目录说明

本目录用于存放项目后续可复用的本地编排脚本。正式抽取核心逻辑应放在 `src/knowledgegraph/`，脚本只保留 CLI、批处理、实验评价和报告生成入口。

## 当前文件

- `journal/download_zsdd.py`：战术导弹技术期刊站点的公开论文 PDF 下载验证脚本。支持按门户/过刊 URL 解析论文，也支持通过 `--year` 和 `--issue` 自动匹配某一期过刊 URL，按 manifest 和已有 PDF 断点续跑。
- `journal/download_ktfy.py`：空天防御期刊站点的公开论文 PDF 下载验证脚本。支持按过刊归档页、期次 URL 或 `--year` / `--issue` 自动解析期次目录并下载公开 PDF，按 manifest 和已有 PDF 断点续跑。
- `journal/journal_download_common.py`：期刊采集脚本公共工具，提供文件名清洗、支持重定向 cookie 和网络瞬断有限重试的 HTTP 请求、cookie 读取、manifest 成功记录识别、断点续跑和已有文件去重判断。
- `journal/wanfang_journal_downloader.py`：万方期刊公共下载器，按 `刊号 + 年份 + 期号 + 三位序号` 枚举整期论文，解析下载入口权限跳转中的题名，支持交易授权页内 `NewFulltext` 二段式 PDF 下载，并对探测和下载中的网络瞬断做有限重试，复用断点续跑和去重逻辑；manifest 不记录带交易 token 的最终 URL。
- `journal/download_xxdkjs.py`：《信息对抗技术》万方期刊下载脚本。支持 `--year` / `--issue` 指定期次、`--max-papers -1` 整期批量、断点续跑、已有 PDF 去重、`--dry-run` 和合法 cookie 输入。
- `journal/download_dzdkjs.py`：《电子信息对抗技术》万方期刊下载脚本。支持 `--year` / `--issue` 指定期次、`--max-papers -1` 整期批量、断点续跑、已有 PDF 去重、`--dry-run` 和合法 cookie 输入。
- `journal/download_hkxb.py`：《航空学报》期刊下载脚本。支持从年份页自动匹配期次 URL、解析 `showArticleFile.do` PDF token、规整站点返回的异常 PDF URL、整期批量、下载瞬断有限重试、断点续跑、已有 PDF 去重和 `--dry-run`。
- `journal/download_all_journals.py`：期刊批量采集编排脚本。自动发现战术导弹技术、空天防御、信息对抗技术、电子信息对抗技术和航空学报的可用期次，按 `data/raw/<journal>/<YYYY-II>/papers/` 调用单刊脚本下载，并在 `data/raw/journal_batch_manifest.jsonl` 记录逐期执行状态；支持 `--journal`、`--start-year`、`--end-year`、`--max-issues`、`--max-papers-per-issue`、`--dry-run` 和断点续跑。
- `run_all_chunks.py`：Phase 1 全量 chunk 抽取脚本。读取标准化 `chunks.jsonl`，调用 `src/knowledgegraph/extraction` 中的 A 组 Schema-Guided extractor，将每个 chunk 的原始 LLM 响应、结构化 JSON、schema 版本和粗粒度状态写入单表 SQLite；不写 Neo4j、不做候选治理库。
- `migrate_phase3_sqlite.py`：Phase 3 结构化 SQLite 迁移脚本。读取 Phase 1 单表 SQLite 和标准化 `chunks.jsonl`，写入 `Document / Chunk / Extraction / ExtractionAttempt / EntityMention / RelationAssertion / SourceClaim / EvidenceSpan / Issue` 等表，并把完整 request/response 归档到文件系统。当前 `content_type` classifier version 为 `content-type-rules-v2`。
- `resolve_entities_sqlite.py`：Phase 4 Entity Resolution v0.5 脚本。读取 Phase 3 SQLite，复制到 Phase 4 输出目录，在副本上新增 `resolved_entities`、`entity_resolution_aliases` 和 `entity_mentions.resolved_entity_id` 等字段，用规则和内置高置信别名表完成实体归一，并报告真实合并率、singleton 占比和规则命中分布；不调用 Neo4j、embedding 或 LLM。
- `analyze_research_findings_v0.py`：Phase 4 后的真实研究查询验证脚本。只读 Phase 4 SQLite，创建临时 `canonical_relations` 查询表，按 document 去重口径复核高频统计并生成 `docs/experiment-artifacts/research_findings_v0.md`；不写数据库、不创建持久 read model、不引入 Neo4j。
- `build_hypothesis_links_v0.py`：基于 v3 全量 `ExtractionResult` JSONL 的七类关系投影与规则路径预测脚本。把 15 类关系保守投影为 `ENABLES / DRIVES / IMPLEMENTS / HAS_CAPABILITY / APPLIES_TO / CONSTRAINS / RESPONSIBLE_FOR`，生成 `projected_edges.jsonl`、`hypotheses.jsonl`、`summary.json` 和 `docs/experiment-artifacts/seven_relation_hypothesis_prediction_v0.md`；不调用 LLM、不重抽、不写 Neo4j。
- `review_relation_direction_v0.py`：Phase 4 关系方向与关系类型 spot check 脚本。只读 Phase 4 SQLite，按文档轮转抽样 high-confidence `enables / supports / applies_to` 关系，使用脚本内人工标签生成 `docs/manual-review/relation_direction_spotcheck_v0.md`；不写数据库、不进入 HypothesisLink。
- `sample_relation_quality_ab.py`：Relation Quality Hardening v0 的 200 条分层样本清单生成脚本。只读 Phase 4 SQLite，输出 `data/processed/relation_quality_ab/sample_manifest.jsonl` 和 `docs/manual-review/relation_quality_ab_sample_plan.md`；不调用 LLM、不写数据库、不计算未标注准确率。
- `export_phase1_sqlite_results.py`：把 `run_all_chunks.py` 生成的 Phase 1 风格 SQLite `payload_json` 导出为标准 `ExtractionResult` JSONL，并可同步生成结构性 `evaluation_summary`。主要用于 v3 全量并发抽取后复用既有 JSONL 评价和抽样流程。
- `sample_relation_quality_jsonl.py`：从标准 `ExtractionResult` JSONL 与对应 chunks 中生成 v3 关系质量人工审核样本，保留 `trigger_text`、`inference_eligible` 和 `extraction_rule_version` 等 v3 审核字段；不调用 LLM、不写数据库、不自动判断语义正确性。
- `evaluate_relation_quality_ab.py`：Prompt/schema A/B 结果对比脚本。读取 `ExtractionResult` JSONL 和对应 chunks，输出 `docs/experiment-artifacts/prompt_v2_ab_evaluation.md`；只比较结构字段、关系分布和 relation quality 字段覆盖率，不自动判断语义正确性。
- `evaluate_seven_relation_prompt_v4_ab.py`：v3 旧 prompt/schema 与 v4 七类关系 prompt 的同样本结构 A/B 对比脚本。自动取 v3/v4 共有 chunk，比对七类之外关系、claim/trigger_text 覆盖、治理健康指标，并可接入两侧 HypothesisLink summary；不自动判断语义正确率。
- `evaluate_relation_quality_labels.py`：Relation Quality 200 条人工标签门禁脚本。读取 `sample_manifest.jsonl` 与人工维护的 `manual_labels.jsonl`，生成 `manual_labels_template.jsonl` 和 `docs/manual-review/relation_quality_label_gate.md`；不调用 LLM、不写数据库，未满足人工标注门槛时以非零状态退出。
- `validate_route_discovery_cases.py`：路线发现 benchmark case 一致性校验脚本。读取 `data/benchmarks/route_discovery/gold_routes_v0.jsonl` 与 `source_manifest_v0.jsonl`，检查本地源文件、visible/holdout 分组、旧过程快照路径泄漏、gold edge 引用、slot 引用、slot/edge 分层评估字段和当前七类关系兼容性；不调用 LLM、不下载文件、不写数据。
- `audit_route_discovery_gold_evidence.py`：路线发现 benchmark gold slot 证据审核门禁脚本。读取 `gold_routes_v0.jsonl` 与 `gold_slot_evidence_audit_v0.jsonl`，检查每个 gold slot 是否有人工证据审核、来源 ID 是否一致、visible slot 是否有 visible evidence，并输出 JSON/Markdown gate 报告；不参与抽取或候选生成。
- `audit_route_discovery_gold_adequacy.py`：路线发现 benchmark gold 充分性门禁脚本。读取 `gold_routes_v0.jsonl` 与 Stage 3/3.2 候选库，诊断 strict hit 是否可能被 gold alias、endpoint、relation scope、route pattern 或 stage policy 过窄低估；只输出人工审核队列，不自动修改 gold，不参与候选生成。
- `route_discovery_gold_alignment.py`：路线发现 benchmark 的人工对齐包 loader。读取 `gold_alignment_v0.jsonl`，只在评价侧扩展 endpoint alias、route pattern variant 和 stage policy；拒绝未人工审核的记录，不参与候选生成。
- `prepare_route_discovery_benchmark_chunks.py`：路线发现 benchmark 可见来源 chunk 准备脚本。只读取 `visible_sources`，按 gold alias 引导选择每个可见来源的 Top-N chunk，输出 `chunks_visible_gold_guided.jsonl` 和 `chunk_selection_summary.json`；HTML 来源使用 `route-visible-preprocess-v2` 清理导航/侧栏噪声，不读取 hidden bridge source，不下载文件。
- `evaluate_route_discovery_extraction_coverage.py`：路线发现 benchmark 分层覆盖率评估脚本。读取抽取 SQLite、visible chunks 与 benchmark gold case，分别输出 input slot presence、extracted slot hit、slot stage hit、same-chunk endpoint co-occurrence、candidate endpoint readiness、edge stage counts、direct edge relation hit 和 slot/edge diagnosis；匹配时带实体类型 gate，不把 direct gold edge 当作抽取阶段唯一门槛。
- `run_codex_extraction_chunks.py`：路线发现 benchmark 与文献诊断样本的 Codex CLI 抽取 runner。复用当前七类关系 prompt 与 `run_all_chunks.py` 的单表 SQLite schema，通过本地 `CODEX_HOME` 配置调用 Codex CLI，把每个 chunk 的最终 JSON 消息解析、治理和结构校验后写入 `extractions` 表；默认读取 `route_discovery_visible_v4_3_gold_guided` 干净输入，使用 `D:\tmp\codex-rag-labeling-no-mcp`、`gpt-5.5` 和 `model_reasoning_effort=high`。支持 `--workers` 并发调用 Codex CLI，SQLite 写入仍在主线程串行完成；支持 `--chunk-id` 定点探针；Codex 子进程超时会清理进程树并把该 chunk 写成 `failed`。
- `filter_literature_diagnostic_sample.py`：文献诊断样本文档级过滤脚本。读取 100 篇样本 manifest/chunks 和可选抽取 SQLite，排除 `信息动态`、`征稿启事`、`专题征稿/专题征文` 等非研究输入，输出 `sample_manifest_research.jsonl`、`chunks_research.jsonl`、`chunks_probe_one_per_doc_research.jsonl`、过滤后的抽取库和 `sample_filter_report.json`；不重新抽取关系，不修改原始 100 篇输入。
- `demand_discovery_demo.py`：需求挖掘 Python harness 复刻 demo CLI。默认 `--mode fake` 离线运行 fake provider、domain tools、save point、DomainStore、audit 和 report 生成，并输出候选需求摘要与 trace JSONL；`--mode fake --watch` 运行 Phase 2 多 worker fake 剧本，订阅 scheduler 事件打印 worker 进度行，并按 `--output-root/--run-id` 写入 `progress.md`；`--mode real` 通过进程环境变量或仓库根目录 PowerShell 风格 `.env` 读取 `DEMAND_DISCOVERY_API_KEY`、`DEMAND_DISCOVERY_BASE_URL`、`DEMAND_DISCOVERY_MODEL` 等 provider 配置，调用 Responses/Codex-compatible SSE provider 跑同一套工具和 save point 流程；命令行 `--base-url`、`--model` 等参数可覆盖配置；`--dry-run-provider-request` 只打印脱敏 provider request 摘要，不调用远程服务、不打印 API Key 或 Authorization header。
- `demand_discovery_autonomous_research.py`：Phase 5 topic-only 自治调研 runner。只输入 `--topic` 即可从白名单 source strategy 选源，fake 模式离线生成两轮 `ResearchRound -> JudgementReport -> candidate_synthesis -> audit -> report` trace；`--seed-url` 仅作为人工约束，不再是自治路径必填；`--mode real` 进入 Phase 5 round-level controller，内部调用 `src/knowledgegraph/demand_discovery/network_research.py::run_network_worker_round` 作为每轮 worker 取证执行器，再由 judge、candidate synthesis 和 audit/report gate 收口；真实模式必须通过 `--api-key-env` / `.env` 提供 provider 配置，并支持 `--endpoint-mode`、`--base-url`、`--endpoint-path` 和 `--model`；`--mode codex` 分发到独立 `knowledgegraph.demand_discovery.codex_workflow`，由 Codex CLI 分别运行 planner/reader/judge/synthesizer/auditor/reporter 角色，本地执行白名单校验、reader 后证据材料化、judge-worker 多轮路由、DomainStore 导入、trace、报告质量重写门禁和 `report.md` 落盘，不调用 Phase 5 主链路；`--codex-max-worker-tasks-per-round` 控制每轮 reader worker 数，`--codex-max-report-rewrites` 控制 reporter 质量门禁重写次数；真实 API / 真实网页 smoke 需用户明确允许后执行。
- `demand_discovery_scheduler.py`：Phase 4 定时任务 runner 入口。读取 `configs/demand_discovery/scheduled_tasks/*.json`，按 schedule/repeat/done 报告执行一次 tick 或前台轮询，输出 done 报告和 `outputs/scheduled/runner.log`；`--mode fake` 用本地 fake provider 验证定时触发到 raw signal 落库，`--mode real` 复用 `DEMAND_DISCOVERY_*` provider 配置和 Phase 3 网络工具执行 task brief。
- `demand_discovery_review.py`：Phase 4 人工审核 CLI。读取 append-only domain JSONL，支持 `list`、`show <report_id>` 和 `decide <report_id>`，写入 `HumanReviewRecord`、更新 report/candidate 状态，并重写 `outputs/push/inbox.md` 与 `outputs/push/watchlist.md`。
- `demand_discovery_cleanup.py`：Phase 4 留痕清理 CLI。读取 `configs/demand_discovery/retention.yaml`，默认 dry-run 打印将删除的 runtime log、processed inbox、worker session 和未被 evidence 引用的旧 artifact；只有 `--apply` 才实际删除。
- `demand_discovery_manual_source_pack.py`：需求挖掘 manual source pack 第一轮真实实践入口。读取 `configs/demand_discovery/source_packs/*.json` 中的受控主题、白名单信源、工具约束和审核预期，禁用 search/fetch/read，只挂载领域写入工具链；`--mode fake` 用离线 fake provider 验证 `source -> evidence -> candidate -> audit -> report -> trace` 输出契约，`--mode real` 复用 `DEMAND_DISCOVERY_*` provider 配置调用真实 SSE provider；输出写入 `outputs/runs/<run_id>/` 下的 `run_config.json`、`domain.jsonl`、`trace.jsonl`、`session.jsonl`、`report.md` 和 `manual_review_checklist.md`。
- `stage2_entity_normalization.py`：Stage 2 实体归一化薄 CLI，核心实现位于 `knowledgegraph.material_governance.entity_normalization`。读取 Stage 1 风格 `extractions` SQLite，物化 `entity_mentions`、`relation_assertions`、`resolved_entities`、`entity_aliases`、`alias_seed_candidates`、`alias_seed_reviews` 和 `normalization_issues`；使用精确归一、模型审核 seed alias 和保守 noise alias，不重新抽取关系、不生成候选路线、不写 Neo4j。
- `stage2_model_governance.py`：Stage 2.5 模型治理 legacy experiment。读取 Stage 2 SQLite，复制到新库后追加 embedding 缓存、embedding alias candidates、大模型 alias candidate review 和全量 relation assertion review；默认不调用外部模型，必须显式指定 `--embedding-provider dashscope` 和 `--alias-review-provider llm --relation-review-provider llm` 才会产生外部调用。新文献材料治理主线不再默认调用该脚本，实体治理 v2 的 embedding provider 已收敛到 `knowledgegraph.material_governance.entity_governance.embeddings`。
- `stage2_apply_governance_merges.py`：Stage 2.6 治理合并应用脚本。读取 Stage 2.5 治理库，只应用 `same_entity` alias review，把合并结果写入新 SQLite，并保留 merge group、member 和 source review 审计表；不把关系候选升级为事实。
- `stage2_entity_governance_v2.py`：Stage 2 Entity Governance v2 薄 CLI。只解析参数、构造可选 provider、调用 `knowledgegraph.material_governance.entity_governance.runner.run_entity_governance_v2()`、输出治理报告并打印 summary；schema、候选生成、review、apply、annotation refresh 和报告逻辑均在 `src/knowledgegraph/material_governance/entity_governance/` 下维护。embedding 候选支持 `--embedding-workers` 并发调度，模型 review 支持 `--review-workers` 并发调度，review transport 默认通过 `--entity-review-provider codex` 使用 Codex CLI `exec`，OpenAI-compatible API 和 `none` 仅作为显式实验/规则路径；不物理删除原始 mention，不修改输入 DB，不覆盖原始 mention/provenance/relation assertion，不把 concept link 写成事实边。
- `stage2_relation_data_enhancement.py`：Stage 2.7 关系 read model 薄 CLI。只解析参数并调用 `knowledgegraph.material_governance.relation_governance.read_model.enhance_relation_data()`，写入 relation governance annotation、dangling endpoint issue、canonical relation edge 和 review queue；不调用模型、不修改原始 relation assertion、不把关系升级为事实图谱边。
- `stage2_review_canonical_relations.py`：Stage 2.8 canonical relation review 薄 CLI。只解析参数、构造 reviewer factory 并调用 `knowledgegraph.material_governance.relation_governance.review.review_canonical_relations()`；默认 `--review-provider codex` 通过 Codex CLI `exec` 审核 canonical edge，OpenAI-compatible `llm` 仅作为显式实验 provider；不修改 raw relation assertion，不接受事实边。
- `stage2_apply_relation_review_corrections.py`：Stage 2.9 关系 review 改正投影薄 CLI。只解析参数并调用 `knowledgegraph.material_governance.relation_governance.corrections.apply_relation_review_corrections()`，生成 `relation_review_corrections` 和 `reviewed_canonical_relation_edges`；只对 `full + path_safe` 的 `correct / wrong_type / reversed` 做保守保留、改类型或反向投影，不修改 raw relation assertion，不接受事实边。
- `stage3_route_candidate_generation.py`：Stage 3 路线候选生成脚本。读取 Stage 2.6 merged DB，投影 canonical slots 和 path-safe candidate edges，并可选调用 LLM 基于可见 chunk context 与安全 case task context 生成 `unverified_candidate`；不读取 hidden bridge source，不读取 gold slots/edges，不写 Neo4j。
- `stage3_route_slot_abstraction.py`：Stage 3.1 路线级上位候选概念生成脚本。读取 Stage 3 候选库，默认把已有 `llm_route_candidate` 槽位提升为 `route_concept_candidates` 并反向链接支撑它的字面 `canonical_projection` 槽位；可选调用 LLM 从字面槽位和未验证 route slot 线索生成上位概念。当前 LLM prompt 版本为 `stage3-route-slot-abstraction-v4`，输出仍为 `unverified_candidate`，不读取 gold、hidden source，不改实体和关系事实表。
- `evaluate_stage3_1_route_slot_abstraction.py`：Stage 3.1 上位候选概念评价脚本。只用于评价，把 `route_concept_candidates` 临时视为 candidate slot，与原 `candidate_slots` 合并后对 gold slot 和 endpoint readiness 计数；gold 只用于评价，不参与概念生成。
- `stage3_concept_edge_projection.py`：Stage 3.2 concept-level edge projection 与 route assembly 脚本。读取 Stage 3.1 DB，把字面 `candidate_edges` 通过 `route_concept_source_links` 投影为 `concept_candidate_edges`，并组装线性路径和共享 capability 的四层候选路线；不调用 LLM、不读取 gold/hidden、不修改事实表。
- `stage3_reviewed_edge_route_aggregation.py`：Stage 3 reviewed-edge 路线聚合薄 CLI。只解析参数并调用 `knowledgegraph.material_governance.route_governance.reviewed_edge_aggregation.generate_routes_from_reviewed_edges()`；核心逻辑读取 Stage 2.9 `reviewed_canonical_relation_edges`，默认排除非 `path_safe`、显式泛词和启发式泛词端点，生成兼容 Stage 3 的 literal slots、candidate edges、route concepts、concept edges 和多跳 `route_assemblies`；输出仍为 `unverified_candidate`，不修改 Stage 2.9 审核表，不把路线接受为事实。
- `stage3_route_model_governance.py`：Stage 3 路线模型治理薄 CLI。只解析参数、构造 reviewer factory 并调用 `knowledgegraph.material_governance.route_governance.model_review.govern_stage3_routes()`；默认通过 Codex CLI `exec` 审核 `route_assemblies` 的连续性、修正异常路线、复核未成路线的短边桥接候选，并生成 route node clusters 与 route subgraphs；新增输出仍为候选，不修改 Stage 2.9 审核表或原始 `route_assemblies`。
- `run_literature_relation_governance.py`：文献材料关系治理 pipeline 薄 CLI。读取 `configs/pipelines/literature_100_doc_diagnostic_v1.json`，委托 `knowledgegraph.material_governance.pipeline` 做 stage selection、skip/force、required/completion table 校验和 run manifest 输出；`--dry-run` 只打印选中阶段，不调用 Codex 或真实模型。
- `evaluate_stage3_2_concept_routes.py`：Stage 3.2 concept graph 评价脚本。只用于评价，比较 base、concept slots only 和 concept graph 三种候选面上的 slot/edge/chain/route 命中；默认读取人工 `gold_alignment_v0.jsonl` 并额外输出 calibrated 指标；gold 和 alignment 只用于评价，不参与生成。
- `evaluate_stage3_route_candidates.py`：Stage 3 候选 benchmark evaluator。只读 Stage 3 DB 与 gold routes，用严格字符串口径评价 slot hit、endpoint readiness、edge/chain/route hit，并输出 JSON summary 与 `docs/experiment-artifacts/stage3_route_candidate_generation_v1_validation.md`；默认读取人工 `gold_alignment_v0.jsonl` 并保留 strict + calibrated 双指标；gold 只用于评价，不用于候选生成。
- `review_stage3_candidate_edges.py`：Stage 3 候选边语义近似审核脚本。只读 Stage 3 DB 与 gold routes，区分 strict match、semantic match、relation near miss、endpoint near miss、wrong direction 和 missing candidate；gold 只用于评价诊断。
- `stage3_endpoint_matching.py`：Stage 3 evaluator/reviewer 共享端点匹配工具。端点匹配会合并 candidate edge 文本与 linked candidate slot 的 canonical name/aliases，并优先使用 linked slot layer；只用于评价和治理，不参与候选生成。
- `run_route_discovery_governance_gate.py`：路线发现端到端治理 gate。组合 benchmark 结构校验、gold evidence audit、Stage 3 严格评价、人工 gold alignment 校准和语义近似审核，输出瓶颈归因；不修改候选库，不把 gold 泄漏进生成流程。
- `extraction_experiment/`：第一轮抽取技术选型实验脚本与历史兼容入口，提供 MinerU API OCR 解析、PDF/Markdown 转 chunk、B/C 对照预计算结果生成、B/C 预计算结果接入、结构性评价器和路径对比报告；其中 `schema.py`、`models.py`、`adapters.py`、`llm_client.py` 和 `relation_quality.py` 只作为 `src/knowledgegraph/extraction` 的兼容导出壳。
- `extraction_experiment/prepare_journal_markdown_batch.py`：期刊 PDF→Markdown 批量编排脚本。复用 `prepare_chunks.py` 和 MinerU OCR 管线，自动发现 `data/raw/zsdd|ktfy|xxdkjs|dzdkjs|hkxb/<YYYY-II>/papers/`，输出到 `data/processed/<journal>/<issue>/`，并写入 `data/processed/journal_prepare_batch_manifest.jsonl`；支持 `--target-pdfs-per-journal` 按来源累计到指定 PDF→Markdown 数量，支持 `--issue-order newest|oldest` 控制期次顺序；默认迁移旧的 `zsdd_2026_02_full_ocr` MinerU 产物后在新目录重建 chunks/report；`--subprocess-timeout-seconds` 用于限制单期期次子进程总耗时，避免远端上传或轮询卡住整个批处理。

## Phase 1 全量抽取

`run_all_chunks.py` 用于执行当前架构 spec 中的 Phase 1：用真实 347 个 chunk 冲击 extractor 假设，并用最小 SQLite 单表保存结果。

默认输入：

- `data/processed/extraction_experiments/zsdd_2026_02_full_ocr/chunks.jsonl`

默认输出：

- `data/processed/extraction_experiments/zsdd_2026_02_phase1_all_chunks/phase1_extractions.sqlite`

SQLite 表：

```text
extractions(id, chunk_id, raw_llm, payload_json, schema_version, status, created_at)
```

示例：

```text
python scripts/run_all_chunks.py --mode offline --limit 2 --force
python scripts/run_all_chunks.py --mode llm --limit 1 --force
python scripts/run_all_chunks.py --mode llm --max-new 10
python scripts/run_all_chunks.py --mode llm --workers 3 --batch-size 6 --max-new 18
python scripts/run_all_chunks.py --mode llm --prompt-version v4 --chunks data/processed/extraction_experiments/zsdd_2026_02_v4_seven_relation_ab/chunks_sample.jsonl --db data/processed/extraction_experiments/zsdd_2026_02_v4_seven_relation_ab/v4_sample.sqlite --workers 4 --batch-size 8 --force
python scripts/run_all_chunks.py --mode llm --retry-failed
python scripts/run_all_chunks.py --summary-only
python scripts/run_all_chunks.py --mode llm
```

并发参数说明：

- `--workers N`：并发执行抽取调用。真实 LLM 模式下，每个任务独立创建 OpenAI-compatible client，避免共享响应状态。
- `--batch-size N`：限制每批提交的 chunk 数；适合先用小批量观察失败率、耗时和限流情况。设为 `0` 时一次提交所有待处理 chunk。
- `--prompt-version v3|v4`：真实 LLM 模式下选择 A 组 prompt。`v3` 保留历史 15 类关系；`v4` 使用当前 v4.5 七类局部关系 prompt，不覆盖历史 v3 产物。
- SQLite 删除、插入和提交仍在主线程串行执行，避免并发写入导致锁冲突或重复行。

Phase 1 SQL 检查示例：

```text
SELECT status, COUNT(*) FROM extractions GROUP BY status;
SELECT COUNT(*) FROM extractions WHERE json_array_length(json_extract(payload_json, '$.relations')) > 0;
SELECT json_extract(value, '$.name') AS entity, COUNT(*)
FROM extractions, json_each(json_extract(payload_json, '$.entities'))
GROUP BY entity
ORDER BY COUNT(*) DESC
LIMIT 20;
```

## Phase 3 结构化迁移

`migrate_phase3_sqlite.py` 用于执行当前架构 spec 中的 Phase 3：把 Phase 1 的最小单表结果迁移为可查询、可复盘、可人工抽检的结构化 SQLite。

默认输入：

- `data/processed/extraction_experiments/zsdd_2026_02_phase1_all_chunks/phase1_extractions.sqlite`
- `data/processed/extraction_experiments/zsdd_2026_02_full_ocr/chunks.jsonl`

默认输出：

- `data/processed/extraction_experiments/zsdd_2026_02_phase3_structured/phase3_extractions.sqlite`
- `data/processed/extraction_experiments/zsdd_2026_02_phase3_structured/attempts/`

示例：

```text
python scripts/migrate_phase3_sqlite.py --force
python scripts/migrate_phase3_sqlite.py --phase1-db path/to/phase1.sqlite --chunks path/to/chunks.jsonl --output-db path/to/phase3.sqlite --force
```

边界：

- 不创建 Neo4j 图谱。
- 不创建 canonical `Entity`、`FactEdge` 或 `HypothesisLink`。
- `RelationAssertion` 是 Phase 3 唯一正式关系治理对象。
- dangling `SourceClaim` endpoint 会保留原始 claim，并生成 `claim_missing_subject_mention` / `claim_missing_object_mention` 结构化 Issue。
- request/response 完整内容写入 `attempts/` 文件系统归档，SQLite 只保存路径和 SHA-256 hash。

## Phase 4 Entity Resolution v0.5

`resolve_entities_sqlite.py` 用于把 Phase 3 的 `EntityMention` 归并到 v0.5 canonical entity。该脚本默认复制 Phase 3 SQLite，不原地修改 Phase 3 输出。

默认输入：

- `data/processed/extraction_experiments/zsdd_2026_02_phase3_structured/phase3_extractions.sqlite`

默认输出：

- `data/processed/extraction_experiments/zsdd_2026_02_phase4_entity_resolution_v0/entity_resolution.sqlite`

示例：

```text
python scripts/resolve_entities_sqlite.py --force
python scripts/resolve_entities_sqlite.py --phase3-db path/to/phase3.sqlite --output-db path/to/entity_resolution.sqlite --force
```

边界：

- 不调用远程模型。
- 不引入 Neo4j。
- 不做 embedding 或 LLM 归一。
- `resolved_entities` 是 v0.5 归一结果，不是最终实体主数据。
- `coverage` 只是分配覆盖率，不能当作语义归一质量；必须同时查看 `true_merge_mention_rate`、`singleton_entity_rate` 和 `rule_counts`。

## Phase 4 研究查询验证

`analyze_research_findings_v0.py` 用于验证当前结构化数据是否能回答真实研究问题，而不是继续只做 schema/性能诊断。脚本读取 Phase 4 SQLite，在连接内创建临时 `canonical_relations` 表以降低 SQL 重复连接成本，并输出 `docs/experiment-artifacts/research_findings_v0.md`。

示例：

```text
python scripts/analyze_research_findings_v0.py
python scripts/analyze_research_findings_v0.py --db path/to/entity_resolution.sqlite --output docs/experiment-artifacts/research_findings_v0.md
```

边界：

- 不写入 SQLite。
- 不生成持久 read model。
- 不进入 HypothesisLink。
- 不引入 Neo4j。
- 高频统计必须同时报告 raw、chunk、document 三种计数；默认判断领域共识时优先看 document 去重口径。

## Seven Relation Hypothesis Prediction v0

`build_hypothesis_links_v0.py` 用于验证“先把 v3 的 15 类关系收敛为 7 类预测边，再做规则路径型 hypothesis 生成”是否有实际价值。

默认输入：

- `data/processed/extraction_experiments/zsdd_2026_02_full_ocr_llm_v3_all_chunks/group_a_schema_guided/extraction_results.jsonl`

默认输出：

- `data/processed/extraction_experiments/zsdd_2026_02_v3_seven_relation_prediction/projected_edges.jsonl`
- `data/processed/extraction_experiments/zsdd_2026_02_v3_seven_relation_prediction/hypotheses.jsonl`
- `data/processed/extraction_experiments/zsdd_2026_02_v3_seven_relation_prediction/summary.json`
- `docs/experiment-artifacts/seven_relation_hypothesis_prediction_v0.md`

示例：

```text
python scripts/build_hypothesis_links_v0.py
python scripts/build_hypothesis_links_v0.py --results path/to/extraction_results.jsonl --output-dir data/processed/extraction_experiments/custom_prediction --report docs/experiment-artifacts/custom_prediction.md
```

边界：

- 不调用远程模型。
- 不修改 v3 原始 JSONL。
- 不创建正式图谱边，只生成 `status=unverified` 的 hypothesis 候选。
- 本轮 `raw_relation_type` 仅作为实验审计字段，不能推导为未来主 schema 必须保留。

## Seven Relation Prompt v4 A/B

`evaluate_seven_relation_prompt_v4_ab.py` 用于比较旧 v3 prompt/schema 与 v4 七类关系 prompt 在同一批 chunk 上的结构效果。v4 输出仍使用统一 `ExtractionResult`，但 `adapter_name=group_a_schema_guided_v4`。当前代码中的 v4.5 prompt trace 版本为 `schema-guided-json-v4.5-seven-relations`；历史 v4/v4.1/v4.2/v4.3/v4.4 样本仍可能显示 `schema-guided-json-v4-seven-relations`、`schema-guided-json-v4.1-seven-relations`、`schema-guided-json-v4.2-seven-relations`、`schema-guided-json-v4.3-seven-relations` 或 `schema-guided-json-v4.4-seven-relations`。

本轮实验输入/输出：

```text
python scripts/evaluate_seven_relation_prompt_v4_ab.py --chunks data/processed/extraction_experiments/zsdd_2026_02_v4_seven_relation_ab/chunks_sample.jsonl --v3-results data/processed/extraction_experiments/zsdd_2026_02_full_ocr_llm_v3_all_chunks/group_a_schema_guided/extraction_results.jsonl --v4-results data/processed/extraction_experiments/zsdd_2026_02_v4_seven_relation_ab/group_a_schema_guided_v4/extraction_results.jsonl --v3-prediction-summary data/processed/extraction_experiments/zsdd_2026_02_v4_seven_relation_ab/v3_sample_prediction/summary.json --v4-prediction-summary data/processed/extraction_experiments/zsdd_2026_02_v4_seven_relation_ab/v4_sample_prediction/summary.json --output docs/experiment-artifacts/seven_relation_prompt_v4_ab_evaluation.md
```

边界：

- 不把 v4 结构 A/B 当作语义准确率验收。
- 不覆盖 `zsdd_2026_02_full_ocr_llm_v3_all_chunks/` 历史结果。
- v4 若要进入全量重抽，仍需人工抽样复核方向、关系类型和弱表达治理。

## Route Discovery Benchmark 校验

`validate_route_discovery_cases.py` 用于校验路线发现 benchmark 的 gold case 与来源清单是否仍满足当前数据约束。

默认输入：

- `data/benchmarks/route_discovery/gold_routes_v0.jsonl`
- `data/benchmarks/route_discovery/source_manifest_v0.jsonl`

相关 schema：

- `data/benchmarks/route_discovery/schemas/gold_route_case_schema_v0.json`
- `data/benchmarks/route_discovery/schemas/candidate_route_output_schema_v0.json`

示例：

```text
python scripts/validate_route_discovery_cases.py
```

边界：

- 不调用远程模型。
- 不下载或生成 source 文件。
- 不把 gold case 写入事实图谱。
- 不自动判断候选路线语义正确性；它只检查结构、一致性、来源路径、hidden/visible 分组和七类关系兼容性。

`audit_route_discovery_gold_evidence.py` 用于校验 16 个 gold slot 是否都有人工证据审核记录。该脚本不判断系统是否命中 gold，只检查 gold/audit 自身是否可追溯。

示例：

```text
python scripts/audit_route_discovery_gold_evidence.py
python scripts/audit_route_discovery_gold_evidence.py --check-verbatim-excerpts
```

默认输出：

- `data/benchmarks/route_discovery/gold_slot_evidence_audit_gate_summary.json`
- `docs/manual-review/route_discovery_gold_slot_evidence_audit_gate.md`

边界：

- 不调用远程模型。
- 不读取 Stage 2/3 候选库。
- 默认不逐字校验 `evidence_excerpt`，因为 audit 允许人工压缩归纳；需要严格核查时显式使用 `--check-verbatim-excerpts`。

`audit_route_discovery_gold_adequacy.py` 用于校验当前 gold/evaluator 是否足以解释 Stage 3/3.2 strict scoring。它会把 strict miss 但 semantic near match、候选路线形态与 gold route 不一致、acceptable_relations 可能过窄、以及非 chunk-local gold edge 被误当 direct extraction gate 的情况写入人工审核队列。

示例：

```text
python scripts/audit_route_discovery_gold_adequacy.py
python scripts/audit_route_discovery_gold_adequacy.py --db data/processed/extraction_experiments/route_discovery_visible_v4_4_stage2_validation/stage3_concept_routes.sqlite
```

默认输出：

- `data/benchmarks/route_discovery/gold_adequacy_gate_summary.json`
- `docs/manual-review/route_discovery_gold_adequacy_gate.md`

边界：

- 不调用远程模型。
- 不自动扩充或改写 `gold_routes_v0.jsonl`。
- 不证明候选路线为真；它只说明 strict score 可能低估了当前候选面，需要人工审核 gold alias、alternate endpoint、alternate route shape 或 evaluator 口径。

## Route Discovery Benchmark 抽取覆盖

`prepare_route_discovery_benchmark_chunks.py` 与 `evaluate_route_discovery_extraction_coverage.py` 用于做路线发现 benchmark 的抽取阶段诊断：先从可见背景文档生成 chunks，再分层检查当前 v4 prompt 的 input slot presence、extracted slot hit、slot stage hit、same-chunk endpoint co-occurrence、candidate endpoint readiness、edge stage counts 和 direct edge relation hit。

示例：

```text
python scripts/prepare_route_discovery_benchmark_chunks.py
python scripts/run_all_chunks.py --mode llm --prompt-version v4 --chunks data/processed/extraction_experiments/route_discovery_visible_v4_3_gold_guided/chunks_visible_gold_guided.jsonl --db data/processed/extraction_experiments/route_discovery_visible_v4_3_gold_guided/v4_3_visible_extractions.sqlite --workers 2 --batch-size 2 --retry-failed
python scripts/evaluate_route_discovery_extraction_coverage.py --chunks data/processed/extraction_experiments/route_discovery_visible_v4_3_gold_guided/chunks_visible_gold_guided.jsonl --db data/processed/extraction_experiments/route_discovery_visible_v4_3_gold_guided/v4_3_visible_extractions.sqlite --output-json data/processed/extraction_experiments/route_discovery_visible_v4_3_gold_guided/gold_coverage_summary.json --report docs/experiment-artifacts/route_discovery_v4_3_visible_extraction_coverage.md
python scripts/run_codex_extraction_chunks.py --retry-failed --workers 8
python scripts/evaluate_route_discovery_extraction_coverage.py --db data/processed/extraction_experiments/route_discovery_visible_v4_3_gold_guided/codex_gpt_5_5_visible_extractions.sqlite --output-json data/processed/extraction_experiments/route_discovery_visible_v4_3_gold_guided/codex_gpt_5_5_gold_coverage_summary.json --report docs/experiment-artifacts/route_discovery_codex_gpt_5_5_v4_3_staged_coverage.md
python scripts/run_codex_extraction_chunks.py --db data/processed/extraction_experiments/route_discovery_visible_v4_3_gold_guided/codex_gpt_5_5_v4_4_visible_extractions.sqlite --retry-failed --workers 8
python scripts/run_codex_extraction_chunks.py --chunk-id BR-AP-002-BR-AP-002-VIS-001-chunk-0001-6d676a76 --db data/processed/extraction_experiments/route_discovery_visible_v4_3_gold_guided/codex_gpt_5_5_v4_4_probe.sqlite --force
python scripts/evaluate_route_discovery_extraction_coverage.py --db data/processed/extraction_experiments/route_discovery_visible_v4_3_gold_guided/codex_gpt_5_5_v4_4_visible_extractions.sqlite --output-json data/processed/extraction_experiments/route_discovery_visible_v4_3_gold_guided/codex_gpt_5_5_v4_4_gold_coverage_summary.json --report docs/experiment-artifacts/route_discovery_codex_gpt_5_5_v4_4_visible_extraction_coverage.md
```

边界：

- `prepare_route_discovery_benchmark_chunks.py` 使用 gold alias 选择 chunk，因此只能作为抽取阶段 sanity check，不是公平检索评测。
- `evaluate_route_discovery_extraction_coverage.py` 同时报告输入可见性、抽取覆盖、slot/edge stage 分布、候选端点准备度和 root-cause diagnosis；direct edge hit 只表示 `evaluation_stage=chunk_local_extraction` 这类显式局部关系命中的严格上限，不要求抽取器直接输出跨文档隐边、chain 或完整 route。当前第一批 route discovery gold edge 已无 chunk-local direct gate，`direct edge hit=0` 不能单独判定抽取失败。
- `run_codex_extraction_chunks.py` 只把 Codex 当作本地 LLM transport，不写 Neo4j、不做实体归一、不生成 CandidateRoute；不得把 tmp Codex 配置或 token 写入仓库。批量抽取时先用 `--workers 8 --max-new 8 --batch-size 8` 做稳定性探针，再扩大到断点续跑全量。
- hidden bridge source 只用于 gold case 设计和评估，不得进入抽取输入。

## Stage 2 Entity Normalization

`stage2_entity_normalization.py` 是调用 `knowledgegraph.material_governance.entity_normalization.normalize_extraction_sqlite()` 的兼容 CLI，用于把 Stage 1 抽取 SQLite 中的实体提及归并为可审计 canonical entity。该脚本默认消费历史 v4.3 Codex 可见来源抽取库，也可通过 `--input-db` 指向 v4.4 抽取库；它输出新的 Stage 2 SQLite，不原地修改输入库。

默认输入：

- `data/processed/extraction_experiments/route_discovery_visible_v4_3_gold_guided/codex_gpt_5_5_visible_extractions.sqlite`

默认输出：

- `data/processed/extraction_experiments/stage2_entity_normalization_v1/stage2_entity_normalization.sqlite`

示例：

```text
python scripts/stage2_entity_normalization.py --force
python scripts/stage2_entity_normalization.py --input-db path/to/extractions.sqlite --output-db path/to/stage2.sqlite --force
```

边界：

- 不重新调用 LLM 抽取关系。
- 不生成 candidate route、HypothesisLink 或四层路线。
- 不引入 Neo4j。
- 内置 alias seed 审核只标记为 `model_reviewed_seed`，不得视为人工审核。
- `coverage` 只是分配覆盖率，必须同时查看 `true_merge_mention_rate`、`singleton_entity_rate`、`rule_counts` 和 `issue_counts`。

## Stage 2.5 Model Governance Legacy Experiment

`stage2_model_governance.py` 是旧 Stage 2.5 对照实验入口，不再作为文献材料治理主线默认阶段。它用于在 Stage 2 baseline 之上加入 embedding 候选召回、LLM 补充候选和大模型审核。它会复制输入库到输出库，再新增治理表；不会自动合并实体、不会新增关系、不会生成路线。大样本运行时可用 `--max-embedding-entities` 和 `--min-embedding-mentions` 先治理高影响 canonical entity，避免第一轮治理直接做全库 O(n²) 候选对比。

默认输入：

- `data/processed/extraction_experiments/stage2_entity_normalization_v1/stage2_entity_normalization.sqlite`

默认输出：

- `data/processed/extraction_experiments/stage2_entity_normalization_v1/stage2_entity_model_governance.sqlite`

只创建治理表、不调用模型：

```text
python scripts/stage2_model_governance.py --force
```

小批量真实调用：

```text
python scripts/stage2_model_governance.py --force --embedding-provider dashscope --llm-candidate-provider llm --alias-review-provider llm --relation-review-provider llm --max-alias-candidates 20 --max-relation-reviews 50 --max-llm-candidate-batches 2
```

高影响实体池真实调用：

```text
python scripts/stage2_model_governance.py --force --embedding-provider dashscope --llm-candidate-provider llm --alias-review-provider llm --relation-review-provider none --max-embedding-entities 800 --max-alias-candidates 300 --max-llm-candidate-batches 8 --review-batch-size 20 --llm-candidate-batch-size 50 --similarity-threshold 0.84 --top-k 5
```

全量真实调用：

```text
python scripts/stage2_model_governance.py --force --embedding-provider dashscope --llm-candidate-provider llm --alias-review-provider llm --relation-review-provider llm
```

需要的 `.env` 示例：

```text
pip install dashscope
```

```text
Set DASHSCOPE_API_KEY or STAGE2_EMBEDDING_API_KEY in your shell; do not commit the value.
$env:STAGE2_EMBEDDING_PROVIDER="dashscope"
$env:STAGE2_EMBEDDING_MODEL="text-embedding-v4"
$env:STAGE2_EMBEDDING_DIMENSION="1024"
$env:STAGE2_EMBEDDING_BATCH_SIZE="10"
$env:STAGE2_EMBEDDING_MIN_SIMILARITY="0.86"
$env:STAGE2_EMBEDDING_TOP_K="5"

$env:STAGE2_LLM_CANDIDATE_PROVIDER="llm"
$env:STAGE2_LLM_CANDIDATE_BATCH_SIZE="60"
$env:STAGE2_ALIAS_REVIEW_PROVIDER="llm"
$env:STAGE2_RELATION_REVIEW_PROVIDER="llm"
$env:STAGE2_REVIEW_LLM_API_KEY="..."
$env:STAGE2_REVIEW_LLM_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
$env:STAGE2_REVIEW_LLM_MODEL="..."
$env:STAGE2_REVIEW_LLM_TEMPERATURE="0"
$env:STAGE2_REVIEW_LLM_JSON_MODE="true"
$env:STAGE2_REVIEW_BATCH_SIZE="20"
$env:STAGE2_MODEL_CALL_MAX_RETRIES="5"
$env:STAGE2_MODEL_CALL_RETRY_SLEEP_SECONDS="10"
```

如果 `STAGE2_REVIEW_LLM_*` 未设置，脚本会回退到既有 `EXTRACTION_LLM_*` 配置。

## Stage 2.6 Governance Merge Apply

`stage2_apply_governance_merges.py` 用于把 Stage 2.5 中大模型审核为 `same_entity` 的 alias candidate 应用到新的 merged DB。它复制治理库后写入合并结果，不原地修改 Stage 2.5 输出。脚本还会写入 `entity_governance_annotations`，给每个 active canonical entity 标注路线参与资格和权重乘子。

默认输入：

- `data/processed/extraction_experiments/stage2_entity_normalization_v1/stage2_entity_model_governance.sqlite`

默认输出：

- `data/processed/extraction_experiments/stage2_entity_normalization_v1/stage2_entity_merged.sqlite`

示例：

```text
python scripts/stage2_apply_governance_merges.py --force
```

边界：

- 只应用 `same_entity`，不应用 `related_but_distinct`、`uncertain` 或其他审核结论。
- 旧 canonical entity 会标记为 `merged_into`，新 merged canonical 保留 member/source review 审计记录。
- `Metric`、上下文实体、claim 属性实体会标为 `excluded`；泛称类实体会标为 `limited` 并在 Stage 3 候选边中降权；型号粒度不稳的实体可标为 `review_required`。
- 不修改 relation assertion，不生成候选路线，不写 Neo4j。

## Stage 2.7 Relation Data Enhancement

`stage2_relation_data_enhancement.py` 是薄 CLI，核心逻辑在 `knowledgegraph.material_governance.relation_governance.read_model`。它用于把 Stage 2 Entity Governance v2 输出库中的 relation assertions 和 v2 entity governance annotations 增强为可查询、可排序、可审计的 canonical relation read model。它不调用模型，不覆盖原始关系，不把任何边升级为事实。

默认输入：

- `data/processed/extraction_experiments/literature_100_doc_diagnostic_v1/stage2_entity_governance_v2_research.sqlite`

默认输出：

- `data/processed/extraction_experiments/literature_100_doc_diagnostic_v1/stage2_relation_enhanced_v2_research.sqlite`

示例：

```text
python scripts/stage2_relation_data_enhancement.py --force
```

输出表：

- `relation_governance_annotations`：每条 relation assertion 的路径资格、关系权重、端点权重和治理 flags。
- `canonical_relation_edges`：按 canonical source/relation/target 聚合后的 read model，包含 `assertion_count`、去重文档数、平均 confidence、`edge_weight`、支撑 assertion ID、支撑 document ID 和支撑 chunk ID。
- `relation_review_queue`：从可审核 canonical edges 生成的待复核队列，按 `P0/P1/P2` 排序；跨文档支撑、高权重、`review_required` 边优先。
- `relation_data_quality_issues`：dangling endpoint 等关系级质量问题。

边界：

- `edge_weight` 是候选排序信号，不是事实置信度。
- `responsible_for` 默认保留为 `context_only`。
- `constrains` 默认降为 `limited`。
- dangling endpoint 不进入 `canonical_relation_edges`。
- `relation_review_queue` 不包含 `excluded/context_only` 边；队列项仍为待审核候选，不表示边已成立。
- Stage 2.7 不能识别方向抽反、unsupported 或 plausible_but_overbroad；这些仍依赖 Stage 2.8 canonical relation review 或人工审核。

## Stage 2.8 Canonical Relation Review

`stage2_review_canonical_relations.py` 是薄 CLI，核心逻辑在 `knowledgegraph.material_governance.relation_governance.review`。它用于对 Stage 2.7 的 `relation_review_queue` 做 canonical edge 级模型 review：按优先级取队列、小批量发送、并发调用 reviewer、主线程串行写 SQLite。默认 `--review-provider codex` 通过 Codex CLI `exec` 调用模型；`--review-provider llm` 仅作为显式 OpenAI-compatible 实验路径。它不修改 raw `relation_assertions`，不把 candidate edge 升级为事实边。

默认输入：

- `data/processed/extraction_experiments/literature_100_doc_diagnostic_v1/stage2_relation_enhanced_v2_research.sqlite`
- `data/processed/extraction_experiments/literature_100_doc_diagnostic_v1/chunks_research.jsonl`

示例：

```text
python scripts/stage2_review_canonical_relations.py --review-provider codex --priority-tier P0 --max-edges 8 --batch-size 4 --workers 2
python scripts/stage2_review_canonical_relations.py --review-provider codex --priority-tier P0 --max-edges 100 --batch-size 5 --workers 4
python scripts/stage2_review_canonical_relations.py --review-provider codex --priority-tier P0 --relation-type enables --max-edges 50 --batch-size 5 --workers 4
python scripts/stage2_review_canonical_relations.py --review-provider llm --priority-tier P0 --relation-type implements --relation-type applies_to --max-edges 50 --batch-size 5 --workers 4
```

输出表：

- `canonical_relation_edge_reviews`：每条 canonical edge 的 LLM review 结论，包括 `decision`、`suggested_relation_type`、`suggested_direction`、`path_safety`、`evidence_support` 和 `review_note`。
- `canonical_relation_review_runs`：每次并发探针的运行记录。

边界：

- Prompt version 为 `canonical-relation-edge-review-v1`。
- `--max-edges 0` 表示不设数量上限，会审核当前 `priority-tier` 下所有未审核队列项；全量运行通常按 `P0 -> P1 -> P2` 分段执行，便于观察远端错误和断点续跑。
- `--relation-type` 可重复传入，用于避免队列前端被单一关系类型支配；分层抽样结果应按关系类型分别汇总后再判断是否扩大运行。
- `edge_weight` 只作为队列排序信号，不是事实置信度。
- `decision=correct` 仍不表示事实入库，只表示当前证据下该 candidate edge 通过模型审核。
- `context_only/unsafe/needs_review` 应在后续候选图谱构建或路线预测中降权或过滤。

## Stage 2.9 Relation Review Correction Projection

`stage2_apply_relation_review_corrections.py` 是薄 CLI，核心逻辑和 correction policy 在 `knowledgegraph.material_governance.relation_governance.corrections`。它用于把 Stage 2.8 的 review 结果应用到一个新的治理投影层。它不会覆盖 `canonical_relation_edges` 或 raw `relation_assertions`，只新增“改正后可供后续候选图使用”的投影表。

默认输入：

- `data/processed/extraction_experiments/literature_100_doc_diagnostic_v1/stage2_relation_enhanced_v2_research.sqlite`

示例：

```text
python scripts/stage2_apply_relation_review_corrections.py --force
```

输出表：

- `relation_review_corrections`：每条 reviewed canonical edge 的治理结果，包括 `accepted / corrected / context_only / review_required / rejected`，以及是否改类型、反向、丢弃或待人工复核。
- `reviewed_canonical_relation_edges`：只包含保守可投影的 `accepted / corrected` 边；这些边仍是 `status='unverified_candidate'`，不是事实图谱边。
- `relation_review_correction_runs`：每次应用改正策略的运行记录。

自动改正规则：

- `correct + keep + path_safe + full`：保留原边。
- `wrong_type + keep + path_safe + full + suggested_relation_type 可用`：改为建议关系类型，权重乘以 `0.85`。
- `reversed/wrong_type + reverse + path_safe + full`：交换 source/target，权重乘以 `0.85`。
- `context_only`：保留 correction 记录，但不进入 `reviewed_canonical_relation_edges`。
- `unsafe / unsupported / plausible_but_overbroad / drop`：标为 rejected，不进入投影边。
- `partial / weak / none / uncertain / needs_review`：标为 review_required，不自动入图。

边界：

- 这一步是“治理投影”，不是重新抽取，也不是事实接受。
- `suggested_relation_type` 只在 `full + path_safe` 且不是原类型时自动应用；否则进入 review_required。
- `implements` 的 uses/equipped_with/includes/produces 类错配不会被硬改成事实边，除非 review 给出可用的七类关系且证据为 full。

## Stage 3 Route Candidate Generation

`stage3_route_candidate_generation.py` 用于从 Stage 2.6 merged DB 生成 `unverified_candidate` 级别的 route slots 和 candidate edges。默认会把 active canonical entity 投影为 candidate slot，把大模型审核为 `decision='correct'` 且 `path_safety='path_safe'` 的关系投影为 candidate edge；可选 LLM 只做候选扩展。投影 candidate edge 时会读取 `entity_governance_annotations`：任一端点 `excluded` 则不投影，`limited/review_required` 则保留但降低 `edge_weight` 并写入 `governance_flags_json`。

默认输入：

- `data/processed/extraction_experiments/stage2_entity_normalization_v1/stage2_entity_merged.sqlite`
- `data/processed/extraction_experiments/route_discovery_visible_v4_3_gold_guided/chunks_visible_gold_guided.jsonl`
- `data/benchmarks/route_discovery/gold_routes_v0.jsonl` 中的安全 case task context（只读取 `case_id/title/mode/visible_sources`，不读取 gold slots、gold edges 或 hidden sources）

默认输出：

- `data/processed/extraction_experiments/stage2_entity_normalization_v1/stage3_route_candidates.sqlite`

示例：

```text
python scripts/stage3_route_candidate_generation.py --force --llm-provider none

$env:STAGE3_MODEL_CALL_MAX_RETRIES="1"
$env:STAGE2_REVIEW_LLM_TIMEOUT_SECONDS="180"
$env:STAGE2_REVIEW_LLM_REASONING_EFFORT="low"
python scripts/stage3_route_candidate_generation.py --append --llm-provider llm --llm-case-id BR-AP-001 --chunk-context-chars 600 --case-payload-limit 20
python scripts/stage3_route_candidate_generation.py --append --llm-provider llm --llm-case-id BR-AP-002 --chunk-context-chars 600 --case-payload-limit 20
python scripts/stage3_route_candidate_generation.py --append --llm-provider llm --llm-case-id BR-AP-003 --chunk-context-chars 600 --case-payload-limit 20
```

验证：

```text
python scripts/evaluate_stage3_route_candidates.py
python scripts/review_stage3_candidate_edges.py
python scripts/run_route_discovery_governance_gate.py
```

边界：

- Stage 3 输出仍为 `unverified_candidate`，不是事实图谱、不是最终路线发现。
- `candidate_edges.edge_weight = confidence * source_weight_multiplier * target_weight_multiplier`，只是候选排序信号，不是事实置信度。
- LLM 生成器不得读取 hidden bridge sources、gold slots 或 gold edges。
- `--append` 用于按 case 续跑，避免单个 LLM 调用超时导致已完成 case 白费。
- 当前严格 benchmark 口径是字符串子串匹配，但端点文本会合并 linked candidate slot 的 canonical name/aliases；语义接近候选需要单独的人工/模型审核门禁，不能和 strict hit 混报。
- `run_route_discovery_governance_gate.py` 会把 gold 证据审核、gold 充分性审核、严格评价、人工 gold alignment 校准和语义近似审核合并成一个归因报告；当输入为 Stage 3.2 DB 时会同时读取 `route_concept_candidates` 和 `concept_candidate_edges`。当前 v4.4 Stage 3.2 产物 strict edge hit 为 `1/14`，calibrated edge hit 为 `3/14`，calibrated route variant hit 为 `1/1`，但 full route hit 仍为 `0/4`；主要瓶颈仍是 candidate expansion / endpoint alignment，不能把 strict miss 直接解释为 prompt 或模型失败。

## Stage 3.1 Route Slot Abstraction

`stage3_route_slot_abstraction.py` 用于把 Stage 3 的候选槽位提升为路线级上位候选概念。默认 `existing-slots` 路径不调用外部模型：它把已有 `llm_route_candidate` 槽位作为上位概念种子，并通过名称/alias 相似度链接同 case、同 layer 的 `canonical_projection` 字面槽位。当前 LLM prompt 版本为 `stage3-route-slot-abstraction-v4`，会使用 `edge_neighborhood` 判断 route role，保留 application target / operational problem environment，要求 slash-compressed 与英文/缩写表达生成 plain-language aliases，并把 source candidate slot aliases 继承到 route concept。

默认输入：

- `data/processed/extraction_experiments/route_discovery_visible_v4_4_stage2_validation/stage3_route_candidates_llm_governed.sqlite`

默认输出：

- `data/processed/extraction_experiments/route_discovery_visible_v4_4_stage2_validation/stage3_route_slot_abstractions.sqlite`
- `docs/experiment-artifacts/stage3_route_slot_abstraction_v1.md`

示例：

```text
python scripts/stage3_route_slot_abstraction.py --force
python scripts/stage3_route_slot_abstraction.py --force --concept-generator llm --case-id BR-AP-002
python scripts/evaluate_stage3_1_route_slot_abstraction.py
python scripts/evaluate_stage3_1_route_slot_abstraction.py --db data/processed/extraction_experiments/route_discovery_visible_v4_4_stage2_validation/stage3_route_slot_abstractions_llm.sqlite --output-json data/processed/extraction_experiments/route_discovery_visible_v4_4_stage2_validation/stage3_1_route_slot_abstraction_llm_eval_summary.json --report docs/experiment-artifacts/stage3_1_route_slot_abstraction_llm_eval.md
python scripts/stage3_route_slot_abstraction.py --force --concept-generator llm --output-db data/processed/extraction_experiments/route_discovery_visible_v4_4_stage2_validation/stage3_route_slot_abstractions_llm_v4.sqlite --report docs/experiment-artifacts/stage3_route_slot_abstraction_v4_llm.md
python scripts/evaluate_stage3_1_route_slot_abstraction.py --db data/processed/extraction_experiments/route_discovery_visible_v4_4_stage2_validation/stage3_route_slot_abstractions_llm_v4.sqlite --output-json data/processed/extraction_experiments/route_discovery_visible_v4_4_stage2_validation/stage3_1_route_slot_abstraction_llm_v4_eval_summary.json --report docs/experiment-artifacts/stage3_1_route_slot_abstraction_llm_v4_eval.md
```

边界：

- 输出表为 `route_concept_candidates`、`route_concept_source_links` 和 `stage3_slot_abstraction_runs`。
- 每个 route concept 必须链接至少一个 source candidate slot，不能成为孤立概念；LLM 路径可引用 `literal_candidate_slots` 或 `existing_route_slots`，但后者只能作为未验证 alias/抽象线索。
- 不读取 benchmark gold slots、gold edges 或 hidden bridge sources。
- 不修改 `candidate_slots`、`candidate_edges`、`resolved_entities` 或 `relation_assertions`。
- route concept 仍为 `status='unverified_candidate'`，只服务于后续 endpoint matching、route assembly 和人工审核排序。
- `evaluate_stage3_1_route_slot_abstraction.py` 的 concept-augmented 指标只证明端点召回变化；它不会证明关系边成立，也不会把 route concept 接入 `candidate_edges`。

## Stage 3.2 Concept Edge Projection And Route Assembly

`stage3_concept_edge_projection.py` 用于把 Stage 3.1 的 route concepts 接入候选边和候选路线。它不重新抽取、不调用 LLM、不读取 gold，也不把 concept edge 写成事实。投影规则是：如果字面 `candidate_edge` 的 source/target slot 分别支撑了两个 route concepts，则生成一条 `concept_candidate_edges` 候选边；若 concept edges 能形成路线片段，则写入 `route_assemblies`。

默认输入：

- `data/processed/extraction_experiments/route_discovery_visible_v4_4_stage2_validation/stage3_route_slot_abstractions_llm_v4.sqlite`

默认输出：

- `data/processed/extraction_experiments/route_discovery_visible_v4_4_stage2_validation/stage3_concept_routes.sqlite`
- `docs/experiment-artifacts/stage3_2_concept_edge_projection.md`
- `docs/experiment-artifacts/stage3_2_concept_route_evaluation.md`

示例：

```text
python scripts/stage3_concept_edge_projection.py --force
python scripts/evaluate_stage3_2_concept_routes.py
```

边界：

- 输出表为 `concept_candidate_edges`、`route_assemblies` 和 `stage3_concept_projection_runs`。
- `route_assemblies` 支持线性 `principle->technology->capability`、`technology->capability->scenario`，以及共享 capability 的 `principle+technology->capability->scenario`。
- 所有输出固定为 `status='unverified_candidate'`。
- 当前严格 gold 评价中，Stage 3.2 把 edge hit 从 `0/14` 提升到 `1/14`，但 route hit 仍为 `0`；真实价值主要体现在生成了可人工审核的四层候选路线。

## Stage 3 Route Model Governance

`stage3_route_model_governance.py` 是薄 CLI，核心逻辑在 `knowledgegraph.material_governance.route_governance.model_review`，gap/subgraph/report public API 分别在 `route_governance.gap_review`、`route_governance.subgraphs` 和 `route_governance.report`。它用于对 reviewed-edge 生成的路线候选做模型复核和路线图增补。默认 `--review-provider codex`，通过 Codex CLI `exec` 调用模型；`--review-provider llm` 仅保留为兼容旧实验的显式选项，不作为默认路线。脚本会写入 `route_assembly_reviews`、`reviewed_route_assemblies`、`route_gap_candidates`、`route_gap_reviews`、`supplemental_route_assemblies`、`route_node_clusters`、`route_subgraphs` 和运行记录。

默认输入/输出：

- `data/processed/extraction_experiments/literature_100_doc_diagnostic_v1/stage3_reviewed_edge_routes_full13_concurrent_research.sqlite`
- `docs/experiment-artifacts/literature_100_doc_stage3_route_model_governance_codex_full.md`

示例：

```text
python scripts/stage3_route_model_governance.py --review-provider codex --force --max-routes 0 --max-gap-candidates 500 --max-cluster-candidates 200 --batch-size 4 --workers 4
python scripts/stage3_route_model_governance.py --review-provider codex --retry-failed-routes --route-review-only --max-routes 0 --batch-size 4 --workers 4
```

边界：

- 不修改 Stage 2.9 `reviewed_canonical_relation_edges`、原始 relation assertion 或原始 `route_assemblies`。
- `reviewed_route_assemblies` 和 `supplemental_route_assemblies` 是模型治理后的候选投影，不表示事实图谱事实。
- 短边补路线必须经过模型审核；泛词桥接、错误拼接和证据不足路线会留在 review 表中，不进入候选投影。
- `route_node_clusters` 只是路线级聚合/可视化节点，不是实体归一合并。

## Literature Relation Governance Pipeline

`run_literature_relation_governance.py` 是材料治理链路的 pipeline 编排入口。它不承载业务规则，核心配置和执行逻辑位于 `knowledgegraph.material_governance.pipeline`；默认配置为 `configs/pipelines/literature_100_doc_diagnostic_v1.json`。`--from-stage` / `--to-stage` 可选择阶段范围，`--force-stage` 可强制重跑单个阶段，`--dry-run` 只输出计划阶段顺序。非 dry-run 会默认写入 `output_root/pipeline_run_manifest.json`。

示例：

```text
python scripts/run_literature_relation_governance.py --dry-run --from-stage relation_read_model --to-stage projection_audit
python scripts/run_literature_relation_governance.py --config configs/pipelines/literature_100_doc_diagnostic_v1.json --from-stage relation_read_model --to-stage projection_audit
```

边界：

- pipeline config 使用统一的 `inputs`、`outputs`、`report`、`runner_params`、`required_tables` 和 `completion_tables` schema；不接受脚本私有的 `db` / `output_db` 顶层别名。
- `required_tables` 按输入路径检查，`completion_tables` 按输出路径检查；in-place DB stage 必须声明 completion tables。
- Codex review 阶段仍需要显式执行非 dry-run 才会调用模型；dry-run 不调用任何模型或外部服务。

## Phase 4 关系方向 spot check

`review_relation_direction_v0.py` 用于验证真实研究查询中暴露的关系方向风险。脚本从 Phase 4 SQLite 抽取 `confidence >= 0.9` 的 `enables / supports / applies_to` 关系，按关系类型定额、按文档轮转采样，并用脚本内 `MANUAL_LABELS` 输出人工校验报告。

示例：

```text
python scripts/review_relation_direction_v0.py
python scripts/review_relation_direction_v0.py --db path/to/entity_resolution.sqlite --output docs/manual-review/relation_direction_spotcheck_v0.md
```

边界：

- 不写入 SQLite。
- 不调用 LLM。
- 不修改实体归一结果。
- 不直接作为抽取准确率总评，只用于判断高价值多跳推断前是否需要 prompt/schema 修正或人工审核。

## Relation Quality A/B

`sample_relation_quality_ab.py` 用于从 Phase 4 SQLite 中抽取 `200` 条分层样本，作为 prompt/schema v1-v2 A/B 和人工审核清单。

示例：

```text
python scripts/sample_relation_quality_ab.py
python scripts/sample_relation_quality_ab.py --sample-size 200 --min-per-relation 20
```

`evaluate_relation_quality_ab.py` 用于比较 v1/v2 `ExtractionResult` JSONL 的结构指标、关系类型分布、`inference_eligible` 分布和 `trigger_text` 覆盖率。

示例：

```text
python scripts/evaluate_relation_quality_ab.py --chunks data/processed/extraction_experiments/zsdd_2026_02_full_ocr/chunks_one_per_doc.jsonl --v1-results data/processed/extraction_experiments/zsdd_2026_02_full_ocr_one_per_doc_llm_v2/group_a_schema_guided/extraction_results.jsonl --output docs/experiment-artifacts/prompt_v2_ab_evaluation.md
```

`evaluate_relation_quality_labels.py` 用于把 200 条样本的人工审核标签转成 gate 结果。默认会先生成可填写模板 `manual_labels_template.jsonl`，再读取 `manual_labels.jsonl` 计算三项门槛。

示例：

```text
python scripts/evaluate_relation_quality_labels.py
python scripts/evaluate_relation_quality_labels.py --labels data/processed/relation_quality_ab/manual_labels.jsonl --output docs/manual-review/relation_quality_label_gate.md
```

边界：

- 这些脚本都不调用远程 LLM。
- 这些脚本都不写 SQLite。
- A/B 报告不计算方向抽反率、严格错误率或路径不安全率；这些指标必须来自人工标注。
- 人工标签 gate 未通过前，不应进入 HypothesisLink；未满 `200` 条有效标签时脚本返回非零状态是预期行为。

## Relation Quality v3 全量样本

v3 全量抽取复用 `run_all_chunks.py` 的并发和断点续跑能力，先写 Phase 1 风格 SQLite，再导出标准 `ExtractionResult` JSONL：

```text
python scripts/run_all_chunks.py --mode llm --chunks data/processed/extraction_experiments/zsdd_2026_02_full_ocr/chunks.jsonl --db data/processed/extraction_experiments/zsdd_2026_02_full_ocr_llm_v3_all_chunks/v3_all_chunks.sqlite --workers 8 --batch-size 16 --retry-failed
python scripts/export_phase1_sqlite_results.py --db data/processed/extraction_experiments/zsdd_2026_02_full_ocr_llm_v3_all_chunks/v3_all_chunks.sqlite --output data/processed/extraction_experiments/zsdd_2026_02_full_ocr_llm_v3_all_chunks/group_a_schema_guided/extraction_results.jsonl
```

从 v3 JSONL 生成 200 条人工审核样本：

```text
python scripts/sample_relation_quality_jsonl.py --sample-size 200 --min-per-relation 8
python scripts/evaluate_relation_quality_labels.py --sample data/processed/relation_quality_ab_v3/sample_manifest.jsonl --template data/processed/relation_quality_ab_v3/manual_labels_template.jsonl --labels data/processed/relation_quality_ab_v3/manual_labels.jsonl --output docs/manual-review/relation_quality_v3_label_gate.md
```

边界：

- v3 样本来自标准 JSONL，不依赖 Phase 4 SQLite 或实体归一结果。
- `trigger_text` 和 `inference_eligible` 只是审核辅助字段，人工标签仍以原文 evidence 与 claim 为准。
- v3 人工标签 gate 未通过前，不应进入 HypothesisLink。

## extraction_experiment 使用方式

### PDF 转 chunks

输入：

- `--source-root data/raw/zsdd/2026-02/papers`：PDF 来源目录。
- `--dataset-name zsdd_2026_02`：实验数据集名称。
- `--limit 1`：默认只调用 MinerU 处理 1 篇 PDF。
- `--skip-mineru`：跳过 MinerU 调用，直接把已有 markdown 转为 chunks。
- `--token-env-var MINERU_TOKEN`：MinerU token 环境变量名。
- `--enable-ocr / --no-enable-ocr`：默认开启 OCR。项目后续 MinerU 调用必须保持 OCR 开启；只有受控对比实验可以显式使用 `--no-enable-ocr`，并应使用单独 `--dataset-name`。
- `--artifact-root`：可选，指定保存 MinerU 结果 zip、JSON、图片等结构化产物的目录；默认写入当前 dataset 的 `mineru_artifacts/`。
- `--disable-env-proxy / --no-disable-env-proxy`：默认清理代理环境变量后调用 MinerU，避免本机无效代理影响请求。

说明：

- `prepare_chunks.py` 调用当前目录内的 `mineru_api_batch.py` 完成 MinerU 远程解析；`deliver/` 目录只作为清洗、切块、质检和后处理工具来源，不再提供远程 API 上传入口。
- 如果当前 shell 未加载 `MINERU_TOKEN`，脚本会读取仓库根目录 `.env` 中的 PowerShell 风格 MinerU token 配置，但不会输出 token 内容。

输出：

- `data/processed/extraction_experiments/<dataset-name>/mineru_raw/`：MinerU raw markdown。
- `data/processed/extraction_experiments/<dataset-name>/mineru_artifacts/`：每篇文档的 MinerU 原始结果归档，包括 `result.zip`、Markdown、JSON、图片和 `artifact_manifest.json`。
- `data/processed/extraction_experiments/<dataset-name>/chunks.jsonl`：标准化 `DocumentChunk`。
- `data/processed/extraction_experiments/<dataset-name>/prepare_chunks_report.json`：准备阶段报告。

示例：

```text
python scripts/extraction_experiment/prepare_chunks.py --limit 1
python scripts/extraction_experiment/prepare_chunks.py --skip-mineru --raw-markdown-root data/processed/extraction_experiments/zsdd_2026_02/mineru_raw
python scripts/extraction_experiment/prepare_journal_markdown_batch.py --journal zsdd --journal ktfy --journal xxdkjs --journal dzdkjs --journal hkxb --limit 0
python scripts/extraction_experiment/prepare_journal_markdown_batch.py --journal dzdkjs --journal hkxb --target-pdfs-per-journal 100 --issue-order newest --no-migrate-legacy-zsdd
```

### 抽取实验

输入：

- `--demo`：使用内置 demo chunk，验证本地流程。
- `--chunks path/to/chunks.jsonl`：读取标准化 `DocumentChunk` JSONL。
- `--group-a-mode offline|llm`：A 组使用离线启发式模式或真实 LLM 模式，默认 `offline`。
- `--group-a-prompt-version v3|v4`：真实 LLM 模式下选择 A 组 prompt。`v3` 为历史 15 类关系 prompt，`v4` 为当前七类局部关系 prompt。
- `--group-a-results path/to/a.jsonl`：接入 A 组预计算 `ExtractionResult`，用于复用已完成的真实 LLM 输出，避免重复调用模型。
- `--group-b-results path/to/b.jsonl`：接入 LlamaIndex 方案预计算 `ExtractionResult`。
- `--group-c-results path/to/c.jsonl`：接入 Neo4j KG Builder 方案预计算 `ExtractionResult`。

当前实验 schema 为 `extraction-experiment-v2`。v3 prompt trace 版本为 `schema-guided-json-v3`，使用历史 15 类关系；当前 v4.5 prompt trace 版本为 `schema-guided-json-v4.5-seven-relations`，要求模型只根据 chunk 原文抽取 `enables / drives / implements / has_capability / applies_to / constrains / responsible_for` 七类局部关系，并补强 `Principle / Technology / Capability / Scenario` 等实体类型边界。v4.5 不要求模型生成或补齐完整技术链路，显式要求“未来、提出、可能、预期、有望”等弱表达把 relation 降为 `assertion_strength=speculative` 且 `claim.modality` 不得为 `asserted`，要求 `evidence_spans[].quote` 逐字复制 chunk 原文连续片段，并用泛化类别提示 Principle 端点，包括统计相关或依赖关系、控制与反馈机制、模型假设、扰动/畸变/约束机理、特征空间变换、传输/传播/流动机理、均衡或优化机制。v4.5 还要求对新质、杀手锏、新概念、颠覆性、先导性、前瞻性、探索性、技术突袭、技术颠覆、新原理验证、多学科融合创新等创新信号保留实体、claim 和 evidence，并可用 `innovation_signal:<触发词>:<evidence_id>` warning 进入后续加权与审核排序。v4.5 不在 prompt 中写入 benchmark case 的特定实体名或 gold label。两者都会要求每条关系绑定 `SourceClaim`、evidence span、`inference_eligible`、`trigger_text` 和 `extraction_rule_version`；适配器会计算原文 span，并对 OCR 空白差异做受控回填。

A 组真实 LLM 模式使用 OpenAI-compatible Chat Completions 接口。当前默认模型标识为 `gpt-5.5`，默认 `reasoning_effort=high`，默认 endpoint 为 `https://api.openai.com/v1`。本地 URL、模型和 token 从仓库根目录 `.env` 或当前 shell 环境变量读取；如需使用其他兼容服务，通过环境变量覆盖。

```text
EXTRACTION_LLM_API_KEY      # 推荐使用；也可用 DEEPSEEK_API_KEY、DASHSCOPE_API_KEY 或 OPENAI_API_KEY
EXTRACTION_LLM_BASE_URL     # 默认 https://api.openai.com/v1
EXTRACTION_LLM_MODEL        # 默认 gpt-5.5
EXTRACTION_LLM_REASONING_EFFORT  # 默认 high
EXTRACTION_LLM_THINKING_ENABLED  # 默认 false；DeepSeek v4-pro 默认 true
EXTRACTION_LLM_JSON_MODE         # 默认 true；如接口不支持 response_format，可设为 false
EXTRACTION_LLM_TIMEOUT_SECONDS
EXTRACTION_LLM_TEMPERATURE
```

根目录 `.env` 使用 PowerShell 风格变量，例如：

```text
$env:EXTRACTION_LLM_API_KEY="你的 token"
$env:EXTRACTION_LLM_BASE_URL="你的 OpenAI-compatible base URL"
$env:EXTRACTION_LLM_MODEL="gpt-5.5"
$env:EXTRACTION_LLM_REASONING_EFFORT="high"
```

输出：

- 默认输出到 `data/processed/extraction_experiments/demo/`。
- 每组输出 `extraction_results.jsonl`。
- 总结输出 `evaluation_summary.json` 和 `evaluation_summary.md`。

示例：

```text
python scripts/extraction_experiment/run_experiment.py --chunks data/processed/extraction_experiments/zsdd_2026_02/chunks.jsonl --group-a-mode llm --output-dir data/processed/extraction_experiments/zsdd_2026_02_llm
python scripts/extraction_experiment/run_experiment.py --chunks data/processed/extraction_experiments/zsdd_2026_02_v4_seven_relation_ab/chunks_sample.jsonl --group-a-mode llm --group-a-prompt-version v4 --output-dir data/processed/extraction_experiments/zsdd_2026_02_v4_seven_relation_ab_run_experiment
python scripts/extraction_experiment/run_experiment.py --demo --output-dir data/processed/extraction_experiments/demo
python scripts/extraction_experiment/run_experiment.py --demo --group-a-mode llm --output-dir data/processed/extraction_experiments/demo-llm
```

### B/C 对照结果与路径比较

`generate_baseline_results.py` 用于生成 B/C 的框架输出形态代理结果。它不调用真实 LlamaIndex 或 Neo4j，只生成可进入 `PrecomputedResultAdapter` 的 `ExtractionResult` JSONL，用于比较“路径抽取/图构建输出”在项目治理契约下会保留或丢失哪些信息。

示例：

```text
python scripts/extraction_experiment/generate_baseline_results.py --demo --output-dir data/processed/extraction_experiments/abc_path_comparison_demo/precomputed
python scripts/extraction_experiment/generate_baseline_results.py --chunks data/processed/extraction_experiments/group_a_schema_guided_llm_validation_zsdd_sample/chunks_sample.jsonl --output-dir data/processed/extraction_experiments/abc_path_comparison_zsdd_sample/precomputed
```

`compare_results.py` 根据 `evaluation_summary.json` 生成路径对比报告。结构分只用于比较当前样例下的 schema、证据、claim 和 trace 覆盖，不代表抽取准确率。

```text
python scripts/extraction_experiment/compare_results.py --summary data/processed/extraction_experiments/abc_path_comparison_zsdd_sample/evaluation_summary.json --output data/processed/extraction_experiments/abc_path_comparison_zsdd_sample/comparison_report.md
```

### 稳定性报告

`analyze_stability.py` 用于按输入 chunk 汇总抽取结果稳定性，重点查看每篇或每个 chunk 的结构 warning、证据绑定、claim 覆盖、弱表达覆盖、耗时和模型自报 warning。它只评价结构稳定性，不代表语义准确率最终结论。

示例：

```text
python scripts/extraction_experiment/analyze_stability.py --chunks data/processed/extraction_experiments/zsdd_2026_02_full_ocr/chunks_one_per_doc.jsonl --results data/processed/extraction_experiments/zsdd_2026_02_full_ocr_one_per_doc_llm_v2/group_a_schema_guided/extraction_results.jsonl --output data/processed/extraction_experiments/zsdd_2026_02_full_ocr_one_per_doc_llm_v2/stability_report.md
```

### 真实 Neo4j KG Builder 测试

`run_neo4j_kg_builder.py` 调用 `neo4j-graphrag` experimental `SimpleKGPipeline`。默认通过自定义 `KGWriter` 捕获 pipeline 生成的图，不写入 Neo4j 数据库；这样可以在本机 Neo4j 服务未启动时验证真实 KG Builder 抽取质量。脚本需要在包含 `neo4j-graphrag`、`neo4j`、`openai` 的 Python 环境中运行，例如当前 `AgentDev` conda 环境。

当前脚本使用项目自定义 prompt，要求 Neo4j KG Builder 在关系属性中输出 `claim_text`、`claim_type`、`modality`、`evidence_quote`、`assertion_strength`。适配器会把这些关系属性转换为项目统一 `SourceClaim` 与 evidence span；如果 `evidence_quote` 无法匹配原文，则回退到 full chunk evidence 并写入 warning。

示例：

```text
conda run -n AgentDev python scripts/extraction_experiment/run_neo4j_kg_builder.py --chunks data/processed/extraction_experiments/group_a_schema_guided_llm_validation_zsdd_sample/chunks_sample.jsonl --limit 1 --output-dir data/processed/extraction_experiments/neo4j_kg_builder_real_zsdd_sample
conda run -n AgentDev python scripts/extraction_experiment/run_neo4j_kg_builder.py --chunks data/processed/extraction_experiments/group_a_schema_guided_llm_validation_zsdd_sample/chunks_sample.jsonl --limit 1 --output-dir data/processed/extraction_experiments/neo4j_kg_builder_enhanced_schema_zsdd_sample
```

输出：

- `group_c_neo4j_kg_builder/extraction_results.jsonl`：适配为项目统一契约后的结果。
- `group_c_neo4j_kg_builder/raw_graphs.jsonl`：Neo4j KG Builder 原始节点和边。
- `evaluation_summary.json` / `evaluation_summary.md`：结构性评价摘要。

边界：

- offline 模式不调用远程 LLM、LlamaIndex 或 Neo4j 服务。
- llm 模式只调用 A 组 OpenAI-compatible LLM，不写事实图谱。
- B/C 对照结果生成脚本是框架输出形态代理，不代表真实 LlamaIndex 或 Neo4j KG Builder 的质量结论。
- 真实 Neo4j KG Builder 测试默认不写数据库；如后续要测试真实 Neo4j 写入，需要先启动数据库并单独增加写入参数。
- A 组离线适配器只用于验证统一契约和评价流程，不代表正式抽取质量。
- 抽取结果是候选和来源声明，不是事实图谱事实。

## 维护约定

- 新增脚本时必须说明输入、输出、边界和使用方式。
- 新增可复用抽取、归一、候选图构建核心逻辑时，优先放入 `src/knowledgegraph/`；`scripts/` 中只新增调用入口。
- 脚本不得写入 API Key、账号、密码或本地私有配置。
- 脚本输出的数据文件应放到明确的数据目录，避免混入源码目录。
- 调用 MinerU 处理项目语料时默认开启 OCR，不要复用未记录 OCR 配置的历史产物作为正式抽取输入。
- 修改脚本行为后，同步更新本 README。
