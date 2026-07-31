# Pi Harness Python Replication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 Pi 的 AgentHarness 核心能力迁移到 Python，并交付一个可运行的需求挖掘 demo。

**Architecture:** 先复刻通用 harness kernel，再在其上装配需求挖掘领域层。低层 `AgentLoop` 只处理 LLM turn、工具调用、事件和队列；上层 `DiscoveryHarness` 负责 phase、session/trace、context pack、save point、provider 和领域写入。

**Tech Stack:** Python standard library, `dataclasses`, `asyncio`, `json`, `sqlite3` or JSONL, `unittest`; optional `requests`/`openai` for real provider adapter. Tests must not require real API keys or remote services.

---

## 1. Scope And Milestones

本计划覆盖最终迁移目标，但按可运行里程碑推进。

### Milestone A: Harness Kernel Demo

交付一个不依赖真实模型的 demo：fake provider 生成 tool call，harness 执行工具，save point 写入 trace，最后输出一份最小需求报告。

### Milestone B: Pi Harness Parity

补齐 Pi harness 的核心能力：phase 状态机、turn snapshot、steer/follow-up/next-turn queue、pending proposal queues、save point、hook、session JSONL、context projection、abort、settled event、provider stream event。

### Milestone C: Demand Discovery Runtime

接入 `CandidateDemand`、`EvidenceCard`、`SourceRecord`、`AuditReport`、领域工具、审核 agent、报告生成和可追溯 trace。

### Milestone D: Runnable Real-Provider Demo

在 fake demo 保持可复现的基础上，增加可选 real provider 模式，支持 OpenAI Responses-compatible 或 Codex backend endpoint。真实 provider demo 必须通过环境变量启用，默认不调用网络。

## 2. Proposed File Structure

```text
src/knowledgegraph/demand_discovery/
  __init__.py
  demo.py
  harness/
    __init__.py
    types.py
    event_stream.py
    events.py
    tools.py
    agent_loop.py
    agent_harness.py
    session_store.py
    trace_store.py
    context_pack.py
    scheduler.py
  llm/
    __init__.py
    types.py
    fake_provider.py
    responses_adapter.py
    model_config.py
  domain/
    __init__.py
    models.py
    store.py
    tools.py
    report.py
  workers/
    __init__.py
    roles.py
    prompts.py
scripts/
  demand_discovery_demo.py
tests/
  test_demand_discovery_event_stream.py
  test_demand_discovery_fake_provider.py
  test_demand_discovery_agent_loop.py
  test_demand_discovery_agent_harness.py
  test_demand_discovery_session_trace.py
  test_demand_discovery_context_pack.py
  test_demand_discovery_domain_tools.py
  test_demand_discovery_demo.py
```

职责边界：

- `harness/`：通用 agent runtime，不依赖军事需求领域概念。
- `llm/`：provider adapter 和 fake provider，不写领域状态。
- `domain/`：需求挖掘数据结构、领域 store、领域工具、报告生成。
- `workers/`：角色 prompt、任务 prompt 和 agent role 配置。
- `demo.py`：Python API 级 demo 编排。
- `scripts/demand_discovery_demo.py`：命令行入口，只调用 `src` 内核心能力。
- `tests/`：沿用当前仓库 `unittest` 风格，默认离线运行。

## 3. Implementation Tasks

### Task 1: Package Scaffold And Import Contract

**Files:**

- Create: `src/knowledgegraph/demand_discovery/__init__.py`
- Create: `src/knowledgegraph/demand_discovery/harness/__init__.py`
- Create: `src/knowledgegraph/demand_discovery/llm/__init__.py`
- Create: `src/knowledgegraph/demand_discovery/domain/__init__.py`
- Create: `src/knowledgegraph/demand_discovery/workers/__init__.py`
- Modify: `src/README.md`
- Test: `tests/test_demand_discovery_imports.py`

- [ ] **Step 1: Write the import test**

```python
from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class DemandDiscoveryImportTests(unittest.TestCase):
    def test_package_imports(self) -> None:
        import knowledgegraph.demand_discovery as package
        import knowledgegraph.demand_discovery.harness as harness
        import knowledgegraph.demand_discovery.llm as llm
        import knowledgegraph.demand_discovery.domain as domain
        import knowledgegraph.demand_discovery.workers as workers

        self.assertEqual(package.__all__, ["harness", "llm", "domain", "workers"])
        self.assertIn("harness", harness.__name__)
        self.assertIn("llm", llm.__name__)
        self.assertIn("domain", domain.__name__)
        self.assertIn("workers", workers.__name__)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the failing test**

Run: `python -m unittest tests.test_demand_discovery_imports -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'knowledgegraph.demand_discovery'`.

- [ ] **Step 3: Add package files**

`src/knowledgegraph/demand_discovery/__init__.py`:

```python
"""Demand discovery runtime and demo package."""

__all__ = ["harness", "llm", "domain", "workers"]
```

Each subpackage `__init__.py`:

```python
"""Subpackage for demand discovery."""
```

- [ ] **Step 4: Update `src/README.md`**

Add `src/knowledgegraph/demand_discovery` to the current structure and state that it contains the Python Pi harness replication and demand-discovery demo runtime.

- [ ] **Step 5: Run the test**

Run: `python -m unittest tests.test_demand_discovery_imports -v`

Expected: PASS.

### Task 2: Core Message, Tool, And Event Types

**Files:**

- Create: `src/knowledgegraph/demand_discovery/harness/types.py`
- Create: `src/knowledgegraph/demand_discovery/harness/events.py`
- Test: `tests/test_demand_discovery_types.py`

- [ ] **Step 1: Write type behavior tests**

```python
from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.harness.events import AgentEvent
from knowledgegraph.demand_discovery.harness.types import (
    AgentMessage,
    AssistantContentBlock,
    DomainWriteProposal,
    DomainTraceProposal,
    ToolCall,
    ToolResult,
    UserMessage,
)


class DemandDiscoveryTypesTests(unittest.TestCase):
    def test_messages_round_trip_to_dict(self) -> None:
        user = UserMessage(content="start", timestamp=1)
        assistant = AgentMessage(
            role="assistant",
            content=[AssistantContentBlock(type="text", text="hello")],
            timestamp=2,
        )

        self.assertEqual(user.to_dict()["role"], "user")
        self.assertEqual(assistant.to_dict()["content"][0]["text"], "hello")

    def test_tool_call_and_result_shape(self) -> None:
        call = ToolCall(id="call-1", name="echo", arguments={"text": "hi"})
        result = ToolResult(
            tool_call_id=call.id,
            tool_name=call.name,
            content="hi",
            details={"length": 2},
            domain_proposals=[
                DomainWriteProposal(
                    action="upsert",
                    object_type="EvidenceCard",
                    payload={"evidence_id": "ev-1"},
                )
            ],
            trace_proposals=[
                DomainTraceProposal(
                    event_type="evidence_created",
                    target_type="EvidenceCard",
                    target_id="ev-1",
                    payload_summary="created ev-1",
                    output_refs=["ev-1"],
                )
            ],
            is_error=False,
            terminate=False,
        )

        self.assertEqual(result.to_message().role, "tool_result")
        self.assertEqual(result.to_message().tool_call_id, "call-1")
        self.assertEqual(result.domain_proposals[0].object_type, "EvidenceCard")
        self.assertEqual(result.trace_proposals[0].event_type, "evidence_created")

    def test_agent_event_shape(self) -> None:
        event = AgentEvent(type="turn_start", run_id="run-1", payload={"turn": 1})

        self.assertEqual(event.type, "turn_start")
        self.assertEqual(event.payload["turn"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the failing test**

Run: `python -m unittest tests.test_demand_discovery_types -v`

Expected: FAIL because modules are not implemented.

- [ ] **Step 3: Implement dataclasses**

Implement these stable contracts:

```python
@dataclass
class AssistantContentBlock:
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)

@dataclass
class AgentMessage:
    role: str
    content: str | list[AssistantContentBlock]
    timestamp: int
    tool_call_id: str = ""
    tool_name: str = ""
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class UserMessage(AgentMessage):
    def __init__(self, content: str, timestamp: int, metadata: dict[str, Any] | None = None) -> None:
        super().__init__("user", content, timestamp, metadata=metadata or {})

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

@dataclass
class DomainWriteProposal:
    action: str
    object_type: str
    payload: dict[str, Any]

@dataclass
class DomainTraceProposal:
    event_type: str
    target_type: str
    target_id: str
    payload_summary: str
    input_refs: list[str] = field(default_factory=list)
    output_refs: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)

@dataclass
class ToolResult:
    tool_call_id: str
    tool_name: str
    content: str
    details: dict[str, Any]
    domain_proposals: list[DomainWriteProposal] = field(default_factory=list)
    trace_proposals: list[DomainTraceProposal] = field(default_factory=list)
    is_error: bool = False
    terminate: bool = False
```

`ToolResult` 使用四个明确通道：

- `content`：给模型看的短摘要，会进入 tool result message。
- `details`：程序、UI、debug 可读的结构化结果，不承载待执行写入。
- `domain_proposals`：建议写入或修改 `SourceRecord`、`EvidenceCard`、`CandidateDemand`、`AuditReport`、`DemandReport` 等领域对象，由 harness 在 save point 校验后落盘。
- `trace_proposals`：建议写入的 `DomainTraceEvent`，由 harness 在 save point 校验、关联和去重后落盘。

`AgentEvent` fields:

```python
type: str
run_id: str
payload: dict[str, Any]
agent_run_id: str = ""
timestamp: int = 0
```

Every dataclass needs `to_dict()`.

- [ ] **Step 4: Run the test**

Run: `python -m unittest tests.test_demand_discovery_types -v`

Expected: PASS.

### Task 3: Async Event Stream And Fake Provider

**Files:**

- Create: `src/knowledgegraph/demand_discovery/harness/event_stream.py`
- Create: `src/knowledgegraph/demand_discovery/llm/types.py`
- Create: `src/knowledgegraph/demand_discovery/llm/fake_provider.py`
- Test: `tests/test_demand_discovery_event_stream.py`
- Test: `tests/test_demand_discovery_fake_provider.py`

- [ ] **Step 1: Write event stream tests**

Test cases:

- `AsyncEventStream` yields events in pushed order.
- `end(result)` stops iteration and `result()` returns final value.
- `error(exc)` emits an error event and marks stream finished.

Run: `python -m unittest tests.test_demand_discovery_event_stream -v`

Expected before implementation: FAIL.

- [ ] **Step 2: Implement `AsyncEventStream`**

Required public methods:

```python
push(event: Any) -> None
end(result: Any = None) -> None
error(message: str) -> None
result() -> Any
__aiter__() -> AsyncIterator[Any]
```

Use `asyncio.Queue`; never busy-wait.

- [ ] **Step 3: Write fake provider tests**

Test cases:

- queued responses are consumed in order.
- exhausted queue returns an assistant error message.
- a response factory can inspect context and call count.
- a fake assistant message can include text and tool calls.

Run: `python -m unittest tests.test_demand_discovery_fake_provider -v`

Expected before implementation: FAIL.

- [ ] **Step 4: Implement fake provider**

Required API:

```python
class FakeProvider:
    def set_responses(self, responses: list[FakeResponse]) -> None: ...
    def append_responses(self, responses: list[FakeResponse]) -> None: ...
    def pending_count(self) -> int: ...
    def stream(self, context: LLMContext, tools: list[Any], options: dict[str, Any]) -> AsyncEventStream: ...
```

`FakeResponse` supports:

- assistant text.
- assistant content blocks with tool calls.
- callable factory `(context, state) -> AssistantMessage`.
- raised exception converted to provider error.

- [ ] **Step 5: Run tests**

Run:

```powershell
python -m unittest tests.test_demand_discovery_event_stream tests.test_demand_discovery_fake_provider -v
```

Expected: PASS.

### Task 4: Tool Registry And Tool Execution Contract

**Files:**

- Create: `src/knowledgegraph/demand_discovery/harness/tools.py`
- Test: `tests/test_demand_discovery_tools.py`

- [ ] **Step 1: Write tool registry tests**

Test cases:

- registering a tool exposes name, description, schema, execution mode.
- schema validation rejects missing required argument.
- `before_tool_call` can block execution.
- `after_tool_call` can rewrite result and set `terminate`.
- tool results keep `details`, `domain_proposals`, and `trace_proposals` separated.
- sequential tools are executed in source order.

Run: `python -m unittest tests.test_demand_discovery_tools -v`

Expected before implementation: FAIL.

- [ ] **Step 2: Implement tool contracts**

Required classes:

```python
@dataclass
class ToolExecutionContext:
    run_id: str
    agent_run_id: str
    worker_id: str
    permissions: dict[str, Any]

@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters_schema: dict[str, Any]
    execute: Callable[[ToolCall, ToolExecutionContext], Awaitable[ToolResult]]
    execution_mode: str = "parallel"
    prompt_guidelines: str = ""

class ToolRegistry:
    def register(self, tool: ToolDefinition) -> None: ...
    def get(self, name: str) -> ToolDefinition: ...
    def list_active(self, names: list[str] | None = None) -> list[ToolDefinition]: ...
```

Schema validation can start with a small JSON-schema subset: `type=object`, `required`, `properties`, primitive `string/number/boolean/object/array`. Do not add external dependencies in this task.

- [ ] **Step 3: Run tests**

Run: `python -m unittest tests.test_demand_discovery_tools -v`

Expected: PASS.

### Task 5: AgentLoop Without Harness State

**Files:**

- Create: `src/knowledgegraph/demand_discovery/harness/agent_loop.py`
- Test: `tests/test_demand_discovery_agent_loop.py`

- [ ] **Step 1: Write no-tool loop test**

Verify event order:

```text
agent_start
turn_start
message_start
message_update
message_end
turn_end
agent_end
```

Run: `python -m unittest tests.test_demand_discovery_agent_loop.DemandDiscoveryAgentLoopTests.test_no_tool_event_order -v`

Expected before implementation: FAIL.

- [ ] **Step 2: Implement minimal loop**

`AgentLoop.run()` inputs:

```python
messages: list[AgentMessage]
provider: ProviderLike
tools: list[ToolDefinition]
config: AgentLoopConfig
```

Output:

```python
AsyncEventStream[AgentEvent]
```

The loop must append the user message, stream provider events, create final assistant message, and emit lifecycle events.

- [ ] **Step 3: Write tool-call loop tests**

Test cases:

- assistant tool calls execute tools and append tool result messages.
- parallel tool execution emits `tool_execution_end` in completion order.
- tool result messages are appended in original tool call order.
- all tool results with `terminate=True` stop the loop.
- `prepare_next_turn` is called before the next provider request.

- [ ] **Step 4: Implement tool-call handling**

Match Pi semantics:

- provider tool calls are batched per assistant turn.
- all tool calls are prepared/validated before execution.
- sequential mode is forced if any called tool declares `execution_mode="sequential"`.
- tool result messages are written in original call order.
- `prepare_next_turn` can replace messages, tools, model options, or stop.

- [ ] **Step 5: Run loop tests**

Run: `python -m unittest tests.test_demand_discovery_agent_loop -v`

Expected: PASS.

### Task 6: AgentHarness Phase, Queue, Snapshot, And Save Point

**Files:**

- Create: `src/knowledgegraph/demand_discovery/harness/agent_harness.py`
- Test: `tests/test_demand_discovery_agent_harness.py`

- [ ] **Step 1: Write phase and queue tests**

Test cases:

- `prompt()` starts only when phase is `idle`.
- `steer()` can inject current-turn message.
- `follow_up()` runs after apparent stop.
- `next_turn()` is preserved for the next prompt.
- `abort()` clears steer/follow-up but preserves next-turn queue.

Run: `python -m unittest tests.test_demand_discovery_agent_harness -v`

Expected before implementation: FAIL.

- [ ] **Step 2: Implement `DiscoveryHarness`**

Required public API:

```python
class DiscoveryHarness:
    async def prompt(self, text: str) -> AgentMessage: ...
    def steer(self, text: str) -> None: ...
    def follow_up(self, text: str) -> None: ...
    def next_turn(self, text: str) -> None: ...
    def abort(self) -> None: ...
    def set_active_tools(self, names: list[str]) -> None: ...
    def subscribe(self, handler: Callable[[AgentEvent], None]) -> None: ...
```

Required internal behavior:

- `phase`: `idle`, `turn`, `compaction`, `branch_summary`, `retry`.
- `turn_snapshot`: messages, tools, active tool names, provider options, context pack.
- `pending_domain_proposals`: accepted `DomainWriteProposal` items waiting for save point validation and flush.
- `pending_trace_proposals`: accepted `DomainTraceProposal` items waiting for save point validation and flush.
- Do not implement a third aggregate core queue for these items; keep domain proposals and trace proposals as two explicit queues.
- `settled` event emitted after all listeners and pending proposal flushes complete.

- [ ] **Step 3: Write save point tests**

Verify:

- updates to active tools during a turn affect only the next provider request.
- pending domain/trace proposals are not durable before `turn_end`.
- save point emits after `turn_end`.

- [ ] **Step 4: Implement save point**

`_save_point()` must:

```python
flush_pending_domain_proposals()
flush_pending_trace_proposals()
rebuild_context_pack()
publish save_point event
```

- [ ] **Step 5: Run harness tests**

Run: `python -m unittest tests.test_demand_discovery_agent_harness -v`

Expected: PASS.

### Task 7: Append-Only Session And Domain Trace Stores

**Files:**

- Create: `src/knowledgegraph/demand_discovery/harness/session_store.py`
- Create: `src/knowledgegraph/demand_discovery/harness/trace_store.py`
- Test: `tests/test_demand_discovery_session_trace.py`

- [ ] **Step 1: Write store tests**

Test cases:

- memory session store appends entries and restores active leaf.
- JSONL session store writes header and entries.
- domain trace store appends `DomainTraceEvent` and can return report lineage.
- runtime events are not accepted as domain trace events.
- active pointer changes are append-only.

Run: `python -m unittest tests.test_demand_discovery_session_trace -v`

Expected before implementation: FAIL.

- [ ] **Step 2: Implement memory and JSONL stores**

Session entries:

```python
entry_id
parent_id
run_id
type
timestamp
payload
```

Runtime and trace boundary:

```text
RuntimeEvent:
  provider_stream | agent_runtime | harness | scheduler
  used by EventBus, UI, debug, progress, and optional sanitized runtime logs
  not used as formal report evidence

SessionEntry:
  append-only replay record for messages, save points, active pointer, model/tool changes
  not used as formal report evidence by itself

DomainTraceEvent:
  append-only domain lineage record for source/evidence/candidate/audit/report state changes
  used by report trace, source audit, human review, SOP extraction
```

Do not create separate first-version stores for `ProviderStreamEvent`, `AgentRuntimeEvent`, `HarnessEvent`, and `SchedulerEvent`. Keep them as `RuntimeEvent.category` values on the event bus; only `DomainTraceEvent` goes into `DomainTraceStore`.

Domain trace events:

```python
domain_trace_id
trace_id
event_type
actor
target_type
target_id
input_refs
output_refs
summary
decision
rationale
model
prompt_id
tool_refs
runtime_event_id
created_at
```

Do not overwrite old entries.

- [ ] **Step 3: Integrate stores into harness**

Harness writes final messages, save points, and active pointer changes to `SessionStore`. Tool lifecycle, provider deltas, queue changes, and scheduler progress remain `RuntimeEvent` records on `EventBus`. Domain lineage writes from `domain_proposals` and `trace_proposals` go through `pending_domain_proposals` / `pending_trace_proposals` and flush into `DomainStore` / `DomainTraceStore` only at save point.

- [ ] **Step 4: Run store tests**

Run: `python -m unittest tests.test_demand_discovery_session_trace -v`

Expected: PASS.

### Task 8: ContextPack Builder And Compaction Projection

**Files:**

- Create: `src/knowledgegraph/demand_discovery/harness/context_pack.py`
- Test: `tests/test_demand_discovery_context_pack.py`

- [ ] **Step 1: Write context pack tests**

Test cases:

- different agent roles receive different projections.
- evidence and candidate objects are summarized, not copied as full JSON.
- long document text is represented by artifact refs and excerpts.
- compaction summary preserves evidence ids, candidate ids, open questions, and excluded directions.

Run: `python -m unittest tests.test_demand_discovery_context_pack -v`

Expected before implementation: FAIL.

- [ ] **Step 2: Implement `ContextPackBuilder`**

Required API:

```python
build(agent_role, task_brief, run_state, token_budget) -> ContextPack
compact_trace_segment(events, policy) -> ContextSummary
```

Use approximate token counting with `ceil(len(text) / 4)` for now.

- [ ] **Step 3: Wire builder into save point**

At save point, harness rebuilds the shared context snapshot for the next provider request.

- [ ] **Step 4: Run context tests**

Run: `python -m unittest tests.test_demand_discovery_context_pack -v`

Expected: PASS.

### Task 9: Demand Discovery Domain Models And Store

**Files:**

- Create: `src/knowledgegraph/demand_discovery/domain/models.py`
- Create: `src/knowledgegraph/demand_discovery/domain/store.py`
- Test: `tests/test_demand_discovery_domain_models.py`

- [ ] **Step 1: Write domain model tests**

Verify:

- `SourceRecord`, `EvidenceCard`, `CandidateDemand`, `DomainTraceEvent`, `AuditReport`, `DemandReport` serialize to dict.
- `CandidateDemand.evidence_ids` links to existing evidence.
- candidate status can move forward and back by appending `DomainTraceEvent`.
- deleted or merged candidates are superseded, not removed.
- field names match `demand_discovery_module_discussion.md` for the four core domain objects.

Run: `python -m unittest tests.test_demand_discovery_domain_models -v`

Expected before implementation: FAIL.

- [ ] **Step 2: Implement domain dataclasses**

Minimum fields:

```python
SourceRecord:
  source_id: str
  title: str
  source_name: str
  source_tier: str
  source_type: str
  publish_time: datetime | None
  url_or_path: str
  summary_text: str | None
  summary_source: str
  collection_decision: str
  author_or_org: str | None
  is_repost: bool | None
  original_source: str | None
  institutional_stance: str | None
  created_at: datetime
  updated_at: datetime

EvidenceCard:
  evidence_id: str
  source_id: str
  claim: str
  evidence_summary: str
  excerpt: str | None
  source_location: str
  evidence_assessment: str
  created_by: str
  created_at: datetime

CandidateDemand:
  candidate_id: str
  title: str
  demand_statement: str
  status: str
  evidence_ids: list[str]
  open_questions: list[str]
  solution_signals: list[str]
  created_by: str
  created_at: datetime
  updated_at: datetime

DomainTraceEvent:
  domain_trace_id: str
  trace_id: str
  event_type: str
  actor: str
  target_type: str
  target_id: str
  input_refs: list[str]
  output_refs: list[str]
  summary: str
  decision: str | None
  rationale: str | None
  model: str | None
  prompt_id: str | None
  tool_refs: list[str]
  runtime_event_id: str | None
  created_at: datetime

AuditReport:
  audit_id: str
  candidate_id: str
  conclusion: str
  scorecard: dict[str, Any]
  comments: str
  required_rework: list[str]
  created_by: str
  created_at: datetime

DemandReport:
  report_id: str
  candidate_id: str
  title: str
  body: str
  evidence_ids: list[str]
  audit_id: str
  domain_trace_ids: list[str]
  created_at: datetime
```

The first four objects are the core schema from `demand_discovery_module_discussion.md` and must not drift in field names. `AuditReport` and `DemandReport` are implementation-layer supplement objects for review and demo output; they should reference core objects by id instead of duplicating source or evidence payloads.

- [ ] **Step 3: Implement `DomainStore`**

Start with in-memory store plus JSONL export:

```python
upsert_source(record)
upsert_evidence(card)
upsert_candidate(candidate)
append_audit(report)
append_demand_report(report)
get_candidate(candidate_id)
list_candidates(status=None)
```

- [ ] **Step 4: Run domain tests**

Run: `python -m unittest tests.test_demand_discovery_domain_models -v`

Expected: PASS.

### Task 10: Domain Tools And Pending Domain/Trace Proposals

**Files:**

- Create: `src/knowledgegraph/demand_discovery/domain/tools.py`
- Test: `tests/test_demand_discovery_domain_tools.py`

- [ ] **Step 1: Write domain tool tests**

Test cases:

- `create_evidence_card` returns model-readable summary and machine-readable details.
- `create_or_update_candidate` emits `domain_proposals` and writes only through `pending_domain_proposals` / `pending_trace_proposals`.
- domain writes are never embedded in `details`.
- trace writes are emitted through `trace_proposals`.
- invalid evidence id blocks candidate update.
- audit tool can write audit report but cannot mutate candidate body.

Run: `python -m unittest tests.test_demand_discovery_domain_tools -v`

Expected before implementation: FAIL.

- [ ] **Step 2: Implement domain tools**

Tools:

```python
create_source_record
create_evidence_card
create_or_update_candidate
merge_candidate
run_audit
generate_demand_report
```

Each tool returns:

```python
ToolResult(
  content="short model-readable summary",
  details={...},
  domain_proposals=[
    DomainWriteProposal(action="upsert", object_type="EvidenceCard", payload={...})
  ],
  trace_proposals=[
    DomainTraceProposal(
      event_type="evidence_created",
      target_type="EvidenceCard",
      target_id="ev-1",
      payload_summary="created ev-1",
      output_refs=["ev-1"],
    )
  ],
  terminate=False,
)
```

Domain writes are proposals in `domain_proposals`; trace writes are proposals in `trace_proposals`. `details` may contain generated ids, fetch metadata, truncation metadata, cache refs, hash values, and UI/debug fields, but must not contain executable domain writes. Harness validates proposals and flushes them at save point.

Domain trace proposals must be checked against the accepted domain proposal instead of inferred from free-form payloads. First-version validation table:

| Domain proposal | Required domain action | Required trace event | Required target |
|---|---|---|---|
| `SourceRecord` | `upsert` | `source_seen` or `source_updated` | `target_type=SourceRecord`, `target_id=source_id` |
| `EvidenceCard` | `upsert` | `evidence_created` or `evidence_updated` | `target_type=EvidenceCard`, `target_id=evidence_id` |
| `CandidateDemand` | `upsert` | `candidate_created` or `candidate_updated` | `target_type=CandidateDemand`, `target_id=candidate_id` |
| `CandidateDemand` | `merge` | `candidate_merged` | `target_type=CandidateDemand`, `target_id=surviving_candidate_id` |
| `AuditReport` | `append` | `audit_completed` | `target_type=AuditReport`, `target_id=audit_id` |
| `DemandReport` | `append` | `report_generated` | `target_type=DemandReport`, `target_id=report_id` |

If one tool returns multiple domain proposals, each accepted domain proposal must have a matching `DomainTraceProposal` with explicit `target_type`, `target_id`, and `event_type`. `input_refs` and `output_refs` carry source/evidence/candidate/audit/report ids needed for lineage.

- [ ] **Step 3: Wire domain write validation into harness**

Validation rules:

- evidence can exist without a candidate.
- candidate evidence ids must exist.
- audit report requires existing candidate.
- demand report requires candidate and audit report.
- status rollback requires both a domain proposal and a trace proposal.
- every accepted domain proposal emits or references a corresponding trace event.

- [ ] **Step 4: Run domain tool tests**

Run: `python -m unittest tests.test_demand_discovery_domain_tools -v`

Expected: PASS.

### Task 11: Provider Adapter For Responses-Compatible And Codex Backend

**Files:**

- Create: `src/knowledgegraph/demand_discovery/llm/model_config.py`
- Create: `src/knowledgegraph/demand_discovery/llm/responses_adapter.py`
- Test: `tests/test_demand_discovery_responses_adapter.py`

- [ ] **Step 1: Write provider contract tests**

Test cases:

- `responses_compatible` builds `/v1/responses` style payload and does not send Codex-only headers.
- `codex_backend` normalizes URL to `/codex/responses` and sets Codex headers.
- `custom_endpoint` uses exact endpoint path and configured auth header.
- SSE text delta, reasoning delta, tool-call delta, completed, failed are parsed into provider events.
- `response.completed` stops parsing even if body remains open.

Run: `python -m unittest tests.test_demand_discovery_responses_adapter -v`

Expected before implementation: FAIL.

- [ ] **Step 2: Implement model config**

Fields:

```python
provider
model
api_key_env
base_url
endpoint_mode
endpoint_path
headers
auth_header
timeout_ms
max_retries
reasoning_effort
reasoning_summary
cache_retention
text_verbosity
```

Do not store actual API keys in config objects returned to trace.

- [ ] **Step 3: Implement request builders and SSE parser**

Implement:

```python
build_responses_request(context, tools, options)
build_codex_request(context, tools, options)
parse_sse_lines(lines)
map_responses_event(raw)
```

Use mocked HTTP in tests. Real network is not required for this task.

- [ ] **Step 4: Run provider adapter tests**

Run: `python -m unittest tests.test_demand_discovery_responses_adapter -v`

Expected: PASS.

### Task 12: Runnable Fake Demo

**Files:**

- Create: `src/knowledgegraph/demand_discovery/demo.py`
- Create: `scripts/demand_discovery_demo.py`
- Test: `tests/test_demand_discovery_demo.py`
- Modify: `tests/README.md`

- [ ] **Step 1: Write demo test**

The test runs the demo in fake mode and asserts:

- exit code is 0.
- output includes a candidate demand title.
- output includes at least one evidence id.
- output includes trace event count.
- no API key or Authorization header is printed.

Run: `python -m unittest tests.test_demand_discovery_demo -v`

Expected before implementation: FAIL.

- [ ] **Step 2: Implement fake demo scenario**

Demo flow:

```text
user task brief
-> fake horizon scanner emits source signal
-> fake reader tool creates EvidenceCard
-> fake synthesizer tool creates CandidateDemand
-> fake audit tool approves candidate
-> report tool generates DemandReport
-> CLI prints report summary and trace path
```

The demo must run with:

```powershell
python scripts\demand_discovery_demo.py --mode fake
```

- [ ] **Step 3: Update `tests/README.md`**

Add the new demand discovery demo tests and state that they do not call remote services.

- [ ] **Step 4: Run demo test and CLI**

Run:

```powershell
python -m unittest tests.test_demand_discovery_demo -v
python scripts\demand_discovery_demo.py --mode fake
```

Expected: PASS and a readable local demo report summary.

### Task 13: Scheduler And Multi-Agent Context Reuse

**Files:**

- Create: `src/knowledgegraph/demand_discovery/harness/scheduler.py`
- Create: `src/knowledgegraph/demand_discovery/workers/roles.py`
- Create: `src/knowledgegraph/demand_discovery/workers/prompts.py`
- Test: `tests/test_demand_discovery_scheduler.py`

- [ ] **Step 1: Write scheduler tests**

Test cases:

- same worker class with different context pack creates different agent runs.
- orchestrator can spawn horizon scanner, reader, synthesizer, audit worker.
- shared candidate registry prevents duplicate candidate titles in one run.
- worker events are correlated by `run_id`, `agent_run_id`, `worker_id`, `parent_event_id`.

Run: `python -m unittest tests.test_demand_discovery_scheduler -v`

Expected before implementation: FAIL.

- [ ] **Step 2: Implement scheduler**

Required API:

```python
spawn_worker(role, task_brief, context_pack) -> agent_run_id
run_until_idle()
list_worker_states()
cancel_worker(agent_run_id)
```

Concurrency can start with `asyncio.gather`; stateful domain writes still pass through save point validation.

- [ ] **Step 3: Run scheduler tests**

Run: `python -m unittest tests.test_demand_discovery_scheduler -v`

Expected: PASS.

### Task 14: Real Provider Demo Mode

**Files:**

- Modify: `src/knowledgegraph/demand_discovery/demo.py`
- Modify: `scripts/demand_discovery_demo.py`
- Test: `tests/test_demand_discovery_demo.py`

- [ ] **Step 1: Add offline tests for real-mode configuration**

Tests should verify:

- `--mode real` requires `DEMAND_DISCOVERY_API_KEY` or configured env var.
- missing key fails with a clear message.
- real mode does not print the key.
- `--dry-run-provider-request` prints sanitized endpoint mode, model, and payload summary.

Run: `python -m unittest tests.test_demand_discovery_demo -v`

Expected before implementation: FAIL for new tests.

- [ ] **Step 2: Implement real-mode flags**

CLI flags:

```text
--mode fake|real
--endpoint-mode responses_compatible|codex_backend|custom_endpoint
--base-url URL
--model MODEL
--api-key-env ENV_NAME
--dry-run-provider-request
```

Default mode remains `fake`.

- [ ] **Step 3: Run offline tests**

Run: `python -m unittest tests.test_demand_discovery_demo -v`

Expected: PASS.

- [ ] **Step 4: Manual real-provider smoke test**

Only run when user explicitly supplies environment configuration.

Run:

```powershell
$env:DEMAND_DISCOVERY_API_KEY="<redacted>"
python scripts\demand_discovery_demo.py --mode real --endpoint-mode responses_compatible --base-url "<url>" --model "<model>"
```

Expected: one demand report summary, trace event count, no secret printed.

### Task 15: Documentation And Execution Guide

**Files:**

- Modify: `docs/README.md`
- Modify: `src/README.md`
- Modify: `tests/README.md`
- Create: `docs/architecture/pi_harness_python_replication_runtime_design.md`

- [ ] **Step 1: Write runtime design doc**

Document:

- module boundaries.
- how Pi concepts map to Python.
- fake demo execution.
- optional real provider execution.
- trace and report output locations.
- what is not migrated from Pi.

- [ ] **Step 2: Update indexes**

Add runtime design doc to `docs/README.md`; ensure `src/README.md` and `tests/README.md` mention the new package and tests.

- [ ] **Step 3: Run documentation checks**

Run:

```powershell
rg -n "pi_harness_python_replication_runtime_design|demand_discovery_demo|knowledgegraph.demand_discovery" docs src tests
```

Expected: relevant references exist.

### Task 16: Final Verification Gate

**Files:**

- No new files.

- [ ] **Step 1: Run all demand discovery tests**

Run:

```powershell
python -m unittest `
  tests.test_demand_discovery_imports `
  tests.test_demand_discovery_types `
  tests.test_demand_discovery_event_stream `
  tests.test_demand_discovery_fake_provider `
  tests.test_demand_discovery_tools `
  tests.test_demand_discovery_agent_loop `
  tests.test_demand_discovery_agent_harness `
  tests.test_demand_discovery_session_trace `
  tests.test_demand_discovery_context_pack `
  tests.test_demand_discovery_domain_models `
  tests.test_demand_discovery_domain_tools `
  tests.test_demand_discovery_responses_adapter `
  tests.test_demand_discovery_demo `
  tests.test_demand_discovery_scheduler `
  -v
```

Expected: PASS.

- [ ] **Step 2: Run the fake demo**

Run:

```powershell
python scripts\demand_discovery_demo.py --mode fake
```

Expected:

- report title.
- candidate id.
- evidence ids.
- audit conclusion.
- trace event count.
- no API key, Authorization header, full prompt, or long source body printed.

- [ ] **Step 3: Run targeted existing package import test**

Run:

```powershell
python -m unittest tests.test_src_extraction_package -v
```

Expected: PASS, proving the new package did not break existing `src/knowledgegraph` imports.

## 4. Demo Acceptance Criteria

The migrated demo is acceptable when:

- `python scripts\demand_discovery_demo.py --mode fake` runs without network, without API key, and prints a readable report summary.
- The fake demo exercises provider stream, tool call, domain write, save point, audit, report generation, and trace lineage.
- `DomainTraceStore.get_report_trace(report_id)` can reconstruct source -> evidence -> candidate -> audit -> report without relying on runtime/UI events.
- The harness has phase, snapshot, queue, pending proposal queues, save point, hook, session, trace, context pack, fake provider, and provider adapter seams.
- Real provider mode is optional, environment-driven, and sanitized.
- Tests cover the core Pi harness behaviors before real provider work is considered complete.

## 5. Self-Review

Spec coverage:

- Agent loop / harness parity is covered by Tasks 5 and 6.
- Session / context parity is covered by Tasks 7 and 8.
- Tools / sandbox / network boundary is covered by Tasks 4, 10, 11, and 14.
- Event / trace / stream is covered by Tasks 2, 3, 6, and 7.
- Provider / model adapter is covered by Tasks 3, 11, and 14.
- Tests and runnable demo are covered by Tasks 12 and 16.

Scope decision:

- This plan intentionally delivers fake demo before real provider mode. That keeps the harness behavior testable without API keys and avoids making network instability block kernel migration.
- Full Pi UI/TUI, npm/bun release workflow, coding tools, shell/file mutation tools, and provider full matrix are excluded from this implementation plan.
