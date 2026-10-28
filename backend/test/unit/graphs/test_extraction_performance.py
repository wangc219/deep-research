"""抽取预算、连接复用和故障重试策略。"""

from types import SimpleNamespace
import asyncio
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from platform_core.knowledge.graphs.extractors.llm import ExtractionOutputTruncatedError, LLMGraphExtractor
from platform_core.knowledge.graphs.extractors.base import normalize_extraction_result, verify_extraction_evidence
from platform_core.knowledge.graphs.milvus_graph_service import MilvusGraphService, is_retryable_extraction_error


@pytest.mark.asyncio
async def test_extraction_reuses_client_and_expands_only_truncated_responses(monkeypatch):
    models = []

    def create(**kwargs):
        budget = kwargs["model_params"]["max_tokens"]
        model = SimpleNamespace(
            call=AsyncMock(
                return_value=SimpleNamespace(
                    content='{"relations": []}', finish_reason="length" if budget == 4096 else "stop"
                )
            ),
            aclose=AsyncMock(),
        )
        models.append((kwargs, model))
        return model

    monkeypatch.setattr("platform_core.knowledge.graphs.extractors.llm.select_model", create)
    extractor = LLMGraphExtractor(
        {"model_spec": "siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash", "max_output_tokens": 4096}
    )
    await extractor.extract("样本一")
    await extractor.extract("样本二")
    assert len(models) == 2
    assert [item[0]["model_params"]["max_tokens"] for item in models] == [4096, 8192]
    assert models[0][0]["model_params"]["extra_body"] == {"enable_thinking": True, "thinking_budget": 2048}
    assert models[0][0]["model_params"]["max_retries"] == 0
    await extractor.aclose()
    for _, model in models:
        model.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_truncation_never_saves_partial_json(monkeypatch):
    factory = Mock(
        return_value=SimpleNamespace(
            call=AsyncMock(return_value=SimpleNamespace(content='{"relations": []}', finish_reason="length"))
        )
    )
    monkeypatch.setattr("platform_core.knowledge.graphs.extractors.llm.select_model", factory)
    extractor = LLMGraphExtractor({"model_spec": "test:model", "max_output_tokens": 16384})
    with pytest.raises(ExtractionOutputTruncatedError):
        await extractor.extract("长文本")
    assert factory.call_count == 2


@pytest.mark.parametrize(
    "params",
    [
        {"max_output_tokens": True},
        {"max_output_tokens": 65536},
        {"enable_thinking": "false"},
        {"model_params": {"extra_body": []}},
    ],
)
def test_invalid_performance_options_rejected(params):
    with pytest.raises(ValueError):
        LLMGraphExtractor({"model_spec": "test:model", **params}).validate_options()


@pytest.mark.parametrize("status,expected", [(400, False), (401, False), (429, True), (503, True)])
def test_retryable_http_errors(status, expected):
    error = RuntimeError("wrapped")
    error.__cause__ = httpx.HTTPStatusError(
        "response", request=httpx.Request("POST", "https://example.test"), response=httpx.Response(status)
    )
    assert is_retryable_extraction_error(error) is expected


@pytest.mark.asyncio
async def test_invalid_json_fails_once_without_wasting_retries():
    chunk = SimpleNamespace(
        chunk_id="c", file_id="f", chunk_index=0, content="text", extraction_result=None, graph_extraction_details={}
    )
    extractor = SimpleNamespace(extractor_type="llm", extract=AsyncMock(side_effect=ValueError("invalid JSON")))
    repo = SimpleNamespace(mark_graph_extraction_failed=AsyncMock(), update_extraction_result=AsyncMock())
    service = MilvusGraphService(chunk_repo=repo)
    with pytest.raises(ValueError):
        await service._get_chunk_extraction_result("kb", chunk, extractor)
    extractor.extract.assert_awaited_once()
    repo.mark_graph_extraction_failed.assert_awaited_once_with("c", 1, "invalid JSON")


def test_fact_quotes_are_checked_without_dropping_relations():
    relation = {
        "source": {"text": "算法", "label": "Technology"},
        "target": {"text": "精度", "label": "Capability"},
        "text": "提升",
        "claim_level": "Fact",
        "confidence": 0.9,
    }
    result = normalize_extraction_result(
        {
            "relations": [
                {**relation, "evidence_quote": "精度提高 １０％"},
                {**relation, "evidence_quote": "精度达到百分之百"},
            ]
        },
        "llm",
    )
    verified = verify_extraction_evidence(result, "实验显示，精度提高\n10%。")
    assert len(verified["relations"]) == 2
    assert verified["relations"][0]["claim_level"] == "Fact"
    assert verified["relations"][1]["claim_level"] == "Inference"
    assert verified["relations"][1]["expert_review_required"] is True
    assert verified["metadata"]["evidence_verification"] == {"verified_facts": 1, "reclassified_facts": 1}


@pytest.mark.asyncio
async def test_extraction_has_wall_clock_deadline_even_when_transport_is_alive(monkeypatch):
    cancelled = asyncio.Event()

    async def call(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(
        "platform_core.knowledge.graphs.extractors.llm.select_model", lambda **kwargs: SimpleNamespace(call=call)
    )
    extractor = LLMGraphExtractor({"model_spec": "test:model", "timeout_seconds": 0.01})
    with pytest.raises(TimeoutError, match="超过 0.01 秒"):
        await extractor.extract("text")
    assert cancelled.is_set()
