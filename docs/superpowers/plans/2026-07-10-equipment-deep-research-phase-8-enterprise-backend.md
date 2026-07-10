# Phase 8 企业后端服务与异步任务实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在研究内核之上实现 FastAPI、application service、持久化运行状态、独立 worker、Redis 队列、可重放 SSE、RBAC 和版本化 OpenAPI。

**Architecture:** API 不直接运行多智能体任务，只校验 command 并交给 `RunQueue`；worker 通过 `ResearchApplicationService` 调用现有 runner。PostgreSQL 保存业务与审计真相，Redis 只承担队列、锁和短期通知；开发模式可使用 SQLite 与 in-process queue。

**Tech Stack:** FastAPI、Pydantic 2、SQLAlchemy 2、Alembic、PostgreSQL、Redis、pytest、httpx。

## Global Constraints

- API base path 固定为 `/api/v1`。
- CLI 与 API 必须调用同一个 `ResearchApplicationService`。
- 所有写接口支持 `Idempotency-Key`；配置写接口支持 `If-Match` revision。
- API key、provider header、完整模型上下文和原始 session 不进入 API DTO。
- 长任务只能由 worker 执行，FastAPI request handler 不调用 `DeepResearchRunner.run()`。
- SSE 支持 `Last-Event-ID` 补发。

---

### Task 1: 建立 application service 与运行状态机

**Files:**
- Create: `src/equipment_deep_research/application/__init__.py`
- Create: `src/equipment_deep_research/application/dto.py`
- Create: `src/equipment_deep_research/application/run_service.py`
- Create: `src/equipment_deep_research/application/review_service.py`
- Modify: `src/equipment_deep_research/orchestration/runner.py`
- Test: `tests/equipment_deep_research/unit/test_run_application_service.py`

**Interfaces:**
- Consumes: `DeepResearchRunner`、`RunRepository`、`RunQueue`。
- Produces: `CreateRunCommand`、`RunView`、`ResearchApplicationService.create_run()`、`start_run()`、`pause_run()`、`resume_run()`、`cancel_run()`、`execute_run()`。

- [ ] **Step 1: 写失败测试固定状态机**

```python
def test_create_and_start_run_are_separate_commands(service) -> None:
    created = service.create_run(CreateRunCommand(
        topic="低空无人机探测预警能力",
        research_route="new_winning_mechanism",
        selected_agent_ids=["international_situation", "combat_scenario"],
        max_rounds=5,
        created_by="analyst-1",
    ))
    assert created.status == "draft"
    started = service.start_run(created.run_id, actor="analyst-1", idempotency_key="start-1")
    assert started.status == "queued"
    assert service.queue.pending_run_ids() == [created.run_id]

def test_invalid_transition_is_rejected(service) -> None:
    run = service.create_run(valid_create_command())
    with pytest.raises(InvalidRunTransition, match="draft.*resume"):
        service.resume_run(run.run_id, actor="analyst-1", idempotency_key="resume-1")
```

- [ ] **Step 2: 运行并确认 application 模块不存在**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_run_application_service.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现状态与 command**

运行状态定义为 `draft|queued|planning|researching|winning_l1|recalling|winning_l2|winning_l3|auditing|review_required|completed|pause_requested|paused|cancel_requested|cancelled|limited|failed`。每次 command 写入 actor、request id、idempotency key 和审计事件。

- [ ] **Step 4: 运行 application service 测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_run_application_service.py -q`

Expected: PASS。

- [ ] **Step 5: 将 CLI 改为调用 application service**

Run: `python3 -m pytest tests/test_deep_research_runner.py tests/equipment_deep_research/unit/test_run_application_service.py -q`

Expected: CLI 既有行为保持通过，且 CLI 与 API 用例层不重复业务逻辑。

### Task 2: 实现 SQLAlchemy 仓储与 Alembic 迁移

**Files:**
- Create: `src/equipment_deep_research/persistence/__init__.py`
- Create: `src/equipment_deep_research/persistence/database.py`
- Create: `src/equipment_deep_research/persistence/models.py`
- Create: `src/equipment_deep_research/persistence/repositories.py`
- Create: `alembic.ini`
- Create: `migrations/env.py`
- Create: `migrations/versions/20260710_0001_initial.py`
- Test: `tests/equipment_deep_research/integration/test_persistence.py`

**Interfaces:**
- Produces: `RunRepository`、`DomainObjectRepository`、`EventRepository`、`ReviewRepository`、`ConfigurationRepository`。

- [ ] **Step 1: 写失败测试覆盖持久化和并发 revision**

```python
def test_run_and_events_survive_new_repository_instance(database_url: str) -> None:
    first = repositories(database_url)
    first.runs.create(run_record("run-1"))
    first.events.append(runtime_event(sequence=1, run_id="run-1"))
    second = repositories(database_url)
    assert second.runs.get("run-1").status == "draft"
    assert second.events.list_after("run-1", sequence=0)[0].sequence == 1

def test_configuration_revision_prevents_lost_update(repositories) -> None:
    current = repositories.configuration.get("agents")
    repositories.configuration.update("agents", payload_a(), expected_revision=current.revision)
    with pytest.raises(RevisionConflict):
        repositories.configuration.update("agents", payload_b(), expected_revision=current.revision)
```

- [ ] **Step 2: 运行并确认持久化模块不存在**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_persistence.py -q`

Expected: FAIL。

- [ ] **Step 3: 建立数据库表**

迁移创建 `users`、`runs`、`run_tasks`、`domain_objects`、`runtime_events`、`reviews`、`configuration_revisions`、`artifact_index`、`idempotency_keys`。所有 run 关联表包含 `run_id`，事件 sequence 在 run 内唯一。

- [ ] **Step 4: 在 SQLite 和 PostgreSQL profile 运行测试**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_persistence.py -q`

Expected: PASS；无 PostgreSQL 环境时容器测试标记为 integration 并在 CI profile 执行。

- [ ] **Step 5: 验证迁移可升级和回滚一个版本**

Run: `alembic upgrade head`

Expected: 退出码 0，`alembic current` 显示 `20260710_0001`。

### Task 3: 实现任务队列与独立 worker

**Files:**
- Create: `src/equipment_deep_research/queue/__init__.py`
- Create: `src/equipment_deep_research/queue/base.py`
- Create: `src/equipment_deep_research/queue/in_process.py`
- Create: `src/equipment_deep_research/queue/redis_queue.py`
- Create: `src/equipment_deep_research/queue/worker.py`
- Test: `tests/equipment_deep_research/integration/test_worker_queue.py`
- Test: `tests/equipment_deep_research/integration/test_worker_recovery.py`

**Interfaces:**
- Produces: `RunQueue.enqueue()`、`claim()`、`ack()`、`retry()`；`ResearchWorker.run_once()`、`heartbeat()`。

- [ ] **Step 1: 写失败测试**

```python
def test_worker_claims_run_and_executes_application_service(queue, service) -> None:
    queue.enqueue("run-1", idempotency_key="enqueue-1")
    worker = ResearchWorker(queue=queue, service=service, worker_id="worker-1")
    outcome = worker.run_once()
    assert outcome.run_id == "run-1"
    assert queue.is_acked("run-1") is True

def test_stale_claim_is_recovered_without_repeating_savepoint(queue, service) -> None:
    queue.seed_stale_claim("run-2", claimed_by="dead-worker")
    service.seed_checkpoint("run-2", checkpoint_id="cp-2", completed_task_ids=["task-a"])
    outcome = ResearchWorker(queue, service, "worker-2").run_once()
    assert outcome.resumed_from == "cp-2"
    assert service.execution_count("task-a") == 0
```

- [ ] **Step 2: 运行并确认队列模块不存在**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_worker_queue.py tests/equipment_deep_research/integration/test_worker_recovery.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现开发与企业队列**

`InProcessRunQueue` 用于测试和本地开发；`RedisRunQueue` 使用 consumer group、可见性超时和幂等键。worker 每 10 秒 heartbeat，在 save point 检查 pause/cancel command，失败按错误类型决定 retry 或 failed。

- [ ] **Step 4: 运行队列和恢复测试**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_worker_queue.py tests/equipment_deep_research/integration/test_worker_recovery.py -q`

Expected: PASS。

- [ ] **Step 5: 验证 API 代码不直接运行研究**

Run: `rg -n "DeepResearchRunner\(|\.execute_run\(" src/equipment_deep_research/api/routes`

Expected: 无结果。

### Task 4: 实现 FastAPI、版本化路由和统一错误

**Files:**
- Create: `src/equipment_deep_research/api/__init__.py`
- Create: `src/equipment_deep_research/api/app.py`
- Create: `src/equipment_deep_research/api/dependencies.py`
- Create: `src/equipment_deep_research/api/errors.py`
- Create: `src/equipment_deep_research/api/middleware.py`
- Create: `src/equipment_deep_research/api/schemas/runs.py`
- Create: `src/equipment_deep_research/api/routes/catalog.py`
- Create: `src/equipment_deep_research/api/routes/runs.py`
- Create: `src/equipment_deep_research/api/routes/evidence.py`
- Create: `src/equipment_deep_research/api/routes/winning.py`
- Create: `src/equipment_deep_research/api/routes/reports.py`
- Test: `tests/equipment_deep_research/api/test_runs_api.py`
- Test: `tests/equipment_deep_research/api/test_openapi.py`

**Interfaces:**
- Produces: `create_app()` 和 `/api/v1` 路由。

- [ ] **Step 1: 写失败 API 测试**

```python
def test_create_start_and_get_run(client) -> None:
    created = client.post("/api/v1/runs", headers={"Idempotency-Key": "create-1"}, json={
        "topic": "低空无人机探测预警能力",
        "research_route": "new_winning_mechanism",
        "selected_agent_ids": ["international_situation", "combat_scenario"],
        "max_rounds": 5,
    })
    assert created.status_code == 201
    run_id = created.json()["run_id"]
    assert client.post(f"/api/v1/runs/{run_id}/start", headers={"Idempotency-Key": "start-1"}).status_code == 202
    assert client.get(f"/api/v1/runs/{run_id}").json()["status"] == "queued"

def test_error_has_stable_shape(client) -> None:
    response = client.get("/api/v1/runs/missing")
    assert response.status_code == 404
    assert set(response.json()) == {"code", "message", "details", "request_id"}
```

- [ ] **Step 2: 运行并确认 API 不存在**

Run: `python3 -m pytest tests/equipment_deep_research/api/test_runs_api.py tests/equipment_deep_research/api/test_openapi.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现 API 与 OpenAPI schema**

路由只调用 application service；中间件生成 request id、记录结构化访问日志并处理 idempotency。OpenAPI operation id 使用稳定命名，例如 `create_run`、`get_run_evidence`、`confirm_run_report`。

- [ ] **Step 4: 运行 API 测试**

Run: `python3 -m pytest tests/equipment_deep_research/api/test_runs_api.py tests/equipment_deep_research/api/test_openapi.py -q`

Expected: PASS。

- [ ] **Step 5: 导出 OpenAPI artifact**

Run: `python3 scripts/export_openapi.py --output apps/web/openapi/openapi.json`

Expected: 文件存在，包含 `/api/v1/runs`、`/events`、`/evidence`、`/winning`、`/capabilities`、`/report` 和 `/configuration`。

### Task 5: 实现可重放 SSE 事件流

**Files:**
- Create: `src/equipment_deep_research/api/sse.py`
- Create: `src/equipment_deep_research/api/routes/events.py`
- Modify: `src/equipment_deep_research/harness/event_bus.py`
- Test: `tests/equipment_deep_research/api/test_sse_replay.py`

**Interfaces:**
- Consumes: `EventRepository.list_after(run_id, sequence)`。
- Produces: `RunEventStream.stream()`、`GET /runs/{run_id}/events`。

- [ ] **Step 1: 写失败测试**

```python
def test_sse_replays_after_last_event_id(client, event_repository) -> None:
    event_repository.append(run_event("run-1", 1, "run_status_changed"))
    event_repository.append(run_event("run-1", 2, "agent_status_changed"))
    event_repository.append(run_event("run-1", 3, "round_completed"))
    response = client.get("/api/v1/runs/run-1/events", headers={"Last-Event-ID": "1"})
    assert "id: 2" in response.text
    assert "id: 3" in response.text
    assert "id: 1" not in response.text
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/api/test_sse_replay.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现 replay、heartbeat 和脱敏**

先从数据库补发历史，再订阅 Redis 通知；每 15 秒发送 comment heartbeat。event id 使用 sequence，payload 只包含对象引用和安全摘要。

- [ ] **Step 4: 运行 SSE 测试**

Run: `python3 -m pytest tests/equipment_deep_research/api/test_sse_replay.py -q`

Expected: PASS。

- [ ] **Step 5: 验证事件 DTO 与 OpenAPI 对齐**

Run: `python3 -m pytest tests/equipment_deep_research/api/test_openapi.py -q -k event`

Expected: PASS。

### Task 6: 实现鉴权、RBAC 和 artifact 权限

**Files:**
- Create: `src/equipment_deep_research/api/auth.py`
- Create: `src/equipment_deep_research/api/routes/auth.py`
- Create: `src/equipment_deep_research/api/routes/configuration.py`
- Create: `src/equipment_deep_research/api/routes/artifacts.py`
- Test: `tests/equipment_deep_research/api/test_api_rbac.py`
- Test: `tests/equipment_deep_research/api/test_artifact_access.py`

**Interfaces:**
- Produces: `CurrentUser`、`require_roles()`、开发账号 adapter、OIDC claims adapter。

- [ ] **Step 1: 写失败权限矩阵测试**

```python
@pytest.mark.parametrize("role,path,method,expected", [
    ("analyst", "/api/v1/runs", "POST", 201),
    ("auditor", "/api/v1/runs", "POST", 403),
    ("reviewer", "/api/v1/runs/run-1/confirm", "POST", 200),
    ("analyst", "/api/v1/configuration/agents", "PUT", 403),
    ("admin", "/api/v1/configuration/agents", "PUT", 200),
])
def test_role_matrix(client_for_role, role, path, method, expected) -> None:
    response = client_for_role(role).request(method, path, headers={"Idempotency-Key": f"{role}-{method}"}, json=request_body(path))
    assert response.status_code == expected
```

- [ ] **Step 2: 运行并确认所有请求尚未鉴权**

Run: `python3 -m pytest tests/equipment_deep_research/api/test_api_rbac.py tests/equipment_deep_research/api/test_artifact_access.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现服务端权限**

开发 adapter 从测试 header 注入用户；生产 adapter 验证 OIDC issuer、audience、expiry 和角色 claims。Artifact 下载先校验 run 可见权限，再返回受控 content type 与 attachment filename。

- [ ] **Step 4: 运行权限测试**

Run: `python3 -m pytest tests/equipment_deep_research/api/test_api_rbac.py tests/equipment_deep_research/api/test_artifact_access.py -q`

Expected: PASS。

- [ ] **Step 5: 生成 Phase 8 审查包**

Run: `python3 -m pytest -q`

Expected: 全部 PASS；`docs/testing/phase-8-test-report.md` 记录 OpenAPI、状态机、worker 恢复、SSE replay、RBAC、迁移和健康检查结果。
