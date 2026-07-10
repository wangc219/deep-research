# Phase 10 前后端联调与企业交付验收实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成五判据审计、甲方可读报告、前后端联调、企业安全、容器部署、样例、操作文档和最终验收，使系统达到可安装、可运行、可审计、可演示、可运维的企业级交付标准。

**Architecture:** 审计 agent 使用只读投影检查对象级追溯和门控；报告 agent 只消费已审计的能力画像、证据卡和限制。ExportService 统一导出七类规定产物、数据库快照和 manifest；Docker Compose 组合 Web、API、worker、PostgreSQL、Redis 和反向代理，前后端通过同一 OpenAPI 契约验收。

**Tech Stack:** Markdown、JSON/JSONL、PostgreSQL、Redis、FastAPI、React、Playwright、Docker Compose、Nginx、pytest、hashlib。

## Global Constraints

- 报告不得出现无 EvidenceCard 支撑的事实性结论。
- 报告必须明确区分新作战能力方向和现有装备升级需求。
- 报告必须直接回答“需要发展具备什么功能的产品”。
- 分析师未确认时，最终状态不能是 `approved`。
- 发布产物中的对象引用必须可解析，文件 hash 写入 manifest。
- Web、API、CLI 导出的同一 run 必须具有一致 capability ids、evidence ids 和 audit status。
- 验收部署必须启用非默认凭据、持久卷、健康检查和服务重启策略。
- 前端生产构建只能通过同源 `/api/v1` 访问后端。

---

### Task 1: 实现最终五判据审计

**Files:**
- Rewrite: `src/equipment_deep_research/orchestration/reporting.py`
- Create: `src/equipment_deep_research/orchestration/audit.py`
- Test: `tests/equipment_deep_research/unit/test_final_audit.py`

**Interfaces:**
- Produces: `FinalAuditPolicy`、`FinalAuditor.audit()`、`AuditResult.status`。

- [ ] **Step 1: 写失败测试**

```python
def test_all_five_criteria_are_required_for_approval() -> None:
    result = auditor.audit(valid_run_view(analyst_confirmed=True))
    assert result.status == "approved"
    assert set(result.checks) == {
        "consistency", "confidence", "coverage", "analyst_confirmation", "round_limit"
    }

def test_unconfirmed_run_requires_review() -> None:
    result = auditor.audit(valid_run_view(analyst_confirmed=False))
    assert result.status == "review_required"
    assert result.checks["analyst_confirmation"] is False

def test_broken_traceability_is_limited() -> None:
    result = auditor.audit(run_with_missing_evidence_ref())
    assert result.status == "limited"
    assert "missing evidence" in " ".join(result.comments).lower()
```

- [ ] **Step 2: 运行并确认旧审计不符合五判据**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_final_audit.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现对象级检查**

一致性检查场景/路径/能力/装备映射和矛盾；置信度检查关键节点 ≥0.70；覆盖度检查路线必需输出或 limitation；确认检查 CLI 标志和确认时间；轮次检查总轮次与 target attempt。状态优先级为 `failed > limited > review_required > approved`。

- [ ] **Step 4: 运行审计测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_final_audit.py -q`

Expected: PASS。

- [ ] **Step 5: 验证审计 agent 只读 scope**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_final_audit.py -q -k readonly`

Expected: auditor 只能写 `AuditResult` 和 trace，不能改 EvidenceCard、stage 或 capability。

### Task 2: 实现甲方可读报告模板

**Files:**
- Create: `src/equipment_deep_research/orchestration/report_templates.py`
- Modify: `src/equipment_deep_research/orchestration/reporting.py`
- Test: `tests/equipment_deep_research/unit/test_report_rendering.py`

**Interfaces:**
- Produces: `ReportRenderer.render()`、`ResearchReport`。

- [ ] **Step 1: 写失败测试固定报告结构**

```python
def test_report_answers_core_question_and_separates_types() -> None:
    report = renderer.render(valid_run_view())
    assert "## 核心结论：需要发展具备什么功能的产品" in report.body
    assert "## 新作战能力方向" in report.body
    assert "## 现有装备升级需求" in report.body
    assert "## 制胜逻辑与场景追溯" in report.body
    assert "## 证据索引" in report.body
    assert "## 限制与待确认事项" in report.body

def test_every_capability_line_links_logic_scenario_evidence_and_gap() -> None:
    report = renderer.render(valid_run_view())
    for item in valid_run_view().capability_images:
        assert item.capability_id in report.body
        assert item.source_winning_logic in report.body
        assert item.related_scenario in report.body
        assert item.capability_gap in report.body
        assert item.evidence_ids[0] in report.body
```

- [ ] **Step 2: 运行并确认旧报告结构不足**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_report_rendering.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现报告章节**

章节顺序固定为：执行摘要、研究问题与路线、启用 agent 与覆盖、形势/场景/装备/运用综合发现、制胜机理 L1/L2/L3、核心产品功能结论、新能力、升级需求、优先级、追溯链、证据索引、冲突与反证、限制、分析师确认。

- [ ] **Step 4: 运行报告测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_report_rendering.py -q`

Expected: PASS。

- [ ] **Step 5: 验证报告不引用 rejected evidence**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_report_rendering.py -q -k rejected`

Expected: PASS；rejected 材料只能出现在“限制/反证”并带状态说明。

### Task 3: 实现统一发布器与交付 manifest

**Files:**
- Create: `src/equipment_deep_research/application/export_service.py`
- Create: `src/equipment_deep_research/orchestration/publisher.py`
- Modify: `src/equipment_deep_research/orchestration/runner.py`
- Modify: `src/equipment_deep_research/api/routes/reports.py`
- Test: `tests/equipment_deep_research/integration/test_output_publisher.py`
- Test: `tests/equipment_deep_research/api/test_export_api.py`

**Interfaces:**
- Produces: `ExportService.export_run()`、`RunPublisher.publish()`、`delivery_manifest.json`、`GET /runs/{run_id}/export`。

- [ ] **Step 1: 写失败测试**

```python
def test_publisher_writes_required_outputs_and_hashes(tmp_path: Path) -> None:
    published = publisher(tmp_path).publish(valid_run_view())
    required = {
        "report.md", "capability_images.json", "round_summary.json",
        "domain.jsonl", "trace.jsonl", "agent_sessions", "artifacts",
    }
    assert required <= {path.name for path in published.paths}
    manifest = json.loads((tmp_path / "delivery_manifest.json").read_text())
    assert manifest["files"]["report.md"]["sha256"]
    assert manifest["schema_version"] == "1.0"
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_output_publisher.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现原子发布**

先写 `*.tmp`，校验 JSON/JSONL 和引用，再原子替换；manifest 记录 run id、schema version、生成时间、状态、模型、agent ids、route、文件大小和 SHA-256。保留 `run.db` 与 `checkpoints/` 供恢复，但不替代规定产物。

- [ ] **Step 4: 运行发布器测试**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_output_publisher.py -q`

Expected: PASS。

- [ ] **Step 5: 验证损坏引用阻止发布**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_output_publisher.py -q -k broken_ref`

Expected: 发布失败且不留下半成品正式文件。

### Task 4: 建立完整交付 E2E 与验收矩阵

**Files:**
- Create: `tests/equipment_deep_research/e2e/test_delivery_bundle.py`
- Create: `tests/equipment_deep_research/e2e/test_api_cli_consistency.py`
- Create: `apps/web/tests/delivery.spec.ts`
- Create: `apps/web/tests/traceability.spec.ts`
- Rewrite: `docs/ACCEPTANCE.md`
- Create: `docs/CONFIGURATION.md`
- Create: `docs/AGENT_CUSTOMIZATION.md`
- Create: `docs/OPERATIONS.md`

**Interfaces:**
- Consumes: 完整 runner 和 publisher。
- Produces: 自动验收入口与操作文档。

- [ ] **Step 1: 写交付 E2E**

```python
@pytest.mark.parametrize("route", [
    "new_winning_mechanism", "traditional_gap", "war_case_learning",
])
def test_delivery_bundle_for_each_route(route, tmp_path) -> None:
    result = run_fake_delivery(tmp_path, route=route, analyst_confirmed=True)
    validate_manifest(Path(result["run_dir"]))
    validate_all_object_refs(Path(result["run_dir"]))
    report = Path(result["report_path"]).read_text()
    assert "需要发展具备什么功能的产品" in report

def test_api_and_cli_export_same_domain_results(tmp_path) -> None:
    cli_result = run_via_cli(tmp_path, run_id="same-input-cli")
    api_result = run_via_api(tmp_path, run_id="same-input-api")
    assert capability_ids(cli_result) == capability_ids(api_result)
    assert evidence_ids(cli_result) == evidence_ids(api_result)
    assert audit_status(cli_result) == audit_status(api_result)
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/e2e/test_delivery_bundle.py tests/equipment_deep_research/e2e/test_api_cli_consistency.py -q`

Expected: FAIL，直到文档和发布校验完成。

- [ ] **Step 3: 编写精确使用文档**

`CONFIGURATION.md` 解释 provider、模型、预算、搜索、证据评分；`AGENT_CUSTOMIZATION.md` 给出一个可运行自定义 agent YAML 和 output contract；`OPERATIONS.md` 给出 fake、real、resume、子集 agent、分析师确认、故障诊断命令。

- [ ] **Step 4: 运行交付 E2E**

Run: `python3 -m pytest tests/equipment_deep_research/e2e/test_delivery_bundle.py tests/equipment_deep_research/e2e/test_api_cli_consistency.py -q`

Expected: PASS；随后运行 `pnpm --dir apps/web playwright test tests/delivery.spec.ts tests/traceability.spec.ts`，Web 可完成同一交付流程。

- [ ] **Step 5: 执行验收文档中的所有命令**

Run: `python3 -m pytest -q`

Expected: 全部 PASS；fake 示例命令均退出 0；real 命令按环境得到 approved/review_required/limited 中的可解释状态。

### Task 5: 生成甲方算法与 Web 演示样例

**Files:**
- Create: `examples/fake-new-winning/`
- Create: `examples/fake-traditional-gap/`
- Create: `examples/fake-war-case/`
- Create: `examples/fake-agent-subset/`
- Create: `examples/fake-custom-agent/`
- Create: `examples/real-smoke/`
- Create: `examples/web-research-lifecycle/`

**Interfaces:**
- Produces: 可演示算法产物和 Web 操作截图。

- [ ] **Step 1: 生成五个确定性 fake 样例**

每个样例保留 `report.md`、`capability_images.json`、`round_summary.json`、精简后的 trace 摘要和运行命令；完整 raw artifact 仍留在 `outputs/runs/`，避免文档目录膨胀。

- [ ] **Step 2: 生成真实 smoke 样例或降级样例**

真实网络可用时保留 accepted evidence 的公开 URL、excerpt 和 artifact hash；不可用时保留 limited 诊断，并在最终测试报告标注在线复验命令。

- [ ] **Step 3: 生成 Web 生命周期样例**

保存研究任务列表、新建研究、实时控制台、证据中心、L1/L2/L3、能力画像和报告评审的 1440×900 截图；截图只使用 fake 演示数据，不包含密钥和内部诊断信息。

- [ ] **Step 4: 校验所有样例 manifest**

Run: `python3 scripts/validate_examples.py examples`

Expected: 每个算法样例对象引用有效，Web 截图清单完整。

- [ ] **Step 5: 记录样例复现命令**

每个样例 README 给出 CLI 或 Web 路径、使用的 agent、route、配置 revision 和预期 audit status。

### Task 6: 实现企业验收部署包

**Files:**
- Create: `deploy/compose/docker-compose.yml`
- Create: `deploy/compose/.env.example`
- Create: `deploy/nginx/nginx.conf`
- Create: `deploy/production/api.env.example`
- Create: `deploy/production/worker.env.example`
- Create: `deploy/production/web.env.example`
- Create: `Dockerfile.api`
- Create: `Dockerfile.worker`
- Create: `apps/web/Dockerfile`
- Create: `tests/deployment/test_compose_smoke.py`

**Interfaces:**
- Produces: Web、API、worker、PostgreSQL、Redis、Nginx 单机验收部署。

- [ ] **Step 1: 写部署 smoke 测试**

```python
def test_compose_services_are_healthy(compose_stack) -> None:
    assert compose_stack.get("/api/v1/health/live").status_code == 200
    ready = compose_stack.get("/api/v1/health/ready").json()
    assert ready["database"] == "ready"
    assert ready["queue"] == "ready"
    assert compose_stack.get("/").status_code == 200
```

- [ ] **Step 2: 构建容器**

Run: `docker compose -f deploy/compose/docker-compose.yml build`

Expected: API、worker、web 镜像构建成功，前端生产镜像不包含开发依赖和密钥文件。

- [ ] **Step 3: 启动并迁移**

Run: `docker compose -f deploy/compose/docker-compose.yml up -d`

Expected: PostgreSQL/Redis 先健康，迁移完成后 API、worker、web/nginx 健康。

- [ ] **Step 4: 运行 compose smoke**

Run: `python3 -m pytest tests/deployment/test_compose_smoke.py -q`

Expected: PASS，可通过 Web 创建并完成一个 fake run。

- [ ] **Step 5: 验证重启恢复**

在研究中重启 API 和 worker，确认 API 重启不影响 queued/running run，worker 从最后 save point 恢复且不重复 EvidenceCard。

### Task 7: 完成安全、性能和可靠性验收

**Files:**
- Create: `tests/security/test_secret_redaction.py`
- Create: `tests/security/test_oidc_rbac.py`
- Create: `tests/security/test_artifact_headers.py`
- Create: `tests/performance/test_run_list_api.py`
- Create: `tests/performance/test_sse_fanout.py`
- Create: `tests/performance/test_worker_concurrency.py`
- Create: `docs/testing/security-test-report.md`
- Create: `docs/testing/performance-test-report.md`

**Interfaces:**
- Consumes: 企业部署 profile。
- Produces: 安全与性能基线。

- [ ] **Step 1: 执行安全测试**

Run: `python3 -m pytest tests/security -q`

Expected: 密钥脱敏、OIDC claims、RBAC、artifact header、SSRF 和配置 revision 测试全部通过。

- [ ] **Step 2: 执行前端依赖和构建检查**

Run: `pnpm --dir apps/web audit --prod`

Expected: 无 high/critical 级生产依赖漏洞；存在例外时必须在安全报告记录组件、影响、缓解和升级计划。

- [ ] **Step 3: 执行性能基线**

Run: `python3 -m pytest tests/performance -q`

Expected: 1000 条 run 的列表接口 P95 小于 500ms；单 API 实例 50 个 SSE 连接稳定；worker 并发 4 时无重复 save point。

- [ ] **Step 4: 执行浏览器性能检查**

Run: `pnpm --dir apps/web playwright test tests/performance.spec.ts`

Expected: 1440×900 下任务列表、运行控制台和能力画像首屏 3 秒内可交互，500 条证据使用服务端分页且无明显布局抖动。

- [ ] **Step 5: 编写安全和性能报告**

报告记录环境、数据规模、命令、结果、阈值、未关闭风险和甲方生产部署建议。

### Task 8: 完成企业文档、最终测试报告和交付清单

**Files:**
- Rewrite: `README.md`
- Rewrite: `docs/TECHNICAL_SCHEME.md`
- Rewrite: `docs/ACCEPTANCE.md`
- Create: `docs/API.md`
- Create: `docs/USER_GUIDE.md`
- Create: `docs/ADMIN_GUIDE.md`
- Create: `docs/OPERATIONS.md`
- Create: `docs/DEPLOYMENT.md`
- Create: `docs/testing/final-test-report.md`
- Create: `docs/DELIVERY_CHECKLIST.md`

**Interfaces:**
- Produces: 甲方企业交付文档集。

- [ ] **Step 1: 编写角色化手册**

用户手册覆盖创建、监控、证据、制胜机理、能力画像、评审和导出；管理员手册覆盖 agent/provider/tool/context/evidence 配置和 revision；运维手册覆盖迁移、备份、恢复、健康检查、日志和故障处理。

- [ ] **Step 2: 编写接口和部署文档**

API 文档引用生成 OpenAPI；部署文档分别给出开发、甲方验收和生产 profile，明确 PostgreSQL、Redis、artifact、OIDC、TLS、出口代理和密钥配置。

- [ ] **Step 3: 编写最终测试报告**

报告必须列出：算法测试、API、worker、数据库、前端单元、Playwright、三视口、RBAC、SSE、恢复、联网、五判据、安全、性能、compose 和已知限制。

- [ ] **Step 4: 执行最终自动验收**

```bash
python3 -m pytest -q
pnpm --dir apps/web test --run
pnpm --dir apps/web build
pnpm --dir apps/web playwright test
python3 -m pytest tests/deployment/test_compose_smoke.py -q
```

Expected: 全部 PASS。

- [ ] **Step 5: 完成交付清单审查**

`DELIVERY_CHECKLIST.md` 逐项确认算法源码、CLI、API、worker、Web 源码与构建产物、数据库迁移、容器、默认配置、自定义 agent 说明、fake/real 样例、三张架构图 HTML/PDF、OpenAPI、用户/管理员/运维手册、安全/性能/最终测试报告和验收说明均存在且与实际实现一致。
