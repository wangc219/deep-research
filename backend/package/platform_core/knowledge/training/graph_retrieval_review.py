"""为实体/三元组双通道检索生成盲审包并回并人工判断。"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections import defaultdict
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .graph_retrieval_quality import (
    RETRIEVAL_METHODS,
    GraphRetrievalQualityCase,
    RetrievalJudgmentProvenance,
    evaluate_graph_retrieval_quality,
)

REVIEW_CONTRACT = "defense-kg-retrieval-blind-review-v1"
REVIEW_KEY_CONTRACT = "defense-kg-retrieval-blind-key-v1"


class RetrievedPathSnapshot(BaseModel):
    """尚未包含人工判断的一条检索路径。"""

    path_id: str = Field(min_length=1, max_length=128)
    relation_ids: list[str] = Field(min_length=1, max_length=12)
    chunk_ids: list[str] = Field(default_factory=list, max_length=100)
    file_ids: list[str] = Field(default_factory=list, max_length=100)


class GraphRetrievalRunSnapshot(BaseModel):
    """一个方法在同一查询上的原始返回快照。"""

    query_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=2000)
    method: Literal[
        "keyword",
        "entity_vector",
        "triple_vector",
        "lightrag_hybrid",
        "lightrag_mix",
    ]
    retrieved_entity_ids: list[str] = Field(default_factory=list, max_length=1000)
    retrieved_triple_ids: list[str] = Field(default_factory=list, max_length=2000)
    retrieved_paths: list[RetrievedPathSnapshot] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_unique_rankings(self):
        for label, values in (
            ("retrieved_entity_ids", self.retrieved_entity_ids),
            ("retrieved_triple_ids", self.retrieved_triple_ids),
            ("retrieved_paths", [item.path_id for item in self.retrieved_paths]),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} 不得包含重复 ID")
        return self


def prepare_blinded_graph_retrieval_review(
    records: list[GraphRetrievalRunSnapshot | dict[str, Any]],
    *,
    blind_key: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """隐藏方法名称并输出可分发评审文件与仅由评测负责人保存的映射。"""
    runs = [
        item if isinstance(item, GraphRetrievalRunSnapshot) else GraphRetrievalRunSnapshot.model_validate(item)
        for item in records
    ]
    if not runs:
        raise ValueError("检索运行快照不能为空")
    _validate_run_matrix(runs)

    secret = blind_key or secrets.token_hex(32)
    input_fingerprint = _canonical_sha256([run.model_dump(mode="json") for run in runs])
    review_runs = []
    mapping = []
    for run in sorted(runs, key=lambda item: (item.query_id, item.method)):
        run_id = hmac.new(
            secret.encode(),
            f"{run.query_id}\0{run.method}".encode(),
            hashlib.sha256,
        ).hexdigest()[:24]
        review_runs.append(
            {
                "run_id": run_id,
                "query_id": run.query_id,
                "query": run.query,
                "gold_entity_ids": [],
                "gold_triple_ids": [],
                "retrieved_entity_ids": run.retrieved_entity_ids,
                "retrieved_triple_ids": run.retrieved_triple_ids,
                "retrieved_paths": [
                    {
                        **path.model_dump(mode="json"),
                        "valid": None,
                        "relevant": None,
                    }
                    for path in run.retrieved_paths
                ],
            }
        )
        mapping.append({"run_id": run_id, "query_id": run.query_id, "method": run.method})

    review_runs.sort(key=lambda item: hmac.new(secret.encode(), item["run_id"].encode(), hashlib.sha256).hexdigest())
    review = {
        "review_contract": REVIEW_CONTRACT,
        "input_fingerprint_sha256": input_fingerprint,
        "instructions": {
            "gold": "填写该查询相关的权威实体和关系 ID；同一 query_id 的所有 run 必须一致",
            "paths": "逐条填写 valid 与 relevant 布尔值，不得留空",
            "provenance": "填写真实审核人、带时区时间和标注规范版本",
        },
        "judgment": {
            "source": "human",
            "reviewer_id": "",
            "reviewed_at": "",
            "guideline_version": "defense-kg-retrieval-review-v1",
        },
        "runs": review_runs,
    }
    key = {
        "key_contract": REVIEW_KEY_CONTRACT,
        "input_fingerprint_sha256": input_fingerprint,
        "review_sha256": _canonical_sha256(review),
        "mapping": sorted(mapping, key=lambda item: item["run_id"]),
    }
    return review, key


def finalize_blinded_graph_retrieval_review(
    review: dict[str, Any],
    key: dict[str, Any],
) -> list[dict[str, Any]]:
    """校验人工盲审完整性，恢复方法名称并生成正式质量评测输入。"""
    if review.get("review_contract") != REVIEW_CONTRACT:
        raise ValueError("review 不是受支持的盲审契约")
    if key.get("key_contract") != REVIEW_KEY_CONTRACT:
        raise ValueError("key 不是受支持的盲审映射契约")
    fingerprint = review.get("input_fingerprint_sha256")
    if fingerprint != key.get("input_fingerprint_sha256"):
        raise ValueError("review 与 key 的输入指纹不一致")

    provenance = RetrievalJudgmentProvenance.model_validate(review.get("judgment") or {})
    mapping_items = key.get("mapping")
    review_runs = review.get("runs")
    if not isinstance(mapping_items, list) or not isinstance(review_runs, list):
        raise ValueError("review.runs 与 key.mapping 必须是数组")
    method_by_run = {
        str(item.get("run_id") or ""): str(item.get("method") or "") for item in mapping_items if isinstance(item, dict)
    }
    if len(method_by_run) != len(mapping_items):
        raise ValueError("key.mapping 存在无效或重复 run_id")
    review_ids = [str(item.get("run_id") or "") for item in review_runs if isinstance(item, dict)]
    if len(review_ids) != len(review_runs) or len(review_ids) != len(set(review_ids)):
        raise ValueError("review.runs 存在无效或重复 run_id")
    if set(review_ids) != set(method_by_run):
        raise ValueError("review 与 key 的 run_id 集合不一致")

    output = []
    for item in review_runs:
        gold_entities = item.get("gold_entity_ids")
        gold_triples = item.get("gold_triple_ids")
        if not isinstance(gold_entities, list) or not isinstance(gold_triples, list):
            raise ValueError("每条评审必须包含 gold_entity_ids 和 gold_triple_ids 数组")
        if not gold_entities and not gold_triples:
            raise ValueError(f"run {item['run_id']} 尚未填写任何 Gold")
        paths = item.get("retrieved_paths")
        if not isinstance(paths, list):
            raise ValueError(f"run {item['run_id']} 的 retrieved_paths 必须是数组")
        for path in paths:
            if not isinstance(path, dict) or not isinstance(path.get("valid"), bool):
                raise ValueError(f"run {item['run_id']} 存在未判断 valid 的路径")
            if not isinstance(path.get("relevant"), bool):
                raise ValueError(f"run {item['run_id']} 存在未判断 relevant 的路径")

        case = GraphRetrievalQualityCase.model_validate(
            {
                "query_id": item.get("query_id"),
                "query": item.get("query"),
                "method": method_by_run[item["run_id"]],
                "gold_entity_ids": gold_entities,
                "gold_triple_ids": gold_triples,
                "retrieved_entity_ids": item.get("retrieved_entity_ids") or [],
                "retrieved_triple_ids": item.get("retrieved_triple_ids") or [],
                "retrieved_paths": paths,
                "judgment": provenance.model_dump(mode="json"),
            }
        )
        output.append(case.model_dump(mode="json"))

    report = evaluate_graph_retrieval_quality(output)
    if not report["complete"]:
        raise ValueError(f"盲审方法矩阵不完整: {report['missing_methods_by_query']}")
    return sorted(output, key=lambda item: (item["query_id"], item["method"]))


def _validate_run_matrix(runs: list[GraphRetrievalRunSnapshot]) -> None:
    methods_by_query: dict[str, set[str]] = defaultdict(set)
    query_text: dict[str, str] = {}
    for run in runs:
        if run.method in methods_by_query[run.query_id]:
            raise ValueError(f"查询 {run.query_id} 的方法 {run.method} 重复出现")
        methods_by_query[run.query_id].add(run.method)
        if query_text.setdefault(run.query_id, run.query) != run.query:
            raise ValueError(f"查询 {run.query_id} 的 query 文本不一致")
    missing = {
        query_id: sorted(set(RETRIEVAL_METHODS) - methods)
        for query_id, methods in methods_by_query.items()
        if set(RETRIEVAL_METHODS) - methods
    }
    if missing:
        raise ValueError(f"检索方法矩阵不完整: {missing}")


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
