"""In-process multi-agent scheduler for demand discovery workers.

Each worker is an isolated ``DiscoveryHarness`` with its own session file and
context projection. Workers share the same in-memory ``DomainStore`` and
``DomainTraceStore``; because this scheduler runs in one event loop, save point
flushes are synchronous and do not need locks. If this ever becomes
multi-process, the shared store boundary must move to SQLite or another
transactional backend.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from knowledgegraph.demand_discovery.domain.dedup import (
    NEAR_DUP_THRESHOLD,
    similarity,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore
from knowledgegraph.demand_discovery.harness.agent_harness import DiscoveryHarness
from knowledgegraph.demand_discovery.harness.budget import RunBudget
from knowledgegraph.demand_discovery.harness.cancellation import CancelToken
from knowledgegraph.demand_discovery.harness.context_pack import (
    ContextPack,
    ContextPackBuilder,
)
from knowledgegraph.demand_discovery.harness.event_bus import (
    EventBus,
    ProgressWriter,
    RuntimeEvent,
    runtime_event_from_agent,
)
from knowledgegraph.demand_discovery.harness.events import AgentEvent
from knowledgegraph.demand_discovery.harness.model_prompt import (
    DemandDiscoveryPromptBuilder,
    ModelPrompt,
)
from knowledgegraph.demand_discovery.harness.session_store import JsonlSessionStore
from knowledgegraph.demand_discovery.harness.tools import BeforeToolCall, ToolDefinition
from knowledgegraph.demand_discovery.harness.trace_store import DomainTraceStore
from knowledgegraph.demand_discovery.harness.worker_report import (
    WorkerReport,
    build_worker_report,
    normalize_worker_report_evidence_policy,
    snapshot_store,
)
from knowledgegraph.demand_discovery.harness.worker_stop_policy import (
    WorkerStopPolicy,
    WorkerStopPolicyConfig,
)
from knowledgegraph.demand_discovery.domain.models import DomainTraceEvent


@dataclass
class WorkerSpec:
    role: str
    task_brief: str
    tools: list[str]
    budget: RunBudget
    context_pack: ContextPack
    system_prompt: str = ""
    assignment_id: str = ""
    source_id: str = ""
    source_guidance: dict[str, Any] = field(default_factory=dict)


@dataclass
class WorkerState:
    run_id: str
    agent_run_id: str
    worker_id: str
    role: str
    task_brief: str
    context_pack: ContextPack
    status: str = "pending"
    parent_event_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "agent_run_id": self.agent_run_id,
            "worker_id": self.worker_id,
            "role": self.role,
            "task_brief": self.task_brief,
            "context_pack": self.context_pack.to_dict(),
            "status": self.status,
            "parent_event_id": self.parent_event_id,
        }


@dataclass
class WorkerRuntime:
    spec: WorkerSpec
    state: WorkerState
    cancel_token: CancelToken
    session_path: Path
    report: WorkerReport | None = None
    stop_policy: WorkerStopPolicy | None = None


ProviderFactory = Callable[[WorkerSpec], Any]
ToolRegistryFactory = Callable[[WorkerSpec], list[ToolDefinition]]
BeforeToolCallFactory = Callable[[WorkerSpec], BeforeToolCall | None]


class DiscoveryScheduler:
    """Runs worker specs as child harnesses with bounded concurrency."""

    def __init__(
        self,
        run_id: str,
        *,
        provider_factory: ProviderFactory | None = None,
        tool_registry_factory: ToolRegistryFactory | None = None,
        domain_store: DomainStore | None = None,
        trace_store: DomainTraceStore | None = None,
        sessions_dir: str | Path | None = None,
        cancel_token: CancelToken | None = None,
        max_concurrency: int = 4,
        event_bus: EventBus | None = None,
        progress_writer: ProgressWriter | None = None,
        before_tool_call_factory: BeforeToolCallFactory | None = None,
        max_worker_follow_ups_per_assignment: int = 2,
    ) -> None:
        self.run_id = run_id
        self.provider_factory = provider_factory or _missing_provider_factory
        self.tool_registry_factory = tool_registry_factory or (lambda spec: [])
        self.domain_store = domain_store or DomainStore()
        self.trace_store = trace_store or DomainTraceStore()
        self.sessions_dir = Path(sessions_dir or Path("outputs") / "runs" / run_id / "workers")
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.cancel_token = cancel_token or CancelToken()
        self.max_concurrency = max(1, max_concurrency)
        self.event_bus = event_bus
        self.progress_writer = progress_writer
        self.before_tool_call_factory = before_tool_call_factory or (lambda spec: None)
        self.max_worker_follow_ups_per_assignment = max_worker_follow_ups_per_assignment

        self._states: dict[str, WorkerState] = {}
        self._runtimes: dict[str, WorkerRuntime] = {}
        self._brief_to_run: dict[str, str] = {}
        self._recent_events: list[RuntimeEvent] = []
        self.events: list[AgentEvent] = []

    async def spawn_worker(
        self,
        spec: WorkerSpec,
        parent_event_id: str = "",
        parent_cancel_token: CancelToken | None = None,
    ) -> str:
        duplicate = self._duplicate_worker(spec)
        if duplicate:
            state = self._states[duplicate]
            self._emit("worker_dedup_skipped", state, {"duplicate_of": duplicate})
            return duplicate

        agent_run_id = f"agent-{uuid4().hex}"
        state = WorkerState(
            run_id=self.run_id,
            agent_run_id=agent_run_id,
            worker_id=spec.role,
            role=spec.role,
            task_brief=spec.task_brief,
            context_pack=spec.context_pack,
            parent_event_id=parent_event_id,
        )
        token_parent = parent_cancel_token or self.cancel_token
        runtime = WorkerRuntime(
            spec=spec,
            state=state,
            cancel_token=token_parent.derive(),
            session_path=self.sessions_dir / f"{agent_run_id}.jsonl",
        )
        self._states[agent_run_id] = state
        self._runtimes[agent_run_id] = runtime
        self._brief_to_run[_normalize_brief(spec.role, spec.task_brief)] = agent_run_id
        self._emit("worker_spawned", state)
        return agent_run_id

    async def run_workers(
        self,
        specs: list[WorkerSpec],
        *,
        parent_event_id: str = "",
        parent_cancel_token: CancelToken | None = None,
    ) -> list[WorkerReport]:
        agent_ids = [
            await self.spawn_worker(
                spec,
                parent_event_id=parent_event_id,
                parent_cancel_token=parent_cancel_token,
            )
            for spec in specs
        ]
        await self.run_until_idle()
        return [self._runtimes[agent_id].report for agent_id in agent_ids if self._runtimes[agent_id].report is not None]

    async def run_until_idle(self) -> list[WorkerReport]:
        pending = [
            runtime
            for runtime in self._runtimes.values()
            if runtime.state.status == "pending"
        ]
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def run_one(runtime: WorkerRuntime) -> WorkerReport:
            async with semaphore:
                return await self._run_runtime(runtime)

        reports = await asyncio.gather(
            *(run_one(runtime) for runtime in pending),
            return_exceptions=False,
        )
        return list(reports)

    async def cancel_worker(self, agent_run_id: str) -> None:
        runtime = self._runtimes[agent_run_id]
        runtime.cancel_token.cancel("worker_cancelled")
        if runtime.state.status == "pending":
            runtime.state.status = "cancelled"
            self._emit("worker_cancelled", runtime.state)

    async def cancel_all(self) -> None:
        for agent_run_id in list(self._runtimes):
            await self.cancel_worker(agent_run_id)

    def list_worker_states(self) -> list[WorkerState]:
        return list(self._states.values())

    async def _run_runtime(self, runtime: WorkerRuntime) -> WorkerReport:
        state = runtime.state
        before = snapshot_store(self.domain_store)
        final_message = None
        error = ""
        if state.status == "cancelled":
            report = self._report(runtime, "cancelled", before, final_message, "")
            runtime.report = report
            return report

        state.status = "running"
        self._emit("worker_started", state)

        try:
            provider = self.provider_factory(runtime.spec)
            tools = _filter_tools(
                self.tool_registry_factory(runtime.spec),
                runtime.spec.tools,
            )
            model_prompt = _model_prompt_for_worker(runtime.spec, tools=tools)
            session_store = JsonlSessionStore(
                runtime.session_path,
                run_id=self.run_id,
            )
            stop_policy = self._make_stop_policy(runtime)
            runtime.stop_policy = stop_policy
            harness = DiscoveryHarness(
                provider=provider,
                tools=tools,
                session_store=session_store,
                trace_store=self.trace_store,
                domain_store=self.domain_store,
                context_builder=ContextPackBuilder(),
                run_id=self.run_id,
                agent_run_id=state.agent_run_id,
                worker_id=state.role,
                budget=runtime.spec.budget,
                cancel_token=runtime.cancel_token,
                system_prompt=runtime.spec.system_prompt or model_prompt.base_instructions,
                parent_event_id=state.parent_event_id,
                before_tool_call=self.before_tool_call_factory(runtime.spec),
                apparent_stop_follow_up_policy=(
                    stop_policy.apparent_stop_follow_up_policy
                    if stop_policy is not None
                    else None
                ),
                model_options=_model_options_from_prompt(model_prompt),
            )
            harness.subscribe(
                lambda event: self._handle_child_event(event, state.parent_event_id)
            )
            final_message = await harness.prompt(model_prompt.render_input())
            if runtime.cancel_token.cancelled or harness.last_run_aborted:
                state.status = "cancelled"
            elif final_message.is_error:
                state.status = "failed"
                error = str(final_message.metadata.get("error_message", "worker failed"))
            else:
                state.status = "completed"
        except Exception as exc:
            state.status = "failed"
            error = str(exc)

        report = self._report(runtime, state.status, before, final_message, error)
        runtime.report = report
        self._emit(f"worker_{state.status}", state, {"error": error} if error else None)
        return report

    def _report(
        self,
        runtime: WorkerRuntime,
        status: str,
        before,
        final_message,
        error: str,
    ) -> WorkerReport:
        report = build_worker_report(
            agent_run_id=runtime.state.agent_run_id,
            role=runtime.state.role,
            task_brief=runtime.state.task_brief,
            status=status,
            before=before,
            after_store=self.domain_store,
            final_message=final_message,
            budget=runtime.spec.budget,
            session_path=str(runtime.session_path),
            error=error,
        )
        if runtime.stop_policy is not None:
            assignment_id = runtime.spec.assignment_id or runtime.state.agent_run_id
            report.assignment_id = assignment_id
            report.source_id = runtime.spec.source_id
            checks = [
                check
                for check in self.domain_store.worker_self_checks.values()
                if check.assignment_id == assignment_id
            ]
            if checks:
                report.self_check = checks[-1]
                report.queries_used = list(checks[-1].queries_used)
                report.routes_used = list(checks[-1].routes_used)
            report.follow_up_instructions = list(
                runtime.stop_policy.follow_up_instruction_ids
            )
            report.follow_up_attempt_count = runtime.stop_policy.follow_up_attempt_count
            report = normalize_worker_report_evidence_policy(report)
        self._append_worker_report_trace(runtime, report)
        return report

    def _make_stop_policy(self, runtime: WorkerRuntime) -> WorkerStopPolicy | None:
        spec = runtime.spec
        if not (spec.assignment_id or spec.source_id or spec.source_guidance):
            return None
        assignment_id = spec.assignment_id or runtime.state.agent_run_id
        return WorkerStopPolicy(
            store=self.domain_store,
            config=WorkerStopPolicyConfig(
                run_id=self.run_id,
                round_id=str(spec.source_guidance.get("round_id", "")),
                assignment_id=assignment_id,
                source_id=spec.source_id,
                target_source_id=spec.source_id,
                query_revisions=[
                    {"language": "auto", "query": str(query)}
                    for query in spec.source_guidance.get("planned_queries", [])
                ],
                route_revisions=[
                    str(item) for item in spec.source_guidance.get("route_hints", [])
                ],
                allowed_tools=list(spec.tools),
                max_follow_ups_per_assignment=self.max_worker_follow_ups_per_assignment,
            ),
        )

    def _append_worker_report_trace(
        self,
        runtime: WorkerRuntime,
        report: WorkerReport,
    ) -> None:
        self.domain_store.append_trace(
            DomainTraceEvent(
                domain_trace_id=f"dt-{uuid4().hex}",
                trace_id=self.run_id,
                event_type="worker_report_finalized",
                actor="scheduler",
                target_type="WorkerReport",
                target_id=report.report_id or runtime.state.agent_run_id,
                input_refs=[
                    *report.evidence_refs,
                    *report.lead_refs,
                    *(report.follow_up_instructions or []),
                ],
                output_refs=[report.report_id or runtime.state.agent_run_id],
                summary=f"worker report finalized for {runtime.state.role}",
                decision=report.status,
                rationale=report.blocked_reason or report.error,
                model=None,
                prompt_id=None,
                tool_refs=[],
                runtime_event_id=None,
                created_at=datetime.now(timezone.utc),
            )
        )

    def _handle_child_event(self, event: AgentEvent, parent_event_id: str) -> None:
        self.events.append(event)
        if self.event_bus is not None:
            runtime_event = self.event_bus.publish(
                runtime_event_from_agent(
                    event,
                    category="agent_runtime",
                    parent_event_id=parent_event_id,
                )
            )
            self._recent_events.append(runtime_event)
        self._write_progress()

    def _emit(
        self,
        event_type: str,
        state: WorkerState,
        extra_payload: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "worker_id": state.worker_id,
            "role": state.role,
            "status": state.status,
            "task_brief": state.task_brief,
            "parent_event_id": state.parent_event_id,
        }
        if extra_payload:
            payload.update(extra_payload)
        event = AgentEvent(
            type=event_type,
            run_id=self.run_id,
            agent_run_id=state.agent_run_id,
            payload=payload,
        )
        self.events.append(event)
        if self.event_bus is not None:
            runtime_event = self.event_bus.publish(
                RuntimeEvent(
                    category="scheduler",
                    event_type=event_type,
                    run_id=self.run_id,
                    agent_run_id=state.agent_run_id,
                    parent_event_id=state.parent_event_id,
                    payload=payload,
                )
            )
            self._recent_events.append(runtime_event)
        self._write_progress()

    def _write_progress(self) -> None:
        if self.progress_writer is None:
            return
        self.progress_writer.write(
            run_id=self.run_id,
            task_brief="multi-agent worker batch",
            worker_states=self.list_worker_states(),
            domain_store=self.domain_store,
            recent_events=self._recent_events[-20:],
        )

    def _duplicate_worker(self, spec: WorkerSpec) -> str:
        key = _normalize_brief(spec.role, spec.task_brief)
        exact = self._brief_to_run.get(key, "")
        if exact:
            return exact
        normalized_brief = _normalize_brief("", spec.task_brief)
        if len(normalized_brief) < 8:
            return ""
        for existing_key, agent_run_id in self._brief_to_run.items():
            existing_brief = _normalize_brief(
                "",
                self._states[agent_run_id].task_brief,
            )
            if len(existing_brief) < 8:
                continue
            if similarity(normalized_brief, existing_brief) >= NEAR_DUP_THRESHOLD:
                return agent_run_id
        return ""


def _filter_tools(
    tools: list[ToolDefinition],
    active_names: list[str],
) -> list[ToolDefinition]:
    if not active_names:
        return list(tools)
    active = set(active_names)
    return [tool for tool in tools if tool.name in active]


def _worker_prompt(spec: WorkerSpec) -> str:
    return _model_prompt_for_worker(spec).render_input()


def _model_prompt_for_worker(
    spec: WorkerSpec,
    tools: list[ToolDefinition] | None = None,
) -> ModelPrompt:
    return DemandDiscoveryPromptBuilder().build(
        spec.context_pack,
        turn_objective=spec.task_brief,
        tools=list(tools or []),
        hard_prohibitions=_hard_prohibitions_for_role(spec.role),
        authorized_scope={
            "assignment_id": spec.assignment_id,
            "source_id": spec.source_id,
            "source_guidance": dict(spec.source_guidance),
        },
        output_schema=_output_schema_for_role(spec.role),
        parallel_tool_calls=False,
    )


def _model_options_from_prompt(prompt: ModelPrompt) -> dict[str, Any]:
    options: dict[str, Any] = {"parallel_tool_calls": prompt.parallel_tool_calls}
    if prompt.output_schema is not None:
        options["output_schema"] = dict(prompt.output_schema)
        name = str(
            prompt.output_schema.get("title")
            or prompt.output_schema.get("name")
            or "demand_discovery_worker_output"
        )
        options["output_schema_name"] = _schema_name(name)
    return options


def _hard_prohibitions_for_role(role: str) -> list[str]:
    if role == "auditor":
        return [
            "必须先读取 audit_context，再通过 run_audit 写入审计结论",
            "不得把 listing/search/site_home/access_status 页面证据标为 direct 或 used_for_core",
            "watchlist 必须写入 recommended_report_status、status_reason 和 recheck_conditions",
        ]
    return [
        "不得从搜索摘要、listing/search/site_home 页面创建 EvidenceCard",
        "没有正文 artifact/source_location 的 strong finding 必须降级",
    ]


def _output_schema_for_role(role: str) -> dict[str, Any]:
    if role == "auditor":
        return _audit_output_schema()
    return _worker_report_output_schema()


def _schema_name(name: str) -> str:
    normalized = "".join(ch if ch.isalnum() else "_" for ch in name.strip().lower())
    normalized = "_".join(part for part in normalized.split("_") if part)
    return normalized or "demand_discovery_worker_output"


def _worker_report_output_schema() -> dict[str, Any]:
    return {
        "title": "demand_discovery_worker_report",
        "type": "object",
        "required": ["findings", "open_questions", "risks", "need_more_sources"],
        "properties": {
            "findings": {"type": "array", "items": {"type": "string"}},
            "open_questions": {"type": "array", "items": {"type": "string"}},
            "risks": {"type": "array", "items": {"type": "string"}},
            "need_more_sources": {"type": "boolean"},
            "discarded_findings": {"type": "array", "items": {"type": "string"}},
            "remaining_blind_spots": {"type": "array", "items": {"type": "string"}},
        },
    }


def _audit_output_schema() -> dict[str, Any]:
    evidence_review_schema = {
        "type": "object",
        "required": [
            "support_level",
            "support_type",
            "used_for_core",
            "reason",
            "missing_link",
        ],
        "properties": {
            "evidence_id": {"type": "string"},
            "support_level": {
                "type": "string",
                "enum": [
                    "direct",
                    "partial",
                    "adjacent",
                    "weak",
                    "irrelevant",
                    "unassessed",
                ],
            },
            "support_type": {
                "type": "string",
                "enum": [
                    "explicit_demand",
                    "inferred_gap",
                    "context_only",
                    "counter_evidence",
                    "irrelevant",
                ],
            },
            "used_for_core": {"type": "boolean"},
            "reason": {"type": "string"},
            "missing_link": {"type": "string"},
        },
        "additionalProperties": False,
    }
    evidence_support_schema = {
        "type": "object",
        "required": [
            "verdict",
            "reason",
            "evidence_reviews",
            "recommended_report_status",
            "status_reason",
            "recheck_conditions",
        ],
        "properties": {
            "verdict": {"type": "string", "enum": ["pass", "doubt", "fail"]},
            "reason": {"type": "string"},
            "evidence_reviews": {
                "type": "object",
                "additionalProperties": evidence_review_schema,
            },
            "recommended_report_status": {
                "type": "string",
                "enum": ["review_ready", "needs_revision", "watchlist", "rejected"],
            },
            "status_reason": {"type": "string"},
            "recheck_conditions": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "additionalProperties": True,
    }
    return {
        "title": "demand_discovery_audit_output",
        "type": "object",
        "required": [
            "audit_id",
            "candidate_id",
            "conclusion",
            "scorecard",
            "comments",
            "required_rework",
        ],
        "properties": {
            "audit_id": {"type": "string"},
            "candidate_id": {"type": "string"},
            "conclusion": {
                "type": "string",
                "enum": ["approved", "needs_revision", "rejected"],
            },
            "scorecard": {
                "type": "object",
                "required": ["evidence_support"],
                "properties": {"evidence_support": evidence_support_schema},
                "additionalProperties": True,
            },
            "comments": {"type": "string"},
            "required_rework": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": False,
    }


def _normalize_brief(role: str, brief: str) -> str:
    return " ".join(f"{role} {brief}".lower().split())


def _missing_provider_factory(spec: WorkerSpec) -> Any:
    raise RuntimeError("provider_factory is required to run worker specs")

