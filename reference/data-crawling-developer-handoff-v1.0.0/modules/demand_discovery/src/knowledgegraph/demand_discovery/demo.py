"""Runnable demand discovery demo flows."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

from knowledgegraph.demand_discovery.domain.audit_rubric import load_default_rubric
from knowledgegraph.demand_discovery.domain.orchestration_tools import spawn_worker_tool
from knowledgegraph.demand_discovery.domain.report import REQUIRED_SECTIONS
from knowledgegraph.demand_discovery.domain.store import DomainStore
from knowledgegraph.demand_discovery.domain.tools import build_domain_tools
from knowledgegraph.demand_discovery.harness.agent_harness import DiscoveryHarness
from knowledgegraph.demand_discovery.harness.context_pack import ContextPackBuilder
from knowledgegraph.demand_discovery.harness.event_bus import EventBus, ProgressWriter
from knowledgegraph.demand_discovery.harness.intervention import (
    FileInbox,
    attach_file_inbox,
)
from knowledgegraph.demand_discovery.harness.scheduler import (
    DiscoveryScheduler,
    WorkerSpec,
)
from knowledgegraph.demand_discovery.harness.session_store import JsonlSessionStore
from knowledgegraph.demand_discovery.harness.trace_store import DomainTraceStore
from knowledgegraph.demand_discovery.llm.fake_provider import FakeProvider, FakeResponse
from knowledgegraph.demand_discovery.llm.model_config import (
    DEFAULT_REAL_MODEL,
    ModelConfig,
)
from knowledgegraph.demand_discovery.llm.responses_adapter import (
    build_provider_request,
    ResponsesProvider,
)
from knowledgegraph.demand_discovery.llm.types import LLMContext
from knowledgegraph.demand_discovery.workers.agent_defs import default_agent_dir


@dataclass
class DemoResult:
    candidate_title: str
    candidate_id: str
    evidence_ids: list[str]
    audit_conclusion: str
    report_title: str
    trace_event_count: int
    trace_path: Path | None = None
    progress_path: Path | None = None


async def run_fake_demo(output_path: Path | None = None) -> DemoResult:
    """Run the deterministic offline fake-provider demo."""

    provider = FakeProvider()
    provider.set_responses(_fake_responses())
    return await _run_demo_with_provider(
        provider,
        task_brief="discover low-altitude sensing demand",
        output_path=output_path,
    )


async def run_fake_watch_demo(
    *,
    output_path: Path | None = None,
    output_root: Path,
    run_id: str,
    event_bus: EventBus | None = None,
) -> DemoResult:
    """Run the Phase 2 fake multi-worker path with progress snapshots."""

    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    store = DomainStore()
    trace_store = DomainTraceStore()
    rubric = load_default_rubric()
    bus = event_bus or EventBus()
    progress_path = run_dir / "progress.md"

    def worker_provider(spec: WorkerSpec) -> FakeProvider:
        return _fake_watch_worker_provider(spec, rubric.item_ids)

    scheduler = DiscoveryScheduler(
        run_id,
        provider_factory=worker_provider,
        tool_registry_factory=lambda spec: _tools_for_worker(spec, store, rubric),
        domain_store=store,
        trace_store=trace_store,
        sessions_dir=run_dir / "workers",
        max_concurrency=2,
        event_bus=bus,
        progress_writer=ProgressWriter(progress_path),
    )
    parent_provider = FakeProvider()
    parent_provider.set_responses(_fake_watch_parent_responses(rubric.item_ids))
    domain_tools = build_domain_tools(store, rubric=rubric)
    tools = [
        *domain_tools,
        spawn_worker_tool(
            scheduler=scheduler,
            agent_dir=default_agent_dir(),
            available_tool_names={tool.name for tool in domain_tools},
        ),
    ]
    harness = DiscoveryHarness(
        provider=parent_provider,
        tools=tools,
        session_store=JsonlSessionStore(run_dir / "parent.jsonl", run_id=run_id),
        trace_store=trace_store,
        domain_store=store,
        context_builder=ContextPackBuilder(),
        run_id=run_id,
        agent_run_id="orchestrator",
        worker_id="orchestrator",
        event_bus=bus,
    )
    attach_file_inbox(
        bus,
        harness,
        FileInbox(run_dir / "inbox"),
        run_id=run_id,
        agent_run_id="orchestrator",
        listen_agent_run_id="orchestrator",
    )

    assistant = await harness.prompt("Run the Phase 2 fake watch demo.")
    if assistant.is_error:
        error_message = assistant.metadata.get("error_message", "")
        raise RuntimeError(f"provider error: {error_message or 'unknown error'}")
    if output_path is not None:
        store.export_jsonl(output_path)
    if not store.candidates or not store.demand_reports:
        raise RuntimeError("watch demo did not produce a demand report")

    report = next(iter(store.demand_reports.values()))
    candidate = store.get_candidate(report.candidate_id)
    audit = store.audit_reports.get(report.audit_id)
    return DemoResult(
        candidate_title=candidate.title,
        candidate_id=candidate.candidate_id,
        evidence_ids=list(candidate.evidence_ids),
        audit_conclusion=audit.conclusion if audit is not None else "not_available",
        report_title=report.title,
        trace_event_count=len(store.trace_events),
        trace_path=output_path,
        progress_path=progress_path,
    )


async def run_real_demo(
    output_path: Path | None = None,
    endpoint_mode: str = "responses_compatible",
    base_url: str = "https://api.openai.com",
    endpoint_path: str = "",
    model: str = DEFAULT_REAL_MODEL,
    api_key_env: str = "DEMAND_DISCOVERY_API_KEY",
    api_key: str | None = None,
) -> DemoResult:
    """Run the demo with a configured Responses-compatible provider."""

    resolved_api_key = api_key if api_key is not None else os.environ.get(api_key_env, "")
    if not resolved_api_key:
        raise ValueError(f"missing API key env {api_key_env}")
    config = ModelConfig(
        provider="real",
        model=model,
        base_url=base_url,
        endpoint_mode=endpoint_mode,
        endpoint_path=endpoint_path,
        api_key_env=api_key_env,
    )
    provider = ResponsesProvider(config, resolved_api_key)
    return await _run_demo_with_provider(
        provider,
        task_brief=_real_demo_task_brief(),
        output_path=output_path,
    )


async def _run_demo_with_provider(
    provider: Any,
    task_brief: str,
    output_path: Path | None = None,
) -> DemoResult:
    store = DomainStore()
    harness = DiscoveryHarness(
        provider=provider,
        tools=build_domain_tools(store),
        domain_store=store,
        context_builder=ContextPackBuilder(),
    )

    assistant = await harness.prompt(task_brief)
    if assistant.is_error:
        error_message = assistant.metadata.get("error_message", "")
        raise RuntimeError(f"provider error: {error_message or 'unknown error'}")

    if output_path is not None:
        store.export_jsonl(output_path)

    if not store.candidates or not store.demand_reports:
        raise RuntimeError(
            "provider did not produce a demand report through domain tools "
            f"(sources={len(store.sources)}, evidence={len(store.evidence)}, "
            f"candidates={len(store.candidates)}, reports={len(store.demand_reports)})"
        )

    report = next(iter(store.demand_reports.values()))
    candidate = store.get_candidate(report.candidate_id)
    audit = (
        store.audit_reports.get(report.audit_id)
        if report.audit_id
        else next(iter(store.audit_reports.values()), None)
    )
    return DemoResult(
        candidate_title=candidate.title,
        candidate_id=candidate.candidate_id,
        evidence_ids=list(candidate.evidence_ids),
        audit_conclusion=audit.conclusion if audit is not None else "not_available",
        report_title=report.title,
        trace_event_count=len(store.trace_events),
        trace_path=output_path,
    )


def run_fake_demo_sync(output_path: Path | None = None) -> DemoResult:
    return asyncio.run(run_fake_demo(output_path))


def run_fake_watch_demo_sync(
    *,
    output_path: Path | None = None,
    output_root: Path,
    run_id: str,
    event_bus: EventBus | None = None,
) -> DemoResult:
    return asyncio.run(
        run_fake_watch_demo(
            output_path=output_path,
            output_root=output_root,
            run_id=run_id,
            event_bus=event_bus,
        )
    )


def run_real_demo_sync(
    output_path: Path | None = None,
    endpoint_mode: str = "responses_compatible",
    base_url: str = "https://api.openai.com",
    endpoint_path: str = "",
    model: str = DEFAULT_REAL_MODEL,
    api_key_env: str = "DEMAND_DISCOVERY_API_KEY",
    api_key: str | None = None,
) -> DemoResult:
    return asyncio.run(
        run_real_demo(
            output_path=output_path,
            endpoint_mode=endpoint_mode,
            base_url=base_url,
            endpoint_path=endpoint_path,
            model=model,
            api_key_env=api_key_env,
            api_key=api_key,
        )
    )


def build_dry_run_provider_request(
    endpoint_mode: str,
    base_url: str,
    model: str,
    api_key_env: str = "DEMAND_DISCOVERY_API_KEY",
    endpoint_path: str = "",
) -> dict[str, Any]:
    config = ModelConfig(
        provider="real",
        model=model,
        base_url=base_url,
        endpoint_mode=endpoint_mode,
        api_key_env=api_key_env,
        endpoint_path=endpoint_path,
    )
    request = build_provider_request(config, LLMContext(messages=[]), [], {})
    return {
        "endpoint_mode": endpoint_mode,
        "model": model,
        "url": request["url"],
        "payload_keys": sorted(request["payload"].keys()),
        "api_key_env": api_key_env,
    }


def format_demo_result(result: DemoResult) -> str:
    lines = [
        f"Candidate Demand: {result.candidate_title}",
        f"Candidate ID: {result.candidate_id}",
        f"Evidence: {', '.join(result.evidence_ids)}",
        f"Audit: {result.audit_conclusion}",
        f"Report: {result.report_title}",
        f"Trace events: {result.trace_event_count}",
    ]
    if result.trace_path is not None:
        lines.append(f"Trace path: {result.trace_path}")
    if result.progress_path is not None:
        lines.append(f"Progress path: {result.progress_path}")
    return "\n".join(lines)


def _fake_responses() -> list[FakeResponse]:
    return [
        FakeResponse(
            tool_calls=[
                {
                    "id": "call-source",
                    "name": "create_source_record",
                    "arguments": {
                        "source_id": "src-low-altitude-1",
                        "title": "Low-altitude operations create sensing constraints",
                        "source_name": "Demo Source",
                        "source_tier": "A",
                        "source_type": "demo",
                        "url_or_path": "demo://low-altitude-source",
                        "summary_text": "Public demo source for low-altitude sensing.",
                        "summary_source": "model_generated",
                        "collection_decision": "use_as_evidence",
                    },
                }
            ]
        ),
        FakeResponse(
            tool_calls=[
                {
                    "id": "call-evidence",
                    "name": "create_evidence_card",
                    "arguments": {
                        "evidence_id": "ev-low-altitude-1",
                        "source_id": "src-low-altitude-1",
                        "claim": "Low-altitude missions need more resilient sensing.",
                        "evidence_summary": "Terrain and clutter create residual sensing gaps.",
                        "excerpt": "Demo excerpt about sensing constraints.",
                        "source_location": "text:demo#para:1",
                        "evidence_assessment": "strong",
                    },
                }
            ]
        ),
        FakeResponse(
            tool_calls=[
                {
                    "id": "call-candidate",
                    "name": "create_or_update_candidate",
                    "arguments": {
                        "candidate_id": "cand-low-altitude",
                        "title": "Low-altitude resilient sensing",
                        "demand_statement": (
                            "Need resilient sensing for low-altitude operation "
                            "under terrain, clutter, and constrained deployment."
                        ),
                        "evidence_ids": ["ev-low-altitude-1"],
                        "open_questions": ["Which platforms face the strongest gap?"],
                        "solution_signals": ["distributed sensing"],
                    },
                }
            ]
        ),
        FakeResponse(
            tool_calls=[
                {
                    "id": "call-audit",
                    "name": "run_audit",
                    "arguments": {
                        "audit_id": "audit-low-altitude",
                        "candidate_id": "cand-low-altitude",
                        "conclusion": "approved",
                        "scorecard": _passing_default_scorecard(),
                        "comments": "Demo audit approved.",
                    },
                }
            ]
        ),
        FakeResponse(
            tool_calls=[
                {
                    "id": "call-report",
                    "name": "generate_demand_report",
                    "arguments": {
                        "report_id": "report-low-altitude",
                        "candidate_id": "cand-low-altitude",
                        "title": "Low-altitude resilient sensing report",
                        "body": "Demo report body with source and evidence summary.",
                        "evidence_ids": ["ev-low-altitude-1"],
                        "audit_id": "audit-low-altitude",
                    },
                }
            ]
        ),
        FakeResponse(text="done"),
    ]


def _fake_watch_worker_provider(
    spec: WorkerSpec,
    rubric_item_ids: list[str],
) -> FakeProvider:
    provider = FakeProvider()
    if spec.role == "reader":
        suffix = "a" if "A" in spec.task_brief else "b"
        provider.set_responses(
            [
                FakeResponse(
                    tool_calls=[
                        {
                            "id": f"src-{suffix}",
                            "name": "create_source_record",
                            "arguments": {
                                "source_id": f"src-{suffix}",
                                "title": f"Source {suffix}",
                                "source_name": "Phase 2 Watch Demo",
                                "source_tier": "A",
                                "source_type": "document",
                                "url_or_path": f"fixture://{suffix}",
                                "summary_text": "summary",
                                "summary_source": "manual",
                                "collection_decision": "use_as_evidence",
                            },
                        },
                        {
                            "id": f"ev-{suffix}",
                            "name": "create_evidence_card",
                            "arguments": {
                                "evidence_id": f"ev-{suffix}",
                                "source_id": f"src-{suffix}",
                                "claim": f"claim {suffix}",
                                "evidence_summary": f"summary {suffix}",
                                "excerpt": f"excerpt {suffix}",
                                "source_location": "p1",
                                "evidence_assessment": "strong",
                            },
                        },
                    ]
                ),
                FakeResponse(text=f"findings:\n- reader {suffix} completed"),
            ]
        )
        return provider

    provider.set_responses(
        [
            FakeResponse(
                tool_calls=[
                    {
                        "id": "audit-watch",
                        "name": "run_audit",
                        "arguments": {
                            "audit_id": "audit-watch",
                            "candidate_id": "cand-watch",
                            "conclusion": "approved",
                        "scorecard": _passing_scorecard(
                            rubric_item_ids,
                            evidence_ids=["ev-a", "ev-b"],
                        ),
                            "comments": "Phase 2 fake watch audit approved.",
                        },
                    }
                ]
            ),
            FakeResponse(text="findings:\n- audit approved"),
        ]
    )
    return provider


def _fake_watch_parent_responses(rubric_item_ids: list[str]) -> list[FakeResponse]:
    return [
        FakeResponse(
            tool_calls=[
                {
                    "id": "spawn-readers",
                    "name": "spawn_worker",
                    "arguments": {
                        "tasks": [
                            {"agent": "reader", "task": "Read source A"},
                            {"agent": "reader", "task": "Read source B"},
                        ]
                    },
                }
            ]
        ),
        FakeResponse(
            tool_calls=[
                {
                    "id": "candidate",
                    "name": "create_or_update_candidate",
                    "arguments": {
                        "candidate_id": "cand-watch",
                        "title": "Phase 2 watched demand",
                        "demand_statement": "Need a validated multi-worker demand discovery path.",
                        "status": "candidate_demand",
                        "evidence_ids": ["ev-a", "ev-b"],
                        "open_questions": ["Confirm evidence strength."],
                    },
                }
            ]
        ),
        FakeResponse(
            tool_calls=[
                {
                    "id": "spawn-auditor",
                    "name": "spawn_worker",
                    "arguments": {"agent": "auditor", "task": "Audit cand-watch"},
                }
            ]
        ),
        FakeResponse(
            tool_calls=[
                {
                    "id": "report",
                    "name": "generate_demand_report",
                    "arguments": {
                        "report_id": "report-watch",
                        "candidate_id": "cand-watch",
                        "audit_id": "audit-watch",
                        "title": "Phase 2 watched demand report",
                        "evidence_ids": ["ev-a", "ev-b"],
                        "demand_type": "inferred",
                        "sections": {
                            key: f"{key} content"
                            for key in REQUIRED_SECTIONS
                        },
                    },
                }
            ]
        ),
        FakeResponse(text="done"),
    ]


def _tools_for_worker(spec: WorkerSpec, store: DomainStore, rubric) -> list[Any]:
    active = set(spec.tools)
    return [tool for tool in build_domain_tools(store, rubric=rubric) if tool.name in active]


def _passing_scorecard(
    item_ids: list[str],
    *,
    evidence_ids: list[str],
) -> dict[str, Any]:
    scorecard: dict[str, Any] = {
        item_id: {"verdict": "pass", "reason": "fake watch fixture passes this item"}
        for item_id in item_ids
    }
    scorecard["evidence_support"] = _passing_evidence_support(evidence_ids)
    return scorecard


def _real_demo_task_brief() -> str:
    rubric_item_ids = ", ".join(load_default_rubric().item_ids)
    return (
        "Run a compact demand discovery demo. Use the available tools in this "
        "exact order and finish with a short text response: "
        "1 create_source_record with source_id src-real-demo-1, a concise title, "
        "source_name Real Provider Demo, source_tier A, source_type demo, "
        "url_or_path demo://real-provider, summary_text, summary_source "
        "model_generated, collection_decision use_as_evidence. "
        "2 create_evidence_card with evidence_id ev-real-demo-1, source_id "
        "src-real-demo-1, claim, evidence_summary, excerpt, source_location "
        "text:real-demo#para:0, evidence_assessment strong. "
        "3 create_or_update_candidate with candidate_id cand-real-demo, title, "
        "demand_statement, evidence_ids [ev-real-demo-1], open_questions, and "
        "solution_signals. "
        "4 run_audit with audit_id audit-real-demo, candidate_id cand-real-demo, "
        "conclusion approved, a complete scorecard covering these rubric item "
        f"ids ({rubric_item_ids}) plus scorecard.evidence_support with a direct "
        "evidence review for ev-real-demo-1, and comments. "
        "5 generate_demand_report with report_id report-real-demo, candidate_id "
        "cand-real-demo, title, body, evidence_ids [ev-real-demo-1], and "
        "audit_id audit-real-demo."
    )


def _passing_default_scorecard() -> dict[str, Any]:
    scorecard: dict[str, Any] = {
        item_id: {"verdict": "pass", "reason": "demo fixture passes this item"}
        for item_id in load_default_rubric().item_ids
    }
    scorecard["evidence_support"] = _passing_evidence_support(["ev-low-altitude-1"])
    return scorecard


def _passing_evidence_support(evidence_ids: list[str]) -> dict[str, Any]:
    return {
        "verdict": "pass",
        "reason": "fixture audit evidence directly supports the core conclusion",
        "evidence_reviews": {
            evidence_id: {
                "evidence_id": evidence_id,
                "support_level": "direct",
                "support_type": "inferred_gap",
                "used_for_core": True,
                "reason": "fixture body evidence supports the candidate",
                "missing_link": "",
            }
            for evidence_id in evidence_ids
        },
    }
