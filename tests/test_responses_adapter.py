from __future__ import annotations

from knowledgegraph.demand_discovery.llm.model_config import ModelConfig
from knowledgegraph.demand_discovery.llm.responses_adapter import build_provider_request
from knowledgegraph.demand_discovery.llm.types import LLMContext


def test_legacy_endpoint_mode_uses_standard_responses_api() -> None:
    request = build_provider_request(
        ModelConfig(
            provider="openai",
            model="gpt-5.5",
            base_url="https://gateway.example/openai",
            endpoint_mode="codex_backend",
        ),
        LLMContext(messages=[]),
        [],
        {},
    )

    assert request["url"] == "https://gateway.example/v1/responses"
    assert "OpenAI-Beta" not in request["headers"]
    assert "originator" not in request["headers"]
