from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Mapping, Sequence
from collections.abc import Awaitable, Sequence as AsyncSequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import os
from pathlib import Path
from threading import RLock
from typing import Any, Callable
from urllib.parse import urlsplit

from equipment_deep_research.agents.provider import AgentProvider, AgentRunRequest
from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.harness.agent_harness import AgentHarness
from equipment_deep_research.harness.profiles import HarnessCatalog
from equipment_deep_research.domain.identifiers import (
    safe_identifier_path,
    validate_internal_identifier,
)
from equipment_deep_research.domain.models import (
    EquipmentObservation,
    OperationalSynthesis,
    ScenarioModel,
    StrategicAssessment,
    TraceEvent,
    new_stable_id,
    now_iso,
    typed_domain_object_from_packet,
)
from equipment_deep_research.domain.store import DomainStore, TraceStore
from equipment_deep_research.domain.workspace import RunWorkspace
from equipment_deep_research.harness.context import (
    ContextPack,
    ContextPackBuilder,
    compact_handoff_value,
)
from equipment_deep_research.harness.session import JsonlSessionStore
from equipment_deep_research.harness.stop_policy import (
    evaluate_baseline_stop,
    evaluate_evidence_sufficiency,
)
from equipment_deep_research.tools.artifacts import SecureArtifactStore
from equipment_deep_research.tools.materialization import EvidenceMaterializer
from equipment_deep_research.tools.source_index import SourcePriorityIndex
from equipment_deep_research.tools.knowledge_index import AgentKnowledgeIndex
from equipment_deep_research.tools.evidence import EvidenceGovernor
from equipment_deep_research.domain.messages import AgentExecutionResult, TaskEnvelope
from equipment_deep_research.providers.base import (
    ModelMessage,
    ProviderFinalTurn,
    ProviderStreamEvent,
)
from equipment_deep_research.tools.definitions import ToolDefinition
from equipment_deep_research.tools.domain_tools import build_domain_tool_definitions
from equipment_deep_research.tools.permissions import effective_tool_names


@dataclass(frozen=True)
class WorkerReport:
    agent_id: str
    status: str
    new_evidence_ids: list[str]
    packet_id: str
    handoff_summary: str
    session_path: str
    error: str = ""
    domain_object_type: str = ""
    domain_object_id: str = ""
    harness_profile: str = ""
    active_skill_ids: list[str] = field(default_factory=list)
    active_tool_names: list[str] = field(default_factory=list)
    stop_reason: str = ""
    worker_report_id: str = field(
        default_factory=lambda: new_stable_id("worker-report")
    )
    created_at: str = field(default_factory=now_iso)
    schema_version: str = "1.0"


class _BaselineHarnessProvider:
    """Adapter that makes the existing role provider one AgentHarness model turn."""

    def __init__(self, provider: AgentProvider, request: AgentRunRequest) -> None:
        self.provider = provider
        self.request = request
        self.result: Any | None = None
        self.error: BaseException | None = None

    async def stream(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolDefinition],
        options: Mapping[str, Any],
    ) -> AsyncIterator[ProviderStreamEvent]:
        del messages, tools, options
        try:
            self.result = await asyncio.to_thread(
                self.provider.run_baseline_agent,
                self.request,
            )
        except BaseException as exc:
            self.error = exc
            raise
        yield ProviderStreamEvent.final(
            ProviderFinalTurn(
                text=self.result.raw_message,
                finish_reason="completed",
                metadata={"legacy_provider_adapter": True},
            )
        )


class _HarnessStoreProxy:
    """Keep inner Harness savepoints isolated until the runner commits its wave."""

    def __init__(self, delegate: Any, run_id: str) -> None:
        self.delegate = delegate
        self.run_id = run_id
        self.commits: list[tuple[tuple[Any, ...], tuple[Any, ...]]] = []

    def commit(self, domains: Sequence[Any], traces: Sequence[Any]) -> str:
        self.commits.append((tuple(domains), tuple(traces)))
        return new_stable_id("harness-checkpoint")


class DiscoveryScheduler:
    def __init__(
        self,
        *,
        run_id: str,
        run_dir: Path,
        provider: AgentProvider,
        store: DomainStore,
        trace: TraceStore,
        mode: str = "fake",
        context_builder: ContextPackBuilder | None = None,
        source_materials: list[dict[str, Any]] | None = None,
        session_store_factory: Callable[[str, Path], Any] | None = None,
        workspace: RunWorkspace | None = None,
        evidence_governor: EvidenceGovernor | None = None,
        event_sink: Callable[[str, dict[str, Any]], None] | None = None,
        harness_store: Any | None = None,
        harness_catalog: HarnessCatalog | None = None,
        shared_context: Mapping[str, Any] | None = None,
    ) -> None:
        self.run_id = run_id
        self.run_dir = run_dir
        self.provider = provider
        self.store = store
        self.trace = trace
        self.mode = mode
        self.context_builder = context_builder or ContextPackBuilder()
        self.session_store_factory = session_store_factory
        self.workspace = workspace
        self.sessions_dir = run_dir / "agent_sessions"
        if workspace is None:
            if self.run_dir.is_symlink():
                raise ValueError("run_dir must not be a symlink")
            if self.sessions_dir.is_symlink():
                raise ValueError("agent_sessions must not be a symlink")
            self.sessions_dir.mkdir(parents=True, exist_ok=True)
            if self.sessions_dir.is_symlink():
                raise ValueError("agent_sessions must not be a symlink")
            if self.sessions_dir.resolve(strict=True).parent != self.run_dir.resolve(
                strict=True
            ):
                raise ValueError("agent_sessions must stay within run_dir")
        self.materializer = EvidenceMaterializer(
            artifact_store=(
                SecureArtifactStore.for_workspace(workspace)
                if workspace is not None
                else SecureArtifactStore(run_dir / "artifacts")
            )
        )
        source_index_path = os.environ.get("EQUIPMENT_DR_SOURCE_PRIORITY_INDEX")
        self.source_index = SourcePriorityIndex(source_index_path)
        self.knowledge_index = AgentKnowledgeIndex(
            os.environ.get("EQUIPMENT_DR_AGENT_KNOWLEDGE_INDEX")
        )
        self.source_materials = source_materials if source_materials is not None else []
        self.evidence_governor = evidence_governor or EvidenceGovernor()
        self.event_sink = event_sink
        self.harness_store = harness_store
        self.harness_catalog = harness_catalog or HarnessCatalog.empty()
        self.shared_context = dict(shared_context or {})
        self._state_lock = RLock()

    def close(self) -> None:
        self.materializer.close()

    def __enter__(self) -> "DiscoveryScheduler":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def run_baseline_agents(
        self,
        *,
        agents: list[AgentDef],
        topic: str,
        research_route: str,
    ) -> list[WorkerReport]:
        reports: list[WorkerReport] = []
        for agent in agents:
            reports.append(
                self.run_agent(
                    agent=agent,
                    topic=topic,
                    research_route=research_route,
                )
            )
        return reports

    def prefetch_agent(
        self,
        *,
        agent: AgentDef,
        topic: str,
        research_route: str,
        round_index: int = 1,
        execution_priority: str = "normal",
        search_intensity: str = "standard",
        plan_mode: str = "required",
    ) -> dict[str, Any]:
        prefetch = getattr(self.provider, "prefetch_baseline_agent", None)
        if not callable(prefetch):
            return {"agent_id": agent.agent_id, "status": "unsupported"}
        context, _, _ = self._build_agent_context(
            agent=agent,
            topic=topic,
            research_route=research_route,
            recall_request=None,
            execution_priority=execution_priority,
            search_intensity=search_intensity,
            plan_mode=plan_mode,
        )
        result = prefetch(
            AgentRunRequest(
                run_id=self.run_id,
                agent=agent,
                topic=topic,
                research_route=research_route,
                context=context.sections,
                round_index=round_index,
            )
        )
        if self.mode == "real":
            sources = [
                item
                for item in result.get("web_sources", [])
                if isinstance(item, Mapping) and str(item.get("url", "")).strip()
            ][: max(1, int(os.environ.get("EQUIPMENT_DR_EVIDENCE_PREWARM_LIMIT", "6")))]
            if sources:
                with ThreadPoolExecutor(
                    max_workers=min(
                        len(sources),
                        max(
                            1,
                            int(
                                os.environ.get(
                                    "EQUIPMENT_DR_EVIDENCE_PREWARM_CONCURRENCY",
                                    "4",
                                )
                            ),
                        ),
                    ),
                    thread_name_prefix=f"evidence-prewarm-{agent.agent_id}",
                ) as executor:
                    prewarm_rows = list(
                        executor.map(
                            lambda item: self.materializer.prefetch_url(
                                str(item.get("url", ""))
                            ),
                            sources,
                        )
                    )
                result["prewarmed_count"] = sum(
                    row.get("status") in {"fetched", "cached", "fetch_blocked"}
                    for row in prewarm_rows
                )
        result.pop("web_sources", None)
        return result

    def _build_agent_context(
        self,
        *,
        agent: AgentDef,
        topic: str,
        research_route: str,
        recall_request: dict[str, Any] | None,
        execution_priority: str = "critical",
        search_intensity: str = "standard",
        plan_mode: str = "required",
    ) -> tuple[ContextPack, list[dict[str, Any]], list[dict[str, Any]]]:
        blueprint = self.shared_context.get("discovery_blueprint", {})
        optimized_v2 = (
            isinstance(blueprint, Mapping)
            and blueprint.get("execution_profile_id") == "optimized_v2"
        )
        with self._state_lock:
            context = self.context_builder.build_for_baseline_agent(
                agent=agent,
                topic=topic,
                research_route=research_route,
                store=self.store,
                recall_request=recall_request,
                minimal_handoff=optimized_v2,
            )
        source_priorities = self.source_index.recommend(agent.agent_id, topic)
        shared_source_priorities = self.source_index.recommend_shared(
            [
                str(item)
                for item in self.shared_context.get("selected_business_agent_ids", [])
            ],
            topic,
        )
        incremental_knowledge = self.knowledge_index.recommend(agent.agent_id, topic)
        shared_projection = {
            key: compact_handoff_value(
                _minimal_shared_context_value(key, value)
                if optimized_v2
                else value,
                max_string_chars=240 if optimized_v2 else 360,
                max_list_items=4 if optimized_v2 else 6,
                max_mapping_items=7 if optimized_v2 else 10,
            )
            for key, value in self.shared_context.items()
            if key != "selected_business_agent_ids"
        }
        sections = {
            **context.sections,
            **shared_projection,
            "source_priorities": source_priorities[:6]
            if optimized_v2
            else source_priorities,
            "shared_source_priorities": shared_source_priorities[:4]
            if optimized_v2
            else shared_source_priorities,
            "incremental_knowledge": incremental_knowledge[:3]
            if optimized_v2
            else incremental_knowledge,
            "_execution_priority": execution_priority,
            "_search_intensity": search_intensity,
            "_agent_plan_mode": (
                plan_mode
                if plan_mode in {"required", "reference", "callback"}
                else "required"
            ),
        }
        token_budget = int(agent.context_policy.get("token_budget", 5000))
        if optimized_v2:
            token_budget = min(token_budget, 2400)
        bounded_context = self.context_builder.projector.compactor.compact(
            ContextPack(agent.agent_id, sections),
            token_budget=token_budget,
        )[0]
        return (
            bounded_context,
            source_priorities,
            incremental_knowledge,
        )

    def run_agent(
        self,
        *,
        agent: AgentDef,
        topic: str,
        research_route: str,
        raise_on_error: bool = False,
        recall_request: dict[str, Any] | None = None,
        round_index: int = 1,
        execution_priority: str = "critical",
        search_intensity: str = "standard",
        plan_mode: str = "required",
    ) -> WorkerReport:
        if self.workspace is not None:
            validated_agent_id = validate_internal_identifier(
                agent.agent_id,
                field_name="agent_id",
            )
            session_path = self.sessions_dir.joinpath(f"{validated_agent_id}.jsonl")
        else:
            session_path = safe_identifier_path(
                self.sessions_dir,
                agent.agent_id,
                suffix=".jsonl",
                field_name="agent_id",
            )
        session = self._open_session_store(session_path.name)
        try:
            context, source_priorities, incremental_knowledge = (
                self._build_agent_context(
                    agent=agent,
                    topic=topic,
                    research_route=research_route,
                    recall_request=recall_request,
                    execution_priority=execution_priority,
                    search_intensity=search_intensity,
                    plan_mode=plan_mode,
                )
            )
            self._append_session(
                session,
                {
                    "event_type": "task_received",
                    "created_at": now_iso(),
                    "agent_id": agent.agent_id,
                    "task_id": f"baseline:{agent.agent_id}",
                    "title": f"{agent.display_name}研究任务",
                    "summary": agent.description,
                    "capability_tags": agent.capability_tags,
                    "context_sections": sorted(context.sections),
                    "allowed_tools": agent.tools,
                    "object_read_scopes": agent.object_read_scopes,
                    "object_write_scopes": agent.object_write_scopes,
                    "budget": (
                        self.harness_catalog.profiles[
                            agent.harness_profile
                        ].task_budget()
                        if agent.harness_profile
                        and agent.harness_profile in self.harness_catalog.profiles
                        else {
                            "max_tokens": int(
                                agent.context_policy.get("token_budget", 5000)
                            )
                        }
                    ),
                    "skills": agent.skills,
                    "research_policy": agent.research_policy,
                    "upstream_agent_ids": [
                        item.get("agent_id")
                        for item in context.sections.get("upstream_handoffs", [])
                    ],
                    "round_index": round_index,
                    "recall_request": recall_request or {},
                    "source_priority_count": len(source_priorities),
                    "incremental_memory_count": len(incremental_knowledge),
                    "source_priority_domains": list(
                        dict.fromkeys(
                            str(item.get("domain", ""))
                            for item in source_priorities
                            if str(item.get("domain", ""))
                        )
                    ),
                },
            )
            self.trace.append(
                TraceEvent(
                    event_id=f"trace-delegated-{agent.agent_id}-r{round_index}",
                    event_type="agent_task_delegated",
                    actor="orchestrator",
                    summary=f"委派给{agent.display_name}：{agent.description}",
                    output_refs=[f"baseline:{agent.agent_id}"],
                    payload={
                        "target_agent_id": agent.agent_id,
                        "capability_tags": agent.capability_tags,
                        "allowed_tools": agent.tools,
                        "skills": [item.get("name") for item in agent.skills],
                        "research_policy": agent.research_policy,
                        "upstream_agent_ids": [
                            item.get("agent_id")
                            for item in context.sections.get("upstream_handoffs", [])
                        ],
                        "context_sections": sorted(context.sections),
                        "round_index": round_index,
                        "source_priority_count": len(source_priorities),
                        "incremental_memory_count": len(incremental_knowledge),
                    },
                )
            )
            hosted_search_call_id = f"{agent.agent_id}:hosted-search:r{round_index}"
            if self.mode == "real" and getattr(
                self.provider, "uses_hosted_web_search", False
            ):
                self._append_session(
                    session,
                    {
                        "event_type": "tool_call",
                        "created_at": now_iso(),
                        "agent_id": agent.agent_id,
                        "tool_name": "search_sources",
                        "call_id": hosted_search_call_id,
                        "arguments": {
                            "topic": topic,
                            "research_route": research_route,
                            "round_index": round_index,
                            "backend": getattr(
                                self.provider,
                                "discovery_backend",
                                "model_discovery",
                            ),
                        },
                    },
                )
            request = AgentRunRequest(
                run_id=self.run_id,
                agent=agent,
                topic=topic,
                research_route=research_route,
                context={
                    **context.sections,
                },
                round_index=round_index,
            )
            harness_result: AgentExecutionResult | None = None
            active_tool_names = list(agent.tools)
            blueprint = self.shared_context.get("discovery_blueprint", {})
            optimized_v2 = (
                isinstance(blueprint, Mapping)
                and blueprint.get("execution_profile_id") == "optimized_v2"
            )
            active_skill_ids = list(agent.skill_ids[:1] if optimized_v2 else agent.skill_ids)
            stop_reason = "legacy_provider_completed"
            if self.harness_store is not None and agent.harness_profile:
                profile = self.harness_catalog.profiles[agent.harness_profile]
                skill_definitions = [
                    self.harness_catalog.skills[skill_id]
                    for skill_id in agent.skill_ids
                ]
                active_tool_names = list(
                    effective_tool_names(
                        agent_allowlist=agent.tools,
                        task_allowlist=agent.tools,
                        skill_allowlists=(
                            skill.allowed_tools for skill in skill_definitions
                        ),
                        phase_allowlist=profile.phase_tools.get(
                            "baseline", agent.tools
                        ),
                    )
                )
                if optimized_v2:
                    active_tool_names = _minimal_agent_tools(
                        agent.agent_id,
                        active_tool_names,
                    )
                adapter = _BaselineHarnessProvider(self.provider, request)
                harness = AgentHarness(
                    adapter,
                    build_domain_tool_definitions(active_tool_names),
                    _HarnessStoreProxy(self.harness_store, self.run_id),
                    sessions_root=self.sessions_dir,
                    model_name=str(agent.model_profile.get("model", "gpt-5.5")),
                    model_options={
                        key: value
                        for key, value in agent.model_profile.items()
                        if key not in {"provider", "model"}
                    },
                    session_store_factory=(
                        lambda session_ref, _root: self._open_harness_session_store(
                            session_ref
                        )
                    ),
                )
                harness_task = TaskEnvelope(
                    task_id=f"baseline:{agent.agent_id}:r{round_index}",
                    run_id=self.run_id,
                    round_index=round_index,
                    parent_task_id="orchestrator",
                    target_agent_id=agent.agent_id,
                    target_capability_tags=list(agent.capability_tags),
                    objective=agent.description,
                    research_questions=[topic],
                    context_refs=[context.context_hash],
                    evidence_refs=[
                        item.get("evidence_id", "")
                        for item in context.sections.get("evidence_index", [])
                    ],
                    allowed_tools=active_tool_names,
                    object_read_scopes=list(agent.object_read_scopes),
                    object_write_scopes=list(agent.object_write_scopes),
                    budget=profile.task_budget(),
                    return_contract=(
                        str(
                            agent.output_contract.get("name", "baseline_finding_packet")
                        )
                        if isinstance(agent.output_contract, dict)
                        else str(agent.output_contract)
                    ),
                    return_node="baseline_reduce",
                    runtime_profile_id=agent.harness_profile,
                    active_skill_ids=active_skill_ids,
                    phase_id="baseline",
                )
                harness_result = asyncio.run(harness.execute(harness_task))
                if harness_result.status != "completed" or adapter.result is None:
                    if adapter.error is not None:
                        raise adapter.error
                    raise RuntimeError(
                        harness_result.error
                        or f"AgentHarness stopped with status={harness_result.status}"
                    )
                result = adapter.result
                stop_reason = harness_result.status
                self._append_session(
                    session,
                    {
                        "event_type": "harness_execution",
                        "created_at": now_iso(),
                        "agent_id": agent.agent_id,
                        "runtime_profile_id": agent.harness_profile,
                        "active_skill_ids": active_skill_ids,
                        "active_tool_names": active_tool_names,
                        "phase_id": "baseline",
                        "stop_reason": stop_reason,
                        "snapshot_count": len(harness_result.snapshots),
                        "harness_session_path": str(harness.last_session_path or ""),
                    },
                )
                self.trace.append(
                    TraceEvent(
                        event_id=f"trace-harness-{agent.agent_id}-r{round_index}",
                        event_type="agent_harness_completed",
                        actor=agent.agent_id,
                        summary=f"{agent.harness_profile} completed: {stop_reason}",
                        payload={
                            "runtime_profile_id": agent.harness_profile,
                            "active_skill_ids": active_skill_ids,
                            "active_tool_names": active_tool_names,
                            "phase_id": "baseline",
                            "stop_reason": stop_reason,
                            "snapshot_count": len(harness_result.snapshots),
                        },
                    )
                )
            else:
                result = self.provider.run_baseline_agent(request)
            for call_index, metric in enumerate(result.model_calls, start=1):
                self._append_session(
                    session,
                    {
                        "event_type": "agent_model_call_completed",
                        "created_at": now_iso(),
                        "agent_id": agent.agent_id,
                        **metric,
                    },
                )
                self.trace.append(
                    TraceEvent(
                        event_id=(
                            f"trace-model-call-{agent.agent_id}-"
                            f"r{round_index}-{call_index}"
                        ),
                        event_type="agent_model_call_completed",
                        actor=agent.agent_id,
                        summary=(
                            f"{metric.get('phase', 'model')} completed in "
                            f"{metric.get('elapsed_seconds', 'unknown')}s"
                        ),
                        payload=dict(metric),
                    )
                )
            if self.mode == "real" and getattr(
                self.provider, "uses_hosted_web_search", False
            ):
                self._append_session(
                    session,
                    {
                        "event_type": "tool_result",
                        "created_at": now_iso(),
                        "agent_id": agent.agent_id,
                        "tool_name": "search_sources",
                        "call_id": hosted_search_call_id,
                        "status": "completed"
                        if result.packet.search_log
                        else "no_sources",
                        "output_refs": [item.evidence_id for item in result.evidence],
                        "summary": (
                            f"执行 {len(result.packet.search_log)} 个查询，返回 "
                            f"{len(result.evidence)} 个待材料化来源。"
                        ),
                    },
                )
            materialized_refs: list[str] = []
            accepted_evidence_ids: list[str] = []
            accepted_evidence: list[Any] = []
            targeted_supplement = bool(
                isinstance(recall_request, dict)
                and recall_request.get("targeted_supplement")
            )
            accepted_target = (
                max(
                    2,
                    min(
                        3,
                        int(
                            os.environ.get(
                                "EQUIPMENT_DR_TARGETED_EVIDENCE_ACCEPT_TARGET", "3"
                            )
                        ),
                    ),
                )
                if targeted_supplement
                else max(
                    1,
                    min(
                        int(
                            os.environ.get("EQUIPMENT_DR_EVIDENCE_ACCEPT_TARGET", "6")
                        ),
                        int(
                            agent.research_policy.get(
                                "evidence_accept_target",
                                os.environ.get("EQUIPMENT_DR_EVIDENCE_ACCEPT_TARGET", "6"),
                            )
                        ),
                    ),
                )
            )
            minimum_accepted = max(
                1,
                min(
                    accepted_target,
                    (
                        2
                        if targeted_supplement
                        else min(
                            int(os.environ.get("EQUIPMENT_DR_EVIDENCE_MIN_COUNT", "3")),
                            int(
                                agent.research_policy.get(
                                    "evidence_min_count",
                                    os.environ.get("EQUIPMENT_DR_EVIDENCE_MIN_COUNT", "3"),
                                )
                            ),
                        )
                    ),
                ),
            )
            minimum_domains = max(
                1,
                min(
                    int(os.environ.get("EQUIPMENT_DR_EVIDENCE_MIN_DOMAINS", "2")),
                    int(
                        agent.research_policy.get(
                            "evidence_min_domains",
                            os.environ.get("EQUIPMENT_DR_EVIDENCE_MIN_DOMAINS", "2"),
                        )
                    ),
                ),
            )
            materialize_attempts = (
                min(len(result.evidence), max(accepted_target, 4))
                if targeted_supplement
                else max(
                    accepted_target,
                    min(
                        int(
                            os.environ.get(
                                "EQUIPMENT_DR_EVIDENCE_MATERIALIZE_ATTEMPTS",
                                str(len(result.evidence)),
                            )
                        ),
                        int(
                            agent.research_policy.get(
                                "evidence_materialize_attempts",
                                os.environ.get(
                                    "EQUIPMENT_DR_EVIDENCE_MATERIALIZE_ATTEMPTS",
                                    str(len(result.evidence)),
                                ),
                            )
                        )
                    ),
                )
            )
            evidence_candidates = _diversify_evidence_candidates(
                result.evidence[:materialize_attempts]
            )
            # The accepted target already includes the governed evidence count,
            # source diversity and counter-evidence requirements used by the
            # release gate. Once it is reached, additional page materialization
            # adds latency without changing downstream admissibility; any later
            # gap is handled by the targeted callback path.
            maximum_accepted = min(materialize_attempts, accepted_target)
            materialize_workers = min(
                len(evidence_candidates),
                max(
                    1,
                    int(
                        os.environ.get(
                            "EQUIPMENT_DR_EVIDENCE_MATERIALIZE_CONCURRENCY",
                            "4",
                        )
                    ),
                ),
            )
            candidate_offset = 0
            evidence_sufficiency = evaluate_evidence_sufficiency(
                result.packet,
                accepted_evidence,
                minimum_count=minimum_accepted,
                target_count=accepted_target,
                minimum_domains=minimum_domains,
                require_counterevidence=bool(
                    agent.research_policy.get("require_counter_evidence", True)
                ),
            )
            while (
                candidate_offset < len(evidence_candidates)
                and len(accepted_evidence_ids) < maximum_accepted
            ):
                batch_size = min(
                    max(1, materialize_workers),
                    len(evidence_candidates) - candidate_offset,
                    maximum_accepted - len(accepted_evidence_ids),
                )
                batch = evidence_candidates[
                    candidate_offset : candidate_offset + batch_size
                ]
                candidate_offset += len(batch)
                for evidence in batch:
                    materialize_tool = (
                        "fetch_page" if self.mode == "real" else "create_evidence_card"
                    )
                    self._append_session(
                        session,
                        {
                            "event_type": "tool_call",
                            "created_at": now_iso(),
                            "agent_id": agent.agent_id,
                            "tool_name": materialize_tool,
                            "call_id": f"{agent.agent_id}:{evidence.evidence_id}:materialize",
                            "arguments": {
                                "source_url": evidence.source_url,
                                "source_title": evidence.source_title,
                                "mode": self.mode,
                            },
                        },
                    )
                if len(batch) > 1:
                    with ThreadPoolExecutor(
                        max_workers=min(materialize_workers, len(batch)),
                        thread_name_prefix=f"evidence-{agent.agent_id}",
                    ) as executor:
                        materialized_rows = list(
                            executor.map(
                                lambda item: self.materializer.materialize(
                                    item,
                                    mode=self.mode,
                                ),
                                batch,
                            )
                        )
                else:
                    materialized_rows = [
                        self.materializer.materialize(batch[0], mode=self.mode)
                    ]
                for evidence, materialized in zip(
                    batch,
                    materialized_rows,
                    strict=True,
                ):
                    materialize_tool = (
                        "fetch_page" if self.mode == "real" else "create_evidence_card"
                    )
                    self._append_session(
                        session,
                        {
                            "event_type": "tool_result",
                            "created_at": now_iso(),
                            "agent_id": agent.agent_id,
                            "tool_name": materialize_tool,
                            "call_id": f"{agent.agent_id}:{evidence.evidence_id}:materialize",
                            "status": materialized.material.get("status", "completed"),
                            "artifact_refs": materialized.material.get(
                                "artifact_refs", []
                            ),
                            "formal_evidence_allowed": materialized.material.get(
                                "formal_evidence_allowed", True
                            ),
                        },
                    )
                    with self._state_lock:
                        assessment = self.evidence_governor.assess(
                            materialized.evidence,
                            _evidence_metrics(agent, materialized.evidence),
                            existing=self.store.evidence_snapshot(),
                        )
                        should_accept = bool(
                            len(accepted_evidence_ids) < maximum_accepted
                            and materialized.material.get(
                                "formal_evidence_allowed", True
                            )
                            and assessment.decision == "accepted"
                        )
                        if should_accept:
                            self.store.add_evidence(materialized.evidence)
                    self.source_index.record(
                        agent_id=agent.agent_id,
                        topic=topic,
                        evidence=materialized.evidence,
                        material=materialized.material,
                        assessment=assessment,
                    )
                    material = {
                        **materialized.material,
                        "evidence_assessment": assessment.__dict__,
                    }
                    formal_evidence_allowed = bool(
                        materialized.material.get("formal_evidence_allowed", True)
                    )
                    projected_decision = (
                        assessment.decision
                        if formal_evidence_allowed
                        else "rejected"
                    )
                    projected_reasons = list(assessment.reasons)
                    if not formal_evidence_allowed:
                        projected_reasons.append(
                            "材料化未形成可独立核验的正式证据"
                        )
                    self._append_session(
                        session,
                        {
                            "event_type": "evidence_assessed",
                            "created_at": now_iso(),
                            "agent_id": agent.agent_id,
                            "evidence_id": evidence.evidence_id,
                            "decision": projected_decision,
                            "quality_score": assessment.score,
                            "reasons": projected_reasons,
                        },
                    )
                    with self._state_lock:
                        self.source_materials.append(material)
                    materialized_refs.extend(
                        materialized.material.get("artifact_refs", [])
                    )
                    if should_accept:
                        self._append_session(
                            session,
                            {
                                "event_type": "tool_call",
                                "created_at": now_iso(),
                                "agent_id": agent.agent_id,
                                "tool_name": "create_evidence_card",
                                "call_id": f"{agent.agent_id}:{evidence.evidence_id}:persist",
                                "arguments": {
                                    "evidence_id": materialized.evidence.evidence_id,
                                    "claim": materialized.evidence.claim,
                                    "source_location": materialized.evidence.source_location,
                                },
                            },
                        )
                        accepted_evidence_ids.append(materialized.evidence.evidence_id)
                        accepted_evidence.append(materialized.evidence)
                        self._append_session(
                            session,
                            {
                                "event_type": "tool_result",
                                "created_at": now_iso(),
                                "agent_id": agent.agent_id,
                                "tool_name": "create_evidence_card",
                                "call_id": f"{agent.agent_id}:{evidence.evidence_id}:persist",
                                "status": "accepted",
                                "output_refs": [materialized.evidence.evidence_id],
                            },
                        )
                evidence_sufficiency = evaluate_evidence_sufficiency(
                    result.packet,
                    accepted_evidence,
                    minimum_count=minimum_accepted,
                    target_count=accepted_target,
                    minimum_domains=minimum_domains,
                    require_counterevidence=bool(
                        agent.research_policy.get("require_counter_evidence", True)
                    ),
                )
                batch_cache_hits = sum(
                    bool(item.material.get("fetch_cache_hit"))
                    for item in materialized_rows
                )
                threshold_met = evidence_sufficiency.allowed
                quality_target_met = bool(
                    threshold_met
                    and len(accepted_evidence_ids) >= accepted_target
                )
                continued_after_threshold = bool(
                    threshold_met
                    and not quality_target_met
                    and candidate_offset < len(evidence_candidates)
                )
                self.trace.append(
                    TraceEvent(
                        event_id=(
                            f"trace-materialization-progress-{agent.agent_id}-"
                            f"r{round_index}-{candidate_offset}"
                        ),
                        event_type="baseline_materialization_progress",
                        actor=agent.agent_id,
                        summary=(
                            f"证据并行材料化 {candidate_offset}/{len(evidence_candidates)}"
                            f"（本批 {len(batch)} 路并行，缓存复用 {batch_cache_hits}），"
                            f"正式接纳 {len(accepted_evidence_ids)}/{accepted_target}"
                            + (
                                "；已达最低门槛，继续补足质量目标"
                                if continued_after_threshold
                                else "；已达质量目标，停止扩证"
                                if quality_target_met
                                else "；多源候选已完成"
                                if threshold_met
                                else ""
                            )
                        ),
                        input_refs=[item.evidence_id for item in batch],
                        output_refs=list(accepted_evidence_ids),
                        payload={
                            "agent_id": agent.agent_id,
                            "attempted_count": candidate_offset,
                            "candidate_count": len(evidence_candidates),
                            "accepted_count": len(accepted_evidence_ids),
                            "minimum_count": minimum_accepted,
                            "target_count": accepted_target,
                            "parallel_batch_size": len(batch),
                            "cache_hit_count": batch_cache_hits,
                            "quality_threshold_met": threshold_met,
                            "quality_target_met": quality_target_met,
                            "continued_after_threshold": continued_after_threshold,
                            "remaining_candidate_count": (
                                len(evidence_candidates) - candidate_offset
                            ),
                            "distinct_domains": (
                                evidence_sufficiency.distinct_domains
                            ),
                        },
                    )
                )
            packet = result.packet
            upstream_handoffs = [
                item
                for item in context.sections.get("upstream_handoffs", [])
                if isinstance(item, Mapping)
                and str(item.get("agent_id", "")).strip()
            ]
            if upstream_handoffs:
                analysis_sections = dict(packet.analysis_sections)
                upstream_synthesis = analysis_sections.get(
                    "upstream_synthesis", {}
                )
                upstream_synthesis = (
                    dict(upstream_synthesis)
                    if isinstance(upstream_synthesis, Mapping)
                    else {}
                )
                upstream_synthesis.update(
                    {
                        "consumed_agents": list(
                            dict.fromkeys(
                                str(item["agent_id"])
                                for item in upstream_handoffs
                            )
                        ),
                        "packet_ids": list(
                            dict.fromkeys(
                                str(item.get("packet_id", ""))
                                for item in upstream_handoffs
                                if str(item.get("packet_id", "")).strip()
                            )
                        ),
                    }
                )
                analysis_sections["upstream_synthesis"] = upstream_synthesis
                packet = type(packet)(
                    **{
                        **packet.__dict__,
                        "analysis_sections": analysis_sections,
                    }
                )
            if packet.evidence_ids != accepted_evidence_ids:
                packet = type(packet)(
                    **{
                        **packet.__dict__,
                        "evidence_ids": accepted_evidence_ids,
                        "coverage_notes": [
                            *packet.coverage_notes,
                            "部分来源未通过网络安全或材料化校验，已从正式证据集中剔除。",
                        ],
                    }
                )
            packet.validate_for_submit()
            stop_decision = evaluate_baseline_stop(
                packet,
                enforce_evidence_counts=bool(
                    self.mode == "real"
                    and getattr(self.provider, "enforce_profile_stops", False)
                ),
                minimum_evidence_count=minimum_accepted,
                evidence_sufficiency=evidence_sufficiency,
            )
            self.trace.append(
                TraceEvent(
                    event_id=f"trace-stop-policy-{agent.agent_id}-r{round_index}",
                    event_type="stop_policy_evaluated",
                    actor=agent.agent_id,
                    summary=(
                        "baseline quality gates passed"
                        if stop_decision.allowed
                        else "; ".join(stop_decision.reasons)
                    ),
                    input_refs=[packet.packet_id, *packet.evidence_ids],
                    payload={
                        "runtime_profile_id": agent.harness_profile,
                        "allowed": stop_decision.allowed,
                        "reasons": list(stop_decision.reasons),
                        "evidence_sufficiency": {
                            "accepted_count": evidence_sufficiency.accepted_count,
                            "distinct_domains": evidence_sufficiency.distinct_domains,
                            "minimum_count": minimum_accepted,
                            "target_count": accepted_target,
                        },
                    },
                )
            )
            if not stop_decision.allowed:
                evidence_only_limited = _evidence_only_stop_reasons(
                    stop_decision.reasons
                )
                allow_limited = bool(
                    self.mode == "real"
                    and getattr(self.provider, "provider_kind", "") == "codex_cli"
                    and os.environ.get(
                        "EQUIPMENT_DR_ALLOW_LIMITED_BASELINE",
                        "1",
                    )
                    == "1"
                    and packet.findings
                    and (bool(accepted_evidence_ids) or evidence_only_limited)
                )
                if not allow_limited:
                    raise RuntimeError(
                        "stop policy blocked normal completion: "
                        + "; ".join(stop_decision.reasons)
                    )
                limitation = "；".join(stop_decision.reasons)
                packet = type(packet)(
                    **{
                        **packet.__dict__,
                        "confidence": min(
                            packet.confidence,
                            0.49 if accepted_evidence_ids else 0.35,
                        ),
                        "coverage_notes": [
                            *packet.coverage_notes,
                            "本节点未完全满足证据门槛，已降级交接并交由后续循环和独立审计限制使用；"
                            "若无正式证据，所有结论仅作为待验证假设，不得进入确定性参数或成熟度判断。",
                        ],
                        "limitations": [*packet.limitations, limitation],
                    }
                )
                stop_reason = "quality_gates_limited"
            else:
                stop_reason = "quality_gates_passed"
            self.store.add_baseline_packet(packet)
            self.knowledge_index.record(
                packet=packet,
                evidence=accepted_evidence,
            )
            domain_object = typed_domain_object_from_packet(packet)
            domain_object_type = ""
            domain_object_id = ""
            if isinstance(domain_object, StrategicAssessment):
                self.store.add_strategic_assessment(domain_object)
                domain_object_type, domain_object_id = (
                    "StrategicAssessment",
                    domain_object.assessment_id,
                )
            elif isinstance(domain_object, ScenarioModel):
                self.store.add_scenario_model(domain_object)
                domain_object_type, domain_object_id = (
                    "ScenarioModel",
                    domain_object.scenario_id,
                )
            elif isinstance(domain_object, EquipmentObservation):
                self.store.add_equipment_observation(domain_object)
                domain_object_type, domain_object_id = (
                    "EquipmentObservation",
                    domain_object.observation_id,
                )
            elif isinstance(domain_object, OperationalSynthesis):
                self.store.add_operational_synthesis(domain_object)
                domain_object_type, domain_object_id = (
                    "OperationalSynthesis",
                    domain_object.synthesis_id,
                )
            self._append_session(
                session,
                {
                    "event_type": "baseline_result",
                    "created_at": now_iso(),
                    "agent_id": agent.agent_id,
                    "context_sections": sorted(context.sections),
                    "raw_message": result.raw_message,
                    "packet_id": packet.packet_id,
                    "evidence_ids": packet.evidence_ids,
                    "materialized_artifact_refs": materialized_refs,
                },
            )
            new_evidence = sorted(accepted_evidence_ids)
            self.trace.append(
                TraceEvent(
                    event_id=(
                        f"trace-{agent.agent_id}-baseline"
                        if round_index == 1
                        else f"trace-{agent.agent_id}-baseline-r{round_index}"
                    ),
                    event_type="baseline_agent_completed",
                    actor=agent.agent_id,
                    summary=packet.handoff_summary,
                    output_refs=[packet.packet_id, *new_evidence],
                    payload={
                        "capability_tags": agent.capability_tags,
                        "artifact_refs": materialized_refs,
                    },
                )
            )
            return WorkerReport(
                agent_id=agent.agent_id,
                status="completed",
                new_evidence_ids=new_evidence,
                packet_id=packet.packet_id,
                handoff_summary=packet.handoff_summary,
                session_path=str(session_path),
                domain_object_type=domain_object_type,
                domain_object_id=domain_object_id,
                harness_profile=agent.harness_profile,
                active_skill_ids=list(agent.skill_ids),
                active_tool_names=active_tool_names,
                stop_reason=stop_reason,
            )
        except Exception as exc:
            self.trace.append(
                TraceEvent(
                    event_id=(
                        f"trace-{agent.agent_id}-failed"
                        if round_index == 1
                        else f"trace-{agent.agent_id}-failed-r{round_index}"
                    ),
                    event_type="baseline_agent_failed",
                    actor=agent.agent_id,
                    summary=str(exc),
                )
            )
            report = WorkerReport(
                agent_id=agent.agent_id,
                status="failed",
                new_evidence_ids=[],
                packet_id="",
                handoff_summary="",
                session_path=str(session_path),
                error=str(exc),
            )
            if raise_on_error:
                try:
                    setattr(exc, "worker_report", report)
                except (AttributeError, TypeError):
                    pass
                raise
            return report
        finally:
            close = getattr(session, "close", None)
            if callable(close):
                close()

    def append_savepoint(
        self,
        report: WorkerReport,
        checkpoint_id: str,
        *,
        task_id: str,
        batch_hash: str,
    ) -> None:
        session_ref = Path(report.session_path).name
        session = self._open_session_store(session_ref)
        try:
            self._append_session(
                session,
                {
                    "event_type": "savepoint",
                    "agent_id": report.agent_id,
                    "task_id": task_id,
                    "checkpoint_id": checkpoint_id,
                    "batch_hash": batch_hash,
                    "worker_report_id": report.worker_report_id,
                    "packet_id": report.packet_id,
                    "evidence_ids": report.new_evidence_ids,
                    "created_at": now_iso(),
                    "schema_version": "1.0",
                },
            )
        finally:
            close = getattr(session, "close", None)
            if callable(close):
                close()

    def _open_session_store(self, session_ref: str) -> Any:
        if self.session_store_factory is not None:
            return self.session_store_factory(session_ref, self.sessions_dir)
        if self.workspace is not None:
            root_fd = self.workspace.dup_sessions_fd()
            try:
                return JsonlSessionStore(
                    session_ref,
                    root_fd=root_fd,
                    root_label=self.sessions_dir,
                )
            finally:
                os.close(root_fd)
        return JsonlSessionStore(session_ref, root_dir=self.sessions_dir)

    def _open_harness_session_store(self, session_ref: str) -> Any:
        if self.workspace is not None:
            root_fd = self.workspace.dup_sessions_fd()
            try:
                return JsonlSessionStore(
                    session_ref,
                    root_fd=root_fd,
                    root_label=self.sessions_dir,
                )
            finally:
                os.close(root_fd)
        return JsonlSessionStore(session_ref, root_dir=self.sessions_dir)

    def _append_session(self, session: Any, record: dict[str, Any]) -> None:
        session.append(record)
        if self.event_sink is None:
            return
        allowed_events = {
            "task_received",
            "tool_call",
            "tool_result",
            "evidence_assessed",
            "baseline_result",
            "savepoint",
        }
        event_type = str(record.get("event_type", ""))
        if event_type not in allowed_events:
            return
        safe_keys = {
            "event_type",
            "created_at",
            "agent_id",
            "task_id",
            "title",
            "summary",
            "capability_tags",
            "context_sections",
            "allowed_tools",
            "skills",
            "research_policy",
            "upstream_agent_ids",
            "round_index",
            "recall_request",
            "tool_name",
            "call_id",
            "arguments",
            "status",
            "artifact_refs",
            "formal_evidence_allowed",
            "evidence_id",
            "decision",
            "quality_score",
            "reasons",
            "packet_id",
            "evidence_ids",
            "materialized_artifact_refs",
            "checkpoint_id",
            "output_refs",
            "worker_report_id",
        }
        self.event_sink(
            event_type,
            {
                "source": "session_projection",
                "event": {
                    key: value for key, value in record.items() if key in safe_keys
                },
            },
        )


def _minimal_shared_context_value(key: str, value: Any) -> Any:
    if key != "discovery_blueprint" or not isinstance(value, Mapping):
        return value
    return {
        field: value.get(field)
        for field in (
            "primary_branch",
            "branch_name",
            "emphasis",
            "required_outputs",
            "execution_profile_id",
            "adaptive_winning_step_modes",
        )
        if value.get(field) not in (None, "", [], {})
    }


def _minimal_agent_tools(agent_id: str, tools: Sequence[str]) -> list[str]:
    domain_tool = {
        "international_situation": "test_competing_hypothesis",
        "combat_scenario": "stress_test_scenario",
        "operational_employment": "compare_coa",
        "weapon_equipment": "compare_equipment_capability",
        "case_research": "transfer_case_lesson",
    }.get(agent_id, "")
    preferred = ("search_sources", "create_evidence_card", domain_tool)
    selected = [item for item in preferred if item and item in tools]
    return selected or list(tools)[:2]


def _evidence_metrics(agent: AgentDef, evidence: Any) -> dict[str, float]:
    freshness = {
        "international_situation": 0.9,
        "combat_scenario": 0.82,
        "weapon_equipment": 0.76,
        "operational_employment": 0.8,
    }.get(agent.agent_id, 0.75)
    direct_support = 0.85 if evidence.excerpt else 0.2
    transparency = 0.86 if evidence.source_location else 0.3
    if agent.agent_id == "weapon_equipment" and any(
        token in evidence.excerpt for token in ("参数", "型号", "批次", "预算", "采购")
    ):
        direct_support = 0.92
    return {
        "relevance": 0.88,
        "transparency": transparency,
        "freshness": freshness,
        "direct_support": direct_support,
        "extraction_quality": 0.88 if evidence.artifact_refs else 0.3,
    }


def _diversify_evidence_candidates(candidates: Sequence[Any]) -> list[Any]:
    """Interleave source domains so the first batch can satisfy diversity gates."""
    groups: dict[str, deque[Any]] = defaultdict(deque)
    domain_order: list[str] = []
    for candidate in candidates:
        try:
            domain = (urlsplit(str(candidate.source_url)).hostname or "").lower()
        except ValueError:
            domain = ""
        key = domain or f"unknown:{len(domain_order)}"
        if key not in groups:
            domain_order.append(key)
        groups[key].append(candidate)
    diversified: list[Any] = []
    while any(groups[key] for key in domain_order):
        for key in domain_order:
            if groups[key]:
                diversified.append(groups[key].popleft())
    return diversified


def _evidence_only_stop_reasons(reasons: Sequence[Any]) -> bool:
    """Whether a stop failure can safely become a hypothesis-only handoff."""

    rows = [str(item).strip() for item in reasons if str(item).strip()]
    evidence_markers = (
        "正式证据少于",
        "独立来源域少于",
        "缺少反证、冲突或适用边界",
    )
    return bool(rows) and all(
        any(row.startswith(marker) for marker in evidence_markers)
        for row in rows
    )


class SubagentWaveScheduler:
    """Bounded concurrent runtime scheduler for isolated TaskEnvelope waves."""

    def __init__(
        self,
        execute: Callable[[TaskEnvelope], Awaitable[AgentExecutionResult]],
        *,
        max_concurrency: int = 4,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        self.execute = execute
        self.max_concurrency = max_concurrency
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    async def run_wave(
        self, tasks: AsyncSequence[TaskEnvelope]
    ) -> list[AgentExecutionResult]:
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def execute_one(task: TaskEnvelope) -> AgentExecutionResult:
            if self._cancelled:
                return AgentExecutionResult(
                    "cancelled",
                    task.task_id,
                    task.target_agent_id,
                    "cancelled",
                    error="wave cancelled",
                )
            async with semaphore:
                try:
                    return await self.execute(task)
                except Exception as exc:
                    return AgentExecutionResult(
                        "failed",
                        task.task_id,
                        task.target_agent_id,
                        "failed",
                        error=f"{type(exc).__name__}: {exc}",
                    )

        return list(await asyncio.gather(*(execute_one(task) for task in tasks)))
