"""统一模型配置覆盖旧环境变量，保留完整 Agent 编排与报告重试。"""

from pathlib import Path

import pytest

from equipment_deep_research.agents.workflows.reporter import _resolve_reporter_provider
from equipment_deep_research.orchestration.runner import DeepResearchRunner
from equipment_deep_research.providers import platform_access

ROOT = Path("/app") if Path("/app/configs").exists() else Path(__file__).resolve().parents[4]


def test_platform_agents_and_report_retries_ignore_legacy_environment(tmp_path, monkeypatch):
    """主控、子角色、报告和指定旧 profile 的重试均使用选定模型。"""
    monkeypatch.setenv("EQUIPMENT_DR_MODEL", "old-global-model")
    monkeypatch.setenv("EQUIPMENT_DR_PROVIDER", "codex")
    monkeypatch.setenv("EQUIPMENT_DR_FALLBACK_PROFILES", "deepseek")
    monkeypatch.setenv("EQUIPMENT_DR_AGENT_REPORTER_MODEL", "old-reporter-model")
    monkeypatch.setenv(
        "EQUIPMENT_DR_AGENT_MODELS", '{"reporter":{"provider":"codex","model":"old","base_url":"https://old.invalid"}}'
    )
    runner = DeepResearchRunner(
        project_root=ROOT,
        output_root=tmp_path,
        agent_config_path=ROOT / "configs/equipment_deep_research/agents.yaml",
        preset_config_path=ROOT / "configs/equipment_deep_research/presets.yaml",
        provider_config_path=ROOT / "configs/equipment_deep_research/providers.yaml",
    )
    host = runner._select_agent_provider(
        "real",
        "platform",
        run_id="routing-test",
        model="chosen-model",
        base_url="https://chosen.example/v1",
        api_key="current-key",
        agent_model_profiles={"reporter": {"provider": "codex", "model": "stale"}},
    )
    providers = [host.provider, *host.agent_providers.values()]
    providers.append(host._provider_for("winning_swarm_test", isolation_id="subagent", provider_profile="codex-gpt"))
    recovered, force = _resolve_reporter_provider(
        host, isolation_id="retry", force_fallback=True, provider_profile="codex-gpt"
    )
    providers.append(recovered)
    assert not force
    assert len(host.agent_definitions) > 5
    for provider in providers:
        assert provider.provider_id == "platform"
        assert provider.model == "chosen-model"
        assert provider.base_url == "https://chosen.example/v1/chat/completions"
        assert provider._api_key == "current-key"


def test_legacy_execution_uses_managed_default_and_fake_stays_offline(monkeypatch):
    """历史真实任务由宿主接管，fake 任务保持离线。"""
    calls = []

    def resolver(spec):
        calls.append(spec)
        return {"model_spec": spec or "platform:default", "execution": {"model": "chosen"}}

    monkeypatch.setattr(platform_access, "_resolver", resolver)
    runtime = platform_access.resolve_platform_execution({"mode": "real", "provider": "codex", "model": "old"})
    assert runtime["model_spec"] == "platform:default"
    assert platform_access.resolve_platform_execution({"mode": "fake"}) is None
    assert calls == [""]
    assert platform_access.resolve_platform_execution({"model_spec": "chosen:other"})["model_spec"] == "chosen:other"


def test_standalone_execution_remains_supported(monkeypatch):
    """没有平台宿主时保持原独立项目入口。"""
    monkeypatch.setattr(platform_access, "_resolver", None)
    assert platform_access.resolve_platform_execution({"mode": "real", "provider": "codex"}) is None
    with pytest.raises(ValueError, match="未初始化"):
        platform_access.resolve_platform_execution({"model_spec": "platform:chosen"})


def test_managed_catalog_exposes_specs_without_secrets(monkeypatch):
    """深研模型菜单复用平台目录，凭据仅作为可用性布尔值投影。"""
    from equipment_deep_research.model_profiles import public_profiles
    from platform_core.models.providers.cache import ModelInfo
    from platform_core.services.equipment_model_adapter import equipment_model_profiles

    info = ModelInfo(
        provider_id="configured",
        model_id="chosen",
        model_type="chat",
        display_name="Configured model",
        api_key="secret-never-in-catalog",
        base_url="https://configured.example/v1",
        provider_type="openai",
    )
    monkeypatch.setattr("platform_core.services.equipment_model_adapter.model_cache.get_all_specs", lambda _: [info])
    monkeypatch.setattr(platform_access, "_catalog", equipment_model_profiles)
    catalog = public_profiles()
    assert catalog["managed"] is True
    assert catalog["profiles"][0]["id"] == "configured:chosen"
    assert catalog["profiles"][0]["credential_configured"] is True
    assert "secret-never-in-catalog" not in str(catalog)
    assert "base_url" not in catalog["profiles"][0]
