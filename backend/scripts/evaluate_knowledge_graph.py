#!/usr/bin/env python3
"""生成知识图谱密封测试、阈值校准、对比评测和 Pilot 验收报告。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from platform_core.knowledge.training import (
    assess_pilot_acceptance,
    audit_gold_dataset,
    calibrate_acceptance_policy,
    compare_retrieval_methods,
    evaluate_graph_retrieval_quality,
    evaluate_innovation_quality,
    evaluate_ie_predictions,
    load_gold_jsonl,
    load_prediction_jsonl,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", required=True, help="平台统一金标 JSONL")
    parser.add_argument("--predictions", required=True, help="统一预测 JSONL")
    parser.add_argument("--pipeline-revision", required=True)
    parser.add_argument("--build-stats", help="Pilot 构建统计 JSON")
    parser.add_argument("--operational-checks", help="运行验收布尔项 JSON")
    parser.add_argument("--retrieval-cases", help="四方案检索对比 JSON/JSONL")
    parser.add_argument(
        "--graph-retrieval-cases",
        help="实体/三元组双通道、多跳及跨文档路径人工判断 JSON/JSONL",
    )
    parser.add_argument("--innovation-cases", help="四方案创新质量人工评测 JSON/JSONL")
    parser.add_argument("--output", required=True, help="报告输出目录")
    parser.add_argument("--allow-non-pilot-gold", action="store_true", help="开发期允许非 210/30/60 数据集")
    parser.add_argument("--require-pass", action="store_true", help="综合验收未通过时返回非零退出码")
    args = parser.parse_args()

    gold_path = Path(args.gold)
    prediction_path = Path(args.predictions)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)

    gold = load_gold_jsonl(gold_path)
    predictions = load_prediction_jsonl(prediction_path)
    expected_splits = None
    if args.allow_non_pilot_gold:
        expected_splits = {
            split: sum(document.split == split for document in gold) for split in ("train", "dev", "test")
        }
    gold_audit = audit_gold_dataset(
        gold,
        expected_splits=expected_splits,
        require_pilot_provenance=not args.allow_non_pilot_gold,
    )
    if args.allow_non_pilot_gold:
        gold_audit = {
            **gold_audit,
            "evaluation_scope": "development_only",
            "pilot_ready": False,
            "errors": [
                *gold_audit["errors"],
                "开发期非 210/30/60 数据集不得生成正式 Pilot 通过结论",
            ],
        }
    else:
        gold_audit["evaluation_scope"] = "formal_pilot"

    test_gold = [document for document in gold if document.split == "test"]
    test_ids = {document.document_id for document in test_gold}
    test_predictions = [document for document in predictions if document.document_id in test_ids]
    sealed_test_metrics = evaluate_ie_predictions(test_gold, test_predictions)
    calibration = calibrate_acceptance_policy(
        gold,
        predictions,
        pipeline_revision=args.pipeline_revision,
    )

    build_stats = _load_json_object(args.build_stats) if args.build_stats else _empty_build_stats()
    operational_checks = _load_json_object(args.operational_checks) if args.operational_checks else {}
    retrieval = None
    if args.retrieval_cases:
        retrieval = compare_retrieval_methods(_load_json_records(args.retrieval_cases))
    graph_retrieval_quality = None
    if args.graph_retrieval_cases:
        graph_retrieval_quality = evaluate_graph_retrieval_quality(_load_json_records(args.graph_retrieval_cases))
    innovation_quality = None
    if args.innovation_cases:
        innovation_quality = evaluate_innovation_quality(_load_json_records(args.innovation_cases))
    acceptance = assess_pilot_acceptance(
        gold_audit=gold_audit,
        sealed_test_metrics=sealed_test_metrics,
        build_stats=build_stats,
        operational_checks=operational_checks,
        retrieval_comparison=retrieval,
        graph_retrieval_quality=graph_retrieval_quality,
        innovation_quality=innovation_quality,
    )

    reports = {
        "gold-audit.json": gold_audit,
        "sealed-test-metrics.json": sealed_test_metrics,
        "acceptance-policy.json": calibration,
        "pilot-acceptance.json": acceptance,
    }
    if retrieval is not None:
        reports["retrieval-comparison.json"] = retrieval
    if graph_retrieval_quality is not None:
        reports["graph-retrieval-quality.json"] = graph_retrieval_quality
    if innovation_quality is not None:
        reports["innovation-quality.json"] = innovation_quality
    for filename, payload in reports.items():
        _write_json(output / filename, payload)

    input_paths = [gold_path, prediction_path]
    input_paths.extend(
        Path(path)
        for path in (
            args.build_stats,
            args.operational_checks,
            args.retrieval_cases,
            args.graph_retrieval_cases,
            args.innovation_cases,
        )
        if path
    )
    manifest = {
        "report_contract": "defense-kg-evaluation-bundle-v4",
        "pipeline_revision": args.pipeline_revision,
        "inputs": {str(path): _sha256(path) for path in input_paths},
        "reports": {filename: _sha256(output / filename) for filename in sorted(reports)},
        "pilot_passed": acceptance["passed"],
        "calibration_ready": calibration["calibrated"],
    }
    _write_json(output / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 2 if args.require_pass and not acceptance["passed"] else 0


def _empty_build_stats() -> dict[str, Any]:
    return {
        "source_documents": 0,
        "paper_documents": 0,
        "patent_documents": 0,
        "documents_with_build_runs": 0,
        "accepted_entities": 0,
        "accepted_relations": 0,
        "duplicate_relation_mentions_excluded": False,
        "unreviewed_hypotheses_excluded": False,
    }


def _load_json_object(path: str) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} 必须是 JSON 对象")
    return payload


def _load_json_records(path: str) -> list[dict[str, Any]]:
    source = Path(path)
    content = source.read_text(encoding="utf-8")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        payload = [json.loads(line) for line in content.splitlines() if line.strip()]
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"{path} 必须是 JSON 数组或 JSONL")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
