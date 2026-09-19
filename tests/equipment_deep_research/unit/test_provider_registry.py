from __future__ import annotations

import asyncio
import json
from pathlib import Path
import subprocess

import pytest

from equipment_deep_research.providers.fake import ScriptedFakeProvider
from equipment_deep_research.providers.registry import ProviderConfigurationError, ProviderRegistry
from equipment_deep_research.providers.base import ModelMessage, ProviderFinalTurn, ProviderStreamEvent, ProviderToolCall
from equipment_deep_research.providers.cli_agent import ExternalCliProvider
from equipment_deep_research.providers.codex import CodexCliProvider
from equipment_deep_research.providers.fallback import FallbackProvider
from equipment_deep_research.providers.openai_compatible import OpenAICompatibleProvider, build_chat_payload
from equipment_deep_research.providers.responses import ProviderCapacityError, ProviderRequestError


PROVIDER_CONFIG = Path(__file__).parents[3] / "configs/equipment_deep_research/providers.yaml"


def test_provider_registry_defaults_to_codex_cli() -> None:
    registry = ProviderRegistry.load(PROVIDER_CONFIG)
    assert registry.default_provider == "codex"
    assert registry.profile_snapshot()["type"] == "codex_cli"
    assert registry.profile_snapshot()["base_url_host"] == "api.openai.com"


def test_codex_registry_can_disable_global_config_inheritance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.setenv("PROJECT_CODEX_KEY", "test-project-key")
    provider = ProviderRegistry.load(PROVIDER_CONFIG).create(
        "codex",
        base_url="https://codex.example.test/v1",
        api_key_env="PROJECT_CODEX_KEY",
        workspace_path=tmp_path,
    )

    assert provider.inherit_user_config is False


def test_codex_registry_rejects_local_login_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.delenv("EQUIPMENT_DR_CODEX_BASE_URL", raising=False)
    monkeypatch.delenv("EQUIPMENT_DR_CODEX_API_KEY_ENV", raising=False)

    with pytest.raises(
        ProviderConfigurationError,
        match="local ChatGPT/Codex login inheritance is disabled",
    ):
        ProviderRegistry.load(PROVIDER_CONFIG).create(
            "codex",
            workspace_path=tmp_path,
        )


def test_codex_registry_reads_configured_api_key_environment_and_base_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.setenv("PROJECT_CODEX_KEY", "test-project-codex-key")
    provider = ProviderRegistry.load(PROVIDER_CONFIG).create(
        "codex",
        model="codex-model",
        base_url="https://codex.example.test/v1",
        api_key_env="PROJECT_CODEX_KEY",
        workspace_path=tmp_path,
    )

    assert provider.model == "codex-model"
    assert provider.base_url == "https://codex.example.test/v1"
    assert provider.snapshot()["base_url_host"] == "codex.example.test"
    assert "test-project-codex-key" not in repr(provider)
    assert "test-project-codex-key" not in str(provider.snapshot())


def test_codex_registry_accepts_full_responses_endpoint_as_base_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.setenv("PROJECT_CODEX_KEY", "test-project-codex-key")

    provider = ProviderRegistry.load(PROVIDER_CONFIG).create(
        "codex",
        base_url="https://codex.example.test/v1/responses",
        api_key_env="PROJECT_CODEX_KEY",
        workspace_path=tmp_path,
    )

    assert provider.base_url == "https://codex.example.test/v1"


def test_codex_registry_isolates_each_agent_context_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.setenv("PROJECT_CODEX_KEY", "test-project-codex-key")
    registry = ProviderRegistry.load(PROVIDER_CONFIG)

    situation = registry.create(
        "codex",
        base_url="https://codex.example.test/v1",
        api_key_env="PROJECT_CODEX_KEY",
        workspace_path=tmp_path,
        isolation_key="international_situation",
    )
    equipment = registry.create(
        "codex",
        base_url="https://codex.example.test/v1",
        api_key_env="PROJECT_CODEX_KEY",
        workspace_path=tmp_path,
        isolation_key="weapon_equipment",
    )

    assert situation.codex_home != equipment.codex_home
    assert situation.codex_home.name == "international_situation"
    assert equipment.codex_home.name == "weapon_equipment"
    assert situation.snapshot()["context_isolation"] == "international_situation"
    assert equipment.snapshot()["context_isolation"] == "weapon_equipment"


def test_codex_registry_rejects_missing_configured_api_key_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.delenv("MISSING_CODEX_KEY", raising=False)

    with pytest.raises(ProviderConfigurationError, match="MISSING_CODEX_KEY"):
        ProviderRegistry.load(PROVIDER_CONFIG).create(
            "codex",
            api_key_env="MISSING_CODEX_KEY",
            workspace_path=tmp_path,
        )


def test_provider_registry_builds_default_gpt55_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_API_KEY", "test-key")
    monkeypatch.setenv("EQUIPMENT_DR_RESPONSES_MODEL", "gpt-5.5")
    registry = ProviderRegistry.load(PROVIDER_CONFIG)
    provider = registry.create("responses")
    assert provider.model == "gpt-5.5"
    assert "test-key" not in repr(provider)
    assert provider.snapshot()["base_url_host"] == "api.openai.com"


def test_provider_registry_builds_deepseek_openai_compatible_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("EQUIPMENT_DR_DEEPSEEK_MODEL", "deepseek-chat")
    monkeypatch.setenv(
        "EQUIPMENT_DR_DEEPSEEK_BASE_URL",
        "https://api.deepseek.com/v1/chat/completions",
    )
    provider = ProviderRegistry.load(PROVIDER_CONFIG).create(
        "deepseek", workspace_path=tmp_path
    )
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.model == "deepseek-chat"
    assert provider.base_url.endswith("/v1/chat/completions")
    assert provider.snapshot()["type"] == "chat_completions"


def test_deepseek_fallback_does_not_inherit_primary_codex_model(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("EQUIPMENT_DR_MODEL", "gpt-5.5")
    monkeypatch.setenv("EQUIPMENT_DR_DEEPSEEK_MODEL", "deepseek-chat")
    monkeypatch.setenv(
        "EQUIPMENT_DR_DEEPSEEK_BASE_URL",
        "https://api.deepseek.com/v1/chat/completions",
    )

    provider = ProviderRegistry.load(PROVIDER_CONFIG).create(
        "deepseek", workspace_path=tmp_path
    )

    assert provider.model == "deepseek-chat"


def test_chat_payload_is_provider_neutral() -> None:
    payload = build_chat_payload(
        "deepseek-reasoner",
        [],
        [],
        {"output_schema": {"answer": "string"}},
        structured_mode="json_object",
    )
    assert payload["model"] == "deepseek-reasoner"
    assert payload["response_format"] == {"type": "json_object"}


def test_chat_payload_adds_json_marker_for_json_object_gateways() -> None:
    payload = build_chat_payload(
        "deepseek-v4-flash-0731",
        [ModelMessage("user", "请输出符合字段约束的结构化结果")],
        [],
        {"output_schema": {"ok": "boolean"}},
        structured_mode="json_object",
    )

    assert payload["response_format"] == {"type": "json_object"}
    assert any(
        "json" in str(message.get("content", "")).lower()
        for message in payload["messages"]
    )


def test_chat_payload_does_not_duplicate_json_marker() -> None:
    payload = build_chat_payload(
        "deepseek-v4-flash-0731",
        [ModelMessage("user", "Return valid JSON only")],
        [],
        {"output_schema": {"ok": "boolean"}},
        structured_mode="json_object",
    )

    assert len(payload["messages"]) == 1


def test_chat_provider_retries_empty_length_reasoning_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenAICompatibleProvider(
        provider_id="codex-deepseek",
        model="deepseek-v4-flash-0731",
        base_url="https://gateway.example.test/v1/chat/completions",
        api_key="test-key",
    )
    calls: list[int] = []

    def fake_post(payload: dict) -> list[str]:
        calls.append(int(payload["max_tokens"]))
        if len(calls) == 1:
            return [
                'data: {"choices":[{"delta":{"reasoning_content":"thinking"},"finish_reason":null}]}\n',
                'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n',
                "data: [DONE]\n",
            ]
        return [
            'data: {"choices":[{"delta":{"content":"{\\"findings\\":[{\\"statement\\":\\"ok\\"}]}"},"finish_reason":"stop"}]}\n',
            "data: [DONE]\n",
        ]

    monkeypatch.setattr(provider, "_post", fake_post)

    async def collect() -> list[ProviderStreamEvent]:
        return [
            event
            async for event in provider.stream(
                [ModelMessage("user", "return JSON")],
                [],
                {"max_output_tokens": 1200, "output_schema": {"findings": []}},
            )
        ]

    events = asyncio.run(collect())
    final = events[-1].final_turn
    assert calls == [1200, 8192]
    assert final is not None
    assert final.finish_reason == "stop"
    assert final.text and "findings" in final.text


def test_chat_provider_keeps_empty_length_turn_when_retry_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_CHAT_COMPLETIONS_MAX_RETRIES", "1")
    provider = OpenAICompatibleProvider(
        provider_id="codex-deepseek",
        model="deepseek-v4-flash-0731",
        base_url="https://gateway.example.test/v1/chat/completions",
        api_key="test-key",
    )
    calls = 0

    def fake_post(_payload: dict) -> list[str]:
        nonlocal calls
        calls += 1
        return [
            'data: {"choices":[{"delta":{"reasoning_content":"thinking"},"finish_reason":null}]}\n',
            'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n',
            "data: [DONE]\n",
        ]

    monkeypatch.setattr(provider, "_post", fake_post)

    async def collect() -> list[ProviderStreamEvent]:
        return [
            event
            async for event in provider.stream(
                [ModelMessage("user", "return JSON")],
                [],
                {"max_output_tokens": 1200},
            )
        ]

    events = asyncio.run(collect())
    final = events[-1].final_turn
    assert calls == 2
    assert final is not None
    assert final.text is None
    assert final.finish_reason == "length"


def test_chat_provider_negotiates_plain_json_when_gateway_rejects_response_format(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = OpenAICompatibleProvider(
        provider_id="codex-deepseek",
        model="deepseek-v4-flash-0731",
        base_url="https://gateway.example.test/v1/chat/completions",
        api_key="test-key",
        structured_mode="json_object",
    )
    payloads: list[dict] = []

    def fake_post(payload: dict) -> list[str]:
        payloads.append(dict(payload))
        if len(payloads) == 1:
            raise ProviderRequestError(
                "codex-deepseek Chat Completions request failed: status=400 "
                'detail={"error":{"message":"This response_format type is unavailable now"}}'
            )
        return [
            'data: {"choices":[{"delta":{"content":"{\\"ok\\":true}"},"finish_reason":"stop"}]}\n',
            "data: [DONE]\n",
        ]

    monkeypatch.setattr(provider, "_post", fake_post)

    async def collect() -> list[ProviderStreamEvent]:
        return [
            event
            async for event in provider.stream(
                [ModelMessage("user", "return JSON")],
                [],
                {"output_schema": {"ok": "boolean"}},
            )
        ]

    events = asyncio.run(collect())
    final = events[-1].final_turn
    assert len(payloads) == 2
    assert payloads[0].get("response_format") == {"type": "json_object"}
    assert "response_format" not in payloads[1]
    assert final is not None
    assert final.text and "ok" in final.text
    assert final.metadata["structured_output_fallback"] is True


def test_real_provider_requires_its_environment_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EQUIPMENT_DR_API_KEY", raising=False)
    registry = ProviderRegistry.load(PROVIDER_CONFIG)
    with pytest.raises(ProviderConfigurationError, match="EQUIPMENT_DR_API_KEY"):
        registry.create("responses")


def test_scripted_fake_provider_can_emit_tool_then_final_text() -> None:
    provider = ScriptedFakeProvider([
        [ProviderStreamEvent.tool_call_event(ProviderToolCall("call-1", "search_sources", {"query": "test"}))],
        [ProviderStreamEvent.final(ProviderFinalTurn(text="done"))],
    ])
    assert provider.remaining_steps == 2


def test_registry_exposes_configured_external_cli_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.registry.shutil.which",
        lambda command: f"/usr/local/bin/{command}" if command else None,
    )
    registry = ProviderRegistry.load(PROVIDER_CONFIG)

    options = {item["id"]: item for item in registry.public_options()["providers"]}

    assert options["claude"]["type"] == "external_cli"
    assert options["claude"]["driver"] == "claude_json"
    assert options["claude"]["available"] is True
    assert options["generic_cli"]["driver"] == "jsonl"


def test_registry_builds_claude_code_adapter(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.cli_agent.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")

    provider = ProviderRegistry.load(PROVIDER_CONFIG).create(
        "claude",
        workspace_path=tmp_path,
        isolation_key="reporter",
    )

    assert isinstance(provider, ExternalCliProvider)
    assert provider.provider_id == "claude"
    assert provider.protocol == "claude_json"
    assert provider.capabilities().structured_output is True
    assert provider.snapshot()["context_isolation"] == "reporter"
    assert "test-anthropic-key" not in repr(provider.snapshot())


def test_external_provider_model_can_be_selected_by_provider_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.cli_agent.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("EQUIPMENT_DR_CLAUDE_MODEL", "alternate-claude-model")
    provider = ProviderRegistry.load(PROVIDER_CONFIG).create(
        "claude", workspace_path=tmp_path, isolation_key="model-switch"
    )
    assert provider.model == "alternate-claude-model"


def test_claude_adapter_normalizes_structured_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.cli_agent.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    provider = ExternalCliProvider(
        provider_id="claude",
        command="claude",
        protocol="claude_json",
        workspace_path=tmp_path,
        schema_flag="--json-schema",
        schema_mode="inline",
    )

    turn = provider._parse_output(
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "session_id": "session-1",
                "structured_output": {"summary": "done"},
                "usage": {"input_tokens": 10, "output_tokens": 3},
            }
        )
    )

    assert turn.text == '{"summary":"done"}'
    assert turn.finish_reason == "success"
    assert turn.metadata["session_id"] == "session-1"
    assert turn.usage["output_tokens"] == 3


@pytest.mark.parametrize("disable_timeout", [False, True])
def test_external_cli_stream_passes_reporter_timeout_override(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    disable_timeout: bool,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.cli_agent.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    provider = ExternalCliProvider(
        provider_id="claude",
        command="claude",
        protocol="text",
        workspace_path=tmp_path,
        timeout_seconds=7,
    )
    observed: list[bool] = []

    async def fake_execute(command, prompt, *, disable_timeout=False):
        del command, prompt
        observed.append(disable_timeout)
        return subprocess.CompletedProcess(
            args=["claude"],
            returncode=0,
            stdout="报告正文",
            stderr="",
        )

    monkeypatch.setattr(provider, "_execute", fake_execute)

    async def collect():
        return [
            event
            async for event in provider.stream(
                [ModelMessage("user", "写报告")],
                [],
                {"_disable_provider_timeout": disable_timeout},
            )
        ]

    events = asyncio.run(collect())
    assert observed == [disable_timeout]
    assert events[0].final_turn.text == "报告正文"


@pytest.mark.parametrize("disable_timeout", [False, True])
def test_external_cli_execute_only_uses_wall_timeout_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    disable_timeout: bool,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.cli_agent.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    provider = ExternalCliProvider(
        provider_id="claude",
        command="claude",
        protocol="text",
        workspace_path=tmp_path,
        timeout_seconds=7,
    )

    class FakeProcess:
        pid = 1234
        returncode = 0

        async def communicate(self, _prompt):
            return b"done", b""

    async def fake_create_process(*args, **kwargs):
        del args, kwargs
        return FakeProcess()

    wait_for_calls: list[float] = []

    async def fake_wait_for(awaitable, *, timeout):
        wait_for_calls.append(timeout)
        return await awaitable

    monkeypatch.setattr(
        "equipment_deep_research.providers.cli_agent.asyncio.create_subprocess_exec",
        fake_create_process,
    )
    monkeypatch.setattr(
        "equipment_deep_research.providers.cli_agent.asyncio.wait_for",
        fake_wait_for,
    )
    monkeypatch.setattr(
        "equipment_deep_research.providers.cli_agent.register_process_group",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "equipment_deep_research.providers.cli_agent.release_process_group",
        lambda *args, **kwargs: None,
    )

    result = asyncio.run(
        provider._execute(
            ["claude"],
            "报告正文",
            disable_timeout=disable_timeout,
        )
    )
    assert result.stdout == "done"
    assert wait_for_calls == ([] if disable_timeout else [7])


def test_provider_registry_builds_explicit_fallback_chain(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.cli_agent.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setenv("PROJECT_CODEX_KEY", "test-codex-key")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_API_KEY_ENV", "PROJECT_CODEX_KEY")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_BASE_URL", "https://api.openai.com/v1")

    registry = ProviderRegistry.load(PROVIDER_CONFIG)
    chain = registry.create_chain(
        "claude",
        fallback_profiles=["codex"],
        workspace_path=tmp_path,
        api_key_env="ANTHROPIC_API_KEY",
        base_url="https://api.anthropic.com",
        isolation_key="orchestrator",
    )

    assert isinstance(chain, FallbackProvider)
    assert len(chain.providers) == 2
    assert chain.snapshot()["type"] == "fallback_chain"
    assert chain.providers[0].base_url == "https://api.anthropic.com"
    assert chain.providers[1].base_url == "https://api.openai.com/v1"


def test_codex_capacity_fallback_is_optional_without_deepseek_credential(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.setenv("PROJECT_CODEX_KEY", "test-codex-key")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("EQUIPMENT_DR_DEEPSEEK_API_KEY_ENV", raising=False)

    registry = ProviderRegistry.load(PROVIDER_CONFIG)
    chain = registry.create_chain(
        "codex",
        fallback_profiles=registry.profile("codex")["fallback_providers"],
        workspace_path=tmp_path,
        api_key_env="PROJECT_CODEX_KEY",
        base_url="https://codex.example.test/v1",
    )

    assert isinstance(chain, CodexCliProvider)


def test_codex_capacity_fallback_builds_only_when_deepseek_is_configured(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.setenv("PROJECT_CODEX_KEY", "test-codex-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    monkeypatch.setenv(
        "EQUIPMENT_DR_CODEX_DEEPSEEK_BASE_URL",
        "https://api.deepseek.com/",
    )

    registry = ProviderRegistry.load(PROVIDER_CONFIG)
    chain = registry.create_chain(
        "codex",
        fallback_profiles=registry.profile("codex")["fallback_providers"],
        workspace_path=tmp_path,
        api_key_env="PROJECT_CODEX_KEY",
        base_url="https://codex.example.test/v1",
    )

    assert isinstance(chain, FallbackProvider)
    assert chain.fallback_policy == "capacity_only"
    assert isinstance(chain.providers[1], CodexCliProvider)


def test_direct_deepseek_model_profile_accepts_no_fallback_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    monkeypatch.setenv("EQUIPMENT_DR_DEEPSEEK_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv(
        "EQUIPMENT_DR_CODEX_DEEPSEEK_BASE_URL",
        "http://127.0.0.1:8787/v1",
    )

    provider = ProviderRegistry.load(PROVIDER_CONFIG).create_model_profile(
        "codex-deepseek",
        workspace_path=tmp_path,
        isolation_key="reporter-fallback",
    )

    assert isinstance(provider, CodexCliProvider)
    assert provider.model == "deepseek-v4-flash"
    assert provider.base_url == "http://127.0.0.1:8787/v1"


def test_task_model_profiles_keep_codex_models_and_endpoints_isolated(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.setenv("EQUIPMENT_DR_PROVIDER", "codex")
    monkeypatch.setenv("EQUIPMENT_DR_MODEL", "gpt-5.5")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_API_KEY", "gpt-key")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("EQUIPMENT_DR_DEEPSEEK_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv(
        "EQUIPMENT_DR_CODEX_DEEPSEEK_BASE_URL",
        "https://api.deepseek.com/",
    )
    monkeypatch.setenv("QUEEN_API_KEY", "queen-key")
    monkeypatch.setenv("EQUIPMENT_DR_QUEEN_MODEL", "qwen3.8-flash")
    monkeypatch.setenv(
        "EQUIPMENT_DR_QUEEN_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    registry = ProviderRegistry.load(PROVIDER_CONFIG)
    providers = {
        profile: registry.create_model_profile(
            profile,
            workspace_path=tmp_path,
            isolation_key=f"task-{profile}",
        )
        for profile in ("codex-gpt", "codex-deepseek", "codex-queen")
    }
    task_providers = {
        name: provider.providers[0]
        if isinstance(provider, FallbackProvider)
        else provider
        for name, provider in providers.items()
    }

    assert all(
        isinstance(provider, CodexCliProvider)
        for provider in task_providers.values()
    )
    assert {name: provider.model for name, provider in task_providers.items()} == {
        "codex-gpt": "gpt-5.5",
        "codex-deepseek": "deepseek-v4-flash",
        "codex-queen": "qwen3.8-flash",
    }
    assert {name: provider.base_url for name, provider in task_providers.items()} == {
        "codex-gpt": "https://api.openai.com/v1",
        "codex-deepseek": "https://api.deepseek.com",
        "codex-queen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    }
    assert len({provider.codex_home for provider in task_providers.values()}) == 3


class _RaisingProvider:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def capabilities(self):
        return ScriptedFakeProvider([]).capabilities()

    async def stream(self, messages, tools, options):
        del messages, tools, options
        raise self.error
        yield  # pragma: no cover


def test_capacity_only_fallback_does_not_mask_non_capacity_errors() -> None:
    fallback = FallbackProvider(
        [_RaisingProvider(ProviderRequestError("bad request")), ScriptedFakeProvider([])],
        fallback_policy="capacity_only",
    )

    async def collect():
        return [
            event
            async for event in fallback.stream([], [], {})
        ]

    with pytest.raises(ProviderRequestError, match="bad request"):
        import asyncio

        asyncio.run(collect())


def test_capacity_only_fallback_switches_after_capacity_error() -> None:
    backup = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text="fallback"))]]
    )
    fallback = FallbackProvider(
        [_RaisingProvider(ProviderCapacityError("at capacity")), backup],
        fallback_policy="capacity_only",
    )

    async def collect():
        return [
            event
            async for event in fallback.stream([], [], {})
        ]

    import asyncio

    events = asyncio.run(collect())
    assert events[-1].final_turn.text == "fallback"
    assert events[-1].final_turn.metadata["fallback_activated"] is True
    assert events[-1].final_turn.metadata["fallback_reason"] == "capacity"
    assert events[-1].final_turn.metadata["fallback_from"] == "provider"


def test_reporter_can_force_deepseek_after_non_capacity_primary_failure() -> None:
    primary = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text="must not run"))]]
    )
    backup = ScriptedFakeProvider(
        [[ProviderStreamEvent.final(ProviderFinalTurn(text="repaired column"))]]
    )
    fallback = FallbackProvider(
        [primary, backup],
        fallback_policy="capacity_only",
    )

    async def collect():
        return [
            event
            async for event in fallback.stream(
                [ModelMessage("user", "repair only the failed report column")],
                [],
                {
                    "_force_fallback_provider": True,
                    "_fallback_reason": "report_chapter_retry_exhausted",
                },
            )
        ]

    events = asyncio.run(collect())

    assert primary.inputs == []
    assert events[-1].final_turn.text == "repaired column"
    assert events[-1].final_turn.metadata["fallback_activated"] is True
    assert (
        events[-1].final_turn.metadata["fallback_reason"]
        == "report_chapter_retry_exhausted"
    )


def test_codex_chain_uses_deepseek_after_capacity_budget_is_exhausted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.shutil.which",
        lambda command: f"/usr/local/bin/{command}",
    )
    monkeypatch.setenv("PROJECT_CODEX_KEY", "test-codex-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")
    monkeypatch.setenv(
        "EQUIPMENT_DR_CODEX_DEEPSEEK_BASE_URL",
        "https://api.deepseek.com/",
    )
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_CAPACITY_RETRY_ATTEMPTS", "2")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_CAPACITY_RETRY_BACKOFF_SECONDS", "0")
    monkeypatch.setenv("EQUIPMENT_DR_CODEX_CAPACITY_RETRY_JITTER_SECONDS", "0")
    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(
        "equipment_deep_research.providers.codex.asyncio.sleep",
        no_sleep,
    )

    registry = ProviderRegistry.load(PROVIDER_CONFIG)
    chain = registry.create_chain(
        "codex",
        fallback_profiles=registry.profile("codex")["fallback_providers"],
        workspace_path=tmp_path,
        api_key_env="PROJECT_CODEX_KEY",
        base_url="https://codex.example.test/v1",
    )
    assert isinstance(chain, FallbackProvider)
    codex, deepseek = chain.providers

    def capacity_execute(command, prompt):
        del prompt
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=json.dumps(
                {
                    "type": "turn.failed",
                    "error": {"message": "Selected model is at capacity"},
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(codex, "_execute", capacity_execute)

    def fallback_execute(command, prompt):
        del prompt
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="\n".join(
                [
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {"type": "agent_message", "text": "fallback"},
                        }
                    ),
                    json.dumps({"type": "turn.completed"}),
                ]
            ),
            stderr="",
        )

    monkeypatch.setattr(deepseek, "_execute", fallback_execute)

    async def collect():
        return [
            event
            async for event in chain.stream(
                [ModelMessage("user", "capacity")],
                [],
                {},
            )
        ]

    events = asyncio.run(collect())
    assert events[-1].final_turn.text == "fallback"
    assert len(events) == 1


def test_openai_compatible_normalizes_root_and_v1_urls() -> None:
    from equipment_deep_research.providers.openai_compatible import (
        normalize_chat_completions_url,
    )

    assert (
        normalize_chat_completions_url("https://api.deepseek.com")
        == "https://api.deepseek.com/v1/chat/completions"
    )
    assert (
        normalize_chat_completions_url("https://relay.example/v1")
        == "https://relay.example/v1/chat/completions"
    )
    assert (
        normalize_chat_completions_url(
            "https://relay.example/v1/chat/completions"
        )
        == "https://relay.example/v1/chat/completions"
    )
