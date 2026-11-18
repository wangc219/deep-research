"""知识候选自动接受策略。

抽取器只负责产生候选和分数；本模块集中决定候选能否绕过人工审核，避免
各抽取阶段不应携带彼此冲突的准入逻辑。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from platform_core.knowledge.graphs.defense_ontology import (
    DEFENSE_ONTOLOGY_V1,
    canonical_entity_type,
    validate_relation_types,
)

DEFAULT_ACCEPTANCE_PROFILE_VERSION = "defense-pilot-v1"
MINIMUM_AUTO_ACCEPT_PRECISION = 0.90
DEFAULT_ENTITY_THRESHOLD = 0.95
DEFAULT_RELATION_THRESHOLD = 0.95
FUSE_CLOSED = "closed"
FUSE_OPEN = "open"


def default_acceptance_policy(pipeline_revision: str) -> dict[str, Any]:
    """返回安全默认策略；未经金标校准时不自动接受任何候选。"""
    return {
        "profile_version": DEFAULT_ACCEPTANCE_PROFILE_VERSION,
        "pipeline_revision": pipeline_revision,
        "calibrated_pipeline_revision": None,
        "calibrated": False,
        "entity_precision": None,
        "relation_precision": None,
        "minimum_precision": MINIMUM_AUTO_ACCEPT_PRECISION,
        "entity_default_threshold": DEFAULT_ENTITY_THRESHOLD,
        "relation_default_threshold": DEFAULT_RELATION_THRESHOLD,
        "entity_thresholds": {},
        "relation_thresholds": {},
        "calibrated_entity_types": [],
        "calibrated_relation_types": [],
        "calibration_report": {},
        "auto_accept_enabled": False,
        "fuse_state": FUSE_CLOSED,
        "fuse_reason": "",
    }


def normalize_acceptance_policy(
    value: dict[str, Any] | None,
    *,
    pipeline_revision: str,
) -> dict[str, Any]:
    """校验并固定一份可随 pipeline 配置持久化的准入策略快照。"""
    if value is not None and not isinstance(value, dict):
        raise ValueError("acceptance_policy 必须是对象")

    normalized = default_acceptance_policy(pipeline_revision)
    supplied = deepcopy(value or {})
    allowed = set(normalized)
    unknown = sorted(set(supplied) - allowed)
    if unknown:
        raise ValueError(f"acceptance_policy 包含未知字段: {', '.join(unknown)}")
    normalized.update(supplied)
    normalized["profile_version"] = _required_text(
        normalized["profile_version"],
        "acceptance_policy.profile_version",
    )
    normalized["pipeline_revision"] = pipeline_revision

    calibrated_revision = normalized.get("calibrated_pipeline_revision")
    normalized["calibrated_pipeline_revision"] = (
        _required_text(calibrated_revision, "acceptance_policy.calibrated_pipeline_revision")
        if calibrated_revision is not None
        else None
    )
    for field in ("calibrated", "auto_accept_enabled"):
        if not isinstance(normalized[field], bool):
            raise ValueError(f"acceptance_policy.{field} 必须是布尔值")

    normalized["minimum_precision"] = _probability(
        normalized["minimum_precision"],
        "acceptance_policy.minimum_precision",
    )
    if normalized["minimum_precision"] < MINIMUM_AUTO_ACCEPT_PRECISION:
        raise ValueError(f"acceptance_policy.minimum_precision 不得低于 {MINIMUM_AUTO_ACCEPT_PRECISION:.2f}")
    for field in ("entity_precision", "relation_precision"):
        value = normalized[field]
        normalized[field] = None if value is None else _probability(value, f"acceptance_policy.{field}")
    for field in ("entity_default_threshold", "relation_default_threshold"):
        normalized[field] = _probability(normalized[field], f"acceptance_policy.{field}")
    for field in ("entity_thresholds", "relation_thresholds"):
        normalized[field] = _threshold_map(normalized[field], f"acceptance_policy.{field}")
    for field in ("calibrated_entity_types", "calibrated_relation_types"):
        value = normalized[field]
        if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError(f"acceptance_policy.{field} 必须是非空字符串数组")
        normalized[field] = sorted(set(item.strip() for item in value))
    if not isinstance(normalized["calibration_report"], dict):
        raise ValueError("acceptance_policy.calibration_report 必须是对象")

    fuse_state = str(normalized["fuse_state"] or "").strip().lower()
    if fuse_state not in {FUSE_CLOSED, FUSE_OPEN}:
        raise ValueError("acceptance_policy.fuse_state 必须是 closed 或 open")
    normalized["fuse_state"] = fuse_state
    normalized["fuse_reason"] = str(normalized.get("fuse_reason") or "").strip()[:1000]
    if fuse_state == FUSE_OPEN and not normalized["fuse_reason"]:
        raise ValueError("自动接受熔断时必须记录 fuse_reason")

    if normalized["calibrated"]:
        if normalized["calibrated_pipeline_revision"] != pipeline_revision:
            raise ValueError("校准结果必须与当前 pipeline_revision 完全一致")
        minimum = normalized["minimum_precision"]
        if normalized["entity_precision"] is None or normalized["entity_precision"] < minimum:
            raise ValueError("实体校准 Precision 未达到自动接受门槛")
        if normalized["relation_precision"] is None or normalized["relation_precision"] < minimum:
            raise ValueError("关系校准 Precision 未达到自动接受门槛")

    return normalized


def apply_acceptance_policy(
    result: dict[str, Any],
    source_text: str,
    options: dict[str, Any] | None,
) -> dict[str, Any]:
    """依据固定策略设置实体和关系 mention 的审核状态。"""
    extractor_options = options or {}
    pipeline_revision = str(
        extractor_options.get("pipeline_revision")
        or result.get("metadata", {}).get("pipeline_revision")
        or "legacy-unversioned"
    )
    policy = normalize_acceptance_policy(
        extractor_options.get("acceptance_policy"),
        pipeline_revision=pipeline_revision,
    )
    eligible, blocked_reason = _auto_accept_eligibility(policy, pipeline_revision)

    entity_status_by_key: dict[tuple[str, str], str] = {}
    entity_reason_counts: dict[str, int] = {}
    accepted_entities = 0
    for entity in result["entities"]:
        reason = _entity_block_reason(entity, source_text, policy) if eligible else blocked_reason
        status = "accepted" if not reason else "pending"
        entity["review_status"] = status
        entity["acceptance_reason"] = "policy_accepted" if status == "accepted" else reason
        entity_status_by_key[_entity_key(entity)] = status
        if status == "accepted":
            accepted_entities += 1
        else:
            entity_reason_counts[reason] = entity_reason_counts.get(reason, 0) + 1

    relation_reason_counts: dict[str, int] = {}
    accepted_relations = 0
    for relation in result["relations"]:
        reason = (
            _relation_block_reason(relation, source_text, policy, entity_status_by_key) if eligible else blocked_reason
        )
        status = "accepted" if not reason else "pending"
        relation["review_status"] = status
        relation["acceptance_reason"] = "policy_accepted" if status == "accepted" else reason
        if status == "accepted":
            accepted_relations += 1
        else:
            relation_reason_counts[reason] = relation_reason_counts.get(reason, 0) + 1

    result.setdefault("metadata", {})["acceptance_policy"] = {
        "profile_version": policy["profile_version"],
        "pipeline_revision": pipeline_revision,
        "calibrated": policy["calibrated"],
        "auto_accept_eligible": eligible,
        "fuse_state": policy["fuse_state"],
        "blocked_reason": blocked_reason,
        "accepted_entities": accepted_entities,
        "pending_entities": len(result["entities"]) - accepted_entities,
        "accepted_relations": accepted_relations,
        "pending_relations": len(result["relations"]) - accepted_relations,
        "entity_pending_reasons": entity_reason_counts,
        "relation_pending_reasons": relation_reason_counts,
    }
    return result


def open_acceptance_fuse(policy: dict[str, Any], *, reason: str) -> dict[str, Any]:
    """生成暂停自动接受的策略快照，抽取与人工审核仍可继续。"""
    updated = deepcopy(policy)
    updated["fuse_state"] = FUSE_OPEN
    updated["fuse_reason"] = _required_text(reason, "fuse_reason")[:1000]
    return updated


def _auto_accept_eligibility(policy: dict[str, Any], pipeline_revision: str) -> tuple[bool, str]:
    if not policy["auto_accept_enabled"]:
        return False, "auto_accept_disabled"
    if policy["fuse_state"] == FUSE_OPEN:
        return False, "quality_fuse_open"
    if not policy["calibrated"]:
        return False, "profile_not_calibrated"
    if policy["calibrated_pipeline_revision"] != pipeline_revision:
        return False, "pipeline_revision_not_calibrated"
    minimum = policy["minimum_precision"]
    if policy["entity_precision"] is None or policy["entity_precision"] < minimum:
        return False, "entity_precision_below_gate"
    if policy["relation_precision"] is None or policy["relation_precision"] < minimum:
        return False, "relation_precision_below_gate"
    return True, ""


def _entity_block_reason(entity: dict[str, Any], source_text: str, policy: dict[str, Any]) -> str:
    label = canonical_entity_type(entity.get("label") or "")
    if label not in DEFENSE_ONTOLOGY_V1.entity_type_by_code:
        return "unknown_entity_type"
    calibrated_types = policy["calibrated_entity_types"]
    if calibrated_types and label not in calibrated_types:
        return "entity_type_not_calibrated"
    if entity.get("conflict") or entity.get("has_conflict"):
        return "conflict_detected"
    if not _span_matches_text(entity, source_text):
        return "entity_span_not_reconstructable"
    threshold = policy["entity_thresholds"].get(label, policy["entity_default_threshold"])
    if _confidence(entity) < threshold:
        return "entity_confidence_below_threshold"
    return ""


def _relation_block_reason(
    relation: dict[str, Any],
    source_text: str,
    policy: dict[str, Any],
    entity_status_by_key: dict[tuple[str, str], str],
) -> str:
    if relation.get("claim_level") != "Fact":
        return "claim_level_not_fact"
    if relation.get("expert_review_required"):
        return "expert_review_required"
    if relation.get("conflict") or relation.get("has_conflict"):
        return "conflict_detected"
    source = relation["source"]
    target = relation["target"]
    if (
        entity_status_by_key.get(_entity_key(source)) != "accepted"
        or entity_status_by_key.get(_entity_key(target)) != "accepted"
    ):
        return "endpoint_not_accepted"
    relation_type = str(relation.get("label") or "")
    calibrated_types = policy["calibrated_relation_types"]
    if calibrated_types and relation_type not in calibrated_types:
        return "relation_type_not_calibrated"
    if not validate_relation_types(source.get("label") or "", relation_type, target.get("label") or ""):
        return "ontology_constraint_failed"
    if not _evidence_spans_match(relation.get("evidence_spans"), source_text):
        return "relation_evidence_not_reconstructable"
    threshold = policy["relation_thresholds"].get(relation_type, policy["relation_default_threshold"])
    if _confidence(relation) < threshold:
        return "relation_confidence_below_threshold"
    return ""


def _span_matches_text(entity: dict[str, Any], source_text: str) -> bool:
    start = entity.get("start")
    end = entity.get("end")
    return (
        isinstance(start, int)
        and not isinstance(start, bool)
        and isinstance(end, int)
        and not isinstance(end, bool)
        and 0 <= start < end <= len(source_text)
        and source_text[start:end] == entity.get("text")
    )


def _evidence_spans_match(value: Any, source_text: str) -> bool:
    if not isinstance(value, list) or not value:
        return False
    for span in value:
        if not isinstance(span, dict):
            return False
        start = span.get("start")
        end = span.get("end")
        if (
            isinstance(start, bool)
            or isinstance(end, bool)
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
            or end > len(source_text)
        ):
            return False
    return True


def _entity_key(entity: dict[str, Any]) -> tuple[str, str]:
    return (str(entity.get("text") or ""), canonical_entity_type(entity.get("label") or ""))


def _confidence(item: dict[str, Any]) -> float:
    value = item.get("confidence")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return max(0.0, min(float(value), 1.0))


def _probability(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} 必须是 0 到 1 的数字")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} 必须是 0 到 1 的数字") from exc
    if not 0 <= parsed <= 1:
        raise ValueError(f"{field} 必须是 0 到 1 的数字")
    return parsed


def _threshold_map(value: Any, field: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} 必须是对象")
    return {str(key): _probability(item, f"{field}.{key}") for key, item in value.items()}


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} 不能为空")
    return text
