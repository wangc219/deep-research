"""Build per-document stability reports for extraction experiment outputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from models import DocumentChunk, ExtractionResult, load_chunks, load_results
from schema import NEGATION_TERMS, WEAK_MODALITY_TERMS


def main() -> int:
    args = _parse_args()
    chunks = load_chunks(Path(args.chunks))
    results = load_results(Path(args.results))
    report = build_stability_report(chunks, results)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".json":
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output.write_text(_to_markdown(report), encoding="utf-8")
    print(f"Wrote stability report to {output}")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize extraction stability by document/chunk.",
    )
    parser.add_argument("--chunks", required=True, help="Input DocumentChunk JSONL.")
    parser.add_argument("--results", required=True, help="ExtractionResult JSONL.")
    parser.add_argument("--output", required=True, help="Output .md or .json report path.")
    return parser.parse_args()


def build_stability_report(
    chunks: list[DocumentChunk],
    results: list[ExtractionResult],
) -> dict[str, Any]:
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    results_by_chunk = {result.chunk_id: result for result in results}
    rows: list[dict[str, Any]] = []

    total_evidence = 0
    bound_evidence = 0
    total_relations = 0
    total_claims = 0
    chunks_with_result = 0
    chunks_valid = 0
    chunks_with_claims = 0
    weak_chunks = 0
    weak_chunks_covered = 0

    for chunk in chunks:
        result = results_by_chunk.get(chunk.chunk_id)
        title = str(chunk.metadata.get("title") or chunk.section_title or chunk.document_id)
        if result is None:
            rows.append(
                {
                    "title": title,
                    "document_id": chunk.document_id,
                    "chunk_id": chunk.chunk_id,
                    "status": "missing_result",
                    "entities": 0,
                    "relations": 0,
                    "claims": 0,
                    "non_asserted_claims": 0,
                    "evidence_spans": 0,
                    "bound_evidence_spans": 0,
                    "latency_ms": 0,
                    "structural_warnings": ["missing_result"],
                    "model_warning_count": 0,
                    "model_warnings": [],
                }
            )
            continue

        chunks_with_result += 1
        structural_warnings = result.validate(chunk.text)
        if not structural_warnings:
            chunks_valid += 1
        evidence_count = len(result.evidence_spans)
        evidence_bound = sum(
            1
            for evidence in result.evidence_spans
            if evidence.quote and evidence.quote in chunk.text
        )
        total_evidence += evidence_count
        bound_evidence += evidence_bound
        total_relations += len(result.relations)
        total_claims += len(result.claims)
        if result.claims:
            chunks_with_claims += 1

        has_weak_language = _has_weak_language(chunk.text)
        if has_weak_language:
            weak_chunks += 1
            if any(claim.modality != "asserted" for claim in result.claims):
                weak_chunks_covered += 1

        rows.append(
            {
                "title": title,
                "document_id": chunk.document_id,
                "chunk_id": chunk.chunk_id,
                "status": "ok" if not structural_warnings else "warning",
                "entities": len(result.entities),
                "relations": len(result.relations),
                "claims": len(result.claims),
                "non_asserted_claims": sum(
                    1 for claim in result.claims if claim.modality != "asserted"
                ),
                "evidence_spans": evidence_count,
                "bound_evidence_spans": evidence_bound,
                "latency_ms": result.trace.latency_ms if result.trace else 0,
                "structural_warnings": structural_warnings,
                "model_warning_count": len(result.warnings),
                "model_warnings": result.warnings,
            }
        )

    return {
        "summary": {
            "chunk_count": len(chunks),
            "result_count": chunks_with_result,
            "valid_result_rate": _ratio(chunks_valid, len(chunks)),
            "evidence_span_binding_rate": _ratio(bound_evidence, total_evidence),
            "claim_coverage_rate": _ratio(chunks_with_claims, chunks_with_result),
            "weak_modality_coverage_rate": _ratio(weak_chunks_covered, weak_chunks),
            "weak_modality_chunk_count": weak_chunks,
            "relation_count": total_relations,
            "claim_count": total_claims,
            "avg_latency_ms": round(
                sum(row["latency_ms"] for row in rows) / chunks_with_result,
                2,
            )
            if chunks_with_result
            else 0,
            "max_latency_ms": max((row["latency_ms"] for row in rows), default=0),
        },
        "rows": rows,
    }


def _to_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    rows = report["rows"]
    lines = [
        "# 抽取稳定性报告",
        "",
        "本报告按输入 chunk 汇总结构有效性、证据绑定、claim 覆盖和模型自报 warning。它不代表语义准确率最终结论。",
        "",
        "## 总览",
        "",
        f"- 输入 chunk 数：{summary['chunk_count']}",
        f"- 返回结果数：{summary['result_count']}",
        f"- 结构有效率：{summary['valid_result_rate']:.2f}",
        f"- evidence span 绑定率：{summary['evidence_span_binding_rate']:.2f}",
        f"- claim 覆盖率：{summary['claim_coverage_rate']:.2f}",
        f"- 弱表达覆盖率：{summary['weak_modality_coverage_rate']:.2f}",
        f"- 关系数：{summary['relation_count']}",
        f"- claim 数：{summary['claim_count']}",
        f"- 平均耗时：{summary['avg_latency_ms']:.0f} ms",
        f"- 最大耗时：{summary['max_latency_ms']} ms",
        "",
        "## 分文档结果",
        "",
        "| 标题 | 状态 | 实体 | 关系 | claim | 非 asserted claim | 证据绑定 | 耗时 ms | 模型 warning |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {title} | {status} | {entities} | {relations} | {claims} | "
            "{non_asserted_claims} | {bound_evidence_spans}/{evidence_spans} | "
            "{latency_ms} | {model_warning_count} |".format(**row)
        )

    warning_rows = [
        row for row in rows if row["structural_warnings"] or row["model_warnings"]
    ]
    if warning_rows:
        lines.extend(["", "## Warning 明细", ""])
        for row in warning_rows:
            lines.append(f"### {row['title']}")
            if row["structural_warnings"]:
                lines.append(
                    "- 结构 warning："
                    + "；".join(str(item) for item in row["structural_warnings"])
                )
            for warning in row["model_warnings"]:
                lines.append(f"- 模型 warning：{warning}")
            lines.append("")
    return "\n".join(lines)


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def _has_weak_language(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in set(WEAK_MODALITY_TERMS) | set(NEGATION_TERMS))


if __name__ == "__main__":
    sys.exit(main())
