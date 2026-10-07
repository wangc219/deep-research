"""Topic-only autonomous research runner entrypoint."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from uuid import uuid4

from knowledgegraph.demand_discovery.domain.audit_rubric import load_default_rubric
from knowledgegraph.demand_discovery.domain.models import (
    AuditReport,
    DemandReport,
    DomainTraceEvent,
)
from knowledgegraph.demand_discovery.domain.report import (
    determine_autonomous_report_review_status,
    validate_autonomous_report_gate,
)
from knowledgegraph.demand_discovery.domain.report_context import (
    CuratedReportItem,
    ReportContextBundle,
)
from knowledgegraph.demand_discovery.domain.research_state import ResearchRound
from knowledgegraph.demand_discovery.domain.source_registry import (
    SourceRegistry,
    default_source_whitelist_path,
)
from knowledgegraph.demand_discovery.domain.source_strategy import (
    SourceStrategy,
    SourceStrategyPlanner,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore
from knowledgegraph.demand_discovery.domain.tools import run_audit_tool
from knowledgegraph.demand_discovery.harness.audit_context import (
    build_audit_context_bundle,
)
from knowledgegraph.demand_discovery.harness.budget import RunBudget
from knowledgegraph.demand_discovery.harness.context_pack import ContextPack
from knowledgegraph.demand_discovery.harness.research_loop import ResearchLoopController
from knowledgegraph.demand_discovery.harness.report_context import (
    ArtifactResolver,
    ContextIndexer,
    ContextVerifier,
)
from knowledgegraph.demand_discovery.harness.report_context_curator import (
    run_report_context_curator_agent,
)
from knowledgegraph.demand_discovery.harness.report_publisher import publish_report
from knowledgegraph.demand_discovery.harness.reporter import run_reporter_agent
from knowledgegraph.demand_discovery.harness.scheduler import (
    DiscoveryScheduler,
    WorkerSpec,
)
from knowledgegraph.demand_discovery.harness.types import AssistantContentBlock
from knowledgegraph.demand_discovery.llm.config_env import (
    env_value,
    load_demand_discovery_dotenv,
)
from knowledgegraph.demand_discovery.llm.fake_provider import FakeProvider, FakeResponse
from knowledgegraph.demand_discovery.llm.model_config import (
    DEFAULT_AGENT_MAX_TOKENS,
    DEFAULT_CONTEXT_TOKEN_BUDGET,
    DEFAULT_REAL_MODEL,
    ModelConfig,
)
from knowledgegraph.demand_discovery.llm.responses_adapter import ResponsesProvider
from knowledgegraph.demand_discovery.llm.types import AssistantMessage, LLMContext
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore


@dataclass(frozen=True)
class AutonomousResearchResult:
    run_id: str
    run_dir: Path
    source_strategy_id: str
    round_summary_path: Path
    domain_path: Path
    trace_path: Path


async def run_autonomous_research(
    *,
    mode: str,
    topic: str,
    output_root: Path,
    run_id: str,
    max_rounds: int = 2,
    seed_urls: list[str] | None = None,
    allow_browser: bool = False,
    source_whitelist_path: str | Path | None = None,
    endpoint_mode: str = "responses_compatible",
    base_url: str = "https://api.openai.com",
    endpoint_path: str = "",
    model: str = DEFAULT_REAL_MODEL,
    api_key_env: str = "DEMAND_DISCOVERY_API_KEY",
    api_key: str | None = None,
) -> AutonomousResearchResult:
    if mode not in {"fake", "real"}:
        raise ValueError("mode must be fake or real")
    if not topic.strip():
        raise ValueError("topic is required")
    resolved_api_key = ""
    if mode == "real":
        resolved_api_key = _resolve_real_api_key(api_key, api_key_env)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    registry = SourceRegistry.load(source_whitelist_path or default_source_whitelist_path())
    strategy = SourceStrategyPlanner(registry).plan(
        topic=topic,
        seed_urls=seed_urls,
        allow_browser=allow_browser,
        min_sources=4 if mode == "real" else 2,
    )
    store = DomainStore(tier_status_cap=registry.tier_status_cap)
    store.upsert_source_strategy(strategy)
    if mode == "real":
        return await _run_real_strategy_seed_research(
            topic=topic,
            output_root=output_root,
            run_dir=run_dir,
            run_id=run_id,
            max_rounds=max_rounds,
            seed_urls=seed_urls,
            allow_browser=allow_browser,
            source_whitelist_path=source_whitelist_path,
            strategy=strategy,
            store=store,
            registry=registry,
            endpoint_mode=endpoint_mode,
            base_url=base_url,
            endpoint_path=endpoint_path,
            model=model,
            api_key_env=api_key_env,
            api_key=resolved_api_key,
        )
    if max_rounds > 1:
        controller = ResearchLoopController(
            run_id=run_id,
            topic=topic,
            strategy=strategy,
            store=store,
            registry=registry,
            max_rounds=max_rounds,
            judge_provider_factory=_fixture_judge_provider_factory(topic=topic),
            judge_sessions_dir=run_dir / "judge",
        )
        loop_result = await controller.run_fake_loop_async()
        trace = list(loop_result["trace"])
        audit_summary, report_summary = _complete_fake_audit_and_report(
            store,
            loop_result=loop_result,
            trace=trace,
            run_dir=run_dir,
        )
        summary = {
            "run_id": run_id,
            "mode": mode,
            "topic": topic,
            "max_rounds": max_rounds,
            "source_strategy": strategy.to_dict(),
            "rounds": loop_result["rounds"],
            "worker_tasks": _first_round_worker_tasks(strategy),
            "candidate_synthesis": loop_result["candidate_synthesis"],
            "audit": audit_summary,
            "report": report_summary,
            "trace": trace,
            "open_search_plans": loop_result.get("open_search_plans", []),
        }
        round_summary_path = run_dir / "round_summary.json"
        round_summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        domain_path = run_dir / "domain.jsonl"
        store.export_jsonl(domain_path)
        trace_path = run_dir / "trace.jsonl"
        _write_domain_trace_jsonl(trace_path, store)
        _write_run_config(
            run_dir,
            run_id=run_id,
            mode=mode,
            topic=topic,
            max_rounds=max_rounds,
            seed_urls=seed_urls,
            allow_browser=allow_browser,
            source_whitelist_path=source_whitelist_path,
            endpoint_mode=endpoint_mode,
            base_url=base_url,
            endpoint_path=endpoint_path,
            model=model,
            api_key_env=api_key_env,
        )
        return AutonomousResearchResult(
            run_id=run_id,
            run_dir=run_dir,
            source_strategy_id=strategy.strategy_id,
            round_summary_path=round_summary_path,
            domain_path=domain_path,
            trace_path=trace_path,
        )
    first_round = ResearchRound(
        round_id="round-1",
        run_id=run_id,
        index=1,
        topic=topic,
        hypothesis=f"围绕“{topic}”发现公开信源线索并形成可审计 evidence。",
        source_strategy_id=strategy.strategy_id,
        worker_report_ids=[],
        judgement_id=None,
        next_round_plan={},
        stop_reason=None,
        status="planned",
        created_at=_now(),
        updated_at=_now(),
    )
    store.upsert_research_round(first_round)
    worker_tasks = _first_round_worker_tasks(strategy)
    summary = {
        "run_id": run_id,
        "mode": mode,
        "topic": topic,
        "max_rounds": max_rounds,
        "source_strategy": strategy.to_dict(),
        "rounds": [first_round.to_dict()],
        "worker_tasks": worker_tasks,
        "trace": ["source_strategy", "research_round_planned", "worker_tasks_planned"],
    }
    round_summary_path = run_dir / "round_summary.json"
    round_summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    trace_path = run_dir / "trace.jsonl"
    _append_trace_event(
        store,
        event_type="source_strategy_selected",
        actor="autonomous_research",
        target_type="SourceStrategy",
        target_id=strategy.strategy_id,
        output_refs=[strategy.strategy_id],
        summary=f"selected source strategy {strategy.strategy_id}",
        payload={"mode": mode},
    )
    _append_trace_event(
        store,
        event_type="research_round_planned",
        actor="autonomous_research",
        target_type="ResearchRound",
        target_id=first_round.round_id,
        input_refs=[strategy.strategy_id],
        output_refs=[first_round.round_id],
        summary=f"planned {first_round.round_id}",
        payload={"worker_task_count": len(worker_tasks)},
    )
    domain_path = run_dir / "domain.jsonl"
    store.export_jsonl(domain_path)
    _write_domain_trace_jsonl(trace_path, store)
    _write_run_config(
        run_dir,
        run_id=run_id,
        mode=mode,
        topic=topic,
        max_rounds=max_rounds,
        seed_urls=seed_urls,
        allow_browser=allow_browser,
        source_whitelist_path=source_whitelist_path,
        endpoint_mode=endpoint_mode,
        base_url=base_url,
        endpoint_path=endpoint_path,
        model=model,
        api_key_env=api_key_env,
    )
    return AutonomousResearchResult(
        run_id=run_id,
        run_dir=run_dir,
        source_strategy_id=strategy.strategy_id,
        round_summary_path=round_summary_path,
        domain_path=domain_path,
        trace_path=trace_path,
    )


def run_autonomous_research_sync(**kwargs: Any) -> AutonomousResearchResult:
    return asyncio.run(run_autonomous_research(**kwargs))


def _first_round_worker_tasks(strategy: SourceStrategy) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for index, source in enumerate(strategy.selected_sources, start=1):
        seed_url = source.entry_urls[0] if source.entry_urls else ""
        tasks.append(
            {
                "task_id": f"worker-task-{index}",
                "round_id": "round-1",
                "role": "reader",
                "source_name": source.source_name,
                "seed_url": seed_url,
                "content_languages": list(source.content_languages),
                "planned_queries": list(source.planned_queries),
                "tools": [
                    "classify_source_page",
                    "discover_articles",
                    "download_document",
                    "read_document",
                ],
                "task_brief": (
                    f"Use discover_articles on {seed_url} for topic {strategy.topic}. "
                    "Only create EvidenceCard after reading article or downloaded document body."
                ),
            }
        )
    return tasks


def _fixture_judge_provider_factory(
    *,
    topic: str,
) -> Callable[[], FakeProvider]:
    """Build a fake model provider that still writes judgement through tools."""

    def provider_factory() -> FakeProvider:
        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(
                    factory=lambda context, state: _fixture_judge_response(
                        context,
                        state,
                        topic=topic,
                    )
                ),
                FakeResponse(text="judgement recorded"),
            ]
        )
        return provider

    return provider_factory


def _fixture_judge_response(
    context: LLMContext,
    state: dict[str, Any],
    *,
    topic: str,
) -> AssistantMessage:
    payload = _fixture_judge_payload_from_context(context, topic=topic)
    call_id = f"fixture-judge-{state.get('call_count', 1)}-{payload['round_id']}"
    return AssistantMessage(
        content=[
            AssistantContentBlock(
                type="tool_call",
                id=call_id,
                name="record_judgement",
                arguments=payload,
            )
        ]
    )


def _fixture_judge_payload_from_context(
    context: LLMContext,
    *,
    topic: str,
) -> dict[str, Any]:
    brief = _latest_judge_task_brief(context)
    data = _json_payload_from_judge_brief(brief)
    round_id = str(data.get("round_id") or "round-unknown")
    worker_reports = [
        report for report in data.get("worker_reports", []) if isinstance(report, dict)
    ]
    evidence_rows = [
        row for row in data.get("evidence", []) if isinstance(row, dict)
    ]
    report_ids = _dedupe_refs(
        [
            str(report.get("report_id") or report.get("agent_run_id") or "")
            for report in worker_reports
        ]
    )
    evidence_ids = _dedupe_refs(
        [
            str(evidence_id)
            for report in worker_reports
            for evidence_id in [
                *list(report.get("evidence_refs") or []),
                *list(report.get("new_evidence_cards") or []),
            ]
        ]
    )
    lead_ids = _dedupe_refs(
        [
            str(lead_id)
            for report in worker_reports
            for lead_id in list(report.get("lead_refs") or [])
        ]
    )
    evidence_strength_map = {
        str(row.get("evidence_id")): _fixture_evidence_strength(row)
        for row in evidence_rows
        if str(row.get("evidence_id", "")).strip()
    }
    for evidence_id in evidence_ids:
        evidence_strength_map.setdefault(evidence_id, "unassessed")
    has_strong_evidence = any(
        strength in {"strong", "direct"}
        for strength in evidence_strength_map.values()
    )
    finding_reports = _finding_report_index(worker_reports)
    consensus_points = [
        {
            "text": text,
            "worker_report_ids": ids,
            "evidence_ids": evidence_ids,
            "lead_ids": lead_ids,
        }
        for text, ids in finding_reports.items()
        if len(ids) >= 2
    ]
    if not consensus_points and worker_reports:
        fallback_text = _first_finding(worker_reports) or f"围绕“{topic}”形成初步线索"
        consensus_points = [
            {
                "text": fallback_text,
                "worker_report_ids": report_ids or ["fixture-worker"],
                "evidence_ids": evidence_ids,
                "lead_ids": lead_ids,
            }
        ]
    blind_spots = [
        {
            "text": question,
            "worker_report_ids": _report_ids_for_open_question(
                worker_reports,
                question,
            ),
            "evidence_ids": [],
            "lead_ids": lead_ids,
        }
        for question in _unique_report_values(worker_reports, "open_questions")
    ]
    contradictions = [
        {
            "text": risk,
            "worker_report_ids": _report_ids_for_open_question(
                worker_reports,
                risk,
                field="risk_or_conflict",
            ),
            "evidence_ids": evidence_ids,
            "lead_ids": lead_ids,
        }
        for risk in _unique_report_values(worker_reports, "risk_or_conflict")
    ]
    needs_more = bool(
        blind_spots
        or contradictions
        or not has_strong_evidence
        or any(bool(report.get("need_more_sources")) for report in worker_reports)
    )
    next_round_plan = (
        _fixture_continue_plan(
            round_id=round_id,
            topic=topic,
            worker_report_ids=report_ids,
            evidence_ids=evidence_ids,
            lead_ids=lead_ids,
            blind_spots=blind_spots,
        )
        if needs_more
        else {
            "plan_version": 1,
            "round_id": round_id,
            "summary": "已有证据足以进入候选合成",
            "controller_tasks": [],
            "worker_briefs": {},
            "remaining_open_questions": [],
            "stop_candidate_reason": "judge_stop",
        }
    )
    return {
        "judgement_id": f"judge-fixture-{round_id}",
        "round_id": round_id,
        "consensus_points": consensus_points,
        "contradictions": contradictions,
        "partial_coverage": blind_spots[:1] if needs_more else [],
        "unique_insights": _fixture_unique_insights(
            finding_reports,
            evidence_ids=evidence_ids,
            lead_ids=lead_ids,
        ),
        "blind_spots": blind_spots,
        "evidence_strength_map": evidence_strength_map,
        "next_round_plan": next_round_plan,
        "stop_or_continue": "continue" if needs_more else "stop",
        "rationale": (
            "fixture model judgement: evidence still needs open-source cross-check"
            if needs_more
            else "fixture model judgement: direct evidence is sufficient for synthesis"
        ),
    }


def _fixture_continue_plan(
    *,
    round_id: str,
    topic: str,
    worker_report_ids: list[str],
    evidence_ids: list[str],
    lead_ids: list[str],
    blind_spots: list[dict[str, Any]],
) -> dict[str, Any]:
    question = (
        str(blind_spots[0].get("text", "")).strip()
        if blind_spots
        else f"补充“{topic}”的独立公开正文交叉验证"
    )
    task_id = "task-open-1"
    query = _fixture_search_query(topic, question)
    return {
        "plan_version": 1,
        "round_id": round_id,
        "summary": "白名单 route/query 未形成足够直接证据，下一轮开放搜索补证",
        "controller_tasks": [
            {
                "task_id": task_id,
                "objective": question,
                "gap_type": "missing_direct_evidence",
                "routing_hint": "open_search_candidate",
                "source_scope": "open_web_after_whitelist_exhausted",
                "input_refs": {
                    "worker_report_ids": worker_report_ids,
                    "evidence_ids": evidence_ids,
                    "lead_ids": lead_ids,
                },
                "query_revisions": [
                    {"language": "auto", "query": query},
                ],
                "completion_check": (
                    "白名单 route/query 已耗尽或无新增后，开放搜索读取正文并创建 EvidenceCard；"
                    "如果只能得到 partial/adjacent evidence，需明确说明"
                ),
            }
        ],
        "worker_briefs": {
            task_id: (
                f"围绕“{topic}”补充独立公开正文证据。优先 query：{query}。"
                "必须读取正文并记录来源质量后再创建 EvidenceCard。"
            )
        },
        "remaining_open_questions": [question],
        "stop_candidate_reason": "",
    }


def _latest_judge_task_brief(context: LLMContext) -> str:
    for message in reversed(context.messages):
        content = getattr(message, "content", "")
        if isinstance(content, str) and '"worker_reports"' in content:
            return content
    raise ValueError("fixture judge received no task brief")


def _json_payload_from_judge_brief(brief: str) -> dict[str, Any]:
    if "```json" not in brief:
        raise ValueError("fixture judge task brief has no json payload")
    raw = brief.split("```json", 1)[1].split("```", 1)[0]
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("fixture judge json payload must be an object")
    return payload


def _fixture_evidence_strength(row: dict[str, Any]) -> str:
    text = str(row.get("evidence_assessment", "") or "").lower()
    if any(token in text for token in ["strong", "direct", "较强", "直接"]):
        return "strong"
    if any(token in text for token in ["partial", "部分"]):
        return "partial"
    if any(token in text for token in ["adjacent", "相邻"]):
        return "adjacent"
    if any(token in text for token in ["weak", "弱"]):
        return "weak"
    return text or "unassessed"


def _finding_report_index(worker_reports: list[dict[str, Any]]) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for report in worker_reports:
        report_id = str(report.get("report_id") or report.get("agent_run_id") or "")
        for finding in report.get("partial_findings") or []:
            text = str(finding).strip()
            if not text:
                continue
            rows.setdefault(text, [])
            if report_id and report_id not in rows[text]:
                rows[text].append(report_id)
    return rows


def _fixture_unique_insights(
    finding_reports: dict[str, list[str]],
    *,
    evidence_ids: list[str],
    lead_ids: list[str],
) -> list[dict[str, Any]]:
    return [
        {
            "text": text,
            "worker_report_ids": ids,
            "evidence_ids": evidence_ids,
            "lead_ids": lead_ids,
        }
        for text, ids in finding_reports.items()
        if len(ids) == 1
    ][:3]


def _first_finding(worker_reports: list[dict[str, Any]]) -> str:
    for report in worker_reports:
        for finding in report.get("partial_findings") or []:
            text = str(finding).strip()
            if text:
                return text
    return ""


def _unique_report_values(
    worker_reports: list[dict[str, Any]],
    field: str,
) -> list[str]:
    return _dedupe_refs(
        [
            str(item)
            for report in worker_reports
            for item in list(report.get(field) or [])
        ]
    )


def _report_ids_for_open_question(
    worker_reports: list[dict[str, Any]],
    value: str,
    *,
    field: str = "open_questions",
) -> list[str]:
    return _dedupe_refs(
        [
            str(report.get("report_id") or report.get("agent_run_id") or "")
            for report in worker_reports
            if value in {str(item) for item in list(report.get(field) or [])}
        ]
    ) or ["fixture-worker"]


def _fixture_search_query(topic: str, question: str) -> str:
    words = " ".join(part for part in [topic.strip(), question.strip()] if part)
    return words[:120] if words else topic


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _complete_fake_audit_and_report(
    store: DomainStore,
    *,
    loop_result: dict[str, Any],
    trace: list[str],
    run_dir: Path,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    return _complete_autonomous_audit_and_report(
        store,
        loop_result=loop_result,
        trace=trace,
        run_dir=run_dir,
        audit_actor="fixture-auditor",
        audit_comments="Fake autonomous audit approved for offline gate exercise.",
        audit_reason="fake autonomous gate pass",
        audit_mode="fixture",
    )


def _complete_autonomous_audit_and_report(
    store: DomainStore,
    *,
    loop_result: dict[str, Any],
    trace: list[str],
    run_dir: Path,
    audit_actor: str,
    audit_comments: str,
    audit_reason: str,
    audit_mode: str = "fixture",
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if audit_mode == "real":
        raise ValueError("real path requires auditor worker")
    draft = loop_result.get("candidate_synthesis")
    if not isinstance(draft, dict) or draft.get("status") != "synthesized":
        return None, None
    candidate_id = str(draft["candidate_id"])
    judgement_id = str(draft["judgement_id"])
    rubric = load_default_rubric()
    audit_id = f"audit-{candidate_id}"
    scorecard = _fixture_audit_scorecard(
        rubric_item_ids=rubric.item_ids,
        evidence_ids=list(draft["evidence_ids"]),
        audit_reason=audit_reason,
    )
    audit = store.append_audit(
        AuditReport(
            audit_id=audit_id,
            candidate_id=candidate_id,
            conclusion="approved",
            scorecard=scorecard,
            comments=audit_comments,
            required_rework=[],
            created_by=audit_actor,
            created_at=_now(),
        )
    )
    trace.append("audit")
    audit_trace = _append_trace_event(
        store,
        event_type="audit_completed",
        actor=audit_actor,
        target_type="AuditReport",
        target_id=audit.audit_id,
        input_refs=_dedupe_refs(
            [
                candidate_id,
                judgement_id,
                *list(draft["evidence_ids"]),
                *_open_source_lineage_refs(store, list(draft["evidence_ids"])),
            ]
        ),
        output_refs=[audit.audit_id],
        summary=f"audit completed {audit.audit_id}",
        decision=audit.conclusion,
        rationale=audit.comments,
        payload={
            "audit_mode": audit_mode,
            "audit_comments": audit_comments,
            "decision": audit.conclusion,
            "evidence_support": scorecard.get("evidence_support", {}),
            "required_rework": [],
        },
    )
    return _complete_autonomous_report_after_audit(
        store,
        loop_result=loop_result,
        trace=trace,
        run_dir=run_dir,
        audit=audit,
        audit_trace=audit_trace,
    )


def _fixture_audit_scorecard(
    *,
    rubric_item_ids: list[str],
    evidence_ids: list[str],
    audit_reason: str,
) -> dict[str, Any]:
    scorecard = {
        item_id: {"verdict": "pass", "reason": audit_reason}
        for item_id in rubric_item_ids
    }
    scorecard["evidence_support"] = {
        "verdict": "pass",
        "reason": "fixture audit treats fake evidence as direct for offline gate exercise",
        "evidence_reviews": {
            evidence_id: {
                "evidence_id": evidence_id,
                "support_level": "direct",
                "support_type": "inferred_gap",
                "used_for_core": True,
                "reason": "deterministic fake evidence supports fake candidate",
                "missing_link": "",
            }
            for evidence_id in evidence_ids
        },
    }
    return scorecard


def _complete_autonomous_report_after_audit(
    store: DomainStore,
    *,
    loop_result: dict[str, Any],
    trace: list[str],
    run_dir: Path,
    audit: AuditReport,
    audit_trace: DomainTraceEvent | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    draft = loop_result.get("candidate_synthesis")
    if not isinstance(draft, dict) or draft.get("status") != "synthesized":
        return None, None
    candidate_id = str(draft["candidate_id"])
    judgement_id = str(draft["judgement_id"])
    judgement = store.judgement_reports[judgement_id]
    if audit_trace is None:
        audit_trace = _latest_trace_for(store, audit.audit_id, "audit_completed")
    evidence_ids = list(draft["evidence_ids"])
    review_status = determine_autonomous_report_review_status(
        judgement,
        audit=audit,
        store=store,
        evidence_ids=evidence_ids,
    )
    validate_autonomous_report_gate(
        store,
        candidate_id=candidate_id,
        audit_id=audit.audit_id,
        evidence_ids=evidence_ids,
        judgement_id=judgement_id,
        review_status=review_status,
    )
    report_id = f"report-{candidate_id}"
    tier_cap_error: ValueError | None = None
    try:
        store.update_candidate_status(
            candidate_id,
            "demand_report",
            "autonomous report gate reached",
            "autonomous_research",
        )
    except ValueError as exc:
        if "exceeds source tier cap" not in str(exc):
            raise
        tier_cap_error = exc
        review_status = _degrade_review_status_for_tier_cap(review_status)
    report_context = _build_fixture_report_context(
        store,
        run_id=str(loop_result.get("run_id", "")),
        topic=str(loop_result.get("topic", "")),
        candidate_id=candidate_id,
        judgement_id=judgement_id,
        audit_id=audit.audit_id,
        review_status=review_status,
        run_dir=run_dir,
        artifacts=None,
    )
    body = _render_autonomous_report_body(
        report_id=report_id,
        candidate_id=candidate_id,
        judgement_id=judgement_id,
        review_status=review_status,
        title=str(draft["title"]),
        demand_statement=str(draft["demand_statement"]),
        evidence_ids=list(draft["evidence_ids"]),
        open_questions=list(draft.get("open_questions", [])),
        audit_comments=audit.comments,
        required_rework=list(audit.required_rework),
    )
    if tier_cap_error is not None:
        degraded_reason = f"source tier cap blocked demand_report: {tier_cap_error}"
        report_trace = _append_trace_event(
            store,
            event_type="report_generated",
            actor="autonomous_research",
            target_type="DemandReportDraft",
            target_id=report_id,
            input_refs=_dedupe_refs(
                [
                    candidate_id,
                    audit.audit_id,
                    judgement_id,
                    *list(draft["evidence_ids"]),
                    *_open_source_lineage_refs(store, list(draft["evidence_ids"])),
                ]
            ),
            output_refs=[report_id],
            summary=f"degraded report draft generated {report_id}",
            decision=review_status,
            rationale=degraded_reason,
            payload={
                "storage_status": "degraded_report_draft",
                "degraded_reason": degraded_reason,
                "candidate_status": store.candidates[candidate_id].status,
            },
        )
        domain_trace_ids = _domain_trace_ids_for_report(
            store,
            required=[
                audit_trace.domain_trace_id if audit_trace is not None else None,
                report_trace.domain_trace_id,
            ],
        )
        (run_dir / "report.md").write_text(
            body + "\n\n## 门禁降级\n" + degraded_reason + "\n",
            encoding="utf-8",
        )
        trace.append("report")
        return audit.to_dict(), {
            "report_id": report_id,
            "candidate_id": candidate_id,
            "title": str(draft["title"]),
            "body": body,
            "evidence_ids": list(draft["evidence_ids"]),
            "audit_id": audit.audit_id,
            "domain_trace_ids": domain_trace_ids,
            "created_at": _now().isoformat(),
            "review_status": review_status,
            "storage_status": "degraded_report_draft",
            "degraded_reason": degraded_reason,
            "candidate_status": store.candidates[candidate_id].status,
        }
    report_trace = _append_trace_event(
        store,
        event_type="report_generated",
        actor="autonomous_research",
        target_type="DemandReport",
        target_id=report_id,
        input_refs=_dedupe_refs(
            [
                candidate_id,
                audit.audit_id,
                judgement_id,
                *list(draft["evidence_ids"]),
                *_open_source_lineage_refs(store, list(draft["evidence_ids"])),
            ]
        ),
        output_refs=[report_id],
        summary=f"report generated {report_id}",
        decision=review_status,
        rationale="autonomous report gate completed",
    )
    domain_trace_ids = _domain_trace_ids_for_report(
        store,
        required=[
            audit_trace.domain_trace_id if audit_trace is not None else None,
            report_trace.domain_trace_id,
        ],
    )
    report = store.append_demand_report(
        DemandReport(
            report_id=report_id,
            candidate_id=candidate_id,
            title=str(draft["title"]),
            body=body,
            evidence_ids=list(draft["evidence_ids"]),
            audit_id=audit.audit_id,
            domain_trace_ids=domain_trace_ids,
            created_at=_now(),
            review_status=review_status,
        )
    )
    published = publish_report(
        store,
        report_id=report.report_id,
        output_dir=run_dir,
        report_context_bundle_id=report_context.bundle_id,
    )
    _append_trace_event(
        store,
        event_type="report_published",
        actor="report_publisher",
        target_type="DemandReport",
        target_id=report.report_id,
        input_refs=[report.report_id, report_context.bundle_id],
        output_refs=[str(published.report_md_path), str(published.manifest_path)],
        summary="report published to markdown and manifest",
        payload={
            "report_md_path": str(published.report_md_path),
            "report_manifest_path": str(published.manifest_path),
        },
    )
    trace.append("report")
    report_summary = report.to_dict()
    report_summary["report_mode"] = "fixture"
    report_summary["report_context_bundle_id"] = report_context.bundle_id
    report_summary["report_md_path"] = str(published.report_md_path)
    report_summary["report_manifest_path"] = str(published.manifest_path)
    return audit.to_dict(), report_summary


async def _complete_autonomous_report_after_audit_async(
    store: DomainStore,
    *,
    loop_result: dict[str, Any],
    trace: list[str],
    run_dir: Path,
    audit: AuditReport,
    report_mode: str,
    reporter_provider: Any | None,
    artifacts: ArtifactStore | ArtifactResolver | None,
    curator_provider: Any | None = None,
    audit_trace: DomainTraceEvent | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if report_mode != "real":
        return _complete_autonomous_report_after_audit(
            store,
            loop_result=loop_result,
            trace=trace,
            run_dir=run_dir,
            audit=audit,
            audit_trace=audit_trace,
        )
    if reporter_provider is None or curator_provider is None or artifacts is None:
        raise RuntimeError(
            "real report generation requires curator_provider, reporter_provider, and artifacts"
        )
    draft = loop_result.get("candidate_synthesis")
    if not isinstance(draft, dict) or draft.get("status") != "synthesized":
        return None, None
    candidate_id = str(draft["candidate_id"])
    judgement_id = str(draft["judgement_id"])
    judgement = store.judgement_reports[judgement_id]
    if audit_trace is None:
        audit_trace = _latest_trace_for(store, audit.audit_id, "audit_completed")
    evidence_ids = list(draft["evidence_ids"])
    review_status = determine_autonomous_report_review_status(
        judgement,
        audit=audit,
        store=store,
        evidence_ids=evidence_ids,
    )
    validate_autonomous_report_gate(
        store,
        candidate_id=candidate_id,
        audit_id=audit.audit_id,
        evidence_ids=evidence_ids,
        judgement_id=judgement_id,
        review_status=review_status,
    )
    try:
        store.update_candidate_status(
            candidate_id,
            "demand_report",
            "autonomous reporter path reached",
            "autonomous_research",
        )
    except ValueError as exc:
        if "exceeds source tier cap" not in str(exc):
            raise
        review_status = _degrade_review_status_for_tier_cap(review_status)
    report_context = await _build_verified_report_context(
        store,
        run_id=str(loop_result.get("run_id", "")),
        topic=str(loop_result.get("topic", "")),
        candidate_id=candidate_id,
        judgement_id=judgement_id,
        audit_id=audit.audit_id,
        review_status=review_status,
        run_dir=run_dir,
        artifacts=artifacts,
        curator_provider=curator_provider,
    )
    reporter_assigned = _append_trace_event(
        store,
        event_type="reporter_assigned",
        actor="autonomous_research",
        target_type="ReportContextBundle",
        target_id=report_context.bundle_id,
        input_refs=[candidate_id, judgement_id, audit.audit_id],
        output_refs=[report_context.bundle_id],
        summary="reporter assigned to verified report context",
        decision="assigned",
    )
    reporter_result = await run_reporter_agent(
        provider=reporter_provider,
        store=store,
        artifacts=artifacts,
        bundle_id=report_context.bundle_id,
        session_path=run_dir / "reporter_session.jsonl",
        system_prompt=_load_agent_prompt("reporter"),
    )
    published = publish_report(
        store,
        report_id=reporter_result.report_id,
        output_dir=run_dir,
        report_context_bundle_id=report_context.bundle_id,
    )
    published_trace = _append_trace_event(
        store,
        event_type="report_published",
        actor="report_publisher",
        target_type="DemandReport",
        target_id=reporter_result.report_id,
        input_refs=[reporter_result.report_id, report_context.bundle_id],
        output_refs=[str(published.report_md_path), str(published.manifest_path)],
        summary="report published to markdown and manifest",
        payload={
            "report_md_path": str(published.report_md_path),
            "report_manifest_path": str(published.manifest_path),
            "reporter_assigned_trace_id": reporter_assigned.domain_trace_id,
        },
    )
    report = store.demand_reports[reporter_result.report_id]
    report_summary = report.to_dict()
    report_summary["report_mode"] = "real"
    report_summary["report_context_bundle_id"] = report_context.bundle_id
    report_summary["reporter_session_path"] = reporter_result.session_path
    report_summary["report_md_path"] = str(published.report_md_path)
    report_summary["report_manifest_path"] = str(published.manifest_path)
    report_summary["report_published_trace_id"] = published_trace.domain_trace_id
    if audit_trace is not None and audit_trace.domain_trace_id not in report_summary["domain_trace_ids"]:
        report_summary["domain_trace_ids"].append(audit_trace.domain_trace_id)
    trace.append("report")
    return audit.to_dict(), report_summary


async def _run_real_audit_worker(
    *,
    store: DomainStore,
    run_id: str,
    run_dir: Path,
    candidate_id: str,
    judgement_id: str,
    report_core_conclusion: str,
    provider_factory: Callable[[WorkerSpec], Any] | None = None,
    endpoint_mode: str = "responses_compatible",
    base_url: str = "https://api.openai.com",
    endpoint_path: str = "",
    model: str = DEFAULT_REAL_MODEL,
    api_key_env: str = "DEMAND_DISCOVERY_API_KEY",
    api_key: str | None = None,
) -> AuditReport:
    bundle = build_audit_context_bundle(
        store,
        candidate_id=candidate_id,
        judgement_id=judgement_id,
        report_core_conclusion=report_core_conclusion,
    )
    input_refs = _audit_worker_input_refs(store, candidate_id, judgement_id)
    assignment_trace = _append_trace_event(
        store,
        event_type="audit_worker_assignment_planned",
        actor="autonomous_research",
        target_type="CandidateDemand",
        target_id=candidate_id,
        input_refs=input_refs,
        output_refs=[],
        summary=f"planned real audit worker for {candidate_id}",
        rationale="real audit mode requires run_audit tool execution",
        payload={"audit_mode": "real"},
    )
    scheduler = DiscoveryScheduler(
        run_id,
        provider_factory=provider_factory
        or _real_audit_provider_factory(
            api_key=api_key,
            api_key_env=api_key_env,
            endpoint_mode=endpoint_mode,
            base_url=base_url,
            endpoint_path=endpoint_path,
            model=model,
        ),
        tool_registry_factory=lambda _spec: [
            run_audit_tool(store, rubric=load_default_rubric())
        ],
        domain_store=store,
        sessions_dir=run_dir / "audit_workers",
        max_concurrency=1,
    )
    spec = WorkerSpec(
        role="auditor",
        task_brief="Audit candidate evidence support with run_audit.",
        tools=["run_audit"],
        budget=RunBudget(max_tool_calls=40, max_tokens=DEFAULT_AGENT_MAX_TOKENS),
        context_pack=ContextPack(
            agent_role="auditor",
            task_brief="semantic audit",
            sections={"audit_context": bundle.to_dict()},
            token_budget=DEFAULT_CONTEXT_TOKEN_BUDGET,
        ),
        system_prompt=_load_agent_prompt("auditor"),
    )
    reports = await scheduler.run_workers(
        [spec],
        parent_event_id=assignment_trace.domain_trace_id,
    )
    audit = _latest_audit_for_candidate(store, candidate_id)
    if audit is None:
        error = reports[0].error if reports else "audit worker produced no report"
        raise RuntimeError(f"real audit worker did not write AuditReport: {error}")
    worker_status = reports[0].status if reports else "unknown"
    _append_trace_event(
        store,
        event_type="audit_worker_completed",
        actor="autonomous_research",
        target_type="AuditReport",
        target_id=audit.audit_id,
        input_refs=[assignment_trace.domain_trace_id],
        output_refs=[audit.audit_id],
        summary=f"real audit worker completed {audit.audit_id}",
        decision=audit.conclusion,
        rationale=audit.comments,
        payload={
            "audit_mode": "real",
            "audit_completed_event_source": "run_audit_tool",
            "audit_id": audit.audit_id,
            "worker_status": worker_status,
        },
    )
    return audit


def _real_audit_provider_factory(
    *,
    api_key: str | None,
    api_key_env: str,
    endpoint_mode: str,
    base_url: str,
    endpoint_path: str,
    model: str,
) -> Callable[[WorkerSpec], ResponsesProvider]:
    def factory(_spec: WorkerSpec) -> ResponsesProvider:
        resolved_api_key = api_key or env_value(
            api_key_env,
            load_demand_discovery_dotenv(Path.cwd()),
            "",
        )
        if not resolved_api_key:
            raise ValueError(f"missing API key env {api_key_env}")
        return ResponsesProvider(
            ModelConfig(
                provider="real",
                model=model,
                base_url=base_url,
                endpoint_mode=endpoint_mode,
                endpoint_path=endpoint_path,
                api_key_env=api_key_env,
                timeout_ms=180_000,
                max_retries=2,
            ),
            resolved_api_key,
        )

    return factory


def _real_judge_provider_factory(
    *,
    api_key: str | None,
    api_key_env: str,
    endpoint_mode: str,
    base_url: str,
    endpoint_path: str,
    model: str,
) -> Callable[[], ResponsesProvider]:
    def factory() -> ResponsesProvider:
        resolved_api_key = api_key or env_value(
            api_key_env,
            load_demand_discovery_dotenv(Path.cwd()),
            "",
        )
        if not resolved_api_key:
            raise ValueError(f"missing API key env {api_key_env}")
        return ResponsesProvider(
            ModelConfig(
                provider="real",
                model=model,
                base_url=base_url,
                endpoint_mode=endpoint_mode,
                endpoint_path=endpoint_path,
                api_key_env=api_key_env,
                timeout_ms=180_000,
                max_retries=2,
            ),
            resolved_api_key,
        )

    return factory


def _real_context_curator_provider_factory(
    *,
    api_key: str | None,
    api_key_env: str,
    endpoint_mode: str,
    base_url: str,
    endpoint_path: str,
    model: str,
) -> Callable[[], ResponsesProvider]:
    def factory() -> ResponsesProvider:
        resolved_api_key = api_key or env_value(
            api_key_env,
            load_demand_discovery_dotenv(Path.cwd()),
            "",
        )
        if not resolved_api_key:
            raise ValueError(f"missing API key env {api_key_env}")
        return ResponsesProvider(
            ModelConfig(
                provider="real",
                model=model,
                base_url=base_url,
                endpoint_mode=endpoint_mode,
                endpoint_path=endpoint_path,
                api_key_env=api_key_env,
                timeout_ms=180_000,
                max_retries=2,
            ),
            resolved_api_key,
        )

    return factory


def _real_reporter_provider_factory(
    *,
    api_key: str | None,
    api_key_env: str,
    endpoint_mode: str,
    base_url: str,
    endpoint_path: str,
    model: str,
) -> Callable[[], ResponsesProvider]:
    def factory() -> ResponsesProvider:
        resolved_api_key = api_key or env_value(
            api_key_env,
            load_demand_discovery_dotenv(Path.cwd()),
            "",
        )
        if not resolved_api_key:
            raise ValueError(f"missing API key env {api_key_env}")
        return ResponsesProvider(
            ModelConfig(
                provider="real",
                model=model,
                base_url=base_url,
                endpoint_mode=endpoint_mode,
                endpoint_path=endpoint_path,
                api_key_env=api_key_env,
                timeout_ms=180_000,
                max_retries=2,
            ),
            resolved_api_key,
        )

    return factory


def _build_fixture_report_context(
    store: DomainStore,
    *,
    run_id: str,
    topic: str,
    candidate_id: str,
    judgement_id: str,
    audit_id: str,
    review_status: str,
    run_dir: Path,
    artifacts: ArtifactStore | ArtifactResolver | None,
) -> Any:
    pool = ContextIndexer(store, artifacts).build_candidate_pool(
        run_id=run_id,
        topic=topic,
        candidate_id=candidate_id,
        judgement_id=judgement_id,
        audit_id=audit_id,
        review_status=review_status,
    )
    _append_trace_event(
        store,
        event_type="report_context_indexed",
        actor="report_context",
        target_type="ReportContextCandidatePool",
        target_id=pool.bundle_id,
        input_refs=[candidate_id, judgement_id, audit_id],
        output_refs=[pool.bundle_id],
        summary="report context candidate pool indexed",
    )
    curated_items = [
        CuratedReportItem(
            item_id=f"cur-{index}",
            material_ids=[material.material_id],
            report_use=(
                "core"
                if "core" in material.allowed_report_uses
                else material.allowed_report_uses[0]
            ),
            claim_summary=material.summary or material.title,
            curation_reason="fixture deterministic curation",
        )
        for index, material in enumerate(pool.materials, start=1)
        if material.allowed_report_uses
    ]
    verified = ContextVerifier().verify(pool, curated_items=curated_items)
    if not verified.ok or verified.bundle is None:
        raise ValueError("report context verification failed: " + "; ".join(verified.errors))
    store.upsert_report_context_bundle(verified.bundle)
    _append_trace_event(
        store,
        event_type="report_context_verified",
        actor="report_context",
        target_type="ReportContextBundle",
        target_id=verified.bundle.bundle_id,
        input_refs=[pool.bundle_id],
        output_refs=[verified.bundle.bundle_id],
        summary="report context verified",
        payload={"warnings": list(verified.warnings)},
    )
    (run_dir / "report_context_bundle.json").write_text(
        json.dumps(verified.bundle.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return verified.bundle


async def _build_verified_report_context(
    store: DomainStore,
    *,
    run_id: str,
    topic: str,
    candidate_id: str,
    judgement_id: str,
    audit_id: str,
    review_status: str,
    run_dir: Path,
    artifacts: ArtifactStore | ArtifactResolver | None,
    curator_provider: Any | None,
) -> ReportContextBundle:
    pool = ContextIndexer(store, artifacts).build_candidate_pool(
        run_id=run_id,
        topic=topic,
        candidate_id=candidate_id,
        judgement_id=judgement_id,
        audit_id=audit_id,
        review_status=review_status,
    )
    _append_trace_event(
        store,
        event_type="report_context_indexed",
        actor="report_context",
        target_type="ReportContextCandidatePool",
        target_id=pool.bundle_id,
        input_refs=[candidate_id, judgement_id, audit_id],
        output_refs=[pool.bundle_id],
        summary="report context candidate pool indexed",
    )
    if curator_provider is None:
        curated_items = [
            CuratedReportItem(
                item_id=f"cur-{index}",
                material_ids=[material.material_id],
                report_use=(
                    "core"
                    if "core" in material.allowed_report_uses
                    else material.allowed_report_uses[0]
                ),
                claim_summary=material.summary or material.title,
                curation_reason="fixture deterministic curation",
            )
            for index, material in enumerate(pool.materials, start=1)
            if material.allowed_report_uses
        ]
    else:
        curated_items = await run_report_context_curator_agent(
            provider=curator_provider,
            pool=pool,
            session_path=run_dir / "report_context_curator_session.jsonl",
            system_prompt=_load_agent_prompt("context_curator"),
        )
        _append_trace_event(
            store,
            event_type="report_context_curated",
            actor="context_curator",
            target_type="ReportContextCandidatePool",
            target_id=pool.bundle_id,
            input_refs=[pool.bundle_id],
            output_refs=[item.item_id for item in curated_items],
            summary="report context curated by agent",
            payload={"curated_item_count": len(curated_items)},
        )
    verified = ContextVerifier().verify(pool, curated_items=curated_items)
    if not verified.ok or verified.bundle is None:
        raise ValueError("report context verification failed: " + "; ".join(verified.errors))
    store.upsert_report_context_bundle(verified.bundle)
    _append_trace_event(
        store,
        event_type="report_context_verified",
        actor="report_context",
        target_type="ReportContextBundle",
        target_id=verified.bundle.bundle_id,
        input_refs=[pool.bundle_id],
        output_refs=[verified.bundle.bundle_id],
        summary="report context verified",
        payload={"warnings": list(verified.warnings)},
    )
    (run_dir / "report_context_bundle.json").write_text(
        json.dumps(verified.bundle.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return verified.bundle


def _latest_audit_for_candidate(
    store: DomainStore,
    candidate_id: str,
) -> AuditReport | None:
    audits = [
        audit
        for audit in store.audit_reports.values()
        if audit.candidate_id == candidate_id
    ]
    if not audits:
        return None
    return max(audits, key=lambda item: item.created_at)


def _audit_worker_input_refs(
    store: DomainStore,
    candidate_id: str,
    judgement_id: str,
) -> list[str]:
    candidate = store.candidates[candidate_id]
    refs = [candidate_id, judgement_id, *list(candidate.evidence_ids)]
    refs.extend(_open_source_lineage_refs(store, list(candidate.evidence_ids)))
    return _dedupe_refs(refs)


def _load_agent_prompt(role: str) -> str:
    prompt_path = Path(__file__).resolve().parent / "workers" / "agents" / f"{role}.md"
    return prompt_path.read_text(encoding="utf-8")


def _latest_trace_for(
    store: DomainStore,
    target_id: str,
    event_type: str,
) -> DomainTraceEvent | None:
    for event in reversed(store.trace_events):
        if event.target_id == target_id and event.event_type == event_type:
            return event
    return None


def _degrade_review_status_for_tier_cap(review_status: str) -> str:
    if review_status == "review_ready":
        return "needs_revision"
    return review_status


def _domain_trace_ids_for_report(
    store: DomainStore,
    *,
    required: list[str | None],
) -> list[str]:
    domain_trace_ids = [
        event.domain_trace_id
        for event in store.trace_events
        if event.domain_trace_id
    ]
    for trace_id in required:
        if trace_id and trace_id not in domain_trace_ids:
            domain_trace_ids.append(trace_id)
    return domain_trace_ids


def _open_source_lineage_refs(store: DomainStore, evidence_ids: list[str]) -> list[str]:
    refs: list[str] = []
    for evidence_id in evidence_ids:
        evidence = store.evidence.get(evidence_id)
        if evidence is None:
            continue
        source = store.sources.get(evidence.source_id)
        if source is None or not source.open_source_lead_id:
            continue
        refs.append(source.open_source_lead_id)
        lead = store.open_source_leads.get(source.open_source_lead_id)
        if lead is not None:
            refs.append(lead.plan_id)
        if evidence.source_quality_assessment_id:
            refs.append(evidence.source_quality_assessment_id)
    return _dedupe_refs(refs)


def _dedupe_refs(refs: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        text = str(ref).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _render_autonomous_report_body(
    *,
    report_id: str,
    candidate_id: str,
    judgement_id: str,
    review_status: str,
    title: str,
    demand_statement: str,
    evidence_ids: list[str],
    open_questions: list[str],
    audit_comments: str = "",
    required_rework: list[str] | None = None,
) -> str:
    questions = "\n".join(f"- {item}" for item in open_questions) or "- 无"
    evidence = "\n".join(f"- {item}" for item in evidence_ids) or "- 无"
    rework = "\n".join(f"- {item}" for item in (required_rework or [])) or "- 无"
    return "\n".join(
        [
            "---",
            f"report_id: {report_id}",
            f"candidate_id: {candidate_id}",
            f"judgement_id: {judgement_id}",
            f"review_status: {review_status}",
            "---",
            "",
            f"# {title}",
            "",
            demand_statement,
            "",
            "## 证据",
            evidence,
            "",
            "## 审计结论",
            audit_comments or "- 无",
            "",
            "## 必要返工",
            rework,
            "",
            "## 待解决问题",
            questions,
        ]
    )


def _write_run_config(
    run_dir: Path,
    *,
    run_id: str,
    mode: str,
    topic: str,
    max_rounds: int,
    seed_urls: list[str] | None,
    allow_browser: bool,
    source_whitelist_path: str | Path | None,
    endpoint_mode: str = "responses_compatible",
    base_url: str = "https://api.openai.com",
    endpoint_path: str = "",
    model: str = DEFAULT_REAL_MODEL,
    api_key_env: str = "DEMAND_DISCOVERY_API_KEY",
) -> None:
    payload: dict[str, Any] = {
        "run_id": run_id,
        "mode": mode,
        "topic": topic,
        "max_rounds": max_rounds,
        "seed_urls": list(seed_urls or []),
        "allow_browser": allow_browser,
        "source_whitelist_path": str(source_whitelist_path or default_source_whitelist_path()),
    }
    if mode == "real":
        payload.update(
            {
                "endpoint_mode": endpoint_mode,
                "base_url": base_url,
                "endpoint_path": endpoint_path,
                "model": model,
                "api_key_env": api_key_env,
            }
        )
    (run_dir / "run_config.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


async def _run_real_strategy_seed_research(
    *,
    topic: str,
    output_root: Path,
    run_dir: Path,
    run_id: str,
    max_rounds: int,
    seed_urls: list[str] | None,
    allow_browser: bool,
    source_whitelist_path: str | Path | None,
    strategy: SourceStrategy,
    store: DomainStore,
    registry: SourceRegistry,
    endpoint_mode: str,
    base_url: str,
    endpoint_path: str,
    model: str,
    api_key_env: str,
    api_key: str,
) -> AutonomousResearchResult:
    """Run real provider/network workers inside the Phase 5 round controller."""

    selected_seed_urls = list(seed_urls or [])
    if not selected_seed_urls:
        for source in strategy.selected_sources:
            selected_seed_urls.extend(source.entry_urls[:1])
    selected_seed_urls = selected_seed_urls[: max(1, min(4, len(selected_seed_urls)))]
    if not selected_seed_urls:
        raise ValueError("real autonomous research requires at least one whitelisted entry URL")

    controller = ResearchLoopController(
        run_id=run_id,
        topic=topic,
        strategy=strategy,
        store=store,
        registry=registry,
        max_rounds=max_rounds,
        judge_provider_factory=_real_judge_provider_factory(
            api_key=api_key,
            api_key_env=api_key_env,
            endpoint_mode=endpoint_mode,
            base_url=base_url,
            endpoint_path=endpoint_path,
            model=model,
        ),
        judge_sessions_dir=run_dir / "judge",
    )

    async def execute_round(**kwargs: Any):
        from knowledgegraph.demand_discovery.network_research import run_network_worker_round

        index = int(kwargs["index"])
        round_topic = str(kwargs["topic"])
        network_output_root = run_dir / "network_workers"
        network_run_id = f"{run_id}-round-{index}-network"
        try:
            return await run_network_worker_round(
                mode="real",
                topic=round_topic,
                seed_urls=list(kwargs["seed_urls"]),
                output_root=network_output_root,
                run_id=network_run_id,
                round_id=str(kwargs["round_id"]),
                source_whitelist_path=source_whitelist_path,
                endpoint_mode=endpoint_mode,
                base_url=base_url,
                endpoint_path=endpoint_path,
                model=model,
                api_key_env=api_key_env,
                api_key=api_key,
                allow_browser=allow_browser,
                planned_tasks=list(kwargs.get("planned_tasks") or []),
                allow_open_search=bool(kwargs.get("allow_open_search", False)),
                open_search_plan_id=str(kwargs.get("open_search_plan_id", "")),
                open_search_plan_payload=kwargs.get("open_search_plan_payload"),
                source_guidance=_source_guidance_for_strategy(
                    strategy,
                    selected_seed_urls,
                ),
            )
        except RuntimeError as exc:
            network_run_dir = network_output_root / network_run_id
            domain_path = network_run_dir / "domain.jsonl"
            trace_path = network_run_dir / "trace.jsonl"
            if not domain_path.exists():
                raise
            return SimpleNamespace(
                run_id=network_run_id,
                run_dir=network_run_dir,
                domain_path=domain_path,
                trace_path=trace_path,
                evidence_ids=[],
                trace_event_count=_jsonl_count(trace_path),
                report_trace_event_count=0,
                error=str(exc),
            )

    loop_result = await controller.run_network_loop(
        seed_urls=selected_seed_urls,
        execute_round=execute_round,
    )
    trace = list(loop_result["trace"])
    controller_trace_cursor = len(controller.trace)
    audit_summary: dict[str, Any] | None = None
    report_summary: dict[str, Any] | None = None
    draft = loop_result.get("candidate_synthesis")
    if isinstance(draft, dict) and draft.get("status") == "synthesized":
        audit = await _run_real_audit_worker(
            store=store,
            run_id=run_id,
            run_dir=run_dir,
            candidate_id=str(draft["candidate_id"]),
            judgement_id=str(draft["judgement_id"]),
            report_core_conclusion=str(draft["demand_statement"]),
            endpoint_mode=endpoint_mode,
            base_url=base_url,
            endpoint_path=endpoint_path,
            model=model,
            api_key_env=api_key_env,
            api_key=api_key,
        )
        trace.append("audit")
        while _audit_needs_open_search_repair(audit, topic=topic):
            repair_queries = _audit_repair_queries(audit, topic=topic)
            previous_judgement = store.judgement_reports.get(str(draft["judgement_id"]))
            repair_result = await controller.run_network_open_search_repair_round(
                seed_urls=selected_seed_urls,
                execute_round=execute_round,
                trigger_audit_id=audit.audit_id,
                repair_queries=repair_queries,
                previous_judgement=previous_judgement,
            )
            trace.extend(controller.trace[controller_trace_cursor:])
            controller_trace_cursor = len(controller.trace)
            if repair_result is None:
                break
            loop_result["rounds"].append(repair_result["round"])
            loop_result["network_worker_runs"].append(
                repair_result["network_worker_run"]
            )
            loop_result["candidate_synthesis"] = repair_result["candidate_synthesis"]
            loop_result["open_search_plans"] = [
                plan.to_dict() for plan in store.open_search_plans.values()
            ]
            draft = loop_result.get("candidate_synthesis")
            if not isinstance(draft, dict) or draft.get("status") != "synthesized":
                break
            audit = await _run_real_audit_worker(
                store=store,
                run_id=run_id,
                run_dir=run_dir,
                candidate_id=str(draft["candidate_id"]),
                judgement_id=str(draft["judgement_id"]),
                report_core_conclusion=str(draft["demand_statement"]),
                endpoint_mode=endpoint_mode,
                base_url=base_url,
                endpoint_path=endpoint_path,
                model=model,
                api_key_env=api_key_env,
                api_key=api_key,
            )
            trace.append("audit")
        artifact_resolver = _artifact_resolver_for_loop_result(loop_result, run_dir)
        audit_summary, report_summary = await _complete_autonomous_report_after_audit_async(
            store,
            loop_result=loop_result,
            trace=trace,
            run_dir=run_dir,
            audit=audit,
            report_mode="real",
            curator_provider=_real_context_curator_provider_factory(
                api_key=api_key,
                api_key_env=api_key_env,
                endpoint_mode=endpoint_mode,
                base_url=base_url,
                endpoint_path=endpoint_path,
                model=model,
            )(),
            reporter_provider=_real_reporter_provider_factory(
                api_key=api_key,
                api_key_env=api_key_env,
                endpoint_mode=endpoint_mode,
                base_url=base_url,
                endpoint_path=endpoint_path,
                model=model,
            )(),
            artifacts=artifact_resolver,
        )
    summary = {
        "run_id": run_id,
        "mode": "real",
        "topic": topic,
        "max_rounds": max_rounds,
        "source_strategy": strategy.to_dict(),
        "selected_seed_urls": selected_seed_urls,
        "real_execution": "phase5_research_loop_with_network_workers",
        "rounds": loop_result["rounds"],
        "candidate_synthesis": loop_result["candidate_synthesis"],
        "audit": audit_summary,
        "report": report_summary,
        "trace": trace,
        "network_worker_runs": loop_result["network_worker_runs"],
        "open_search_plans": loop_result.get("open_search_plans", []),
        "trace_event_count": len(store.trace_events),
        "report_trace_event_count": (
            len(report_summary.get("domain_trace_ids", []))
            if isinstance(report_summary, dict)
            else 0
        ),
        "allow_browser": allow_browser,
    }
    round_summary_path = run_dir / "round_summary.json"
    round_summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    domain_path = run_dir / "domain.jsonl"
    trace_path = run_dir / "trace.jsonl"
    store.export_jsonl(domain_path)
    _write_domain_trace_jsonl(trace_path, store)
    _write_run_config(
        run_dir,
        run_id=run_id,
        mode="real",
        topic=topic,
        max_rounds=max_rounds,
        seed_urls=seed_urls,
        allow_browser=allow_browser,
        source_whitelist_path=source_whitelist_path,
        endpoint_mode=endpoint_mode,
        base_url=base_url,
        endpoint_path=endpoint_path,
        model=model,
        api_key_env=api_key_env,
    )
    return AutonomousResearchResult(
        run_id=run_id,
        run_dir=run_dir,
        source_strategy_id=strategy.strategy_id,
        round_summary_path=round_summary_path,
        domain_path=domain_path,
        trace_path=trace_path,
    )


def _artifact_resolver_for_loop_result(
    loop_result: dict[str, Any],
    run_dir: Path,
) -> ArtifactStore | ArtifactResolver:
    stores: list[ArtifactStore] = []
    seen: set[Path] = set()
    for row in list(loop_result.get("network_worker_runs", []) or []):
        if not isinstance(row, dict):
            continue
        raw_path = str(row.get("artifact_dir", "")).strip()
        if not raw_path:
            continue
        path = Path(raw_path)
        if path.exists():
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                stores.append(ArtifactStore(path))
    if stores:
        return ArtifactResolver(stores)
    return ArtifactStore(run_dir / "artifacts")


def _audit_needs_open_search_repair(
    audit: AuditReport,
    *,
    topic: str,
) -> bool:
    conclusion = audit.conclusion.strip().lower()
    if conclusion in {"approved", "pass", "通过"}:
        return False
    return bool(_audit_repair_queries(audit, topic=topic))


def _audit_repair_queries(
    audit: AuditReport,
    *,
    topic: str,
) -> list[str]:
    scorecard = audit.scorecard if isinstance(audit.scorecard, dict) else {}
    evidence_support = scorecard.get("evidence_support", {})
    if not isinstance(evidence_support, dict):
        evidence_support = {}
    values: list[str] = []
    values.extend(str(item) for item in audit.required_rework)
    values.extend(_string_values(evidence_support.get("recheck_conditions")))
    values.extend(_string_values(evidence_support.get("status_reason")))
    values.extend(_string_values(audit.comments))
    values.append(topic)
    return _dedupe_nonempty_text(values, limit=6)


def _string_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _dedupe_nonempty_text(values: list[str], *, limit: int) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        rows.append(text)
        if len(rows) >= limit:
            break
    return rows


def _source_guidance_for_strategy(
    strategy: SourceStrategy,
    seed_urls: list[str],
) -> list[dict[str, Any]]:
    seed_set = set(seed_urls)
    rows: list[dict[str, Any]] = []
    for source in strategy.selected_sources:
        source_urls = [url for url in source.entry_urls if not seed_set or url in seed_set]
        for url in source_urls[:1]:
            rows.append(
                {
                    "source_name": source.source_name,
                    "source_tier": source.source_tier,
                    "url": url,
                    "content_languages": list(source.content_languages),
                    "planned_queries": list(source.planned_queries),
                }
            )
    return rows


def _resolve_real_api_key(
    api_key: str | None,
    api_key_env: str,
) -> str:
    if api_key:
        return api_key
    dotenv = load_demand_discovery_dotenv(Path.cwd())
    resolved = env_value(api_key_env, dotenv, "")
    if not resolved:
        raise ValueError(f"missing API key env {api_key_env}")
    return resolved


def _write_domain_trace_jsonl(path: Path, store: DomainStore) -> None:
    path.write_text(
        "\n".join(
            json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True)
            for event in store.trace_events
        )
        + ("\n" if store.trace_events else ""),
        encoding="utf-8",
    )


def _jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _append_trace_event(
    store: DomainStore,
    *,
    event_type: str,
    actor: str,
    target_type: str,
    target_id: str,
    input_refs: list[str] | None = None,
    output_refs: list[str] | None = None,
    summary: str,
    decision: str | None = None,
    rationale: str | None = None,
    payload: dict[str, Any] | None = None,
) -> DomainTraceEvent:
    return store.append_trace(
        DomainTraceEvent(
            domain_trace_id=f"dt-{uuid4().hex}",
            trace_id="autonomous-research",
            event_type=event_type,
            actor=actor,
            target_type=target_type,
            target_id=target_id,
            input_refs=list(input_refs or []),
            output_refs=list(output_refs or []),
            summary=summary,
            decision=decision,
            rationale=rationale,
            model=None,
            prompt_id=None,
            tool_refs=[],
            runtime_event_id=None,
            created_at=_now(),
            payload=dict(payload or {}),
        )
    )
