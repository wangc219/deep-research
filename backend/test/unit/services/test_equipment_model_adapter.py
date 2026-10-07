import os
from pathlib import Path

from platform_core.models.providers.cache import ModelInfo
from platform_core.services.equipment_model_adapter import (
    apply_equipment_model_env,
    bind_equipment_execution,
    resolve_equipment_model,
    runner_call_from_runtime,
    runtime_from_model_info,
)
from platform_core.services.equipment_research_task import aggregate_model_usage

REPO_ROOT = Path(__file__).resolve().parents[4]
if not (REPO_ROOT / "configs").exists():
    REPO_ROOT = Path("/app")


def _chat_info() -> ModelInfo:
    return ModelInfo(
        provider_id="deepseek",
        model_id="deepseek-chat",
        model_type="chat",
        display_name="DeepSeek Chat",
        api_key="sk-test",
        base_url="https://api.deepseek.com",
        provider_type="openai",
    )


def test_platform_model_spec_maps_to_real_runner_contract() -> None:
    runtime = runtime_from_model_info(_chat_info())
    assert runtime["mode"] == "real"
    assert runtime["provider"] == "platform"
    assert runtime["model"] == "deepseek-chat"
    assert runtime["api_key_env"] == "EQUIPMENT_DR_API_KEY"
    assert runtime["model_spec"] == "deepseek:deepseek-chat"
    assert runtime["execution"]["mode"] == "real"
    assert runtime["execution"]["provider"] == "platform"
    assert "api_key" not in runtime
    assert "api_key" not in runtime["execution"]
    assert runtime["env"]["EQUIPMENT_DR_PROVIDER"] == "platform"
    assert runtime["env"]["EQUIPMENT_DR_PROFILE"] == "platform-chat"
    assert runtime["env"]["EQUIPMENT_DR_API_KEY"] == "sk-test"
    assert "EQUIPMENT_DR_CODEX_API_KEY" not in runtime["env"]

    call = runner_call_from_runtime(runtime)
    assert call["mode"] == "real"
    assert call["provider_name"] == "platform"
    assert call["provider_model"] == "deepseek-chat"
    assert call["provider_base_url"] == "https://api.deepseek.com"
    assert call["provider_api_key_env"] == "EQUIPMENT_DR_API_KEY"
    assert call["provider_api_key"] == "sk-test"


def test_bind_live_execution_uses_platform_chat_completions(monkeypatch) -> None:
    info = _chat_info()
    monkeypatch.setattr(
        "platform_core.services.equipment_model_adapter.model_cache.get_model_info",
        lambda spec: info if spec == info.spec else None,
    )
    binding = bind_equipment_execution({"model_spec": "deepseek:deepseek-chat"})
    assert binding["mode"] == "real"
    assert binding["runner"]["mode"] == "real"
    assert binding["runner"]["provider_name"] == "platform"
    assert binding["runner"]["provider_api_key"] == "sk-test"
    assert binding["overlay"]["EQUIPMENT_DR_MODEL"] == "deepseek-chat"
    assert "api_key" not in binding["execution"]


def test_bind_fake_execution_skips_platform_model() -> None:
    binding = bind_equipment_execution({"execution": {"mode": "fake"}})
    assert binding["mode"] == "fake"
    assert binding["runner"]["mode"] == "fake"
    assert binding["overlay"] == {}
    assert binding["runner"]["provider_name"] is None
    assert binding["runner"]["provider_api_key"] is None


def test_missing_model_settings_points_to_frontend() -> None:
    try:
        resolve_equipment_model("")
    except RuntimeError as exc:
        assert "模型设置" in str(exc)
    else:
        raise AssertionError("expected missing model settings to fail")


def test_apply_equipment_model_env_restores_previous_values(monkeypatch) -> None:
    monkeypatch.delenv("EQUIPMENT_DR_API_KEY", raising=False)
    monkeypatch.setenv("EQUIPMENT_DR_MODEL", "previous")
    with apply_equipment_model_env({"EQUIPMENT_DR_MODEL": "deepseek-chat", "EQUIPMENT_DR_API_KEY": "sk-live"}):
        assert os.environ["EQUIPMENT_DR_MODEL"] == "deepseek-chat"
        assert os.environ["EQUIPMENT_DR_API_KEY"] == "sk-live"
    assert os.environ["EQUIPMENT_DR_MODEL"] == "previous"
    assert "EQUIPMENT_DR_API_KEY" not in os.environ


def test_platform_provider_profile_accepts_model_settings_runtime() -> None:
    from equipment_deep_research.model_profiles import get_profile
    from equipment_deep_research.providers.openai_compatible import OpenAICompatibleProvider
    from equipment_deep_research.providers.registry import ProviderRegistry
    from platform_core.services.equipment_model_adapter import create_equipment_provider

    registry = ProviderRegistry.load(REPO_ROOT / "configs/equipment_deep_research/providers.yaml")
    provider = registry.create(
        "platform",
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
        api_key="sk-test",
    )
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.model == "deepseek-chat"
    assert provider.capabilities().structured_output is True
    profile_id, profile = get_profile(
        "platform-chat",
        REPO_ROOT / "configs/equipment_deep_research/model-profiles.yaml",
    )
    assert profile_id == "platform-chat"
    assert profile["provider"] == "platform"
    runtime = runtime_from_model_info(_chat_info())
    bound = create_equipment_provider(runtime, isolation_key="query-gen-test")
    assert isinstance(bound, OpenAICompatibleProvider)
    assert bound.model == "deepseek-chat"


def test_research_model_events_are_aggregated_for_platform_observability() -> None:
    usage = aggregate_model_usage(
        [
            (
                "agent_model_call_completed",
                {
                    "event": {
                        "model_spec": "deepseek:deepseek-chat",
                        "elapsed_seconds": 1.25,
                        "usage": {"input_tokens": 120, "output_tokens": 30, "total_tokens": 150},
                    }
                },
            ),
            (
                "winning_model_call_completed",
                {
                    "model": "deepseek-chat",
                    "elapsed_seconds": 0.75,
                    "usage": {"prompt_tokens": 80, "completion_tokens": 20},
                },
            ),
        ],
        model_spec="deepseek:deepseek-chat",
    )

    assert usage["call_count"] == 2
    assert usage["usage_reported_call_count"] == 2
    assert usage["complete"] is True
    assert usage["total"] == {"input_tokens": 200, "output_tokens": 50, "total_tokens": 250}
    assert usage["elapsed_seconds"] == 2.0


def test_equipment_usage_observer_routes_all_business_surfaces(monkeypatch) -> None:
    """Query、正式研究与深研的并行调用必须写入对应统一总览入口。"""

    from platform_core.services.equipment_model_usage import (
        create_equipment_call_observer,
    )

    rows = []
    monkeypatch.setattr(
        "platform_core.services.equipment_model_usage.model_cache.get_all_specs",
        lambda _kind: [],
    )
    monkeypatch.setattr(
        "platform_core.services.equipment_model_usage.model_call_repository.record_model_call",
        rows.append,
    )

    identities = (
        ("query-gen-generation-1", "", "Query 生成", "generation-1"),
        ("deep-job-1", "deep_contextual_dialogue_s6_column_3", "深研对话", "job-1"),
        ("run-research-1", "winning_s6_parallel_card_01_module_overview", "研究任务", "research-1"),
        ("run-research-1", "report_generation_chapter_2_operations", "研究任务", "research-1"),
    )
    for index, (isolation_key, phase, expected_surface, expected_run_id) in enumerate(
        identities,
        start=1,
    ):
        observe = create_equipment_call_observer(
            provider_id="platform",
            model="chosen",
            base_url="https://example.test/v1",
            api_key="secret",
            isolation_key=isolation_key,
        )
        observe(
            {
                "id": f"call-{index}",
                "phase": phase,
                "run_id": expected_run_id if expected_surface == "研究任务" else "",
                "status": "completed",
                "duration_ms": 10,
                "usage": {
                    "prompt_tokens": 7,
                    "completion_tokens": 3,
                    "total_tokens": 10,
                },
            }
        )
        assert rows[-1]["surface"] == expected_surface
        assert rows[-1]["run_id"] == expected_run_id
        assert rows[-1]["phase"] == phase
        assert rows[-1]["total_tokens"] == 10


def test_selected_model_reaches_http_provider(monkeypatch):
    """使用本地 HTTP 服务验证所选模型与服务端凭据到达实际请求。"""
    import asyncio
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    from equipment_deep_research.providers.base import ModelMessage
    from platform_core.services.equipment_model_adapter import create_equipment_provider

    captured = {}
    # 测试服务运行在容器内，不应改写成宿主机地址。
    monkeypatch.setattr("platform_core.services.equipment_model_adapter.get_docker_safe_url", lambda url: url)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            captured["payload"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captured["authorization"] = self.headers["Authorization"]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(
                b'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":null}]}\n\n'
                b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                b"data: [DONE]\n\n"
            )

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        info = ModelInfo(
            provider_id="local-test",
            model_id="chosen-nondefault",
            model_type="chat",
            display_name="Chosen",
            api_key="server-test-secret",
            provider_type="openai",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
        )
        monkeypatch.setattr(
            "platform_core.services.equipment_model_adapter.model_cache.get_model_info",
            lambda spec: info if spec == info.spec else None,
        )
        runtime = resolve_equipment_model(info.spec)
        provider = create_equipment_provider(runtime, isolation_key="model-selection-http-test")

        async def consume():
            return [event async for event in provider.stream([ModelMessage(role="user", content="ping")], [], {})]

        events = asyncio.run(consume())
        assert captured["payload"]["model"] == "chosen-nondefault"
        assert captured["authorization"] == "Bearer server-test-secret"
        assert any(event.event_type == "final" for event in events)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
