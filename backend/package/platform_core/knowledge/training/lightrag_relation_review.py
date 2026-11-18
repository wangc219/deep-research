"""生成仅供本地人工复核的 LightRAG 关系补抽审核包。"""

from __future__ import annotations

import hashlib
from typing import Any

from platform_core.knowledge.graphs.lightrag_relation_completion import match_relation_cues

from .lightrag_ablation import AblationInput


def build_relation_completion_review_pack(
    inputs: list[AblationInput],
    baseline_results: list[dict[str, Any]],
    enhanced_results: list[dict[str, Any]],
    *,
    source_report_sha256: str,
) -> dict[str, Any]:
    """列出增强臂新增关系及原文证据，不把模型候选冒充人工 Gold。"""
    if len(inputs) != len(baseline_results) or len(inputs) != len(enhanced_results):
        raise ValueError("关系审核包的输入与两组结果数量必须一致")

    items = []
    for source, baseline, enhanced in zip(inputs, baseline_results, enhanced_results, strict=True):
        baseline_keys = {_relation_key(item) for item in baseline.get("relations") or []}
        for relation in enhanced.get("relations") or []:
            relation_key = _relation_key(relation)
            if relation_key in baseline_keys or "lightrag_llm_gleaning" not in (relation.get("model_sources") or []):
                continue
            source_entity = _compact_endpoint(relation.get("source"))
            target_entity = _compact_endpoint(relation.get("target"))
            evidence = _evidence_rows(source.text, relation.get("evidence_spans"))
            label = str(relation.get("label") or "").strip().upper()
            items.append(
                {
                    "review_id": _review_id(source, relation_key),
                    "document_id_sha256": _sha256_text(source.document_id),
                    "block_id_sha256": _sha256_text(source.block_id),
                    "block_text_sha256": _sha256_text(source.text),
                    "source": source_entity,
                    "target": target_entity,
                    "relation_type": label,
                    "claim_level": relation.get("claim_level"),
                    "confidence": relation.get("confidence"),
                    "evidence": evidence,
                    "matched_cues": list(
                        dict.fromkeys(
                            cue for row in evidence for cue in match_relation_cues(label, str(row.get("text") or ""))
                        )
                    )[:4],
                    "model_sources": list(relation.get("model_sources") or []),
                    "duplicate_with_baseline": False,
                    "review_status": "pending_human_review",
                    "human_review": {
                        "decision": None,
                        "reviewer_identity": None,
                        "reviewed_at": None,
                        "notes": None,
                    },
                }
            )

    items.sort(key=lambda item: (item["document_id_sha256"], item["block_id_sha256"], item["review_id"]))
    return {
        "contract": "defense-lightrag-relation-review-v1",
        "source_report_sha256": source_report_sha256,
        "local_only": True,
        "contains_source_evidence_text": True,
        "candidate_provenance": "model_recall_proxy",
        "gold_status": "not_gold_pending_human_review",
        "instructions": (
            "逐项核对端点、方向、关系类型和 evidence 原文；只有真实人员填写身份、时间和决定后，"
            "相应记录才可进入人工审核结果。"
        ),
        "candidate_count": len(items),
        "items": items,
    }


def _relation_key(value: Any) -> tuple[Any, ...]:
    if not isinstance(value, dict):
        return ("invalid", repr(value))
    return (
        _endpoint_key(value.get("source")),
        str(value.get("label") or "").strip().upper(),
        _endpoint_key(value.get("target")),
    )


def _endpoint_key(value: Any) -> tuple[Any, ...]:
    if not isinstance(value, dict):
        return ("ref", str(value or ""))
    return (
        str(value.get("label") or ""),
        value.get("start"),
        value.get("end"),
        str(value.get("text") or ""),
    )


def _compact_endpoint(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"text": str(value or ""), "label": None, "start": None, "end": None}
    return {
        "text": str(value.get("text") or ""),
        "label": value.get("label"),
        "start": value.get("start"),
        "end": value.get("end"),
        "confidence": value.get("confidence"),
        "model_sources": list(value.get("model_sources") or []),
    }


def _evidence_rows(text: str, spans: Any) -> list[dict[str, Any]]:
    rows = []
    for span in spans or []:
        if not isinstance(span, dict):
            continue
        start, end = span.get("start"), span.get("end")
        if (
            isinstance(start, int)
            and not isinstance(start, bool)
            and isinstance(end, int)
            and not isinstance(end, bool)
            and 0 <= start < end <= len(text)
        ):
            rows.append({"start": start, "end": end, "text": text[start:end]})
    return rows


def _review_id(source: AblationInput, relation_key: tuple[Any, ...]) -> str:
    payload = repr((source.document_id, source.block_id, relation_key))
    return f"lrr-{_sha256_text(payload)[:20]}"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
