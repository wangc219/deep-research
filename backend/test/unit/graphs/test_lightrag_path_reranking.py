from __future__ import annotations

import pytest

from platform_core.knowledge.graphs.lightrag_path_reranking import LightRAGPathReranker


def _path(path_id: str, score: float, relation_id: str, *, name: str) -> dict:
    return {
        "path_id": path_id,
        "score": score,
        "route_kind": "principle_to_capability",
        "claim_level": "Fact",
        "semantic_coverage": 0.6,
        "nodes": [
            {"id": f"{path_id}-n1", "name": name, "type": "KeyTechnology", "semantic_role": "technology"},
            {"id": f"{path_id}-n2", "name": "抗干扰能力", "type": "Capability", "semantic_role": "capability"},
        ],
        "relations": [
            {
                "id": relation_id,
                "type": "ENABLES_CAPABILITY",
                "evidence_count": 2,
                "properties": {"evidence_quote": "不应发送的原文证据"},
            }
        ],
        "relation_ids": [relation_id],
        "evidence": {"support_level": "multi_source"},
        "evidence_gaps": [],
        "research_inspiration": {"research_threads": {"main": [name], "side": ["验证约束"], "parallel": ["备选路线"]}},
    }


@pytest.mark.asyncio
async def test_path_reranker_is_disabled_by_default_without_model_call():
    calls = 0

    async def complete(_prompt):
        nonlocal calls
        calls += 1
        return {"rankings": []}

    paths = [_path("p1", 2.0, "r1", name="相控阵"), _path("p2", 1.8, "r2", name="宽带射频")]
    result = await LightRAGPathReranker(completion=complete).rerank(
        query="提升抗干扰能力",
        mode="requirement_driven",
        paths=paths,
    )

    assert calls == 0
    assert [item["path_id"] for item in result["paths"]] == ["p1", "p2"]
    assert result["provenance"]["status"] == "disabled"


@pytest.mark.asyncio
async def test_path_reranker_reorders_only_closed_candidates_and_keeps_grounding():
    captured_prompt = ""

    async def complete(prompt):
        nonlocal captured_prompt
        captured_prompt = prompt
        return {
            "rankings": [
                {
                    "path_id": "p2",
                    "query_relevance": 1.0,
                    "mechanism_coherence": 1.0,
                    "evidence_strength": 1.0,
                    "innovation_value": 1.0,
                    "supporting_relation_ids": ["r2", "invented"],
                },
                {
                    "path_id": "p1",
                    "query_relevance": 0.0,
                    "mechanism_coherence": 0.0,
                    "evidence_strength": 0.0,
                    "innovation_value": 0.0,
                    "supporting_relation_ids": ["r1"],
                },
                {
                    "path_id": "invented-path",
                    "query_relevance": 1.0,
                    "mechanism_coherence": 1.0,
                    "evidence_strength": 1.0,
                    "innovation_value": 1.0,
                    "supporting_relation_ids": ["invented"],
                },
            ]
        }

    paths = [_path("p1", 2.0, "r1", name="相控阵"), _path("p2", 1.8, "r2", name="宽带射频")]
    result = await LightRAGPathReranker(
        {"enabled": True, "model_spec": "local:military-chat"},
        completion=complete,
    ).rerank(query="提升抗干扰能力", mode="requirement_driven", paths=paths)

    assert [item["path_id"] for item in result["paths"]] == ["p2", "p1"]
    assert {item["path_id"] for item in result["paths"]} == {"p1", "p2"}
    assert result["paths"][0]["llm_rerank"]["supporting_relation_ids"] == ["r2"]
    assert result["paths"][0]["relations"] == paths[1]["relations"]
    assert result["provenance"]["ranked_count"] == 2
    assert "不应发送的原文证据" not in captured_prompt
    assert "research_threads" in captured_prompt
    assert "main" in captured_prompt
    assert "主线" in captured_prompt
    assert "parallel" in captured_prompt
    assert "组合路线" in captured_prompt


@pytest.mark.asyncio
async def test_path_reranker_rejects_ungrounded_scores_and_degrades_without_reordering():
    async def complete(_prompt):
        return {
            "rankings": [
                {
                    "path_id": "p2",
                    "query_relevance": 1.0,
                    "mechanism_coherence": 1.0,
                    "evidence_strength": 1.0,
                    "innovation_value": 1.0,
                    "supporting_relation_ids": ["not-on-path"],
                }
            ]
        }

    paths = [_path("p1", 2.0, "r1", name="相控阵"), _path("p2", 1.8, "r2", name="宽带射频")]
    result = await LightRAGPathReranker(
        {"enabled": True, "model_spec": "local:military-chat"},
        completion=complete,
    ).rerank(query="提升抗干扰能力", mode="entity_expansion", paths=paths)

    assert [item["path_id"] for item in result["paths"]] == ["p1", "p2"]
    assert result["provenance"]["status"] == "completed"
    assert result["provenance"]["ranked_count"] == 0


@pytest.mark.asyncio
async def test_path_reranker_requires_boundary_and_minimum_relation_coverage():
    async def complete(_prompt):
        return {
            "rankings": [
                {
                    "path_id": "p2",
                    "query_relevance": 1.0,
                    "mechanism_coherence": 1.0,
                    "evidence_strength": 1.0,
                    "innovation_value": 1.0,
                    "supporting_relation_ids": ["r2-middle"],
                }
            ]
        }

    multi_hop = _path("p2", 1.8, "r2-first", name="宽带射频")
    multi_hop["relations"] = [
        {"id": "r2-first", "type": "BASED_ON", "evidence_count": 2},
        {"id": "r2-middle", "type": "APPLIED_TO", "evidence_count": 2},
        {"id": "r2-last", "type": "ENABLES_CAPABILITY", "evidence_count": 2},
    ]
    multi_hop["relation_ids"] = ["r2-first", "r2-middle", "r2-last"]
    paths = [_path("p1", 2.0, "r1", name="相控阵"), multi_hop]
    result = await LightRAGPathReranker(
        {"enabled": True, "model_spec": "local:military-chat"},
        completion=complete,
    ).rerank(query="提升抗干扰能力", mode="entity_expansion", paths=paths)

    assert [item["path_id"] for item in result["paths"]] == ["p1", "p2"]
    assert "llm_rerank" not in next(item for item in result["paths"] if item["path_id"] == "p2")
    assert result["provenance"]["ranked_count"] == 0
    assert result["provenance"]["requires_boundary_relations"] is True
    assert result["provenance"]["min_relation_coverage"] == pytest.approx(0.6667)


@pytest.mark.asyncio
async def test_path_reranker_accepts_complete_multihop_citations_and_records_coverage():
    async def complete(_prompt):
        return {
            "rankings": [
                {
                    "path_id": "p2",
                    "query_relevance": 1.0,
                    "mechanism_coherence": 1.0,
                    "evidence_strength": 1.0,
                    "innovation_value": 1.0,
                    "supporting_relation_ids": ["r2-first", "r2-middle", "r2-last"],
                }
            ]
        }

    multi_hop = _path("p2", 1.8, "r2-first", name="宽带射频")
    multi_hop["relations"] = [
        {"id": "r2-first", "type": "BASED_ON", "evidence_count": 2},
        {"id": "r2-middle", "type": "APPLIED_TO", "evidence_count": 2},
        {"id": "r2-last", "type": "ENABLES_CAPABILITY", "evidence_count": 2},
    ]
    multi_hop["relation_ids"] = ["r2-first", "r2-middle", "r2-last"]
    result = await LightRAGPathReranker(
        {"enabled": True, "model_spec": "local:military-chat"},
        completion=complete,
    ).rerank(
        query="提升抗干扰能力",
        mode="entity_expansion",
        paths=[_path("p1", 2.0, "r1", name="相控阵"), multi_hop],
    )

    enhanced = next(item for item in result["paths"] if item["path_id"] == "p2")["llm_rerank"]
    assert enhanced["evidence_coverage"] == 1.0
    assert enhanced["required_relation_count"] == 2
    assert enhanced["boundary_relation_ids"] == ["r2-first", "r2-last"]


@pytest.mark.asyncio
async def test_path_reranker_failure_is_observable_and_strict_mode_raises():
    async def fail(_prompt):
        raise TimeoutError("private detail")

    paths = [_path("p1", 2.0, "r1", name="相控阵"), _path("p2", 1.8, "r2", name="宽带射频")]
    degraded = await LightRAGPathReranker(
        {"enabled": True, "model_spec": "local:military-chat"},
        completion=fail,
    ).rerank(query="提升抗干扰能力", mode="requirement_driven", paths=paths)

    assert degraded["provenance"]["status"] == "degraded"
    assert degraded["provenance"]["failure_type"] == "TimeoutError"
    assert "private detail" not in str(degraded)

    with pytest.raises(TimeoutError):
        await LightRAGPathReranker(
            {"enabled": True, "model_spec": "local:military-chat", "strict": True},
            completion=fail,
        ).rerank(query="提升抗干扰能力", mode="requirement_driven", paths=paths)


@pytest.mark.asyncio
async def test_path_reranker_bounds_large_candidate_context_without_full_degradation():
    captured_prompt = ""

    async def complete(prompt):
        nonlocal captured_prompt
        captured_prompt = prompt
        return {"rankings": []}

    paths = []
    for index in range(30):
        path = _path(f"p{index}", 30 - index, f"r{index}", name=f"宽带技术{index}")
        long_value = "跨域迁移与复杂电磁环境验证" * 20
        path["evidence_gaps"] = [long_value] * 8
        path["research_inspiration"] = {
            "research_threads": {
                "main": [long_value] * 8,
                "side": [long_value] * 8,
                "parallel": [long_value] * 8,
            },
            "value_signals": [{"entity": long_value, "label": long_value, "text": long_value} for _ in range(8)],
        }
        paths.append(path)

    result = await LightRAGPathReranker(
        {"enabled": True, "model_spec": "local:military-chat"},
        completion=complete,
    ).rerank(query="提升抗干扰能力", mode="requirement_driven", paths=paths)

    provenance = result["provenance"]
    assert provenance["status"] == "completed"
    assert provenance["context_limited"] is True
    assert 2 <= provenance["prompt_candidate_count"] < provenance["candidate_count"] == 30
    assert provenance["omitted_candidate_count"] == 30 - provenance["prompt_candidate_count"]
    assert len(captured_prompt) < 30_000
