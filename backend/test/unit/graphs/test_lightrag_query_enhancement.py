from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from platform_core.knowledge.graphs.lightrag_query_enhancement import (
    LightRAGQueryPlanner,
    graph_keyword_entity_hits,
    graph_keyword_queries,
    merge_graph_subgraphs,
    normalize_retrieval_mode,
    reciprocal_rank_fuse_graph_hits,
    retrieval_queries,
)


@pytest.mark.asyncio
async def test_disabled_query_planner_never_calls_llm():
    completion = AsyncMock(side_effect=AssertionError("不应调用模型"))
    planner = LightRAGQueryPlanner({"enabled": False}, completion=completion)

    result = await planner.plan("复杂电磁环境下的目标感知")

    completion.assert_not_awaited()
    assert result["low_level_keywords"] == ["复杂电磁环境下的目标感知"]
    assert result["provenance"]["status"] == "disabled"
    assert result["provenance"]["llm_used"] is False


@pytest.mark.asyncio
async def test_query_planner_normalizes_low_and_high_level_keywords():
    completion = AsyncMock(
        return_value={
            "low_level_keywords": ["相控阵雷达", "  相控阵雷达  ", "波束形成"],
            "high_level_keywords": ["抗干扰机理"],
            "concept_targets": ["复杂电磁环境"],
            "principle_terms": ["波束形成机理"],
            "technology_terms": ["自适应波束形成技术"],
            "capability_targets": ["复杂环境感知"],
            "application_targets": ["机载雷达系统"],
            "constraints": ["低功耗"],
            "military_value_dimensions": ["体系协同"],
            "innovation_objectives": ["跨域迁移"],
            "weak_signal_terms": ["新型射频材料"],
        }
    )
    planner = LightRAGQueryPlanner(
        {"enabled": True, "model_spec": "local:model"},
        completion=completion,
    )

    result = await planner.plan("复杂环境感知")
    local_query, global_query = retrieval_queries(result)

    assert result["low_level_keywords"] == ["相控阵雷达", "波束形成"]
    assert local_query == "复杂环境感知；相控阵雷达；波束形成"
    assert global_query == (
        "复杂环境感知；抗干扰机理；复杂电磁环境；波束形成机理；自适应波束形成技术；"
        "机载雷达系统；低功耗；体系协同；跨域迁移；新型射频材料"
    )
    assert result["provenance"] == {
        "planner_version": "lightrag-query-planner-v4",
        "status": "completed",
        "model_spec": "local:model",
        "llm_used": True,
    }


def test_retrieval_queries_never_drop_original_query_after_llm_rewrite():
    local_query, global_query = retrieval_queries(
        {
            "query": "低功耗条件下提升复杂电磁环境感知能力",
            "low_level_keywords": ["相控阵雷达", "波束形成"],
            "high_level_keywords": ["抗干扰机理"],
            "concept_targets": ["复杂电磁环境"],
            "principle_terms": ["波束形成机理"],
            "technology_terms": ["自适应波束形成技术"],
            "capability_targets": ["环境感知"],
            "application_targets": ["机载雷达系统"],
            "constraints": ["低功耗"],
            "military_value_dimensions": ["生存力"],
            "innovation_objectives": ["技术组合"],
            "weak_signal_terms": ["新原理"],
        }
    )

    assert local_query.startswith("低功耗条件下提升复杂电磁环境感知能力；")
    assert global_query.startswith("低功耗条件下提升复杂电磁环境感知能力；")
    assert "生存力；技术组合；新原理" in global_query


def test_graph_keyword_queries_keep_short_entity_terms_instead_of_one_long_sentence():
    terms = graph_keyword_queries(
        {
            "query": "分布式自适应规划控制与载荷即插即用技术可以形成哪些能力",
            "low_level_keywords": ["分布式自适应规划控制", "载荷即插即用技术"],
            "technology_terms": ["开放式体系架构"],
            "capability_targets": ["载荷即插即用能力"],
        }
    )

    assert terms == [
        "分布式自适应规划控制",
        "载荷即插即用技术",
        "开放式体系架构",
        "载荷即插即用能力",
    ]


def test_graph_keyword_entity_hits_return_stable_exact_and_partial_anchors():
    graph = {
        "nodes": [
            {
                "id": "neo4j-tech",
                "name": "分布式自适应规划控制",
                "properties": {"entity_id": "tech-1"},
            },
            {
                "id": "neo4j-cap",
                "name": "载荷即插即用能力",
                "properties": {"entity_id": "cap-1"},
            },
            {"id": "neo4j-other", "name": "无关实体", "properties": {"entity_id": "other-1"}},
        ]
    }

    hits = graph_keyword_entity_hits(graph, ["分布式自适应规划控制", "载荷即插即用"])

    assert [(item["id"], item["keyword"]) for item in hits] == [
        ("tech-1", "分布式自适应规划控制"),
        ("cap-1", "载荷即插即用"),
    ]


@pytest.mark.asyncio
async def test_query_planner_prompt_encodes_top_down_and_bottom_up_five_role_strategy():
    completion = AsyncMock(
        return_value={
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
            "weak_signal_terms": [],
        }
    )
    planner = LightRAGQueryPlanner({"enabled": True, "model_spec": "project:model"}, completion=completion)

    await planner.plan("提升复杂环境感知能力")

    prompt = completion.await_args.args[0]
    assert "需求/问题 → 原理 → 技术 → 能力 → 应用 → 证据" in prompt
    assert "面向新质技术的自下而上发现" in prompt
    assert "这里只生成召回词，不得把潜在链路写成事实" in prompt


@pytest.mark.asyncio
async def test_query_planner_degrades_without_leaking_failure_message():
    completion = AsyncMock(side_effect=RuntimeError("含敏感内部地址"))
    planner = LightRAGQueryPlanner(
        {"enabled": True, "model_spec": "local:model", "strict": False},
        completion=completion,
    )

    result = await planner.plan("技术 A")

    assert result["provenance"]["status"] == "degraded"
    assert result["provenance"]["failure_type"] == "RuntimeError"
    assert "含敏感内部地址" not in str(result)


@pytest.mark.asyncio
async def test_query_planner_strict_mode_propagates_failure():
    planner = LightRAGQueryPlanner(
        {"enabled": True, "model_spec": "local:model", "strict": True},
        completion=AsyncMock(side_effect=RuntimeError("offline")),
    )

    with pytest.raises(RuntimeError, match="offline"):
        await planner.plan("技术 A")


def test_reciprocal_rank_fusion_uses_entity_and_triple_endpoints():
    result = reciprocal_rank_fuse_graph_hits(
        [{"id": "entity-a"}, {"id": "entity-b"}],
        [{"source_id": "entity-b", "target_id": "entity-c"}],
    )

    assert result["entity_ids"][0] == "entity-b"
    assert set(result["entity_ids"]) == {"entity-a", "entity-b", "entity-c"}
    assert result["sources_by_entity_id"]["entity-b"] == ["entity", "triple"]
    assert result["relevance_by_entity_id"]["entity-b"] == 1.0
    assert result["fusion_method"] == "reciprocal-rank-fusion-v1"


def test_reciprocal_rank_fusion_adds_only_explicit_chunk_entity_anchors():
    result = reciprocal_rank_fuse_graph_hits(
        [{"id": "entity-a"}],
        [],
        [{"id": "entity-b", "chunk_id": "chunk-1"}, {"id": "entity-a", "chunk_id": "chunk-2"}],
    )

    assert result["entity_ids"][0] == "entity-a"
    assert set(result["entity_ids"]) == {"entity-a", "entity-b"}
    assert result["sources_by_entity_id"]["entity-a"] == ["chunk", "entity"]
    assert result["sources_by_entity_id"]["entity-b"] == ["chunk"]


def test_reciprocal_rank_fusion_prioritizes_exact_keyword_entity_anchors():
    result = reciprocal_rank_fuse_graph_hits(
        [{"id": "semantic-1"}],
        [],
        [],
        [{"id": "keyword-1"}],
    )

    assert result["entity_ids"][:2] == ["keyword-1", "semantic-1"]
    assert result["sources_by_entity_id"]["keyword-1"] == ["keyword"]
    assert result["relevance_by_entity_id"]["keyword-1"] == 1.0


def test_reciprocal_rank_fusion_uses_one_relationship_source_for_all_relations():
    result = reciprocal_rank_fuse_graph_hits(
        [],
        [
            {
                "source_id": "entity-a",
                "target_id": "entity-b",
            }
        ],
    )

    assert result["sources_by_entity_id"] == {
        "entity-a": ["triple"],
        "entity-b": ["triple"],
    }


def test_merge_graph_subgraphs_deduplicates_stable_ids():
    result = merge_graph_subgraphs(
        {"nodes": [{"id": "n1"}], "edges": [{"id": "e1"}]},
        {"nodes": [{"id": "n1"}, {"id": "n2"}], "edges": [{"id": "e1"}, {"id": "e2"}]},
    )

    assert [node["id"] for node in result["nodes"]] == ["n1", "n2"]
    assert [edge["id"] for edge in result["edges"]] == ["e1", "e2"]


@pytest.mark.parametrize("value", ["semantic", "unknown"])
def test_retrieval_mode_rejects_unsupported_values(value):
    with pytest.raises(ValueError, match="retrieval_mode"):
        normalize_retrieval_mode(value)


def test_retrieval_mode_defaults_to_mix():
    assert normalize_retrieval_mode(None) == "mix"


def test_retrieval_mode_accepts_upstream_naive_mode():
    assert normalize_retrieval_mode("NAIVE") == "naive"
