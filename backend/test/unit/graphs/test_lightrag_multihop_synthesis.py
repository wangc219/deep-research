from __future__ import annotations

import pytest

from platform_core.knowledge.graphs.lightrag_multihop_synthesis import LightRAGMultiHopSynthesizer


def _path() -> dict:
    return {
        "path_id": "path-1",
        "claim_level": "Fact",
        "score": 4.2,
        "nodes": [
            {"name": "分布式孔径", "type": "KeyTechnology", "semantic_role": "technology"},
            {"name": "协同探测", "type": "Capability", "semantic_role": "capability"},
        ],
        "relations": [{"id": "relation-1", "type": "ENABLES_CAPABILITY", "evidence_count": 2}],
        "relation_ids": ["relation-1"],
        "evidence": {"chunk_ids": ["chunk-1"], "file_ids": ["file-1"]},
        "evidence_gaps": ["缺少极端干扰条件测试"],
        "research_inspiration": {},
    }


@pytest.mark.asyncio
async def test_multihop_synthesis_keeps_only_closed_evidence_citations():
    async def complete(_prompt):
        item = {
            "statement": "分布式孔径可沿现有关系支撑协同探测能力。",
            "path_ids": ["path-1", "invented-path"],
            "relation_ids": ["relation-1", "invented-relation"],
            "chunk_ids": ["chunk-1", "invented-chunk"],
            "file_ids": ["file-1", "invented-file"],
        }
        return {
            "executive_conclusion": "现有证据支持该技术到能力的路径，但仍有验证边界。",
            "conclusion_path_ids": ["path-1", "invented-path"],
            "reasoning_chain": [item],
            "key_findings": [item],
            "technology_routes": [item],
            "capability_implications": [item],
            "application_directions": [item],
            "evidence_boundaries": [item],
            "unresolved_questions": [item],
        }

    result = await LightRAGMultiHopSynthesizer(
        {"enabled": True, "model_spec": "cloud:model"},
        completion=complete,
    ).synthesize(query="协同探测", discovery_mode="bottom_up", paths=[_path()])

    assert result["provenance"]["status"] == "completed"
    assert result["provenance"]["creates_graph_facts"] is False
    assert result["provenance"]["creates_innovation_hypotheses"] is False
    assert result["narrative"]["conclusion_path_ids"] == ["path-1"]
    finding = result["narrative"]["key_findings"][0]
    assert finding["path_ids"] == ["path-1"]
    assert finding["relation_ids"] == ["relation-1"]
    assert finding["chunk_ids"] == ["chunk-1"]
    assert finding["file_ids"] == ["file-1"]


@pytest.mark.asyncio
async def test_multihop_synthesis_degrades_when_conclusion_has_no_valid_path_reference():
    async def complete(_prompt):
        return {
            "executive_conclusion": "无依据结论",
            "conclusion_path_ids": ["invented"],
            "reasoning_chain": [],
            "key_findings": [],
            "technology_routes": [],
            "capability_implications": [],
            "application_directions": [],
            "evidence_boundaries": [],
            "unresolved_questions": [],
        }

    result = await LightRAGMultiHopSynthesizer(
        {"enabled": True, "model_spec": "cloud:model"},
        completion=complete,
    ).synthesize(query="协同探测", discovery_mode="top_down", paths=[_path()])

    assert result["narrative"] is None
    assert result["provenance"]["status"] == "degraded"


@pytest.mark.asyncio
async def test_multihop_synthesis_does_not_call_model_without_paths():
    calls = 0

    async def complete(_prompt):
        nonlocal calls
        calls += 1
        return {}

    result = await LightRAGMultiHopSynthesizer(
        {"enabled": True, "model_spec": "cloud:model"},
        completion=complete,
    ).synthesize(query="协同探测", discovery_mode="top_down", paths=[])

    assert calls == 0
    assert result["provenance"]["status"] == "no_evidence"
