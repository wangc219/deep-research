"""Routing helpers for judge-produced next-round plans."""

from __future__ import annotations

from typing import Any

from knowledgegraph.demand_discovery.domain.judgement import JudgementReport
from knowledgegraph.demand_discovery.domain.judgement_plan import (
    HUMAN_ROUTING_HINTS,
    OPEN_SEARCH_ROUTING_HINTS,
    OPEN_WEB_SCOPES,
    build_repaired_next_round_plan,
    normalized_query_revisions,
)


def controller_tasks_from_judgement(
    judgement: JudgementReport,
    *,
    topic: str = "",
) -> list[dict[str, Any]]:
    plan = build_repaired_next_round_plan(
        judgement.next_round_plan,
        topic=topic,
        round_id=judgement.round_id,
    )
    return [dict(task) for task in plan.get("controller_tasks", [])]


def worker_assignments_from_judgement(
    judgement: JudgementReport,
    *,
    topic: str = "",
) -> list[dict[str, Any]]:
    plan = build_repaired_next_round_plan(
        judgement.next_round_plan,
        topic=topic,
        round_id=judgement.round_id,
    )
    briefs = plan.get("worker_briefs", {})
    assignments: list[dict[str, Any]] = []
    for task in plan.get("controller_tasks", []):
        if not _has_worker_report_refs(task):
            continue
        task_id = str(task.get("task_id", ""))
        assignments.append(
            {
                **dict(task),
                "worker_brief": str(briefs.get(task_id, "")),
            }
        )
    return assignments


def open_search_tasks_from_judgement(
    judgement: JudgementReport,
    *,
    topic: str = "",
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for task in controller_tasks_from_judgement(judgement, topic=topic):
        if not _has_worker_report_refs(task):
            continue
        routing_hint = str(task.get("routing_hint", ""))
        source_scope = str(task.get("source_scope", ""))
        if routing_hint in OPEN_SEARCH_ROUTING_HINTS or source_scope in OPEN_WEB_SCOPES:
            result.append(task)
    return result


def open_search_queries_from_judgement(
    judgement: JudgementReport,
    *,
    fallback_topic: str = "",
    limit: int = 6,
) -> list[str]:
    candidates: list[str] = []
    for task in open_search_tasks_from_judgement(judgement, topic=fallback_topic):
        candidates.extend(
            item["query"]
            for item in normalized_query_revisions(task)
            if item.get("query")
        )
    if fallback_topic:
        candidates.append(fallback_topic)
    return _dedupe_nonempty(candidates, limit=limit)


def human_profile_requests_from_judgement(
    judgement: JudgementReport,
    *,
    topic: str = "",
) -> list[dict[str, Any]]:
    return [
        task
        for task in controller_tasks_from_judgement(judgement, topic=topic)
        if _has_worker_report_refs(task)
        and str(task.get("routing_hint", "")) in HUMAN_ROUTING_HINTS
    ]


def _has_worker_report_refs(task: dict[str, Any]) -> bool:
    input_refs = task.get("input_refs", {})
    if not isinstance(input_refs, dict):
        return False
    values = input_refs.get("worker_report_ids", [])
    if isinstance(values, list):
        return any(str(item).strip() for item in values)
    return bool(str(values).strip())


def _dedupe_nonempty(values: list[str], *, limit: int) -> list[str]:
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
