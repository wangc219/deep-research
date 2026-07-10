"""Compare relation-quality fields for prompt/schema A/B result files.

This script compares ExtractionResult JSONL files. It does not judge semantic
correctness without human labels; manual direction/type accuracy belongs in the
review manifest produced by sample_relation_quality_ab.py.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = PROJECT_ROOT / "scripts" / "extraction_experiment"
sys.path.insert(0, str(EXPERIMENT_ROOT))

from evaluator import evaluate_group  # noqa: E402
from models import DocumentChunk, ExtractionResult, load_chunks, load_results  # noqa: E402


DEFAULT_OUTPUT = (
    PROJECT_ROOT / "docs" / "experiment-artifacts" / "prompt_v2_ab_evaluation.md"
)


def main() -> int:
    args = parse_args()
    chunks = load_chunks(Path(args.chunks).expanduser().resolve())
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    groups: list[tuple[str, list[ExtractionResult]]] = []
    if args.v1_results:
        groups.append(("v1", load_results(Path(args.v1_results).expanduser().resolve())))
    if args.v2_results:
        groups.append(("v2", load_results(Path(args.v2_results).expanduser().resolve())))
    if not groups:
        raise SystemExit("Provide at least one of --v1-results or --v2-results")

    summaries = [
        {"label": label, **summarize_results(results, chunks_by_id)}
        for label, results in groups
    ]
    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_report(summaries), encoding="utf-8")
    if args.json_output:
        json_path = Path(args.json_output).expanduser().resolve()
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps({"groups": summaries}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {output_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate relation quality A/B result files.")
    parser.add_argument("--chunks", required=True)
    parser.add_argument("--v1-results", default="")
    parser.add_argument("--v2-results", default="")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--json-output", default="")
    return parser.parse_args()


def summarize_results(
    results: list[ExtractionResult],
    chunks_by_id: dict[str, DocumentChunk],
) -> dict[str, Any]:
    base = evaluate_group("group_a_schema_guided", results, chunks_by_id)
    relation_type_counts: Counter[str] = Counter()
    inference_counts: Counter[str] = Counter()
    trigger_text_count = 0
    rule_version_counts: Counter[str] = Counter()
    warning_code_counts: Counter[str] = Counter()
    total_relations = 0
    for result in results:
        for warning in result.warnings:
            warning_code = str(warning).split(":", 1)[0]
            if warning_code in {"relation_type_suspicious", "path_unsafe_relation"}:
                warning_code_counts[warning_code] += 1
        for relation in result.relations:
            total_relations += 1
            relation_type_counts[relation.relation_type] += 1
            inference_counts[relation.inference_eligible or "missing"] += 1
            if relation.trigger_text:
                trigger_text_count += 1
            if relation.extraction_rule_version:
                rule_version_counts[relation.extraction_rule_version] += 1
    return {
        **base,
        "total_relations": total_relations,
        "relation_type_counts": dict(sorted(relation_type_counts.items())),
        "inference_eligible_counts": dict(sorted(inference_counts.items())),
        "relations_with_trigger_text": trigger_text_count,
        "relations_with_trigger_text_rate": ratio(trigger_text_count, total_relations),
        "rule_version_counts": dict(sorted(rule_version_counts.items())),
        "relation_quality_warning_counts": dict(sorted(warning_code_counts.items())),
    }


def build_report(summaries: list[dict[str, Any]]) -> str:
    lines = [
        "# Prompt v2 A/B Evaluation",
        "",
        "日期：2026-05-25",
        "",
        "本文只比较结构、关系类型分布和 relation quality 字段覆盖率。方向抽反率、严格错误率和路径不安全率必须来自人工标注，不在未标注结果上自动计算。",
        "",
        "## Summary",
        "",
        "| group | results | prompt | schema | relations | trigger_text_rate | inference_eligible | relation_quality_warnings |",
        "|---|---:|---|---|---:|---:|---|---|",
    ]
    for summary in summaries:
        lines.append(
            "| {label} | {result_count} | {prompt_versions} | {schema_versions} | "
            "{total_relations} | {relations_with_trigger_text_rate:.2f} | "
            "{inference_eligible_counts} | {relation_quality_warning_counts} |".format(**summary)
        )
    lines.extend(["", "## Interpretation", ""])
    lines.extend(build_interpretation(summaries))
    lines.extend(["", "## Relation Type Counts", ""])
    for summary in summaries:
        lines.extend(
            [
                f"### {summary['label']}",
                "",
                table(
                    ["relation_type", "count"],
                    [
                        {"relation_type": key, "count": value}
                        for key, value in summary["relation_type_counts"].items()
                    ],
                ),
                "",
            ]
        )
    return "\n".join(lines)


def build_interpretation(summaries: list[dict[str, Any]]) -> list[str]:
    by_label = {str(summary["label"]): summary for summary in summaries}
    lines = [
        "这是结构性 A/B，不是语义准确率验收。`trigger_text`、`inference_eligible` 和关系类型分布只能说明 prompt/schema 是否按新契约产出字段；方向抽反率、严格错误率和路径不安全率仍必须来自人工标注。",
        "",
    ]
    if "v1" in by_label and "v2" in by_label:
        v1 = by_label["v1"]
        v2 = by_label["v2"]
        v1_types = v1.get("relation_type_counts", {})
        v2_types = v2.get("relation_type_counts", {})
        v1_overloaded = int(v1_types.get("enables", 0)) + int(v1_types.get("applies_to", 0))
        v2_overloaded = int(v2_types.get("enables", 0)) + int(v2_types.get("applies_to", 0))
        new_relation_counts = {
            key: int(v2_types.get(key, 0))
            for key in ["drives", "responsible_for", "has_capability"]
            if int(v2_types.get(key, 0)) > 0
        }
        lines.extend(
            [
                f"- `enables + applies_to` 从 `{v1_overloaded}` 降到 `{v2_overloaded}`。这是关系类型过载下降的结构信号，但不是人工正确率结论。",
                f"- v2 新关系使用情况：`{new_relation_counts}`。如果新增关系长期不用，说明 schema 过宽；如果集中爆发，需要人工复核是否形成新的万能筐。",
                f"- v2 `trigger_text` 覆盖率为 `{v2.get('relations_with_trigger_text_rate', 0):.2f}`，说明审计字段已进入输出面，可用于后续人工审核。",
            ]
        )
    else:
        lines.append("- 当前报告未同时提供 v1 和 v2，因此只能看单组结构覆盖，不能比较 prompt/schema 变化。")

    lines.extend(
        [
            "- 当前 gate 状态：未通过。原因是 `data/processed/relation_quality_ab/sample_manifest.jsonl` 的 200 条样本尚未完成人工标注。",
            "- 进入 HypothesisLink 前的门槛仍是：`direction_reversal_rate < 4%`、`strict_error_rate < 10%`、`path_unsafe_rate < 12%`。这些指标不得从未标注模型输出自动计算。",
        ]
    )
    return lines


def table(headers: list[str], rows: list[dict[str, Any]]) -> str:
    output = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        output.append("| " + " | ".join(str(row.get(header, "")) for header in headers) + " |")
    return "\n".join(output)


def ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


if __name__ == "__main__":
    raise SystemExit(main())
