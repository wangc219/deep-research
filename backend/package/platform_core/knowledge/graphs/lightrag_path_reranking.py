"""用受约束 LLM 对已接受多跳路径做查询相关性重排。"""

from __future__ import annotations

import json
import math
from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import Any

from platform_core.knowledge.graphs.extractors.llm import LLMGraphExtractor

PATH_RERANKER_VERSION = "defense-lightrag-path-reranker-v3"
MAX_RERANK_CANDIDATES = 30
MAX_RERANK_CONTEXT_CHARS = 24000
DEFAULT_MIN_RELATION_COVERAGE = 2 / 3
_REQUIRED_KEYS = ("rankings",)

Completion = Callable[[str], Awaitable[dict[str, Any]]]


class LightRAGPathReranker:
    """只重排封闭路径候选，不生成或改写任何图谱知识。"""

    def __init__(self, options: dict[str, Any] | None = None, *, completion: Completion | None = None):
        self.options = dict(options or {})
        self._completion = completion
        self._extractor: LLMGraphExtractor | None = None

    async def rerank(self, *, query: str, mode: str, paths: list[dict[str, Any]]) -> dict[str, Any]:
        """返回稳定重排路径及可审计、非事实性的评分谱系。"""
        candidates = [deepcopy(path) for path in paths[:MAX_RERANK_CANDIDATES]]
        if not self.options.get("enabled") or len(candidates) < 2:
            return {
                "paths": candidates,
                "provenance": self._provenance(
                    status="disabled",
                    llm_used=False,
                    ranked_count=0,
                    candidate_count=len(candidates),
                ),
            }

        model_spec = str(self.options.get("model_spec") or "").strip()
        if not model_spec:
            raise ValueError("启用 LLM 多跳路径重排时必须配置 model_spec")
        strict = self.options.get("strict", False)
        if not isinstance(strict, bool):
            raise ValueError("LLM 多跳路径重排 strict 必须是布尔值")
        min_relation_coverage = _coverage_threshold(
            self.options.get("min_relation_coverage", DEFAULT_MIN_RELATION_COVERAGE)
        )

        try:
            compact, omitted_candidate_count = _compact_candidates(
                candidates,
                min_relation_coverage=min_relation_coverage,
            )
            payload = await self._complete(_reranking_prompt(query=query, mode=mode, candidates=compact))
            reranked, ranked_count = _apply_rankings(
                candidates,
                payload,
                mode=mode,
                min_relation_coverage=min_relation_coverage,
            )
            return {
                "paths": reranked,
                "provenance": self._provenance(
                    status="completed",
                    llm_used=True,
                    ranked_count=ranked_count,
                    min_relation_coverage=min_relation_coverage,
                    candidate_count=len(candidates),
                    prompt_candidate_count=len(compact),
                    omitted_candidate_count=omitted_candidate_count,
                ),
            }
        except Exception as exc:  # noqa: BLE001
            if strict:
                raise
            return {
                "paths": candidates,
                "provenance": self._provenance(
                    status="degraded",
                    llm_used=False,
                    ranked_count=0,
                    min_relation_coverage=min_relation_coverage,
                    failure_type=type(exc).__name__,
                    candidate_count=len(candidates),
                ),
            }

    async def aclose(self) -> None:
        """释放重排器独占的模型连接。"""
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
                    "timeout_seconds": self.options.get("timeout_seconds", 90),
                    "max_output_tokens": self.options.get("max_output_tokens", 4096),
                    "enable_thinking": self.options.get("enable_thinking", False),
                    "model_params": dict(self.options.get("model_params") or {}),
                    "enable_hypothesis_extraction": False,
                    "max_hypotheses_per_chunk": 0,
                }
            )
        return await self._extractor.complete_json(prompt, required_keys=_REQUIRED_KEYS)

    def _provenance(
        self,
        *,
        status: str,
        llm_used: bool,
        ranked_count: int,
        min_relation_coverage: float = DEFAULT_MIN_RELATION_COVERAGE,
        failure_type: str | None = None,
        candidate_count: int = 0,
        prompt_candidate_count: int = 0,
        omitted_candidate_count: int = 0,
    ) -> dict[str, Any]:
        result = {
            "reranker_version": PATH_RERANKER_VERSION,
            "status": status,
            "model_spec": str(self.options.get("model_spec") or "").strip() or None,
            "llm_used": llm_used,
            "ranked_count": ranked_count,
            "min_relation_coverage": round(min_relation_coverage, 4),
            "requires_boundary_relations": True,
            "candidate_count": candidate_count,
            "prompt_candidate_count": prompt_candidate_count,
            "omitted_candidate_count": omitted_candidate_count,
            "context_limited": omitted_candidate_count > 0,
        }
        if failure_type:
            result["failure_type"] = failure_type
        return result


def _compact_candidates(
    paths: list[dict[str, Any]],
    *,
    min_relation_coverage: float,
) -> tuple[list[dict[str, Any]], int]:
    prepared = []
    for path in paths:
        relations = path.get("relations") or []
        inspiration = path.get("research_inspiration") or {}
        relation_ids = _relation_sequence(path)
        boundary_relation_ids = _boundary_relation_ids(path, relation_ids)
        required_relation_count = max(1, math.ceil(len(relation_ids) * min_relation_coverage))
        required_relation_count = max(required_relation_count, min(2, len(relation_ids)))
        prepared.append(
            {
                "path_id": str(path.get("path_id") or ""),
                "deterministic_score": _nonnegative_float(path.get("score")),
                "route_kind": str(path.get("route_kind") or ""),
                "claim_level": str(path.get("claim_level") or ""),
                "semantic_coverage": _probability(path.get("semantic_coverage")),
                "semantic_closures": [str(item) for item in (path.get("semantic_closures") or [])][:4],
                "relation_signature": {
                    key: max(int((path.get("relation_signature") or {}).get(key) or 0), 0)
                    for key in ("valid_count", "invalid_count", "unknown_count")
                },
                "nodes": [
                    {
                        "name": str(node.get("name") or "")[:200],
                        "type": str(node.get("type") or "")[:80],
                        "semantic_role": str(node.get("semantic_role") or "")[:40],
                    }
                    for node in (path.get("nodes") or [])[:7]
                ],
                "relations": [
                    {
                        "relation_id": str(relation.get("id") or ""),
                        "type": str(relation.get("type") or "")[:100],
                        "evidence_count": max(int(relation.get("evidence_count") or 0), 0),
                    }
                    for relation in relations[:6]
                ],
                "boundary_relation_ids": boundary_relation_ids,
                "minimum_support_count": required_relation_count,
                "support_level": str((path.get("evidence") or {}).get("support_level") or ""),
                "evidence_gaps": [str(item)[:200] for item in (path.get("evidence_gaps") or [])[:8]],
                "military_value_dimensions": [
                    str(item)[:120] for item in inspiration.get("military_value_dimensions") or []
                ][:8],
                "expected_capability_gains": [
                    str(item)[:200] for item in inspiration.get("expected_capability_gains") or []
                ][:6],
                "research_threads": {
                    thread: [str(item)[:200] for item in (inspiration.get("research_threads") or {}).get(thread, [])][
                        :8
                    ]
                    for thread in ("main", "side", "parallel")
                },
                "value_signals": [
                    {
                        "entity": str(item.get("entity") or "")[:120],
                        "label": str(item.get("label") or "")[:80],
                        "text": str(item.get("text") or "")[:240],
                    }
                    for item in inspiration.get("value_signals") or []
                    if isinstance(item, dict)
                ][:8],
            }
        )
    encoded = json.dumps(prepared, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) <= MAX_RERANK_CONTEXT_CHARS:
        return prepared, 0

    compact = []
    for candidate in prepared:
        bounded = [*compact, candidate]
        encoded = json.dumps(bounded, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) > MAX_RERANK_CONTEXT_CHARS:
            break
        compact.append(candidate)
    if len(compact) < 2:
        raise ValueError("多跳路径重排单条候选过长，无法在上下文预算内保留两个候选")
    return compact, len(prepared) - len(compact)


def _apply_rankings(
    paths: list[dict[str, Any]],
    payload: dict[str, Any],
    *,
    mode: str,
    min_relation_coverage: float,
) -> tuple[list[dict[str, Any]], int]:
    raw_rankings = payload.get("rankings")
    if not isinstance(raw_rankings, list):
        raise ValueError("多跳路径重排模型必须返回 rankings 数组")
    paths_by_id = {str(path.get("path_id") or ""): path for path in paths}
    relation_ids_by_path = {path_id: _relation_sequence(path) for path_id, path in paths_by_id.items()}
    normalized: dict[str, dict[str, Any]] = {}
    for item in raw_rankings:
        if not isinstance(item, dict):
            continue
        path_id = str(item.get("path_id") or "").strip()
        if not path_id or path_id not in paths_by_id or path_id in normalized:
            continue
        requested_relation_ids = dict.fromkeys(
            str(value or "").strip() for value in item.get("supporting_relation_ids") or []
        )
        relation_ids = relation_ids_by_path[path_id]
        relation_id_set = set(relation_ids)
        supporting_relation_ids = [
            relation_id for relation_id in requested_relation_ids if relation_id in relation_id_set
        ]
        required_relation_count = max(1, math.ceil(len(relation_ids) * min_relation_coverage)) if relation_ids else 0
        required_relation_count = max(required_relation_count, min(2, len(relation_ids)))
        boundary_relation_ids = _boundary_relation_ids(paths_by_id[path_id], relation_ids)
        coverage = len(supporting_relation_ids) / len(relation_ids) if relation_ids else 0.0
        if (
            not relation_ids
            or len(supporting_relation_ids) < required_relation_count
            or coverage < min_relation_coverage
            or not set(boundary_relation_ids).issubset(supporting_relation_ids)
        ):
            continue
        dimensions = {
            "query_relevance": _probability(item.get("query_relevance")),
            "mechanism_coherence": _probability(item.get("mechanism_coherence")),
            "evidence_strength": _probability(item.get("evidence_strength")),
            "innovation_value": _probability(item.get("innovation_value")),
        }
        weights = (0.4, 0.25, 0.25, 0.1) if mode == "requirement_driven" else (0.25, 0.25, 0.2, 0.3)
        model_score = sum(score * weight for score, weight in zip(dimensions.values(), weights, strict=True))
        normalized[path_id] = {
            **dimensions,
            "model_score": round(model_score, 6),
            "supporting_relation_ids": supporting_relation_ids,
            "evidence_coverage": round(coverage, 4),
            "required_relation_count": required_relation_count,
            "boundary_relation_ids": boundary_relation_ids,
        }

    maximum_baseline = max((_nonnegative_float(path.get("score")) for path in paths), default=0.0)
    reranked = []
    for original_rank, path in enumerate(paths, start=1):
        path_id = str(path.get("path_id") or "")
        baseline = _nonnegative_float(path.get("score")) / maximum_baseline if maximum_baseline else 0.0
        model_result = normalized.get(path_id)
        model_score = model_result["model_score"] if model_result else baseline
        combined_score = round(baseline * 0.6 + model_score * 0.4, 6)
        item = {**path, "rerank_score": combined_score}
        if model_result:
            item["llm_rerank"] = {
                **model_result,
                "original_rank": original_rank,
                "advisory_only": True,
            }
        reranked.append(item)
    reranked.sort(
        key=lambda item: (
            -float(item["rerank_score"]),
            -_nonnegative_float(item.get("score")),
            str(item.get("path_id") or ""),
        )
    )
    return reranked, len(normalized)


def _probability(value: Any) -> float:
    number = _nonnegative_float(value)
    if number > 1:
        raise ValueError("多跳路径评分必须位于 0 到 1")
    return number


def _coverage_threshold(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("多跳路径关系覆盖率必须是 0.5 到 1 之间的数字")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("多跳路径关系覆盖率必须是 0.5 到 1 之间的数字") from exc
    if not math.isfinite(parsed) or not 0.5 <= parsed <= 1.0:
        raise ValueError("多跳路径关系覆盖率必须是 0.5 到 1 之间的数字")
    return parsed


def _relation_sequence(path: dict[str, Any]) -> list[str]:
    values = path.get("relation_ids") or [item.get("id") for item in path.get("relations") or []]
    return list(dict.fromkeys(str(value).strip() for value in values if str(value or "").strip()))


def _boundary_relation_ids(path: dict[str, Any], relation_ids: list[str]) -> list[str]:
    allowed_relation_ids = set(relation_ids)
    requested = [
        str(value).strip()
        for value in path.get("boundary_relation_ids") or []
        if str(value).strip() in allowed_relation_ids
    ]
    if requested:
        return list(dict.fromkeys(requested))
    if not relation_ids:
        return []
    return list(dict.fromkeys((relation_ids[0], relation_ids[-1])))


def _nonnegative_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("多跳路径评分必须是数字") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError("多跳路径评分不能为负数")
    return number


def _reranking_prompt(*, query: str, mode: str, candidates: list[dict[str, Any]]) -> str:
    mode_instruction = (
        "自上而下：优先满足需求、约束、原理到技术再到能力的闭合链。"
        if mode == "requirement_driven"
        else "自下而上：优先识别技术组合、机理迁移和新能力出口，但不得补造缺失关系。"
    )
    return f"""你是军事武器装备技术原理知识图谱的多跳路径重排器。
你只能为给定的封闭路径候选评分，不能新增路径、节点、关系、证据或事实。

目标：{mode_instruction}

规则：
- path_id 必须来自候选；每个 path_id 最多出现一次；
- supporting_relation_ids 必须来自该路径自身 relations，覆盖 minimum_support_count，且包含全部
  boundary_relation_ids；不能只引用中间一条关系为整条路径打分；
- 四项评分均为 0 到 1：query_relevance、mechanism_coherence、evidence_strength、innovation_value；
- innovation_value 要重点判断军事任务价值、新质技术特征、跨域迁移和能力跃迁潜力。低频弱信号只有在
  路径证据完整、来源可追溯时才可高分，不能把证据稀缺本身当作创新；
- research_threads 只用于排序和解释：自上而下优先 main 的闭合主线，side 用于约束、验证和风险，
  parallel 用于比较替代、互补或组合路线；研究线索不授权补造缺失节点、关系或事实；
- semantic_closures 中 mechanism_chain（原理—技术—能力）、application_chain（技术—能力—应用）和
  requirement_chain（需求—技术/能力—应用）是比机械五类齐全更实用的闭环信号；至少一个闭环的路径优先；
- relation_signature.invalid_count 大于 0 说明已知本体关系方向或端点类型不合法，mechanism_coherence 必须显著降分；
  unknown_count 仅表示扩展关系未知，不得自动判错；
- evidence_gaps 越严重，evidence_strength 越低；Hypothesis 不能伪装成 Fact；
- 不输出解释、自然语言事实、Markdown 或候选之外的内容。

查询：{query}
模式：{mode}
候选：{json.dumps(candidates, ensure_ascii=False, separators=(",", ":"))}

严格返回：
{{"rankings":[{{"path_id":"候选 ID","query_relevance":0.0,"mechanism_coherence":0.0,
"evidence_strength":0.0,"innovation_value":0.0,"supporting_relation_ids":["该路径关系 ID"]}}]}}
"""
