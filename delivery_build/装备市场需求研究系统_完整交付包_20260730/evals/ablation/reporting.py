from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import zipfile

from evals.aggregate import bootstrap_interval


ABLATION_LABELS = {
    "full_method": "完整方法",
    "no_multisource_baseline": "去多源基线",
    "no_winning_mechanism": "去制胜机理",
}


def effect_summary(comparison: dict[str, Any], ablation_id: str) -> dict[str, Any]:
    systems = comparison.get("systems", {})
    full = systems.get("full_method", {})
    ablated = systems.get(ablation_id, {})
    delta = float(full.get("score_rate", 0.0)) - float(ablated.get("score_rate", 0.0))
    paired_differences = [
        1.0
        if row.get("winner") == "full_method"
        else -1.0
        if row.get("winner") == ablation_id
        else 0.0
        for row in comparison.get("query_outcomes", [])
    ]
    if paired_differences:
        lower, upper = bootstrap_interval(
            paired_differences,
            samples=5000,
            seed=20260726,
        )
    else:
        # Backward-compatible fallback for imported aggregate summaries that
        # predate per-Query outcomes.
        full_ci = list(full.get("bootstrap_95pct", [0.0, 0.0]))
        ablated_ci = list(ablated.get("bootstrap_95pct", [0.0, 0.0]))
        lower = float(full_ci[0] if full_ci else 0.0) - float(
            ablated_ci[1] if len(ablated_ci) > 1 else 0.0
        )
        upper = float(full_ci[1] if len(full_ci) > 1 else 0.0) - float(
            ablated_ci[0] if ablated_ci else 0.0
        )
    status = (
        "supported"
        if delta > 0 and lower > 0
        else "directional"
        if delta > 0
        else "unsupported"
    )
    return {
        "ablation_id": ablation_id,
        "score_delta": round(delta, 4),
        "paired_bootstrap_95pct": [round(lower, 4), round(upper, 4)],
        "conservative_95pct": [round(lower, 4), round(upper, 4)],
        "status": status,
    }


def write_ablation_report(
    root: Path,
    *,
    manifest: dict[str, Any],
    summary: dict[str, Any],
) -> Path:
    lines = [
        f"# 消融实验报告：{manifest['experiment_id']}",
        "",
        "## 1. 实验配置",
        "",
        f"- 数据集：`{manifest['dataset_id']}`",
        f"- Query 数量：{manifest.get('query_count', 0)}",
        f"- 控制组来源：{manifest.get('control_source', '')}",
        f"- 运行模式：{manifest.get('mode', '')}",
        f"- 结论级别：{'探索性' if manifest.get('exploratory_only') else '正式'}",
        "",
        "| 实验组 | 基线 | 制胜机理 | L1-L4 |",
        "|---|---|---|---|",
        "| 完整方法 | 多角色、多通道 | S1-S6 | 启用 |",
        "| 去多源基线 | 单通用 Agent、单通道 | 单次 S1-S6 | 关闭 |",
        "| 去制胜机理 | 完整多源基线 | 跳过 | 关闭 |",
        "",
        "## 2. 有效性检查",
        "",
    ]
    validity = manifest.get("validity", {})
    for variant, row in validity.items():
        lines.append(
            f"- {ABLATION_LABELS.get(variant, variant)}："
            f"{'通过' if row.get('valid') else '无效'}"
            + (f"；{row.get('reason')}" if row.get("reason") else "")
        )
    lines.extend(["", "## 3. Judge 结果", ""])
    for variant, comparison in summary.get("comparisons", {}).items():
        effect = summary.get("effects", {}).get(variant, {})
        full = comparison.get("systems", {}).get("full_method", {})
        ablated = comparison.get("systems", {}).get(variant, {})
        status_label = {
            "supported": "设计贡献得到支持",
            "directional": "仅有方向性证据",
            "unsupported": "当前数据不支持",
        }.get(effect.get("status"), "未形成结论")
        lines.extend(
            [
                f"### 完整方法 vs {ABLATION_LABELS.get(variant, variant)}",
                "",
                f"- 完整方法：{full.get('wins', 0)}胜 / {full.get('ties', 0)}平 / {full.get('losses', 0)}负，得分率 {float(full.get('score_rate', 0))*100:.1f}%",
                f"- 消融方法：{ablated.get('wins', 0)}胜 / {ablated.get('ties', 0)}平 / {ablated.get('losses', 0)}负，得分率 {float(ablated.get('score_rate', 0))*100:.1f}%",
                f"- 配对得分差：{float(effect.get('score_delta', 0))*100:.1f}%",
                f"- 配对 Bootstrap 95% 区间：{effect.get('paired_bootstrap_95pct', effect.get('conservative_95pct', [0, 0]))}",
                f"- 结论：**{status_label}**",
                "",
            ]
        )
        dimensions = comparison.get("dimension_votes", {})
        if dimensions:
            lines.extend(["| 维度 | 完整方法 | 平 | 消融组 |", "|---|---:|---:|---:|"])
            for dimension, votes in dimensions.items():
                lines.append(
                    f"| {dimension} | {votes.get('full_method', 0)} | {votes.get('tie', 0)} | {votes.get(variant, 0)} |"
                )
            lines.append("")
        runtime = comparison.get("runtime", {})
        if runtime:
            lines.extend(
                [
                    "| 实验组 | 完成率 | 平均耗时(秒) | 平均模型调用量 | 平均估算成本 |",
                    "|---|---:|---:|---:|---:|",
                ]
            )
            for system_id in ("full_method", variant):
                metrics = runtime.get(system_id, {})
                usage = metrics.get("mean_usage", {})
                call_count = usage.get("model_calls", usage.get("calls", 0))
                lines.append(
                    f"| {ABLATION_LABELS.get(system_id, system_id)} | "
                    f"{float(metrics.get('completion_rate', 0))*100:.1f}% | "
                    f"{float(metrics.get('mean_duration_seconds', 0)):.3f} | "
                    f"{float(call_count or 0):.3f} | "
                    f"{float(metrics.get('mean_estimated_cost', 0)):.6f} |"
                )
            lines.append("")
    lines.extend(
        [
            "## 4. 解释边界",
            "",
            "- 置信区间跨越 0 时，只能报告方向性证据，不能宣称核心设计已被统计证明。",
            "- 绑定历史项目报告且模型、时点或执行配置不完全一致时，本次结果自动降级为探索性。",
            "- 任一消融运行出现被禁止的 L1-L4、Recall 或被移除阶段事件时，该比较不进入有效结论。",
            "",
        ]
    )
    path = root / "ablation-report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def build_bundle(root: Path) -> Path:
    target = root / "ablation-bundle.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*")):
            if path.is_file() and path != target:
                archive.write(path, path.relative_to(root))
    return target


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
