# Phase 2 Registry 与模型执行后端实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 agent/tool/provider 三类 registry，接入默认 `gpt-5.5` 的 Responses-compatible HTTP provider，使 fake 与真实执行后端在相同 Harness 下可互换。

**Architecture:** Registry 只负责配置解析和实例构造，不承载业务流程。Provider 通过统一异步 stream 协议输出文本、推理片段和工具调用；敏感配置只从环境变量读取，事件和 session 只记录脱敏后的 provider 快照。

**Tech Stack:** urllib/requests、SSE、asyncio、PyYAML、pytest mock transport。

## Global Constraints

- 默认 provider 为 `responses`，默认模型为 `gpt-5.5`。
- 测试不得访问公网。
- provider 不得执行工具；工具只由 AgentLoop/ToolRegistry 执行。
- agent 配置声明的工具和对象 scope 必须在加载期校验、调用期复核。
- API key、Authorization header 不得进入 trace、session 或异常文本。

---

### Task 1: 完成 AgentRegistry 强校验和自定义替换

**Files:**
- Modify: `src/equipment_deep_research/agents/registry.py`
- Create: `src/equipment_deep_research/agents/contracts.py`
- Test: `tests/equipment_deep_research/unit/test_agent_registry.py`

**Interfaces:**
- Produces: `AgentDef.object_read_scopes`、`object_write_scopes`、`model_profile`、`validate()`；`AgentRegistry.select_agents()`、`resolve_capability()`。

- [ ] **Step 1: 写失败测试**

```python
def test_registry_rejects_duplicate_ids_and_unknown_contract(tmp_path: Path) -> None:
    path = write_agents(tmp_path, agents=[agent("same"), agent("same")])
    with pytest.raises(ValueError, match="duplicate agent_id"):
        AgentRegistry.load(path)

def test_custom_agent_can_cover_multiple_default_capabilities(tmp_path: Path) -> None:
    registry = AgentRegistry.load(write_integrated_agent(tmp_path))
    selected = registry.select_agents(["integrated_research"])
    assert {"situation", "threat", "scenario", "equipment", "operation"} <= set(selected[0].capability_tags)
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_agent_registry.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现加载期校验**

必须校验：唯一 `agent_id`、非空 capability tags、工具存在于 ToolRegistry 定义、input/output contract 存在、可见 section 合法、read/write scope 合法、默认 baseline agent 不包含系统 agent。

- [ ] **Step 4: 运行 registry 测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_agent_registry.py -q`

Expected: PASS。

- [ ] **Step 5: 验证默认和自定义配置**

Run: `python3 -m pytest tests/equipment_deep_research -q -k "custom_agent or registry"`

Expected: PASS。

### Task 2: 实现 ToolRegistry 与双重权限检查

**Files:**
- Create: `src/equipment_deep_research/tools/registry.py`
- Modify: `src/equipment_deep_research/tools/permissions.py`
- Modify: `src/equipment_deep_research/harness/agent_harness.py`
- Test: `tests/equipment_deep_research/integration/test_tool_registry.py`

**Interfaces:**
- Consumes: `ToolDefinition`、`TaskEnvelope`、`AgentDef`。
- Produces: `ToolRegistry.register()`、`active_for(agent, task)`、`execute(call, context)`。

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_task_cannot_expand_agent_tool_permissions(registry, limited_agent) -> None:
    task = task_for(limited_agent.agent_id, allowed_tools=["fetch_page"])
    with pytest.raises(PermissionError, match="agent allowlist"):
        registry.active_for(limited_agent, task)

@pytest.mark.asyncio
async def test_tool_result_with_forbidden_object_scope_is_rejected(registry, task) -> None:
    task = replace(task, object_write_scopes=["BaselineFindingPacket"])
    with pytest.raises(PermissionError, match="EvidenceCard"):
        await registry.execute(create_evidence_call(), execution_context(task))
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_tool_registry.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现权限交集**

活动工具集合必须等于 `registered tools ∩ agent.tools ∩ task.allowed_tools`。执行后再次校验每个 proposal 的 `object_type` 是否在 task 与 agent 的 write scope 交集中，未通过时丢弃整个 ToolResult 并记录 `tool_permission_denied`。

- [ ] **Step 4: 运行工具 registry 测试**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_tool_registry.py -q`

Expected: PASS。

- [ ] **Step 5: 回归 Harness 权限测试**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_agent_harness.py tests/equipment_deep_research/integration/test_tool_registry.py -q`

Expected: PASS。

### Task 3: 实现 ProviderRegistry 和可编程 FakeProvider

**Files:**
- Create: `src/equipment_deep_research/providers/registry.py`
- Create: `src/equipment_deep_research/providers/fake.py`
- Delete: `src/equipment_deep_research/agents/provider.py`
- Test: `tests/equipment_deep_research/unit/test_provider_registry.py`

**Interfaces:**
- Consumes: `providers.yaml`。
- Produces: `ProviderRegistry.load()`、`create(profile_name)`；`ScriptedFakeProvider`。

- [ ] **Step 1: 写失败测试**

```python
def test_provider_registry_builds_default_gpt55_profile(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_API_KEY", "test-key")
    registry = ProviderRegistry.load(PROVIDER_CONFIG)
    provider = registry.create("responses")
    assert provider.model == "gpt-5.5"
    assert "test-key" not in repr(provider)

def test_scripted_fake_provider_can_emit_tool_then_final_text() -> None:
    provider = ScriptedFakeProvider([tool_call_message("search_sources"), text_message("done")])
    assert provider.remaining_steps == 2
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_provider_registry.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现 registry 和 fake provider**

Provider 配置对象只保存环境变量名；`create()` 时读取值。缺失真实凭据时抛出 `ProviderConfigurationError`，fake provider 不要求凭据。

- [ ] **Step 4: 运行 provider registry 测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_provider_registry.py -q`

Expected: PASS。

- [ ] **Step 5: 扫描旧 provider 引用**

Run: `rg -n "agents\.provider|FakeAgentProvider|RealAgentProvider" src/equipment_deep_research tests/equipment_deep_research`

Expected: 无结果。

### Task 4: 实现 Responses-compatible HTTP provider

**Files:**
- Create: `src/equipment_deep_research/providers/responses.py`
- Test: `tests/equipment_deep_research/unit/test_responses_provider.py`
- Fixture: `tests/equipment_deep_research/fixtures/responses_sse.txt`

**Interfaces:**
- Consumes: `ModelProvider.stream(messages, tools, options)`。
- Produces: `ResponsesProvider`、`build_request_payload()`、`parse_sse_event()`。

- [ ] **Step 1: 写失败测试固定请求格式**

```python
def test_responses_payload_uses_gpt55_and_declared_tools() -> None:
    payload = build_request_payload(
        model="gpt-5.5", messages=[user("研究主题")], tools=[search_tool],
        options={"reasoning_effort": "high", "max_output_tokens": 12000},
    )
    assert payload["model"] == "gpt-5.5"
    assert payload["tools"][0]["name"] == "search_sources"
    assert payload["reasoning"]["effort"] == "high"

def test_sse_parser_reconstructs_text_and_tool_arguments() -> None:
    events = parse_fixture("responses_sse.txt")
    message = assistant_from_events(events)
    assert message.tool_calls[0].name == "search_sources"
    assert message.tool_calls[0].arguments == {"query": "低空无人机 威胁 趋势"}
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_responses_provider.py -q`

Expected: FAIL。

- [ ] **Step 3: 实现请求、SSE 和错误映射**

支持事件：response created、output text delta、reasoning delta、function call arguments delta、completed、failed。HTTP 401 映射为 `ProviderAuthenticationError`，429/5xx 映射为可重试错误；异常消息只包含状态码、request id 和脱敏 body 摘要。

- [ ] **Step 4: 运行 provider 测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_responses_provider.py -q`

Expected: PASS。

- [ ] **Step 5: 验证源码没有外部 CLI 调用**

Run: `rg -n "subprocess|os\.system|codex exec|RUN_CODEX" src/equipment_deep_research/providers src/equipment_deep_research/harness`

Expected: 无结果。

### Task 5: 将 registry/provider 接入 runner

**Files:**
- Modify: `src/equipment_deep_research/orchestration/runner.py`
- Modify: `src/equipment_deep_research/interfaces/cli.py`
- Modify: `scripts/run_deep_research.py`
- Test: `tests/equipment_deep_research/integration/test_runner_provider_selection.py`
- Create: `docs/testing/phase-2-test-report.md`

**Interfaces:**
- Consumes: `ProviderRegistry`、`ToolRegistry`、`AgentHarness`。
- Produces: CLI `--provider fake|responses`、`--model` 覆盖；run summary provider snapshot。

- [ ] **Step 1: 写失败测试**

```python
def test_fake_mode_selects_fake_provider_and_real_selects_responses(tmp_path, monkeypatch) -> None:
    fake = runner(tmp_path).run(
        mode="fake", topic="provider测试", research_route="new_winning_mechanism", run_id="fake"
    )
    assert read_summary(fake)["provider"]["type"] == "fake"
    monkeypatch.setenv("EQUIPMENT_DR_API_KEY", "test")
    real_runner = runner(tmp_path, transport=mock_responses_transport())
    real = real_runner.run(
        mode="real", topic="provider测试", research_route="new_winning_mechanism", run_id="real"
    )
    assert read_summary(real)["provider"]["model"] == "gpt-5.5"
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_runner_provider_selection.py -q`

Expected: FAIL。

- [ ] **Step 3: 接入 provider 和 tool 构造**

runner 根据模式选择 profile，但允许 `--provider` 显式覆盖。summary 只记录 `provider type/model/base_url_host`，不记录 key 和 headers。

- [ ] **Step 4: 运行集成和全量测试**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_runner_provider_selection.py -q`

Expected: PASS。

- [ ] **Step 5: 生成 Phase 2 审查包**

Run: `python3 -m pytest -q`

Expected: 全部 PASS；报告附 mock Responses 请求摘要、工具拒绝 trace、fake smoke 产物和真实凭据缺失时的明确错误示例。
