"""Auditable attribution helpers for prompt/memory self-evolution.

The winning workflow intentionally keeps model calls small and provider
agnostic.  This module provides the missing *observation* boundary: every
S1--S6 call can emit a bounded lifecycle record without persisting the raw
prompt, reviewer note, or model answer.  The record is safe to append to the
normal :class:`TraceStore` and is also useful to offline replay/evaluation.

The helper is deliberately dependency free.  Hosts may install a callback via
``set_evolution_trace_sink``; when no callback is installed records remain in a
run-local list and can be retrieved with ``evolution_trace_events``.  Emission
is best-effort and must never turn a successful model call into a failed run.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
import json
import re
from threading import RLock
from time import monotonic
from typing import Any
from uuid import uuid4

from equipment_deep_research.domain.models import now_iso


_STAGES = frozenset({"S1", "S2", "S3", "S4", "S5", "S6"})
_STAGE_RE = re.compile(r"(?:^|[_:/ -])s([1-6])(?:$|[_:/ -])", re.IGNORECASE)
_ID_RE = re.compile(
    r"^(?:feedback|lesson|memory|evidence|packet|ev|source)[-_][A-Za-z0-9][A-Za-z0-9_.:-]{0,180}$",
    re.IGNORECASE,
)
_MAX_IDS = 64
_MAX_ROWS = 48
_MAX_TEXT = 1800


def _bounded_text(value: Any, *, limit: int = 256) -> str:
    """Return a small, deterministic string for trace identity fields."""

    return str(value or "").strip()[:limit]


def _json_safe(value: Any, *, depth: int = 0) -> Any:
    """Return a bounded JSON-compatible projection for hashing.

    Hash inputs must be deterministic but cannot allow an accidentally passed
    provider object or an unbounded transcript to grow a trace event.  Values
    deeper than six levels are represented by a stable string representation.
    """

    if depth > 6:
        return str(value)[:256]
    if value is None or isinstance(value, (bool, int, float, str)):
        if isinstance(value, float) and value != value:
            return None
        return value
    if isinstance(value, Mapping):
        rows = sorted(value.items(), key=lambda item: str(item[0]))
        return {
            str(key): _json_safe(item, depth=depth + 1)
            for key, item in rows[:_MAX_ROWS]
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        rows = list(value)
        if isinstance(value, (set, frozenset)):
            rows.sort(key=lambda item: str(item))
        return [_json_safe(item, depth=depth + 1) for item in rows[:_MAX_ROWS]]
    # Dataclasses and provider metadata occasionally reach this boundary.  Do
    # not import/asdict them (some provider containers are not deepcopyable).
    if hasattr(value, "__dict__"):
        return _json_safe(vars(value), depth=depth + 1)
    return str(value)[:_MAX_TEXT]


def stable_hash(value: Any) -> str:
    """Hash a canonical JSON projection using the project-wide ``sha256:`` form."""

    encoded = json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


def _clean_ids(values: Sequence[Any]) -> list[str]:
    result: list[str] = []
    for raw in values:
        token = str(raw or "").strip()
        if not token or len(token) > 192:
            continue
        if token not in result:
            result.append(token)
        if len(result) >= _MAX_IDS:
            break
    return result


def _walk(value: Any, *, depth: int = 0) -> list[tuple[str, Any]]:
    if depth > 5:
        return []
    rows: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key).lower()
            rows.append((key_text, item))
            rows.extend(_walk(item, depth=depth + 1))
    elif isinstance(value, (list, tuple)):
        for item in value[:_MAX_ROWS]:
            rows.extend(_walk(item, depth=depth + 1))
    return rows


def _ids_from_value(value: Any, *, allow_regex: bool = False) -> list[str]:
    values: list[str] = []
    if isinstance(value, Mapping):
        for key in (
            "id",
            "feedback_id",
            "memory_id",
            "lesson_id",
            "evidence_id",
            "packet_id",
            "source_id",
        ):
            if key in value:
                values.extend(_ids_from_value(value[key], allow_regex=allow_regex))
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in list(value)[:_MAX_ROWS]:
            values.extend(_ids_from_value(item, allow_regex=allow_regex))
    elif isinstance(value, str):
        token = value.strip()
        if token and _ID_RE.match(token):
            values.append(token)
        elif allow_regex:
            values.extend(_ID_RE.findall(token))
    return _clean_ids(values)


def extract_memory_ids(payload: Any) -> list[str]:
    """Extract explicit/derived lesson ids, never free-form reviewer text."""

    values: list[str] = []
    for key, item in _walk(payload):
        if key in {
            "memory_ids",
            "memory_id",
            "selected_memory_ids",
            "selected_memories",
            "applied_memory_ids",
            "applied_memories",
            "lesson_ids",
            "lesson_id",
            "feedback_ids",
            "feedback_id",
            "retrieved_memory_ids",
            "retrieved_memories",
            "expert_review_feedback",
            "memory_snapshot",
        }:
            values.extend(_ids_from_value(item, allow_regex=key in {"memory_snapshot"}))
    return _clean_ids(values)


def extract_evidence_ids(payload: Any) -> list[str]:
    values: list[str] = []
    for key, item in _walk(payload):
        if (
            "evidence" in key
            or key in {"source_refs", "source_ids", "valid_reference_ids"}
        ):
            values.extend(_ids_from_value(item, allow_regex=True))
    # A few legacy handoffs use ``derived_from`` and include packet ids.  Do
    # not classify those as evidence; the upstream extractor handles packets.
    return _clean_ids(
        token
        for token in values
        if token.lower().startswith(("evidence-", "ev-", "source-"))
    )


def extract_packet_ids(payload: Any) -> list[str]:
    values: list[str] = []
    for key, item in _walk(payload):
        if (
            "packet" in key
            or key in {"upstream_handoffs", "upstream", "derived_from"}
        ):
            values.extend(_ids_from_value(item, allow_regex=True))
    return _clean_ids(
        token for token in values if token.lower().startswith("packet-")
    )


def _first_value(payload: Any, names: Sequence[str]) -> Any:
    wanted = {str(name).lower() for name in names}
    for key, item in _walk(payload):
        if key in wanted and item not in (None, "", [], {}):
            return item
    return ""


def _first_present(payload: Any, names: Sequence[str]) -> tuple[bool, Any]:
    """Find a field while preserving the distinction between absent and empty.

    That distinction matters for ``applied_memory_ids=[]``: an empty list is a
    deliberate signal that retrieval was selected but no memory survived
    compaction, whereas an absent field means an older caller did not expose
    an applied-set boundary.
    """

    wanted = {str(name).lower() for name in names}
    # Prefer the current call's direct boundary over a nested business input.
    # ``run_core_json`` wraps payloads under ``input``; callers may still add a
    # turn-level override beside that wrapper and it must win deterministically.
    if isinstance(payload, Mapping):
        for key, item in payload.items():
            if str(key).lower() in wanted:
                return True, item
    for key, item in _walk(payload):
        if key in wanted:
            return True, item
    return False, None


def _explicit_id_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return _clean_ids([value])
    if isinstance(value, Mapping):
        return _ids_from_value(value, allow_regex=False)
    if isinstance(value, (list, tuple, set, frozenset)):
        values: list[str] = []
        for item in list(value)[:_MAX_ROWS]:
            if isinstance(item, Mapping):
                values.extend(_ids_from_value(item, allow_regex=False))
            else:
                values.extend(_explicit_id_list(item))
        return _clean_ids(values)
    return _clean_ids([value])


def _resolve_memory_boundary(
    payload: Any,
    context: Mapping[str, Any],
    names: Sequence[str],
    fallback: Sequence[str],
) -> tuple[list[str], bool, str]:
    """Resolve a selected/applied memory set from payload, then run context.

    Returns ``(ids, explicit, source)``.  Payload fields are searched first so
    a compaction boundary attached to one model turn can override the
    run-level default.  Empty explicit lists are retained as authoritative.
    """

    present, value = _first_present(payload, names)
    if present:
        return _explicit_id_list(value), True, "payload"
    present, value = _first_present(context, names)
    if present:
        return _explicit_id_list(value), True, "context"
    scope = (
        context.get("scope") or context.get("evolution_scope")
        if isinstance(context, Mapping)
        else None
    )
    if isinstance(scope, Mapping):
        present, value = _first_present(scope, names)
        if present:
            return _explicit_id_list(value), True, "context.scope"
    return list(fallback), False, "inferred"


def _scope_projection(payload: Any, context: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten bounded tenant/evolution scope fields into every trace row."""

    payload_map = payload if isinstance(payload, Mapping) else {}
    nested_scope = (
        context.get("scope") or context.get("evolution_scope")
        if isinstance(context, Mapping)
        else None
    )
    nested_scope = nested_scope if isinstance(nested_scope, Mapping) else {}

    def value_for(name: str) -> Any:
        # Scope is installed by the runner and is authoritative.  Payload is a
        # compatibility fallback for standalone workflow tests/embedders.
        return (
            context.get(name)
            or nested_scope.get(name)
            or payload_map.get(name)
            or _first_value(payload_map, (name,))
        )

    raw_stages = value_for("stage_scope")
    if isinstance(raw_stages, str):
        raw_stages = re.split(r"[,\s]+", raw_stages.strip()) if raw_stages.strip() else []
    if not isinstance(raw_stages, (list, tuple, set, frozenset)):
        raw_stages = []
    stage_scope = sorted(
        {
            token
            for token in (str(item).upper().strip() for item in raw_stages)
            if token in _STAGES
        }
    )
    return {
        "tenant_id": _bounded_text(value_for("tenant_id")),
        "workspace_id": _bounded_text(value_for("workspace_id")),
        "project_id": _bounded_text(value_for("project_id")),
        "profile_id": _bounded_text(value_for("profile_id")),
        "route": _bounded_text(value_for("route") or value_for("research_route")),
        "stage_scope": stage_scope,
        "trace_id": _bounded_text(
            context.get("trace_id")
            or nested_scope.get("trace_id")
            or payload_map.get("trace_id")
            or context.get("run_id")
            or payload_map.get("run_id")
        ),
    }


def stage_for(agent_id: Any, phase: Any, payload: Any) -> str:
    """Resolve a stable S1--S6 id from explicit fields, phase, or agent name."""

    if isinstance(payload, Mapping):
        for key in (
            "stage_id",
            "stage",
            "mission_node",
            "merge_target",
            "target_stage",
        ):
            value = str(payload.get(key, "")).upper().strip()
            if value in _STAGES:
                return value
        step = payload.get("step")
        if str(step).isdigit() and int(step) in range(1, 7):
            return f"S{int(step)}"
        steps = payload.get("contribution_to_steps")
        if isinstance(steps, (list, tuple)) and len(steps) == 1:
            value = str(steps[0]).upper().strip()
            if value in _STAGES:
                return value
        nested = payload.get("input")
        if isinstance(nested, Mapping) and nested is not payload:
            resolved = stage_for(agent_id, phase, nested)
            if resolved:
                return resolved
        for key in ("dynamic_agent_spec", "task_input", "context"):
            nested = payload.get(key)
            if isinstance(nested, Mapping) and nested is not payload:
                resolved = stage_for(agent_id, phase, nested)
                if resolved:
                    return resolved
    for candidate in (phase, agent_id):
        match = _STAGE_RE.search(str(candidate or ""))
        if match:
            return f"S{match.group(1)}"
    return ""


def _prompt_sections(payload: Any, host_context: Mapping[str, Any], stage: str) -> list[str]:
    explicit = _first_value(payload, ("prompt_section_ids", "prompt_sections"))
    if not explicit:
        explicit = host_context.get("prompt_section_ids")
    if isinstance(explicit, str):
        explicit = [explicit]
    rows = _clean_ids(explicit if isinstance(explicit, (list, tuple, set)) else [])
    if not rows and stage:
        rows = ["common", stage]
    return rows[:16]


def _evolution_context(host: Any) -> Mapping[str, Any]:
    value = getattr(host, "_evolution_context", {})
    return value if isinstance(value, Mapping) else {}


def _memory_rows(payload: Any, memory_ids: Sequence[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    wanted = set(memory_ids)
    for key, item in _walk(payload):
        if key not in {
            "expert_review_feedback",
            "retrieved_memories",
            "memory_snapshot",
            "feedback",
        }:
            continue
        values = item if isinstance(item, (list, tuple)) else [item]
        for row in values[:_MAX_ROWS]:
            if not isinstance(row, Mapping):
                continue
            identifier = str(
                row.get("feedback_id")
                or row.get("memory_id")
                or row.get("lesson_id")
                or ""
            ).strip()
            if identifier and (not wanted or identifier in wanted):
                rows.append(
                    {
                        key: row.get(key)
                        for key in (
                            "feedback_id",
                            "memory_id",
                            "lesson_id",
                            "effect_status",
                            "memory_status",
                            "taxonomy",
                            "utility_ema",
                            "target_agent_ids",
                        )
                        if key in row
                    }
                )
    return rows[:_MAX_ROWS]


def _upstream_projection(payload: Any, packet_ids: Sequence[str]) -> Any:
    if not isinstance(payload, Mapping):
        return list(packet_ids)
    keys = (
        "upstream_handoffs",
        "upstream",
        "upstream_synthesis",
        "packet_index",
        "packets",
        "prior_step_outputs",
        "derived_from",
    )
    projection = {key: payload.get(key) for key in keys if key in payload}
    if not projection:
        return list(packet_ids)
    return projection


def _query_projection(payload: Any) -> Any:
    if not isinstance(payload, Mapping):
        return payload
    nested = payload.get("input")
    if isinstance(nested, Mapping) and nested is not payload:
        payload = nested
    values: dict[str, Any] = {}
    for key in (
        "topic",
        "query",
        "structured_query_brief",
        "research_route",
        "discovery_branch",
    ):
        if key in payload and payload[key] not in (None, "", [], {}):
            values[key] = payload[key]
    return values or payload


def _evidence_projection(payload: Any, evidence_ids: Sequence[str]) -> Any:
    if not isinstance(payload, Mapping):
        return list(evidence_ids)
    nested = payload.get("input")
    if isinstance(nested, Mapping) and nested is not payload:
        payload = nested
    values: dict[str, Any] = {"evidence_ids": list(evidence_ids)}
    for key in ("evidence_index", "evidence_refs", "valid_evidence_ids", "public_evidence"):
        if key in payload:
            values[key] = payload[key]
    return values


def _provider_snapshot(host: Any) -> Mapping[str, Any]:
    provider = getattr(host, "provider", None)
    snapshot = getattr(provider, "snapshot", lambda: {})()
    return snapshot if isinstance(snapshot, Mapping) else {}


def _usage_value(metadata: Mapping[str, Any], key: str) -> Any:
    usage = metadata.get("usage", {})
    if isinstance(usage, Mapping):
        return usage.get(key)
    return None


def _infer_adoption(output: str, memory_ids: Sequence[str], metadata: Mapping[str, Any]) -> bool:
    explicit = metadata.get("adopted")
    if isinstance(explicit, bool):
        return explicit
    if not memory_ids or not output:
        return False
    lowered = output.lower()
    if any(token in lowered for token in ("不采纳", "不适用", "contradict", "not applicable", "reject")):
        return False
    if any(token in lowered for token in ("采纳", "遵循", "依据反馈", "adopt", "follow", "lesson")):
        return True
    # Explicit ids in a structured response are stronger evidence than a
    # lexical guess, while a plain prose response remains inconclusive.
    return any(identifier in output for identifier in memory_ids)


def _infer_contradiction(output: str, metadata: Mapping[str, Any]) -> bool:
    explicit = metadata.get("contradicted")
    if isinstance(explicit, bool):
        return explicit
    lowered = str(output or "").lower()
    return any(
        token in lowered
        for token in ("冲突", "矛盾", "不适用", "contradict", "conflict", "inconsistent")
    )


def _quality_delta(metadata: Mapping[str, Any]) -> float | None:
    for key in ("quality_delta", "utility_delta", "score_delta"):
        value = metadata.get(key)
        if value in (None, ""):
            continue
        try:
            return round(float(value), 6)
        except (TypeError, ValueError):
            continue
    return None


def _outcome(delta: float | None, *, success: bool, adopted: bool, contradicted: bool) -> str:
    if not success:
        return "failed"
    if delta is not None:
        if delta > 0.01:
            return "improved"
        if delta < -0.01:
            return "degraded"
        return "neutral"
    if contradicted:
        return "degraded"
    # A call can complete without enough information to claim causal impact.
    # Keep this distinct from neutral (which requires an evaluated delta).
    return "inconclusive" if adopted or not adopted else "inconclusive"


@dataclass
class EvolutionRetrievalHandle:
    retrieval_event_id: str
    host: Any
    stage_id: str
    agent_id: str
    phase: str
    run_id: str
    memory_ids: list[str]
    selected_memory_ids: list[str]
    applied_memory_ids: list[str]
    selected_explicit: bool
    applied_explicit: bool
    truncation_reason: str
    evidence_ids: list[str]
    packet_ids: list[str]
    base_payload: dict[str, Any]
    base_event: dict[str, Any]
    started_at: float = field(default_factory=monotonic)


def _base_event(
    host: Any,
    *,
    agent_id: str,
    phase: str,
    payload: Any,
    system: str,
    retrieval_event_id: str,
) -> tuple[dict[str, Any], EvolutionRetrievalHandle | None]:
    context = _evolution_context(host)
    stage = stage_for(agent_id, phase, payload)
    if not stage:
        return {}, None
    payload_map = payload if isinstance(payload, Mapping) else {}
    memory_ids = extract_memory_ids(payload)
    # A run-level snapshot can contain ids while the current stage has no
    # targeted lesson.  Keep the snapshot hash but avoid claiming selection.
    snapshot_ids = _clean_ids(
        context.get("memory_ids", [])
        if isinstance(context.get("memory_ids", []), (list, tuple, set))
        else []
    )
    prompt_bundle_hash = str(
        _first_value(payload, ("prompt_bundle_hash",))
        or context.get("prompt_bundle_hash", "")
    )
    memory_snapshot_hash = str(
        _first_value(payload, ("memory_snapshot_hash",))
        or context.get("memory_snapshot_hash", "")
    )
    if not prompt_bundle_hash:
        prompt_bundle_hash = stable_hash(system)
    if not memory_snapshot_hash:
        memory_snapshot_hash = stable_hash(
            _memory_rows(payload, memory_ids or snapshot_ids) or snapshot_ids
        )
    selected_memory_ids, selected_explicit, selected_source = _resolve_memory_boundary(
        payload,
        context,
        ("selected_memory_ids", "selected_memories"),
        memory_ids,
    )
    # ``applied_memory_ids`` was added after the original callback contract.
    # Keep the legacy inference when old callers expose only a retrieved list,
    # but retain an explicit empty list as a hard boundary (for example when
    # token-budget compaction drops all selected lessons before injection).
    applied_memory_ids, applied_explicit, applied_source = _resolve_memory_boundary(
        payload,
        context,
        ("applied_memory_ids", "applied_memories"),
        selected_memory_ids,
    )
    truncation_present, truncation_value = _first_present(
        payload,
        ("truncation_reason", "memory_truncation_reason"),
    )
    if not truncation_present:
        truncation_present, truncation_value = _first_present(
            context,
            ("truncation_reason", "memory_truncation_reason"),
        )
    context_scope = (
        context.get("scope") or context.get("evolution_scope")
        if isinstance(context, Mapping)
        else None
    )
    if not truncation_present and isinstance(context_scope, Mapping):
        truncation_present, truncation_value = _first_present(
            context_scope,
            ("truncation_reason", "memory_truncation_reason"),
        )
    truncation_reason = _bounded_text(truncation_value, limit=512)
    evidence_ids = extract_evidence_ids(payload)
    packet_ids = extract_packet_ids(payload)
    query_hash = stable_hash(_query_projection(payload_map))
    evidence_hash = stable_hash(_evidence_projection(payload_map, evidence_ids))
    upstream_hash = stable_hash(_upstream_projection(payload_map, packet_ids))
    input_hash = stable_hash(payload_map)
    prompt_sections = _prompt_sections(payload_map, context, stage)
    snapshot = _provider_snapshot(host)
    run_id = str(
        _first_value(payload, ("run_id",))
        or context.get("run_id", "")
        or ""
    ).strip()
    scope_fields = _scope_projection(payload_map, context)
    event = {
        "retrieval_event_id": retrieval_event_id,
        "run_id": run_id,
        "stage": stage,
        "stage_id": stage,
        "agent_id": str(agent_id),
        "phase": str(phase),
        "memory_ids": memory_ids,
        "memory_id": selected_memory_ids[0] if selected_memory_ids else "",
        "selected_memory_ids": selected_memory_ids,
        "applied_memory_ids": applied_memory_ids,
        "selected_memory_ids_source": selected_source,
        "applied_memory_ids_source": applied_source,
        "selected_memory_ids_explicit": selected_explicit,
        "applied_memory_ids_explicit": applied_explicit,
        "truncation_reason": truncation_reason,
        "memory_truncation_reason": truncation_reason,
        "memory_snapshot_ids": snapshot_ids[:_MAX_IDS],
        "prompt_bundle_hash": prompt_bundle_hash,
        "memory_snapshot_hash": memory_snapshot_hash,
        "prompt_section_ids": prompt_sections,
        "query_hash": query_hash,
        "evidence_snapshot_hash": evidence_hash,
        "upstream_packet_hash": upstream_hash,
        "input_hash": input_hash,
        "evidence_ids": evidence_ids,
        "upstream_packet_ids": packet_ids,
        "selected": bool(selected_memory_ids),
        "applied": False,
        "adopted": False,
        "contradicted": False,
        "outcome": "pending",
        "retrieval_status": (
            "selected" if selected_memory_ids else "no_memory_selected"
        ),
        "quality_delta": None,
        "token_cost": None,
        "cost_usd": None,
        "latency_ms": None,
        "model_profile": str(snapshot.get("model", "")),
        "provider": str(snapshot.get("type", "")),
        "attempt": payload_map.get("attempt") or payload_map.get("middle_cycle"),
        "created_at": now_iso(),
        "schema_version": "1.0",
        **scope_fields,
    }
    handle = EvolutionRetrievalHandle(
        retrieval_event_id=retrieval_event_id,
        host=host,
        stage_id=stage,
        agent_id=str(agent_id),
        phase=str(phase),
        run_id=run_id,
        memory_ids=memory_ids,
        selected_memory_ids=selected_memory_ids,
        applied_memory_ids=applied_memory_ids,
        selected_explicit=selected_explicit,
        applied_explicit=applied_explicit,
        truncation_reason=truncation_reason,
        evidence_ids=evidence_ids,
        packet_ids=packet_ids,
        base_payload=dict(payload_map),
        base_event=event,
    )
    return event, handle


def _emit(host: Any, event: Mapping[str, Any]) -> None:
    """Emit a bounded event to a host sink or run-local buffer."""

    payload = dict(event)
    callback = getattr(host, "_evolution_trace_sink", None)
    if callable(callback):
        try:
            callback(payload)
            return
        except TypeError:
            # Compatibility with application event sinks using
            # ``(event_type, payload)``.
            try:
                callback(str(payload.get("event_type", "evolution_retrieval_event")), payload)
                return
            except Exception:
                return
        except Exception:
            return
    # Backward-compatible bridge: older runners only install the winning
    # progress callback.  Forward the event there as well as retaining the
    # local buffer, allowing the runner to persist it without a new provider
    # interface.  A dedicated sink remains authoritative and avoids a second
    # delivery path.
    progress = getattr(host, "_winning_progress_callback", None)
    if callable(progress):
        try:
            progress(dict(event))
        except Exception:
            pass
    lock = getattr(host, "_evolution_trace_lock", None)
    if lock is None:
        lock = RLock()
        try:
            host._evolution_trace_lock = lock
        except Exception:
            pass
    try:
        with lock:
            rows = getattr(host, "_evolution_trace_events", None)
            if not isinstance(rows, list):
                rows = []
                host._evolution_trace_events = rows
            rows.append(payload)
    except Exception:
        return


def set_evolution_trace_sink(host: Any, callback: Callable[..., Any] | None) -> None:
    """Install/remove the callback receiving lifecycle records for one host."""

    host._evolution_trace_sink = callback
    if not hasattr(host, "_evolution_trace_lock"):
        host._evolution_trace_lock = RLock()
    if not hasattr(host, "_evolution_trace_events"):
        host._evolution_trace_events = []


def set_evolution_context(host: Any, context: Mapping[str, Any] | None) -> None:
    """Attach immutable run-level snapshot metadata used by call attribution."""

    prior = getattr(host, "_evolution_context", {})
    merged = dict(prior) if isinstance(prior, Mapping) else {}
    explicit_boundary_keys = {
        "selected_memory_ids",
        "selected_memories",
        "applied_memory_ids",
        "applied_memories",
        "truncation_reason",
        "memory_truncation_reason",
    }
    for key, value in dict(context or {}).items():
        # Nested workflow calls often provide a partial context with empty
        # compatibility fields.  Do not erase a run-level snapshot already
        # installed by the runner merely because that field is omitted here.
        if value in (None, "", [], {}) and key not in explicit_boundary_keys:
            continue
        merged[key] = value
    host._evolution_context = merged


def evolution_trace_events(host: Any) -> list[dict[str, Any]]:
    lock = getattr(host, "_evolution_trace_lock", None)
    rows = getattr(host, "_evolution_trace_events", [])
    if not isinstance(rows, list):
        return []
    if lock is None:
        return [dict(row) for row in rows if isinstance(row, Mapping)]
    with lock:
        return [dict(row) for row in rows if isinstance(row, Mapping)]


def begin_retrieval(
    host: Any,
    *,
    agent_id: str,
    phase: str,
    payload: Any,
    system: str,
) -> EvolutionRetrievalHandle | None:
    """Emit ``selected`` and ``applied`` boundaries before a model call."""

    retrieval_event_id = f"retrieval-{uuid4()}"
    event, handle = _base_event(
        host,
        agent_id=agent_id,
        phase=phase,
        payload=payload,
        system=system,
        retrieval_event_id=retrieval_event_id,
    )
    if handle is None:
        return None
    selected = bool(handle.selected_memory_ids)
    selected_event = {
        **event,
        "event_type": "evolution_retrieval_selected",
        "retrieval_status": "selected" if selected else "no_memory_selected",
        "applied": False,
    }
    _emit(host, selected_event)
    applied = bool(handle.applied_memory_ids)
    if applied:
        applied_status = "applied"
    elif selected:
        applied_status = "selected_not_applied"
    else:
        applied_status = "no_memory_applied"
    applied_event = {
        **event,
        "event_type": "evolution_retrieval_applied",
        "retrieval_status": applied_status,
        "applied": applied,
    }
    _emit(host, applied_event)
    return handle


def finish_retrieval(
    handle: EvolutionRetrievalHandle | None,
    *,
    output: str = "",
    metadata: Mapping[str, Any] | None = None,
    success: bool = True,
    error: BaseException | None = None,
) -> None:
    """Emit the terminal attribution event for a model call."""

    if handle is None:
        return
    details = dict(metadata or {})
    elapsed = max(0.0, monotonic() - handle.started_at)
    usage = details.get("usage", {})
    usage = usage if isinstance(usage, Mapping) else {}
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    total_tokens = usage.get("total_tokens")
    if total_tokens is None:
        try:
            total_tokens = int(input_tokens or 0) + int(output_tokens or 0)
        except (TypeError, ValueError):
            total_tokens = None
    if total_tokens is None:
        # Conservative estimate used only when a provider omits usage.
        total_tokens = max(0, (len(str(output or "")) + len(str(handle.base_payload))) // 4)
    # A provider can report the final applied set after prompt construction.
    # An explicitly empty list remains authoritative and prevents a lexical
    # output match from claiming that a selected-but-dropped lesson was used.
    applied_memory_ids = list(handle.applied_memory_ids)
    applied_explicit = handle.applied_explicit
    present, value = _first_present(
        details,
        ("applied_memory_ids", "applied_memories"),
    )
    if present:
        applied_memory_ids = _explicit_id_list(value)
        applied_explicit = True
    selected_memory_ids = list(handle.selected_memory_ids)
    present, value = _first_present(
        details,
        ("selected_memory_ids", "selected_memories"),
    )
    if present:
        selected_memory_ids = _explicit_id_list(value)
    truncation_reason = handle.truncation_reason
    present, value = _first_present(
        details,
        ("truncation_reason", "memory_truncation_reason"),
    )
    if present:
        truncation_reason = _bounded_text(value, limit=512)
    delta = _quality_delta(details)
    adopted = _infer_adoption(str(output or ""), applied_memory_ids, details)
    contradicted = _infer_contradiction(str(output or ""), details)
    selected = bool(selected_memory_ids)
    applied = bool(applied_memory_ids)
    event = {
        **handle.base_event,
        "event_type": "evolution_retrieval_outcome",
        "memory_ids": list(handle.memory_ids),
        "selected_memory_ids": selected_memory_ids,
        "applied_memory_ids": applied_memory_ids,
        "selected": selected,
        "applied": applied,
        "selected_memory_ids_explicit": (
            handle.selected_explicit
            or any(key in details for key in ("selected_memory_ids", "selected_memories"))
        ),
        "applied_memory_ids_explicit": applied_explicit,
        "truncation_reason": truncation_reason,
        "memory_truncation_reason": truncation_reason,
        "adopted": adopted,
        "contradicted": contradicted,
        "outcome": _outcome(
            delta,
            success=success,
            adopted=adopted,
            contradicted=contradicted,
        ),
        "retrieval_status": "outcome",
        "quality_delta": delta,
        "token_cost": total_tokens,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cost_usd": details.get("cost_usd", details.get("estimated_cost_usd")),
        "latency_ms": round(elapsed * 1000, 3),
        "elapsed_seconds": round(elapsed, 6),
        "output_hash": stable_hash(str(output or "")),
        "finish_reason": details.get("finish_reason"),
        "error_type": type(error).__name__ if error is not None else "",
        "error": str(error)[:512] if error is not None else "",
        "created_at": now_iso(),
    }
    _emit(handle.host, event)


__all__ = [
    "EvolutionRetrievalHandle",
    "begin_retrieval",
    "evolution_trace_events",
    "extract_evidence_ids",
    "extract_memory_ids",
    "extract_packet_ids",
    "finish_retrieval",
    "set_evolution_context",
    "set_evolution_trace_sink",
    "stable_hash",
    "stage_for",
]
