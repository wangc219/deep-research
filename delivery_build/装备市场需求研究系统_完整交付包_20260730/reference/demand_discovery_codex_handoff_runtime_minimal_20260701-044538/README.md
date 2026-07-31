# 需求挖掘主链路与 Codex 链路交接说明

## 一句话结论

当前仓库内有两条需求挖掘链路：

- **主链路**：`--mode fake/real`，是自研 agent harness / research loop 的完整工程化实现，包含多 worker 调度、工具调用、DomainStore、judge、audit、report、人工审核和留痕清理等能力。但真实联网工具链的站点发现、正文清洗、跨站检索和动态页面处理仍偏弱，暂不建议作为主要真实调研入口。
- **Codex 链路**：`--mode codex`，是当前建议使用的真实需求研判入口。它保留既有角色工作流和领域对象，但把 planner / reader / judge / synthesizer / auditor / reporter 的具体执行交给 Codex CLI，并复用 Codex 自带 web search。本地程序负责白名单校验、reader 后证据材料化、judge-worker 多轮路由、DomainStore 导入、trace、报告质量门禁和产物发布。

协作者如果只想复现实验，应优先运行 `--mode codex`。主链路适合继续做 harness 能力开发、工具增强和受控 fake/单元测试验证。

## 推荐阅读顺序

1. 本文档：先理解两条链路的边界、用法和当前状态。
2. `scripts/demand_discovery_autonomous_research.py`：统一 CLI 入口。
3. `src/knowledgegraph/demand_discovery/codex_workflow.py`：当前真实可用链路。
4. `src/knowledgegraph/demand_discovery/autonomous_research.py`：主链路入口和 Phase 5 controller 编排。
5. `configs/demand_discovery/source_whitelist.yaml`：白名单信源边界。
6. `outputs/runs/codex-materialized-real-smoke/`：本次真实试跑产物。

## 统一 CLI 入口

脚本入口：

```powershell
python scripts\demand_discovery_autonomous_research.py --mode <fake|real|codex> --topic "<需求方向>"
```

常用参数：

```text
--mode fake                         离线 fake 主链路，适合快速检查结构和报告产物
--mode real                         自研主链路真实 provider，当前不建议作为主要真实调研入口
--mode codex                        独立 Codex 链路，当前建议用于真实需求方向研判
--topic                             需求研判主题，必填
--output-root                       输出根目录，默认 outputs/runs
--run-id                            本次运行目录名
--max-rounds                        最大研究轮数
--seed-url                          可重复传入，约束 source strategy
--source-whitelist                  白名单 YAML，默认 configs/demand_discovery/source_whitelist.yaml
--allow-browser                     允许 browser 类信源进入 source strategy
--codex-model                       Codex 模型，默认 gpt-5.5
--codex-reasoning-effort            Codex reasoning effort，默认 high
--codex-timeout                     单角色超时秒数，默认 900
--codex-no-search                   禁用 Codex web search
--codex-max-worker-tasks-per-round  每轮 reader worker 数上限
--codex-max-report-rewrites         reporter 质量门禁重写次数
```

推荐真实运行命令：

```powershell
python scripts\demand_discovery_autonomous_research.py `
  --mode codex `
  --topic "低空无人机探测预警能力缺口" `
  --run-id codex-materialized-real-smoke `
  --max-rounds 1 `
  --codex-max-worker-tasks-per-round 1 `
  --codex-max-report-rewrites 1
```

离线结构验证命令：

```powershell
python scripts\demand_discovery_autonomous_research.py `
  --mode fake `
  --topic "低空无人机探测预警能力缺口" `
  --run-id demand-discovery-fake-check `
  --max-rounds 2
```

## 输出目录怎么看

每次运行写入：

```text
outputs/runs/<run-id>/
  round_summary.json        # 总控摘要，最重要的机器可读入口
  domain.jsonl              # SourceRecord / EvidenceCard / CandidateDemand / AuditReport / DemandReport 等领域对象
  trace.jsonl               # source -> evidence -> candidate -> audit -> report 的事件链
  report.md                 # 面向人工阅读的最终报告
  report_manifest.json      # report 发布元数据
  role_outputs/             # Codex 链路每个角色返回的 JSON
  codex_last_messages/      # Codex 每个角色最终消息文本
  artifacts/                # reader 后材料化保存的 HTML / text artifact
```

最先看 `round_summary.json` 的这些字段：

```text
execution                    是否为 independent_codex_workflow
accepted_source_ids          被白名单接受的 SourceRecord
accepted_evidence_ids        被接受的 EvidenceCard
source_materials             reader 后本地材料化结果
judgement                    judge 共识、盲点、下一轮计划
candidate                    synthesizer 生成的候选需求
audit                        auditor 审计结论和限制
report.review_status         report gate 状态
report_quality.status        reporter 质量门禁状态
```

## 主链路现状

入口：

```text
scripts/demand_discovery_autonomous_research.py --mode fake|real
src/knowledgegraph/demand_discovery/autonomous_research.py
```

主链路目标是复刻并产品化自研 agent harness，当前已经实现：

- source strategy：从白名单中选择 A/B 类公开信源，生成 seed / query plan。
- ResearchLoopController：按 round 编排 worker、judge、stop/continue 和候选合成。
- DiscoveryScheduler / WorkerSpec：支持多 worker 调度、事件订阅、进度输出和 session 隔离。
- DomainStore：统一落地 SourceRecord、EvidenceCard、CandidateDemand、AuditReport、DemandReport、ResearchRound、JudgementReport 等对象。
- 工具层：搜索、白名单抓取、正文简化、文档读取、浏览器 observe/execute、open search、report context 等。
- judge / auditor / reporter：有模型入口、fake provider、审计量表、报告发布和人工审核接口。
- retention / review / scheduled runner：已具备运行留痕、人工审核和定时任务的工程边界。

主链路当前问题：

- 真实联网工具的站点发现能力弱，遇到站内搜索、专题页、动态页面、英文站聚合页时成功率不稳定。
- 正文简化仍容易把导航、推荐、专题列表和正文压成一个长段落，影响精确段落定位。
- 自研工具调用需要模型严格按工具协议执行；真实运行中 reader 容易停在“找到了线索但未形成足够 EvidenceCard”的状态。
- 跨来源扩展和失败恢复还不够强，真实调研效率低于 Codex 自带 web search。

因此，主链路目前更适合做框架开发、fake e2e、工具单测和后续网络能力增强，不建议作为交付给业务协作者的主要真实使用入口。

## Codex 链路现状

入口：

```text
scripts/demand_discovery_autonomous_research.py --mode codex
src/knowledgegraph/demand_discovery/codex_workflow.py
```

工作流：

```text
source strategy
  -> planner
  -> reader worker(s)
  -> 本地导入 SourceRecord / EvidenceCard
  -> 本地材料化 accepted evidence: fetch/download -> classify -> read -> artifact refs
  -> judge
  -> 若 judge 要继续，则把 controller_tasks / worker_briefs 路由给下一轮 reader
  -> synthesizer
  -> auditor
  -> reporter
  -> report quality gate / rewrite
  -> publish report.md / report_manifest.json
```

Codex 链路当前已经实现：

- 独立控制流：不调用、不修改 Phase 5 主链路 controller。
- 角色复用：reader / judge / auditor / reporter 复用 `workers/agents/*.md`；planner / synthesizer 用 `workers/codex_roles/*.md` 补全。
- Codex CLI 执行：每个角色通过 Codex CLI 单独运行并返回 JSON。
- 白名单约束：本地导入 SourceRecord / EvidenceCard 时仍通过 `SourceRegistry` 校验 URL。
- judge-worker 多轮：judge 的 `controller_tasks` / `worker_briefs` 经现有 `judgement_plan` 和 `judge_plan_routing` 修复后再派发给下一轮 reader。
- reader 后材料化：accepted evidence 会调用现有 `fetch_page` / `download_document`、`classify_source_page`、`read_document` 和 `ArtifactStore` 保存 raw / text artifact，并尽量回填 `EvidenceCard.source_location` 与 `excerpt`。
- 报告质量门禁：薄报告会用 `report_quality_feedback` 请求 reporter 重写；audit 非 approved 时 report status 会降级。
- 产物完整：`role_outputs`、`codex_last_messages`、`round_summary.json`、`domain.jsonl`、`trace.jsonl`、`artifacts` 和 `report.md` 均落盘。

Codex 链路当前限制：

- 真实搜索由 Codex 自带 web search 完成，本地只能在导入和材料化阶段做白名单/证据约束。
- 如果网页正文简化质量差，`source_materials.read_excerpt` 可能带导航噪声。
- 当前材料化匹配是程序化近似匹配，不等同于人工页码级精读。
- 如果要升级到工程指标、型号能力或装备论证，仍需要更强的 PDF 全文、实验数据、指标来源和系统工程材料。

## 本次真实试跑结果

运行目录：

```text
outputs/runs/codex-materialized-real-smoke/
```

运行命令：

```powershell
python scripts\demand_discovery_autonomous_research.py `
  --mode codex `
  --topic "低空无人机探测预警能力缺口" `
  --run-id codex-materialized-real-smoke `
  --max-rounds 1 `
  --codex-max-worker-tasks-per-round 1 `
  --codex-max-report-rewrites 1
```

结果摘要：

```text
execution: independent_codex_workflow
round_count: 1
roles: planner, reader, judge, synthesizer, auditor, reporter
accepted_sources: 4
accepted_evidence: 4
source_materials: 4
source_material_statuses: matched
audit_conclusion: approved
report_status: review_ready
report_quality: passed
report_attempts: 1
```

这次试跑验证了：

- Codex 角色调用链完整执行。
- reader 产出的 4 条 evidence 均通过白名单导入。
- 4 条 evidence 均完成本地 HTML / text artifact 材料化。
- trace 中存在 `reader_source_materialized`。
- auditor 给出 `approved`。
- reporter 输出通过本地质量门禁并发布 `report.md`。

同时也暴露了后续优化点：81.cn 页面正文简化后部分 text artifact 为单个长段落，`read_excerpt` 会混入导航/推荐内容。这不影响链路打通，但会影响段落级引用精度。

## 后续改进方向

优先级 P0：让 Codex 链路稳定交付

- 优化 `page_simplify`，剥离 81.cn 等站点的导航、推荐、专题栏和页面 chrome。
- 对 `source_materials` 增加更严格的正文命中 gate：如果匹配段落过长或包含大量导航词，应标为 `fetched_needs_cleaning`，而不是直接 `matched`。
- 在 reporter prompt 中要求优先引用 `source_materials.matched_source_location`，避免回退到 reader 自报的旧 URL 段落。
- 增加真实 smoke 的轻量 summary checker，自动输出 accepted evidence、materialized evidence、report status 和异常口径检查。

优先级 P1：增强主链路真实联网能力

- 强化 `discover_articles` 对站内列表页、专题页、搜索页的识别和正文链接抽取。
- 针对核心白名单站点增加站点 profile / parser adapter，减少通用 HTML 简化误差。
- 改进 open search -> whitelist fetch 的闭环：搜索只产出候选 URL，EvidenceCard 必须来自本地 fetch/read 后的正文。
- 加强 browser observe/execute 在动态站点上的受控使用，保留安全底线但提升可达性。

优先级 P2：提升证据治理和报告可信度

- 为 EvidenceCard 增加材料化状态字段或 companion index，区分 `reader_claimed`、`locally_fetched`、`paragraph_matched`、`needs_cleaning`。
- 为报告生成前增加 consistency gate：所有核心 evidence 必须有本地 artifact ref。
- 将跨来源覆盖作为 judge/auditor 的结构化评分项，不只写在自然语言限制里。
- 建立多主题回归集，比较主链路、Codex 链路和人工 baseline 的 accepted evidence 数、source diversity、report readiness。

## 关键文件清单

```text
scripts/demand_discovery_autonomous_research.py
src/knowledgegraph/demand_discovery/autonomous_research.py
src/knowledgegraph/demand_discovery/codex_workflow.py
src/knowledgegraph/demand_discovery/network_research.py
src/knowledgegraph/demand_discovery/domain/
src/knowledgegraph/demand_discovery/harness/
src/knowledgegraph/demand_discovery/tools/
src/knowledgegraph/demand_discovery/workers/agents/
src/knowledgegraph/demand_discovery/workers/codex_roles/
configs/demand_discovery/source_whitelist.yaml
configs/demand_discovery/audit_rubric.json
tests/test_demand_discovery_codex_workflow.py
tests/test_demand_discovery_autonomous_research_runner.py
docs/superpowers/plans/2026-07-01-codex-demand-workflow.md
outputs/runs/codex-materialized-real-smoke/
```

## 协作者开箱验证

在包根目录执行：

```powershell
python --version
pip install -r requirements.txt
python -m unittest tests.test_demand_discovery_codex_workflow tests.test_demand_discovery_autonomous_research_runner -v
python -m py_compile src\knowledgegraph\demand_discovery\codex_workflow.py scripts\demand_discovery_autonomous_research.py
```

若本机已安装并登录 Codex CLI，可继续执行真实链路：

```powershell
codex --version
python scripts\demand_discovery_autonomous_research.py `
  --mode codex `
  --topic "低空无人机探测预警能力缺口" `
  --run-id collaborator-codex-check `
  --max-rounds 1 `
  --codex-max-worker-tasks-per-round 1
```

普通干净交接包不要包含 `.env`、API Key、Codex token 或本机私有 `CODEX_HOME`。本 runtime minimal 包按交接要求额外包含 `.env`，但仍不包含本机 `CODEX_HOME` 或 Codex auth。

## 最小运行配置说明

本包是 runtime minimal 版本，额外包含仓库根目录 `.env`，用于让 CLI 读取运行参数。它不包含本机 `CODEX_HOME`、Codex auth、历史会话、logs 或个人 skills。协作者应使用自己机器上已经登录可用的 Codex CLI 环境。

运行示例：

```powershell
.\RUN_CODEX_WORKFLOW.ps1 -Topic "低空无人机探测预警能力缺口" -RunId "collaborator-codex-check"
```

如果协作者使用自定义 Codex home，请在运行前自行设置环境变量：

```powershell
$env:CODEX_HOME="D:\path\to\their\.codex"
.\RUN_CODEX_WORKFLOW.ps1
```

注意：该包包含 `.env`，只应通过可信渠道交给指定协作者，不应提交到 Git 或公开网盘。
