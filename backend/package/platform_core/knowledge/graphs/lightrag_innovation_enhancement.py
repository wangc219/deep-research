"""用受约束 LLM 增强跨文档创新假设，不把预测写成事实。"""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import Any

from platform_core.knowledge.graphs.core_semantic_roles import CORE_ROLE_DEFINITIONS
from platform_core.knowledge.graphs.extractors.llm import ExtractionOutputTruncatedError, LLMGraphExtractor

INNOVATION_ENHANCEMENT_VERSION = "lightrag-innovation-enhancement-v5"
INNOVATION_DIMENSIONS = (
    "military_value",
    "novelty",
    "feasibility",
    "transferability",
    "evidence_strength",
    "weak_signal_potential",
)
DEFAULT_MIN_EVIDENCE_COVERAGE = 2 / 3
DEFAULT_MAX_HYPOTHESES_PER_CALL = 3
DEFAULT_INNOVATION_CONCURRENCY = 2
MAX_INNOVATION_CONCURRENCY = 8
OUTPUT_TOKEN_RESERVE = 384
OUTPUT_TOKENS_PER_HYPOTHESIS = 700
Completion = Callable[[str], Awaitable[dict[str, Any]]]


class LightRAGInnovationEnhancer:
    """只增强既有候选的解释与排序，不创建或接受图谱边。"""

    def __init__(self, options: dict[str, Any] | None = None, *, completion: Completion | None = None):
        self.options = dict(options or {})
        self._completion = completion
        self._extractor: LLMGraphExtractor | None = None

    async def enhance(
        self,
        *,
        query: str,
        discovery_mode: str,
        query_analysis: dict[str, Any],
        path_result: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """增强可引用已接受路径的候选；关闭或降级时保持原候选不变。"""
        if not self.options.get("enabled") or not candidates:
            return {
                "candidates": candidates,
                "report": _report("disabled" if not self.options.get("enabled") else "empty"),
            }
        model_spec = str(self.options.get("model_spec") or "").strip()
        if not model_spec:
            raise ValueError("启用 LLM 创新增强时必须配置 model_spec")
        strict = self.options.get("strict", False)
        if not isinstance(strict, bool):
            raise ValueError("LLM 创新增强 strict 必须是布尔值")
        min_evidence_coverage = _coverage_threshold(
            self.options.get("min_evidence_coverage", DEFAULT_MIN_EVIDENCE_COVERAGE)
        )
        max_structure_repairs = self.options.get("max_structure_repairs", 1)
        if (
            isinstance(max_structure_repairs, bool)
            or not isinstance(max_structure_repairs, int)
            or max_structure_repairs not in {0, 1}
        ):
            raise ValueError("创新增强 max_structure_repairs 只能是 0 或 1")
        max_output_tokens = _bounded_integer_option(
            self.options.get("max_output_tokens", 4096),
            field="创新增强 max_output_tokens",
            minimum=256,
            maximum=32768,
        )
        max_hypotheses_per_call = _hypotheses_per_call(
            self.options.get("max_hypotheses_per_call"),
            max_output_tokens=max_output_tokens,
        )

        batches = [
            candidates[offset : offset + max_hypotheses_per_call]
            for offset in range(0, len(candidates), max_hypotheses_per_call)
        ]
        concurrency_count = _bounded_integer_option(
            self.options.get("concurrency_count", DEFAULT_INNOVATION_CONCURRENCY),
            field="创新增强 concurrency_count",
            minimum=1,
            maximum=MAX_INNOVATION_CONCURRENCY,
        )
        semaphore = asyncio.Semaphore(concurrency_count)

        async def enhance_batch(batch_index: int, batch: list[dict[str, Any]]) -> dict[str, Any]:
            llm_calls = 0
            repair_count = 0
            try:
                prompt = _build_prompt(
                    query=query,
                    discovery_mode=discovery_mode,
                    query_analysis=query_analysis,
                    path_result=path_result,
                    candidates=batch,
                    min_evidence_coverage=min_evidence_coverage,
                )
                llm_calls += 1
                async with semaphore:
                    payload = await self._complete(prompt)
                batch_reasons: dict[str, int] = {}
                enhanced, applied, rejected = apply_innovation_enhancements(
                    batch,
                    payload,
                    model_spec=model_spec,
                    min_evidence_coverage=min_evidence_coverage,
                    rejection_reasons=batch_reasons,
                )
                if not applied and rejected and max_structure_repairs == 1:
                    repair_count += 1
                    llm_calls += 1
                    async with semaphore:
                        repaired_payload = await self._complete(
                            _build_structure_repair_prompt(
                                prompt=prompt,
                                previous_payload=payload,
                                rejection_reasons=batch_reasons,
                            )
                        )
                    repaired_reasons: dict[str, int] = {}
                    enhanced, applied, rejected = apply_innovation_enhancements(
                        batch,
                        repaired_payload,
                        model_spec=model_spec,
                        min_evidence_coverage=min_evidence_coverage,
                        rejection_reasons=repaired_reasons,
                    )
                    batch_reasons = repaired_reasons
                return {
                    "batch_index": batch_index,
                    "candidates": enhanced,
                    "applied": applied,
                    "rejected": rejected,
                    "rejection_reasons": batch_reasons,
                    "llm_calls": llm_calls,
                    "repair_count": repair_count,
                    "error": None,
                }
            except Exception as exc:  # noqa: BLE001
                return {
                    "batch_index": batch_index,
                    "candidates": batch,
                    "applied": 0,
                    "rejected": 0,
                    "rejection_reasons": {},
                    "llm_calls": llm_calls,
                    "repair_count": repair_count,
                    "error": exc,
                }

        outcomes = await asyncio.gather(
            *(enhance_batch(batch_index, batch) for batch_index, batch in enumerate(batches))
        )
        enhanced_candidates: list[dict[str, Any]] = []
        rejection_reasons: dict[str, int] = {}
        failure_types: dict[str, int] = {}
        degraded_batch_indices: list[int] = []
        truncated_batch_indices: list[int] = []
        applied_count = 0
        rejected_count = 0
        llm_calls = 0
        repair_count = 0

        for outcome in outcomes:
            error = outcome["error"]
            llm_calls += int(outcome["llm_calls"])
            repair_count += int(outcome["repair_count"])
            if error is not None:
                if strict:
                    raise error
                failure_type = type(error).__name__
                failure_types[failure_type] = failure_types.get(failure_type, 0) + 1
                degraded_batch_indices.append(int(outcome["batch_index"]))
                if isinstance(error, ExtractionOutputTruncatedError):
                    truncated_batch_indices.append(int(outcome["batch_index"]))
            enhanced_candidates.extend(outcome["candidates"])
            applied_count += int(outcome["applied"])
            rejected_count += int(outcome["rejected"])
            _merge_counts(rejection_reasons, outcome["rejection_reasons"])

        status = "completed"
        if degraded_batch_indices:
            status = "degraded" if len(degraded_batch_indices) == len(batches) else "partial"
        enhanced_candidates.sort(
            key=lambda item: (float(item.get("score") or 0.0), str(item.get("hypothesis_id") or "")),
            reverse=True,
        )
        return {
            "candidates": enhanced_candidates,
            "report": _report(
                status,
                model_spec=model_spec,
                applied_count=applied_count,
                rejected_count=rejected_count,
                min_evidence_coverage=min_evidence_coverage,
                rejection_reasons=rejection_reasons,
                repair_attempted=bool(repair_count),
                repair_count=repair_count,
                failure_types=failure_types,
                llm_calls=llm_calls,
                batch_count=len(batches),
                requested_candidates=len(candidates),
                max_hypotheses_per_call=max_hypotheses_per_call,
                output_budget=max_output_tokens,
                concurrency_count=concurrency_count,
                degraded_batch_indices=degraded_batch_indices,
                truncated_batch_indices=truncated_batch_indices,
            ),
        }

    async def aclose(self) -> None:
        """释放创新分析器独占的模型连接。"""
        if self._extractor is not None:
            await self._extractor.aclose()
            self._extractor = None

    async def _complete(self, prompt: str) -> dict[str, Any]:
        if self._completion is not None:
            return await self._completion(prompt)
        if self._extractor is None:
            self._extractor = LLMGraphExtractor(
                {
                    "model_spec": str(self.options["model_spec"]),
                    "timeout_seconds": self.options.get("timeout_seconds", 120),
                    "max_output_tokens": self.options.get("max_output_tokens", 4096),
                    "enable_thinking": self.options.get("enable_thinking", False),
                    "model_params": dict(self.options.get("model_params") or {}),
                    "enable_hypothesis_extraction": False,
                    "max_hypotheses_per_chunk": 0,
                }
            )
        return await self._extractor.complete_json(prompt, required_keys=("hypotheses",))


def apply_innovation_enhancements(
    candidates: list[dict[str, Any]],
    payload: dict[str, Any],
    *,
    model_spec: str,
    min_evidence_coverage: float = DEFAULT_MIN_EVIDENCE_COVERAGE,
    rejection_reasons: dict[str, int] | None = None,
) -> tuple[list[dict[str, Any]], int, int]:
    """只应用 ID、关键路径覆盖与验证契约均可核验的 LLM 补充。"""
    if not isinstance(payload, dict) or not isinstance(payload.get("hypotheses"), list):
        raise ValueError("创新分析模型必须返回 hypotheses 数组")
    min_evidence_coverage = _coverage_threshold(min_evidence_coverage)
    by_id = {str(item.get("hypothesis_id") or ""): deepcopy(item) for item in candidates}
    applied = 0
    rejected = 0
    seen: set[str] = set()
    for item in payload["hypotheses"]:
        if not isinstance(item, dict):
            rejected += 1
            _record_rejection(rejection_reasons, "invalid_item")
            continue
        hypothesis_id = str(item.get("hypothesis_id") or "").strip()
        candidate = by_id.get(hypothesis_id)
        if candidate is None:
            rejected += 1
            _record_rejection(rejection_reasons, "unknown_hypothesis_id")
            continue
        if hypothesis_id in seen:
            rejected += 1
            _record_rejection(rejection_reasons, "duplicate_hypothesis_id")
            continue
        seen.add(hypothesis_id)
        evidence_validation = _validate_evidence_coverage(
            candidate,
            item.get("supporting_relation_ids"),
            min_evidence_coverage=min_evidence_coverage,
        )
        validation_requirements, normalized_validation = _bounded_structured_list(item.get("validation_requirements"))
        falsification_criteria, normalized_falsification = _bounded_structured_list(item.get("falsification_criteria"))
        cross_domain_extrapolation = item.get("cross_domain_extrapolation")
        innovation_dimensions = _innovation_dimension_scores(item.get("innovation_dimensions"))
        innovation_rationale = _bounded_list(item.get("innovation_rationale"))
        if not evidence_validation["satisfied"]:
            rejected += 1
            _record_rejection(rejection_reasons, "insufficient_evidence_coverage")
            continue
        if not validation_requirements:
            rejected += 1
            _record_rejection(rejection_reasons, "missing_validation_requirements")
            continue
        if not falsification_criteria:
            rejected += 1
            _record_rejection(rejection_reasons, "missing_falsification_criteria")
            continue
        if not isinstance(cross_domain_extrapolation, bool):
            rejected += 1
            _record_rejection(rejection_reasons, "invalid_cross_domain_extrapolation")
            continue
        citations = evidence_validation["supporting_relation_ids"]

        mechanism = _bounded_text(item.get("mechanism_hypothesis"), 1200)
        if mechanism:
            candidate["mechanism_hypothesis"] = mechanism
        normalized_fields: list[str] = []
        for field in ("feasibility_basis", "expected_effects", "applicable_conditions", "uncertainties"):
            values, normalized = _bounded_structured_list(item.get(field))
            if values:
                candidate[field] = values
            if normalized:
                normalized_fields.append(field)
        constraint_conflicts, normalized_conflicts = _bounded_structured_list(item.get("constraint_conflicts"))
        normalized_fields.extend(
            field
            for field, normalized in (
                ("validation_requirements", normalized_validation),
                ("falsification_criteria", normalized_falsification),
                ("constraint_conflicts", normalized_conflicts),
            )
            if normalized
        )
        candidate["validation_requirements"] = validation_requirements
        candidate["falsification_criteria"] = falsification_criteria
        candidate["constraint_conflicts"] = constraint_conflicts
        if innovation_dimensions:
            innovation_profile = dict(candidate.get("innovation_profile") or {})
            innovation_profile["llm_assessment"] = {
                "dimensions": innovation_dimensions,
                "rationale": innovation_rationale,
                "advisory_only": True,
                "model_spec": model_spec,
            }
            candidate["innovation_profile"] = innovation_profile
        requested_adjustment = _score_adjustment(item.get("score_adjustment"))
        risk_penalties = _risk_penalties(
            candidate,
            constraint_conflicts=constraint_conflicts,
            cross_domain_extrapolation=cross_domain_extrapolation,
        )
        adjustment = round(max(-0.15, min(requested_adjustment - risk_penalties["total"], 0.15)), 4)
        candidate["score"] = round(max(0.0, min(float(candidate.get("score") or 0.0) + adjustment, 1.0)), 4)
        score_components = dict(candidate.get("score_components") or {})
        score_components["llm_adjustment"] = adjustment
        score_components["score"] = candidate["score"]
        candidate["score_components"] = score_components
        candidate["claim_level"] = "Hypothesis"
        candidate["review_status"] = "pending"
        candidate["expert_review_required"] = True
        llm_metadata = {
            "version": INNOVATION_ENHANCEMENT_VERSION,
            "model_spec": model_spec,
            "supporting_relation_ids": citations,
            "evidence_coverage": evidence_validation["coverage"],
            "required_relation_count": evidence_validation["required_relation_count"],
            "boundary_relation_ids": evidence_validation["boundary_relation_ids"],
            "boundary_coverage_satisfied": evidence_validation["boundary_coverage_satisfied"],
            "validation_requirements": validation_requirements,
            "falsification_criteria": falsification_criteria,
            "constraint_conflicts": constraint_conflicts,
            "cross_domain_extrapolation": cross_domain_extrapolation,
            "innovation_dimensions": innovation_dimensions,
            "innovation_rationale": innovation_rationale,
            "structure_normalized_by_platform": bool(normalized_fields),
            "normalized_fields": normalized_fields,
            "risk_penalties": risk_penalties,
            "requested_score_adjustment": requested_adjustment,
            "score_adjustment": adjustment,
            "status": "applied",
        }
        candidate["llm_enhancement"] = llm_metadata
        candidate["evidence_path"] = {
            **dict(candidate.get("evidence_path") or {}),
            "llm_enhancement": llm_metadata,
        }
        applied += 1

    ranked = sorted(
        by_id.values(),
        key=lambda item: (float(item.get("score") or 0.0), item["hypothesis_id"]),
        reverse=True,
    )
    return ranked, applied, rejected


def _validate_evidence_coverage(
    candidate: dict[str, Any],
    requested_citations: Any,
    *,
    min_evidence_coverage: float,
) -> dict[str, Any]:
    evidence_path = candidate.get("evidence_path") or {}
    allowed_relations = list(
        dict.fromkeys(str(value).strip() for value in evidence_path.get("relation_ids") or [] if str(value).strip())
    )
    allowed_set = set(allowed_relations)
    requested_values = requested_citations if isinstance(requested_citations, list) else []
    citations = list(
        dict.fromkeys(str(value).strip() for value in requested_values if str(value).strip() in allowed_set)
    )
    boundaries = list(
        dict.fromkeys(
            str(value).strip()
            for value in evidence_path.get("boundary_relation_ids") or []
            if str(value).strip() in allowed_set
        )
    )
    if not boundaries and allowed_relations:
        boundaries = list(dict.fromkeys((allowed_relations[0], allowed_relations[-1])))
    required_count = max(1, math.ceil(len(allowed_relations) * min_evidence_coverage)) if allowed_relations else 0
    required_count = max(required_count, min(2, len(allowed_relations)))
    coverage = len(citations) / len(allowed_relations) if allowed_relations else 0.0
    boundary_coverage_satisfied = bool(boundaries) and set(boundaries).issubset(citations)
    return {
        "supporting_relation_ids": citations,
        "coverage": round(coverage, 4),
        "required_relation_count": required_count,
        "boundary_relation_ids": boundaries,
        "boundary_coverage_satisfied": boundary_coverage_satisfied,
        "satisfied": bool(
            allowed_relations
            and len(citations) >= required_count
            and coverage >= min_evidence_coverage
            and boundary_coverage_satisfied
        ),
    }


def _risk_penalties(
    candidate: dict[str, Any],
    *,
    constraint_conflicts: list[str],
    cross_domain_extrapolation: bool,
) -> dict[str, float]:
    evidence_path = candidate.get("evidence_path") or {}
    gap_penalty = min(len(evidence_path.get("evidence_gaps") or []) * 0.03, 0.09)
    conflict_penalty = min(len(constraint_conflicts) * 0.03, 0.09)
    cross_document_penalty = 0.02 if evidence_path.get("cross_document") else 0.0
    extrapolation_penalty = 0.04 if cross_domain_extrapolation else 0.0
    total = min(gap_penalty + conflict_penalty + cross_document_penalty + extrapolation_penalty, 0.15)
    return {
        "evidence_gap": round(gap_penalty, 4),
        "constraint_conflict": round(conflict_penalty, 4),
        "cross_document_inference": round(cross_document_penalty, 4),
        "cross_domain_extrapolation": round(extrapolation_penalty, 4),
        "total": round(total, 4),
    }


def _coverage_threshold(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("创新证据覆盖率必须是 0.5 到 1 之间的数字")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("创新证据覆盖率必须是 0.5 到 1 之间的数字") from exc
    if not math.isfinite(parsed) or not 0.5 <= parsed <= 1.0:
        raise ValueError("创新证据覆盖率必须是 0.5 到 1 之间的数字")
    return parsed


def _hypotheses_per_call(value: Any, *, max_output_tokens: int) -> int:
    """按结构化输出预算限制单次假设数，避免隐藏推理或长字段截断 JSON。"""
    budget_limit = max(1, (max_output_tokens - OUTPUT_TOKEN_RESERVE) // OUTPUT_TOKENS_PER_HYPOTHESIS)
    budget_limit = min(budget_limit, DEFAULT_MAX_HYPOTHESES_PER_CALL)
    if value is None:
        return budget_limit
    configured = _bounded_integer_option(
        value,
        field="创新增强 max_hypotheses_per_call",
        minimum=1,
        maximum=8,
    )
    return min(configured, budget_limit)


def _bounded_integer_option(value: Any, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{field} 必须是 {minimum} 到 {maximum} 之间的整数")
    return value


def _merge_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for key, count in source.items():
        target[key] = target.get(key, 0) + count


def _record_rejection(reasons: dict[str, int] | None, reason: str) -> None:
    if reasons is not None:
        reasons[reason] = reasons.get(reason, 0) + 1


def _score_adjustment(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not math.isfinite(parsed):
        return 0.0
    return round(max(-0.15, min(parsed, 0.15)), 4)


def _innovation_dimension_scores(value: Any) -> dict[str, float]:
    """只接受完整、有限且位于 0~1 的创新维度，避免局部模型输出误导排序。"""
    if not isinstance(value, dict) or any(name not in value for name in INNOVATION_DIMENSIONS):
        return {}
    result: dict[str, float] = {}
    for name in INNOVATION_DIMENSIONS:
        raw = value.get(name)
        if isinstance(raw, bool):
            return {}
        try:
            score = float(raw)
        except (TypeError, ValueError, OverflowError):
            return {}
        if not math.isfinite(score) or not 0 <= score <= 1:
            return {}
        result[name] = round(score, 4)
    return result


def _bounded_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(text for item in value if (text := _bounded_text(item, 500))))[:12]


def _bounded_structured_list(value: Any) -> tuple[list[str], bool]:
    if isinstance(value, str):
        text = _bounded_text(value, 500)
        return ([text] if text else []), bool(text)
    return _bounded_list(value), False


def _bounded_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _report(
    status: str,
    *,
    model_spec: str = "",
    applied_count: int = 0,
    rejected_count: int = 0,
    min_evidence_coverage: float = DEFAULT_MIN_EVIDENCE_COVERAGE,
    rejection_reasons: dict[str, int] | None = None,
    repair_attempted: bool = False,
    repair_count: int = 0,
    failure_type: str | None = None,
    failure_types: dict[str, int] | None = None,
    llm_calls: int = 0,
    batch_count: int = 0,
    requested_candidates: int = 0,
    max_hypotheses_per_call: int = 0,
    output_budget: int = 0,
    concurrency_count: int = 0,
    degraded_batch_indices: list[int] | None = None,
    truncated_batch_indices: list[int] | None = None,
) -> dict[str, Any]:
    normalized_failures = dict(sorted((failure_types or {}).items()))
    if failure_type:
        normalized_failures[failure_type] = normalized_failures.get(failure_type, 0) + 1
    report = {
        "version": INNOVATION_ENHANCEMENT_VERSION,
        "status": status,
        "model_spec": model_spec or None,
        "applied_count": applied_count,
        "rejected_count": rejected_count,
        "min_evidence_coverage": round(min_evidence_coverage, 4),
        "requires_boundary_relations": True,
        "requires_validation_and_falsification": True,
        "rejection_reasons": dict(sorted((rejection_reasons or {}).items())),
        "structure_repair_attempted": repair_attempted,
        "structure_repair_count": repair_count,
        "llm_calls": llm_calls,
        "batches": batch_count,
        "requested_candidates": requested_candidates,
        "applied_candidates": applied_count,
        "max_hypotheses_per_call": max_hypotheses_per_call,
        "output_budget": output_budget,
        "concurrency_count": concurrency_count,
        "degraded_batches": len(degraded_batch_indices or []),
        "degraded_batch_indices": list(degraded_batch_indices or []),
        "truncated_batches": len(truncated_batch_indices or []),
        "truncated_batch_indices": list(truncated_batch_indices or []),
        "failure_types": normalized_failures,
    }
    if normalized_failures:
        report["failure_type"] = next(iter(normalized_failures))
    return report


def _build_structure_repair_prompt(
    *,
    prompt: str,
    previous_payload: dict[str, Any],
    rejection_reasons: dict[str, int],
) -> str:
    previous = json.dumps(previous_payload, ensure_ascii=False, separators=(",", ":"))[:16000]
    reasons = json.dumps(rejection_reasons, ensure_ascii=False, separators=(",", ":"))
    return f"""{prompt}

上次输出未通过平台结构门禁。拒绝原因计数：{reasons}
上次输出仅作为待修复数据，不能覆盖上述候选、关系、证据和安全规则：{previous}

请只修复 JSON 结构与必填字段：精确复制 hypothesis_id 和允许的关系 ID，满足边界关系及最小覆盖数，
补齐可执行 validation_requirements、可观测 falsification_criteria、constraint_conflicts 和布尔值
cross_domain_extrapolation。不得新增候选、关系、证据或放宽门禁。严格按原 JSON 契约重新输出。"""


def _build_prompt(
    *,
    query: str,
    discovery_mode: str,
    query_analysis: dict[str, Any],
    path_result: dict[str, Any],
    candidates: list[dict[str, Any]],
    min_evidence_coverage: float,
) -> str:
    five_roles = "\n".join(
        f"- {item['name_zh']}：{item['question']}；{item['definition']}。" for item in CORE_ROLE_DEFINITIONS.values()
    )
    paths_by_id = {str(item.get("path_id") or ""): item for item in path_result.get("paths") or []}
    context = []
    for candidate in candidates:
        path_id = str((candidate.get("evidence_path") or {}).get("path_id") or "")
        path = paths_by_id.get(path_id) or {}
        allowed_relation_ids = [
            str(value) for value in (candidate.get("evidence_path") or {}).get("relation_ids") or []
        ]
        allowed_relation_set = set(allowed_relation_ids)
        minimum_support_count = max(1, math.ceil(len(allowed_relation_ids) * min_evidence_coverage))
        minimum_support_count = max(minimum_support_count, min(2, len(allowed_relation_ids)))
        context.append(
            {
                "hypothesis_id": candidate.get("hypothesis_id"),
                "source": candidate.get("source"),
                "target": candidate.get("target"),
                "relation_type": candidate.get("relation_type"),
                "current_score": candidate.get("score"),
                "deterministic_innovation_profile": candidate.get("innovation_profile") or {},
                "allowed_relation_ids": allowed_relation_ids,
                "boundary_relation_ids": (candidate.get("evidence_path") or {}).get("boundary_relation_ids") or [],
                "minimum_support_count": minimum_support_count,
                "query_anchor_match": bool(candidate.get("query_anchor_match")),
                "anchor_context_only": bool((candidate.get("evidence_path") or {}).get("anchor_context_only")),
                "anchor_entity_id": (candidate.get("evidence_path") or {}).get("anchor_entity_id"),
                "path_nodes": [
                    {
                        "entity_id": (node.get("properties") or {}).get("entity_id"),
                        "name": node.get("name"),
                        "type": node.get("type"),
                        "semantic_role": node.get("semantic_role"),
                    }
                    for node in path.get("nodes") or []
                ],
                "path_relations": [
                    {
                        "id": relation.get("id"),
                        "type": relation.get("type"),
                        "claim_level": (relation.get("properties") or {}).get("claim_level"),
                        "evidence_quote": _bounded_text(
                            (relation.get("properties") or {}).get("evidence_quote"),
                            500,
                        ),
                        "evidence_file_id": (relation.get("properties") or {}).get("file_id"),
                        "evidence_chunk_id": (relation.get("properties") or {}).get("chunk_id"),
                        "applicable_conditions": (relation.get("properties") or {}).get("applicable_conditions") or [],
                    }
                    for relation in path.get("relations") or []
                    if str(relation.get("id") or "") in allowed_relation_set
                ],
                "research_threads": (path.get("research_inspiration") or {}).get("research_threads") or {},
                "evidence_gaps": (candidate.get("evidence_path") or {}).get("evidence_gaps") or [],
            }
        )
    payload = json.dumps(
        {
            "query": query,
            "discovery_mode": discovery_mode,
            "query_analysis": query_analysis,
            "candidates": context,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"""你是军事武器装备技术原理的创新假设分析器。
输入候选来自已接受事实图的多跳路径，候选关联本身没有直接原文证据。
anchor_context_only=true 表示其中一个端点是用户查询在图中精确命中的孤立或弱连接实体，给定多跳关系
只提供相关技术上下文，不构成该锚点到目标的直接证据；必须把这一缺口写入不确定性和验证要求，禁止把
上下文路径表述为已连通语义链。

五类主干语义：
{five_roles}

discovery_mode=top_down 时，从用户能力/应用需求反向检查“能力 → 技术 → 原理/概念 → 证据”路径是否完整，
只评估哪些既有技术链可能满足需求以及缺少哪些验证；不得为补齐链路创造实体或事实。
discovery_mode=bottom_up 执行面向新质技术的自下而上发现：从已存在的新原理、新材料、新器件、算法或
技术弱信号向上检查可形成的能力、
可迁移的应用和可互补的技术组合；弱信号不等于弱证据，任何候选仍须覆盖给定多跳关系和边界关系。
research_threads 只作为排序与解释信号：main 支撑基准贡献链，side 提供约束、验证和风险，parallel 用于
比较并行、替代、互补或组合候选；它不授权生成新节点、新关系、新证据，也不得用来补齐缺失的五类角色。
实体的细粒度 type 保持不变，semantic_role 只用于组织 Concept → Principle → Technology → Capability →
Application 链路；预测结果永远保持 Hypothesis/pending。

只能增强给定 hypothesis_id，不得新增、删除或替换 source、target、relation_type、实体、关系或证据 ID。
当前批次恰有 {len(candidates)} 条候选；hypotheses 最多返回 {len(candidates)} 条，且每个 hypothesis_id 最多出现一次。
每项 supporting_relation_ids 必须覆盖 boundary_relation_ids，并至少达到 minimum_support_count；
只引用单条边的多跳结论不会被采用。
所有结论必须保持 Hypothesis，明确适用条件、工程约束、不确定性和需验证内容，不得写成已实现事实。
score_adjustment 只能在 -0.15 到 0.15 之间，证据链间接、存在缺口或跨域外推时应下调。
validation_requirements 必须给出可执行验证，falsification_criteria 必须给出可推翻假设的观测条件。
constraint_conflicts 记录路径证据之间或与适用条件的冲突；cross_domain_extrapolation 必须是布尔值。
innovation_dimensions 必须完整给出 0~1 的六维评估：military_value、novelty、feasibility、
transferability、evidence_strength、weak_signal_potential；其中弱信号潜力不等于证据不足，必须仍有可引用路径。
innovation_rationale 最多给出 6 条短理由，分别说明军事价值、新质性与工程可验证性。六维评分只作为咨询信息，
不能改变候选端点、关系类型、证据或事实状态。

输入：{payload}

严格返回 JSON：
{{"hypotheses":[{{
  "hypothesis_id":"",
  "supporting_relation_ids":[],
  "mechanism_hypothesis":"",
  "feasibility_basis":[],
  "expected_effects":[],
  "applicable_conditions":[],
  "uncertainties":[],
  "validation_requirements":[],
  "falsification_criteria":[],
  "constraint_conflicts":[],
  "cross_domain_extrapolation":false,
  "innovation_dimensions":{{
    "military_value":0.0,
    "novelty":0.0,
    "feasibility":0.0,
    "transferability":0.0,
    "evidence_strength":0.0,
    "weak_signal_potential":0.0
  }},
  "innovation_rationale":[],
  "score_adjustment":0.0
}}]}}"""
