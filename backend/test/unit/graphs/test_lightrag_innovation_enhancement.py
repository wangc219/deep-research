from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from platform_core.knowledge.graphs.lightrag_innovation_enhancement import (
    LightRAGInnovationEnhancer,
    apply_innovation_enhancements,
)
from platform_core.knowledge.graphs.extractors.llm import ExtractionOutputTruncatedError


def _candidate(hypothesis_id: str = "hyp-1") -> dict:
    return {
        "hypothesis_id": hypothesis_id,
        "source": {"entity_id": "entity-a", "name": "技术 A"},
        "target": {"entity_id": "entity-c", "name": "能力 C"},
        "relation_type": "POTENTIAL_FOR",
        "score": 0.6,
        "score_components": {"score": 0.6},
        "evidence_path": {"path_id": "path-1", "relation_ids": ["r1", "r2"]},
        "mechanism_hypothesis": "原始假设",
        "feasibility_basis": [],
        "expected_effects": [],
        "applicable_conditions": [],
        "uncertainties": ["需验证"],
        "claim_level": "Hypothesis",
        "review_status": "pending",
        "expert_review_required": True,
    }


@pytest.mark.asyncio
async def test_disabled_innovation_enhancer_never_calls_llm():
    completion = AsyncMock(side_effect=AssertionError("不应调用模型"))
    enhancer = LightRAGInnovationEnhancer({"enabled": False}, completion=completion)
    candidates = [_candidate()]

    result = await enhancer.enhance(
        query="能力需求",
        discovery_mode="top_down",
        query_analysis={},
        path_result={"paths": []},
        candidates=candidates,
    )

    completion.assert_not_awaited()
    assert result["candidates"] is candidates
    assert result["report"]["status"] == "disabled"


def test_innovation_enhancement_preserves_identity_and_requires_path_citation():
    candidates = [_candidate()]
    payload = {
        "hypotheses": [
            {
                "hypothesis_id": "hyp-1",
                "supporting_relation_ids": ["r1", "r2", "forged-relation"],
                "source": {"entity_id": "forged"},
                "relation_type": "FORGED",
                "mechanism_hypothesis": "技术 A 可能经中间机理影响能力 C。",
                "feasibility_basis": ["路径 r2 提供间接依据。"],
                "expected_effects": ["可能改善能力。"],
                "applicable_conditions": ["低功耗条件"],
                "uncertainties": ["缺少系统试验。"],
                "validation_requirements": ["在低功耗条件下开展对照试验。"],
                "falsification_criteria": ["对照试验未观察到能力增益。"],
                "constraint_conflicts": [],
                "cross_domain_extrapolation": False,
                "score_adjustment": 0.9,
            }
        ]
    }

    enhanced, applied, rejected = apply_innovation_enhancements(
        candidates,
        payload,
        model_spec="local:model",
    )

    assert applied == 1
    assert rejected == 0
    assert enhanced[0]["source"] == candidates[0]["source"]
    assert enhanced[0]["target"] == candidates[0]["target"]
    assert enhanced[0]["relation_type"] == "POTENTIAL_FOR"
    assert enhanced[0]["score"] == 0.75
    assert enhanced[0]["claim_level"] == "Hypothesis"
    assert enhanced[0]["review_status"] == "pending"
    assert enhanced[0]["llm_enhancement"]["supporting_relation_ids"] == ["r1", "r2"]
    assert enhanced[0]["llm_enhancement"]["evidence_coverage"] == 1.0
    assert enhanced[0]["llm_enhancement"]["boundary_coverage_satisfied"] is True
    assert enhanced[0]["llm_enhancement"]["score_adjustment"] == 0.15
    assert enhanced[0]["evidence_path"]["llm_enhancement"] == enhanced[0]["llm_enhancement"]


def test_innovation_enhancement_records_complete_advisory_value_dimensions():
    candidate = _candidate()
    candidate["innovation_profile"] = {"strategic_score": 0.58, "advisory_only": True}
    payload = {
        "hypotheses": [
            {
                "hypothesis_id": "hyp-1",
                "supporting_relation_ids": ["r1", "r2"],
                "validation_requirements": ["开展独立对照试验"],
                "falsification_criteria": ["未观察到可重复能力增益"],
                "constraint_conflicts": [],
                "cross_domain_extrapolation": False,
                "innovation_dimensions": {
                    "military_value": 0.9,
                    "novelty": 0.8,
                    "feasibility": 0.6,
                    "transferability": 0.7,
                    "evidence_strength": 0.65,
                    "weak_signal_potential": 0.75,
                },
                "innovation_rationale": ["具备跨文档技术迁移线索", "仍需工程样机验证"],
            }
        ]
    }

    enhanced, applied, rejected = apply_innovation_enhancements(
        [candidate],
        payload,
        model_spec="project:model",
    )

    assert (applied, rejected) == (1, 0)
    assessment = enhanced[0]["innovation_profile"]["llm_assessment"]
    assert assessment["dimensions"]["weak_signal_potential"] == 0.75
    assert assessment["rationale"] == ["具备跨文档技术迁移线索", "仍需工程样机验证"]
    assert assessment["advisory_only"] is True


def test_innovation_enhancement_rejects_unknown_or_uncited_hypotheses():
    candidate = _candidate()
    payload = {
        "hypotheses": [
            {"hypothesis_id": "unknown", "supporting_relation_ids": ["r1"]},
            {"hypothesis_id": "hyp-1", "supporting_relation_ids": ["forged"]},
        ]
    }

    enhanced, applied, rejected = apply_innovation_enhancements(
        [candidate],
        payload,
        model_spec="local:model",
    )

    assert applied == 0
    assert rejected == 2
    assert enhanced == [candidate]


def test_innovation_enhancement_rejects_single_edge_citation_and_missing_falsification():
    candidate = _candidate()
    payload = {
        "hypotheses": [
            {
                "hypothesis_id": "hyp-1",
                "supporting_relation_ids": ["r1"],
                "validation_requirements": ["开展对照试验"],
                "falsification_criteria": ["未观察到增益"],
                "cross_domain_extrapolation": False,
            },
        ]
    }

    enhanced, applied, rejected = apply_innovation_enhancements(
        [candidate],
        payload,
        model_spec="local:model",
    )

    assert applied == 0
    assert rejected == 1
    assert enhanced == [candidate]

    payload["hypotheses"][0]["supporting_relation_ids"] = ["r1", "r2"]
    payload["hypotheses"][0]["falsification_criteria"] = []
    enhanced, applied, rejected = apply_innovation_enhancements(
        [candidate],
        payload,
        model_spec="local:model",
    )
    assert (applied, rejected) == (0, 1)
    assert enhanced == [candidate]


def test_innovation_enhancement_penalizes_gaps_conflicts_and_cross_document_inference():
    candidate = _candidate()
    candidate["evidence_path"].update(
        {
            "evidence_gaps": ["缺少系统集成验证"],
            "cross_document": True,
        }
    )
    payload = {
        "hypotheses": [
            {
                "hypothesis_id": "hyp-1",
                "supporting_relation_ids": ["r1", "r2"],
                "validation_requirements": ["系统级硬件在环验证"],
                "falsification_criteria": ["重复试验未达到预设阈值"],
                "constraint_conflicts": ["功耗约束与实时性目标冲突"],
                "cross_domain_extrapolation": True,
                "score_adjustment": 0.15,
            }
        ]
    }

    enhanced, applied, rejected = apply_innovation_enhancements(
        [candidate],
        payload,
        model_spec="local:model",
    )

    assert (applied, rejected) == (1, 0)
    metadata = enhanced[0]["llm_enhancement"]
    assert metadata["requested_score_adjustment"] == 0.15
    assert metadata["risk_penalties"]["total"] == 0.12
    assert metadata["score_adjustment"] == 0.03
    assert enhanced[0]["score"] == 0.63
    assert enhanced[0]["constraint_conflicts"] == ["功耗约束与实时性目标冲突"]


def test_innovation_enhancement_normalizes_bounded_scalar_validation_fields():
    payload = {
        "hypotheses": [
            {
                "hypothesis_id": "hyp-1",
                "supporting_relation_ids": ["r1", "r2"],
                "validation_requirements": "开展独立对照试验",
                "falsification_criteria": "未观察到可重复增益",
                "constraint_conflicts": "实时性与功耗约束冲突",
                "feasibility_basis": "已有两跳事实路径",
                "expected_effects": "可能提升感知能力",
                "cross_domain_extrapolation": False,
            }
        ]
    }

    enhanced, applied, rejected = apply_innovation_enhancements(
        [_candidate()],
        payload,
        model_spec="local:model",
    )

    assert (applied, rejected) == (1, 0)
    metadata = enhanced[0]["llm_enhancement"]
    assert metadata["structure_normalized_by_platform"] is True
    assert metadata["normalized_fields"] == [
        "feasibility_basis",
        "expected_effects",
        "validation_requirements",
        "falsification_criteria",
        "constraint_conflicts",
    ]
    assert enhanced[0]["validation_requirements"] == ["开展独立对照试验"]
    assert enhanced[0]["expected_effects"] == ["可能提升感知能力"]


@pytest.mark.asyncio
async def test_innovation_enhancer_degrades_without_leaking_internal_error():
    enhancer = LightRAGInnovationEnhancer(
        {"enabled": True, "model_spec": "local:model", "strict": False},
        completion=AsyncMock(side_effect=RuntimeError("敏感内部地址")),
    )

    result = await enhancer.enhance(
        query="能力需求",
        discovery_mode="top_down",
        query_analysis={},
        path_result={"paths": []},
        candidates=[_candidate()],
    )

    assert result["report"]["status"] == "degraded"
    assert result["report"]["failure_type"] == "RuntimeError"
    assert "敏感内部地址" not in str(result)


@pytest.mark.asyncio
async def test_innovation_enhancer_strict_mode_propagates_failure():
    enhancer = LightRAGInnovationEnhancer(
        {"enabled": True, "model_spec": "local:model", "strict": True},
        completion=AsyncMock(side_effect=RuntimeError("offline")),
    )

    with pytest.raises(RuntimeError, match="offline"):
        await enhancer.enhance(
            query="能力需求",
            discovery_mode="bottom_up",
            query_analysis={},
            path_result={"paths": []},
            candidates=[_candidate()],
        )


@pytest.mark.asyncio
async def test_innovation_prompt_includes_bounded_authoritative_evidence_quote():
    completion = AsyncMock(
        return_value={
            "hypotheses": [
                {
                    "hypothesis_id": "hyp-1",
                    "supporting_relation_ids": ["r1", "r2"],
                    "mechanism_hypothesis": "基于原文证据的受约束解释。",
                    "validation_requirements": ["开展对照验证"],
                    "falsification_criteria": ["未观察到距离分辨率提升"],
                    "constraint_conflicts": [],
                    "cross_domain_extrapolation": False,
                    "score_adjustment": 0,
                }
            ]
        }
    )
    enhancer = LightRAGInnovationEnhancer(
        {"enabled": True, "model_spec": "local:model"},
        completion=completion,
    )
    path_result = {
        "paths": [
            {
                "path_id": "path-1",
                "nodes": [],
                "relations": [
                    {
                        "id": "r1",
                        "type": "ENABLES_CAPABILITY",
                        "properties": {
                            "claim_level": "Fact",
                            "evidence_quote": "脉冲压缩能够提高距离分辨率。",
                            "file_id": "file-1",
                            "chunk_id": "chunk-1",
                        },
                    },
                    {
                        "id": "r2",
                        "type": "USED_IN",
                        "properties": {
                            "claim_level": "Fact",
                            "evidence_quote": "该方法用于复杂电磁环境。",
                            "file_id": "file-2",
                            "chunk_id": "chunk-2",
                        },
                    },
                ],
                "research_inspiration": {
                    "research_threads": {
                        "main": ["脉冲压缩"],
                        "side": ["距离分辨率试验"],
                        "parallel": ["备选调制路线"],
                    }
                },
                "evidence_gaps": [],
            }
        ]
    }

    result = await enhancer.enhance(
        query="提升距离分辨率",
        discovery_mode="top_down",
        query_analysis={},
        path_result=path_result,
        candidates=[_candidate()],
    )

    prompt = completion.await_args.args[0]
    assert "脉冲压缩能够提高距离分辨率。" in prompt
    assert "chunk-1" in prompt
    assert "boundary_relation_ids" in prompt
    assert "falsification_criteria" in prompt
    assert "research_threads" in prompt
    assert "脉冲压缩" in prompt
    assert "main 支撑基准贡献链" in prompt
    assert "parallel 用于" in prompt
    assert "不授权生成新节点、新关系、新证据" in prompt
    assert result["report"]["applied_count"] == 1


@pytest.mark.asyncio
async def test_innovation_enhancer_repairs_structure_once_without_relaxing_evidence_gate():
    completion = AsyncMock(
        side_effect=[
            {
                "hypotheses": [
                    {
                        "hypothesis_id": "hyp-1",
                        "supporting_relation_ids": ["r1"],
                        "validation_requirements": ["开展验证"],
                        "falsification_criteria": ["未观察到增益"],
                        "cross_domain_extrapolation": False,
                    }
                ]
            },
            {
                "hypotheses": [
                    {
                        "hypothesis_id": "hyp-1",
                        "supporting_relation_ids": ["r1", "r2"],
                        "mechanism_hypothesis": "经完整两跳路径形成待验证机理。",
                        "validation_requirements": ["开展独立对照试验"],
                        "falsification_criteria": ["未观察到可重复增益"],
                        "constraint_conflicts": [],
                        "cross_domain_extrapolation": False,
                        "score_adjustment": 0,
                    }
                ]
            },
        ]
    )
    enhancer = LightRAGInnovationEnhancer(
        {"enabled": True, "model_spec": "local:model"},
        completion=completion,
    )

    result = await enhancer.enhance(
        query="能力需求",
        discovery_mode="top_down",
        query_analysis={},
        path_result={"paths": []},
        candidates=[_candidate()],
    )

    assert completion.await_count == 2
    assert "上次输出未通过平台结构门禁" in completion.await_args_list[1].args[0]
    assert result["report"]["structure_repair_attempted"] is True
    assert result["report"]["applied_count"] == 1
    assert result["report"]["rejection_reasons"] == {}
    assert result["candidates"][0]["llm_enhancement"]["evidence_coverage"] == 1.0


def _enhancement_payload(*hypothesis_ids: str) -> dict:
    return {
        "hypotheses": [
            {
                "hypothesis_id": hypothesis_id,
                "supporting_relation_ids": ["r1", "r2"],
                "mechanism_hypothesis": f"{hypothesis_id} 的待验证机理。",
                "validation_requirements": ["开展独立对照试验"],
                "falsification_criteria": ["重复试验未观察到预期增益"],
                "constraint_conflicts": [],
                "cross_domain_extrapolation": False,
                "score_adjustment": 0,
            }
            for hypothesis_id in hypothesis_ids
        ]
    }


@pytest.mark.asyncio
async def test_innovation_enhancer_batches_eight_candidates_with_2048_token_budget():
    completion = AsyncMock(
        side_effect=[
            _enhancement_payload("hyp-0", "hyp-1"),
            _enhancement_payload("hyp-2", "hyp-3"),
            _enhancement_payload("hyp-4", "hyp-5"),
            _enhancement_payload("hyp-6", "hyp-7"),
        ]
    )
    enhancer = LightRAGInnovationEnhancer(
        {
            "enabled": True,
            "model_spec": "project:model",
            "max_output_tokens": 2048,
        },
        completion=completion,
    )

    result = await enhancer.enhance(
        query="能力需求",
        discovery_mode="bottom_up",
        query_analysis={},
        path_result={"paths": []},
        candidates=[_candidate(f"hyp-{index}") for index in range(8)],
    )

    assert completion.await_count == 4
    assert all("当前批次恰有 2 条候选" in call.args[0] for call in completion.await_args_list)
    assert all("面向新质技术的自下而上" in call.args[0] for call in completion.await_args_list)
    assert all("预测结果永远保持 Hypothesis/pending" in call.args[0] for call in completion.await_args_list)
    assert result["report"] == {
        "version": "lightrag-innovation-enhancement-v5",
        "status": "completed",
        "model_spec": "project:model",
        "applied_count": 8,
        "rejected_count": 0,
        "min_evidence_coverage": 0.6667,
        "requires_boundary_relations": True,
        "requires_validation_and_falsification": True,
        "rejection_reasons": {},
        "structure_repair_attempted": False,
        "structure_repair_count": 0,
        "llm_calls": 4,
        "batches": 4,
        "requested_candidates": 8,
        "applied_candidates": 8,
        "max_hypotheses_per_call": 2,
        "output_budget": 2048,
        "concurrency_count": 2,
        "degraded_batches": 0,
        "degraded_batch_indices": [],
        "truncated_batches": 0,
        "truncated_batch_indices": [],
        "failure_types": {},
    }


@pytest.mark.asyncio
async def test_innovation_enhancer_preserves_successful_batches_when_one_batch_truncates():
    completion = AsyncMock(
        side_effect=[
            _enhancement_payload("hyp-0", "hyp-1"),
            ExtractionOutputTruncatedError("length"),
            _enhancement_payload("hyp-4"),
        ]
    )
    candidates = [_candidate(f"hyp-{index}") for index in range(5)]
    enhancer = LightRAGInnovationEnhancer(
        {
            "enabled": True,
            "model_spec": "project:model",
            "max_output_tokens": 2048,
        },
        completion=completion,
    )

    result = await enhancer.enhance(
        query="能力需求",
        discovery_mode="bottom_up",
        query_analysis={},
        path_result={"paths": []},
        candidates=candidates,
    )

    assert result["report"]["status"] == "partial"
    assert result["report"]["applied_count"] == 3
    assert result["report"]["degraded_batch_indices"] == [1]
    assert result["report"]["truncated_batch_indices"] == [1]
    assert result["report"]["failure_types"] == {"ExtractionOutputTruncatedError": 1}
    by_id = {item["hypothesis_id"]: item for item in result["candidates"]}
    assert "llm_enhancement" in by_id["hyp-0"]
    assert "llm_enhancement" not in by_id["hyp-2"]
    assert "llm_enhancement" not in by_id["hyp-3"]
    assert "llm_enhancement" in by_id["hyp-4"]


@pytest.mark.asyncio
async def test_innovation_enhancer_runs_candidate_batches_with_bounded_parallelism():
    active = 0
    peak = 0
    both_started = asyncio.Event()

    async def completion(prompt: str) -> dict:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if peak >= 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=0.2)
        active -= 1
        hypothesis_id = "hyp-0" if "hyp-0" in prompt else "hyp-1"
        return _enhancement_payload(hypothesis_id)

    enhancer = LightRAGInnovationEnhancer(
        {
            "enabled": True,
            "model_spec": "project:model",
            "max_output_tokens": 1024,
            "max_hypotheses_per_call": 1,
            "concurrency_count": 2,
        },
        completion=completion,
    )

    result = await enhancer.enhance(
        query="能力需求",
        discovery_mode="top_down",
        query_analysis={},
        path_result={"paths": []},
        candidates=[_candidate("hyp-0"), _candidate("hyp-1")],
    )

    assert peak == 2
    assert result["report"]["concurrency_count"] == 2
    assert result["report"]["applied_count"] == 2
