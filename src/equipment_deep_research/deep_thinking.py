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
                    "artifact_refs": list(item.get("artifact_refs", []))[:16]
                    if isinstance(item.get("artifact_refs", []), list)
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
    status: str = "completed",
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
        if not isinstance(messages, list) or len(messages) >= MAX_MESSAGES_PER_SESSION:
            raise ValueError("message limit reached for this session")
        item = {
            "message_id": new_id("message"),
            "role": normalized_role,
            "content": text,
            "created_at": now_iso(),
            "status": _bounded_text(status or "completed", 32),
            "artifact_refs": [
                _bounded_text(ref, 180)
                for ref in list(artifact_refs)[:16]
                if _bounded_text(ref, 180)
            ],
        }
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
    candidate = _first_context_text(
        sources,
        ("title", "name", "equipment_form", "primary_equipment_identity", "capability_name"),
        capability_name or "当前能力方向",
    )
    mechanism = _first_context_text(
        sources,
        ("mechanism_chain", "winning_mechanism", "core_disruptive_difference", "reference_overview", "concise_winning_summary"),
        "需进一步确认该方向如何改变现有任务链和对手反应节奏",
    )
    evidence = _first_context_text(
        sources,
        ("evidence_ids", "evidence_refs", "validation_plan", "failure_boundaries", "evidence_basis"),
        "当前仅继承父任务的证据引用，新增判断需回到可核验来源",
    )
    question = _bounded_text(question, MAX_MESSAGE_CHARS)
    query = _bounded_text(query, 1800)
    capability_names = _context_name_list(
        context,
        "capability_cards",
        ("name", "title", "capability_name"),
    )
    reference_names = _context_name_list(
        context,
        "reference_weapons",
        ("title", "name", "equipment_form", "primary_equipment_identity"),
    )
    context_hint_parts: list[str] = []
    if capability_names:
        context_hint_parts.append(f"能力卡：{'、'.join(capability_names)}")
    if reference_names:
        context_hint_parts.append(f"参考方向：{'、'.join(reference_names)}")
    context_hint = "；".join(context_hint_parts)
    context_sentence = f"当前结果上下文（{context_hint}）已纳入本轮判断。" if context_hint else "本轮使用了当前会话保存的可见结果上下文。"
    answer = {
        "mode": mode,
        "sections": [
            {
                "title": "核心判断",
                "text": f"围绕“{candidate}”继续追问“{question}”，当前 Query（{query}）下最值得验证的是：{mechanism}。这是一条待核验的研究假设，不等同于已证实事实。",
            },
            {
                "title": "发散方向",
                "text": f"{context_sentence} 可沿任务对象与直接效果、对手适应与失效边界、装备形态与工程约束、证据与淘汰条件四条线并行展开；先判断哪一条会改变能力结论，再决定是否启动独立深研。",
            },
            {
                "title": "证据与验证",
                "text": f"继承上下文提示：{evidence}。下一轮应补充可定位的一手或高质量二手来源，并记录支持、反证和适用范围，避免把参考武器的存在误写成能力事实。",
            },
        ],
        "next_questions": [
            f"{candidate}在哪个具体作战节点形成不可替代的直接效果？",
            "对手采取哪一种低成本适应后，该方向会失效？",
            "需要补哪类证据才能把这条假设升级为可审核的能力画像？",
        ],
    }
    return answer


def _default_module_texts(candidate: Mapping[str, Any], *, query: str, focus: str) -> dict[str, str]:
    name = _first_text(candidate, ("title", "name", "primary_equipment_identity", "equipment_form"), "参考装备方向")
    overview = _first_text(candidate, ("reference_overview", "overview", "concise_winning_summary"), "该参考方向来自当前 Query 的候选谱系，需通过独立证据核验其作战作用、适用条件与失效边界。")
    mechanism = _first_text(candidate, ("operational_mechanism", "mechanism_chain", "winning_mechanism", "core_disruptive_difference"), "通过改变任务链中的感知、决策、打击或保障连接，争取传统方案难以形成的时间、空间或资源窗口。")
    forms = _first_text(candidate, ("equipment_forms", "equipment_form", "primary_equipment_identity"), name)
    boundaries = _first_text(candidate, ("failure_boundary", "failure_boundaries", "risk_boundaries", "validation_plan"), "强干扰、目标特征不足、授权约束或关键链路中断时，能力可能退化为普通装备效果。")
    direct_effect = _first_text(candidate, ("direct_military_effects", "military_value", "mission_effect", "function"), "压缩对手反应时间、打乱资源分配或扩大局部任务窗口。")
    focus_text = _bounded_text(focus or "针对参考装备方向开展深度研究", 900)
    prefix = f"研究 Query：{_bounded_text(query, 500)}；本次聚焦：{focus_text}。"
    return {
        "overview": f"{prefix}“{name}”不是已入选 S6 卡片，而是从候选谱系中抽取的参考方向。{overview} 研究重点是说明它在何种任务对象、对手反应和约束下改变原有作战窗口，并明确哪些判断仍需证据支持。",
        "technology_implementation": f"围绕“{forms}”的实现，应优先核查感知与识别、任务规划、抗干扰通信、动力与载荷、制造维护等耦合关系。不要只描述技术名词，而要说明技术如何支撑“发现—决策—作用—评估”闭环；{mechanism}",
        "operational_process": f"在授权条件满足后，先确认目标和直接效果，再安排该方向进入任务链；根据对手搜索、拦截、欺骗或机动反馈调整投入，出现识别冲突、附带损伤风险或链路失稳时拒止、脱离或转交后续节点。{boundaries}",
        "capability_effects": f"若假设成立，该方向的直接军事效果应表现为：{direct_effect} 不能只宣称性能提升；需要用任务前后对照和可追溯来源验证效果强度、适用场景与替代方案。",
        "winning_logic": f"其潜在制胜逻辑是把对手原本可预测的处置节奏变成多点、连续或不对称的选择压力；对手若采用低成本适应，{boundaries}。因此本卡应作为可审核候选画像，待补证与专家复核后再决定是否升级为正式能力卡。",
    }


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
    name = _first_text(candidate, ("title", "name", "primary_equipment_identity", "equipment_form"), "参考装备方向")
    capability_id = f"deep-{safe_segment(hypothesis_id, limit=100) or uuid4().hex}"
    # Card identity is stable across retries and conversation turns.  Version
    # numbers, rather than random card ids, represent subsequent deep-research
    # findings for the same hypothesis.
    supplied_binding = _first_text(candidate, ("card_binding_id", "capability_binding_id"), "")
    card_binding_id = supplied_binding or f"deep-card-{hashlib.sha256(hypothesis_id.encode('utf-8')).hexdigest()[:24]}"
    modules = _default_module_texts(candidate, query=query, focus=focus)
    equipment_form = _first_text(
        candidate,
        ("equipment_form", "primary_equipment_identity", "equipment_forms"),
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
        "portrait_authoring_status": "deep_research_authored",
        "analysis_provenance_status": "deep_research_reference",
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
    "synthesize_reply",
    "update_session",
]
