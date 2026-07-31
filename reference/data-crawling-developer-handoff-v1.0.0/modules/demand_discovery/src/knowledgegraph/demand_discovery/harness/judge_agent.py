"""Model-backed judge runner for demand discovery research rounds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from knowledgegraph.demand_discovery.domain.judgement import JudgementReport
from knowledgegraph.demand_discovery.domain.store import DomainStore
from knowledgegraph.demand_discovery.domain.tools import record_judgement_tool
from knowledgegraph.demand_discovery.harness.agent_harness import DiscoveryHarness
from knowledgegraph.demand_discovery.harness.session_store import JsonlSessionStore
from knowledgegraph.demand_discovery.harness.worker_report import WorkerReport


ProviderFactory = Callable[[], Any]


async def run_judge_agent_for_round(
    *,
    round_id: str,
    worker_reports: list[WorkerReport],
    domain_store: DomainStore,
    provider_factory: ProviderFactory,
    run_id: str,
    sessions_dir: str | Path,
    system_prompt: str | None = None,
) -> JudgementReport:
    """Run the judge as an agent that must write JudgementReport via tool."""

    before_ids = set(domain_store.judgement_reports)
    provider = provider_factory()
    session_path = Path(sessions_dir) / f"judge-{round_id}.jsonl"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    harness = DiscoveryHarness(
        provider=provider,
        tools=[record_judgement_tool(domain_store)],
        session_store=JsonlSessionStore(session_path, run_id=run_id),
        domain_store=domain_store,
        run_id=run_id,
        agent_run_id=f"judge-{round_id}",
        worker_id="judge",
        system_prompt=system_prompt or _load_judge_prompt(),
    )
    assistant = await harness.prompt(_judge_task_brief(round_id, worker_reports, domain_store))
    if assistant.is_error:
        error_message = str(assistant.metadata.get("error_message", "") or "judge agent failed")
        raise RuntimeError(error_message)
    candidates = [
        item
        for key, item in domain_store.judgement_reports.items()
        if key not in before_ids and item.round_id == round_id
    ]
    if not candidates:
        candidates = [
            item
            for item in domain_store.judgement_reports.values()
            if item.round_id == round_id
        ]
    if not candidates:
        raise RuntimeError("judge agent did not write JudgementReport")
    return max(candidates, key=lambda item: item.created_at)


def _judge_task_brief(
    round_id: str,
    worker_reports: list[WorkerReport],
    domain_store: DomainStore,
) -> str:
    payload = {
        "round_id": round_id,
        "worker_reports": [report.to_dict() for report in worker_reports],
        "evidence": _evidence_payload(domain_store, worker_reports),
        "sources": _source_payload(domain_store, worker_reports),
        "open_search": _open_search_payload(domain_store),
        "required_action": (
            "Call record_judgement exactly once. Do not answer with text only. "
            "Use next_round_plan.plan_version=1 with controller_tasks and worker_briefs."
        ),
    }
    return (
        "Judge this research round from worker reports and traceable domain state. "
        "Decide whether evidence is sufficient for candidate synthesis or whether "
        "the next round needs targeted follow-up. Produce one JudgementReport by "
        "calling record_judgement.\n\n"
        f"```json\n{json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)}\n```"
    )


def _evidence_payload(
    domain_store: DomainStore,
    worker_reports: list[WorkerReport],
) -> list[dict[str, Any]]:
    evidence_ids = _dedupe(
        evidence_id
        for report in worker_reports
        for evidence_id in [*report.evidence_refs, *report.new_evidence_cards]
    )
    rows: list[dict[str, Any]] = []
    for evidence_id in evidence_ids:
        evidence = domain_store.evidence.get(evidence_id)
        if evidence is None:
            rows.append({"evidence_id": evidence_id, "missing_from_store": True})
            continue
        rows.append(evidence.to_dict())
    return rows


def _source_payload(
    domain_store: DomainStore,
    worker_reports: list[WorkerReport],
) -> list[dict[str, Any]]:
    source_ids = {
        evidence.source_id
        for report in worker_reports
        for evidence_id in [*report.evidence_refs, *report.new_evidence_cards]
        for evidence in [domain_store.evidence.get(evidence_id)]
        if evidence is not None and evidence.source_id
    }
    rows: list[dict[str, Any]] = []
    for source_id in sorted(source_ids):
        source = domain_store.sources.get(source_id)
        if source is not None:
            rows.append(source.to_dict())
    return rows


def _open_search_payload(domain_store: DomainStore) -> dict[str, Any]:
    return {
        "plans": [
            plan.to_dict()
            for plan in domain_store.open_search_plans.values()
        ],
        "leads": [
            lead.to_dict()
            for lead in domain_store.open_source_leads.values()
        ],
        "quality_assessments": [
            assessment.to_dict()
            for assessment in domain_store.source_quality_assessments.values()
        ],
    }


def _load_judge_prompt() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "workers"
        / "agents"
        / "judge.md"
    ).read_text(encoding="utf-8")


def _dedupe(values) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        rows.append(text)
    return rows
