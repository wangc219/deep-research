from __future__ import annotations

import pytest

from platform_core.knowledge.graphs.evidence_grounded_solution import generate_grounded_solution


class _Generator:
    def __init__(self, output):
        self.output = output
        self.payload = None
        self.closed = False

    async def generate(self, payload):
        self.payload = payload
        return self.output

    async def aclose(self):
        self.closed = True


def _valid_output():
    return {
        "mechanism_hypothesis": "技术 A 可能通过机理 B 支撑能力 C。",
        "feasibility_basis": ["已有路径记录技术 A 与机理 B 的关联。"],
        "expected_effects": ["有望提升能力 C，但需要系统级验证。"],
        "uncertainties": ["尚无系统级试验结果。"],
        "citations": [
            {"claim_path": "mechanism_hypothesis", "evidence_ids": ["E001"]},
            {"claim_path": "feasibility_basis[0]", "evidence_ids": ["E001"]},
            {"claim_path": "expected_effects[0]", "evidence_ids": ["E001"]},
        ],
        "claim_level": "Hypothesis",
    }


@pytest.mark.asyncio
async def test_generates_hypothesis_and_closes_adapter():
    generator = _Generator(_valid_output())

    result = await generate_grounded_solution(
        query="能力需求",
        query_analysis={"target_capabilities": ["能力 C"]},
        paths=[{"path_id": "p1"}],
        evidence=[{"evidence_id": "E001", "text": "原始证据"}],
        model_spec="provider:model",
        discovery_mode="bottom_up",
        generator_factory=lambda _: generator,
    )

    assert result["claim_level"] == "Hypothesis"
    assert generator.payload["evidence"][0]["text"] == "原始证据"
    assert generator.payload["discovery_mode"] == "bottom_up"
    assert generator.payload["generation_version"] == "defense-evidence-grounded-solution-v2"
    assert generator.closed is True


@pytest.mark.asyncio
async def test_rejects_unknown_evidence_id_and_still_closes_adapter():
    output = _valid_output()
    output["citations"][0]["evidence_ids"] = ["E999"]
    generator = _Generator(output)

    with pytest.raises(ValueError, match="未提供的证据 ID"):
        await generate_grounded_solution(
            query="能力需求",
            query_analysis={},
            paths=[{"path_id": "p1"}],
            evidence=[{"evidence_id": "E001", "text": "原始证据"}],
            model_spec="provider:model",
            generator_factory=lambda _: generator,
        )

    assert generator.closed is True


@pytest.mark.asyncio
async def test_rejects_uncited_generated_claim():
    output = _valid_output()
    output["citations"] = output["citations"][:1]

    with pytest.raises(ValueError, match="缺少证据引用"):
        await generate_grounded_solution(
            query="能力需求",
            query_analysis={},
            paths=[{"path_id": "p1"}],
            evidence=[{"evidence_id": "E001", "text": "原始证据"}],
            model_spec="provider:model",
            generator_factory=lambda _: _Generator(output),
        )


@pytest.mark.asyncio
async def test_refuses_generation_without_evidence_before_model_creation():
    with pytest.raises(ValueError, match="拒绝生成"):
        await generate_grounded_solution(
            query="能力需求",
            query_analysis={},
            paths=[{"path_id": "p1"}],
            evidence=[],
            model_spec="provider:model",
            generator_factory=lambda _: pytest.fail("不应创建模型"),
        )


@pytest.mark.asyncio
async def test_rejects_unknown_discovery_mode_before_model_creation():
    with pytest.raises(ValueError, match="discovery_mode"):
        await generate_grounded_solution(
            query="能力需求",
            query_analysis={},
            paths=[{"path_id": "p1"}],
            evidence=[{"evidence_id": "E001", "text": "原始证据"}],
            model_spec="provider:model",
            discovery_mode="sideways",  # type: ignore[arg-type]
            generator_factory=lambda _: pytest.fail("不应创建模型"),
        )
