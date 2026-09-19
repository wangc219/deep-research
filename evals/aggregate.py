from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
import random
import statistics

from .models import EvalRunResult, PairwiseJudgment, read_jsonl


def aggregate_pairwise(
    judgments_path: str | Path,
    mapping_path: str | Path,
    results_path: str | Path | None = None,
    *,
    bootstrap_samples: int = 5000,
    seed: int = 20260718,
) -> dict[str, Any]:
    mappings = {row["pair_id"]: row for row in read_jsonl(mapping_path)}
    judgments = [PairwiseJudgment(**row) for row in read_jsonl(judgments_path)]
    query_votes: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
    query_judgments: dict[str, list[dict[str, Any]]] = defaultdict(list)
    dimension_votes: dict[str, Counter[str]] = defaultdict(Counter)
    hard_failures: Counter[str] = Counter()
    for judgment in judgments:
        judgment.validate()
        mapping = mappings.get(judgment.pair_id)
        if not mapping:
            continue
        system_winner = _system_winner(judgment.winner, mapping)
        query_votes[str(mapping["query_id"])].append(
            (system_winner, str(mapping["system_a"]), str(mapping["system_b"]))
        )
        query_judgments[str(mapping["query_id"])].append(
            {
                "pair_id": judgment.pair_id,
                "judge_id": judgment.judge_id,
                "system_winner": system_winner,
                "confidence": judgment.confidence,
                "primary_route": judgment.primary_route,
                "route_confidence": judgment.route_confidence,
                "citation_issues": judgment.citation_issues,
                "hard_failures": judgment.hard_failures,
                "adjudication_required": judgment.adjudication_required,
                "adjudication_reasons": judgment.adjudication_reasons,
            }
        )
        for dimension, winner in judgment.dimensions.items():
            if dimension == "communication_efficiency":
                continue
            dimension_votes[dimension][_system_winner(winner, mapping)] += 1
        for failure in judgment.hard_failures:
            hard_failures[failure] += 1

    query_outcomes: list[dict[str, Any]] = []
    all_systems: set[str] = set()
    for query_id, votes in sorted(query_votes.items()):
        counts = Counter(winner for winner, _, _ in votes)
        all_systems.update(system for _, left, right in votes for system in (left, right))
        non_tie = [(system, count) for system, count in counts.items() if system != "tie"]
        if not non_tie:
            winner = "tie"
        else:
            ranked = sorted(non_tie, key=lambda item: (-item[1], item[0]))
            winner = ranked[0][0] if len(ranked) == 1 or ranked[0][1] > ranked[1][1] else "tie"
        query_outcomes.append({"query_id": query_id, "winner": winner, "votes": dict(counts)})

    system_summary: dict[str, dict[str, Any]] = {}
    for system in sorted(all_systems):
        scores = [1.0 if row["winner"] == system else 0.5 if row["winner"] == "tie" else 0.0 for row in query_outcomes]
        lower, upper = bootstrap_interval(scores, samples=bootstrap_samples, seed=seed)
        system_summary[system] = {
            "wins": sum(row["winner"] == system for row in query_outcomes),
            "ties": sum(row["winner"] == "tie" for row in query_outcomes),
            "losses": sum(row["winner"] not in {system, "tie"} for row in query_outcomes),
            "score_rate": round(statistics.fmean(scores), 4) if scores else 0.0,
            "bootstrap_95pct": [round(lower, 4), round(upper, 4)],
        }

    runtime = _runtime_summary(results_path) if results_path else {}
    adjudication_queue: list[dict[str, Any]] = []
    for query_id, rows in sorted(query_judgments.items()):
        non_tie_winners = {row["system_winner"] for row in rows if row["system_winner"] != "tie"}
        reasons: list[str] = []
        if len(non_tie_winners) > 1:
            reasons.append("judge_or_order_disagreement")
        if any(float(row["confidence"]) < 0.65 for row in rows):
            reasons.append("low_confidence")
        if any(row["citation_issues"] for row in rows):
            reasons.append("citation_issue")
        if any(row["hard_failures"] for row in rows):
            reasons.append("hard_failure")
        if any(row["adjudication_required"] for row in rows):
            reasons.append("judge_requested_adjudication")
        if reasons:
            adjudication_queue.append(
                {
                    "query_id": query_id,
                    "reasons": list(dict.fromkeys(reasons)),
                    "judgments": rows,
                }
            )
    return {
        "schema_version": "1.0",
        "query_count": len(query_outcomes),
        "judgment_count": len(judgments),
        "systems": system_summary,
        "dimension_votes": {key: dict(value) for key, value in sorted(dimension_votes.items())},
        "hard_failures": dict(hard_failures),
        "runtime": runtime,
        "adjudication_queue": adjudication_queue,
        "query_outcomes": query_outcomes,
    }


def bootstrap_interval(scores: list[float], *, samples: int, seed: int) -> tuple[float, float]:
    if not scores:
        return 0.0, 0.0
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(scores, k=len(scores))) for _ in range(max(100, samples)))
    return means[int(len(means) * 0.025)], means[min(len(means) - 1, int(len(means) * 0.975))]


def _system_winner(winner: str, mapping: dict[str, Any]) -> str:
    if winner == "A":
        return str(mapping["system_a"])
    if winner == "B":
        return str(mapping["system_b"])
    return "tie"


def _runtime_summary(results_path: str | Path) -> dict[str, Any]:
    grouped: dict[str, list[EvalRunResult]] = defaultdict(list)
    for row in read_jsonl(results_path):
        result = EvalRunResult.from_dict(row)
        grouped[result.system_id].append(result)
    summary: dict[str, Any] = {}
    for system, rows in grouped.items():
        completed = [row for row in rows if row.status == "completed"]
        summary[system] = {
            "run_count": len(rows),
            "completion_rate": round(len(completed) / len(rows), 4) if rows else 0.0,
            "mean_duration_seconds": round(statistics.fmean(row.duration_seconds for row in completed), 3) if completed else 0.0,
            "mean_estimated_cost": round(statistics.fmean(row.estimated_cost for row in completed), 6) if completed else 0.0,
            "mean_usage": _mean_usage(completed),
        }
    return summary


def _mean_usage(rows: list[EvalRunResult]) -> dict[str, float]:
    keys = sorted(
        {
            key
            for row in rows
            for key, value in row.usage.items()
            if isinstance(value, (int, float))
        }
    )
    return {
        key: round(statistics.fmean(float(row.usage.get(key, 0.0)) for row in rows), 3)
        for key in keys
    }


def aggregate_replay(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Compatibility entry point for text-evolution replay aggregation.

    Keep the implementation in ``evals.replay`` so the legacy pairwise
    aggregator remains stable, while callers that naturally look in this
    module can use the same API.
    """

    from .replay import aggregate_replay as _aggregate_replay

    return _aggregate_replay(*args, **kwargs)


def bootstrap_replay_ci(*args: Any, **kwargs: Any) -> tuple[float, float]:
    """Compatibility wrapper for the paired replay bootstrap helper."""

    from .replay import bootstrap_ci

    return bootstrap_ci(*args, **kwargs)
