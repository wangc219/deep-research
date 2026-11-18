"""LightRAG 风格的图查询规划与多路召回融合。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from platform_core.knowledge.graphs.core_semantic_roles import CORE_ROLE_DEFINITIONS
from platform_core.knowledge.graphs.extractors.llm import LLMGraphExtractor

QUERY_PLANNER_VERSION = "lightrag-query-planner-v4"
RRF_FUSION_VERSION = "reciprocal-rank-fusion-v1"
RETRIEVAL_MODES = frozenset({"naive", "local", "global", "hybrid", "mix"})
_PLAN_KEYS = (
    "low_level_keywords",
    "high_level_keywords",
    "concept_targets",
    "principle_terms",
    "technology_terms",
    "capability_targets",
    "application_targets",
    "constraints",
    "military_value_dimensions",
    "innovation_objectives",
    "weak_signal_terms",
)

Completion = Callable[[str], Awaitable[dict[str, Any]]]


class LightRAGQueryPlanner:
    """把自然语言需求拆成实体级与关系级检索词，不直接生成图谱事实。"""

    def __init__(self, options: dict[str, Any] | None = None, *, completion: Completion | None = None):
        self.options = dict(options or {})
        self._completion = completion
        self._extractor: LLMGraphExtractor | None = None

    async def plan(self, query: str) -> dict[str, Any]:
        """生成可追溯查询计划；关闭或非严格失败时确定性退回原始查询。"""
        normalized_query = str(query or "").strip()
        if not normalized_query:
            raise ValueError("查询不能为空")
        if not self.options.get("enabled"):
            return deterministic_query_plan(normalized_query, status="disabled")

        model_spec = str(self.options.get("model_spec") or "").strip()
        if not model_spec:
            raise ValueError("启用 LLM 检索规划时必须配置 model_spec")
        strict = self.options.get("strict", False)
        if not isinstance(strict, bool):
            raise ValueError("LLM 检索规划 strict 必须是布尔值")

        try:
            payload = await self._complete(_build_query_planning_prompt(normalized_query))
            return normalize_query_plan(
                normalized_query,
                payload,
                status="completed",
                model_spec=model_spec,
            )
        except Exception as exc:  # noqa: BLE001
            if strict:
                raise
            return deterministic_query_plan(
                normalized_query,
                status="degraded",
                model_spec=model_spec,
                failure_type=type(exc).__name__,
            )

    async def aclose(self) -> None:
        """释放查询规划器独占的模型连接。"""
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
                    "timeout_seconds": self.options.get("timeout_seconds", 60),
                    "max_output_tokens": self.options.get("max_output_tokens", 2048),
                    "enable_thinking": self.options.get("enable_thinking", False),
                    "model_params": dict(self.options.get("model_params") or {}),
                    "enable_hypothesis_extraction": False,
                    "max_hypotheses_per_chunk": 0,
                }
            )
        return await self._extractor.complete_json(prompt, required_keys=_PLAN_KEYS)


def normalize_retrieval_mode(value: str | None) -> str:
    """校验 LightRAG naive/local/global/hybrid/mix 检索模式。"""
    normalized = str(value or "mix").strip().lower()
    if normalized not in RETRIEVAL_MODES:
        raise ValueError("retrieval_mode 必须是 naive、local、global、hybrid 或 mix")
    return normalized


def deterministic_query_plan(
    query: str,
    *,
    status: str,
    model_spec: str = "",
    failure_type: str | None = None,
) -> dict[str, Any]:
    """构造不依赖模型、不会丢失原始查询的退化计划。"""
    provenance = {
        "planner_version": QUERY_PLANNER_VERSION,
        "status": status,
        "model_spec": model_spec or None,
        "llm_used": False,
    }
    if failure_type:
        provenance["failure_type"] = failure_type
    return {
        "query": query,
        "low_level_keywords": [query],
        "high_level_keywords": [query],
        "concept_targets": [],
        "principle_terms": [],
        "technology_terms": [],
        "capability_targets": [],
        "application_targets": [],
        "constraints": [],
        "military_value_dimensions": [],
        "innovation_objectives": [],
        "weak_signal_terms": [],
        "provenance": provenance,
    }


def normalize_query_plan(
    query: str,
    payload: dict[str, Any],
    *,
    status: str,
    model_spec: str,
) -> dict[str, Any]:
    """把模型输出收敛为有界关键词列表并保留规划谱系。"""
    if not isinstance(payload, dict):
        raise ValueError("查询规划模型必须返回 JSON 对象")
    low_level = _normalize_keywords(payload.get("low_level_keywords"))
    high_level = _normalize_keywords(payload.get("high_level_keywords"))
    return {
        "query": query,
        "low_level_keywords": low_level or [query],
        "high_level_keywords": high_level or [query],
        "concept_targets": _normalize_keywords(payload.get("concept_targets")),
        "principle_terms": _normalize_keywords(payload.get("principle_terms")),
        "technology_terms": _normalize_keywords(payload.get("technology_terms")),
        "capability_targets": _normalize_keywords(payload.get("capability_targets")),
        "application_targets": _normalize_keywords(payload.get("application_targets")),
        "constraints": _normalize_keywords(payload.get("constraints")),
        "military_value_dimensions": _normalize_keywords(payload.get("military_value_dimensions")),
        "innovation_objectives": _normalize_keywords(payload.get("innovation_objectives")),
        "weak_signal_terms": _normalize_keywords(payload.get("weak_signal_terms")),
        "provenance": {
            "planner_version": QUERY_PLANNER_VERSION,
            "status": status,
            "model_spec": model_spec,
            "llm_used": True,
        },
    }


def retrieval_queries(plan: dict[str, Any]) -> tuple[str, str]:
    """保留原始意图锚点，再生成实体级 local 与关系级 global 查询。"""
    original = str(plan.get("query") or "").strip()
    local = _join_keywords([original, *(plan.get("low_level_keywords") or [])]) or original
    global_query = _join_keywords(
        [
            original,
            *(plan.get("high_level_keywords") or []),
            *(plan.get("concept_targets") or []),
            *(plan.get("principle_terms") or []),
            *(plan.get("technology_terms") or []),
            *(plan.get("capability_targets") or []),
            *(plan.get("application_targets") or []),
            *(plan.get("constraints") or []),
            *(plan.get("military_value_dimensions") or []),
            *(plan.get("innovation_objectives") or []),
            *(plan.get("weak_signal_terms") or []),
        ]
    )
    return local, global_query or original


def graph_keyword_queries(plan: dict[str, Any], *, max_terms: int = 8) -> list[str]:
    """将查询计划拆成可被 Neo4j CONTAINS 精确命中的短实体词。"""
    fields = (
        "low_level_keywords",
        "concept_targets",
        "principle_terms",
        "technology_terms",
        "capability_targets",
        "application_targets",
    )
    terms: list[str] = []
    seen: set[str] = set()
    for field in fields:
        for item in plan.get(field) or []:
            term = " ".join(str(item or "").split()).strip(" ,，;；")
            marker = term.casefold()
            if len(term) < 2 or not marker or marker in seen:
                continue
            seen.add(marker)
            terms.append(term[:120])
            if len(terms) >= max(1, min(int(max_terms), 12)):
                return terms
    original = str(plan.get("query") or "").strip()
    return terms or ([original] if original else [])


def graph_keyword_entity_hits(
    graph: dict[str, Any],
    keywords: list[str],
) -> list[dict[str, Any]]:
    """从关键词子图提取与短词直接匹配的稳定实体锚点。"""
    keyword_pairs = [(str(item or "").strip(), "".join(str(item or "").casefold().split())) for item in keywords]
    keyword_pairs = [(keyword, normalized) for keyword, normalized in keyword_pairs if normalized]
    hits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for node in graph.get("nodes") or []:
        properties = node.get("properties") or {}
        entity_id = str(properties.get("entity_id") or node.get("entity_id") or "").strip()
        name = str(node.get("name") or properties.get("name") or "").strip()
        normalized_name = "".join(name.casefold().split())
        if not entity_id or not normalized_name or entity_id in seen:
            continue
        match = next(
            (
                (keyword, 1.0 if normalized_keyword == normalized_name else 0.9)
                for keyword, normalized_keyword in keyword_pairs
                if normalized_keyword == normalized_name
                or normalized_keyword in normalized_name
                or normalized_name in normalized_keyword
            ),
            None,
        )
        if match is None:
            continue
        matched_keyword, match_score = match
        seen.add(entity_id)
        hits.append(
            {
                "id": entity_id,
                "name": name,
                "keyword": matched_keyword,
                "match_score": match_score,
                "node": node,
            }
        )
    hits.sort(key=lambda item: (-float(item["match_score"]), str(item["name"]), str(item["id"])))
    return hits[:12]


def reciprocal_rank_fuse_graph_hits(
    entity_hits: list[dict[str, Any]],
    triple_hits: list[dict[str, Any]],
    chunk_entity_hits: list[dict[str, Any]] | None = None,
    keyword_entity_hits: list[dict[str, Any]] | None = None,
    *,
    max_entities: int = 12,
    rank_constant: int = 60,
) -> dict[str, Any]:
    """将实体、三元组端点、Chunk 与关键词实体按 RRF 融合为图种子。"""
    scores: dict[str, float] = {}
    sources: dict[str, set[str]] = {}
    for rank, hit in enumerate(entity_hits, start=1):
        entity_id = str(hit.get("id") or "").strip()
        if entity_id:
            scores[entity_id] = scores.get(entity_id, 0.0) + 1.0 / (rank_constant + rank)
            sources.setdefault(entity_id, set()).add("entity")
    for rank, hit in enumerate(triple_hits, start=1):
        contribution = 1.0 / (rank_constant + rank)
        for field in ("source_id", "target_id"):
            entity_id = str(hit.get(field) or "").strip()
            if entity_id:
                scores[entity_id] = scores.get(entity_id, 0.0) + contribution
                sources.setdefault(entity_id, set()).add("triple")
    for rank, hit in enumerate(chunk_entity_hits or [], start=1):
        entity_id = str(hit.get("id") or "").strip()
        if entity_id:
            scores[entity_id] = scores.get(entity_id, 0.0) + 1.0 / (rank_constant + rank)
            sources.setdefault(entity_id, set()).add("chunk")
    for rank, hit in enumerate(keyword_entity_hits or [], start=1):
        entity_id = str(hit.get("id") or "").strip()
        if entity_id:
            scores[entity_id] = scores.get(entity_id, 0.0) + 2.0 / (rank_constant + rank)
            sources.setdefault(entity_id, set()).add("keyword")

    ranked = sorted(scores, key=lambda entity_id: (-scores[entity_id], entity_id))[:max_entities]
    maximum = max((scores[entity_id] for entity_id in ranked), default=0.0)
    relevance = {entity_id: round(scores[entity_id] / maximum, 6) if maximum else 0.0 for entity_id in ranked}
    return {
        "entity_ids": ranked,
        "relevance_by_entity_id": relevance,
        "sources_by_entity_id": {entity_id: sorted(sources[entity_id]) for entity_id in ranked},
        "fusion_method": RRF_FUSION_VERSION,
    }


def merge_graph_subgraphs(*graphs: dict[str, Any]) -> dict[str, Any]:
    """按稳定节点和边 ID 合并多路 Neo4j 子图。"""
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, dict[str, Any]] = {}
    for graph in graphs:
        for node in graph.get("nodes") or []:
            node_id = str(node.get("id") or "").strip()
            if node_id:
                nodes.setdefault(node_id, node)
        for edge in graph.get("edges") or []:
            edge_id = str(edge.get("id") or "").strip()
            if edge_id:
                edges.setdefault(edge_id, edge)
    return {"nodes": list(nodes.values()), "edges": list(edges.values())}


def _normalize_keywords(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    keywords: list[str] = []
    seen: set[str] = set()
    for item in value:
        keyword = " ".join(str(item or "").split()).strip(" ,，;；")
        marker = keyword.casefold()
        if not keyword or marker in seen:
            continue
        seen.add(marker)
        keywords.append(keyword[:120])
        if len(keywords) >= 12:
            break
    return keywords


def _join_keywords(value: Any) -> str:
    return "；".join(_normalize_keywords(value))


def _build_query_planning_prompt(query: str) -> str:
    five_roles = "\n".join(
        f"- {item['name_zh']}：{item['question']}；{item['definition']}。" for item in CORE_ROLE_DEFINITIONS.values()
    )
    return f"""你是军事武器装备技术原理知识图谱的检索规划器。只拆分检索意图，不回答问题、不生成事实或关系。

五类主干角色：
{five_roles}

面向能力需求的自上而下检索应先锁定 capability_targets 与 application_targets，再向前追溯 Concept/约束、
Principle 和 Technology，形成“需求/问题 → 原理 → 技术 → 能力 → 应用 → 证据”的多跳检索锚点。
面向新质技术的自下而上发现应先锁定 principle_terms、technology_terms 和 weak_signal_terms，再探索其可能
支撑的能力、应用、互补技术与跨域迁移；这里只生成召回词，不得把潜在链路写成事实。

请把查询拆成十一类关键词：
1. low_level_keywords：具体科学原理、技术、算法、材料、组件、系统、型号或实体别名；
2. high_level_keywords：机理关系、能力效果、应用场景、成熟度或跨域主题；
3. concept_targets：需求、问题、对象、环境、威胁或体系概念；
4. principle_terms：解释为何有效的理论、原理、机制或机理；
5. technology_terms：可实现、验证、复用、集成或迁移的技术、算法、模型、材料、器件或组件；
6. capability_targets：期望获得或提升的能力、功能或效能；
7. application_targets：装备系统、平台、任务、场景、保障体系或训练评估应用；
8. constraints：环境、工程、资源、时间、可靠性或安全约束；
9. military_value_dimensions：与任务效能、生存力、感知、打击、保障、体系协同等军事价值相关的维度；
10. innovation_objectives：需要发现的组合、迁移、替代、跨域应用或能力跃迁方向；
11. weak_signal_terms：查询明确暗示的前沿、新原理、新材料、新器件或低频高价值技术线索。

要求：
- 每项必须是 JSON 字符串数组，最多 12 项；没有则返回空数组；
- 保留原查询中的专业术语，不杜撰型号、参数或事实；
- 不输出解释、Markdown、实体关系或答案。

查询：{query}

严格返回：
{{
  "low_level_keywords": [],
  "high_level_keywords": [],
  "concept_targets": [],
  "principle_terms": [],
  "technology_terms": [],
  "capability_targets": [],
  "application_targets": [],
  "constraints": [],
  "military_value_dimensions": [],
  "innovation_objectives": [],
  "weak_signal_terms": []
}}"""
