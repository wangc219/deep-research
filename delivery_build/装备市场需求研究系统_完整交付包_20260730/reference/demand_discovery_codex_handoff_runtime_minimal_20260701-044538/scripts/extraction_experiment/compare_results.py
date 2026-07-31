"""Write a path comparison report from extraction evaluation summaries."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SCORE_WEIGHTS = {
    "valid_result_rate": 15,
    "evidence_span_binding_rate": 20,
    "relation_or_claim_evidence_rate": 15,
    "claim_coverage_rate": 15,
    "weak_modality_coverage_rate": 10,
    "trace_completeness_rate": 10,
    "structure_warning_free_rate": 15,
}


def main() -> None:
    args = _parse_args()
    payload = json.loads(Path(args.summary).read_text(encoding="utf-8"))
    report = build_report(payload)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"Wrote comparison report to {output}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a Markdown comparison report for A/B/C extraction paths."
    )
    parser.add_argument(
        "--summary",
        required=True,
        help="Path to evaluation_summary.json.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to write comparison_report.md.",
    )
    return parser.parse_args()


def build_report(payload: dict[str, Any]) -> str:
    groups = payload.get("groups", [])
    scored_groups = [
        {**group, "structural_score": structural_score(group)} for group in groups
    ]
    ranked_groups = sorted(
        scored_groups,
        key=lambda group: group["structural_score"],
        reverse=True,
    )

    lines = [
        "# A/B/C 抽取路径对比报告",
        "",
        "本报告基于统一 `ExtractionResult` 结构性评价生成，只比较当前样例下的契约服从、证据绑定、SourceClaim 保留和 trace 完整性；不代表全量语义准确率或召回率。",
        "",
        "## 结构性评分",
        "",
        "| 排名 | 路径 | 模型/模式 | prompt | 结构分 | 有效率 | 证据绑定率 | 关系/声明证据率 | claim 覆盖率 | 弱表达覆盖率 | trace 完整率 | 结构 warning | 模型 warning |",
        "|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for rank, group in enumerate(ranked_groups, start=1):
        lines.append(
            "| {rank} | {adapter_name} | {trace_models} | {prompt_versions} | "
            "{structural_score:.1f} | {valid_result_rate:.2f} | "
            "{evidence_span_binding_rate:.2f} | {relation_or_claim_evidence_rate:.2f} | "
            "{claim_coverage_rate:.2f} | {weak_modality_coverage_rate:.2f} | "
            "{trace_completeness_rate:.2f} | {warning_count} | {model_warning_count} |".format(
                rank=rank,
                **group,
            )
        )

    lines.extend(
        [
            "",
            "## 路径判断",
            "",
            *_path_judgements(scored_groups),
            "",
            "## 解释边界",
            "",
            "- 非 A 路径可能来自框架输出形态代理，也可能来自真实框架调用；具体来源以表格中的 `模型/模式`、`prompt` 和结果 trace 为准。",
            "- 结构分会奖励 schema、证据、claim 和 trace，但不会评价抽取语义是否正确。",
            "- 若样例中没有弱表达语句，弱表达覆盖率不纳入结构分权重；表格仍保留原始指标。",
            "- 下一步若要评价真实框架效果，需要接入对应依赖和真实 LLM 调用，再用同一输入、同一评价器复跑。",
            "",
        ]
    )
    return "\n".join(lines)


def structural_score(group: dict[str, Any]) -> float:
    weighted_sum = 0.0
    weight_sum = 0
    for metric_name, weight in SCORE_WEIGHTS.items():
        if metric_name == "structure_warning_free_rate":
            result_count = int(group.get("result_count", 0) or 0)
            warning_count = int(group.get("warning_count", 0) or 0)
            metric_value = 0.0 if result_count == 0 else max(0.0, 1 - warning_count / result_count)
        elif metric_name == "weak_modality_coverage_rate":
            if int(group.get("weak_modality_chunk_count", 0) or 0) == 0:
                continue
            metric_value = float(group.get(metric_name, 0.0) or 0.0)
        else:
            metric_value = float(group.get(metric_name, 0.0) or 0.0)
        weighted_sum += metric_value * weight
        weight_sum += weight
    if weight_sum == 0:
        return 0.0
    return round(weighted_sum / weight_sum * 100, 1)


def _path_judgements(groups: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    by_name = {str(group.get("adapter_name", "")): group for group in groups}

    group_a = by_name.get("group_a_schema_guided")
    if group_a:
        lines.append(
            "- A 组适合作为主线候选：它在当前样例中保留了 SourceClaim，trace 中保留了真实模型/prompt 信息，能直接服务后续 CandidateExtraction 和人工评审。"
        )
        if (
            int(group_a.get("weak_modality_chunk_count", 0) or 0) > 0
            and float(group_a.get("weak_modality_coverage_rate", 0.0) or 0.0) < 1.0
        ):
            lines.append(
                "- A 组仍有需要调优的点：样例中存在弱表达或来源判断语句，但未全部转成非 asserted claim，后续应加强 prompt 和人工抽样审核。"
            )

    group_b = by_name.get("group_b_llamaindex_schema_path")
    if group_b:
        lines.append(
            "- B 组适合作为辅助路径：路径抽取形态对实体关系图较友好，但当前代理输出缺少 SourceClaim，需额外治理层才能进入事实候选。"
        )

    group_c = by_name.get("group_c_neo4j_kg_builder")
    if group_c:
        prompt_versions = str(group_c.get("prompt_versions", ""))
        if "enhanced-schema" in prompt_versions:
            lines.append(
                "- C 组本次来自真实 Neo4j GraphRAG KG Builder 增强版：通过自定义 prompt 和适配器已能产出 SourceClaim 与精确 evidence span，但输出仍偏实体关系图，claim_type/modality 仍需项目规则和人工抽样审核。"
            )
        elif "neo4j-graphrag-simple-kg-pipeline" in prompt_versions:
            lines.append(
                "- C 组本次来自真实 Neo4j GraphRAG KG Builder：输出更偏实体关系图，并包含 lexical graph；claim、精确证据 span 和项目 schema 适配仍需要在写图前完成。"
            )
        else:
            lines.append(
                "- C 组适合作为图构建/数据库路线对照：输出更偏实体关系图，claim、证据治理和项目 schema 适配需要在写图前完成。"
            )

    if not lines:
        lines.append("- 当前摘要中没有可比较的组。")
    return lines


if __name__ == "__main__":
    main()
