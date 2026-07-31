"""Evaluate manual labels for the 200-row relation quality review sample.

This script is a gate calculator, not an auto-grader. It only reads human
labels, computes the agreed thresholds, and reports whether HypothesisLink is
still blocked.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SAMPLE = PROJECT_ROOT / "data" / "processed" / "relation_quality_ab" / "sample_manifest.jsonl"
DEFAULT_TEMPLATE = (
    PROJECT_ROOT / "data" / "processed" / "relation_quality_ab" / "manual_labels_template.jsonl"
)
DEFAULT_LABELS = PROJECT_ROOT / "data" / "processed" / "relation_quality_ab" / "manual_labels.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "manual-review" / "relation_quality_label_gate.md"

VALID_LABELS = {"correct", "reversed", "wrong_relation", "ambiguous"}
VALID_PATH_SAFE_LABELS = {"true", "false", "needs_review"}


@dataclass(frozen=True)
class LabelGateThresholds:
    min_labeled: int = 200
    max_direction_reversal_rate: float = 0.04
    max_strict_error_rate: float = 0.10
    max_path_unsafe_rate: float = 0.12


@dataclass(frozen=True)
class LabelGateResult:
    sample_count: int
    labeled_count: int
    label_counts: dict[str, int]
    path_safe_label_counts: dict[str, int]
    direction_reversal_rate: float
    strict_error_rate: float
    path_unsafe_rate: float
    gate_passed: bool
    fail_reasons: list[str]
    missing_label_count: int
    invalid_label_count: int
    duplicate_label_count: int
    unknown_assertion_count: int
    thresholds: LabelGateThresholds


def main() -> int:
    args = parse_args()
    sample_path = Path(args.sample).expanduser().resolve()
    template_path = Path(args.template).expanduser().resolve()
    labels_path = Path(args.labels).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    samples = read_jsonl(sample_path)
    template_rows = build_label_template_rows(samples)
    write_jsonl(template_path, template_rows)

    labels = read_jsonl(labels_path) if labels_path.exists() else []
    result = evaluate_labels(
        samples=samples,
        labels=labels,
        thresholds=LabelGateThresholds(min_labeled=args.min_labeled),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        build_gate_report(result, sample_path=sample_path, labels_path=labels_path),
        encoding="utf-8",
    )
    print(f"wrote {template_path}")
    print(f"wrote {output_path}")
    return 0 if result.gate_passed else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate manual relation quality labels.")
    parser.add_argument("--sample", default=str(DEFAULT_SAMPLE))
    parser.add_argument("--template", default=str(DEFAULT_TEMPLATE))
    parser.add_argument("--labels", default=str(DEFAULT_LABELS))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--min-labeled", type=int, default=200)
    return parser.parse_args()


def build_label_template_rows(samples: Iterable[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sample in samples:
        row = _sample_dict(sample)
        rows.append(
            {
                "assertion_id": row.get("assertion_id", ""),
                "relation_type": row.get("relation_type", ""),
                "source": row.get("source", ""),
                "source_type": row.get("source_type", ""),
                "target": row.get("target", ""),
                "target_type": row.get("target_type", ""),
                "confidence": row.get("confidence", 0.0),
                "content_type": row.get("content_type", ""),
                "document_title": row.get("document_title", ""),
                "chunk_id": row.get("chunk_id", ""),
                "claim_text": row.get("claim_text", ""),
                "evidence_quote": row.get("evidence_quote", ""),
                "inference_eligible": row.get("inference_eligible", ""),
                "trigger_text": row.get("trigger_text", ""),
                "extraction_rule_version": row.get("extraction_rule_version", ""),
                "label": "",
                "path_safe_label": "",
                "note": "",
            }
        )
    return rows


def evaluate_labels(
    samples: Iterable[Any],
    labels: Iterable[dict[str, Any]],
    thresholds: LabelGateThresholds | None = None,
) -> LabelGateResult:
    thresholds = thresholds or LabelGateThresholds()
    sample_ids = [str(_sample_dict(sample).get("assertion_id", "")) for sample in samples]
    sample_id_set = {sample_id for sample_id in sample_ids if sample_id}
    labels_by_id: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    unknown_count = 0
    invalid_count = 0

    for label_row in labels:
        assertion_id = str(label_row.get("assertion_id", ""))
        if not assertion_id:
            invalid_count += 1
            continue
        if assertion_id not in sample_id_set:
            unknown_count += 1
            continue
        if assertion_id in labels_by_id:
            duplicate_count += 1
        labels_by_id[assertion_id] = label_row

    label_counts: Counter[str] = Counter()
    path_safe_counts: Counter[str] = Counter()
    for sample_id in sample_ids:
        label_row = labels_by_id.get(sample_id)
        if not label_row:
            continue
        label = str(label_row.get("label", "")).strip()
        path_safe_label = str(label_row.get("path_safe_label", "")).strip()
        if label not in VALID_LABELS:
            invalid_count += 1
            continue
        label_counts[label] += 1
        if path_safe_label in VALID_PATH_SAFE_LABELS:
            path_safe_counts[path_safe_label] += 1
        elif path_safe_label:
            invalid_count += 1

    labeled_count = sum(label_counts.values())
    direction_reversal_rate = _ratio(label_counts["reversed"], labeled_count)
    strict_error_rate = _ratio(
        label_counts["reversed"] + label_counts["wrong_relation"],
        labeled_count,
    )
    path_unsafe_count = (
        label_counts["reversed"]
        + label_counts["wrong_relation"]
        + label_counts["ambiguous"]
    )
    path_unsafe_rate = _ratio(path_unsafe_count, labeled_count)

    fail_reasons: list[str] = []
    if labeled_count < thresholds.min_labeled:
        fail_reasons.append("incomplete_labels")
    if invalid_count:
        fail_reasons.append("invalid_labels")
    if duplicate_count:
        fail_reasons.append("duplicate_labels")
    if unknown_count:
        fail_reasons.append("unknown_assertion_ids")
    if (
        labeled_count > 0
        and direction_reversal_rate >= thresholds.max_direction_reversal_rate
    ):
        fail_reasons.append("direction_reversal_rate")
    if labeled_count > 0 and strict_error_rate >= thresholds.max_strict_error_rate:
        fail_reasons.append("strict_error_rate")
    if labeled_count > 0 and path_unsafe_rate >= thresholds.max_path_unsafe_rate:
        fail_reasons.append("path_unsafe_rate")

    return LabelGateResult(
        sample_count=len(sample_ids),
        labeled_count=labeled_count,
        label_counts=dict(sorted(label_counts.items())),
        path_safe_label_counts=dict(sorted(path_safe_counts.items())),
        direction_reversal_rate=direction_reversal_rate,
        strict_error_rate=strict_error_rate,
        path_unsafe_rate=path_unsafe_rate,
        gate_passed=not fail_reasons,
        fail_reasons=fail_reasons,
        missing_label_count=max(0, len(sample_ids) - labeled_count),
        invalid_label_count=invalid_count,
        duplicate_label_count=duplicate_count,
        unknown_assertion_count=unknown_count,
        thresholds=thresholds,
    )


def build_gate_report(
    result: LabelGateResult,
    sample_path: Path,
    labels_path: Path,
) -> str:
    status = "PASS" if result.gate_passed else "FAIL"
    lines = [
        "# Relation Quality Manual Label Gate",
        "",
        "日期：2026-05-25",
        "",
        "本文只汇总人工标签结果，不调用 LLM，不写数据库，也不从未标注样本推断质量。",
        "",
        "## Gate Status",
        "",
        f"- status：`{status}`",
        f"- sample：`{sample_path}`",
        f"- labels：`{labels_path}`",
        f"- sample_count：`{result.sample_count}`",
        f"- labeled_count：`{result.labeled_count}`",
        f"- missing_label_count：`{result.missing_label_count}`",
        f"- fail_reasons：`{result.fail_reasons}`",
        "",
        "## Metrics",
        "",
        f"- direction_reversal_rate：`{_format_rate(result.direction_reversal_rate, result.labeled_count)}`，门槛 `< {result.thresholds.max_direction_reversal_rate:.0%}`",
        f"- strict_error_rate：`{_format_rate(result.strict_error_rate, result.labeled_count)}`，门槛 `< {result.thresholds.max_strict_error_rate:.0%}`",
        f"- path_unsafe_rate：`{_format_rate(result.path_unsafe_rate, result.labeled_count)}`，门槛 `< {result.thresholds.max_path_unsafe_rate:.0%}`",
        "",
        "## Counts",
        "",
        f"- label_counts：`{result.label_counts}`",
        f"- path_safe_label_counts：`{result.path_safe_label_counts}`",
        f"- invalid_label_count：`{result.invalid_label_count}`",
        f"- duplicate_label_count：`{result.duplicate_label_count}`",
        f"- unknown_assertion_count：`{result.unknown_assertion_count}`",
        "",
        "## Decision",
        "",
    ]
    if result.gate_passed:
        lines.append("人工标签门槛通过，可以讨论是否进入 HypothesisLink v0。")
    else:
        lines.append("人工标签门槛未通过，不应进入 HypothesisLink。下一步是补齐标签或修正抽取层后重抽。")
    lines.append("")
    return "\n".join(lines)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _sample_dict(sample: Any) -> dict[str, Any]:
    if isinstance(sample, dict):
        return sample
    if hasattr(sample, "to_dict"):
        return sample.to_dict()
    if hasattr(sample, "__dict__"):
        return dict(sample.__dict__)
    return {}


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def _format_rate(rate: float, denominator: int) -> str:
    if denominator == 0:
        return "N/A"
    return f"{rate:.2%}"


if __name__ == "__main__":
    raise SystemExit(main())
