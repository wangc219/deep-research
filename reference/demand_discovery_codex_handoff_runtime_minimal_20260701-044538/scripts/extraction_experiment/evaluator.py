"""Evaluation utilities for extraction experiment outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from models import DocumentChunk, ExtractionResult
from schema import NEGATION_TERMS, WEAK_MODALITY_TERMS


def evaluate_group(
    adapter_name: str,
    results: list[ExtractionResult],
    chunks_by_id: dict[str, DocumentChunk],
) -> dict[str, Any]:
    validation_warnings: list[str] = []
    evidence_items = 0
    bound_evidence_items = 0
    relation_or_claim_items = 0
    relation_or_claim_items_with_evidence = 0
    trace_complete = 0
    chunks_with_claims = 0
    weak_chunks = 0
    weak_chunks_with_non_asserted_claim = 0
    model_warning_count = 0
    model_warnings_sample: list[str] = []

    for result in results:
        chunk = chunks_by_id.get(result.chunk_id)
        chunk_text = chunk.text if chunk else None
        model_warning_count += len(result.warnings)
        if len(model_warnings_sample) < 20:
            model_warnings_sample.extend(result.warnings[: 20 - len(model_warnings_sample)])
        warnings = result.validate(chunk_text)
        validation_warnings.extend(warnings)

        evidence_by_id = {span.evidence_id: span for span in result.evidence_spans}
        for span in result.evidence_spans:
            evidence_items += 1
            if chunk_text is not None and span.quote and span.quote in chunk_text:
                bound_evidence_items += 1

        for relation in result.relations:
            relation_or_claim_items += 1
            if relation.evidence_span_ids and all(
                evidence_id in evidence_by_id for evidence_id in relation.evidence_span_ids
            ):
                relation_or_claim_items_with_evidence += 1

        for claim in result.claims:
            relation_or_claim_items += 1
            if claim.evidence_span_ids and all(
                evidence_id in evidence_by_id for evidence_id in claim.evidence_span_ids
            ):
                relation_or_claim_items_with_evidence += 1

        if result.trace and result.trace.schema_version and result.trace.model:
            trace_complete += 1
        if result.claims:
            chunks_with_claims += 1

        if chunk and _has_weak_language(chunk.text):
            weak_chunks += 1
            if any(claim.modality != "asserted" for claim in result.claims):
                weak_chunks_with_non_asserted_claim += 1

    result_count = len(results)
    return {
        "adapter_name": adapter_name,
        "result_count": result_count,
        "trace_models": _unique_trace_values(results, "model"),
        "prompt_versions": _unique_trace_values(results, "prompt_version"),
        "schema_versions": _unique_trace_values(results, "schema_version"),
        "valid_result_rate": _ratio(
            result_count - _results_with_warnings(results, chunks_by_id),
            result_count,
        ),
        "warning_count": len(validation_warnings),
        "warnings_sample": validation_warnings[:20],
        "model_warning_count": model_warning_count,
        "model_warnings_sample": model_warnings_sample[:20],
        "evidence_span_count": evidence_items,
        "evidence_span_binding_rate": _ratio(bound_evidence_items, evidence_items),
        "relation_or_claim_count": relation_or_claim_items,
        "relation_or_claim_evidence_rate": _ratio(
            relation_or_claim_items_with_evidence,
            relation_or_claim_items,
        ),
        "claim_coverage_rate": _ratio(chunks_with_claims, result_count),
        "weak_modality_chunk_count": weak_chunks,
        "weak_modality_coverage_rate": _ratio(
            weak_chunks_with_non_asserted_claim,
            weak_chunks,
        ),
        "trace_completeness_rate": _ratio(trace_complete, result_count),
    }


def write_evaluation_summary(
    output_dir: Path,
    summaries: list[dict[str, Any]],
    skipped_groups: list[str],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "groups": summaries,
        "skipped_groups": skipped_groups,
    }
    (output_dir / "evaluation_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "evaluation_summary.md").write_text(
        _summary_markdown(summaries, skipped_groups),
        encoding="utf-8",
    )


def _summary_markdown(
    summaries: list[dict[str, Any]],
    skipped_groups: list[str],
) -> str:
    lines = [
        "# 第一轮抽取实验评价摘要",
        "",
        "本摘要只评价结构性指标，不代表事实图谱入库结论。",
        "",
        "## 结果概览",
        "",
        "| 方案 | 模型/模式 | prompt | 结果数 | 有效率 | 证据 span 绑定率 | 关系/声明证据率 | claim 覆盖率 | 弱表达 chunk 数 | 弱表达覆盖率 | trace 完整率 | 结构 warning 数 | 模型 warning 数 |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for summary in summaries:
        lines.append(
            "| {adapter_name} | {trace_models} | {prompt_versions} | "
            "{result_count} | {valid_result_rate:.2f} | "
            "{evidence_span_binding_rate:.2f} | {relation_or_claim_evidence_rate:.2f} | "
            "{claim_coverage_rate:.2f} | {weak_modality_chunk_count} | {weak_modality_coverage_rate:.2f} | "
            "{trace_completeness_rate:.2f} | {warning_count} | {model_warning_count} |".format(**summary)
        )

    if skipped_groups:
        lines.extend(["", "## 跳过的方案", ""])
        for group_name in skipped_groups:
            lines.append(f"- `{group_name}`：未提供预计算 ExtractionResult JSONL。")

    lines.extend(
        [
            "",
            "## 使用说明",
            "",
            "- A 组结果可来自 offline 或 llm 模式；具体模式以表格中的 `模型/模式`、`prompt` 和结果 trace 为准。",
            "- `结构 warning` 来自统一契约校验；`模型 warning` 来自适配器或 LLM 自报说明，不直接代表结构无效。",
            "- B/C 组需要先由对应框架生成并适配为统一 `ExtractionResult` JSONL，再纳入本评价器。",
            "- 抽取准确率、SourceClaim 语义质量和工程成本需要结合人工抽样审核补充。",
            "",
        ]
    )
    return "\n".join(lines)


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def _unique_trace_values(results: list[ExtractionResult], field_name: str) -> str:
    values = sorted(
        {
            str(getattr(result.trace, field_name, ""))
            for result in results
            if result.trace is not None and getattr(result.trace, field_name, "")
        }
    )
    if not values:
        return ""
    if len(values) <= 3:
        return ", ".join(values)
    return ", ".join(values[:3]) + f" (+{len(values) - 3})"


def _results_with_warnings(
    results: list[ExtractionResult],
    chunks_by_id: dict[str, DocumentChunk],
) -> int:
    count = 0
    for result in results:
        chunk = chunks_by_id.get(result.chunk_id)
        if result.validate(chunk.text if chunk else None):
            count += 1
    return count


def _has_weak_language(text: str) -> bool:
    lowered = text.lower()
    terms = set(WEAK_MODALITY_TERMS) | set(NEGATION_TERMS)
    return any(term in lowered for term in terms)
