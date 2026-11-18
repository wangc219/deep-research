"""用项目 LLM 把封闭多跳证据路径撰述为可追溯结论。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from platform_core.knowledge.graphs.extractors.llm import LLMGraphExtractor

MULTIHOP_SYNTHESIS_VERSION = "defense-lightrag-multihop-synthesis-v1"
MAX_SYNTHESIS_PATHS = 10
MAX_SYNTHESIS_CONTEXT_CHARS = 30000
_REQUIRED_KEYS = (
    "executive_conclusion",
    "conclusion_path_ids",
    "reasoning_chain",
    "key_findings",
    "technology_routes",
    "capability_implications",
    "application_directions",
    "evidence_boundaries",
    "unresolved_questions",
)

Completion = Callable[[str], Awaitable[dict[str, Any]]]


class LightRAGMultiHopSynthesizer:
    """只解释已返回路径，不创建实体、关系或创新假设。"""

    def __init__(self, options: dict[str, Any] | None = None, *, completion: Completion | None = None):
        self.options = dict(options or {})
        self._completion = completion
        self._extractor: LLMGraphExtractor | None = None

    async def synthesize(
        self,
        *,
        query: str,
        discovery_mode: str,
        paths: list[dict[str, Any]],
        query_plan: dict[str, Any] | None = None,
        query_analysis: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """生成带路径、关系、Chunk 和文件引用的完整结论。"""
        candidates = paths[:MAX_SYNTHESIS_PATHS]
        if not self.options.get("enabled"):
            return {"narrative": None, "provenance": self._provenance(status="disabled", llm_used=False)}
        if not candidates:
            return {"narrative": None, "provenance": self._provenance(status="no_evidence", llm_used=False)}

        model_spec = str(self.options.get("model_spec") or "").strip()
        if not model_spec:
            raise ValueError("启用 LLM 多跳结论撰述时必须配置 model_spec")
        strict = self.options.get("strict", False)
        if not isinstance(strict, bool):
            raise ValueError("LLM 多跳结论撰述 strict 必须是布尔值")

        compact_paths, omitted_path_count = _compact_paths(candidates)
        try:
            payload = await self._complete(
                _synthesis_prompt(
                    query=query,
                    discovery_mode=discovery_mode,
                    paths=compact_paths,
                    query_plan=query_plan or {},
                    query_analysis=query_analysis or {},
                )
            )
            narrative = _ground_narrative(payload, candidates)
            return {
                "narrative": narrative,
                "provenance": self._provenance(
                    status="completed",
                    llm_used=True,
                    cited_path_count=len(narrative["cited_path_ids"]),
                    omitted_path_count=omitted_path_count,
                ),
            }
        except Exception as exc:  # noqa: BLE001
            if strict:
                raise
            return {
                "narrative": None,
                "provenance": self._provenance(
                    status="degraded",
                    llm_used=False,
                    failure_type=type(exc).__name__,
                    omitted_path_count=omitted_path_count,
                ),
            }

    async def aclose(self) -> None:
        """释放撰述器独占的模型连接。"""
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
                    "max_truncation_retries": self.options.get("max_truncation_retries", 0),
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
        cited_path_count: int = 0,
        omitted_path_count: int = 0,
        failure_type: str | None = None,
    ) -> dict[str, Any]:
        result = {
            "synthesizer_version": MULTIHOP_SYNTHESIS_VERSION,
            "status": status,
            "model_spec": str(self.options.get("model_spec") or "").strip() or None,
            "llm_used": llm_used,
            "cited_path_count": cited_path_count,
            "omitted_path_count": omitted_path_count,
            "context_limited": omitted_path_count > 0,
            "closed_evidence_only": True,
            "creates_graph_facts": False,
            "creates_innovation_hypotheses": False,
        }
        if failure_type:
            result["failure_type"] = failure_type
        return result


def _compact_paths(paths: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    compact: list[dict[str, Any]] = []
    for path in paths:
        evidence = path.get("evidence") or {}
        inspiration = path.get("research_inspiration") or {}
        item = {
            "path_id": str(path.get("path_id") or ""),
            "claim_level": str(path.get("claim_level") or ""),
            "score": path.get("score"),
            "semantic_coverage": path.get("semantic_coverage"),
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
                for relation in (path.get("relations") or [])[:6]
            ],
            "chunk_ids": [str(item) for item in (evidence.get("chunk_ids") or [])[:30]],
            "file_ids": [str(item) for item in (evidence.get("file_ids") or [])[:20]],
            "support_level": str(evidence.get("support_level") or ""),
            "evidence_gaps": [str(item)[:300] for item in (path.get("evidence_gaps") or [])[:10]],
            "expected_capability_gains": [
                str(item)[:300] for item in (inspiration.get("expected_capability_gains") or [])[:8]
            ],
            "application_directions": [
                str(item)[:300] for item in (inspiration.get("application_directions") or [])[:8]
            ],
            "applicable_conditions": [str(item)[:300] for item in (inspiration.get("applicable_conditions") or [])[:8]],
            "uncertainties": [str(item)[:300] for item in (inspiration.get("uncertainties") or [])[:8]],
        }
        bounded = [*compact, item]
        if len(json.dumps(bounded, ensure_ascii=False, separators=(",", ":"))) > MAX_SYNTHESIS_CONTEXT_CHARS:
            break
        compact.append(item)
    return compact, max(0, len(paths) - len(compact))


def _synthesis_prompt(
    *,
    query: str,
    discovery_mode: str,
    paths: list[dict[str, Any]],
    query_plan: dict[str, Any],
    query_analysis: dict[str, Any],
) -> str:
    direction = (
        "从需求、任务场景和目标能力出发，解释其如何沿证据路径映射到原理、技术、能力和应用。"
        if discovery_mode == "top_down"
        else "从给定技术或原理出发，解释其沿证据路径可支撑的能力边界和已有应用扩展。"
    )
    compact_plan = {
        key: query_plan.get(key) or []
        for key in (
            "low_level_keywords",
            "high_level_keywords",
            "concept_targets",
            "principle_terms",
            "technology_terms",
            "capability_targets",
            "application_targets",
            "constraints",
        )
    }
    compact_analysis = {
        key: query_analysis.get(key) or []
        for key in (
            "concept_targets",
            "principle_terms",
            "target_capabilities",
            "application_scenarios",
            "constraints",
            "key_technical_elements",
        )
    }
    context = {
        "query": query,
        "discovery_mode": discovery_mode,
        "query_plan": compact_plan,
        "query_analysis": compact_analysis,
        "paths": paths,
    }
    return f"""你是知识图谱多跳检索分析 Agent。请对封闭证据路径做详细撰述并输出完整结论。

方向要求：{direction}

硬约束：
1. 只能使用输入 paths 中已经存在的节点、关系和证据 ID；不得新增实体、关系、事实或外部知识。
2. 这是多跳检索结论，不是创新预测。不得提出候选边、技术组合假设或把潜在关系写成事实。
3. 每个实质性判断必须引用 path_ids；涉及机理链路时同时引用 relation_ids。
4. relation_ids、chunk_ids、file_ids 必须逐字来自对应 path。证据不足时写入 evidence_boundaries 或 unresolved_questions。
5. 区分 Fact、Inference 和待审证据；不要把 Inference 改写成确定事实。
6. 用简体中文，先给管理者可读的结论，再给逐步推理、技术路线、能力含义和应用方向。
7. executive_conclusion 不超过 600 个汉字；每个数组最多 3 项，每项 statement 不超过 220 个汉字。
8. 避免重复同一证据边界；优先给出与用户输入直接相关的结论，禁止扩写背景知识。

返回严格 JSON：
{{
  "executive_conclusion": "完整总体结论",
  "conclusion_path_ids": ["path-id"],
  "reasoning_chain": [{{"statement": "逐步推理", "path_ids": [], "relation_ids": [], "chunk_ids": [], "file_ids": []}}],
  "key_findings": [{{"statement": "关键发现", "path_ids": [], "relation_ids": [], "chunk_ids": [], "file_ids": []}}],
  "technology_routes": [{{
    "statement": "已有证据支持的技术路线", "path_ids": [], "relation_ids": [], "chunk_ids": [], "file_ids": []
  }}],
  "capability_implications": [{{
    "statement": "能力含义及边界", "path_ids": [], "relation_ids": [], "chunk_ids": [], "file_ids": []
  }}],
  "application_directions": [{{
    "statement": "已有证据支持的应用方向", "path_ids": [], "relation_ids": [], "chunk_ids": [], "file_ids": []
  }}],
  "evidence_boundaries": [{{
    "statement": "证据边界", "path_ids": [], "relation_ids": [], "chunk_ids": [], "file_ids": []
  }}],
  "unresolved_questions": [{{
    "statement": "待验证问题", "path_ids": [], "relation_ids": [], "chunk_ids": [], "file_ids": []
  }}]
}}

输入：
{json.dumps(context, ensure_ascii=False, separators=(",", ":"))}
"""


def _ground_narrative(payload: dict[str, Any], paths: list[dict[str, Any]]) -> dict[str, Any]:
    allowed: dict[str, dict[str, set[str]]] = {}
    for path in paths:
        path_id = str(path.get("path_id") or "").strip()
        if not path_id:
            continue
        evidence = path.get("evidence") or {}
        allowed[path_id] = {
            "relation_ids": {
                str(item)
                for item in [
                    *(path.get("relation_ids") or []),
                    *(relation.get("id") for relation in (path.get("relations") or [])),
                ]
                if item
            },
            "chunk_ids": {str(item) for item in (evidence.get("chunk_ids") or []) if item},
            "file_ids": {str(item) for item in (evidence.get("file_ids") or []) if item},
        }

    conclusion = str(payload.get("executive_conclusion") or "").strip()
    conclusion_path_ids = _closed_ids(payload.get("conclusion_path_ids"), set(allowed))
    if not conclusion or not conclusion_path_ids:
        raise ValueError("多跳结论缺少可核验的总体结论或路径引用")

    result: dict[str, Any] = {
        "executive_conclusion": conclusion[:6000],
        "conclusion_path_ids": conclusion_path_ids,
    }
    cited_paths = set(conclusion_path_ids)
    for field in _REQUIRED_KEYS[2:]:
        grounded_items = []
        raw_items = payload.get(field)
        if not isinstance(raw_items, list):
            raw_items = []
        for raw in raw_items[:20]:
            if not isinstance(raw, dict):
                continue
            statement = str(raw.get("statement") or "").strip()
            path_ids = _closed_ids(raw.get("path_ids"), set(allowed))
            if not statement or not path_ids:
                continue
            relation_ids = _ids_for_paths(raw.get("relation_ids"), path_ids, allowed, "relation_ids")
            chunk_ids = _ids_for_paths(raw.get("chunk_ids"), path_ids, allowed, "chunk_ids")
            file_ids = _ids_for_paths(raw.get("file_ids"), path_ids, allowed, "file_ids")
            grounded_items.append(
                {
                    "statement": statement[:3000],
                    "path_ids": path_ids,
                    "relation_ids": relation_ids,
                    "chunk_ids": chunk_ids,
                    "file_ids": file_ids,
                }
            )
            cited_paths.update(path_ids)
        result[field] = grounded_items
    result["cited_path_ids"] = sorted(cited_paths)
    result["citation_count"] = sum(len(result[field]) for field in _REQUIRED_KEYS[2:])
    return result


def _closed_ids(value: Any, allowed: set[str]) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item) for item in value if str(item) in allowed))


def _ids_for_paths(
    value: Any,
    path_ids: list[str],
    allowed: dict[str, dict[str, set[str]]],
    field: str,
) -> list[str]:
    available = set().union(*(allowed[path_id][field] for path_id in path_ids))
    return _closed_ids(value, available)
