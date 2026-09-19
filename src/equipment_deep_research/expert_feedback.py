"""Expert review feedback persistence and bounded learning handoff.

Feedback is deliberately kept outside the generated capability artifact.  A
run owns an auditable JSON snapshot, while a small append-only knowledge index
is curated by a local memory processor before routing compact signals to the
relevant S1-S6 stages.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from threading import Lock
from uuid import uuid4
from typing import Any, Mapping


RUN_FEEDBACK_FILENAME = "expert_feedback.json"
KNOWLEDGE_FEEDBACK_FILENAME = "expert-review-feedback.json"
ALL_AGENT_IDS = ("S1", "S2", "S3", "S4", "S5", "S6")
S5_SCORE_WEIGHTS = {
    "innovation": 0.30,
    "demand": 0.30,
    "feasibility": 0.20,
    "effectiveness": 0.10,
    "development": 0.10,
}
MEMORY_PROCESSOR_AGENT_ID = "expert_feedback_memory"
MAX_MEMORY_ITEMS = 8
EFFECT_STATUSES = (
    "pending_validation",
    "validated",
    "effective",
    "ineffective",
    "inconclusive",
    "superseded",
    "withdrawn",
)
DEFAULT_EFFECT_STATUS = "pending_validation"
# ``superseded`` and ``withdrawn`` are tombstone states.  Once a feedback
# lesson has been replaced or explicitly removed it must not be silently
# reactivated by a stale evaluator retry.  A new lesson should be ingested
# instead, preserving the original audit row and its reason for retirement.
_IMMUTABLE_EFFECT_STATUSES = frozenset({"superseded", "withdrawn"})
DEFAULT_MEMORY_STATUS = "candidate"
DEFAULT_MEMORY_TTL_DAYS = 90
MEMORY_STATUSES = (
    "candidate",
    "validated",
    "active",
    "quarantined",
    "retired",
)
_AGENT_FOCUS_TERMS = {
    "S1": ("对手", "敌方", "威胁", "反适应", "诱饵", "侦察", "防御", "薄弱"),
    "S2": ("作战", "战法", "流程", "部署", "协同", "授权", "时序", "任务", "交战"),
    "S3": ("候选", "发散", "创意", "构型", "装备", "新质", "方案", "机理", "创新"),
    "S4": ("能力", "映射", "接口", "技术", "功能", "指标", "体系", "实现", "耦合"),
    "S5": ("筛选", "创新", "独立", "重复", "组合", "基线", "差距", "优先级", "保留"),
    "S6": ("画像", "成稿", "写作", "概述", "逻辑", "表达", "一致", "证据", "边界", "补强"),
}
_HIGH_SIGNAL_TERMS = (
    "需要",
    "应",
    "补充",
    "缺少",
    "避免",
    "不能",
    "问题",
    "边界",
    "验证",
    "优先",
    "改进",
    "准确",
    "证据",
    "流程",
    "技术",
)
_lock = Lock()


class _FeedbackStatusCapability:
    """Process-local capability for trusted evaluator status writes.

    The HTTP API still performs the real identity/role check.  This opaque
    object is an additional library boundary: ordinary callers that merely
    submit reviewer text cannot mark a row ``validated``/``effective`` by
    copying those fields into an input mapping.  It is intentionally omitted
    from ``__all__`` and must only be used by in-process API/evaluator glue.
    """

    __slots__ = ()


_TRUSTED_FEEDBACK_STATUS_TOKEN = _FeedbackStatusCapability()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _clean_list(value: Any, *, limit: int, item_limit: int = 120) -> list[str]:
    values = value if isinstance(value, (list, tuple)) else [value]
    return list(dict.fromkeys(_clean_text(item, item_limit) for item in values if _clean_text(item, item_limit)))[:limit]


def _normalize_agent_ids(value: Any) -> list[str]:
    """Normalize legacy/lower-case stage ids before routing or persistence."""

    normalized: list[str] = []
    # Older API clients have used all of ``["S4", "S6"]``, ``"S4,S6"`` and
    # ``"S4 S6"``.  Treat those forms identically.  Flattening happens before
    # validation so a malformed token cannot become a scope wildcard.
    raw_values = value if isinstance(value, (list, tuple, set, frozenset)) else [value]
    flattened: list[str] = []
    for raw in raw_values:
        flattened.extend(re.split(r"[,;\s]+", str(raw or "").strip()))
    for raw_agent_id in _clean_list(
        flattened, limit=len(ALL_AGENT_IDS), item_limit=32
    ):
        agent_id = raw_agent_id.upper().strip()
        if agent_id in ALL_AGENT_IDS and agent_id not in normalized:
            normalized.append(agent_id)
    return normalized


def _infer_feedback_taxonomy(signal: str) -> list[str]:
    """Map common review language to stable, queryable issue categories.

    This is intentionally conservative.  The mapping creates a candidate
    label for filtering and evaluation; it is not treated as an expert
    judgement and can be amended during human adjudication.
    """

    text = str(signal or "")
    rules = (
        ("evidence_boundary", ("证据", "来源", "验证", "边界")),
        ("unsupported_precision", ("夸大", "精确", "直接写成", "未公开")),
        ("identity_freeze", ("身份", "候选名", "同一装备", "混淆")),
        ("duplicate_selection", ("重复", "独立", "去重", "筛选")),
        ("mechanism_feasibility", ("机理", "实现", "技术", "可行")),
        ("mission_timing_gap", ("时序", "部署", "任务", "交战")),
        ("portfolio_diversity", ("组合", "多样", "覆盖", "优先级")),
        ("causal_chain", ("逻辑", "因果", "链", "闭合")),
    )
    labels = [label for label, terms in rules if any(term in text for term in terms)]
    return labels[:4] or ["general_quality"]


def _infer_feedback_severity(row: Mapping[str, Any]) -> str:
    explicit = str(row.get("severity", "")).strip().lower()
    if explicit in {"low", "medium", "high", "critical"}:
        return explicit
    verdict = str(row.get("verdict", "")).strip().lower()
    if verdict == "rejected":
        return "high"
    rating = row.get("rating")
    try:
        if rating is not None and int(rating) <= 2:
            return "high"
    except (TypeError, ValueError):
        pass
    return "medium"


def _infer_feedback_confidence(row: Mapping[str, Any]) -> float:
    raw_explicit = row.get("confidence")
    if raw_explicit not in (None, ""):
        try:
            explicit = float(raw_explicit)
        except (TypeError, ValueError):
            explicit = -1.0
        if 0.0 <= explicit <= 1.0:
            return round(explicit, 4)
    role = str(row.get("reviewer_role", "expert")).strip().lower()
    base = 0.8 if role in {"expert", "domain_reviewer", "auditor"} else 0.6
    if str(row.get("verdict", "")).strip().lower() == "approved":
        base += 0.05
    return min(1.0, round(base, 4))


def _normalize_effect_status(value: Any) -> str:
    status = str(value or DEFAULT_EFFECT_STATUS).strip().lower()
    return status if status in EFFECT_STATUSES else DEFAULT_EFFECT_STATUS


def _require_effect_evidence(
    evaluator_id: Any,
    evaluation_id: Any,
) -> tuple[str, str]:
    """Require a named evaluator and durable evaluation reference.

    A trusted in-process capability prevents ordinary feedback submitters from
    writing terminal states, but it does not make an otherwise untraceable
    transition auditable.  Every terminal transition therefore needs both an
    evaluator identity and an evaluation/replay id.  Keep this check local to
    the transition function so legacy ingestion remains backwards compatible.
    """

    evaluator = _clean_text(evaluator_id, 160)
    evaluation = _clean_text(evaluation_id, 160)
    if not evaluator:
        raise ValueError("evaluator_id is required for effect status updates")
    if not evaluation:
        raise ValueError("evaluation_id is required for effect status updates")
    return evaluator, evaluation


def _guard_effect_transition(
    prior_status: Any,
    next_status: str,
    *,
    prior_evaluator_id: Any = "",
    prior_evaluation_id: Any = "",
    next_evaluator_id: str = "",
    next_evaluation_id: str = "",
) -> bool:
    """Validate the feedback effect state machine.

    Returns ``True`` for an idempotent replay of the same tombstone state.  A
    different transition out of ``superseded``/``withdrawn`` is rejected,
    including attempts to move back to ``validated`` or ``effective``.
    """

    prior = _normalize_effect_status(prior_status)
    if prior not in _IMMUTABLE_EFFECT_STATUSES:
        return False
    if prior != next_status:
        raise ValueError(
            f"cannot transition immutable feedback effect status: {prior} -> {next_status}"
        )
    # An identical, retried write is safe only when it points at the same
    # evaluation.  Legacy rows may have no evaluation id; allowing one
    # evidence-bearing repair keeps migration possible without allowing a
    # tombstone to be resurrected.
    previous_evaluation = _clean_text(prior_evaluation_id, 160)
    if previous_evaluation and previous_evaluation != next_evaluation_id:
        raise ValueError("immutable feedback effect status has different evidence")
    previous_evaluator = _clean_text(prior_evaluator_id, 160)
    if previous_evaluator and previous_evaluator != next_evaluator_id:
        raise ValueError("immutable feedback effect status has different evaluator")
    return True


def _normalize_memory_status(value: Any) -> str:
    status = str(value or DEFAULT_MEMORY_STATUS).strip().lower()
    return status if status in MEMORY_STATUSES else DEFAULT_MEMORY_STATUS


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number else default


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_expired(item: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    """Apply a conservative TTL to derived memory without deleting its audit row."""

    created_at = str(item.get("created_at", "")).strip()
    if not created_at:
        return False
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    ttl_days = max(1, _safe_int(item.get("ttl_days"), DEFAULT_MEMORY_TTL_DAYS))
    reference = now or datetime.now(timezone.utc)
    return reference >= created + timedelta(days=ttl_days)


def _signal_dedupe_key(signal: Any) -> str:
    """Build a stable semantic key while ignoring card-specific prefixes."""

    text = _clean_text(signal, 1200).lower()
    text = re.sub(r"^针对[^：:]{1,160}[：:]\s*", "", text)
    return re.sub(r"\W+", "", text)


def _feedback_dedupe_key(signal: Any, row: Mapping[str, Any] | None = None) -> str:
    """Build a scope-aware semantic key for idempotent feedback ingestion.

    The old signal-only key made identical comments from two tenants collide in
    the shared knowledge index.  Scope is part of the identity, while the
    human-authored signal remains normalized in the same way for retry
    idempotency.  Empty scope values intentionally remain empty, preserving
    the legacy/global namespace without creating a cross-tenant wildcard.
    """

    item = row if isinstance(row, Mapping) else {}
    scope = {
        key: " ".join(str(item.get(key, "") or "").split()).strip().lower()
        for key in ("tenant_id", "workspace_id", "project_id", "profile_id", "route")
    }
    scope["stage_scope"] = ",".join(
        sorted(_normalize_agent_ids(item.get("stage_scope")))
    )
    canonical = json.dumps(
        {"scope": scope, "signal": _signal_dedupe_key(signal)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + sha256(canonical.encode("utf-8")).hexdigest()


def _curate_learning_signal(comment: Any, capability_name: Any = "") -> str:
    """Extract a short, actionable learning signal from free-form feedback.

    The reviewer remains the source of truth; this is a deterministic
    compression step rather than a generated judgement.  It keeps sentences
    that contain common action/quality markers, preserves their original order,
    removes duplicates, and bounds the text sent into future Agent prompts.
    """

    text = _clean_text(comment, 4000)
    if not text:
        return ""
    parts = [
        _clean_text(part, 360)
        for part in re.split(r"(?<=[。！？!?；;])\s*|\n+", text)
        if _clean_text(part, 360)
    ]
    if not parts:
        return text[:900]
    marked = [
        (index, part)
        for index, part in enumerate(parts)
        if any(term in part for term in _HIGH_SIGNAL_TERMS)
    ]
    selected = [part for _, part in marked] or parts[:3]
    selected = list(dict.fromkeys(selected))
    signal = "；".join(selected)
    signal = _clean_text(signal, 900)
    name = _clean_text(capability_name, 160)
    if (
        name
        and name != "本任务整体能力画像"
        and not signal.startswith(name)
        and not signal.startswith(f"针对{name}：")
    ):
        signal = f"针对{name}：{signal}"
    return signal


def _route_learning_signal(signal: str, capability_name: Any = "") -> tuple[list[str], dict[str, int], str]:
    """Route one compact signal to a small set of relevant S-agent stages."""

    text = f"{_clean_text(capability_name, 160)} {signal}".lower()
    scores = {
        agent_id: sum(text.count(term) for term in terms)
        for agent_id, terms in _AGENT_FOCUS_TERMS.items()
    }
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    positive = [(agent_id, score) for agent_id, score in ranked if score > 0]
    if not positive:
        # A generic portrait review is most actionable to S6; keep a small
        # handoff to S4 because it owns the capability-to-equipment boundary.
        selected = ["S6", "S4"]
        reason = "通用画像反馈，优先交给 S6 成稿与 S4 能力映射"
    else:
        top_score = positive[0][1]
        selected = [
            agent_id
            for agent_id, score in positive
            if score >= max(1, int(top_score * 0.55))
        ][:3]
        reason = "、".join(selected) + " 命中反馈中的对应主题词"
    return selected, {agent_id: score for agent_id, score in ranked}, reason


class ExpertFeedbackMemoryAgent:
    """Bounded local memory processor for reviewer feedback.

    It intentionally has no model/network dependency: it distills the human
    note, scores stage relevance, routes to at most three agents, and marks the
    record as processed.  The interface leaves room for a future LLM-backed
    implementation without changing persistence or runner handoffs.
    """

    agent_id = MEMORY_PROCESSOR_AGENT_ID

    def process(
        self,
        feedback: Mapping[str, Any],
        *,
        _trusted_status_token: object | None = None,
    ) -> dict[str, Any]:
        row = dict(feedback)
        raw_comment = _clean_text(row.get("comment"), 4000)
        raw_important_information = _clean_text(
            row.get("important_information"), 2400
        )
        signal = _curate_learning_signal(
            row.get("learning_signal")
            or row.get("important_information")
            or row.get("comment"),
            row.get("capability_name"),
        )
        requested = _normalize_agent_ids(row.get("target_agent_ids"))
        scoped_stages = _normalize_agent_ids(row.get("stage_scope"))
        if scoped_stages:
            # Stage scope is a hard routing boundary.  It can narrow an
            # explicitly requested target list, but never expand it beyond
            # the stages authorized by the feedback/run context.
            requested = (
                [agent_id for agent_id in requested if agent_id in scoped_stages]
                if requested
                else list(scoped_stages)
            )
        if requested and set(requested) != set(ALL_AGENT_IDS):
            targets = [agent_id for agent_id in ALL_AGENT_IDS if agent_id in requested]
            route_scores = {agent_id: 0 for agent_id in ALL_AGENT_IDS}
            route_reason = "沿用兼容客户端指定的目标 Agent"
        else:
            targets, route_scores, route_reason = _route_learning_signal(
                signal,
                row.get("capability_name"),
            )
            if scoped_stages:
                targets = [agent_id for agent_id in targets if agent_id in scoped_stages]
                if not targets:
                    targets = list(scoped_stages)
                route_reason = f"stage_scope限制：{','.join(targets)}"
        if row.get("expert_dimension_scores") and (
            not scoped_stages or "S5" in scoped_stages
        ):
            if "S5" not in targets:
                targets = ["S5", *targets][:3]
            route_scores["S5"] = max(1, int(route_scores.get("S5", 0)))
            route_reason = f"结构化五维评分定向S5；{route_reason}"
        effect_status = _normalize_effect_status(row.get("effect_status"))
        memory_status = _normalize_memory_status(row.get("memory_status"))
        trusted_status = _trusted_status_token is _TRUSTED_FEEDBACK_STATUS_TOKEN
        # A client-supplied status must never escalate an unvalidated item into
        # the production memory layer.  Promotion is performed by a separate
        # evaluator/adjudicator in a later lifecycle step.  The explicit
        # process-local capability is reserved for that evaluator path and is
        # not part of the public request contract.
        if not trusted_status or effect_status not in {"validated", "effective"}:
            effect_status = DEFAULT_EFFECT_STATUS
            memory_status = DEFAULT_MEMORY_STATUS
        row.update(
            {
                "learning_signal": signal,
                "important_information": signal,
                # Keep the bounded downstream summary separate from the
                # reviewer-authored text so consolidation never destroys the
                # audit source or makes a derived summary look human-authored.
                "raw_comment": raw_comment,
                "raw_important_information": raw_important_information,
                "derived": True,
                "dedupe_key": _feedback_dedupe_key(signal, row),
                "target_agent_ids": targets,
                "stage_scope": scoped_stages,
                "route_scores": route_scores,
                "route_reason": route_reason,
                "memory_processor": self.agent_id,
                "learning_status": "processed",
                # ``processed`` only describes deterministic compression and
                # routing.  It must not be mistaken for a validated/effective
                # long-term lesson.
                "effect_status": effect_status,
                "memory_status": memory_status,
                "taxonomy": _clean_list(
                    row.get("taxonomy") or _infer_feedback_taxonomy(signal),
                    limit=6,
                    item_limit=80,
                ),
                "severity": _infer_feedback_severity(row),
                "confidence": _infer_feedback_confidence(row),
                "utility_ema": round(
                    max(-1.0, min(1.0, _safe_float(row.get("utility_ema")))),
                    6,
                ),
                "ttl_days": max(
                    1,
                    min(
                        3650,
                        _safe_int(row.get("ttl_days"), DEFAULT_MEMORY_TTL_DAYS),
                    ),
                ),
                "processed_at": _now(),
            }
        )
        return row


_memory_agent = ExpertFeedbackMemoryAgent()


def process_feedback_memory(
    feedback: Mapping[str, Any],
    *,
    _trusted_status_token: object | None = None,
) -> dict[str, Any]:
    return _memory_agent.process(
        feedback,
        _trusted_status_token=_trusted_status_token,
    )


def _read_json(path: Path, fallback: Any) -> Any:
    try:
        if path.is_symlink() or not path.is_file():
            return fallback
        value = json.loads(path.read_text(encoding="utf-8"))
        return value
    except (OSError, ValueError, TypeError):
        return fallback


def _safe_storage_file(
    root: Path,
    filename: str,
    *,
    create_root: bool,
) -> Path | None:
    """Return a direct, non-symlinked child of a trusted storage root."""

    root_path = Path(root).expanduser()
    try:
        if root_path.is_symlink():
            return None
        if create_root:
            root_path.mkdir(parents=True, exist_ok=True)
        if not root_path.is_dir():
            return None
        resolved_root = root_path.resolve(strict=True)
        path = resolved_root / filename
        if path.is_symlink():
            return None
        resolved_path = path.resolve(strict=False)
        if resolved_path.parent != resolved_root:
            return None
        if path.exists() and not path.is_file():
            return None
        return path
    except OSError:
        return None


def _knowledge_root(output_root: Path, *, create: bool) -> Path | None:
    """Resolve the fixed sibling knowledge directory without following links."""

    try:
        output = Path(output_root).expanduser().resolve(strict=False)
        parent = output.parent
        knowledge = parent / "knowledge"
        if knowledge.is_symlink():
            return None
        if create:
            knowledge.mkdir(parents=True, exist_ok=True)
        if not knowledge.is_dir():
            return None
        resolved = knowledge.resolve(strict=True)
        if resolved.parent != parent:
            return None
        return resolved
    except OSError:
        return None


def _atomic_write(path: Path, value: Any, *, root: Path) -> None:
    """Atomically replace one direct child without following a leaf symlink."""

    safe_path = _safe_storage_file(root, path.name, create_root=True)
    if safe_path is None or safe_path != path:
        raise ValueError("feedback storage path is unsafe")
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # Recheck immediately before replacement. If a leaf link appeared in
        # the meantime, abort instead of silently replacing an unsafe path.
        if path.is_symlink():
            raise ValueError("feedback storage path is unsafe")
        temporary.replace(path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def run_feedback_path(run_root: Path) -> Path:
    return Path(run_root) / RUN_FEEDBACK_FILENAME


def knowledge_feedback_path(output_root: Path) -> Path:
    return Path(output_root).resolve().parent / "knowledge" / KNOWLEDGE_FEEDBACK_FILENAME


def load_run_feedback(run_root: Path | None) -> list[dict[str, Any]]:
    if run_root is None:
        return []
    path = _safe_storage_file(
        Path(run_root), RUN_FEEDBACK_FILENAME, create_root=False
    )
    if path is None:
        return []
    value = _read_json(path, [])
    return [dict(item) for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def load_feedback_index(output_root: Path) -> list[dict[str, Any]]:
    """Load the full cross-task feedback index from a bounded regular file."""

    root = _knowledge_root(Path(output_root), create=False)
    if root is None:
        return []
    path = _safe_storage_file(
        root, KNOWLEDGE_FEEDBACK_FILENAME, create_root=False
    )
    if path is None:
        return []
    value = _read_json(path, [])
    return (
        [dict(item) for item in value if isinstance(item, Mapping)]
        if isinstance(value, list)
        else []
    )


def normalize_feedback(
    *,
    run_id: str,
    capability_id: str,
    capability_name: str,
    comment: str,
    hypothesis_id: str = "",
    important_information: str = "",
    verdict: str = "needs_revision",
    rating: int | None = None,
    dimensions: Any = None,
    target_agent_ids: Any = None,
    reviewer_name: str = "",
    reviewer_role: str = "expert",
    profile_id: str = "",
    tenant_id: str = "",
    workspace_id: str = "",
    project_id: str = "",
    route: str = "",
    stage_scope: Any = None,
    severity: str = "",
    confidence: float | None = None,
    model_dimension_scores: Any = None,
    expert_dimension_scores: Any = None,
) -> dict[str, Any]:
    verdict = verdict if verdict in {"approved", "needs_revision", "rejected"} else "needs_revision"
    score = None if rating is None else max(1, min(5, int(rating)))
    comment = _clean_text(comment, 4000)
    important = _clean_text(important_information, 2400)
    if not comment and not important:
        raise ValueError("comment or important_information is required")
    def normalized_scores(value: Any) -> dict[str, float]:
        if not isinstance(value, Mapping):
            return {}
        result: dict[str, float] = {}
        for dimension in S5_SCORE_WEIGHTS:
            raw = value.get(dimension)
            if raw in (None, ""):
                continue
            number = _safe_float(raw, float("nan"))
            if number != number or not 0.0 <= number <= 1.0:
                raise ValueError(f"{dimension} score must be between 0 and 1")
            result[dimension] = round(number, 4)
        return result

    model_scores = normalized_scores(model_dimension_scores)
    expert_scores = normalized_scores(expert_dimension_scores)
    if expert_scores and set(expert_scores) != set(S5_SCORE_WEIGHTS):
        raise ValueError("expert_dimension_scores must contain all five S5 dimensions")
    model_weighted_score = (
        round(sum(model_scores.get(key, 0.0) * weight for key, weight in S5_SCORE_WEIGHTS.items()), 4)
        if set(model_scores) == set(S5_SCORE_WEIGHTS)
        else None
    )
    expert_weighted_score = (
        round(sum(expert_scores[key] * weight for key, weight in S5_SCORE_WEIGHTS.items()), 4)
        if expert_scores
        else None
    )
    score_deltas = {
        key: round(expert_scores[key] - model_scores[key], 4)
        for key in S5_SCORE_WEIGHTS
        if key in expert_scores and key in model_scores
    }
    scoring_signal = ""
    if expert_scores:
        labels = {
            "innovation": "创新性",
            "demand": "需求性",
            "feasibility": "科学可行性",
            "effectiveness": "效能性",
            "development": "发展性",
        }
        parts = [f"{labels[key]}{round(expert_scores[key] * 100)}分" for key in S5_SCORE_WEIGHTS]
        scoring_signal = f"专家S5评分：{'、'.join(parts)}；综合{round((expert_weighted_score or 0.0) * 100)}分"
        if model_weighted_score is not None:
            scoring_signal += f"；较当前S5综合分变化{round((expert_weighted_score - model_weighted_score) * 100):+d}分"
        if score is None:
            score = max(1, min(5, round((expert_weighted_score or 0.0) * 5)))
    learning_signal = _curate_learning_signal(
        "；".join(value for value in (comment, important, scoring_signal) if value),
        capability_name,
    )
    # The compact signal is the default downstream handoff.  Keep the longer
    # explicit field for compatibility with older API clients that supplied it.
    important = important or learning_signal
    normalized_targets = _normalize_agent_ids(target_agent_ids)
    normalized_scope = _normalize_agent_ids(stage_scope)
    row = {
        "feedback_id": f"feedback-{uuid4()}",
        "run_id": _clean_text(run_id, 128),
        "capability_id": _clean_text(capability_id, 160),
        "hypothesis_id": _clean_text(hypothesis_id, 160),
        "capability_name": _clean_text(capability_name, 300),
        "comment": comment,
        "important_information": important,
        "learning_signal": learning_signal,
        "verdict": verdict,
        "rating": score,
        "score_schema": "s5_five_dimension_v1" if expert_scores else "",
        "score_weights": dict(S5_SCORE_WEIGHTS) if expert_scores else {},
        "model_dimension_scores": model_scores,
        "expert_dimension_scores": expert_scores,
        "score_deltas": score_deltas,
        "model_weighted_score": model_weighted_score,
        "expert_weighted_score": expert_weighted_score,
        "dimensions": _clean_list(dimensions, limit=8),
        "target_agent_ids": normalized_targets,
        "reviewer_name": _clean_text(reviewer_name, 120),
        "reviewer_role": _clean_text(reviewer_role, 80) or "expert",
        "profile_id": _clean_text(profile_id, 120),
        "tenant_id": _clean_text(tenant_id, 120),
        "workspace_id": _clean_text(workspace_id, 120),
        "project_id": _clean_text(project_id, 120),
        "route": _clean_text(route, 120),
        "stage_scope": normalized_scope,
        "taxonomy": _infer_feedback_taxonomy(learning_signal),
        "severity": str(severity or "").strip().lower() or "medium",
        "confidence": (
            None if confidence is None else _safe_float(confidence, 0.0)
        ),
        "effect_status": DEFAULT_EFFECT_STATUS,
        "memory_status": DEFAULT_MEMORY_STATUS,
        "utility_ema": 0.0,
        "ttl_days": DEFAULT_MEMORY_TTL_DAYS,
        "created_at": _now(),
        "learning_status": "queued",
    }
    row["severity"] = _infer_feedback_severity(row)
    row["confidence"] = _infer_feedback_confidence(row)
    return row


def append_feedback(
    *,
    run_root: Path,
    output_root: Path,
    feedback: Mapping[str, Any],
    _trusted_status_token: object | None = None,
) -> dict[str, Any]:
    """Process and persist one feedback item to the run and knowledge index."""

    processed = process_feedback_memory(
        feedback,
        _trusted_status_token=_trusted_status_token,
    )

    with _lock:
        run_path = _safe_storage_file(
            Path(run_root), RUN_FEEDBACK_FILENAME, create_root=True
        )
        knowledge_root = _knowledge_root(Path(output_root), create=True)
        index_path = (
            None
            if knowledge_root is None
            else _safe_storage_file(
                knowledge_root,
                KNOWLEDGE_FEEDBACK_FILENAME,
                create_root=False,
            )
        )
        # Validate both destinations before mutating either one. This keeps a
        # rejected knowledge-index link from producing a misleading partial
        # success in the task-local audit file.
        if run_path is None or knowledge_root is None or index_path is None:
            raise ValueError("feedback storage path is unsafe")
        current_value = _read_json(run_path, [])
        current = (
            [dict(item) for item in current_value if isinstance(item, Mapping)]
            if isinstance(current_value, list)
            else []
        )
        index = load_feedback_index(Path(output_root))
        dedupe_key = str(processed.get("dedupe_key", "")).strip()
        duplicate_of = ""
        if dedupe_key:
            for item in [*index, *current]:
                item_key = str(item.get("dedupe_key", "")).strip()
                if not item_key:
                    item_key = _feedback_dedupe_key(
                        item.get("learning_signal")
                        or item.get("important_information")
                        or item.get("comment"),
                        item,
                    )
                if item_key and item_key == dedupe_key:
                    duplicate_of = str(item.get("feedback_id", "")).strip()
                    if duplicate_of:
                        break
        if duplicate_of:
            processed.update(
                {
                    "learning_status": "deduplicated",
                    "dedupe_status": "duplicate",
                    "duplicate_of": duplicate_of,
                }
            )
        else:
            processed["dedupe_status"] = "canonical"
        current.append(dict(processed))
        _atomic_write(run_path, current, root=run_path.parent)

        # Keep the index bounded and replace accidental duplicate retries by id.
        if not duplicate_of:
            index = [
                item
                for item in index
                if item.get("feedback_id") != processed.get("feedback_id")
            ]
            index.append(dict(processed))
        _atomic_write(index_path, index[-2000:], root=knowledge_root)
    return dict(processed)


def update_feedback_effect_status(
    *,
    output_root: Path,
    feedback_id: str,
    effect_status: str,
    evaluator_id: str = "",
    evaluation_id: str = "",
    reason: str = "",
    utility_delta: float | None = None,
    _trusted_status_token: object | None = None,
) -> dict[str, Any]:
    """Record an evaluator/adjudicator outcome for one feedback item.

    Promotion is intentionally explicit and separate from ingestion.  This
    keeps a submitted review in ``pending_validation`` until a replay,
    adjudication, or other trusted evaluator supplies evidence.  The function
    updates the cross-run index and, when present, the run-local audit copy.
    """

    if _trusted_status_token is not _TRUSTED_FEEDBACK_STATUS_TOKEN:
        raise PermissionError(
            "trusted evaluator authorization is required to update feedback status"
        )
    normalized_status = _normalize_effect_status(effect_status)
    if normalized_status == DEFAULT_EFFECT_STATUS:
        raise ValueError("effect_status must be a terminal validation status")
    evaluator, evaluation = _require_effect_evidence(evaluator_id, evaluation_id)
    feedback_key = str(feedback_id or "").strip()
    if not feedback_key:
        raise ValueError("feedback_id is required")
    with _lock:
        rows = load_feedback_index(Path(output_root))
        target = next(
            (item for item in rows if str(item.get("feedback_id", "")) == feedback_key),
            None,
        )
        if target is None:
            raise KeyError("feedback not found")
        prior_status = _normalize_effect_status(target.get("effect_status"))
        prior_evaluator = _clean_text(target.get("effect_evaluator_id"), 160)
        prior_evaluation = _clean_text(target.get("effect_evaluation_id"), 160)
        same_evidence_retry = (
            prior_status == normalized_status
            and prior_evaluator == evaluator
            and prior_evaluation == evaluation
        )
        # Tombstones are immutable.  A retry of the exact same evidence is
        # idempotent; any attempt to revive the row with a different status or
        # evidence reference is rejected before touching the ledger.
        _guard_effect_transition(
            prior_status,
            normalized_status,
            prior_evaluator_id=prior_evaluator,
            prior_evaluation_id=prior_evaluation,
            next_evaluator_id=evaluator,
            next_evaluation_id=evaluation,
        )
        if same_evidence_retry:
            return dict(target)
        prior_utility = _safe_float(target.get("utility_ema"), 0.0)
        if utility_delta is not None:
            delta = max(-1.0, min(1.0, _safe_float(utility_delta)))
            target["utility_ema"] = round(prior_utility * 0.8 + delta * 0.2, 6)
        updated_at = _now()
        clean_reason = _clean_text(reason, 2000)
        target["effect_status"] = normalized_status
        target["memory_status"] = (
            "active"
            if normalized_status == "effective"
            else "validated"
            if normalized_status == "validated"
            else "quarantined"
            if normalized_status in {"ineffective", "inconclusive"}
            else "retired"
        )
        target["effect_evaluator_id"] = evaluator
        target["effect_evaluation_id"] = evaluation
        target["effect_reason"] = clean_reason
        target["effect_evidence"] = {
            "evaluator_id": evaluator,
            "evaluation_id": evaluation,
            "reason": clean_reason,
            "recorded_at": updated_at,
        }
        if utility_delta is not None:
            target["effect_evidence"]["utility_delta"] = max(
                -1.0, min(1.0, _safe_float(utility_delta))
            )
        history = target.get("effect_history")
        if not isinstance(history, list):
            history = []
        history.append(
            {
                "from_status": prior_status,
                "to_status": normalized_status,
                "evaluator_id": evaluator,
                "evaluation_id": evaluation,
                "reason": clean_reason,
                "recorded_at": updated_at,
            }
        )
        target["effect_history"] = history[-32:]
        target["effect_updated_at"] = updated_at
        knowledge_root = _knowledge_root(Path(output_root), create=False)
        if knowledge_root is None:
            raise ValueError("feedback storage path is unsafe")
        index_path = _safe_storage_file(
            knowledge_root, KNOWLEDGE_FEEDBACK_FILENAME, create_root=False
        )
        if index_path is None:
            raise ValueError("feedback storage path is unsafe")
        _atomic_write(index_path, rows, root=knowledge_root)

        # Keep the task-local audit view synchronized when the conventional
        # output-root/run-id layout is in use.  A missing or legacy run file is
        # not allowed to block the canonical index update.
        run_id = str(target.get("run_id", "")).strip()
        if run_id:
            run_path = _safe_storage_file(
                Path(output_root) / run_id,
                RUN_FEEDBACK_FILENAME,
                create_root=False,
            )
            if run_path is not None:
                local_rows = _read_json(run_path, [])
                if isinstance(local_rows, list):
                    changed = False
                    for item in local_rows:
                        if isinstance(item, Mapping) and str(item.get("feedback_id", "")) == feedback_key:
                            item.update(
                                {
                                    "effect_status": target["effect_status"],
                                    "memory_status": target["memory_status"],
                                    "utility_ema": target["utility_ema"],
                                    "effect_evaluator_id": target["effect_evaluator_id"],
                                    "effect_evaluation_id": target["effect_evaluation_id"],
                                    "effect_reason": target["effect_reason"],
                                    "effect_evidence": target.get("effect_evidence", {}),
                                    "effect_history": target.get("effect_history", []),
                                    "effect_updated_at": target["effect_updated_at"],
                                }
                            )
                            changed = True
                    if changed:
                        _atomic_write(run_path, local_rows, root=run_path.parent)
        return dict(target)


def load_feedback_knowledge(
    output_root: Path,
    topic: str,
    *,
    limit: int = MAX_MEMORY_ITEMS,
    agent_id: str | None = None,
    profile_id: str | None = None,
    tenant_id: str | None = None,
    workspace_id: str | None = None,
    project_id: str | None = None,
    route: str | None = None,
    stage_scope: Any = None,
    include_unvalidated: bool = False,
) -> list[dict[str, Any]]:
    """Return bounded review signals eligible for future S1-S6 turns.

    New feedback is deliberately quarantined from production retrieval until
    an offline replay or an explicit expert adjudication marks it validated.
    ``include_unvalidated`` is intended for developer/auditor inspection only;
    production callers should leave it false.
    """

    rows = load_feedback_index(Path(output_root))
    topic_tokens = {
        token
        for token in re.findall(r"[\w\u4e00-\u9fff]{2,}", str(topic).lower())
        if token.strip()
    }
    topic_taxonomy = set(_infer_feedback_taxonomy(str(topic)))
    # ``general_quality`` is a fallback label, not evidence that two
    # unrelated topics are semantically compatible.  It must never by itself
    # make every generic lesson eligible for retrieval.
    specific_topic_taxonomy = topic_taxonomy - {"general_quality"}

    def score(item: Mapping[str, Any]) -> tuple[float, str]:
        text = " ".join(
            str(item.get(key, ""))
            for key in (
                "capability_name",
                "comment",
                "important_information",
                "learning_signal",
                "dimensions",
                "taxonomy",
                "route",
            )
        ).lower()
        overlap = sum(1 for token in topic_tokens if token in text)
        route_fit = bool(route and str(item.get("route", "")).strip() == route)
        expected_stages = set(_normalize_agent_ids(stage_scope))
        item_stages = set(_normalize_agent_ids(item.get("stage_scope")))
        stage_fit = bool(expected_stages and expected_stages.intersection(item_stages))
        taxonomy_fit = bool(specific_topic_taxonomy.intersection(
            set(_clean_list(item.get("taxonomy"), limit=8, item_limit=80))
        ))
        confidence = max(0.0, min(1.0, _safe_float(item.get("confidence"), 0.0)))
        utility = max(-1.0, min(1.0, _safe_float(item.get("utility_ema"), 0.0)))
        utility_factor = (utility + 1.0) / 2.0
        # Recency is deliberately a small tie-breaker.  It cannot compensate
        # for a missing topical/scope match, but it helps fresh validated
        # lessons win over stale lessons with the same lexical overlap.
        recency = 0.0
        created_at = str(item.get("created_at", "")).strip()
        if created_at:
            try:
                created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                age_days = max(0.0, (datetime.now(timezone.utc) - created).total_seconds() / 86400.0)
                recency = 1.0 / (1.0 + age_days / 90.0)
            except ValueError:
                pass
        value = (
            overlap * 4.0
            + (3.0 if route_fit else 0.0)
            + (2.0 if stage_fit else 0.0)
            + (1.5 if taxonomy_fit else 0.0)
            + confidence
            + utility_factor
            + recency
        )
        return value, created_at

    relevant = [dict(item) for item in rows if isinstance(item, Mapping)]
    if not include_unvalidated:
        relevant = [
            item
            for item in relevant
            if _normalize_effect_status(item.get("effect_status"))
            in {"validated", "effective"}
            and _normalize_memory_status(item.get("memory_status"))
            in {"validated", "active"}
            and not _is_expired(item)
        ]

    def _matches_scope(item: Mapping[str, Any], key: str, expected: str | None) -> bool:
        actual = str(item.get(key, "")).strip()
        if not expected:
            # An unscoped caller may consume only legacy/global entries.  It
            # must never become a wildcard over another tenant, workspace,
            # project, profile, or business route.
            return not actual
        # Empty scope is legacy/unknown and must not cross an explicitly scoped
        # tenant/workspace/profile boundary.
        return actual == expected

    # A run may restrict retrieval to one or more S1–S6 stages.  Unlike the
    # scalar tenant/workspace fields, stage scope is an overlap relation: a
    # lesson authored for S4/S6 is eligible for an S6-only run, but an item
    # with no explicit stage scope is treated as unknown and is not allowed to
    # cross an explicitly scoped boundary.
    expected_stage_scope = {
        stage
        for stage in _normalize_agent_ids(stage_scope)
        if stage in ALL_AGENT_IDS
    }

    def _matches_stage_scope(item: Mapping[str, Any]) -> bool:
        if not expected_stage_scope:
            return True
        actual_stage_scope = {
            stage
            for stage in _normalize_agent_ids(
                item.get("stage_scope") or item.get("target_agent_ids")
            )
            if stage in ALL_AGENT_IDS
        }
        return bool(actual_stage_scope & expected_stage_scope)

    relevant = [
        item
        for item in relevant
        if _matches_scope(item, "profile_id", profile_id)
        and _matches_scope(item, "tenant_id", tenant_id)
        and _matches_scope(item, "workspace_id", workspace_id)
        and _matches_scope(item, "project_id", project_id)
        and _matches_scope(item, "route", route)
        and _matches_stage_scope(item)
    ]
    if agent_id:
        agent_key = str(agent_id).upper().strip()
        relevant = [
            item
            for item in relevant
            if agent_key in _clean_list(item.get("target_agent_ids"), limit=6, item_limit=32)
            or not item.get("target_agent_ids")
        ]
    # A scope-valid but completely unrelated lesson is still dangerous: it
    # consumes context and can bias a stage toward the wrong failure mode.
    # Require at least one topical token or an explicit route/stage/taxonomy
    # fit.  This also makes retrieval fail-closed for an empty/unknown query.
    def has_relevance(item: Mapping[str, Any]) -> bool:
        text = " ".join(
            str(item.get(key, ""))
            for key in (
                "capability_name",
                "comment",
                "important_information",
                "learning_signal",
                "dimensions",
                "taxonomy",
                "route",
            )
        ).lower()
        overlap = any(token in text for token in topic_tokens)
        route_fit = bool(route and str(item.get("route", "")).strip() == route)
        expected_stages = set(_normalize_agent_ids(stage_scope))
        item_stages = set(_normalize_agent_ids(item.get("stage_scope")))
        stage_fit = bool(expected_stages and expected_stages.intersection(item_stages))
        taxonomy_fit = bool(specific_topic_taxonomy.intersection(
            set(_clean_list(item.get("taxonomy"), limit=8, item_limit=80))
        ))
        return overlap or route_fit or stage_fit or taxonomy_fit

    relevant = [item for item in relevant if has_relevance(item)]
    relevant.sort(key=score, reverse=True)
    result: list[dict[str, Any]] = []
    seen_signals: set[str] = set()
    for item in relevant:
        learning_signal = _curate_learning_signal(
            item.get("learning_signal")
            or item.get("important_information")
            or item.get("comment"),
            item.get("capability_name"),
        )
        signal_key = _feedback_dedupe_key(learning_signal, item)
        if not signal_key or signal_key in seen_signals:
            continue
        seen_signals.add(signal_key)
        result.append(
            {
                "feedback_id": str(item.get("feedback_id", "")),
                "hypothesis_id": str(item.get("hypothesis_id", "")),
                "capability_name": _clean_text(item.get("capability_name"), 220),
                # Future Agents receive only the bounded, deterministic
                # learning signal; the full reviewer text stays in the task
                # audit file and developer-facing API.
                "comment": learning_signal,
                "important_information": learning_signal,
                "learning_signal": learning_signal,
                "verdict": str(item.get("verdict", "needs_revision")),
                "rating": item.get("rating"),
                "score_schema": str(item.get("score_schema", "")),
                "score_weights": dict(item.get("score_weights", {}))
                if isinstance(item.get("score_weights"), Mapping)
                else {},
                "model_dimension_scores": dict(item.get("model_dimension_scores", {}))
                if isinstance(item.get("model_dimension_scores"), Mapping)
                else {},
                "expert_dimension_scores": dict(item.get("expert_dimension_scores", {}))
                if isinstance(item.get("expert_dimension_scores"), Mapping)
                else {},
                "score_deltas": dict(item.get("score_deltas", {}))
                if isinstance(item.get("score_deltas"), Mapping)
                else {},
                "model_weighted_score": item.get("model_weighted_score"),
                "expert_weighted_score": item.get("expert_weighted_score"),
                "dimensions": _clean_list(item.get("dimensions"), limit=6),
                "taxonomy": _clean_list(item.get("taxonomy"), limit=6, item_limit=80),
                "severity": str(item.get("severity", "medium")),
                "confidence": _safe_float(item.get("confidence")),
                "effect_status": _normalize_effect_status(item.get("effect_status")),
                "memory_status": _normalize_memory_status(item.get("memory_status")),
                "utility_ema": _safe_float(item.get("utility_ema")),
                "ttl_days": max(1, _safe_int(item.get("ttl_days"), DEFAULT_MEMORY_TTL_DAYS)),
                "target_agent_ids": _clean_list(
                    item.get("target_agent_ids") or ["S6", "S4"],
                    limit=6,
                    item_limit=32,
                ),
                "stage_scope": _normalize_agent_ids(item.get("stage_scope")),
                "profile_id": str(item.get("profile_id", "")),
                "tenant_id": str(item.get("tenant_id", "")),
                "workspace_id": str(item.get("workspace_id", "")),
                "project_id": str(item.get("project_id", "")),
                "route": str(item.get("route", "")),
                "created_at": str(item.get("created_at", "")),
                "source_run_id": str(item.get("run_id", "")),
            }
        )
        if len(result) >= max(1, min(int(limit), MAX_MEMORY_ITEMS)):
            break
    return result


__all__ = [
    "append_feedback",
    "ALL_AGENT_IDS",
    "DEFAULT_EFFECT_STATUS",
    "DEFAULT_MEMORY_STATUS",
    "EFFECT_STATUSES",
    "ExpertFeedbackMemoryAgent",
    "load_feedback_index",
    "load_feedback_knowledge",
    "load_run_feedback",
    "normalize_feedback",
    "process_feedback_memory",
    "run_feedback_path",
    "update_feedback_effect_status",
]
