# 项目文档索引

根目录 [AGENTS.md](../AGENTS.md) 是给后续 agent 使用的长期操作规范，包含工作入口、目录定位、操作要求、输出规范和安全边界。

## 架构设计

- [总体架构设计 Spec](architecture/overall_architecture_design_spec.md)
- [分层系统架构设计 Spec](architecture/layered_system_architecture_spec.md)
- [Extraction Field Dictionary](architecture/extraction_field_dictionary.md)
- [Literature Extraction SOP](architecture/literature_extraction_sop.md)
- [Phase 3 数据结构设计约束与 ADR](architecture/phase3_data_structure_design_constraints.md)
- [Stage 2 Entity Normalization v1 Spec](architecture/stage2_entity_normalization_v1_spec.md)
- [Stage 2.5 Model Governance v1 Spec](architecture/stage2_model_governance_v1_spec.md)
- [Stage 2 Entity Governance v2 Design](architecture/stage2_entity_governance_v2_design.md)
- [Stage 2 Entity Governance v2 Implementation Plan](architecture/stage2_entity_governance_v2_implementation_plan.md)
- [材料治理链路重组设计](architecture/literature_relation_governance_pipeline_restructure.md)
- [材料治理链路重组实施计划](architecture/material_governance_pipeline_restructure_implementation_plan.md)
- [Stage 3.1 Route Slot Abstraction And Novelty Signal Design](architecture/stage3_route_slot_abstraction_and_novelty_signal_design.md)
- [需求挖掘模块共识与待讨论问题](architecture/demand_discovery_module_discussion.md)
- [Pi AgentHarness 复刻文件级复用分析](architecture/pi_agent_harness_file_reuse_analysis.md)
- [Pi Harness Python Replication Implementation Plan](architecture/pi_harness_python_replication_implementation_plan.md)
- [Pi Harness Python Replication Runtime Design](architecture/pi_harness_python_replication_runtime_design.md)
- [Codex Agent-Harness 交互观测实验设计](architecture/codex_agent_harness_interaction_observation_experiment.md)
- [需求挖掘模块长时运行演进计划](architecture/demand_discovery_long_run_evolution_plan.md)
- [Demand Discovery Phase 1: Runtime Hardening Implementation Plan](architecture/demand_discovery_phase1_runtime_hardening_plan.md)
- [Demand Discovery Phase 2: Multi-Agent Runtime Implementation Plan](architecture/demand_discovery_phase2_multi_agent_runtime_plan.md)
- [Demand Discovery Phase 3: Network Tools Implementation Plan](architecture/demand_discovery_phase3_network_tools_plan.md)
- [Demand Discovery Phase 4: Autonomy Loop Implementation Plan](architecture/demand_discovery_phase4_autonomy_loop_plan.md)
- [Demand Discovery Phase 5: Autonomous Research Loop Implementation Plan](architecture/demand_discovery_phase5_autonomous_research_loop_plan.md)
- [Demand Discovery Phase 5: Autonomous Research Usage Guide](architecture/demand_discovery_phase5_autonomous_research_usage.md)
- [Demand Discovery Phase 5 信源画像与 QueryPlanner 设计](architecture/demand_discovery_phase5_source_profile_query_planner_design.md)
- [Demand Discovery Phase 5 报告质量诊断与补强设计](architecture/demand_discovery_phase5_report_quality_diagnostics_design.md)
- [Demand Discovery Phase 5 诊断优化实施方案](architecture/demand_discovery_phase5_diagnostics_implementation_plan.md)
- [需求挖掘主链路与 Codex 链路交接说明](architecture/demand_discovery_main_and_codex_handoff.md)
- [Phase 4 Entity Resolution v0.5 Spec](architecture/phase4_entity_resolution_v0_spec.md)
- [Relation Schema v2 ADR](architecture/relation_schema_v2_adr.md)
- [前端可视化产品形态需求整理](architecture/frontend_visualization_product_requirements.md)

## 实验过程产物

`experiment-artifacts/` 存放阶段实验、查询验证和结构性 A/B 报告。这些文档记录实验过程和阶段判断，不表示最终事实图谱事实。

- [Phase 3 查询验证](experiment-artifacts/phase3_query_validation.md)
- [Demand Discovery Real Provider Smoke Record](experiment-artifacts/demand_discovery_real_provider_smoke.md)
- [Demand Discovery Phase 2 Fake E2E Record](experiment-artifacts/demand_discovery_phase2_fake_e2e.md)
- [Demand Discovery Phase 5 Autonomous Research Smoke Record](experiment-artifacts/demand_discovery_phase5_autonomous_research_smoke.md)
- [Codex Agent-Harness Route A Request Capture Feasibility Probe](experiment-artifacts/codex_agent_harness_route_a_feasibility_probe.md)
- [Codex Agent-Harness Route A Real Task Trace Analysis](experiment-artifacts/codex_agent_harness_route_a_real_task_trace_analysis.md)
- [Codex Agent-Harness Context Admission And Compaction Probe](experiment-artifacts/codex_agent_harness_context_admission_compaction_probe.md)
- [Codex Agent-Harness Web Search Context Probe](experiment-artifacts/codex_agent_harness_web_search_context_probe.md)
- [Entity Resolution v0.5 验证报告](experiment-artifacts/entity_resolution_v0_validation.md)
- [Phase 4 Canonical Query Validation](experiment-artifacts/phase4_query_validation.md)
- [Research Findings v0](experiment-artifacts/research_findings_v0.md)
- [Prompt v2 A/B Evaluation](experiment-artifacts/prompt_v2_ab_evaluation.md)
- [Seven Relation Hypothesis Prediction v0](experiment-artifacts/seven_relation_hypothesis_prediction_v0.md)
- [Seven Relation Prompt v4 A/B Evaluation](experiment-artifacts/seven_relation_prompt_v4_ab_evaluation.md)
- [Seven Relation Prompt v4.1 Re-extraction Validation](experiment-artifacts/seven_relation_prompt_v4_1_reextraction_validation.md)
- [Seven Relation Prompt v4.1 A/B Evaluation](experiment-artifacts/seven_relation_prompt_v4_1_ab_evaluation.md)
- [Seven Relation Prompt v4.1 Sample Prediction](experiment-artifacts/seven_relation_prompt_v4_1_sample_prediction.md)
- [Seven Relation Prompt v4 A/B v3 Sample Prediction](experiment-artifacts/seven_relation_prompt_v4_ab_v3_sample_prediction.md)
- [Seven Relation Prompt v4 A/B v4 Sample Prediction](experiment-artifacts/seven_relation_prompt_v4_ab_v4_sample_prediction.md)
- [Weak Modality Impact on v4 Prediction](experiment-artifacts/weak_modality_prediction_impact_analysis.md)
- [Route Discovery v4.2 Visible Extraction Coverage](experiment-artifacts/route_discovery_v4_2_visible_extraction_coverage.md)
- [Route Discovery Codex gpt-5.5 Visible Extraction Coverage](experiment-artifacts/route_discovery_codex_gpt_5_5_visible_extraction_coverage.md)
- [Route Discovery Codex gpt-5.5 v4.3 Staged Coverage](experiment-artifacts/route_discovery_codex_gpt_5_5_v4_3_staged_coverage.md)
- [Route Discovery Codex gpt-5.5 v4.4 Probe Coverage](experiment-artifacts/route_discovery_codex_gpt_5_5_v4_4_probe_coverage.md)
- [Route Discovery Codex gpt-5.5 v4.4 Visible Extraction Coverage](experiment-artifacts/route_discovery_codex_gpt_5_5_v4_4_visible_extraction_coverage.md)
- [Route Discovery v4.4 Extraction And Governance Validation](experiment-artifacts/route_discovery_v4_4_extraction_governance_validation.md)
- [Route Discovery Governance Gate v1](experiment-artifacts/route_discovery_governance_gate_v1.md)
- [Route Discovery Governance Gate Stage 3.2](experiment-artifacts/route_discovery_governance_gate_stage3_2.md)
- [Route Discovery Prompt v4.2 Benchmark Validation](experiment-artifacts/route_discovery_prompt_v4_2_benchmark_validation.md)
- [Stage 2 Entity Normalization v1 Validation](experiment-artifacts/stage2_entity_normalization_v1_validation.md)
- [Stage 2.5 Model Governance v1 Real Run](experiment-artifacts/stage2_model_governance_v1_real_run.md)
- [Stage 3 Route Candidate Generation v1 Validation](experiment-artifacts/stage3_route_candidate_generation_v1_validation.md)
- [Stage 3 Route Candidate Generation v4.4 Validation](experiment-artifacts/stage3_route_candidate_generation_v4_4_validation.md)
- [Stage 3.1 Route Slot Abstraction v1](experiment-artifacts/stage3_route_slot_abstraction_v1.md)
- [Stage 3.1 Route Slot Abstraction v1 LLM](experiment-artifacts/stage3_route_slot_abstraction_v1_llm.md)
- [Stage 3.1 Route Slot Abstraction Evaluation](experiment-artifacts/stage3_1_route_slot_abstraction_eval.md)
- [Stage 3.1 Route Slot Abstraction LLM Evaluation](experiment-artifacts/stage3_1_route_slot_abstraction_llm_eval.md)
- [Stage 3.1 Route Slot Abstraction v3 LLM](experiment-artifacts/stage3_route_slot_abstraction_v3_llm.md)
- [Stage 3.1 Route Slot Abstraction v3 LLM Evaluation](experiment-artifacts/stage3_1_route_slot_abstraction_llm_v3_eval.md)
- [Stage 3.1 Route Slot Abstraction v4 LLM](experiment-artifacts/stage3_route_slot_abstraction_v4_llm.md)
- [Stage 3.1 Route Slot Abstraction v4 LLM Evaluation](experiment-artifacts/stage3_1_route_slot_abstraction_llm_v4_eval.md)
- [Stage 3.1 Route Slot Abstraction v3/v4 Comparison](experiment-artifacts/stage3_1_route_slot_abstraction_v3_v4_comparison.md)
- [Stage 3.2 Concept Edge Projection](experiment-artifacts/stage3_2_concept_edge_projection.md)
- [Stage 3.2 Concept Route Evaluation](experiment-artifacts/stage3_2_concept_route_evaluation.md)
- [Stage 3 Candidate Edge Semantic Review v4.4](experiment-artifacts/stage3_candidate_edge_semantic_review_v4_4.md)
- [93 篇研究样本 Stage 2 实体归一化验证](experiment-artifacts/literature_100_doc_stage2_entity_normalization_validation.md)
- [93 篇研究样本 Stage 2.5 模型治理验证](experiment-artifacts/literature_100_doc_stage2_5_model_governance_validation.md)
- [93 篇研究样本 Stage 2 Entity Governance v2 验证](experiment-artifacts/literature_100_doc_stage2_entity_governance_v2.md)
- [93 篇研究样本 Stage 2.7 关系数据增强验证](experiment-artifacts/literature_100_doc_stage2_7_relation_data_enhancement.md)
- [93 篇研究样本 Stage 2.8 Canonical Relation LLM Review Probe](experiment-artifacts/literature_100_doc_stage2_8_canonical_relation_review_probe.md)
- [93 篇研究样本 Stage 3 Reviewed Edge Route Aggregation](experiment-artifacts/literature_100_doc_stage3_reviewed_edge_route_aggregation.md)
- [93 篇研究样本 Stage 3 Route Model Governance Codex Full](experiment-artifacts/literature_100_doc_stage3_route_model_governance_codex_full.md)
- [93 篇研究样本 Material Governance Projection Audit](experiment-artifacts/literature_100_doc_projection_audit.md)

## 人工审核与门禁

`manual-review/` 存放人工审核清单、spot check 和质量 gate 报告。未完成人工标签门禁前，这些报告不能作为进入 HypothesisLink 或事实图谱入库的通过证明。

- [Relation Direction Spot Check v0](manual-review/relation_direction_spotcheck_v0.md)
- [Relation Quality A/B Sample Plan](manual-review/relation_quality_ab_sample_plan.md)
- [Relation Quality Manual Label Gate](manual-review/relation_quality_label_gate.md)
- [Relation Quality v3 Sample Plan](manual-review/relation_quality_v3_sample_plan.md)
- [Relation Quality v3 Label Gate](manual-review/relation_quality_v3_label_gate.md)
- [Hypothesis Prediction v0 Top 50 Review](manual-review/hypothesis_prediction_v0_top50_review.md)
- [Route Discovery Gold Slot Evidence Audit v0](manual-review/route_discovery_gold_slot_evidence_audit_v0.md)
- [Route Discovery Gold Slot Evidence Audit Gate](manual-review/route_discovery_gold_slot_evidence_audit_gate.md)
- [Route Discovery Gold Adequacy Gate](manual-review/route_discovery_gold_adequacy_gate.md)
- [Route Discovery Gold Alignment v0](manual-review/route_discovery_gold_alignment_v0.md)
- [100 篇诊断抽取关系质量 10 篇 Spot Check](manual-review/literature_100_doc_relation_quality_10_doc_spotcheck.md)

## Benchmark 设计

`benchmarks/` 存放项目级评测设计文档。这里定义 benchmark case、gold route、候选路线输出和评测指标，不存放已验证事实。

- [Route Discovery Benchmark Design](benchmarks/route_discovery_benchmark_design.md)
- [Route Discovery Benchmark Cases v0](benchmarks/route_discovery_cases_v0.md)

## 调研材料

- [调研方向 Spec](research/research_direction_spec.md)
- [Deep Research Report](research/deep-research-report.md)

## 原始需求参考

- [甲方设计案](source-materials/甲方设计案.md)
- [需求记录](source-materials/需求.md)
- [甲方预设知识图谱](source-materials/甲方预设知识图谱.png)
- [系统输出示例 1](source-materials/系统输出示例1.jpg)
- [系统输出示例 2](source-materials/系统输出示例2.jpg)
- [乙方初版方案设计](source-materials/乙方初版方案设计.md)

## 技术选型

- [抽取与图增强构建技术选型第一轮 Spec](technology-selection/spec/extraction_technology_selection_spec.md)
- [第一轮抽取技术方案实验与评价 Spec](technology-selection/spec/extraction_experiment_evaluation_spec.md)
- [第一轮抽取技术方案实验实施 Plan](technology-selection/plan/extraction_experiment_implementation_plan.md)
- [A/B/C 抽取路径第一轮对比结论](technology-selection/extraction_path_comparison_report.md)
- [Neo4j KG Builder 真实测试报告](technology-selection/neo4j_kg_builder_real_test_report.md)
- [增强 Schema 后 A/C 抽取路线对照报告](technology-selection/enhanced_schema_extractor_vs_neo4j_report.md)
- [自研 Extractor 作为主线抽取治理器的证据结论](technology-selection/self_extractor_advantage_evidence.md)
- [现有文档抽取稳定性测试报告](technology-selection/extraction_stability_one_per_doc_report.md)
- [Neo4j KG Builder 与自研 Extractor 十篇代表样本对照报告](technology-selection/neo4j_vs_self_extractor_one_per_doc_comparison.md)
- [Phase 2 抽取数据复盘 Findings](technology-selection/phase2_extraction_data_findings.md)

## 资料采集

- [战术导弹技术站点采集脚本方案](collection/zsdd_collection_script_plan.md)
- [空天防御站点采集脚本方案](collection/ktfy_collection_script_plan.md)
- [信息对抗技术站点采集脚本方案](collection/xxdkjs_collection_script_plan.md)
- [电子信息对抗技术站点采集脚本方案](collection/dzdkjs_collection_script_plan.md)
- [航空学报站点采集脚本方案](collection/hkxb_collection_script_plan.md)

`collection/` 用于存放资料采集流程、脚本方案和数据源接入说明。新增采集源时，应说明访问入口、关键接口、请求头、输出目录、采集边界和验证方法。采集脚本本体放在 `scripts/`，原始数据放在 `data/raw/`。

## Superpowers 实施计划

- [Codex Demand Workflow Implementation Plan](superpowers/plans/2026-07-01-codex-demand-workflow.md)

## 说明

本目录整理项目推进过程中形成的工作文档和原始需求参考。`source-materials` 中的内容作为需求分析与架构设计依据，不应被直接视为成熟方案或最终 ground truth。

本目录说明只在 `docs/README.md` 维护，不在 `docs/` 深层子目录新增 README。
