"""Conversation primitives for branch-aware, steerable deep research.

The main deep-research ledger remains the source of truth.  This module keeps
the model-facing conversation rules dependency-free: branch projection,
bounded working memory, and steering-mode validation.  It deliberately does
not score evidence coverage; directed innovation often starts from sparse
public evidence and should preserve uncertainty without blocking ideation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from equipment_deep_research.domain.research_gaps import (
    sanitize_public_research_prose,
    sanitize_public_research_gaps,
)


DEFAULT_BRANCH_ID = "main"
STEER_MODES = frozenset({"steer", "queue", "interrupt_steer", "interrupt_send"})
LIVE_STEER_MODES = frozenset({"steer", "interrupt_steer", "interrupt_send"})
# Nanobot keeps recent conversation in the living window and archives the rest
# as structured memory.  Deep research uses the same split so a long thread
# cannot re-anchor later council turns on the full transcript.
LIVING_TURN_LIMIT = 2
CONTEXT_BUDGET_CHARS = 12000
# Nanobot-style quoted follow-up marker.  The WebUI wraps a selected assistant
# excerpt so the next turn can point at a specific claim without stuffing the
# entire previous answer back into model context.
QUOTE_MARKER = "> [引用]"


def bounded_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[: max(0, int(limit))]


def parse_quoted_user_message(content: Any) -> tuple[str, str]:
    """Split a user turn into (quoted_excerpt, question body)."""

    raw = str(content or "").replace("\r\n", "\n").strip()
    if not raw:
        return "", ""
    marker_line = QUOTE_MARKER
    if raw.startswith(f"{marker_line}\n"):
        rest = raw[len(marker_line) + 1 :]
        separator = rest.find("\n\n")
        quote_block = rest if separator < 0 else rest[:separator]
        body = "" if separator < 0 else rest[separator + 2 :]
        lines = quote_block.split("\n")
        if lines and all(line == ">" or line.startswith("> ") for line in lines):
            quote = "\n".join(
                "" if line == ">" else line[2:] for line in lines
            ).strip()
            return quote, body.strip()
    return "", raw


def format_quoted_user_message(content: Any, quoted_context: Any = None) -> str:
    """Wrap a follow-up around a selected excerpt. Slash commands stay bare."""

    body = str(content or "").strip()
    quote = str(quoted_context or "").replace("\r\n", "\n").strip()
    if not quote or body.startswith("/"):
        return body
    if body.startswith(QUOTE_MARKER) or quote.startswith(QUOTE_MARKER):
        return body or quote
    block = "\n".join(f"> {line}" if line else ">" for line in quote.split("\n"))
    return f"{QUOTE_MARKER}\n{block}\n\n{body}" if body else f"{QUOTE_MARKER}\n{block}"


def bounded_visible_text(value: Any, limit: int) -> str:
    """Keep quote structure in the living window instead of flattening it."""

    raw = str(value or "").replace("\r\n", "\n").strip()
    if not raw:
        return ""
    quote, body = parse_quoted_user_message(raw)
    if not quote:
        return bounded_text(raw, limit)
    formatted = format_quoted_user_message(
        bounded_text(body, max(80, int(limit) - 120)),
        bounded_text(quote, min(420, max(80, int(limit) // 2))),
    )
    return formatted[: max(0, int(limit))]


def normalize_branch_id(value: Any) -> str:
    branch_id = bounded_text(value, 128)
    return branch_id or DEFAULT_BRANCH_ID


def normalize_steer_mode(value: Any) -> str:
    mode = bounded_text(value, 32).lower().replace("-", "_")
    if mode not in STEER_MODES:
        raise ValueError("invalid deep steering mode")
    return mode


def branch_message_path(
    messages: Sequence[Mapping[str, Any]] | None,
    branch_id: str = DEFAULT_BRANCH_ID,
    branches: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return the visible ancestry ending on the requested branch.

    New messages form a parent-linked tree.  Legacy messages have no parent or
    branch metadata, so the fallback retains the chronological prefix up to the
    first linked ancestor rather than hiding useful existing conversation.
    """

    rows = [dict(item) for item in (messages or ()) if isinstance(item, Mapping)]
    rows.sort(key=lambda item: int(item.get("sequence", 0) or 0))
    wanted = normalize_branch_id(branch_id)
    for item in rows:
        item["branch_id"] = normalize_branch_id(item.get("branch_id"))

    if wanted == DEFAULT_BRANCH_ID:
        return [item for item in rows if item["branch_id"] == DEFAULT_BRANCH_ID]

    by_id = {
        str(item.get("message_id", "")): item
        for item in rows
        if str(item.get("message_id", "")).strip()
    }
    candidates = [item for item in rows if item["branch_id"] == wanted]
    branch = next(
        (
            item
            for item in (branches or ())
            if isinstance(item, Mapping)
            and normalize_branch_id(item.get("branch_id")) == wanted
        ),
        None,
    )
    current: dict[str, Any] | None = candidates[-1] if candidates else None
    if current is None and isinstance(branch, Mapping):
        current = by_id.get(str(branch.get("forked_from_message_id", "") or ""))
    if current is None:
        return [item for item in rows if item["branch_id"] == DEFAULT_BRANCH_ID]

    path: list[dict[str, Any]] = []
    seen: set[str] = set()
    while current is not None:
        message_id = str(current.get("message_id", ""))
        if message_id and message_id in seen:
            break
        if message_id:
            seen.add(message_id)
        path.append(current)
        parent_id = str(current.get("parent_message_id", "") or "").strip()
        current = by_id.get(parent_id) if parent_id else None
    path.reverse()

    if path:
        first_sequence = int(path[0].get("sequence", 0) or 0)
        prefix = [
            item
            for item in rows
            if item["branch_id"] == DEFAULT_BRANCH_ID
            and int(item.get("sequence", 0) or 0) < first_sequence
            and str(item.get("message_id", "")) not in seen
        ]
        return [*prefix, *path]
    return candidates


def _visible_message_rows(messages: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in messages or ():
        if not isinstance(item, Mapping):
            continue
        role = bounded_text(item.get("role"), 16).lower()
        if role not in {"user", "assistant"}:
            continue
        content = bounded_visible_text(item.get("content"), 1600)
        if not content:
            continue
        try:
            sequence = int(item.get("sequence", 0) or 0)
        except (TypeError, ValueError, OverflowError):
            sequence = 0
        rows.append(
            {
                "role": role,
                "content": content,
                "message_id": bounded_text(item.get("message_id"), 128),
                "sequence": max(0, sequence),
            }
        )
    return rows


def living_transcript(
    messages: Sequence[Mapping[str, Any]] | None,
    *,
    turn_limit: int = LIVING_TURN_LIMIT,
) -> list[dict[str, str]]:
    """Return the recent user/assistant turns that stay in model context.

    Older turns are expected to survive only as working-memory checkpoints.
    """

    rows = _visible_message_rows(messages)
    if not rows:
        return []
    kept: list[dict[str, Any]] = []
    user_turns = 0
    limit = max(1, int(turn_limit or LIVING_TURN_LIMIT))
    for item in reversed(rows):
        kept.append(item)
        if item["role"] == "user":
            user_turns += 1
            if user_turns >= limit:
                break
    kept.reverse()
    return [
        {"role": str(item["role"]), "content": bounded_visible_text(item["content"], 800)}
        for item in kept
    ]


def living_user_questions(
    messages: Sequence[Mapping[str, Any]] | None,
    *,
    limit: int = LIVING_TURN_LIMIT,
) -> list[str]:
    questions: list[str] = []
    for item in living_transcript(messages, turn_limit=limit):
        if item["role"] != "user":
            continue
        _quote, body = parse_quoted_user_message(item.get("content"))
        text = bounded_text(body or item.get("content"), 800)
        if text and text not in questions:
            questions.append(text)
    return questions[: max(1, int(limit or LIVING_TURN_LIMIT))]


def user_turn_count(messages: Sequence[Mapping[str, Any]] | None) -> int:
    return sum(1 for item in _visible_message_rows(messages) if item["role"] == "user")


def conversation_context_usage(
    *,
    messages: Sequence[Mapping[str, Any]] | None = None,
    working_memory: Mapping[str, Any] | None = None,
    current_question: str = "",
    budget: int = CONTEXT_BUDGET_CHARS,
) -> dict[str, Any]:
    """Estimate the bounded model-facing context, not a billing statement."""

    living = living_transcript(messages)
    memory = working_memory_prompt(working_memory)
    archived = max(0, user_turn_count(messages) - len(living_user_questions(messages)))
    payload = {
        "living_transcript": living,
        "working_memory": memory,
        "question": bounded_text(current_question, 1200),
    }
    try:
        estimated_chars = len(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
        )
    except (TypeError, ValueError, OverflowError):
        estimated_chars = 0
    budget_chars = max(1, int(budget or CONTEXT_BUDGET_CHARS))
    share = min(1.0, estimated_chars / budget_chars)
    constraints = memory.get("user_constraints", [])
    decisions = memory.get("decisions", [])
    open_questions = memory.get("open_questions", [])
    active_skills = memory.get("active_skill_ids", [])
    frontier = memory.get("research_frontier", [])
    assumptions = memory.get("assumption_ledger", [])
    lenses = memory.get("explored_lenses", [])
    research_gaps = memory.get("research_gaps", [])
    return {
        "schema_version": "deep-context-usage-v1",
        "branch_id": normalize_branch_id(memory.get("branch_id")),
        "living_turns": len(living_user_questions(messages)),
        "archived_turns": archived,
        "visible_messages": len(_visible_message_rows(messages)),
        "estimated_chars": estimated_chars,
        "budget_chars": budget_chars,
        "share": round(share, 3),
        "compacted": bool(memory) and archived > 0,
        "current_objective": bounded_text(memory.get("current_objective"), 240),
        "constraint_count": len(constraints) if isinstance(constraints, list) else 0,
        "decision_count": len(decisions) if isinstance(decisions, list) else 0,
        "open_question_count": (
            len(open_questions) if isinstance(open_questions, list) else 0
        ),
        "active_skill_count": (
            len(active_skills) if isinstance(active_skills, list) else 0
        ),
        "frontier_count": len(frontier) if isinstance(frontier, list) else 0,
        "assumption_count": len(assumptions) if isinstance(assumptions, list) else 0,
        "explored_lens_count": len(lenses) if isinstance(lenses, list) else 0,
        "research_gap_count": (
            len(research_gaps) if isinstance(research_gaps, list) else 0
        ),
    }


def compaction_notice(usage: Mapping[str, Any] | None) -> str:
    source = usage if isinstance(usage, Mapping) else {}
    if not source.get("compacted"):
        return ""
    try:
        archived = max(0, int(source.get("archived_turns", 0) or 0))
    except (TypeError, ValueError, OverflowError):
        archived = 0
    try:
        living = max(0, int(source.get("living_turns", 0) or 0))
    except (TypeError, ValueError, OverflowError):
        living = 0
    try:
        share = int(round(float(source.get("share", 0) or 0) * 100))
    except (TypeError, ValueError, OverflowError):
        share = 0
    return (
        f"已将前 {archived} 轮研究压缩为决策记忆，当前窗口保留最近 {living} 轮。"
        f"上下文占用约 {max(0, min(100, share))}%。"
    )


def _string_list(value: Any, *, limit: int, item_limit: int) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    result: list[str] = []
    for item in list(value)[:limit]:
        text = bounded_text(item, item_limit)
        if text and text not in result:
            result.append(text)
    return result


def _bounded_mapping_rows(
    value: Any,
    *,
    fields: Mapping[str, int],
    limit: int,
) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    rows: list[dict[str, str]] = []
    for item in list(value)[:limit]:
        if not isinstance(item, Mapping):
            continue
        row = {
            field: bounded_text(item.get(field), size)
            for field, size in fields.items()
            if bounded_text(item.get(field), 8)
        }
        if row:
            rows.append(row)
    return rows


def _merge_research_rows(
    current: Sequence[Mapping[str, Any]],
    previous: Any,
    *,
    identity_fields: Sequence[str],
    fields: Mapping[str, int],
    limit: int,
) -> list[dict[str, str]]:
    inherited = _bounded_mapping_rows(previous, fields=fields, limit=limit)
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for source in [*current, *inherited]:
        row = {
            field: bounded_text(source.get(field), size)
            for field, size in fields.items()
            if bounded_text(source.get(field), 8)
        }
        identity = next(
            (row.get(field, "").casefold() for field in identity_fields if row.get(field)),
            "",
        )
        if not identity or identity in seen:
            continue
        seen.add(identity)
        merged.append(row)
        if len(merged) >= limit:
            break
    return merged


def _research_memory(
    source: Mapping[str, Any],
    prior: Mapping[str, Any],
    directions: Sequence[Mapping[str, Any]],
    open_questions: Sequence[str],
) -> dict[str, Any]:
    """Project non-blocking research progress for the next divergent turn."""

    frontier = _bounded_mapping_rows(
        source.get("research_frontier"),
        fields={
            "direction": 160,
            "status": 32,
            "why_promising": 420,
            "assumption": 420,
            "next_probe": 420,
        },
        limit=8,
    )
    raw_directions = source.get("concept_directions")
    has_new_directions = bool(
        isinstance(raw_directions, Sequence)
        and not isinstance(raw_directions, (str, bytes))
        and raw_directions
    )
    if not frontier and has_new_directions:
        for index, item in enumerate(directions[:6]):
            name = bounded_text(item.get("name"), 160)
            if not name:
                continue
            frontier.append(
                {
                    "direction": name,
                    "status": "stable" if item.get("stable") else "exploring",
                    "why_promising": bounded_text(
                        item.get("winning_angle")
                        or item.get("innovation_thesis")
                        or item.get("disruptive_difference"),
                        420,
                    ),
                    "assumption": bounded_text(item.get("changed_assumption"), 420),
                    "next_probe": bounded_text(
                        open_questions[index] if index < len(open_questions) else "",
                        420,
                    ),
                }
            )
    frontier = _merge_research_rows(
        frontier,
        prior.get("research_frontier"),
        identity_fields=("direction",),
        fields={
            "direction": 160,
            "status": 32,
            "why_promising": 420,
            "assumption": 420,
            "next_probe": 420,
        },
        limit=8,
    )

    assumptions = _bounded_mapping_rows(
        source.get("assumption_ledger"),
        fields={
            "assumption": 420,
            "direction": 160,
            "status": 32,
            "rationale": 420,
        },
        limit=12,
    )
    if not assumptions and has_new_directions:
        for item in directions[:6]:
            assumption = bounded_text(item.get("changed_assumption"), 420)
            if not assumption:
                continue
            assumptions.append(
                {
                    "assumption": assumption,
                    "direction": bounded_text(item.get("name"), 160),
                    "status": "retained" if item.get("stable") else "open",
                    "rationale": bounded_text(
                        item.get("winning_angle") or item.get("disruptive_difference"),
                        420,
                    ),
                }
            )
    assumptions = _merge_research_rows(
        assumptions,
        prior.get("assumption_ledger"),
        identity_fields=("assumption",),
        fields={
            "assumption": 420,
            "direction": 160,
            "status": 32,
            "rationale": 420,
        },
        limit=12,
    )

    strategy = source.get("research_strategy")
    strategy = strategy if isinstance(strategy, Mapping) else {}
    orchestration = source.get("orchestration")
    orchestration = orchestration if isinstance(orchestration, Mapping) else {}
    steps = source.get("divergence_steps")
    steps = steps if isinstance(steps, Sequence) and not isinstance(steps, (str, bytes)) else []
    explored_lenses = _string_list(
        [
            *(strategy.get("lenses", []) if isinstance(strategy.get("lenses"), list) else []),
            *(orchestration.get("divergence_axes", []) if isinstance(orchestration.get("divergence_axes"), list) else []),
            *(orchestration.get("internal_dimensions", []) if isinstance(orchestration.get("internal_dimensions"), list) else []),
            *[
                item.get("axis") or item.get("title") or item.get("stage")
                for item in steps[:8]
                if isinstance(item, Mapping)
            ],
            *(prior.get("explored_lenses", []) if isinstance(prior.get("explored_lenses"), list) else []),
        ],
        limit=18,
        item_limit=120,
    )

    assessment = source.get("research_assessment")
    assessment = assessment if isinstance(assessment, Mapping) else {}
    legacy_gate = source.get("quality_gate")
    legacy_gate = legacy_gate if isinstance(legacy_gate, Mapping) else {}
    research_gaps = sanitize_public_research_gaps(
        [
            *(source.get("research_gaps", []) if isinstance(source.get("research_gaps"), list) else []),
            *(assessment.get("research_gaps", []) if isinstance(assessment.get("research_gaps"), list) else []),
            *(assessment.get("gaps", []) if isinstance(assessment.get("gaps"), list) else []),
            *(assessment.get("advisories", []) if isinstance(assessment.get("advisories"), list) else []),
            *(legacy_gate.get("block_reasons", []) if isinstance(legacy_gate.get("block_reasons"), list) else []),
            *open_questions,
        ],
        limit=10,
        item_limit=500,
    )
    actions = strategy.get("actions") or strategy.get("tools")
    actions = actions if isinstance(actions, list) else []
    last_strategy = {
        "mode": bounded_text(
            strategy.get("mode") or strategy.get("strategy") or orchestration.get("pattern"),
            120,
        ),
        "rationale": bounded_text(strategy.get("rationale"), 500),
        "actions": _string_list(actions, limit=6, item_limit=64),
        "lenses": _string_list(strategy.get("lenses", []), limit=8, item_limit=120),
    }
    last_strategy = {
        key: value for key, value in last_strategy.items() if value not in (None, "", [], {})
    } or (
        dict(prior.get("last_research_strategy"))
        if isinstance(prior.get("last_research_strategy"), Mapping)
        else {}
    )
    try:
        iteration = max(0, int(prior.get("research_iteration", 0) or 0)) + 1
    except (TypeError, ValueError, OverflowError):
        iteration = 1
    return {
        "research_iteration": iteration,
        "research_frontier": frontier,
        "assumption_ledger": assumptions,
        "explored_lenses": explored_lenses,
        "research_gaps": research_gaps,
        "last_research_strategy": last_strategy,
    }


def build_working_memory(
    *,
    answer: Mapping[str, Any] | None,
    question: str,
    branch_id: str = DEFAULT_BRANCH_ID,
    turn_id: str = "",
    previous: Mapping[str, Any] | None = None,
    steering_inputs: Sequence[str] = (),
    source_message_id: str = "",
    source_sequence: int = 0,
) -> dict[str, Any]:
    """Build bounded decision memory from the structured dialogue result."""

    source = answer if isinstance(answer, Mapping) else {}
    prior = previous if isinstance(previous, Mapping) else {}
    quoted_excerpt, question_body = parse_quoted_user_message(question)
    quoted_constraint = (
        f"专家点名引用：{bounded_text(quoted_excerpt, 420)}" if quoted_excerpt else ""
    )
    constraints = _string_list(
        [
            quoted_constraint,
            *(prior.get("user_constraints", []) or []),
            *steering_inputs,
        ],
        limit=12,
        item_limit=600,
    )

    directions: list[dict[str, Any]] = []
    raw_directions = source.get("concept_directions", [])
    if not isinstance(raw_directions, Sequence) or isinstance(
        raw_directions, (str, bytes)
    ) or not raw_directions:
        raw_directions = prior.get("candidate_directions", [])
    if isinstance(raw_directions, Sequence) and not isinstance(raw_directions, (str, bytes)):
        for item in list(raw_directions)[:3]:
            if not isinstance(item, Mapping):
                continue
            compact = {
                key: bounded_text(item.get(key), limit)
                for key, limit in (
                    ("name", 160),
                    ("innovation_variant_name", 160),
                    ("winning_angle", 320),
                    ("innovation_thesis", 500),
                    ("changed_assumption", 420),
                    ("equipment_form", 420),
                    ("innovation_equipment_form", 420),
                    ("operational_mechanism", 600),
                    ("decisive_target", 500),
                    ("direct_damage_mechanism", 500),
                    ("mission_kill_criterion", 420),
                    ("direct_military_effects", 500),
                    ("military_value", 500),
                    ("disruptive_difference", 500),
                    ("novelty", 500),
                    ("related_scenario", 400),
                    ("implementation_concept", 500),
                    # Keep the falsifiable handoff fields available after a
                    # refresh or branch switch; they are compact decision
                    # metadata, not provider transcript.
                    ("adversary_response", 420),
                    ("feasibility_anchor", 420),
                    ("rejection_risk", 320),
                    ("branch_id", 120),
                    ("branch_type", 80),
                    ("novelty_delta", 420),
                    ("counterfactual_test", 420),
                    ("research_probe", 420),
                )
                if bounded_text(item.get(key), 8)
            }
            if compact.get("name"):
                compact["stable"] = bool(item.get("stable", False))
                directions.append(compact)

    adjudication = source.get("adjudication", {})
    adjudication = adjudication if isinstance(adjudication, Mapping) else {}
    decisions: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    reviews = adjudication.get("candidate_reviews", [])
    if isinstance(reviews, Sequence) and not isinstance(reviews, (str, bytes)):
        for item in list(reviews)[:8]:
            if not isinstance(item, Mapping):
                continue
            row = {
                "candidate": bounded_text(item.get("candidate_name"), 160),
                "verdict": bounded_text(item.get("verdict"), 24).lower(),
                "reason": bounded_text(
                    item.get("decisive_issue") or item.get("required_revision"), 420
                ),
            }
            if not row["candidate"]:
                continue
            (rejected if row["verdict"] == "reject" else decisions).append(row)

    def inherited_decisions(key: str) -> list[dict[str, str]]:
        rows = prior.get(key, [])
        if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
            return []
        inherited: list[dict[str, str]] = []
        for item in list(rows)[:8]:
            if not isinstance(item, Mapping):
                continue
            row = {
                "candidate": bounded_text(
                    item.get("candidate") or item.get("candidate_name"), 160
                ),
                "verdict": bounded_text(item.get("verdict"), 24).lower(),
                "reason": bounded_text(
                    item.get("reason")
                    or item.get("decisive_issue")
                    or item.get("required_revision"),
                    420,
                ),
            }
            if row["candidate"]:
                inherited.append(row)
        return inherited

    if not decisions:
        decisions = inherited_decisions("decisions")
    if not rejected:
        rejected = inherited_decisions("rejected_directions")

    summaries = [
        clean
        for item in _string_list(source.get("visible_summary", []), limit=4, item_limit=600)
        for clean in [sanitize_public_research_prose(item, limit=600)]
        if clean
    ]
    if not summaries:
        rationale = sanitize_public_research_prose(
            source.get("selection_rationale"), limit=1000
        )
        if rationale:
            summaries = [rationale]
    if not summaries:
        summaries = [
            clean
            for item in _string_list(
                prior.get("latest_summary", []), limit=4, item_limit=600
            )
            for clean in [sanitize_public_research_prose(item, limit=600)]
            if clean
        ]

    selection_rationale = sanitize_public_research_prose(
        source.get("selection_rationale") or prior.get("selection_rationale"),
        limit=1000,
    )
    open_questions = sanitize_public_research_gaps(
        source.get("next_questions") or source.get("open_questions") or [],
        limit=5,
        item_limit=500,
    )
    if not open_questions:
        open_questions = sanitize_public_research_gaps(
            prior.get("open_questions", []), limit=5, item_limit=500
        )

    try:
        answer_fingerprint = hashlib.sha256(
            json.dumps(source, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:24]
    except (TypeError, ValueError, OverflowError):
        answer_fingerprint = ""

    runtime = source.get("runtime")
    runtime = runtime if isinstance(runtime, Mapping) else {}
    active_skill_ids = _string_list(
        runtime.get("active_skill_ids") or prior.get("active_skill_ids") or [],
        limit=6,
        item_limit=140,
    )
    plugin_ids = _string_list(
        runtime.get("plugin_ids") or prior.get("plugin_ids") or [],
        limit=12,
        item_limit=100,
    )
    last_tool_plan = _string_list(
        runtime.get("plan") or runtime.get("tools") or [],
        limit=5,
        item_limit=64,
    )
    research_memory = _research_memory(
        source,
        prior,
        directions,
        open_questions,
    )

    memory = {
        "schema_version": "deep-working-memory-v2",
        "branch_id": normalize_branch_id(branch_id),
        "turn_id": bounded_text(turn_id, 128),
        "current_objective": bounded_text(
            question_body or question or prior.get("current_objective"), 1200
        ),
        "user_constraints": constraints,
        "candidate_directions": directions,
        "decisions": decisions[:6],
        "rejected_directions": rejected[:6],
        "latest_summary": summaries,
        "selection_rationale": selection_rationale,
        "open_questions": open_questions,
        "finalization_status": bounded_text(
            source.get("finalization_status") or prior.get("finalization_status"),
            48,
        ),
        "active_skill_ids": active_skill_ids,
        "plugin_ids": plugin_ids,
        "last_tool_plan": last_tool_plan,
        **research_memory,
    }
    source_checkpoint = {
        "assistant_message_id": bounded_text(source_message_id, 128),
        "assistant_sequence": max(0, int(source_sequence or 0)),
        "answer_fingerprint": answer_fingerprint,
    }
    memory["source_checkpoint"] = {
        key: value for key, value in source_checkpoint.items() if value not in (None, "", 0)
    }
    return memory


def working_memory_prompt(memory: Mapping[str, Any] | None) -> dict[str, Any]:
    """Positive projection of durable memory for the model-facing context."""

    if not isinstance(memory, Mapping):
        return {}
    allowed = (
        "schema_version",
        "branch_id",
        "current_objective",
        "user_constraints",
        "candidate_directions",
        "decisions",
        "rejected_directions",
        "latest_summary",
        "selection_rationale",
        "open_questions",
        "finalization_status",
        "active_skill_ids",
        "plugin_ids",
        "last_tool_plan",
        "research_iteration",
        "research_frontier",
        "assumption_ledger",
        "explored_lenses",
        "research_gaps",
        "last_research_strategy",
    )
    projected = {
        key: memory.get(key)
        for key in allowed
        if memory.get(key) not in (None, "", [], {})
    }
    for key, limit in (("latest_summary", 6), ("open_questions", 8)):
        if key in projected:
            projected[key] = sanitize_public_research_gaps(
                projected.get(key, []), limit=limit, item_limit=700
            )
    if "selection_rationale" in projected:
        projected["selection_rationale"] = sanitize_public_research_prose(
            projected.get("selection_rationale"), limit=1200
        )
    return {
        key: value for key, value in projected.items() if value not in (None, "", [], {})
    }


def branch_working_memory(
    memory: Mapping[str, Any] | None,
    branch_id: str = DEFAULT_BRANCH_ID,
) -> dict[str, Any]:
    """Read one branch checkpoint while accepting the original flat schema."""

    if not isinstance(memory, Mapping):
        return {}
    branches = memory.get("branches")
    wanted = normalize_branch_id(branch_id)
    if isinstance(branches, Mapping):
        selected = branches.get(wanted)
        return dict(selected) if isinstance(selected, Mapping) else {}
    stored_branch = normalize_branch_id(memory.get("branch_id"))
    return dict(memory) if stored_branch == wanted else {}


def merge_branch_working_memory(
    memory: Mapping[str, Any] | None,
    branch_id: str,
    checkpoint: Mapping[str, Any],
) -> dict[str, Any]:
    """Upsert one bounded branch checkpoint without overwriting sibling work."""

    wanted = normalize_branch_id(branch_id)
    branches: dict[str, Any] = {}
    if isinstance(memory, Mapping) and isinstance(memory.get("branches"), Mapping):
        branches = {
            normalize_branch_id(key): dict(value)
            for key, value in memory["branches"].items()
            if isinstance(value, Mapping)
        }
    elif isinstance(memory, Mapping) and memory:
        legacy_branch = normalize_branch_id(memory.get("branch_id"))
        branches[legacy_branch] = dict(memory)
    branches[wanted] = dict(checkpoint)
    # Conversation branches are intentionally bounded. Oldest inactive branch
    # checkpoints can always be reconstructed from their visible message path.
    if len(branches) > 12:
        branches = dict(list(branches.items())[-12:])
    return {
        "schema_version": "deep-working-memory-branches-v1",
        "active_branch_id": wanted,
        "branches": branches,
    }
