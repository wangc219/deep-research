"""Compare old v3 extraction results with v4 seven-relation prompt results.

This is a structural A/B evaluator. It does not infer semantic correctness
without manual labels.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = PROJECT_ROOT / "scripts" / "extraction_experiment"
sys.path.insert(0, str(EXPERIMENT_ROOT))

from evaluator import evaluate_group  # noqa: E402
from models import DocumentChunk, ExtractionResult, load_chunks, load_results  # noqa: E402
from schema import SEVEN_RELATION_TYPES  # noqa: E402


DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "docs"
    / "experiment-artifacts"
    / "seven_relation_prompt_v4_ab_evaluation.md"
)


def main() -> int:
    args = parse_args()
    chunks = load_chunks(Path(args.chunks).expanduser().resolve())
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    v3_results_all = load_results(Path(args.v3_results).expanduser().resolve())
    v4_results_all = load_results(Path(args.v4_results).expanduser().resolve())
    v3_by_chunk = {result.chunk_id: result for result in v3_results_all}
    v4_by_chunk = {result.chunk_id: result for result in v4_results_all}
    common_chunk_ids = sorted(set(v3_by_chunk) & set(v4_by_chunk))
    if not common_chunk_ids:
        raise SystemExit("No overlapping chunk_id between v3 and v4 results")

    comparable_chunks = {
        chunk_id: chunks_by_id[chunk_id]
        for chunk_id in common_chunk_ids
        if chunk_id in chunks_by_id
    }
    v3_results = [v3_by_chunk[chunk_id] for chunk_id in common_chunk_ids]
    v4_results = [v4_by_chunk[chunk_id] for chunk_id in common_chunk_ids]
    summaries = [
        {
            "input_result_count": len(v3_results_all),
            "common_chunk_count": len(common_chunk_ids),
            **summarize_group("v3_old_prompt", v3_results, comparable_chunks),
        },
        {
            "input_result_count": len(v4_results_all),
            "common_chunk_count": len(common_chunk_ids),
            **summarize_group("v4_seven_relation_prompt", v4_results, comparable_chunks),
        },
    ]
    if args.v3_prediction_summary:
        summaries[0]["prediction_summary"] = _load_prediction_summary(
            Path(args.v3_prediction_summary).expanduser().resolve()
        )
    if args.v4_prediction_summary:
        summaries[1]["prediction_summary"] = _load_prediction_summary(
            Path(args.v4_prediction_summary).expanduser().resolve()
        )

    output_path = Path(args.output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_report(summaries), encoding="utf-8")

    if args.json_output:
        json_path = Path(args.json_output).expanduser().resolve()
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(
            json.dumps({"groups": summaries}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    print(f"wrote {output_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate v3 old prompt vs v4 seven-relation prompt on overlapping chunks.",
    )
    parser.add_argument("--chunks", required=True)
    parser.add_argument("--v3-results", required=True)
    parser.add_argument("--v4-results", required=True)
    parser.add_argument("--v3-prediction-summary", default="")
    parser.add_argument("--v4-prediction-summary", default="")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--json-output", default="")
    return parser.parse_args()


def summarize_group(
    label: str,
    results: list[ExtractionResult],
    chunks_by_id: dict[str, DocumentChunk],
) -> dict[str, Any]:
    base = evaluate_group(label, results, chunks_by_id)
    relation_type_counts: Counter[str] = Counter()
    outside_seven_counts: Counter[str] = Counter()
    inference_counts: Counter[str] = Counter()
    warning_code_counts: Counter[str] = Counter()
    total_relations = 0
    seven_relation_count = 0
    relations_with_claim = 0
    relations_with_trigger_text = 0
    evidence_quote_not_found_count = 0

    for result in results:
        claim_signatures = {
            (claim.subject_entity_id, claim.object_entity_id, claim.predicate)
            for claim in result.claims
        }
        for warning in result.warnings:
            code = _warning_code(warning)
            warning_code_counts[code] += 1
            if code == "evidence_quote_not_found":
                evidence_quote_not_found_count += 1
        for relation in result.relations:
            total_relations += 1
            relation_type_counts[relation.relation_type] += 1
            inference_counts[relation.inference_eligible or "missing"] += 1
            if relation.relation_type in SEVEN_RELATION_TYPES:
                seven_relation_count += 1
            else:
                outside_seven_counts[relation.relation_type] += 1
            if relation.trigger_text:
                relations_with_trigger_text += 1
            signature = (
                relation.source_entity_id,
                relation.target_entity_id,
                relation.relation_type,
            )
            if signature in claim_signatures:
                relations_with_claim += 1

    outside_count = total_relations - seven_relation_count
    return {
        **base,
        "label": label,
        "total_relations": total_relations,
        "seven_relation_count": seven_relation_count,
        "outside_seven_relation_count": outside_count,
        "outside_seven_relation_rate": ratio(outside_count, total_relations),
        "relation_type_counts": dict(sorted(relation_type_counts.items())),
        "outside_seven_relation_types": dict(sorted(outside_seven_counts.items())),
        "inference_eligible_counts": dict(sorted(inference_counts.items())),
        "relations_with_claim_rate": ratio(relations_with_claim, total_relations),
        "relations_with_trigger_text_rate": ratio(relations_with_trigger_text, total_relations),
        "warning_code_counts": dict(sorted(warning_code_counts.items())),
        "evidence_quote_not_found_count": evidence_quote_not_found_count,
    }


def build_report(summaries: list[dict[str, Any]]) -> str:
    lines = [
        "# Seven Relation Prompt v4 A/B Evaluation",
        "",
        f"生成日期：{date.today().isoformat()}",
        "",
        "本文比较旧 v3 prompt/schema 输出与 v4 七类关系 prompt 输出。它是结构性 A/B，不是语义准确率验收；方向抽反率、严格错误率和路径安全性仍需要人工标签确认。",
        "",
        "## Summary",
        "",
        "| group | comparable_chunks | prompt | relations | outside_seven_relation_rate | claim_rate | trigger_text_rate | warnings |",
        "|---|---:|---|---:|---:|---:|---:|---|",
    ]
    for summary in summaries:
        lines.append(
            "| {label} | {common_chunk_count} | {prompt_versions} | {total_relations} | "
            "{outside_seven_relation_rate:.2f} | {relations_with_claim_rate:.2f} | "
            "{relations_with_trigger_text_rate:.2f} | {warning_code_counts} |".format(
                **_with_default_counts(summary)
            )
        )
    lines.extend(["", "## Interpretation", ""])
    lines.extend(build_interpretation(summaries))
    lines.extend(["", "## Governance Health", ""])
    lines.append(
        table(
            [
                "group",
                "valid_rate",
                "evidence_binding_rate",
                "weak_modality_coverage",
                "evidence_quote_not_found",
            ],
            [
                {
                    "group": summary["label"],
                    "valid_rate": f"{summary.get('valid_result_rate', 0):.2f}",
                    "evidence_binding_rate": f"{summary.get('evidence_span_binding_rate', 0):.2f}",
                    "weak_modality_coverage": f"{summary.get('weak_modality_coverage_rate', 0):.2f}",
                    "evidence_quote_not_found": summary.get("evidence_quote_not_found_count", 0),
                }
                for summary in summaries
            ],
        )
    )
    lines.extend(
        [
            "",
            "`weak_modality_coverage` 下降表示模型可能把“可能、未来、提出、预期”等弱表达处理得不够保守；这会影响后续预测边是否应保持 `unverified` 或 `needs_review`。",
        ]
    )
    if any(summary.get("prediction_summary") for summary in summaries):
        lines.extend(["", "## Prediction Sanity Check", ""])
        lines.append(prediction_table(summaries))
        lines.extend(
            [
                "",
                "该部分只看同样本输入能否生成 `status=unverified` 的候选链路，不代表候选语义正确率。hypothesis 数减少不必然是坏事，可能意味着 v4 少抽了旧 schema 的 context-only 或过宽关系。",
            ]
        )
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
                "七类之外关系："
                + (
                    f" `{summary['outside_seven_relation_types']}`"
                    if summary["outside_seven_relation_types"]
                    else "无"
                ),
                "",
            ]
        )
    return "\n".join(lines)


def build_interpretation(summaries: list[dict[str, Any]]) -> list[str]:
    by_label = {summary["label"]: summary for summary in summaries}
    v3 = by_label.get("v3_old_prompt")
    v4 = by_label.get("v4_seven_relation_prompt")
    lines = [
        "- v4 的核心结构目标是让模型直接输出七类预测边，减少旧 v3 到七类边的投影治理开销。",
        "- `outside_seven_relation_rate` 应重点观察：v4 若仍出现七类之外关系，说明 prompt/schema 约束没有生效。",
        "- `claim_rate` 和 `trigger_text_rate` 不应明显下降；否则精简关系会损害可审计性。",
    ]
    if v3 and v4:
        lines.extend(
            [
                f"- v3 七类之外关系数为 `{v3['outside_seven_relation_count']}`，v4 为 `{v4['outside_seven_relation_count']}`。",
                f"- v3 总关系数 `{v3['total_relations']}`，v4 总关系数 `{v4['total_relations']}`。关系数下降不一定是退化，可能是 v4 不再强行抽 context-only 边；需要看人工样本。",
                "- 当前不能据此直接宣布 v4 语义更优；它只能证明输出面是否更适合后续预测治理。",
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


def prediction_table(summaries: list[dict[str, Any]]) -> str:
    rows = []
    for summary in summaries:
        prediction = summary.get("prediction_summary") or {}
        dropped_counts = prediction.get("dropped_relation_counts") or {}
        rows.append(
            {
                "group": summary["label"],
                "projected_edges": prediction.get("projected_edge_count", ""),
                "hypotheses": prediction.get("hypothesis_count", ""),
                "multi_doc": prediction.get("multi_document_hypothesis_count", ""),
                "path_edges": prediction.get("path_participating_edge_count", ""),
                "weak_path_hypotheses": prediction.get("weak_path_hypothesis_count", ""),
                "dropped_relations": sum(int(value) for value in dropped_counts.values()),
            }
        )
    return table(
        [
            "group",
            "projected_edges",
            "hypotheses",
            "multi_doc",
            "path_edges",
            "weak_path_hypotheses",
            "dropped_relations",
        ],
        rows,
    )


def ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def _warning_code(warning: Any) -> str:
    text = str(warning)
    if ":" not in text:
        return "model_warning"
    code = text.split(":", 1)[0]
    structured_codes = {
        "evidence_quote_not_found",
        "relation_type_suspicious",
        "path_unsafe_relation",
        "invalid_relation_type",
        "invalid_entity_type",
        "invalid_claim_type",
        "invalid_modality",
        "invalid_assertion_strength",
        "missing_trace",
        "missing_trace_schema_version",
        "missing_trace_model",
        "relation_missing_source",
        "relation_missing_target",
        "relation_no_evidence",
        "relation_missing_evidence",
        "claim_no_evidence",
        "claim_missing_evidence",
        "entity_missing_evidence",
    }
    return code if code in structured_codes else "model_warning"


def _load_prediction_summary(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _with_default_counts(summary: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(summary)
    enriched.setdefault("common_chunk_count", summary.get("result_count", 0))
    enriched.setdefault("warning_code_counts", {})
    return enriched


if __name__ == "__main__":
    raise SystemExit(main())
