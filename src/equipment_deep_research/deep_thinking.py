"""Bounded deep-thinking compatibility helpers.

This module intentionally keeps the conversation contract separate from the
main S1--S6 run lifecycle.  A session stores only user-visible messages,
structured context references and produced artifacts; provider reasoning
traces are never persisted or returned to the browser.

The authoritative ledger for live runs is SQLite (``deep_sessions``,
``deep_messages``, ``deep_jobs`` and ``capability_versions``), owned by the
persistence repository.  The JSON helpers retained here are a bounded,
atomic compatibility projection for legacy/artifact-only historical runs and
filesystem recovery; callers must not treat them as the source of truth.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from threading import RLock
from typing import Any
from uuid import uuid4


SCHEMA_VERSION = "deep-thinking-v1"
MAX_SESSIONS_PER_RUN = 100
MAX_MESSAGES_PER_SESSION = 80
MAX_MESSAGE_CHARS = 8000
MAX_CONTEXT_CHARS = 24000
MAX_ARTIFACTS_PER_SESSION = 24

# The live single-equipment dialogue is intentionally a different context
# contract from the evidence/audit pipeline.  It is a creative redesign
# surface: the current Query, the weapons already formed under that Query,
# one focused seed and the expert's questions are enough to leap to a new
# equipment hypothesis.  Keep this list explicit so a future card field
# cannot accidentally pull the old audit context back into the model prompt.
SINGLE_EQUIPMENT_INNOVATION_MODE = "single_equipment_innovation_v1"
_QUERY_WEAPON_CATALOG_FIELDS = (
    "name",
    "title",
    "primary_equipment_identity",
    "equipment_form",
    "equipment_forms",
    "equipment_category",
    "operational_mechanism",
    "mechanism_chain",
    "winning_mechanism",
    "direct_military_effects",
    "military_value",
    "capability_gap",
    "related_scenario",
    "innovation_variant_name",
    "innovation_equipment_form",
)
_INNOVATION_DROP_KEYS = {
    "evidence",
    "evidence_id",
    "evidence_ids",
    "evidence_refs",
    "direct_evidence_refs",
    "source_evidence_refs",
    "evidence_index",
    "evidence_gaps",
    "validation",
    "validation_plan",
    "verification",
    "verification_plan",
    "verification_status",
    "version_status",
    "capability_version_status",
    "failure_boundary",
    "failure_boundaries",
    "risk_boundaries",
    "operational_constraints",
    "audit",
    "audit_inputs",
    "auditability",
    "round_summary",
    "recent_visible_history",
    "formal_capability_cards",
    "candidate_lineage",
    "capability_cards",
    "reference_weapons",
    "provider_metadata",
    "raw_session",
    "chain_of_thought",
    "confidence",
    "confidence_limited",
    "status",
    "source",
    "selection_status",
    "provenance_status",
}
_INNOVATION_ALLOWED_EQUIPMENT_KEYS = {
    "hypothesis_id",
    "card_binding_id",
    "capability_id",
    "candidate_id",
    "name",
    "title",
    "primary_equipment_identity",
    "equipment_form",
    "equipment_forms",
    "equipment_category",
    "capability_type",
    "function",
    "project_function",
    "operational_mechanism",
    "mechanism_chain",
    "winning_mechanism",
    "source_winning_logic",
    "military_value",
    "direct_military_effects",
    "mission_effect",
    "related_scenario",
    "capability_gap",
    "mission_node",
    "target",
    "target_type",
    "platform",
    "payload",
    "technology_implementation",
    "technology_features",
    "system_architecture",
    "innovation_delta",
    "innovation_variant_name",
    "innovation_equipment_form",
    "new_equipment_form",
    "design_principle",
    "implementation_concept",
    "evolution_path",
    "differentiation",
    "task_effect",
}


def _innovation_key(value: object) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")


def _query_weapon_identity(item: Mapping[str, Any]) -> str:
    parts = [
        str(item.get(key, "") or "").strip()
        for key in (
            "name",
            "title",
            "primary_equipment_identity",
            "innovation_variant_name",
            "equipment_form",
            "innovation_equipment_form",
        )
    ]
    return re.sub(r"\s+", "", "".join(parts)).casefold()


def _compact_query_weapon(item: Mapping[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in _QUERY_WEAPON_CATALOG_FIELDS:
        child = item.get(key)
        if child in (None, "", [], {}):
            continue
        if isinstance(child, (list, tuple, set, frozenset)):
            values = [str(part).strip()[:180] for part in list(child)[:4] if str(part).strip()]
            if values:
                compact[key] = values
            continue
        compact[key] = str(child).strip()[:500]
    name = str(
        compact.get("name")
        or compact.get("title")
        or compact.get("primary_equipment_identity")
        or compact.get("innovation_variant_name")
        or compact.get("equipment_form")
        or ""
    ).strip()
    if not name:
        return {}
    compact.setdefault("name", name)
    return compact


def project_query_weapons(
    context_refs: Mapping[str, Any] | None = None,
    *,
    source_equipment: Mapping[str, Any] | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Project the current Query's already-formed weapons as a leap catalog.

    Evidence, validation and audit fields stay dropped.  The selected seed is
    kept first so later Agents can diverge *from* it instead of rewriting it.
    """

    source = context_refs if isinstance(context_refs, Mapping) else {}
    current = source.get("current_result_context")
    current = current if isinstance(current, Mapping) else {}
    buckets: list[Any] = [
        source_equipment,
        source.get("candidate"),
        source.get("reference_weapon"),
        source.get("focused_equipment"),
        current.get("selected"),
        current.get("capability_cards"),
        current.get("reference_weapons"),
        source.get("formal_capability_cards"),
        source.get("reference_weapons"),
        source.get("candidate_lineage"),
    ]
    catalog: list[dict[str, Any]] = []
    seen: set[str] = set()
    for bucket in buckets:
        rows: Sequence[Any]
        if isinstance(bucket, Mapping):
            rows = [bucket]
        elif isinstance(bucket, Sequence) and not isinstance(bucket, (str, bytes)):
            rows = list(bucket)[:16]
        else:
            continue
        for item in rows:
            if not isinstance(item, Mapping):
                continue
            compact = _compact_query_weapon(item)
            identity = _query_weapon_identity(compact)
            if not compact or not identity or identity in seen:
                continue
            seen.add(identity)
            catalog.append(compact)
            if len(catalog) >= max(1, min(12, int(limit or 8))):
                return catalog
    return catalog


def single_equipment_innovation_context(
    context_refs: Mapping[str, Any] | None = None,
    *,
    query: str = "",
    equipment: Mapping[str, Any] | None = None,
    question: str = "",
    focus: str = "",
    messages: Sequence[Mapping[str, Any]] | None = None,
    working_memory: Mapping[str, Any] | None = None,
    limit: int = 12000,
) -> dict[str, Any]:
    """Build the model-facing context for Query-weapon creative divergence.

    This is deliberately *not* a generic redaction pass.  It is a positive
    projection with a small allow-list.  The parent run may contain dozens of
    evidence cards, audit decisions and validation boundaries, but none of
    those are inputs to this mode.  Only the Query, the weapons already
    formed under that Query, one focused seed and expert questions are
    retained.  Canonical IDs remain so a resulting hypothesis can be linked
    by the server; they do not carry source prose.
    """

    source = context_refs if isinstance(context_refs, Mapping) else {}
    candidate: Mapping[str, Any] | None = equipment if isinstance(equipment, Mapping) else None
    if candidate is None:
        for key in ("candidate", "reference_weapon", "focused_equipment"):
            value = source.get(key)
            if isinstance(value, Mapping):
                candidate = value
                break
    if candidate is None:
        current = source.get("current_result_context")
        if isinstance(current, Mapping) and isinstance(current.get("selected"), Mapping):
            candidate = current.get("selected")
    candidate = candidate or {}

    def project(value: Any, *, equipment_object: bool = False, depth: int = 0) -> Any:
        if depth > 5:
            return _bounded_text(value, 600)
        if isinstance(value, Mapping):
            result: dict[str, Any] = {}
            for raw_key, child in list(value.items())[:80]:
                key = str(raw_key)
                normalized = _innovation_key(key)
                if normalized in _INNOVATION_DROP_KEYS:
                    continue
                # Do not let aliases such as ``prior_evidence`` or
                # ``validation_notes`` bypass the explicit field list.
                if any(token in normalized for token in ("evidence", "validation", "verification", "failure_boundary", "provider", "trace", "audit")):
                    continue
                if equipment_object and normalized not in _INNOVATION_ALLOWED_EQUIPMENT_KEYS:
                    continue
                projected = project(child, equipment_object=False, depth=depth + 1)
                if projected not in (None, "", [], {}):
                    result[key] = projected
            return result
        if isinstance(value, (list, tuple, set, frozenset)):
            return [project(item, equipment_object=False, depth=depth + 1) for item in list(value)[:16]]
        if isinstance(value, str):
            return _bounded_text(value, 1400)
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return _bounded_text(value, 600)

    projected_equipment = project(candidate, equipment_object=True)
    if not isinstance(projected_equipment, dict):
        projected_equipment = {}

    from equipment_deep_research.domain.conversation import (
        living_transcript,
        living_user_questions,
        user_turn_count,
        working_memory_prompt,
    )
    from equipment_deep_research.deep_runtime.identity import IDENTITY_SKILL

    durable_memory = working_memory_prompt(working_memory)
    living_messages = living_transcript(messages)
    prior_questions = living_user_questions(messages)
    prior_round_conclusions = ""
    if durable_memory:
        prior_constraints = durable_memory.get("user_constraints", [])
        if isinstance(prior_constraints, Sequence) and not isinstance(
            prior_constraints, (str, bytes)
        ):
            for item in list(prior_constraints)[-8:]:
                text = _bounded_text(item, 1600)
                if text and text not in prior_questions:
                    prior_questions.append(text)
        memory_summary = {
            key: durable_memory.get(key)
            for key in (
                "current_objective",
                "candidate_directions",
                "decisions",
                "rejected_directions",
                "latest_summary",
                "open_questions",
            )
            if durable_memory.get(key) not in (None, "", [], {})
        }
        prior_round_conclusions = json.dumps(
            memory_summary, ensure_ascii=False, separators=(",", ":")
        )[:4200]
    elif living_messages:
        # A follow-up turn must iterate on the previous round's directions
        # rather than re-derive them from the raw seed.  Extract only the
        # decision-bearing sections (result + candidate directions) from the
        # latest living assistant summary; the full transcript would re-anchor
        # the model on its own prose.
        for item in reversed(living_messages):
            if str(item.get("role", "")).strip().lower() != "assistant":
                continue
            content = str(item.get("content", "") or "")
            if not content.strip():
                continue
            sections: list[str] = []
            for title in ("本轮完整结果", "候选方向"):
                match = re.search(
                    rf"#{{1,6}}\s*{title}\s*\n(.*?)(?=\n#{{1,6}}\s|\Z)",
                    content,
                    flags=re.DOTALL,
                )
                if match and match.group(1).strip():
                    sections.append(f"{title}：{match.group(1).strip()}")
            prior_round_conclusions = _bounded_text(
                "\n".join(sections) or content, 2400
            )
            break
    # A caller can pass the session history through context_refs when this
    # helper is used outside the API worker.
    if not prior_questions:
        history = source.get("conversation_history") or source.get("messages")
        if isinstance(history, Sequence) and not isinstance(history, (str, bytes)):
            prior_questions = living_user_questions(history)

    query_weapons = project_query_weapons(
        source,
        source_equipment=projected_equipment or candidate,
        limit=8,
    )
    projected_context = {
        "mode": SINGLE_EQUIPMENT_INNOVATION_MODE,
        "context_policy": "query_equipment_questions_only",
        "identity": IDENTITY_SKILL,
        "innovation_goal": "以当前 Query 下已有武器装备为基线，深度发散并推理出名称、构型与作用机理均已跃迁的新质颠覆武器装备",
        "query": _bounded_text(query or source.get("query", ""), 4000),
        "focus": _bounded_text(focus or source.get("focus", ""), 1600),
        "question": _bounded_text(question, MAX_MESSAGE_CHARS),
        "source_equipment": projected_equipment,
        "query_weapons": query_weapons,
        "prior_expert_questions": prior_questions[:8],
        # Empty on the first turn; later turns carry the previous round's
        # visible conclusions so the council deepens or refutes them instead
        # of restarting from the raw equipment seed.
        "prior_round_conclusions": prior_round_conclusions,
        "living_transcript": living_messages,
        "working_memory": durable_memory,
        "dialogue_turn": user_turn_count(messages) + 1,
    }
    bounded = _bounded_json(projected_context, limit=limit)
    fallback = {
        "mode": SINGLE_EQUIPMENT_INNOVATION_MODE,
        "context_policy": "query_equipment_questions_only",
        "query": _bounded_text(query, 4000),
        "question": _bounded_text(question, MAX_MESSAGE_CHARS),
        "source_equipment": projected_equipment,
        "query_weapons": query_weapons[:4],
    }
    return bounded if isinstance(bounded, dict) else fallback

# Context is assembled from browser payloads and interaction projections.  Do
# not persist or return credential-like fields even when a caller accidentally
# includes them in a card/context object.  This is intentionally key-based;
# values such as evidence IDs and ordinary military terminology are retained.
_SENSITIVE_KEY_RE = re.compile(
    r"(?:api[_-]?key|access[_-]?key|secret|password|passwd|token|authorization|cookie|credential|private[_-]?key|client[_-]?secret|chain[_-]?of[_-]?thought|raw[_-]?session|provider[_-]?metadata)",
    flags=re.IGNORECASE,
)

_LOCK = RLock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def safe_segment(value: object, *, limit: int = 180) -> str:
    """Return a collision-resistant filesystem-safe identifier segment.

    Run and hypothesis identifiers are opaque values.  Replacing punctuation
    (the previous behaviour) is unsafe because distinct identifiers such as
    ``"a b"`` and ``"a-b"`` collapse onto the same sidecar directory.  Keep
    ordinary identifiers readable, but derive a stable digest whenever the
    value needs normalization or truncation.  Path separators and NUL remain
    invalid rather than being silently accepted.
    """

    text = str(value or "").strip()
    if not text or text in {".", ".."}:
        return ""
    if "/" in text or "\\" in text or "\x00" in text:
        return ""
    if limit < 16:
        limit = 16
    if len(text) <= limit and re.fullmatch(r"[\w.\-:@+]+", text, flags=re.UNICODE):
        return text
    # Preserve a short human-readable hint while making the mapping injective
    # for practical purposes.  The digest is based on the original value,
    # not the normalized hint, so punctuation changes cannot collide.
    hint = re.sub(r"[^\w.\-:@+]+", "-", text, flags=re.UNICODE).strip("-")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    room = max(1, limit - len(digest) - 2)
    return f"{hint[:room]}--{digest}"[:limit]


def _json_root(output_root: str | Path) -> Path:
    """Use a sidecar directory, never a main run directory.

    Creating a directory below ``outputs/runs/<run_id>`` before a Worker has
    started would make the Worker mistake the task for a resumable run.  The
    sidecar therefore lives next to the configured output root.
    """

    root = Path(output_root).expanduser().resolve()
    return root.parent / "deep-thinking"


def _run_dir(output_root: str | Path, run_id: str, *, create: bool = False) -> Path:
    run_segment = safe_segment(run_id)
    if not run_segment:
        raise ValueError("invalid run id")
    path = _json_root(output_root) / run_segment
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def _session_path(output_root: str | Path, run_id: str, session_id: str) -> Path:
    session_segment = safe_segment(session_id)
    if not session_segment:
        raise ValueError("invalid session id")
    return _run_dir(output_root, run_id, create=False) / f"{session_segment}.json"


def _research_path(output_root: str | Path, run_id: str) -> Path:
    return _run_dir(output_root, run_id, create=False) / "reference-research.json"


def _bounded_text(value: object, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _bounded_json(value: object, *, limit: int = MAX_CONTEXT_CHARS) -> Any:
    """Normalize arbitrary context to JSON-safe data within one total budget.

    The old implementation applied ``limit`` independently to every leaf,
    so a card containing dozens of long fields could still create a multi-MB
    sidecar and prompt payload.  We first remove sensitive keys and normalize
    the shape, then deterministically prune/truncate the complete value until
    its compact JSON representation is no larger than ``limit`` characters.
    """

    try:
        # A caller may deliberately request a smaller budget (for example a
        # compact event preview), so do not silently inflate it to 256.
        budget = max(2, int(limit))
    except (TypeError, ValueError):
        budget = MAX_CONTEXT_CHARS

    def encode(item: Any) -> str:
        try:
            return json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
        except (TypeError, ValueError, RecursionError):
            return json.dumps(str(item), ensure_ascii=False)

    def normalize(item: Any, depth: int = 0) -> Any:
        # A depth cap prevents hostile/corrupt client objects from exhausting
        # the API worker while retaining the visible prefix of normal cards.
        if depth >= 8:
            return _bounded_text(item, min(256, budget))
        if isinstance(item, Mapping):
            result: dict[str, Any] = {}
            for key, child in list(item.items())[:80]:
                normalized_key = _bounded_text(key, 100)
                if not normalized_key or _SENSITIVE_KEY_RE.search(normalized_key):
                    continue
                result[normalized_key] = normalize(child, depth + 1)
            return result
        if isinstance(item, (list, tuple, set, frozenset)):
            return [normalize(child, depth + 1) for child in list(item)[:80]]
        if isinstance(item, str):
            return _bounded_text(item, budget)
        if isinstance(item, (int, float, bool)) or item is None:
            return item
        return _bounded_text(item, min(900, budget))

    def fit(item: Any) -> Any:
        """Prune a normalized value until its serialized size fits budget."""

        if len(encode(item)) <= budget:
            return item
        if isinstance(item, str):
            # Binary search preserves the longest useful visible prefix while
            # accounting for JSON escaping and non-ASCII characters.
            low, high = 0, len(item)
            best = ""
            while low <= high:
                middle = (low + high) // 2
                candidate = item[:middle]
                if len(encode(candidate)) <= budget:
                    best = candidate
                    low = middle + 1
                else:
                    high = middle - 1
            return best
        if isinstance(item, dict):
            # Fit children first, then drop the largest remaining fields. This
            # is deterministic and tends to preserve short identity/status
            # fields while discarding bulky evidence prose last.
            fitted = {key: fit(child) for key, child in item.items()}
            while fitted and len(encode(fitted)) > budget:
                victim = max(
                    fitted,
                    key=lambda key: (len(encode(fitted[key])), str(key)),
                )
                del fitted[victim]
            return fitted
        if isinstance(item, list):
            fitted = [fit(child) for child in item]
            while fitted and len(encode(fitted)) > budget:
                fitted.pop()
            return fitted
        # Huge numeric values are exceedingly rare in a card; stringify them
        # rather than violating the total budget or raising on serialization.
        return fit(str(item))

    normalized = normalize(value)
    result = fit(normalized)
    # ``budget`` is intentionally a hard postcondition.  The fallback is
    # reachable only for pathological key overhead or an exotic serializer.
    if len(encode(result)) > budget:
        return ""
    return result


def _atomic_write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _read_json(path: Path, fallback: object) -> Any:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return fallback
    return payload


def _session_files(output_root: str | Path, run_id: str) -> list[Path]:
    directory = _run_dir(output_root, run_id, create=False)
    if not directory.is_dir() or directory.is_symlink():
        return []
    return sorted(
        (item for item in directory.glob("*.json") if item.name != "reference-research.json" and item.is_file() and not item.is_symlink()),
        key=lambda item: item.name,
    )


def _normalize_kind(value: object) -> str:
    kind = _bounded_text(value, 48).lower().replace("_", "-")
    aliases = {
        "capability": "capability-followup",
        "capability-card": "capability-followup",
        "follow-up": "capability-followup",
        "expert-followup": "capability-followup",
        "deep-research": "reference-research",
        "weapon": "reference-research",
        "reference-weapon": "reference-research",
        "agent": "deep-thinking",
        "global": "deep-thinking",
    }
    kind = aliases.get(kind, kind)
    return kind if kind in {"deep-thinking", "capability-followup", "reference-research"} else "deep-thinking"


def _session_public(record: Mapping[str, Any]) -> dict[str, Any]:
    """Project a session without internal storage details."""

    # Whitelist the public schema instead of copying arbitrary fields from a
    # sidecar file.  This protects against stale/provider metadata accidentally
    # becoming visible after a schema upgrade or a hand-edited artifact.
    public_keys = {
        "schema_version",
        "session_id",
        "run_id",
        "kind",
        "title",
        "capability_id",
        "card_binding_id",
        "capability_name",
        "hypothesis_id",
        "context_refs",
        "messages",
        "artifacts",
        "working_memory",
        "branches",
        "context_usage",
        "status",
        "turn_count",
        "created_by",
        "created_at",
        "updated_at",
    }
    result = {
        key: record.get(key)
        for key in public_keys
        if key in record and key != "_storage_path"
    }
    messages = result.get("messages")
    if isinstance(messages, list):
        # The browser needs the visible answer but never provider metadata that
        # could contain credentials or hidden reasoning fields.
        safe_messages = []
        for item in messages[-MAX_MESSAGES_PER_SESSION:]:
            if not isinstance(item, Mapping):
                continue
            safe_messages.append(
                {
                    "message_id": str(item.get("message_id", "")),
                    "role": str(item.get("role", "user")),
                    "content": _bounded_text(item.get("content", ""), MAX_MESSAGE_CHARS),
                    "created_at": str(item.get("created_at", "")),
                    "status": str(item.get("status", "completed")),
                    "parent_message_id": str(item.get("parent_message_id", "")),
                    "branch_id": str(item.get("branch_id", "main") or "main"),
                    "turn_id": str(item.get("turn_id", "")),
                    "message_kind": str(item.get("message_kind", "message")),
                    "artifact_refs": list(item.get("artifact_refs", []))[:16]
                    if isinstance(item.get("artifact_refs", []), list)
                    else [],
                    "version_refs": list(item.get("version_refs", []))[:16]
                    if isinstance(item.get("version_refs", []), list)
                    else [],
                }
            )
        result["messages"] = safe_messages
    context = result.get("context_refs")
    if context is not None:
        result["context_refs"] = _bounded_json(context)
    artifacts = result.get("artifacts")
    if isinstance(artifacts, list):
        result["artifacts"] = [_bounded_json(item, limit=12000) for item in artifacts[-MAX_ARTIFACTS_PER_SESSION:]]
    from equipment_deep_research.domain.conversation import (
        DEFAULT_BRANCH_ID,
        branch_message_path,
        branch_working_memory,
        conversation_context_usage,
        normalize_branch_id,
    )

    stored_memory = result.get("working_memory")
    stored_memory = stored_memory if isinstance(stored_memory, Mapping) else {}
    active_branch = normalize_branch_id(
        stored_memory.get("active_branch_id") or DEFAULT_BRANCH_ID
    )
    result["context_usage"] = conversation_context_usage(
        messages=branch_message_path(
            result.get("messages") if isinstance(result.get("messages"), list) else [],
            active_branch,
            result.get("branches") if isinstance(result.get("branches"), list) else [],
        ),
        working_memory=branch_working_memory(stored_memory, active_branch),
    )
    return result


def create_session(
    output_root: str | Path,
    *,
    run_id: str,
    kind: str = "deep-thinking",
    title: str = "深度思考会话",
    capability_id: str = "",
    capability_name: str = "",
    card_binding_id: str = "",
    hypothesis_id: str = "",
    context_refs: Mapping[str, Any] | None = None,
    created_by: str = "analyst",
) -> dict[str, Any]:
    """Create a bounded, resumable session."""

    run_id = safe_segment(run_id)
    if not run_id:
        raise ValueError("run_id is required")
    with _LOCK:
        existing = list_sessions(output_root, run_id=run_id)
        if len(existing) >= MAX_SESSIONS_PER_RUN:
            raise ValueError("session limit reached for this run")
        session_id = new_id("thinking")
        timestamp = now_iso()
        record = {
            "schema_version": SCHEMA_VERSION,
            "session_id": session_id,
            "run_id": run_id,
            "kind": _normalize_kind(kind),
            "title": _bounded_text(title or "深度思考会话", 240),
            "capability_id": _bounded_text(capability_id, 256),
            "card_binding_id": _bounded_text(card_binding_id, 256),
            "capability_name": _bounded_text(capability_name, 400),
            "hypothesis_id": _bounded_text(hypothesis_id, 256),
            "context_refs": _bounded_json(dict(context_refs or {})),
            "messages": [],
            "artifacts": [],
            "working_memory": {},
            "branches": [
                {
                    "branch_id": "main",
                    "parent_branch_id": "",
                    "forked_from_message_id": "",
                    "title": "主线",
                    "status": "active",
                }
            ],
            "status": "active",
            "turn_count": 0,
            "created_by": _bounded_text(created_by or "analyst", 120),
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        _atomic_write(_session_path(output_root, run_id, session_id), record)
        return _session_public(record)


def get_session(output_root: str | Path, *, run_id: str, session_id: str) -> dict[str, Any] | None:
    try:
        path = _session_path(output_root, run_id, session_id)
    except ValueError:
        return None
    with _LOCK:
        payload = _read_json(path, None)
    return _session_public(payload) if isinstance(payload, Mapping) else None


def list_sessions(output_root: str | Path, *, run_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with _LOCK:
        for path in _session_files(output_root, run_id):
            payload = _read_json(path, None)
            if isinstance(payload, Mapping) and payload.get("session_id"):
                rows.append(_session_public(payload))
    rows.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
    return rows[:MAX_SESSIONS_PER_RUN]


def delete_session(
    output_root: str | Path, *, run_id: str, session_id: str
) -> bool:
    """Delete one compatibility sidecar without touching capability outputs."""

    try:
        path = _session_path(output_root, run_id, session_id)
    except ValueError:
        return False
    with _LOCK:
        try:
            path.unlink()
        except FileNotFoundError:
            return False
    return True


def _load_session_record(output_root: str | Path, run_id: str, session_id: str) -> tuple[Path, dict[str, Any]]:
    path = _session_path(output_root, run_id, session_id)
    payload = _read_json(path, None)
    if not isinstance(payload, dict):
        raise FileNotFoundError(session_id)
    return path, payload


def append_message(
    output_root: str | Path,
    *,
    run_id: str,
    session_id: str,
    role: str,
    content: str,
    artifact_refs: Sequence[str] = (),
    version_refs: Sequence[str] = (),
    status: str = "completed",
    parent_message_id: str = "",
    branch_id: str = "main",
    turn_id: str = "",
    message_kind: str = "message",
) -> dict[str, Any]:
    """Append one visible message, enforcing session/turn bounds."""

    normalized_role = str(role or "user").strip().lower()
    if normalized_role not in {"user", "assistant", "system"}:
        normalized_role = "user"
    text = str(content or "").strip()
    if not text:
        raise ValueError("message content is required")
    if len(text) > MAX_MESSAGE_CHARS:
        raise ValueError(f"message exceeds {MAX_MESSAGE_CHARS} characters")
    with _LOCK:
        path, record = _load_session_record(output_root, run_id, session_id)
        messages = record.setdefault("messages", [])
        if not isinstance(messages, list):
            raise ValueError("message limit reached for this session")
        normalized_branch = _bounded_text(branch_id or "main", 128) or "main"
        normalized_turn = _bounded_text(turn_id, 128)
        normalized_kind = _bounded_text(message_kind or "message", 32) or "message"
        normalized_status = _bounded_text(status or "completed", 32)
        normalized_artifacts = [
            _bounded_text(ref, 180)
            for ref in list(artifact_refs)[:16]
            if _bounded_text(ref, 180)
        ]
        normalized_versions = [
            _bounded_text(ref, 180)
            for ref in list(version_refs)[:16]
            if _bounded_text(ref, 180)
        ]

        # A retry may replay the same assistant turn after the durable write
        # succeeded but a compatibility projection or memory checkpoint did
        # not.  Update that visible turn in place so the sidecar cannot show a
        # second assistant bubble.  Empty turn IDs intentionally retain the
        # historical append behavior.
        existing_index = None
        if normalized_role == "assistant" and normalized_turn:
            for index, existing in enumerate(messages):
                if not isinstance(existing, Mapping):
                    continue
                if (
                    str(existing.get("role", "")).strip().lower() == "assistant"
                    and _bounded_text(existing.get("turn_id", ""), 128)
                    == normalized_turn
                    and (_bounded_text(existing.get("branch_id") or "main", 128) or "main")
                    == normalized_branch
                    and (_bounded_text(existing.get("message_kind") or "message", 32) or "message")
                    == normalized_kind
                ):
                    existing_index = index
                    break
        if existing_index is not None:
            current = dict(messages[existing_index])
            merged_artifacts = list(current.get("artifact_refs", [])) if isinstance(current.get("artifact_refs", []), list) else []
            for value in normalized_artifacts:
                if value not in merged_artifacts:
                    merged_artifacts.append(value)
            merged_versions = list(current.get("version_refs", [])) if isinstance(current.get("version_refs", []), list) else []
            for value in normalized_versions:
                if value not in merged_versions:
                    merged_versions.append(value)
            current.update(
                {
                    "role": normalized_role,
                    "content": text,
                    "status": normalized_status,
                    "artifact_refs": merged_artifacts[:16],
                    "version_refs": merged_versions[:16],
                    "turn_id": normalized_turn,
                    "message_kind": normalized_kind,
                }
            )
            messages[existing_index] = current
            record["updated_at"] = now_iso()
            _atomic_write(path, record)
            return dict(current)
        if len(messages) >= MAX_MESSAGES_PER_SESSION:
            raise ValueError("message limit reached for this session")
        item = {
            "message_id": new_id("message"),
            "role": normalized_role,
            "content": text,
            "created_at": now_iso(),
            "status": normalized_status,
            "parent_message_id": _bounded_text(parent_message_id, 128),
            "branch_id": normalized_branch,
            "turn_id": normalized_turn,
            "message_kind": normalized_kind,
            "artifact_refs": normalized_artifacts,
            "version_refs": normalized_versions,
        }
        if not item["parent_message_id"]:
            item["parent_message_id"] = next(
                (
                    str(existing.get("message_id", ""))
                    for existing in reversed(messages)
                    if isinstance(existing, Mapping)
                    and str(existing.get("branch_id", "main") or "main")
                    == item["branch_id"]
                ),
                "",
            )
        messages.append(item)
        record["turn_count"] = int(record.get("turn_count", 0) or 0) + (1 if normalized_role == "user" else 0)
        record["updated_at"] = item["created_at"]
        _atomic_write(path, record)
        return dict(item)


def update_session(
    output_root: str | Path,
    *,
    run_id: str,
    session_id: str,
    status: str | None = None,
    artifacts: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    with _LOCK:
        path, record = _load_session_record(output_root, run_id, session_id)
        if status is not None:
            normalized = _bounded_text(status, 32).lower()
            if normalized not in {"active", "running", "completed", "failed", "cancelled", "partial", "blocked"}:
                raise ValueError("invalid session status")
            record["status"] = normalized
        if artifacts is not None:
            current = record.setdefault("artifacts", [])
            if not isinstance(current, list):
                current = []
            # A follow-up turn can refine the same candidate repeatedly.  Keep
            # one reviewable artifact per stable identity instead of growing a
            # duplicate list and presenting multiple identical merge buttons.
            normalized_items = [
                item
                for item in (_bounded_json(item, limit=12000) for item in artifacts)
                if isinstance(item, Mapping)
            ]
            for incoming in normalized_items:
                incoming_key = str(
                    incoming.get("artifact_id")
                    or incoming.get("capability_id")
                    or incoming.get("hypothesis_id")
                    or ""
                ).strip()
                existing_index = None
                if incoming_key:
                    for index, existing in enumerate(current):
                        if not isinstance(existing, Mapping):
                            continue
                        existing_key = str(
                            existing.get("artifact_id")
                            or existing.get("capability_id")
                            or existing.get("hypothesis_id")
                            or ""
                        ).strip()
                        if existing_key and existing_key == incoming_key:
                            existing_index = index
                            break
                if existing_index is None:
                    current.append(incoming)
                else:
                    current[existing_index] = {**dict(current[existing_index]), **dict(incoming)}
            record["artifacts"] = current[-MAX_ARTIFACTS_PER_SESSION:]
        record["updated_at"] = now_iso()
        _atomic_write(path, record)
        return _session_public(record)


def _first_text(mapping: Mapping[str, Any], keys: Sequence[str], fallback: str = "") -> str:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return _bounded_text(value, 900)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            values = [str(item).strip() for item in value if str(item).strip()]
            if values:
                return _bounded_text("；".join(values), 900)
    return fallback


def _context_sources(context: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return bounded, ordered projections of the visible result context.

    The browser sends the selected card under ``current_result_context`` and
    the API stores it below ``client_context``.  Earlier versions of the
    offline synthesizer only inspected the top-level mapping, so every
    follow-up sounded generic even when a specific capability or reference
    weapon was selected.  This helper deliberately walks only visible,
    structured mappings (never provider traces) and caps list expansion.
    More specific selections precede the run-level summary so they win when a
    field such as ``name`` appears in more than one place.
    """

    sources: list[Mapping[str, Any]] = []
    seen: set[int] = set()

    def add(value: Any, depth: int = 0) -> None:
        if depth > 2 or not isinstance(value, Mapping):
            return
        marker = id(value)
        if marker in seen:
            return
        seen.add(marker)
        sources.append(value)

    def add_container(value: Any, depth: int = 0) -> None:
        if not isinstance(value, Mapping) or depth > 2:
            return
        # A selected card/candidate is more specific than aggregate lists.
        for key in ("candidate", "reference_weapon", "selected", "focus", "current_result_context"):
            nested = value.get(key)
            if isinstance(nested, Mapping):
                add(nested, depth)
                add_container(nested, depth + 1)
        for key in ("capability_cards", "reference_weapons", "cards", "items"):
            nested = value.get(key)
            if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes)):
                for item in list(nested)[:8]:
                    if isinstance(item, Mapping):
                        add(item, depth)
                        add_container(item, depth + 1)

    # Specific objects supplied by the session are intentionally first.
    for key in ("candidate", "reference_weapon", "selected"):
        value = context.get(key)
        if isinstance(value, Mapping):
            add(value)
            add_container(value, 1)
    for container_key in ("current_result_context", "client_context"):
        container = context.get(container_key)
        if isinstance(container, Mapping):
            add_container(container, 0)
            add(container)
    add(context)
    return sources


def _first_context_text(
    sources: Sequence[Mapping[str, Any]],
    keys: Sequence[str],
    fallback: str = "",
) -> str:
    for source in sources:
        value = _first_text(source, keys, "")
        if value:
            return _bounded_text(value, 900)
    return fallback


def _context_name_list(
    context: Mapping[str, Any],
    key: str,
    fields: Sequence[str],
    *,
    limit: int = 5,
) -> list[str]:
    """Extract short display names from an aggregate visible context list."""

    values: list[str] = []
    containers: list[Any] = [context]
    client = context.get("client_context")
    if isinstance(client, Mapping):
        containers.extend((client, client.get("current_result_context")))
    current = context.get("current_result_context")
    if isinstance(current, Mapping):
        containers.append(current)
    for container in containers:
        if not isinstance(container, Mapping):
            continue
        items = container.get(key)
        if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
            continue
        for item in list(items)[:limit * 2]:
            if not isinstance(item, Mapping):
                continue
            value = _first_text(item, fields, "")
            if value and value not in values:
                values.append(_bounded_text(value, 180))
            if len(values) >= limit:
                return values
    return values


def synthesize_reply(
    *,
    query: str,
    question: str,
    context_refs: Mapping[str, Any] | None = None,
    capability_name: str = "",
    mode: str = "offline-bounded",
) -> dict[str, Any]:
    """Produce a transparent, bounded answer for the local/fake runtime.

    The shape is deliberately provider-neutral.  A production provider can
    replace the prose while preserving ``sections`` and ``next_questions``.
    """

    context = context_refs if isinstance(context_refs, Mapping) else {}
    sources = _context_sources(context)
    source_equipment = context.get("source_equipment") if isinstance(context.get("source_equipment"), Mapping) else None
    equipment_sources = [source_equipment] if source_equipment is not None else sources
    candidate = _first_context_text(
        equipment_sources,
        ("title", "name", "equipment_form", "primary_equipment_identity", "capability_name"),
        capability_name or "当前能力方向",
    )
    mechanism = _first_context_text(
        equipment_sources,
        ("mechanism_chain", "winning_mechanism", "core_disruptive_difference", "reference_overview", "concise_winning_summary"),
        "需进一步确认该方向如何改变现有任务链和对手反应节奏",
    )
    equipment_form = _first_context_text(
        equipment_sources,
        ("equipment_form", "equipment_forms", "primary_equipment_identity"),
        candidate,
    )
    direct_effect = _first_context_text(
        equipment_sources,
        ("direct_military_effects", "military_value", "mission_effect", "function"),
        "在当前任务节点形成不同于原装备的直接军事效果",
    )
    question = _bounded_text(question, MAX_MESSAGE_CHARS)
    query = _bounded_text(query, 1800)
    query_weapon_names = [
        str(item.get("name") or item.get("title") or "").strip()
        for item in (
            context.get("query_weapons", [])
            if isinstance(context.get("query_weapons"), list)
            else []
        )
        if isinstance(item, Mapping) and str(item.get("name") or item.get("title") or "").strip()
    ][:4]
    catalog_clause = (
        f"当前 Query 下已有武器基线包括：{'、'.join(query_weapon_names)}。"
        if query_weapon_names
        else ""
    )
    context_sentence = (
        "本轮以当前 Query 下已有武器装备为种子展开深度发散，推理新质颠覆构型。"
        if query_weapon_names
        else "本轮只基于当前 Query、目标装备和专家问题展开。"
    )
    answer = {
        "mode": mode,
        "sections": [
            {
                "title": "创新起点",
                "text": f"围绕“{candidate}”继续追问“{question}”，当前 Query（{query}）下可先重写其默认作用方式：{mechanism}。",
            },
            {
                "title": "关键假设改写",
                "text": (
                    f"{context_sentence}{catalog_clause} "
                    "优先探索任务角色、作用机理、构型和运用方式的改写，形成性能跃迁之外的新质装备方向。"
                ).strip(),
            },
            {
                "title": "新质装备方向",
                "text": f"可以把“{candidate}”推进为具备新构型与新作战角色的变体，并围绕直接军事效果说明其作用机理。",
            },
        ],
        "next_questions": [
            f"{candidate}在哪个具体作战节点形成不可替代的直接效果？",
            "哪个既有任务假设最值得彻底改写，才能形成新的装备角色？",
            "如何把该装备从性能改良推进到作用机理跃迁？",
            "怎样设计新的构型与运用方式，产生不同于现有装备的直接军事效果？",
        ],
        "concept_directions": [
            {
                "name": f"{candidate}创新变体",
                "innovation_variant_name": f"{candidate}创新变体",
                "innovation_thesis": f"以“{candidate}”为种子，改写其任务角色与作用方式",
                "winning_angle": "任务链重构",
                "changed_assumption": "既有装备必须沿用原有构型和任务角色",
                "equipment_form": equipment_form,
                "innovation_equipment_form": equipment_form,
                "operational_mechanism": mechanism,
                "military_value": direct_effect,
                "direct_military_effects": direct_effect,
                "novelty": "由单项性能改良转向装备角色与作用链重构",
                "disruptive_difference": "改变装备在任务链中的作用节点与协同关系",
                "implementation_concept": "围绕新任务角色重组感知、决策、载荷和协同接口",
                "stable": True,
            }
        ],
        "capability_card_draft": {},
    }
    return answer


def _pretty_section_body(text: str) -> str:
    """Normalize jammed Chinese summaries into readable markdown paragraphs."""

    body = str(text or "").strip()
    if not body:
        return ""
    # Prefer existing paragraph breaks; otherwise split dense「；」chains that
    # were historically used as pseudo-bullets in the complete-result block.
    if "\n" in body:
        return body
    parts = [part.strip(" ；;·") for part in body.split("；") if part.strip(" ；;·")]
    if len(parts) >= 3 and sum(1 for part in parts if len(part) >= 12) >= 2:
        return "\n\n".join(parts)
    return body


def format_deep_complete_answer(answer: Mapping[str, Any] | None) -> str:
    """Build the durable assistant transcript for one finished deep turn.

    Mid-flight SSE deltas remain incremental.  The final assistant message must
    still present a single, self-contained summary the expert can read after
    the process thread settles.
    """

    payload = answer if isinstance(answer, Mapping) else {}
    sections = payload.get("sections", [])
    sections = sections if isinstance(sections, list) else []
    blocks: list[str] = []
    for item in sections:
        if not isinstance(item, Mapping):
            continue
        title = str(item.get("title", "") or "").strip()
        text = _pretty_section_body(str(item.get("text", "") or ""))
        if not title or not text:
            continue
        # Avoid ``### Title`` + body that itself starts with the same heading.
        heading_prefix = re.compile(rf"^#{{1,6}}\s*{re.escape(title)}\s*", re.MULTILINE)
        text = heading_prefix.sub("", text).strip()
        blocks.append(f"### {title}\n\n{text}")
    if blocks:
        return "\n\n".join(blocks)

    # Fallback for older/offline payloads that only carry next_questions.
    questions = payload.get("next_questions", [])
    questions = questions if isinstance(questions, list) else []
    question_bits = [str(item).strip() for item in questions[:4] if str(item).strip()]
    if question_bits:
        return "### 下一轮创新问题\n\n" + "\n".join(f"- {item}" for item in question_bits)
    return "本轮深度发散已结束。"


def build_deep_complete_sections(
    *,
    visible_summary: Sequence[str] | None = None,
    agent_dialogue: Sequence[Mapping[str, Any]] | None = None,
    dialogue_steps: Sequence[Mapping[str, Any]] | None = None,
    directions: Sequence[Mapping[str, Any]] | None = None,
    capability_card_draft: Mapping[str, Any] | None = None,
    adjudication: Mapping[str, Any] | None = None,
    open_questions: Sequence[str] | None = None,
    block_reasons: Sequence[str] | None = None,
    provider_finalization_status: str = "",
    selection_rationale: str = "",
    source_equipment_label: str = "",
    query_weapon_names: Sequence[str] | None = None,
) -> list[dict[str, str]]:
    """Assemble the complete end-of-turn summary sections for deep dialogue."""

    summaries = [str(item).strip() for item in (visible_summary or []) if str(item).strip()]
    dialogue = [item for item in (agent_dialogue or []) if isinstance(item, Mapping)]
    steps = [item for item in (dialogue_steps or []) if isinstance(item, Mapping)]
    direction_rows = [item for item in (directions or []) if isinstance(item, Mapping)]
    draft = capability_card_draft if isinstance(capability_card_draft, Mapping) else {}
    adjudication_row = adjudication if isinstance(adjudication, Mapping) else {}
    questions = [str(item).strip() for item in (open_questions or []) if str(item).strip()]
    reasons = [str(item).strip() for item in (block_reasons or []) if str(item).strip()]
    rationale = str(selection_rationale or "").strip()
    mission = str(adjudication_row.get("mission_focus", "") or "").strip()
    review = str(adjudication_row.get("review_summary", "") or "").strip()
    seed_label = str(source_equipment_label or "").strip()
    catalog_names = [
        str(item).strip()
        for item in (query_weapon_names or [])
        if str(item).strip()
    ][:6]
    new_names = [
        str(item.get("name") or item.get("innovation_variant_name") or "").strip()
        for item in direction_rows
        if str(item.get("name") or item.get("innovation_variant_name") or "").strip()
    ][:3]
    leap_line = ""
    if seed_label or catalog_names:
        baseline = "、".join(catalog_names[:4]) or seed_label
        arrived = "、".join(new_names) if new_names else "新质颠覆候选"
        leap_line = (
            f"以当前 Query 已有装备「{baseline}」为基线，本轮已推理出与其相关但构型/机理跃迁的方向：{arrived}。"
        )

    complete_bits = [
        part
        for part in (
            leap_line,
            rationale,
            *summaries[:4],
            mission,
            review,
        )
        if part
    ]
    # Deduplicate near-identical summary sentences that often repeat across
    # rationale / visible_summary / adjudication review fields.
    deduped_complete: list[str] = []
    seen_complete: set[str] = set()
    for part in complete_bits:
        key = re.sub(r"\s+", "", part)
        if key in seen_complete:
            continue
        seen_complete.add(key)
        deduped_complete.append(part)
    sections: list[dict[str, str]] = [
        {
            "title": "本轮完整结果",
            "text": (
                "\n\n".join(deduped_complete)[:3200]
                or "已完成本轮内部多维发散、对抗裁决与综合收敛。"
            ),
        },
        {
            "title": "多 Agent 交叉审议 · 深度发散过程",
            "text": "\n\n".join(
                (
                    f"**{item.get('axis') or item.get('role') or '发散'}**\n"
                    f"{str(item.get('summary', '') or '').strip()}"
                    + (
                        f"\n- 候选：{'、'.join(str(name) for name in item.get('proposal_names', [])[:3] if str(name).strip())}"
                        if isinstance(item.get("proposal_names"), list)
                        and any(str(name).strip() for name in item.get("proposal_names", [])[:3])
                        else ""
                    )
                )
                for item in dialogue
                if str(item.get("round", "")).strip().lower() == "divergence"
                and str(item.get("summary", "") or "").strip()
            )[:5200]
            or "\n\n".join(
                f"**{item.get('title') or '步骤'}**\n{item.get('text') or ''}".strip()
                for item in steps
                if str(item.get("text", "") or "").strip()
            )[:4200]
            or "本轮围绕单个装备完成了内部多维可见发散。",
        },
        {
            "title": "对抗裁决与综合",
            "text": "\n\n".join(
                (
                    f"**{item.get('role') or '议事 Agent'}**\n"
                    f"{str(item.get('summary', '') or '').strip()}"
                    + (
                        f"\n- {'、'.join(str(name) for name in (item.get('verdicts') or item.get('proposal_names') or [])[:6] if str(name).strip())}"
                        if (item.get("verdicts") or item.get("proposal_names"))
                        else ""
                    )
                )
                for item in dialogue
                if str(item.get("round", "")).strip().lower() in {"critique", "synthesis"}
                and str(item.get("summary", "") or "").strip()
            )[:5200]
            or "本轮由内部多维发散、对抗裁决并综合收敛。",
        },
        {
            "title": "候选方向",
            "text": "\n\n".join(
                "\n".join(
                    part
                    for part in (
                        f"**{str(item.get('name', '') or item.get('innovation_variant_name', '') or '').strip()}**",
                        f"- 制胜角度：{item['winning_angle']}" if item.get("winning_angle") else "",
                        f"- 改写假设：{item['changed_assumption']}" if item.get("changed_assumption") else "",
                        (
                            f"- 构型：{item.get('innovation_equipment_form') or item.get('equipment_form')}"
                            if (item.get("innovation_equipment_form") or item.get("equipment_form"))
                            else ""
                        ),
                        f"- 机理：{item['operational_mechanism']}" if item.get("operational_mechanism") else "",
                        (
                            f"- 效果：{item.get('direct_military_effects') or item.get('military_value') or item.get('function')}"
                            if (item.get("direct_military_effects") or item.get("military_value") or item.get("function"))
                            else ""
                        ),
                        (
                            f"- 打击对象：{item.get('decisive_target')}"
                            if item.get("decisive_target")
                            else ""
                        ),
                        (
                            f"- 直接毁伤：{item.get('direct_damage_mechanism')}"
                            if item.get("direct_damage_mechanism")
                            else ""
                        ),
                        (
                            f"- 失能判据：{item.get('mission_kill_criterion')}"
                            if item.get("mission_kill_criterion")
                            else ""
                        ),
                        (
                            f"- 颠覆差异：{item.get('disruptive_difference') or item.get('novelty')}"
                            if (item.get("disruptive_difference") or item.get("novelty"))
                            else ""
                        ),
                    )
                    if str(part or "").strip()
                )
                for item in direction_rows
            )[:5200]
            or "本轮未形成稳定候选能力卡。",
        },
    ]
    draft_text = "\n\n".join(
        f"#### {label}\n{str(draft.get(key, '') or '').strip()}"
        for key, label in (
            ("overview", "概述"),
            ("technology_implementation", "装备与技术实现"),
            ("operational_process", "关键作战流程"),
            ("capability_effects", "能力与作战效果"),
            ("winning_logic", "制胜逻辑机理"),
        )
        if str(draft.get(key, "") or "").strip()
    )[:9000]
    if draft_text:
        sections.append({"title": "五栏能力画像", "text": draft_text})
    if provider_finalization_status == "analysis_only" or reasons:
        reason_text = "\n".join(f"- {item}" for item in reasons[:6]) if reasons else ""
        sections.append(
            {
                "title": "发布质量门",
                "text": (
                    "本轮讨论可见，但未写入正式能力画像版本。"
                    + (f"\n\n原因：\n{reason_text}" if reason_text else "")
                )[:2200],
            }
        )
    if provider_finalization_status == "awaiting_user_confirmation":
        sections.append(
            {
                "title": "是否形成能力卡",
                "text": (
                    "这个方向已经形成了可辨识的装备构型、作用机理和直接军事价值。"
                    "你可以继续追问，把关键边界再挖深；如果认可当前方向，再确认形成五栏能力卡。"
                ),
            }
        )
    question_text = "\n".join(f"- {item}" for item in questions[:6]) if questions else ""
    sections.append(
        {
            "title": "下一轮创新问题",
            "text": question_text[:2200]
            or "继续追问装备构型、作用机理和作战角色的跃迁。",
        }
    )
    return sections


def _default_module_texts(candidate: Mapping[str, Any], *, query: str, focus: str) -> dict[str, str]:
    # A reference artifact may be created before the model has authored the
    # five S6 columns.  Do not synthesize generic prose here: an empty/partial
    # module map makes the pending authoring state explicit and prevents a
    # template paragraph from being mistaken for a reviewed capability card.
    module_keys = (
        "overview",
        "technology_implementation",
        "operational_process",
        "capability_effects",
        "winning_logic",
    )
    draft = candidate.get("capability_card_draft")
    if isinstance(draft, Mapping):
        drafted_modules = {
            key: _bounded_text(draft.get(key, ""), 6000)
            for key in module_keys
            if _bounded_text(draft.get(key, ""), 6000)
        }
    else:
        drafted_modules = {}
    # Preserve explicitly authored module fields supplied by an upstream
    # adapter, but never derive prose from generic equipment metadata.
    for key in module_keys:
        if key not in drafted_modules:
            direct = _bounded_text(candidate.get(key, ""), 6000)
            if direct:
                drafted_modules[key] = direct
    if drafted_modules:
        return {key: drafted_modules.get(key, "") for key in module_keys}

    # Keep the stable five-key shape for compatibility, while leaving missing
    # prose empty so callers can show an explicit pending-authoring state.
    return {key: "" for key in module_keys}


def build_reference_capability(
    *,
    run_id: str,
    query: str,
    candidate: Mapping[str, Any],
    focus: str = "",
    source_session_id: str = "",
) -> dict[str, Any]:
    """Build a versioned capability-card artifact from a reference candidate."""

    hypothesis_id = _first_text(candidate, ("hypothesis_id", "candidate_id", "id"), new_id("hypothesis"))
    source_equipment_identity = _first_text(candidate, ("source_equipment_identity", "title", "name", "primary_equipment_identity", "equipment_form"), "参考装备方向")
    name = _first_text(candidate, ("innovation_variant_name", "title", "name", "primary_equipment_identity", "equipment_form"), "参考装备方向")
    capability_id = f"deep-{safe_segment(hypothesis_id, limit=100) or uuid4().hex}"
    # Card identity is stable across retries and conversation turns.  Version
    # numbers, rather than random card ids, represent subsequent deep-research
    # findings for the same hypothesis.
    supplied_binding = _first_text(candidate, ("card_binding_id", "capability_binding_id"), "")
    card_binding_id = supplied_binding or f"deep-card-{hashlib.sha256(hypothesis_id.encode('utf-8')).hexdigest()[:24]}"
    modules = _default_module_texts(candidate, query=query, focus=focus)
    modules_complete = all(
        _bounded_text(modules.get(key, ""), 8)
        for key in (
            "overview",
            "technology_implementation",
            "operational_process",
            "capability_effects",
            "winning_logic",
        )
    )
    equipment_form = _first_text(
        candidate,
        ("innovation_equipment_form", "new_equipment_form", "equipment_form", "primary_equipment_identity", "equipment_forms"),
        name,
    )
    raw_forms = candidate.get("equipment_forms", candidate.get("equipment_form", []))
    if isinstance(raw_forms, (list, tuple, set, frozenset)):
        equipment_forms = [
            _bounded_text(item, 320)
            for item in list(raw_forms)[:8]
            if _bounded_text(item, 320)
        ]
    elif raw_forms:
        equipment_forms = [_bounded_text(raw_forms, 320)]
    else:
        equipment_forms = [equipment_form] if equipment_form else []
    operational_mechanism = _first_text(
        candidate,
        ("operational_mechanism", "mechanism_chain", "winning_mechanism", "core_disruptive_difference"),
        modules["technology_implementation"],
    )
    direct_military_effects = _first_text(
        candidate,
        ("direct_military_effects", "military_value", "mission_effect", "function"),
        modules["capability_effects"],
    )
    failure_boundary = _first_text(
        candidate,
        ("failure_boundary", "failure_boundaries", "risk_boundaries", "operational_constraints"),
        "强干扰、目标特征不足、授权约束或关键链路中断时，能力可能退化为普通装备效果。",
    )
    validation_plan = _first_text(
        candidate,
        ("validation_plan", "verification_plan", "validation"),
        "补充可定位来源，并以任务前后对照、对手适应和失效边界验证该假设。",
    )
    related_scenario = _first_text(candidate, ("related_scenario", "scenario", "mission_node"), "当前 Query 关联场景")
    capability_gap = _first_text(candidate, ("capability_gap", "failure_boundary", "failure_boundaries"), "参考方向对应的能力缺口待验证")
    evidence_ids = candidate.get("evidence_ids", [])
    if not isinstance(evidence_ids, list):
        evidence_ids = [str(evidence_ids)] if evidence_ids else []
    return {
        "capability_id": capability_id,
        "card_binding_id": card_binding_id,
        "hypothesis_id": hypothesis_id,
        "name": name,
        "title": name,
        "primary_equipment_identity": name,
        "source_equipment_identity": source_equipment_identity,
        "innovation_variant_name": _first_text(candidate, ("innovation_variant_name",), ""),
        "innovation_thesis": _first_text(candidate, ("innovation_thesis",), ""),
        "winning_angle": _first_text(candidate, ("winning_angle",), ""),
        "changed_assumption": _first_text(candidate, ("changed_assumption",), ""),
        "novelty": _first_text(candidate, ("novelty",), ""),
        "disruptive_difference": _first_text(candidate, ("disruptive_difference",), ""),
        "implementation_concept": _first_text(candidate, ("implementation_concept",), ""),
        "equipment_category": _first_text(candidate, ("equipment_category", "category"), equipment_form or "参考装备能力方向"),
        "equipment_form": equipment_form,
        "equipment_forms": equipment_forms,
        "capability_type": "new_capability",
        "source_winning_logic": operational_mechanism or "待核验的制胜机理假设",
        "mechanism_chain": operational_mechanism,
        "operational_mechanism": operational_mechanism,
        "military_value": direct_military_effects,
        "direct_military_effects": direct_military_effects,
        "mission_effect": direct_military_effects,
        "project_function": _first_text(candidate, ("project_function", "function"), direct_military_effects),
        "related_scenario": related_scenario,
        "priority": "exploratory",
        "capability_gap": capability_gap,
        "failure_boundary": failure_boundary,
        "failure_boundaries": [failure_boundary] if failure_boundary else [],
        "validation_plan": validation_plan,
        "verification_plan": validation_plan,
        "capability_portrait_modules": modules,
        "deep_capability_portrait": "",
        "capability_image": "",
        "evidence_ids": [str(item)[:180] for item in evidence_ids[:16]],
        "confidence": 0.35,
        "confidence_limited": True,
        "verification_status": "pending",
        "portrait_authoring_status": (
            "deep_research_authored"
            if modules_complete
            else "pending_s6_authoring"
        ),
        "analysis_provenance_status": (
            "deep_research_reference"
            if modules_complete
            else "pending_authoring"
        ),
        "capability_card_status": (
            "authored"
            if modules_complete
            else "analysis_only_pending_authoring"
        ),
        "source": "reference_weapon_deep_research",
        "source_run_id": run_id,
        "source_session_id": source_session_id,
        "research_query": _bounded_text(query, 4000),
        "research_focus": _bounded_text(focus, 1600),
        "research_version": 1,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }


def save_reference_research(
    output_root: str | Path,
    *,
    run_id: str,
    capability: Mapping[str, Any],
    status: str = "completed",
) -> dict[str, Any]:
    """Upsert one reference-research result by hypothesis id."""

    with _LOCK:
        # Keep the exact record written to disk as the return value.  Deep
        # research versions are assigned below; returning the caller's
        # pre-assignment mapping made HTTP responses disagree with the
        # durable sidecar and caused follow-up merges to target stale v1
        # metadata after a retry.
        persisted: dict[str, Any] = dict(capability)
        path = _research_path(output_root, run_id)
        payload = _read_json(path, None)
        if not isinstance(payload, dict):
            payload = {
                "schema_version": SCHEMA_VERSION,
                "run_id": safe_segment(run_id),
                "items": [],
                "updated_at": now_iso(),
            }
        items = payload.setdefault("items", [])
        if not isinstance(items, list):
            items = []
        key = str(capability.get("hypothesis_id") or capability.get("capability_id") or "").strip()
        replaced = False
        is_deep = bool(capability.get("is_deep_research") or capability.get("source") in {"reference_weapon_deep_research", "deep-thinking"})
        for index, item in enumerate(items):
            if isinstance(item, Mapping) and key and str(item.get("hypothesis_id") or item.get("capability_id") or "").strip() == key and not is_deep:
                items[index] = dict(capability)
                replaced = True
                break
        if not replaced:
            if is_deep:
                prior = [int(item.get("research_version", 1) or 1) for item in items if isinstance(item, Mapping) and str(item.get("hypothesis_id") or "").strip() == key]
                persisted = {**persisted, "research_version": max(prior or [0]) + 1, "version_status": capability.get("version_status", "pending_verification")}
            items.append(dict(persisted))
        payload["items"] = items[-MAX_ARTIFACTS_PER_SESSION:]
        payload["status"] = _bounded_text(status, 32)
        payload["updated_at"] = now_iso()
        _atomic_write(path, payload)
        return dict(persisted)


def merge_capability_into_snapshot(
    capability_path: str | Path,
    capability: Mapping[str, Any],
    *,
    mode: str = "append",
) -> dict[str, Any]:
    """Atomically append/replace a deep-research card in capability_images.

    A timestamped ``.pre-deep-thinking`` backup is kept beside the source
    artifact.  The returned metadata is suitable for an audit event.
    """

    path = Path(capability_path).expanduser().resolve()
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(str(path))
    payload = _read_json(path, None)
    if isinstance(payload, list):
        rows = list(payload)
        wrapper = False
    elif isinstance(payload, Mapping):
        raw_rows = payload.get("capability_images", [])
        rows = list(raw_rows) if isinstance(raw_rows, list) else []
        wrapper = True
    else:
        raise ValueError("capability_images artifact is not a JSON list/object")
    candidate = dict(capability)
    key = str(candidate.get("hypothesis_id") or candidate.get("capability_id") or "").strip()
    if not key:
        raise ValueError("capability card has no stable identity")
    existing_index = next(
        (
            index for index, row in enumerate(rows)
            if isinstance(row, Mapping)
            and key
            and str(row.get("hypothesis_id") or row.get("capability_id") or "").strip() == key
        ),
        None,
    )
    normalized_mode = str(mode or "append").strip().lower()
    # Formal S6 cards are immutable.  Deep-research always appends a versioned
    # projection, even when the hypothesis/card binding already exists.  The
    # legacy ``replace`` mode is retained only for non-deep callers; deep
    # artifacts are identified by source/provenance and never overwrite v1.
    is_deep = bool(candidate.get("is_deep_research") or candidate.get("source") in {"reference_weapon_deep_research", "deep-thinking"})
    if existing_index is not None and normalized_mode in {"replace", "upsert"} and not is_deep:
        rows[existing_index] = {**dict(rows[existing_index]), **candidate}
        action = "replaced"
    else:
        existing_versions = [
            int(row.get("research_version", 1) or 1)
            for row in rows
            if isinstance(row, Mapping)
            and str(row.get("card_binding_id", "")) == str(candidate.get("card_binding_id", ""))
        ]
        candidate.setdefault("research_version", max(existing_versions or [0]) + 1 if is_deep else 1)
        candidate.setdefault("version_status", candidate.get("verification_status", "pending_verification") if is_deep else "formal")
        # Deep merges are retried after a successful SQLite version write
        # (for example when the filesystem projection was temporarily
        # unavailable).  Make the compatibility projection idempotent by
        # recognizing the durable version id/lineage before appending another
        # visually identical card.  Formal cards retain the historical
        # append/replace semantics above.
        if is_deep:
            version_id = str(candidate.get("version_id", "") or "").strip()
            version_no = str(candidate.get("version_no", candidate.get("research_version", "")) or "").strip()
            duplicate_index = next(
                (
                    index
                    for index, row in enumerate(rows)
                    if isinstance(row, Mapping)
                    and (
                        (version_id and str(row.get("version_id", "") or "").strip() == version_id)
                        or (
                            version_no
                            and str(row.get("card_binding_id", "") or "")
                            == str(candidate.get("card_binding_id", "") or "")
                            and str(row.get("hypothesis_id", "") or "")
                            == str(candidate.get("hypothesis_id", "") or "")
                            and str(row.get("version_no", row.get("research_version", "")) or "").strip()
                            == version_no
                        )
                    )
                ),
                None,
            )
            if duplicate_index is not None:
                rows[duplicate_index] = {**dict(rows[duplicate_index]), **candidate}
                action = "already_present"
            else:
                rows.append(candidate)
                action = "appended"
        else:
            rows.append(candidate)
            action = "appended"
    backup = path.with_name(f"{path.name}.pre-deep-thinking")
    backup_available = False
    try:
        # Preserve the original artifact exactly once for audit/recovery.
        if backup.is_symlink():
            # Never follow a pre-existing symlink while writing an audit
            # backup.  The merge itself can still proceed, but the caller gets
            # an explicit false availability flag.
            backup_available = False
        elif not backup.exists():
            backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            backup_available = True
        else:
            backup_available = backup.is_file()
    except OSError:
        # The merge itself remains valid when a read-only volume disallows a
        # backup; callers still receive an explicit ``backup_available`` flag.
        backup_available = False
    output = {"capability_images": rows} if wrapper else rows
    _atomic_write(path, output)
    return {
        "action": action,
        "capability_id": str(candidate.get("capability_id", "")),
        "hypothesis_id": str(candidate.get("hypothesis_id", "")),
        "count": len(rows),
        "backup_available": backup_available,
    }


def list_reference_research(output_root: str | Path, *, run_id: str) -> list[dict[str, Any]]:
    with _LOCK:
        payload = _read_json(_research_path(output_root, run_id), None)
    items = payload.get("items", []) if isinstance(payload, Mapping) else []
    return [dict(item) for item in items if isinstance(item, Mapping)]


def _links_path(output_root: str | Path) -> Path:
    return _json_root(output_root) / "research-links.json"


def list_research_links(output_root: str | Path, *, parent_run_id: str = "") -> list[dict[str, Any]]:
    with _LOCK:
        payload = _read_json(_links_path(output_root), None)
    items = payload.get("items", []) if isinstance(payload, Mapping) else []
    rows = [dict(item) for item in items if isinstance(item, Mapping)]
    if parent_run_id:
        rows = [
            item for item in rows
            if str(item.get("parent_run_id", "")).strip() == str(parent_run_id).strip()
        ]
    rows.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
    return rows


def save_research_link(output_root: str | Path, link: Mapping[str, Any]) -> dict[str, Any]:
    """Upsert a parent/child reference-research link."""

    normalized = _bounded_json(dict(link), limit=12000)
    if not isinstance(normalized, dict):
        raise ValueError("research link must be an object")
    key = str(normalized.get("job_id") or normalized.get("child_run_id") or "").strip()
    if not key:
        raise ValueError("research link requires job_id or child_run_id")
    with _LOCK:
        path = _links_path(output_root)
        payload = _read_json(path, None)
        if not isinstance(payload, dict):
            payload = {"schema_version": SCHEMA_VERSION, "items": []}
        items = payload.setdefault("items", [])
        if not isinstance(items, list):
            items = []
        replaced = False
        for index, item in enumerate(items):
            if isinstance(item, Mapping) and str(item.get("job_id") or item.get("child_run_id") or "").strip() == key:
                items[index] = normalized
                replaced = True
                break
        if not replaced:
            items.append(normalized)
        payload["items"] = items[-500:]
        payload["updated_at"] = now_iso()
        _atomic_write(path, payload)
    return dict(normalized)


def delete_run_sidecars(output_root: str | Path, run_id: str) -> None:
    """Remove compatibility sidecars for a permanently deleted parent run.

    SQLite is authoritative, but older deployments may still have JSON
    session/research files.  Cleanup is scoped to the validated run directory
    and removes only links whose parent/child belongs to that run.
    """
    run_segment = safe_segment(run_id)
    if not run_segment:
        return
    with _LOCK:
        root = _json_root(output_root)
        run_dir = root / run_segment
        if run_dir.exists() and not run_dir.is_symlink() and run_dir.parent == root:
            shutil.rmtree(run_dir)
        links_path = _links_path(output_root)
        payload = _read_json(links_path, None)
        if not isinstance(payload, Mapping):
            return
        items = payload.get("items", [])
        if not isinstance(items, list):
            return
        kept = [
            item for item in items
            if not isinstance(item, Mapping)
            or (str(item.get("parent_run_id", "")) != str(run_id)
                and str(item.get("child_run_id", "")) != str(run_id))
        ]
        if len(kept) != len(items):
            _atomic_write(links_path, {**dict(payload), "items": kept, "updated_at": now_iso()})


__all__ = [
    "SCHEMA_VERSION",
    "MAX_MESSAGE_CHARS",
    "SINGLE_EQUIPMENT_INNOVATION_MODE",
    "append_message",
    "build_reference_capability",
    "create_session",
    "delete_run_sidecars",
    "get_session",
    "list_reference_research",
    "list_research_links",
    "list_sessions",
    "merge_capability_into_snapshot",
    "save_research_link",
    "save_reference_research",
    "single_equipment_innovation_context",
    "project_query_weapons",
    "synthesize_reply",
    "build_deep_complete_sections",
    "format_deep_complete_answer",
    "update_session",
]
