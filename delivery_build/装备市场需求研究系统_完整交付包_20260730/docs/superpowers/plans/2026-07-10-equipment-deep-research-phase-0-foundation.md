# Phase 0 基线整改与稳定契约实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 校正现有骨架与最终方案的偏差，建立后续阶段共同依赖的领域契约、配置边界、CLI 和运行目录规范。

**Architecture:** 保留现有 `DeepResearchRunner` 可运行闭环，先通过兼容扩展稳定对象字段和配置。移除来源白名单硬门控，保留网络安全边界；真实模型执行仍在 Phase 2 接入。

**Tech Stack:** Python dataclasses、PyYAML、argparse、pytest。

## Global Constraints

- 默认模型为 `gpt-5.5`。
- 不改变七类既有运行产物名称。
- 默认四类 agent 可配置，不在 runner 中按 agent_id 分支。
- 公开来源不按域名白名单阻断。
- 本阶段结束时现有 fake E2E 必须继续通过。
- 所有跨进程领域对象必须可 JSON 序列化，并包含稳定 id、UTC ISO 时间和 `schema_version`，为 Phase 8 API 与 Phase 9 Web 提供兼容基础。

---

### Task 1: 锁定领域消息与计划图契约

**Files:**
- Create: `src/equipment_deep_research/domain/messages.py`
- Create: `src/equipment_deep_research/domain/planning.py`
- Modify: `src/equipment_deep_research/domain/models.py`
- Test: `tests/equipment_deep_research/unit/test_domain_contracts.py`

**Interfaces:**
- Consumes: 现有 `BaselineFindingPacket`、`RecallRequest`、`CapabilityImageItem`。
- Produces: `TaskEnvelope.validate()`、`RecallEnvelope.target_key()`、`ResearchPlanNode.validate()`、`ResearchPlanGraph.ready_nodes()`。

- [ ] **Step 1: 写失败测试，固定任务信封和计划图行为**

```python
def test_task_envelope_requires_one_target() -> None:
    task = TaskEnvelope(
        task_id="task-1", run_id="run-1", round_index=1,
        parent_task_id=None, target_agent_id="",
        target_capability_tags=[], objective="研究威胁",
        research_questions=["潜在威胁是什么？"], context_refs=[],
        evidence_refs=[], allowed_tools=["search_sources"],
        object_read_scopes=["ResearchProblem"],
        object_write_scopes=["BaselineFindingPacket"],
        budget={"max_turns": 8}, return_contract="BaselineFindingPacket",
        return_node="baseline_reduce",
    )
    with pytest.raises(ValueError, match="target"):
        task.validate()

def test_plan_graph_returns_only_dependency_ready_nodes() -> None:
    graph = ResearchPlanGraph(nodes=[
        ResearchPlanNode("n1", "baseline", [], "pending", "international_situation", ["threat"]),
        ResearchPlanNode("n2", "reduce", ["n1"], "pending", "orchestrator", ["threat"]),
    ])
    assert [node.node_id for node in graph.ready_nodes()] == ["n1"]
```

- [ ] **Step 2: 运行测试并确认因模块不存在而失败**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_domain_contracts.py -q`

Expected: FAIL，提示无法导入 `equipment_deep_research.domain.messages`。

- [ ] **Step 3: 实现稳定契约**

```python
@dataclass(frozen=True)
class TaskEnvelope:
    task_id: str
    run_id: str
    round_index: int
    parent_task_id: str | None
    target_agent_id: str
    target_capability_tags: list[str]
    objective: str
    research_questions: list[str]
    context_refs: list[str]
    evidence_refs: list[str]
    allowed_tools: list[str]
    object_read_scopes: list[str]
    object_write_scopes: list[str]
    budget: dict[str, int]
    return_contract: str
    return_node: str

    schema_version: str = "1.0"

    def validate(self) -> None:
        if not self.target_agent_id and not self.target_capability_tags:
            raise ValueError("task requires target agent or capability target")
        if not self.objective.strip() or not self.return_contract.strip():
            raise ValueError("task objective and return contract are required")

@dataclass(frozen=True)
class ResearchPlanNode:
    node_id: str
    node_type: str
    depends_on: list[str]
    status: str
    target_agent_id: str
    capability_tags: list[str]
```

同时把 `BaselineFindingPacket` 扩展为可选 `claim_ids`、`search_log`、`limitations` 字段，默认空列表，保持旧调用兼容。

- [ ] **Step 4: 运行领域契约测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_domain_contracts.py -q`

Expected: PASS。

- [ ] **Step 5: 记录任务检查点**

Run: `python3 -m pytest tests/test_deep_research_runner.py -q`

Expected: 现有 8 个测试全部通过；在阶段报告记录新增契约名称与兼容字段。

### Task 2: 统一模型、provider、工具和证据配置

**Files:**
- Modify: `configs/equipment_deep_research/agents.yaml`
- Create: `configs/equipment_deep_research/providers.yaml`
- Create: `configs/equipment_deep_research/tools.yaml`
- Create: `configs/equipment_deep_research/evidence.yaml`
- Delete: `configs/equipment_deep_research/source_whitelist.yaml`
- Modify: `src/equipment_deep_research/agents/registry.py`
- Test: `tests/equipment_deep_research/unit/test_configuration.py`

**Interfaces:**
- Consumes: `AgentRegistry.load(path)`。
- Produces: 默认模型 `gpt-5.5`；证据阈值和搜索 provider 的结构化配置。

- [ ] **Step 1: 写配置失败测试**

```python
def test_default_model_and_agent_policies() -> None:
    registry = AgentRegistry.load(ROOT / "configs/equipment_deep_research/agents.yaml")
    assert registry.default_model == "gpt-5.5"
    for agent in registry.enabled_baseline_agents():
        assert agent.tools
        assert agent.context_policy["hide_other_agent_raw_sessions"] is True
        assert agent.object_read_scopes
        assert agent.object_write_scopes == ["EvidenceCard", "BaselineFindingPacket", "WorkingCheckpoint"]

def test_evidence_policy_uses_quality_threshold_not_domains() -> None:
    policy = yaml.safe_load((ROOT / "configs/equipment_deep_research/evidence.yaml").read_text())
    assert policy["acceptance"]["min_quality_score"] == 0.62
    assert "allowed_domains" not in json.dumps(policy)
```

- [ ] **Step 2: 运行并确认旧模型和缺失配置导致失败**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_configuration.py -q`

Expected: FAIL，显示模型值不符、`evidence.yaml` 不存在或 scope 缺失。

- [ ] **Step 3: 写入精确配置**

`evidence.yaml` 至少包含：

```yaml
acceptance:
  min_quality_score: 0.62
  min_direct_support: 0.55
  min_independent_sources_for_high_confidence: 2
weights:
  relevance: 0.30
  transparency: 0.15
  freshness: 0.15
  direct_support: 0.25
  extraction_quality: 0.15
deduplication:
  normalized_url: true
  content_similarity_threshold: 0.88
contradiction:
  preserve_counter_evidence: true
network_safety:
  allowed_schemes: [http, https]
  deny_private_networks: true
  max_response_bytes: 5242880
  max_redirects: 5
```

`providers.yaml` 默认项：

```yaml
default_provider: responses
providers:
  responses:
    type: responses_http
    model: gpt-5.5
    base_url_env: EQUIPMENT_DR_BASE_URL
    api_key_env: EQUIPMENT_DR_API_KEY
    timeout_seconds: 120
  fake:
    type: fake
```

- [ ] **Step 4: 运行配置测试**

Run: `python3 -m pytest tests/equipment_deep_research/unit/test_configuration.py -q`

Expected: PASS。

- [ ] **Step 5: 扫描旧配置残留**

Run: `rg -n "gpt-5.6-sol|source_whitelist|allowed_domains|blocked_unapproved_source" src/equipment_deep_research scripts configs/equipment_deep_research tests/equipment_deep_research`

Expected: 无结果。

### Task 3: 调整 CLI 与运行工作区规范

**Files:**
- Modify: `src/equipment_deep_research/interfaces/cli.py`
- Modify: `src/equipment_deep_research/orchestration/runner.py`
- Create: `src/equipment_deep_research/domain/workspace.py`
- Test: `tests/equipment_deep_research/integration/test_cli_workspace.py`

**Interfaces:**
- Consumes: `DeepResearchRunner.run(mode, topic, research_route, run_id, agent_ids, max_rounds)`。
- Produces: `RunWorkspace.create(output_root, run_id)`；CLI 参数 `--provider-config`、`--evidence-config`、`--resume`、`--analyst-confirmed`。

- [ ] **Step 1: 写失败测试**

```python
def test_workspace_creates_required_directories(tmp_path: Path) -> None:
    ws = RunWorkspace.create(tmp_path, "run-1")
    assert ws.run_dir == tmp_path / "run-1"
    assert ws.sessions_dir.is_dir()
    assert ws.artifacts_dir.is_dir()
    assert ws.checkpoints_dir.is_dir()

def test_cli_no_longer_exposes_source_whitelist() -> None:
    parser_text = Path("src/equipment_deep_research/interfaces/cli.py").read_text()
    assert "--source-whitelist" not in parser_text
    assert "--resume" in parser_text
```

- [ ] **Step 2: 运行并确认失败**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_cli_workspace.py -q`

Expected: FAIL，提示 `RunWorkspace` 或新参数不存在。

- [ ] **Step 3: 实现工作区和参数传递**

```python
@dataclass(frozen=True)
class RunWorkspace:
    run_dir: Path
    sessions_dir: Path
    artifacts_dir: Path
    checkpoints_dir: Path
    database_path: Path

    @classmethod
    def create(cls, output_root: Path, run_id: str) -> "RunWorkspace":
        run_dir = output_root / run_id
        sessions = run_dir / "agent_sessions"
        artifacts = run_dir / "artifacts"
        checkpoints = run_dir / "checkpoints"
        for path in (run_dir, sessions, artifacts, checkpoints):
            path.mkdir(parents=True, exist_ok=True)
        return cls(run_dir, sessions, artifacts, checkpoints, run_dir / "run.db")
```

runner 暂时接受但不执行 `resume`，当为 `True` 时明确抛出 `NotImplementedError("resume is enabled in Phase 1")`，避免静默忽略。

- [ ] **Step 4: 运行 CLI 工作区测试与现有 E2E**

Run: `python3 -m pytest tests/equipment_deep_research/integration/test_cli_workspace.py tests/test_deep_research_runner.py -q`

Expected: PASS。

- [ ] **Step 5: 执行 fake 回归**

Run: `python3 scripts/run_deep_research.py --mode fake --topic "低空无人机探测预警能力缺口" --research-route auto --run-id phase-0-smoke`

Expected: 命令退出码 0，运行目录包含七类规定产物及 `checkpoints/`。

### Task 4: 同步现有文档和测试基线

**Files:**
- Modify: `README.md`
- Modify: `docs/TECHNICAL_SCHEME.md`
- Modify: `docs/ACCEPTANCE.md`
- Modify: `tests/test_deep_research_runner.py`
- Create: `docs/testing/phase-0-test-report.md`

**Interfaces:**
- Consumes: Phase 0 配置和 CLI。
- Produces: 无矛盾的运行说明与 Phase 0 审查包。

- [ ] **Step 1: 修改旧测试断言**

将白名单阻断测试替换为“任意公共域名可进入抓取流程，但失败材料不得成为正式证据”的测试：

```python
def test_public_source_is_quality_gated_not_domain_blocked(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(provider, "_public_smoke_url_for_agent", lambda _: "https://example.com/research")
    result = _runner(tmp_path).run(
        mode="real", topic="测试", research_route="new_winning_mechanism",
        run_id="quality-gate", agent_ids=["international_situation"],
    )
    summary = json.loads(Path(result["summary_path"]).read_text())
    assert summary["source_materials"][0]["status"] != "blocked_unapproved_source"
```

- [ ] **Step 2: 更新 README、技术方案和验收说明**

文档必须明确：默认模型、公开网络广泛搜集、强质量过滤、当前 Phase 0 仍使用占位 real provider、真实 provider 在后续阶段接入。

- [ ] **Step 3: 运行全量测试**

Run: `python3 -m pytest -q`

Expected: 全部 PASS。

- [ ] **Step 4: 执行一致性扫描**

Run: `rg -n "gpt-5.6-sol|source_whitelist|blocked_unapproved_source|白名单外来源" README.md docs/TECHNICAL_SCHEME.md docs/ACCEPTANCE.md src/equipment_deep_research scripts configs/equipment_deep_research tests`

Expected: 无结果。

- [ ] **Step 5: 写 Phase 0 测试报告**

报告固定包含：变更文件、测试命令与结果、`phase-0-smoke` 产物清单、已知限制“真实模型循环和真实搜索尚未接入”、Phase 1 进入条件。
