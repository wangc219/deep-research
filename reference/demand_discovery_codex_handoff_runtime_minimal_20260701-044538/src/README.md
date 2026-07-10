# src 目录说明

`src/` 存放后续可复用的项目核心逻辑。这里的代码面向长期维护和产品化流程；`scripts/` 只保留 CLI、批处理编排和一次性实验入口。

## 当前结构

```text
src/
  knowledgegraph/
    runtime/
      codex_exec.py              # Codex CLI exec transport、最终消息读取、JSON object 提取和进程超时处理
      provider_config.py         # PowerShell 风格 .env / 环境变量读取，不打印密钥
      retry.py                   # 通用 retry helper
      sqlite_utils.py            # SQLite 表、计数、分组和 JSON 小工具
      run_manifest.py            # pipeline run manifest dataclass 与 JSON 输出
    extraction/
      schema.py                  # 抽取契约、实体/关系/claim 枚举和治理常量
      models.py                  # DocumentChunk / ExtractionResult 等统一数据模型
      adapters.py                # 离线/LLM 七类关系抽取适配器与 payload 治理
      document_filtering.py      # 文献级无关信息过滤，例如信息动态、征稿启事、专题征文
      llm_client.py              # OpenAI-compatible LLM client
      relation_quality.py        # 关系 path-safety 与结构化 warning 标注
      relation_quality_rules_v2.json
    governance/
      entity_path_policy.py      # canonical entity 路线参与资格、粒度标签和候选边权重乘子规则
      relation_path_policy.py    # relation type 路线资格、关系权重和跨文档支撑权重规则
    material_governance/         # 材料治理主链路：抽取、实体治理、关系治理、路线治理和投影审计
      extraction/                # Phase 1 SQLite helper 与 Codex chunk runner
      document_filter.py         # 文献诊断样本研究/非研究过滤和 extraction DB 过滤复制
      entity_normalization.py    # Stage 2 entity normalization 实现，脚本只保留兼容 CLI
      entity_governance/         # Stage 2 Entity Governance v2 主实现
        rules.py                 # 材料实体清噪、alias normalization 和规则判定
        schema.py                # v2 candidate/review/concept/apply run/snapshot 表定义
        candidates.py            # rule、embedding、LLM candidate generation
        embeddings.py            # DashScope embedding provider，服务实体治理候选召回
        review.py                # OpenAI-compatible/Codex review provider 与 review 写入
        apply.py                 # same_entity 合并、concept link 写入和 merge audit
        annotations.py           # v1 snapshot 与 v2 path eligibility refresh
        report.py                # summary、quality gates 和 markdown 报告
        runner.py                # Stage 2 实体治理编排入口
      relation_governance/       # Stage 2.7-2.9 关系 read model、review 和保守投影
        read_model.py            # relation annotation、canonical relation edge 和 review queue 生成
        review.py                # canonical relation review，Codex CLI 为默认 transport
        corrections.py           # relation review correction policy 和 reviewed edge projection
      route_governance/          # Stage 3 reviewed-edge 路线聚合、模型复核、gap 增补和子图
        reviewed_edge_aggregation.py  # 从 reviewed relation edges 生成 literal/concept slots、concept edges 和 route assemblies
        model_review.py          # Codex/OpenAI-compatible route reviewer、route review 写入和治理编排
        gap_review.py            # 短边桥接候选、gap review 和 supplemental route projection public API
        subgraphs.py             # route node clusters 和 route subgraphs public API
        report.py                # route model governance summary/report public API
      projection_audit/          # 最终候选投影图形状、泛词泄漏和治理边界审计
        graph_shape.py           # reviewed binary projection 的节点、边、degree 和 component 审计
        leakage.py               # binary/route 泛词泄漏、Source subtype 混合和 broader/narrower 误合并门禁
        report.py                # projection audit Markdown 报告渲染
      pipeline.py                # 材料治理 pipeline config、stage selection、skip/force 和 manifest 编排
    demand_discovery/            # Python 版 Pi harness 复刻与需求挖掘 demo 运行时
      manual_source_pack.py      # 受控 manual source pack 实践 runner 与输出落盘
      autonomous_research.py     # Phase 5 topic-only 自治调研 runner，编排 source strategy、research loop、模型 judge、audit/report gate
      codex_workflow.py          # 独立 Codex 角色工作流，复用 domain/source/report 对象但不调用 Phase 5 主链路
      harness/                   # 通用 agent runtime（loop/事件/工具/save point/session/trace/scheduler/event bus/scheduled runner/inbox/retention/worker stop policy）
        audit_context.py         # 为 auditor worker 构建紧凑证据审查上下文
        judge_agent.py           # 模型 judge agent runner，要求通过 record_judgement 写入 JudgementReport
        report_context_curator.py # 模型 context_curator runner，通过受控工具策展 ReportContextCandidatePool
        reporter.py               # 受限 reporter agent runner，通过 generate_demand_report 写最终 DemandReport
        report_publisher.py       # 发布已入库报告到 report.md 与 report_manifest.json，不生成正文结论
      llm/                       # provider adapter 与 fake provider，不写领域状态
      domain/                    # 需求挖掘数据结构、research state/source strategy/judgement/judgement plan/candidate synthesis、领域 store、领域工具、审核量表、查重、人工审核与报告生成
        evidence_support.py      # EvidenceCard 支撑等级规范和 audit scorecard 语义校验
      tools/                     # 白名单网络抓取、页面/文章发现、受控浏览器 observe/execute、文档下载、artifact、正文简化、检索、精读与关键词门禁工具
      workers/                   # markdown agent 定义、角色 prompt、任务 prompt 与 agent role 配置
        codex_roles/             # 独立 Codex workflow 专用补全 prompt，不参与主链路 agent discovery
```

## 边界

- `src/knowledgegraph/extraction` 是正式文献抽取核心包。
- `src/knowledgegraph/runtime` 只存放跨链路基础设施，例如 Codex exec、provider config、retry、SQLite helper 和 run manifest；不承载材料治理业务规则。
- `src/knowledgegraph/material_governance` 是材料输入到候选治理投影图的主线领域包；本链路的抽取运行、实体治理、关系治理、路线治理和投影审计应优先收敛在这里。
- `src/knowledgegraph/material_governance/document_filter.py` 承载文献样本过滤 runner；输出仍是研究样本输入裁剪和 extraction DB 子集复制，不做实体或关系治理。
- `src/knowledgegraph/material_governance/entity_normalization.py` 承载 Stage 2 entity normalization 的可复用实现；`scripts/stage2_entity_normalization.py` 只保留兼容 CLI 和默认路径。
- `src/knowledgegraph/governance` 只保留跨领域可复用的图谱路径/权重策略；材料实体治理规则属于 `material_governance/entity_governance`，材料关系治理的 read model、review 和 correction policy 属于 `material_governance/relation_governance`，材料路线治理的 reviewed-edge aggregation、model review、gap review 和 subgraph projection 属于 `material_governance/route_governance`。脚本不应从旧材料治理路径导入业务逻辑。
- `src/knowledgegraph/material_governance/projection_audit` 只做候选投影审计和报告，不把候选边、路线或子图升级为事实图谱事实。
- `src/knowledgegraph/material_governance/pipeline.py` 只做配置加载、阶段选择、表级前置/完成校验、skip/force 和 run manifest 编排；具体业务逻辑仍属于各治理子包。
- `src/knowledgegraph/demand_discovery` 是 Python 版 Pi harness 复刻与需求挖掘 demo 运行时；`harness/` 为不依赖军事需求领域概念的通用 agent runtime，`domain/` 承载需求挖掘领域对象与工具。
- `src/knowledgegraph/demand_discovery/codex_workflow.py` 是独立 Codex 角色工作流：planner、reader、judge、synthesizer、auditor、reporter 均由 Codex CLI 角色调用产出 JSON，本地程序只负责白名单校验、reader 后本地证据材料化、judge-worker 多轮路由、DomainStore 导入、trace、报告质量重写门禁和报告产物落盘；该模块不得调用或修改 `autonomous_research.py`、`harness/research_loop.py`、`harness/scheduler.py`、`harness/agent_harness.py` 主链路。Codex workflow 复用 `workers/agents/reader.md`、`judge.md`、`auditor.md`、`reporter.md`，缺失的 planner/synthesizer 补全 prompt 放在 `workers/codex_roles/`，不参与主链路 agent discovery。
- `src/knowledgegraph/demand_discovery/harness/scheduler.py` 将 worker 作为进程内子 harness 调度；worker session 隔离，但共享 `DomainStore` / `DomainTraceStore`。
- `src/knowledgegraph/demand_discovery/harness/scheduled_runner.py` 负责 Phase 4 文件化定时任务轮询和 done 报告；`intervention.py` 负责 run-local inbox 干预通道；`retention.py` 负责输出留痕分层清理。
- `src/knowledgegraph/demand_discovery/harness/research_loop.py` 负责 Phase 5 round-level 自治调研闭环控制，只编排轮次、ReadingQueue、network worker 取证导入、模型 judge agent、停止条件和 candidate synthesis，不重写 AgentLoop / DiscoveryScheduler 内核。
- `src/knowledgegraph/demand_discovery/harness/judge_agent.py` 是 judge 的唯一运行入口：模型读取 worker reports 和 compact domain state，必须通过 `record_judgement` 写入可消费的 `JudgementReport`；系统不再保留程序化 worker-report synthesis 兜底。
- `src/knowledgegraph/demand_discovery/domain/judgement_plan.py` 与 `harness/judge_plan_routing.py` 负责诊断五 judge 下一轮计划契约：`controller_tasks` 给 controller 消费，`worker_briefs` 给 worker 阅读；helper 做受控枚举、refs、修复、brief 编译和路由转译，无 `worker_report_ids` 的 task 不下发为 worker assignment，不调用模型、不替模型做证据充分性判断。
- `src/knowledgegraph/demand_discovery/harness/model_prompt.py` 负责把 ContextPack 组装成 `ModelPrompt(base_instructions, input, tools, output_schema, parallel_tool_calls)`；`harness/worker_stop_policy.py` 负责单 worker apparent-stop 停止门禁和 follow-up 注入，不调用模型、不执行工具、不生成报告。
- `src/knowledgegraph/demand_discovery/harness/audit_context.py` 为 auditor worker 构建 AuditContextBundle；上下文包含 candidate、judgement、EvidenceCard、source tier、开放来源质量和 worker self-check 摘要，不携带 raw HTML 全文。
- `src/knowledgegraph/demand_discovery/domain/evidence_support.py` 定义 direct/partial/adjacent/weak/irrelevant/unassessed 支撑等级、scorecard 校验和核心结论支撑判定；report gate 和 `run_audit` 共用该策略。
- `src/knowledgegraph/demand_discovery/harness/report_context.py`、`harness/report_context_curator.py`、`harness/reporter.py` 与 `harness/report_publisher.py` 构成诊断六报告链路：ContextIndexer 程序化索引，`context_curator` 模型策展，ContextVerifier 校验引用和 audit 权限，`reporter` 模型调用 `generate_demand_report` 入库，publisher 只发布人读 markdown 和机器 manifest。
- 真实 autonomous report path 不再使用 `_render_autonomous_report_body()` 生成正文；该函数只允许 fake fixture 路径使用，并在 summary 中标记 `report_mode=fixture`。
- `src/knowledgegraph/demand_discovery/domain/web_research_session.py`、`domain/worker_research.py` 记录 worker-local working memory、WorkerSelfCheck 和 FollowUpInstruction；这些对象只保存 compact refs/summary，不替代 EvidenceCard、ResearchLead、OpenSourceLead、SourceQualityAssessment 等权威对象。
- `src/knowledgegraph/demand_discovery/domain/dedup.py` 只提供候选和 worker brief 的程序化相似度提示，不定义需求新颖性；`domain/review.py` 负责人工审核后的本地推送清单。
- `src/knowledgegraph/demand_discovery/tools/` 承载真实信源访问工具；外部网页/PDF/检索结果都必须按非可信材料处理，全文落 artifact，模型上下文只暴露摘录和引用。浏览器工具面收敛为 `browser_observe` 与 `browser_execute`：target action 必须引用 observe 返回的 `target_id`；JavaScript 必须引用 `observation_ref`，由工具强制凭证/敏感存储、敏感表单字段、写请求、跨域请求和 URL scope 底线，并通过 script/result artifact 与 trace 审计。浏览器 HTML artifact 落盘前必须脱敏敏感表单字段；JS 后页面 HTML 不得替换可捕获正文 artifact。
- `src/knowledgegraph/demand_discovery/workers/agents/*.md` 是 Phase 2 角色 prompt 的事实源；修改后需要同步跑 prompt 与 fake e2e 测试。
- 需求挖掘 runtime 的当前边界、Pi 概念映射、fake/real demo 执行方式和未迁移范围记录在 `docs/architecture/pi_harness_python_replication_runtime_design.md`。
- `scripts/extraction_experiment/*.py` 中同名模块仅作为历史兼容壳，不再承载新核心逻辑。
- 新增可复用抽取、归一、候选图构建逻辑时，优先放入 `src/knowledgegraph/<domain>/`；新增脚本时只调用 `src` 中的核心能力。
- 不在 `src/` 写入 API Key、本地私有路径或实验输出数据。

## 维护规则

- 修改 `src` 中公共契约、prompt、schema、治理规则后，必须同步更新相关架构文档和定向测试。
- 如果新增顶层包或长期模块，更新本 README。
- `src` 内代码应能通过普通包导入，例如 `knowledgegraph.extraction.models`，不要依赖 `scripts/` 被加入 `sys.path`。
