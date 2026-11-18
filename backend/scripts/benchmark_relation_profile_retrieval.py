#!/usr/bin/env python3
"""用真实本地 embedding/Milvus 比较旧三元组文本与跨文档关系画像召回。"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from platform_core.knowledge.graphs.milvus_graph_vector_store import MilvusGraphVectorStore
from platform_core.knowledge.graphs.relation_semantic_profile import (
    RELATION_SEMANTIC_PROFILE_VERSION,
    build_relation_semantic_profile,
)
from platform_core.models.providers.cache import model_cache

PROBE_CONTRACT = "defense-lightrag-relation-profile-runtime-probe-v1"
DEFAULT_MODEL_SPEC = "local-embedding:BAAI/bge-m3"


def _cases() -> list[dict[str, Any]]:
    return [
        {
            "id": "relation-antijamming",
            "source_id": "entity-wideband-rf",
            "source_name": "宽带射频收发器",
            "source_label": "Component",
            "relation_type": "ENABLES_CAPABILITY",
            "target_id": "entity-antijamming",
            "target_name": "抗干扰能力",
            "target_label": "Capability",
            "mentions": [
                {
                    "file_id": "paper-a",
                    "claim_level": "Fact",
                    "evidence_quote": "频率捷变使接收链避开窄带阻塞干扰，提高复杂电磁环境下的抗干扰能力。",
                    "applicable_conditions": ["宽带工作模式"],
                },
                {
                    "file_id": "paper-b",
                    "claim_level": "Inference",
                    "evidence_quote": "多通道接收可降低压制式干扰对有效信号检测的影响。",
                    "applicable_conditions": ["多通道接收"],
                },
            ],
            "queries": ["频率捷变如何避开窄带阻塞干扰", "压制式干扰下多通道接收有什么作用"],
        },
        {
            "id": "relation-beamforming",
            "source_id": "entity-stap",
            "source_name": "空时自适应波束形成",
            "source_label": "AlgorithmModel",
            "relation_type": "MITIGATES",
            "target_id": "entity-mainlobe-jamming",
            "target_name": "主瓣干扰",
            "target_label": "Constraint",
            "mentions": [
                {
                    "file_id": "paper-c",
                    "claim_level": "Fact",
                    "evidence_quote": "空时联合协方差估计在干扰来向形成零陷，抑制主瓣与旁瓣干扰。",
                    "applicable_conditions": ["阵列校准误差受控"],
                },
                {
                    "file_id": "paper-d",
                    "claim_level": "Fact",
                    "evidence_quote": "训练样本不足时采用对角加载可提高自适应权值的稳健性。",
                    "applicable_conditions": ["小样本快拍"],
                },
            ],
            "queries": ["如何通过协方差估计在干扰来向形成零陷", "小样本快拍下怎样提高自适应权值稳健性"],
        },
        {
            "id": "relation-sic",
            "source_id": "entity-sic-device",
            "source_name": "碳化硅功率器件",
            "source_label": "Component",
            "relation_type": "IMPROVES",
            "target_id": "entity-power-density",
            "target_name": "功率密度",
            "target_label": "Metric",
            "mentions": [
                {
                    "file_id": "paper-e",
                    "claim_level": "Fact",
                    "evidence_quote": "宽禁带特性允许器件在高温强辐照环境保持较低漏电流。",
                    "applicable_conditions": ["高温强辐照"],
                },
                {
                    "file_id": "paper-f",
                    "claim_level": "Inference",
                    "evidence_quote": "降低开关损耗与散热体积可提升电源模块功率密度。",
                    "applicable_conditions": ["高频开关"],
                },
            ],
            "queries": ["高温强辐照环境下如何保持较低漏电流", "降低开关损耗和散热体积带来什么收益"],
        },
        {
            "id": "relation-multispectral",
            "source_id": "entity-multispectral-fusion",
            "source_name": "多光谱目标融合",
            "source_label": "KeyTechnology",
            "relation_type": "ENABLES_CAPABILITY",
            "target_id": "entity-target-recognition",
            "target_name": "目标识别能力",
            "target_label": "Capability",
            "mentions": [
                {
                    "file_id": "paper-g",
                    "claim_level": "Fact",
                    "evidence_quote": "红外热特征与毫米波散射特征互补可降低烟尘遮蔽造成的漏检。",
                    "applicable_conditions": ["烟尘遮蔽"],
                },
                {
                    "file_id": "paper-h",
                    "claim_level": "Inference",
                    "evidence_quote": "跨模态时空配准后进行置信度融合可改善弱小目标识别。",
                    "applicable_conditions": ["完成跨模态配准"],
                },
            ],
            "queries": ["烟尘遮蔽下怎样降低目标漏检", "跨模态时空配准后如何改善弱小目标识别"],
        },
    ]


def _distractors() -> list[dict[str, str]]:
    return [
        {
            "id": "noise-frequency-agile-radar",
            "source_id": "noise-source-1",
            "target_id": "noise-target-1",
            "content": "频率捷变雷达 → IMPROVES → 距离分辨率；窄带信号用于目标测距。",
        },
        {
            "id": "noise-multichannel-bus",
            "source_id": "noise-source-2",
            "target_id": "noise-target-2",
            "content": "多通道数据总线 → ENABLES_CAPABILITY → 体系互操作能力。",
        },
        {
            "id": "noise-jamming-source",
            "source_id": "noise-source-3",
            "target_id": "noise-target-3",
            "content": "压制式干扰机 → USED_IN → 电子对抗场景；宽带阻塞覆盖通信频段。",
        },
        {
            "id": "noise-covariance",
            "source_id": "noise-source-4",
            "target_id": "noise-target-4",
            "content": "协方差矩阵估计 → IMPLEMENTED_BY → 样本统计；用于信号相关性分析。",
        },
        {
            "id": "noise-array-calibration",
            "source_id": "noise-source-5",
            "target_id": "noise-target-5",
            "content": "阵列校准 → MITIGATES → 通道幅相误差；适用于小样本快拍。",
        },
        {
            "id": "noise-radiation-shield",
            "source_id": "noise-source-6",
            "target_id": "noise-target-6",
            "content": "辐照屏蔽结构 → MITIGATES → 高温强辐照环境影响。",
        },
        {
            "id": "noise-switching-loss",
            "source_id": "noise-source-7",
            "target_id": "noise-target-7",
            "content": "软开关控制 → REDUCES → 开关损耗；高频电源需要散热设计。",
        },
        {
            "id": "noise-infrared",
            "source_id": "noise-source-8",
            "target_id": "noise-target-8",
            "content": "红外成像器 → DETECTS → 热目标；烟尘遮蔽降低探测距离。",
        },
        {
            "id": "noise-registration",
            "source_id": "noise-source-9",
            "target_id": "noise-target-9",
            "content": "时空配准算法 → IMPLEMENTED_BY → 特征匹配；支持跨模态坐标转换。",
        },
        {
            "id": "noise-small-target",
            "source_id": "noise-source-10",
            "target_id": "noise-target-10",
            "content": "弱小目标检测器 → IMPROVES → 目标发现概率。",
        },
    ]


def _records(cases: list[dict[str, Any]], *, profile: bool) -> list[dict[str, str]]:
    records = []
    for item in cases:
        canonical = f"{item['source_name']} → {item['relation_type']} → {item['target_name']}"
        content = canonical
        if profile:
            content = build_relation_semantic_profile(
                relation_type=item["relation_type"],
                source_name=item["source_name"],
                source_label=item["source_label"],
                target_name=item["target_name"],
                target_label=item["target_label"],
                base_content=canonical,
                relation_mentions=item["mentions"],
            )
        records.append(
            {
                "id": item["id"],
                "source_id": item["source_id"],
                "target_id": item["target_id"],
                "content": content,
            }
        )
    return [*records, *_distractors()]


def _ranking_metrics(rankings: list[dict[str, Any]], *, k: int) -> dict[str, float]:
    ranks = [item["rank"] for item in rankings]
    return {
        f"recall_at_{k}": sum(rank is not None and rank <= k for rank in ranks) / len(ranks),
        "mrr": sum(1 / rank if rank is not None else 0 for rank in ranks) / len(ranks),
        f"ndcg_at_{k}": sum(1 / math.log2(rank + 1) if rank is not None and rank <= k else 0 for rank in ranks)
        / len(ranks),
    }


def _latency_summary(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "p50_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[max(math.ceil(len(ordered) * 0.95) - 1, 0)], 3),
        "mean_ms": round(statistics.fmean(ordered), 3),
    }


async def _evaluate(
    store: MilvusGraphVectorStore,
    *,
    kb_id: str,
    model_spec: str,
    cases: list[dict[str, Any]],
    top_k: int,
) -> dict[str, Any]:
    queries = [(item["id"], query) for item in cases for query in item["queries"]]
    await store.search_triples(
        kb_id=kb_id,
        query_text=queries[0][1],
        embedding_model_spec=model_spec,
        top_k=top_k,
    )
    rankings = []
    latencies = []
    for gold_id, query in queries:
        started = time.perf_counter()
        hits = await store.search_triples(
            kb_id=kb_id,
            query_text=query,
            embedding_model_spec=model_spec,
            top_k=top_k,
        )
        latencies.append((time.perf_counter() - started) * 1000)
        ids = [str(item.get("id")) for item in hits]
        rankings.append(
            {
                "query_sha256": hashlib.sha256(query.encode()).hexdigest(),
                "gold_id": gold_id,
                "rank": ids.index(gold_id) + 1 if gold_id in ids else None,
                "retrieved_ids": ids,
            }
        )
    return {
        "metrics": _ranking_metrics(rankings, k=top_k),
        "latency": _latency_summary(latencies),
        "rankings": rankings,
    }


async def run_probe(*, model_spec: str, top_k: int) -> dict[str, Any]:
    """执行临时集合探针并在结束时删除全部测试向量。"""
    info = model_cache.get_model_info(model_spec)
    if info is None or info.model_type != "embedding":
        raise ValueError(f"不可用的 embedding model spec: {model_spec}")
    cases = _cases()
    suffix = uuid4().hex[:12]
    baseline_kb_id = f"probe_relation_base_{suffix}"
    profile_kb_id = f"probe_relation_profile_{suffix}"
    store = MilvusGraphVectorStore()
    input_payload = {"cases": cases, "distractors": _distractors()}

    try:
        await store.upsert_graph_records(
            kb_id=baseline_kb_id,
            embedding_model_spec=model_spec,
            record_type="triple",
            records=_records(cases, profile=False),
        )
        await store.upsert_graph_records(
            kb_id=profile_kb_id,
            embedding_model_spec=model_spec,
            record_type="triple",
            records=_records(cases, profile=True),
        )
        baseline = await _evaluate(
            store,
            kb_id=baseline_kb_id,
            model_spec=model_spec,
            cases=cases,
            top_k=top_k,
        )
        profile = await _evaluate(
            store,
            kb_id=profile_kb_id,
            model_spec=model_spec,
            cases=cases,
            top_k=top_k,
        )
    finally:
        store.drop_graph_collections(baseline_kb_id)
        store.drop_graph_collections(profile_kb_id)

    delta = {key: round(profile["metrics"][key] - baseline["metrics"][key], 6) for key in baseline["metrics"]}
    return {
        "contract": PROBE_CONTRACT,
        "generated_at": datetime.now(UTC).isoformat(),
        "evaluation_scope": "synthetic_semantics_real_local_embedding_and_milvus",
        "quality_claim_allowed": False,
        "warning": "该探针验证真实运行行为，但不含人工 Gold，不能替代正式检索质量验收。",
        "relation_profile_version": RELATION_SEMANTIC_PROFILE_VERSION,
        "input_sha256": hashlib.sha256(
            json.dumps(input_payload, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest(),
        "model": {
            "spec": model_spec,
            "model_id": info.model_id,
            "dimension": info.dimension,
            "batch_size": info.batch_size,
        },
        "dataset": {
            "relation_count": len(cases),
            "distractor_count": len(_distractors()),
            "query_count": sum(len(item["queries"]) for item in cases),
            "top_k": top_k,
        },
        "baseline": baseline,
        "relation_profile": profile,
        "metric_delta": delta,
        "probe_passed": all(value >= 0 for value in delta.values()) and any(value > 0 for value in delta.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-spec", default=DEFAULT_MODEL_SPEC)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not 1 <= args.top_k <= 20:
        raise ValueError("top-k 必须在 1 到 20 之间")

    report = asyncio.run(run_probe(model_spec=args.model_spec, top_k=args.top_k))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "probe_passed": report["probe_passed"],
                "metric_delta": report["metric_delta"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["probe_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
