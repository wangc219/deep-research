"""以确定性质量信号决定单个 Block 是否需要 LightRAG 增强。"""

from __future__ import annotations

import math
import re
from typing import Any

from platform_core.knowledge.graphs.lightrag_layout_normalization import build_layout_normalized_text_view
from platform_core.knowledge.graphs.lightrag_text_quality import detect_ocr_damage, substantive_text_metrics

ADAPTIVE_ROUTING_REVISION = "defense-lightrag-adaptive-routing-v1"
_TECHNICAL_SIGNAL = re.compile(
    r"(?:雷达|制导|探测|感知|通信|电子战|对抗|武器|装备|材料|算法|模型|波形|阵列|射频|"
    r"传感器|芯片|控制|仿真|试验|性能|能力|约束|MIMO|LFM|QPSK|ADC|FPGA|SAR)",
    re.IGNORECASE,
)


def decide_lightrag_adaptive_routing(
    text: str,
    base_result: dict[str, Any],
    options: dict[str, Any] | None,
) -> dict[str, Any]:
    """返回可审计路由决定；关闭时保持逐 Block 全量增强的旧语义。"""
    config = normalize_adaptive_routing_options(options)
    entities = list(base_result.get("entities") or [])
    relations = list(base_result.get("relations") or [])
    source_chars = len(text)
    entity_density = len(entities) * 100 / max(source_chars, 1)
    technical_signal_count = len(_TECHNICAL_SIGNAL.findall(text))
    lexical_metrics = substantive_text_metrics(text)
    ocr_damage_count = len(detect_ocr_damage(text))
    layout_deletion_count = 0
    if config["trigger_on_layout_damage"]:
        layout_deletion_count = len(build_layout_normalized_text_view(text).deletions)
    low_confidence_count = sum(
        1
        for item in [*entities, *relations]
        if _finite_confidence(item.get("confidence")) < config["low_confidence_threshold"]
    )
    metadata = base_result.get("metadata") or {}
    warnings = metadata.get("warnings") or []
    reasons = []
    if config["trigger_on_ocr_damage"] and ocr_damage_count:
        reasons.append("ocr_damage")
    if config["trigger_on_layout_damage"] and layout_deletion_count:
        reasons.append("layout_damage")
    if config["trigger_on_backend_warning"] and (metadata.get("feasible") is False or warnings):
        reasons.append("backend_warning")
    if (
        config["trigger_on_no_entities"]
        and source_chars >= config["min_source_chars"]
        and lexical_metrics["is_substantive"]
        and not entities
    ):
        reasons.append(
            "technical_text_without_entities" if technical_signal_count else "substantive_text_without_entities"
        )
    if (
        config["trigger_on_sparse_entities"]
        and source_chars >= config["min_source_chars"]
        and lexical_metrics["is_substantive"]
        and entity_density < config["min_entities_per_100_chars"]
    ):
        reasons.append("sparse_entity_density")
    if config["trigger_on_relation_gap"] and len(entities) >= config["relation_gap_min_entities"] and not relations:
        reasons.append("multiple_entities_without_relation")
    if config["trigger_on_low_confidence"] and low_confidence_count:
        reasons.append("low_confidence_candidates")

    enabled = config["enabled"]
    return {
        "revision": ADAPTIVE_ROUTING_REVISION,
        "enabled": enabled,
        "decision": "enhance" if not enabled or reasons else "skip",
        "should_enhance": not enabled or bool(reasons),
        "trigger_reasons": reasons,
        "metrics": {
            "source_chars": source_chars,
            "technical_signal_count": technical_signal_count,
            **lexical_metrics,
            "entity_count": len(entities),
            "relation_count": len(relations),
            "entity_density_per_100_chars": round(entity_density, 4),
            "low_confidence_count": low_confidence_count,
            "ocr_damage_count": ocr_damage_count,
            "layout_deletion_count": layout_deletion_count,
            "backend_warning_count": len(warnings) + int(metadata.get("feasible") is False),
        },
        "policy": config,
    }


def normalize_adaptive_routing_options(options: dict[str, Any] | None) -> dict[str, Any]:
    """校验自适应路由配置，供流水线规范化和直接构造增强器共用。"""
    if options is not None and not isinstance(options, dict):
        raise ValueError("llm_enhancement.adaptive_routing 必须是对象")
    raw = dict(options or {})
    enabled = _boolean(raw.get("enabled", False), "enabled")
    return {
        "enabled": enabled,
        "min_source_chars": _integer(raw.get("min_source_chars", 80), "min_source_chars", 1, 200_000),
        "min_entities_per_100_chars": _number(
            raw.get("min_entities_per_100_chars", 0.8),
            "min_entities_per_100_chars",
            0.0,
            100.0,
        ),
        "relation_gap_min_entities": _integer(
            raw.get("relation_gap_min_entities", 2),
            "relation_gap_min_entities",
            2,
            1000,
        ),
        "low_confidence_threshold": _number(
            raw.get("low_confidence_threshold", 0.75),
            "low_confidence_threshold",
            0.0,
            1.0,
        ),
        "trigger_on_ocr_damage": _boolean(raw.get("trigger_on_ocr_damage", True), "trigger_on_ocr_damage"),
        "trigger_on_layout_damage": _boolean(
            raw.get("trigger_on_layout_damage", True),
            "trigger_on_layout_damage",
        ),
        "trigger_on_backend_warning": _boolean(
            raw.get("trigger_on_backend_warning", True),
            "trigger_on_backend_warning",
        ),
        "trigger_on_no_entities": _boolean(
            raw.get("trigger_on_no_entities", True),
            "trigger_on_no_entities",
        ),
        "trigger_on_sparse_entities": _boolean(
            raw.get("trigger_on_sparse_entities", True),
            "trigger_on_sparse_entities",
        ),
        "trigger_on_relation_gap": _boolean(
            raw.get("trigger_on_relation_gap", True),
            "trigger_on_relation_gap",
        ),
        "trigger_on_low_confidence": _boolean(
            raw.get("trigger_on_low_confidence", True),
            "trigger_on_low_confidence",
        ),
    }


def _finite_confidence(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        return 1.0
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return normalized if math.isfinite(normalized) else 0.0


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"llm_enhancement.adaptive_routing.{field} 必须是布尔值")
    return value


def _integer(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"llm_enhancement.adaptive_routing.{field} 必须是 {minimum} 到 {maximum} 之间的整数")
    return value


def _number(value: Any, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"llm_enhancement.adaptive_routing.{field} 必须是数字")
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"llm_enhancement.adaptive_routing.{field} 必须是数字") from exc
    if not math.isfinite(normalized) or not minimum <= normalized <= maximum:
        raise ValueError(f"llm_enhancement.adaptive_routing.{field} 必须在 {minimum} 到 {maximum} 之间")
    return normalized
