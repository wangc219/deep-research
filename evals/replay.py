"""Deterministic, offline replay evaluation for text-only evolution.

The production runner is deliberately not imported here.  A replay adapter
materialises one :class:`ReplayObservation` per ``(query_id, arm)`` and this
module performs the bookkeeping that is easy to get subtly wrong:

* the fixed pilot fixture is validated before a comparison starts;
* Prompt-only, Memory-only and Both arms are evaluated on the same Query set;
* quality deltas use paired Query-level bootstrap intervals;
* hard failures, missing pairs, cost and latency regressions are fail-closed;
* all paths written to a manifest are portable project-relative paths.

``neither`` is an optional fourth arm.  It is useful when a champion result is
available in the same replay, but it is not required for the three-arm
attribution experiment described in the evolution design documents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
import json
import random
import statistics

from .models import EvalQuery, read_jsonl


REPLAY_SCHEMA_VERSION = "1.0"
REPLAY_ARMS = ("prompt_only", "memory_only", "both")
OPTIONAL_REPLAY_ARMS = ("neither",)
SUPPORTED_REPLAY_ARMS = frozenset((*REPLAY_ARMS, *OPTIONAL_REPLAY_ARMS))
REPLAY_ARM_CONFIG = {
    "prompt_only": {"candidate_prompt": True, "candidate_memory": False},
    "memory_only": {"candidate_prompt": False, "candidate_memory": True},
    "both": {"candidate_prompt": True, "candidate_memory": True},
    "neither": {"candidate_prompt": False, "candidate_memory": False},
}
_ARM_ALIASES = {
    "prompt": "prompt_only",
    "prompt-only": "prompt_only",
    "prompt_only": "prompt_only",
    "promptonly": "prompt_only",
    "memory": "memory_only",
    "memory-only": "memory_only",
    "memory_only": "memory_only",
    "memoryonly": "memory_only",
    "both": "both",
    "neither": "neither",
    "control": "neither",
}
DEFAULT_REPLAY_SEED = "evolution-pilot-v1"
DEFAULT_BOOTSTRAP_SAMPLES = 2_000
DEFAULT_MIN_QUALITY_DELTA = 0.03
DEFAULT_MAX_HARD_FAILURE_RATE = 0.0
DEFAULT_MAX_COST_INCREASE = 0.15
DEFAULT_MAX_LATENCY_INCREASE = 0.15
DEFAULT_MAX_NON_TARGET_REGRESSION = 0.02


def _as_float(value: Any, *, name: str, minimum: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not isfinite(result):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and result < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return result


def _portable_path(path: str | Path, *, project_root: str | Path | None = None) -> str:
    """Return a path suitable for a moved checkout's manifest.

    Runtime callers may pass absolute paths (for example, a temporary fixture
    in a test).  Persisting those paths would make the manifest non-portable,
    so paths inside ``project_root`` are relativised and external paths are
    represented by their filename only.  The content hash remains the stable
    identity for external files.
    """

    raw = Path(path)
    if not raw.is_absolute():
        return raw.as_posix()
    root = Path(project_root or Path.cwd()).resolve()
    resolved = raw.resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return resolved.name


def _sha256_file(path: str | Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _normalise_sha256(value: Any, *, field: str) -> str:
    """Return a canonical ``sha256:<hex>`` value for manifest identities.

    Replay manifests are persisted and may be handed to the production
    approval ledger.  Keep the sidecar strict about cryptographic identities,
    while leaving the historical opaque ``bundle_id`` field untouched for
    compatibility with older, non-governed replay callers.
    """

    text = str(value or "").strip().lower()
    if text.startswith("sha256:"):
        digest = text[7:]
    else:
        digest = text
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError(f"{field} must be a SHA-256 hash")
    return f"sha256:{digest}"


def _normalise_prompt_hashes(value: Any, *, field: str = "candidate_prompt_hashes") -> dict[str, str]:
    """Normalize a stage-to-prompt-hash map carried by a replay manifest."""

    if value in (None, "", {}):
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    result: dict[str, str] = {}
    for raw_stage, raw_hash in value.items():
        stage = str(raw_stage or "").strip()
        if not stage:
            raise ValueError(f"{field} contains an empty stage")
        result[stage] = _normalise_sha256(raw_hash, field=f"{field}.{stage}")
    return result


def _normalise_string_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise ValueError("list field must be a string or a sequence")
    return tuple(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _normalise_arm(value: Any) -> str:
    raw = str(value or "").strip().lower().replace(" ", "_")
    arm = _ARM_ALIASES.get(raw, raw)
    if arm not in SUPPORTED_REPLAY_ARMS:
        raise ValueError(f"unsupported replay arm: {value}")
    return arm


def _required_arm_list(value: Sequence[str], *, field: str) -> tuple[str, ...]:
    """Normalize an arm list and require the complete three-arm experiment.

    The replay gate is intended to attribute Prompt and Memory changes, so a
    caller must collect ``prompt_only``, ``memory_only`` and ``both``.  The
    optional ``neither`` control may be added, but it cannot replace one of
    the required arms.  Enforcing this at the sidecar boundary prevents an
    accidentally narrowed ``expected_arms`` list from turning an incomplete
    experiment into a passing gate.
    """

    if isinstance(value, str) or not isinstance(value, (list, tuple, set, frozenset)):
        raise ValueError(f"{field} must be a sequence of replay arms")
    normalized = tuple(dict.fromkeys(_normalise_arm(arm) for arm in value))
    if not normalized:
        raise ValueError(
            f"{field} must include prompt_only, memory_only and both; list is empty"
        )
    missing = sorted(set(REPLAY_ARMS) - set(normalized))
    if missing:
        raise ValueError(
            f"{field} must include prompt_only, memory_only and both; missing: {missing}"
        )
    return normalized


def validate_replay_fixture(
    rows_or_path: str | Path | Iterable[Mapping[str, Any]],
    *,
    expected_seed: str | None = DEFAULT_REPLAY_SEED,
    expected_count: int | None = None,
    require_pilot_split: bool = True,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """Validate the immutable Query fixture and return its snapshot metadata.

    The public fixture intentionally contains the six fields required by
    :class:`EvalQuery` plus ``target_stages``, ``residual_tags``,
    ``target_metrics`` and ``seed``.  Unknown extra fields are allowed so an
    evaluator can attach non-public metadata in an admin copy.
    """

    path: Path | None = None
    if isinstance(rows_or_path, (str, Path)):
        path = Path(rows_or_path)
        raw_rows = read_jsonl(path)
    else:
        raw_rows = [dict(row) for row in rows_or_path]
    if not raw_rows:
        raise ValueError("replay fixture must contain at least one Query")
    if expected_count is not None and len(raw_rows) != int(expected_count):
        raise ValueError(f"expected {expected_count} fixture rows; found {len(raw_rows)}")

    query_ids: set[str] = set()
    query_texts: set[str] = set()
    stages: set[str] = set()
    difficulties: set[str] = set()
    seeds: set[str] = set()
    for row in raw_rows:
        payload = dict(row)
        required = {"query_id", "query", "region", "domain", "difficulty", "split"}
        missing = sorted(required - set(payload))
        if missing:
            raise ValueError(f"fixture row is missing fields: {missing}")
        query = EvalQuery.from_dict({key: payload[key] for key in required})
        if query.query_id in query_ids:
            raise ValueError(f"duplicate query_id found: {query.query_id}")
        if query.query.strip() in query_texts:
            raise ValueError(f"duplicate query text found: {query.query_id}")
        query_ids.add(query.query_id)
        query_texts.add(query.query.strip())
        difficulties.add(query.difficulty)
        if require_pilot_split and query.split != "pilot":
            raise ValueError(f"replay fixture must use pilot split: {query.query_id}")

        row_stages = _normalise_string_list(payload.get("target_stages"))
        row_tags = _normalise_string_list(payload.get("residual_tags"))
        row_metrics = _normalise_string_list(payload.get("target_metrics"))
        if not row_stages or not row_tags or not row_metrics:
            raise ValueError(
                f"{query.query_id} requires target_stages, residual_tags and target_metrics"
            )
        invalid_stages = sorted(set(row_stages) - {f"S{index}" for index in range(1, 7)})
        if invalid_stages:
            raise ValueError(f"{query.query_id} contains invalid stages: {invalid_stages}")
        stages.update(row_stages)
        seed = str(payload.get("seed", "")).strip()
        if not seed:
            raise ValueError(f"{query.query_id} is missing deterministic seed")
        seeds.add(seed)

    if expected_seed is not None and seeds != {str(expected_seed)}:
        raise ValueError(
            f"fixture seed mismatch: expected {expected_seed!r}, found {sorted(seeds)!r}"
        )
    snapshot_payload = [
        {key: row[key] for key in sorted(row)}
        for row in raw_rows
    ]
    return {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "valid": True,
        "query_count": len(raw_rows),
        "query_ids": sorted(query_ids),
        "difficulty": sorted(difficulties),
        "stages": sorted(stages),
        "seeds": sorted(seeds),
        "seed": sorted(seeds)[0] if len(seeds) == 1 else "",
        "fixture_sha256": _canonical_hash(snapshot_payload)
        if path is None
        else _sha256_file(path),
        "fixture_path": _portable_path(path, project_root=project_root)
        if path is not None
        else "<in-memory>",
    }


def load_replay_fixture(
    path: str | Path,
    *,
    expected_seed: str | None = DEFAULT_REPLAY_SEED,
    expected_count: int | None = None,
    require_pilot_split: bool = True,
    project_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Load and validate a replay fixture, returning independent row copies."""

    rows = read_jsonl(path)
    validate_replay_fixture(
        rows,
        expected_seed=expected_seed,
        expected_count=expected_count,
        require_pilot_split=require_pilot_split,
        project_root=project_root,
    )
    return [dict(row) for row in rows]


def _normalise_hard_failures(value: Any, count: Any = None) -> tuple[str, ...]:
    if isinstance(value, bool):
        value = ("hard_failure",) if value else ()
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        count = value if count is None else count
        value = ()
    failures = list(_normalise_string_list(value))
    if count is not None:
        numeric = int(_as_float(count, name="hard_failure_count", minimum=0))
        if numeric > len(failures):
            failures.extend(f"hard_failure_{index + 1}" for index in range(len(failures), numeric))
    return tuple(dict.fromkeys(failures))


@dataclass(frozen=True)
class ReplayObservation:
    """One completed (or failed) arm execution for one fixed Query."""

    eval_id: str
    query_id: str
    arm: str
    quality_score: float
    hard_failures: tuple[str, ...] = ()
    token_count: float = 0.0
    estimated_cost: float = 0.0
    duration_seconds: float = 0.0
    non_target_regression: float = 0.0
    metric_scores: Mapping[str, float] = field(default_factory=dict)
    status: str = "completed"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.eval_id).strip():
            raise ValueError("eval_id is required")
        if not str(self.query_id).strip():
            raise ValueError("query_id is required")
        object.__setattr__(self, "arm", _normalise_arm(self.arm))
        status = str(self.status or "completed").strip().lower() or "completed"
        if status not in {"completed", "failed", "skipped"}:
            raise ValueError(f"unsupported replay status: {status}")
        object.__setattr__(self, "status", status)
        # ``from_dict`` already adds a synthetic failure for non-completed
        # rows, but callers can also construct ReplayObservation directly.
        # Normalize that path as well so a failed/skipped execution can never
        # look like a clean paired case merely because its failure list was
        # omitted.
        failures = _normalise_hard_failures(self.hard_failures)
        if status != "completed" and not failures:
            failures = (f"run_{status}",)
        object.__setattr__(self, "hard_failures", failures)
        # Normalize numeric fields on direct construction as well as through
        # ``from_dict``.  API/CLI adapters frequently deserialize JSON values
        # as strings; validating a string without writing back the converted
        # float leaves a frozen observation that later fails in aggregation
        # (for example, ``statistics.fmean(["0.7"])``).  Keeping the
        # dataclass invariant numeric makes direct and wire construction
        # behave identically.
        quality = _as_float(self.quality_score, name="quality_score")
        if not 0.0 <= quality <= 1.0:
            raise ValueError("quality_score must be between 0 and 1")
        object.__setattr__(self, "quality_score", quality)
        for name, value in (
            ("token_count", self.token_count),
            ("estimated_cost", self.estimated_cost),
            ("duration_seconds", self.duration_seconds),
            ("non_target_regression", self.non_target_regression),
        ):
            object.__setattr__(
                self,
                name,
                _as_float(value, name=name, minimum=0.0),
            )
        metric_scores = {
            key: _as_float(value, name=f"metric_scores.{key}")
            for key, value in dict(self.metric_scores).items()
        }
        for key, metric in metric_scores.items():
            if not 0.0 <= metric <= 1.0:
                raise ValueError(f"metric_scores.{key} must be between 0 and 1")
        object.__setattr__(self, "metric_scores", metric_scores)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ReplayObservation":
        row = dict(payload)
        status = str(row.get("status", "completed")).strip() or "completed"
        quality = row.get("quality_score", row.get("quality", row.get("score")))
        if quality is None:
            metrics = row.get("metric_scores", row.get("metrics", {}))
            values: list[float] = []
            for value in dict(metrics or {}).values():
                try:
                    values.append(float(value))
                except (TypeError, ValueError):
                    continue
            if values:
                quality = statistics.fmean(values)
            elif status != "completed":
                quality = 0.0
            else:
                raise ValueError("quality_score or numeric metric_scores is required")
        arm = _normalise_arm(row.get("arm", row.get("variant", row.get("ablation", ""))))
        failures = _normalise_hard_failures(
            row.get("hard_failures", row.get("failures", [])),
            row.get("hard_failure_count"),
        )
        if status != "completed" and not failures:
            failures = (f"run_{status}",)
        return cls(
            eval_id=str(row.get("eval_id", row.get("evaluation_id", "replay"))),
            query_id=str(row.get("query_id", "")),
            arm=arm,
            quality_score=float(quality),
            hard_failures=failures,
            token_count=float(row.get("token_count", row.get("tokens", row.get("total_tokens", 0.0))) or 0.0),
            estimated_cost=float(row.get("estimated_cost", row.get("cost", 0.0)) or 0.0),
            duration_seconds=float(row.get("duration_seconds", row.get("latency_seconds", row.get("latency", 0.0))) or 0.0),
            non_target_regression=float(row.get("non_target_regression", row.get("regression", 0.0)) or 0.0),
            metric_scores=dict(row.get("metric_scores", row.get("metrics", {})) or {}),
            status=status,
            metadata=dict(row.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "eval_id": self.eval_id,
            "query_id": self.query_id,
            "arm": self.arm,
            "quality_score": round(float(self.quality_score), 8),
            "hard_failures": list(self.hard_failures),
            "hard_failure_count": len(self.hard_failures),
            "token_count": round(float(self.token_count), 4),
            "estimated_cost": round(float(self.estimated_cost), 8),
            "duration_seconds": round(float(self.duration_seconds), 6),
            "non_target_regression": round(float(self.non_target_regression), 8),
            "metric_scores": dict(self.metric_scores),
            "status": self.status,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ReplayPolicy:
    """Fail-closed promotion thresholds for a replay comparison."""

    min_quality_delta: float = DEFAULT_MIN_QUALITY_DELTA
    max_hard_failure_rate: float = DEFAULT_MAX_HARD_FAILURE_RATE
    max_cost_increase: float = DEFAULT_MAX_COST_INCREASE
    max_latency_increase: float = DEFAULT_MAX_LATENCY_INCREASE
    max_non_target_regression: float = DEFAULT_MAX_NON_TARGET_REGRESSION
    min_complete_cases: int = 1

    def __post_init__(self) -> None:
        for name in (
            "min_quality_delta",
            "max_hard_failure_rate",
            "max_cost_increase",
            "max_latency_increase",
            "max_non_target_regression",
        ):
            value = _as_float(getattr(self, name), name=name)
            if value < 0.0:
                raise ValueError(f"{name} must be >= 0")
        if int(self.min_complete_cases) < 1:
            raise ValueError("min_complete_cases must be >= 1")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any] | None) -> "ReplayPolicy":
        if not payload:
            return cls()
        names = {
            "min_quality_delta",
            "max_hard_failure_rate",
            "max_cost_increase",
            "max_latency_increase",
            "max_non_target_regression",
            "min_complete_cases",
        }
        return cls(**{key: payload[key] for key in names if key in payload})

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_quality_delta": self.min_quality_delta,
            "max_hard_failure_rate": self.max_hard_failure_rate,
            "max_cost_increase": self.max_cost_increase,
            "max_latency_increase": self.max_latency_increase,
            "max_non_target_regression": self.max_non_target_regression,
            "min_complete_cases": self.min_complete_cases,
        }


def bootstrap_ci(
    values: Sequence[float],
    *,
    samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
    seed: int = 20260913,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Return a deterministic percentile bootstrap interval for a mean."""

    numbers = [float(value) for value in values]
    if not numbers:
        return (0.0, 0.0)
    if len(numbers) == 1:
        value = numbers[0]
        return (value, value)
    sample_count = max(100, int(samples))
    confidence = min(0.999, max(0.5, float(confidence)))
    rng = random.Random(int(seed))
    means = sorted(
        statistics.fmean(rng.choices(numbers, k=len(numbers)))
        for _ in range(sample_count)
    )
    alpha = (1.0 - confidence) / 2.0
    lower_index = max(0, min(len(means) - 1, int(alpha * len(means))))
    upper_index = max(0, min(len(means) - 1, int((1.0 - alpha) * len(means))))
    return means[lower_index], means[upper_index]


def _percentile(values: Sequence[float], percentile: float) -> float:
    numbers = sorted(float(value) for value in values)
    if not numbers:
        return 0.0
    if len(numbers) == 1:
        return numbers[0]
    index = (len(numbers) - 1) * min(1.0, max(0.0, percentile))
    lower = int(index)
    upper = min(len(numbers) - 1, lower + 1)
    fraction = index - lower
    return numbers[lower] + (numbers[upper] - numbers[lower]) * fraction


def _coerce_observations(
    observations: Iterable[ReplayObservation | Mapping[str, Any]] | str | Path,
) -> list[ReplayObservation]:
    rows = read_jsonl(observations) if isinstance(observations, (str, Path)) else list(observations)
    result: list[ReplayObservation] = []
    for row in rows:
        result.append(row if isinstance(row, ReplayObservation) else ReplayObservation.from_dict(row))
    if not result:
        raise ValueError("replay observations must contain at least one row")
    return result


def _group_observations(
    observations: Sequence[ReplayObservation],
) -> dict[str, dict[str, ReplayObservation]]:
    """Collapse judge/model replicas to one deterministic row per Query/arm."""

    grouped: dict[tuple[str, str], list[ReplayObservation]] = {}
    for observation in observations:
        grouped.setdefault((observation.query_id, observation.arm), []).append(observation)
    result: dict[str, dict[str, ReplayObservation]] = {}
    for (query_id, arm), rows in grouped.items():
        metric_keys = sorted({key for row in rows for key in row.metric_scores})
        metrics = {
            key: statistics.fmean(float(row.metric_scores[key]) for row in rows if key in row.metric_scores)
            for key in metric_keys
        }
        failures = tuple(
            dict.fromkeys(failure for row in rows for failure in row.hard_failures)
        )
        status = "completed" if all(row.status == "completed" for row in rows) else "failed"
        representative = ReplayObservation(
            eval_id=rows[0].eval_id,
            query_id=query_id,
            arm=arm,
            quality_score=statistics.fmean(row.quality_score for row in rows),
            hard_failures=failures,
            token_count=statistics.fmean(row.token_count for row in rows),
            estimated_cost=statistics.fmean(row.estimated_cost for row in rows),
            duration_seconds=statistics.fmean(row.duration_seconds for row in rows),
            non_target_regression=max(row.non_target_regression for row in rows),
            metric_scores=metrics,
            status=status,
            metadata={"replicate_count": len(rows)},
        )
        result.setdefault(query_id, {})[arm] = representative
    return result


def _arm_summary(rows: Sequence[ReplayObservation], *, bootstrap_samples: int, seed: int) -> dict[str, Any]:
    quality = [row.quality_score for row in rows]
    costs = [row.estimated_cost for row in rows]
    latency = [row.duration_seconds for row in rows]
    tokens = [row.token_count for row in rows]
    failures = sum(bool(row.hard_failures) for row in rows)
    metric_keys = sorted({key for row in rows for key in row.metric_scores})
    metric_summary = {
        key: {
            "mean": round(
                statistics.fmean(float(row.metric_scores[key]) for row in rows if key in row.metric_scores),
                6,
            ),
            "count": sum(key in row.metric_scores for row in rows),
        }
        for key in metric_keys
    }
    return {
        "query_count": len(rows),
        "completed_count": sum(row.status == "completed" for row in rows),
        "replicate_count": sum(int(row.metadata.get("replicate_count", 1)) for row in rows),
        "quality_mean": round(statistics.fmean(quality), 6) if quality else 0.0,
        "quality_ci": [round(value, 6) for value in bootstrap_ci(quality, samples=bootstrap_samples, seed=seed)],
        "hard_failure_count": sum(len(row.hard_failures) for row in rows),
        "hard_failure_query_count": failures,
        "hard_failure_rate": round(failures / len(rows), 6) if rows else 0.0,
        "hard_failures": sorted({failure for row in rows for failure in row.hard_failures}),
        "mean_token_count": round(statistics.fmean(tokens), 4) if tokens else 0.0,
        "mean_estimated_cost": round(statistics.fmean(costs), 8) if costs else 0.0,
        "mean_duration_seconds": round(statistics.fmean(latency), 6) if latency else 0.0,
        "p95_duration_seconds": round(_percentile(latency, 0.95), 6),
        "max_non_target_regression": round(max((row.non_target_regression for row in rows), default=0.0), 6),
        "metric_scores": metric_summary,
    }


def _paired_effect(
    grouped: Mapping[str, Mapping[str, ReplayObservation]],
    left_arm: str,
    right_arm: str,
    *,
    samples: int,
    seed: int,
) -> dict[str, Any]:
    query_ids = sorted(
        query_id
        for query_id, arms in grouped.items()
        if left_arm in arms and right_arm in arms
    )
    differences = [
        grouped[query_id][left_arm].quality_score - grouped[query_id][right_arm].quality_score
        for query_id in query_ids
    ]
    lower, upper = bootstrap_ci(differences, samples=samples, seed=seed)
    return {
        "left_arm": left_arm,
        "right_arm": right_arm,
        "paired_query_count": len(query_ids),
        "delta": round(statistics.fmean(differences), 6) if differences else None,
        "ci": [round(lower, 6), round(upper, 6)] if differences else None,
        "query_ids": query_ids,
    }


def _paired_metric_effects(
    grouped: Mapping[str, Mapping[str, ReplayObservation]],
    left_arm: str,
    right_arm: str,
    *,
    samples: int,
    seed: int,
) -> dict[str, Any]:
    """Compute paired effects for every metric present in both arms.

    Missing metric values are excluded per metric, while the top-level quality
    effect remains strict about complete Query/arm pairs.  This makes the
    report useful with gradually instrumented traces without weakening the
    promotion gate's denominator.
    """

    metrics = sorted(
        {
            metric
            for arms in grouped.values()
            for arm in (left_arm, right_arm)
            if arm in arms
            for metric in arms[arm].metric_scores
        }
    )
    result: dict[str, Any] = {}
    for metric in metrics:
        query_ids = sorted(
            query_id
            for query_id, arms in grouped.items()
            if left_arm in arms
            and right_arm in arms
            and metric in arms[left_arm].metric_scores
            and metric in arms[right_arm].metric_scores
        )
        differences = [
            float(grouped[query_id][left_arm].metric_scores[metric])
            - float(grouped[query_id][right_arm].metric_scores[metric])
            for query_id in query_ids
        ]
        lower, upper = bootstrap_ci(differences, samples=samples, seed=seed + len(result))
        result[metric] = {
            "paired_query_count": len(query_ids),
            "delta": round(statistics.fmean(differences), 6) if differences else None,
            "ci": [round(lower, 6), round(upper, 6)] if differences else None,
            "query_ids": query_ids,
        }
    return result


def _relative_change(candidate: float, reference: float) -> float | None:
    if reference == 0.0:
        # A non-zero candidate against a zero-cost/zero-latency reference is
        # an unbounded regression, not an unknown value.  Keeping ``inf`` in
        # the internal comparison lets the gate fail closed while JSON output
        # remains normalised below.
        return 0.0 if candidate == 0.0 else float("inf")
    return (candidate - reference) / abs(reference)


def aggregate_replay(
    observations: Iterable[ReplayObservation | Mapping[str, Any]] | str | Path,
    *,
    fixture: str | Path | Iterable[Mapping[str, Any]] | None = None,
    eval_id: str | None = None,
    expected_arms: Sequence[str] = REPLAY_ARMS,
    # A three-arm experiment has no separate ``neither`` control by default;
    # use Prompt-only as the conservative reference.  Callers that collect a
    # fourth control can explicitly pass ``reference_arm="neither"``.
    reference_arm: str = "prompt_only",
    candidate_arm: str = "both",
    policy: ReplayPolicy | Mapping[str, Any] | None = None,
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
    seed: int = 20260913,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """Aggregate replay rows and apply a fail-closed promotion gate.

    ``fixture`` is optional for callers that already validated Query IDs.  If
    supplied, unknown IDs and missing required arms are surfaced as explicit
    gate reasons instead of silently changing the denominator.
    """

    policy_obj = policy if isinstance(policy, ReplayPolicy) else ReplayPolicy.from_mapping(policy)
    # A promotion comparison is only attributable when all three required
    # Prompt/Memory arms are part of the declared experiment.  Validate this
    # before grouping observations so a narrowed/empty ``expected_arms`` list
    # cannot make the completeness denominator vacuously pass.
    expected = _required_arm_list(expected_arms, field="expected_arms")
    candidate_arm = _normalise_arm(candidate_arm)
    reference_arm = _normalise_arm(reference_arm)
    if candidate_arm not in expected:
        raise ValueError(f"candidate_arm must be included in expected_arms: {candidate_arm}")
    if reference_arm not in expected:
        raise ValueError(f"reference_arm must be included in expected_arms: {reference_arm}")
    rows = _coerce_observations(observations)
    grouped = _group_observations(rows)

    fixture_meta: dict[str, Any] = {}
    fixture_query_ids: set[str] | None = None
    if fixture is not None:
        fixture_meta = validate_replay_fixture(
            fixture,
            expected_seed=None,
            expected_count=None,
            require_pilot_split=False,
            project_root=project_root,
        )
        fixture_query_ids = set(fixture_meta["query_ids"])
        unknown = sorted(set(grouped) - fixture_query_ids)
        if unknown:
            fixture_meta["unknown_observation_query_ids"] = unknown
    query_ids = sorted(fixture_query_ids or set(grouped))
    observed_arms = sorted({arm for arms in grouped.values() for arm in arms})
    missing_required_observed_arms = sorted(set(REPLAY_ARMS) - set(observed_arms))
    missing_pairs = {
        query_id: [arm for arm in expected if arm not in grouped.get(query_id, {})]
        for query_id in query_ids
        if any(arm not in grouped.get(query_id, {}) for arm in expected)
    }
    summaries = {
        arm: _arm_summary(
            [grouped[query_id][arm] for query_id in query_ids if arm in grouped.get(query_id, {})],
            bootstrap_samples=bootstrap_samples,
            seed=seed + index,
        )
        for index, arm in enumerate(observed_arms)
    }

    effects: dict[str, Any] = {}
    for index, arm in enumerate(observed_arms):
        if arm == reference_arm:
            continue
        effects[f"{arm}_vs_{reference_arm}"] = _paired_effect(
            grouped,
            arm,
            reference_arm,
            samples=bootstrap_samples,
            seed=seed + 100 + index,
        )
    for left_arm, right_arm, key in (
        ("prompt_only", "memory_only", "prompt_effect_vs_memory"),
        ("memory_only", "prompt_only", "memory_effect_vs_prompt"),
        ("both", "prompt_only", "both_effect_vs_prompt"),
        ("both", "memory_only", "both_effect_vs_memory"),
    ):
        if left_arm in observed_arms and right_arm in observed_arms:
            effects[key] = _paired_effect(
                grouped,
                left_arm,
                right_arm,
                samples=bootstrap_samples,
                seed=seed + 200 + len(effects),
            )
    if all(arm in observed_arms for arm in ("neither", "prompt_only", "memory_only", "both")):
        prompt_main = _paired_effect(grouped, "prompt_only", "neither", samples=bootstrap_samples, seed=seed + 300)
        memory_main = _paired_effect(grouped, "memory_only", "neither", samples=bootstrap_samples, seed=seed + 301)
        both_main = _paired_effect(grouped, "both", "neither", samples=bootstrap_samples, seed=seed + 302)
        interaction_query_ids = sorted(
            query_id
            for query_id, arms in grouped.items()
            if all(arm in arms for arm in ("neither", "prompt_only", "memory_only", "both"))
        )
        interactions = [
            grouped[query_id]["both"].quality_score
            - grouped[query_id]["prompt_only"].quality_score
            - grouped[query_id]["memory_only"].quality_score
            + grouped[query_id]["neither"].quality_score
            for query_id in interaction_query_ids
        ]
        effects["prompt_main_effect"] = prompt_main
        effects["memory_main_effect"] = memory_main
        effects["both_effect"] = both_main
        lower, upper = bootstrap_ci(interactions, samples=bootstrap_samples, seed=seed + 303)
        effects["interaction"] = {
            "paired_query_count": len(interaction_query_ids),
            "delta": round(statistics.fmean(interactions), 6) if interactions else None,
            "ci": [round(lower, 6), round(upper, 6)] if interactions else None,
            "query_ids": interaction_query_ids,
        }

    reasons: list[str] = []
    hard_failure_rate = 0.0
    candidate_summary = summaries.get(candidate_arm)
    reference_summary = summaries.get(reference_arm)
    if not candidate_summary:
        reasons.append(f"missing_candidate_arm:{candidate_arm}")
    if candidate_arm not in observed_arms:
        reasons.append("candidate_arm_not_observed")
    if fixture_meta.get("unknown_observation_query_ids"):
        reasons.append("unknown_observation_query_id")
    if missing_required_observed_arms:
        # Keep this as a gate reason (rather than raising) so callers can
        # inspect the partial replay and obtain a useful remediation report.
        # It is nevertheless fail-closed because any non-empty reason keeps
        # the verdict out of ``pass``.
        reasons.append("required_arm_not_observed")
    if missing_pairs:
        reasons.append("incomplete_query_arm_pairs")
    # A complete Query/arm matrix is not sufficient when one or more rows did
    # not actually finish.  This check remains explicit even though the
    # observation constructor synthesizes a hard failure, protecting callers
    # that deserialize custom subclasses or legacy rows.
    incomplete_arms = sorted(
        arm
        for arm, summary in summaries.items()
        if int(summary.get("completed_count", 0)) != int(summary.get("query_count", 0))
    )
    if incomplete_arms:
        reasons.append("incomplete_arm_execution")
    if candidate_summary:
        hard_failure_rate = float(candidate_summary["hard_failure_rate"])
        if hard_failure_rate > policy_obj.max_hard_failure_rate:
            reasons.append("candidate_hard_failure_rate_exceeded")
    # Any hard failure in any arm invalidates a causal comparison.  This is
    # intentionally stricter than the candidate-only check above.
    all_hard_failures = sorted({failure for summary in summaries.values() for failure in summary["hard_failures"]})
    if all_hard_failures:
        reasons.append("hard_failure_present")

    quality_effect = effects.get(f"{candidate_arm}_vs_{reference_arm}")
    if quality_effect is None or quality_effect.get("delta") is None:
        reasons.append("reference_arm_unavailable")
    else:
        delta = float(quality_effect["delta"])
        ci = quality_effect.get("ci") or [None, None]
        if delta < policy_obj.min_quality_delta or ci[0] is None or float(ci[0]) < policy_obj.min_quality_delta:
            reasons.append("quality_gain_below_threshold")

    metric_effects = _paired_metric_effects(
        grouped,
        candidate_arm,
        reference_arm,
        samples=bootstrap_samples,
        seed=seed + 400,
    ) if candidate_arm in observed_arms and reference_arm in observed_arms else {}

    resource_changes: dict[str, Any] = {}
    if candidate_summary and reference_summary:
        for metric, candidate_key, reference_key, maximum, reason in (
            ("cost", "mean_estimated_cost", "mean_estimated_cost", policy_obj.max_cost_increase, "cost_increase_exceeded"),
            ("latency", "p95_duration_seconds", "p95_duration_seconds", policy_obj.max_latency_increase, "latency_increase_exceeded"),
        ):
            change = _relative_change(float(candidate_summary[candidate_key]), float(reference_summary[reference_key]))
            resource_changes[metric] = (
                "unbounded" if change is not None and change == float("inf") else change
            )
            if change is not None and change > maximum:
                reasons.append(reason)
    else:
        reasons.append("resource_reference_unavailable")
    if candidate_summary and float(candidate_summary["max_non_target_regression"]) > policy_obj.max_non_target_regression:
        reasons.append("non_target_regression_exceeded")

    complete_cases = len(
        [
            query_id
            for query_id in query_ids
            if all(
                arm in grouped.get(query_id, {})
                and grouped[query_id][arm].status == "completed"
                for arm in expected
            )
        ]
    )
    if complete_cases < policy_obj.min_complete_cases:
        reasons.append("insufficient_complete_cases")

    if all_hard_failures:
        verdict = "fail"
    elif any(reason in reasons for reason in ("candidate_hard_failure_rate_exceeded", "hard_failure_present", "incomplete_arm_execution", "required_arm_not_observed", "quality_gain_below_threshold", "cost_increase_exceeded", "latency_increase_exceeded", "non_target_regression_exceeded")):
        verdict = "fail"
    elif reasons:
        verdict = "inconclusive"
    else:
        verdict = "pass"

    return {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "eval_id": eval_id or (rows[0].eval_id if rows else "replay"),
        "seed": seed,
        "observed_arms": observed_arms,
        "expected_arms": list(expected),
        "candidate_arm": candidate_arm,
        "reference_arm": reference_arm,
        "query_count": len(query_ids),
        "observation_count": len(rows),
        "complete_case_count": complete_cases,
        "missing_pairs": missing_pairs,
        "fixture": fixture_meta,
        "arms": summaries,
        "effects": effects,
        "metric_effects": metric_effects,
        "resource_changes": resource_changes,
        "hard_failures": all_hard_failures,
        "policy": policy_obj.to_dict(),
        "gate": {
            "passed": verdict == "pass",
            "verdict": verdict,
            "reasons": list(dict.fromkeys(reasons)),
            "hard_failure_rate": round(hard_failure_rate, 6),
        },
        "verdict": verdict,
    }


def build_replay_manifest(
    *,
    fixture_path: str | Path,
    eval_id: str,
    bundle_id: str,
    arms: Sequence[str] = REPLAY_ARMS,
    seed: str | None = DEFAULT_REPLAY_SEED,
    project_root: str | Path | None = None,
    metadata: Mapping[str, Any] | None = None,
    parent_bundle_hash: str | None = None,
    candidate_prompt_hashes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a portable immutable manifest before running any adapters."""

    fixture_meta = validate_replay_fixture(
        fixture_path,
        expected_seed=seed,
        expected_count=None,
        require_pilot_split=True,
        project_root=project_root,
    )
    # Keep standalone manifests subject to the same attribution contract as
    # ``aggregate_replay``.  Otherwise a manifest can advertise a one-arm
    # experiment that the approval layer would later mistake for a complete
    # replay.
    selected_arms = _required_arm_list(arms, field="arms")
    manifest = {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "eval_id": str(eval_id),
        "bundle_id": str(bundle_id),
        "fixture_path": _portable_path(fixture_path, project_root=project_root),
        "fixture_sha256": fixture_meta["fixture_sha256"],
        "dataset_snapshot": fixture_meta["fixture_sha256"],
        "query_count": fixture_meta["query_count"],
        "query_ids": fixture_meta["query_ids"],
        "arms": list(selected_arms),
        "seed": fixture_meta["seed"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "metadata": dict(metadata or {}),
    }
    # ``bundle_id`` predates governed Prompt evolution and is intentionally
    # allowed to remain an opaque label.  New replay producers can carry the
    # immutable parent Bundle identity explicitly, together with stage-level
    # candidate hashes used by patch proposals.  Keep these fields optional so
    # historical benchmark summaries remain readable and attachable to legacy
    # full-file proposals.
    if parent_bundle_hash not in (None, ""):
        manifest["parent_bundle_hash"] = _normalise_sha256(
            parent_bundle_hash,
            field="parent_bundle_hash",
        )
    normalized_candidate_hashes = _normalise_prompt_hashes(candidate_prompt_hashes)
    if normalized_candidate_hashes:
        manifest["candidate_prompt_hashes"] = normalized_candidate_hashes
    return manifest


def write_replay_summary(path: str | Path, summary: Mapping[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(summary), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return target


def run_replay(
    *,
    fixture_path: str | Path,
    observations: Iterable[ReplayObservation | Mapping[str, Any]] | str | Path,
    eval_id: str,
    bundle_id: str = "",
    output_path: str | Path | None = None,
    expected_arms: Sequence[str] = REPLAY_ARMS,
    reference_arm: str = "prompt_only",
    candidate_arm: str = "both",
    fixture_seed: str | None = DEFAULT_REPLAY_SEED,
    policy: ReplayPolicy | Mapping[str, Any] | None = None,
    bootstrap_samples: int = DEFAULT_BOOTSTRAP_SAMPLES,
    seed: int = 20260913,
    project_root: str | Path | None = None,
    parent_bundle_hash: str | None = None,
    candidate_prompt_hashes: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute the sidecar replay aggregation and optionally persist a report."""

    manifest = build_replay_manifest(
        fixture_path=fixture_path,
        eval_id=eval_id,
        bundle_id=bundle_id,
        arms=expected_arms,
        seed=fixture_seed,
        project_root=project_root,
        parent_bundle_hash=parent_bundle_hash,
        candidate_prompt_hashes=candidate_prompt_hashes,
    )
    summary = aggregate_replay(
        observations,
        fixture=fixture_path,
        eval_id=eval_id,
        expected_arms=expected_arms,
        reference_arm=reference_arm,
        candidate_arm=candidate_arm,
        policy=policy,
        bootstrap_samples=bootstrap_samples,
        seed=seed,
        project_root=project_root,
    )
    summary["manifest"] = manifest
    if output_path is not None:
        write_replay_summary(output_path, summary)
    return summary


# Explicit aliases make the sidecar convenient for callers that use the names
# from the architecture document.
aggregate_replay_evaluation = aggregate_replay
run_replay_evaluation = run_replay


__all__ = [
    "DEFAULT_REPLAY_SEED",
    "REPLAY_ARMS",
    "OPTIONAL_REPLAY_ARMS",
    "SUPPORTED_REPLAY_ARMS",
    "ReplayObservation",
    "ReplayPolicy",
    "aggregate_replay",
    "aggregate_replay_evaluation",
    "bootstrap_ci",
    "build_replay_manifest",
    "load_replay_fixture",
    "run_replay",
    "run_replay_evaluation",
    "validate_replay_fixture",
    "write_replay_summary",
]
