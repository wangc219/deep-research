"""Validation and repair helpers for judge next-round plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


REQUIRED_CONTROLLER_TASK_FIELDS = {
    "task_id",
    "objective",
    "gap_type",
    "routing_hint",
    "source_scope",
    "input_refs",
    "query_revisions",
    "completion_check",
}

GAP_TYPES = {
    "missing_direct_evidence",
    "partial_only",
    "contradiction",
    "source_gap",
    "route_failed",
    "open_search_candidate",
    "human_profile_needed",
    "report_ready_with_limits",
}
ROUTING_HINTS = {
    "same_source_followup",
    "different_whitelist_source",
    "open_search_candidate",
    "human_profile_needed",
    "stop_for_report",
}
SOURCE_SCOPES = {
    "whitelist_first",
    "whitelist_only",
    "open_web_after_whitelist_exhausted",
    "human_profile_required",
}
OPEN_SEARCH_ROUTING_HINTS = {"open_search_candidate"}
OPEN_WEB_SCOPES = {"open_web_after_whitelist_exhausted"}
HUMAN_ROUTING_HINTS = {"human_profile_needed"}
LEGACY_ROUTING_HINT_ALIASES = {
    "human_profile_request": "human_profile_needed",
    "needs_human_steer": "human_profile_needed",
}
SOURCE_SCOPE_ALIASES = {
    "whitelist": "whitelist_first",
}
GENERIC_QUERY_FRAGMENTS = (
    "继续补充材料",
    "补充材料",
    "补充交叉验证材料",
    "交叉验证材料",
    "补充独立来源交叉验证",
    "继续补证",
    "补充证据",
)


@dataclass(frozen=True)
class JudgementPlanAssessment:
    is_valid: bool
    repaired: bool
    plan: dict[str, Any]
    controller_tasks: list[dict[str, Any]] = field(default_factory=list)
    worker_briefs: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    brief_mismatch_task_ids: list[str] = field(default_factory=list)


def assess_next_round_plan(plan: dict[str, Any]) -> JudgementPlanAssessment:
    """Check the minimal Phase 5 next-round plan contract."""

    if not isinstance(plan, dict):
        return JudgementPlanAssessment(
            is_valid=False,
            repaired=False,
            plan={},
            errors=["next_round_plan must be an object"],
        )
    controller_tasks = plan.get("controller_tasks", [])
    worker_briefs = plan.get("worker_briefs", {})
    errors: list[str] = []
    warnings: list[str] = []
    if plan.get("plan_version") != 1:
        errors.append("plan_version must be 1")
    if "tasks" in plan:
        errors.append("legacy tasks field is not allowed")
    if not isinstance(controller_tasks, list):
        errors.append("controller_tasks must be an array")
        controller_tasks = []
    if not isinstance(worker_briefs, dict):
        errors.append("worker_briefs must be an object map keyed by task_id")
        worker_briefs = {}
    normalized_briefs = {
        str(key): str(value)
        for key, value in worker_briefs.items()
        if str(key).strip() and str(value).strip()
    }
    for index, task in enumerate(controller_tasks, start=1):
        if not isinstance(task, dict):
            errors.append(f"controller_tasks[{index}] must be an object")
            continue
        task_id = str(task.get("task_id", "")).strip() or f"controller_tasks[{index}]"
        missing = [
            field_name
            for field_name in REQUIRED_CONTROLLER_TASK_FIELDS
            if field_name not in task or _is_empty(task.get(field_name))
        ]
        if missing:
            errors.append(f"{task_id} missing required fields: {', '.join(missing)}")
        gap_type = str(task.get("gap_type", "")).strip()
        routing_hint = str(task.get("routing_hint", "")).strip()
        source_scope = str(task.get("source_scope", "")).strip()
        if gap_type and gap_type not in GAP_TYPES:
            errors.append(f"{task_id} unknown gap_type: {gap_type}")
        if routing_hint and routing_hint not in ROUTING_HINTS:
            errors.append(f"{task_id} unknown routing_hint: {routing_hint}")
        if source_scope and source_scope not in SOURCE_SCOPES:
            errors.append(f"{task_id} unknown source_scope: {source_scope}")
        input_refs = task.get("input_refs", {})
        if not isinstance(input_refs, dict):
            errors.append(f"{task_id} input_refs must be an object")
        elif not _string_list(input_refs.get("worker_report_ids", [])):
            errors.append(f"{task_id} input_refs.worker_report_ids is required")
        if not isinstance(task.get("query_revisions", []), list):
            errors.append(f"{task_id} query_revisions must be an array")
        else:
            for query_index, item in enumerate(task.get("query_revisions", []), start=1):
                if not _query_from_revision(item):
                    errors.append(
                        f"{task_id} query_revisions[{query_index}] requires query"
                    )
        if task_id not in normalized_briefs:
            errors.append(f"{task_id} missing worker_briefs entry")
    task_ids = {
        str(task.get("task_id", "")).strip()
        for task in controller_tasks
        if isinstance(task, dict)
    }
    for task_id in normalized_briefs:
        if task_id not in task_ids:
            warnings.append(f"worker_briefs has no matching controller task: {task_id}")
    brief_mismatch_task_ids = check_worker_brief_consistency(
        controller_tasks=[task for task in controller_tasks if isinstance(task, dict)],
        worker_briefs=normalized_briefs,
    )
    errors.extend(
        f"{task_id} worker_brief requests tools outside controller authorization"
        for task_id in brief_mismatch_task_ids
    )
    return JudgementPlanAssessment(
        is_valid=not errors,
        repaired=False,
        plan=dict(plan),
        controller_tasks=[dict(task) for task in controller_tasks if isinstance(task, dict)],
        worker_briefs=normalized_briefs,
        errors=errors,
        warnings=warnings,
        brief_mismatch_task_ids=brief_mismatch_task_ids,
    )


def build_repaired_next_round_plan(
    plan: dict[str, Any] | None,
    *,
    topic: str = "",
    round_id: str = "",
    summary: str = "",
) -> dict[str, Any]:
    """Build a valid minimal plan from a judge plan or old v1 draft."""

    source = dict(plan or {})
    source_tasks = _source_tasks(source)
    controller_tasks = [
        _repair_controller_task(item, index=index, topic=topic)
        for index, item in enumerate(source_tasks, start=1)
        if isinstance(item, dict)
    ]
    existing_briefs = {
        str(key): str(value)
        for key, value in source.get("worker_briefs", {}).items()
        if str(key).strip() and str(value).strip()
    } if isinstance(source.get("worker_briefs", {}), dict) else {}
    worker_briefs: dict[str, str] = {}
    for task in controller_tasks:
        task_id = str(task["task_id"])
        brief = existing_briefs.get(task_id, "")
        if task_id in check_worker_brief_consistency(
            controller_tasks=[task],
            worker_briefs={task_id: brief},
        ):
            brief = ""
        worker_briefs[task_id] = brief or compile_worker_brief(task)
    repaired = {
        "plan_version": 1,
        "round_id": str(source.get("round_id") or round_id),
        "summary": str(
            source.get("summary")
            or summary
            or ("继续围绕证据缺口补证" if controller_tasks else "已有证据足以停止")
        ),
        "controller_tasks": controller_tasks,
        "worker_briefs": worker_briefs,
        "remaining_open_questions": _string_list(
            source.get("remaining_open_questions", [])
        ),
        "stop_candidate_reason": str(source.get("stop_candidate_reason", "")),
    }
    return repaired


def compile_worker_brief(task: dict[str, Any]) -> str:
    """Compile one controller task into a natural-language worker brief."""

    input_refs = task.get("input_refs", {})
    if not isinstance(input_refs, dict):
        input_refs = {}
    refs = []
    for key in ("worker_report_ids", "evidence_ids", "lead_ids"):
        values = _string_list(input_refs.get(key, []))
        if values:
            refs.append(f"{key}={', '.join(values)}")
    queries = [
        query
        for item in task.get("query_revisions", [])
        for query in [_query_from_revision(item)]
        if query
    ]
    query_text = "；".join(queries) if queries else "由任务目标生成窄查询"
    refs_text = "；".join(refs) if refs else "无显式输入引用"
    return (
        f"任务 {task.get('task_id', '')}：{task.get('objective', '')}。"
        f"路由提示：{task.get('routing_hint', '')}；信源范围：{task.get('source_scope', '')}。"
        f"优先使用这些 query：{query_text}。"
        f"输入引用：{refs_text}。"
        f"完成检查：{task.get('completion_check', '')}。"
    )


def check_worker_brief_consistency(
    *,
    controller_tasks: list[dict[str, Any]],
    worker_briefs: dict[str, str],
) -> list[str]:
    """Return task ids whose worker brief asks for unauthorized capability."""

    mismatches: list[str] = []
    for task in controller_tasks:
        task_id = str(task.get("task_id", "")).strip()
        if not task_id:
            continue
        brief = worker_briefs.get(task_id, "")
        if not brief:
            continue
        routing_hint = str(task.get("routing_hint", ""))
        source_scope = str(task.get("source_scope", ""))
        open_authorized = (
            routing_hint in OPEN_SEARCH_ROUTING_HINTS
            or source_scope in OPEN_WEB_SCOPES
        )
        lower_brief = brief.lower()
        asks_open_search = any(
            marker in lower_brief
            for marker in (
                "open_search",
                "open search",
                "fetch_open_source_page",
                "开放搜索",
                "开放网页",
                "公开网页",
            )
        )
        asks_browser_or_js = any(
            marker in lower_brief
            for marker in (
                "browser_observe",
                "browser_execute",
                "javascript",
                "js",
                "浏览器",
            )
        )
        if (asks_open_search or asks_browser_or_js) and not open_authorized:
            mismatches.append(task_id)
    return mismatches


def normalized_query_revisions(task: dict[str, Any]) -> list[dict[str, str]]:
    return _normalize_query_revisions(task.get("query_revisions", []), topic="")


def _source_tasks(plan: dict[str, Any]) -> list[Any]:
    controller_tasks = plan.get("controller_tasks", [])
    if isinstance(controller_tasks, list) and controller_tasks:
        return controller_tasks
    legacy_tasks = plan.get("tasks", [])
    if isinstance(legacy_tasks, list):
        return legacy_tasks
    return []


def _repair_controller_task(
    task: dict[str, Any],
    *,
    index: int,
    topic: str,
) -> dict[str, Any]:
    task_id = str(task.get("task_id") or f"task-{index}").strip()
    objective = str(
        task.get("objective")
        or task.get("question")
        or task.get("action_intent")
        or topic
        or "补充下一轮需求证据"
    ).strip()
    raw_gap_type = str(task.get("gap_type", "")).strip()
    gap_type = (
        "missing_direct_evidence"
        if raw_gap_type in {"", "open_search_candidate"}
        else raw_gap_type
    )
    if gap_type not in GAP_TYPES:
        gap_type = "source_gap"
    routing_hint = str(
        task.get("routing_hint")
        or task.get("routing_decision_hint")
        or ("open_search_candidate" if raw_gap_type == "open_search_candidate" else "")
        or ("open_search_candidate" if "开放" in objective else "different_whitelist_source")
    ).strip()
    routing_hint = LEGACY_ROUTING_HINT_ALIASES.get(routing_hint, routing_hint)
    if routing_hint not in ROUTING_HINTS:
        routing_hint = "different_whitelist_source"
    completion_check = _completion_check(task, routing_hint=routing_hint)
    source_scope = _source_scope(task, routing_hint=routing_hint, completion_check=completion_check)
    input_refs = _input_refs(task.get("input_refs", {}))
    query_revisions = _normalize_query_revisions(
        task.get("query_revisions", []),
        topic=topic,
        objective=objective,
    )
    return {
        "task_id": task_id,
        "objective": objective,
        "gap_type": gap_type,
        "routing_hint": routing_hint,
        "source_scope": source_scope,
        "input_refs": input_refs,
        "query_revisions": query_revisions,
        "completion_check": completion_check,
    }


def _input_refs(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        value = {}
    return {
        "worker_report_ids": _string_list(value.get("worker_report_ids", [])),
        "evidence_ids": _string_list(value.get("evidence_ids", [])),
        "lead_ids": _string_list(value.get("lead_ids", [])),
    }


def _normalize_query_revisions(
    value: Any,
    *,
    topic: str,
    objective: str = "",
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    values = value if isinstance(value, list) else [value]
    for item in values:
        language = "auto"
        query = ""
        if isinstance(item, dict):
            language = str(item.get("language") or "auto").strip() or "auto"
            query = str(item.get("query", "")).strip()
        else:
            query = str(item).strip()
        query = _repair_generic_query(query, topic=topic, objective=objective)
        if query:
            rows.append({"language": language, "query": query})
    if not rows:
        query = _repair_generic_query(objective or topic, topic=topic, objective=objective)
        if query:
            rows.append({"language": "auto", "query": query})
    return _dedupe_query_revisions(rows)


def _repair_generic_query(query: str, *, topic: str, objective: str) -> str:
    text = " ".join(str(query).split())
    if not text:
        return ""
    if _is_generic_query(text):
        pieces = [topic.strip(), objective.strip()]
        text = " ".join(piece for piece in pieces if piece)
    return text


def _is_generic_query(query: str) -> bool:
    stripped = query.strip()
    if stripped in {"补证", "补充材料", "继续补证", "更多材料"}:
        return True
    return any(fragment in stripped for fragment in GENERIC_QUERY_FRAGMENTS)


def _dedupe_query_revisions(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        query = row["query"].strip()
        if not query or query in seen:
            continue
        seen.add(query)
        result.append({"language": row.get("language", "auto") or "auto", "query": query})
    return result


def _completion_check(task: dict[str, Any], *, routing_hint: str) -> str:
    if str(task.get("completion_check", "")).strip():
        return str(task["completion_check"]).strip()
    done_criteria = task.get("done_criteria", [])
    if isinstance(done_criteria, list) and done_criteria:
        return "；".join(str(item) for item in done_criteria if str(item).strip())
    if isinstance(done_criteria, str) and done_criteria.strip():
        return done_criteria.strip()
    if routing_hint in OPEN_SEARCH_ROUTING_HINTS:
        return "找到可读取正文的开放来源并创建 EvidenceCard，或说明只能得到 partial/adjacent evidence"
    return "至少新增一条白名单正文证据，或说明 route/query 已耗尽"


def _source_scope(
    task: dict[str, Any],
    *,
    routing_hint: str,
    completion_check: str,
) -> str:
    constraints = task.get("source_constraints", {})
    if not isinstance(constraints, dict):
        constraints = {}
    raw = str(task.get("source_scope") or constraints.get("source_scope") or "").strip()
    raw = SOURCE_SCOPE_ALIASES.get(raw, raw)
    whitelist_exhausted = (
        constraints.get("whitelist_exhausted") is True
        or "白名单" in completion_check and ("耗尽" in completion_check or "无新增" in completion_check)
    )
    if routing_hint in OPEN_SEARCH_ROUTING_HINTS:
        if whitelist_exhausted or raw in {"", "open_web_after_whitelist_exhausted"}:
            return "open_web_after_whitelist_exhausted"
        if raw in {"open_web", "whitelist_first", "whitelist_only"}:
            return "whitelist_first"
        return raw if raw in SOURCE_SCOPES else "whitelist_first"
    if routing_hint in HUMAN_ROUTING_HINTS:
        return "human_profile_required"
    return raw if raw in SOURCE_SCOPES else "whitelist_first"


def _query_from_revision(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("query", "")).strip()
    return str(item).strip()


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict)):
        return not value
    return False
