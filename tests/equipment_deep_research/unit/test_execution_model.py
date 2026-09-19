from __future__ import annotations

import json

from equipment_deep_research.execution_model import (
    configured_model,
    resolve_agent_model_profiles,
    resolve_model,
    resolve_swarm_model,
)


def test_environment_model_overrides_stale_task_model(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_MODEL", "gateway-model")
    assert (
        resolve_model(requested="stale-model", fallback="yaml-model")
        == "gateway-model"
    )


def test_provider_specific_model_overrides_global_model(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_MODEL", "global-model")
    monkeypatch.setenv("EQUIPMENT_DR_CLAUDE_MODEL", "claude-model")
    assert resolve_model(provider="claude", fallback="yaml-model") == "claude-model"


def test_explicit_deepseek_provider_uses_unified_profile_model_env(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_PROVIDER", "codex")
    monkeypatch.setenv("EQUIPMENT_DR_MODEL", "gpt-5.5")
    monkeypatch.setenv("EQUIPMENT_DR_DEEPSEEK_MODEL", "deepseek-v4-flash")
    monkeypatch.delenv("EQUIPMENT_DR_CODEX_DEEPSEEK_MODEL", raising=False)

    assert (
        configured_model(provider="codex_deepseek", fallback="yaml-model")
        == "deepseek-v4-flash"
    )


def test_explicit_queen_provider_uses_unified_profile_model_env(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_PROVIDER", "codex")
    monkeypatch.setenv("EQUIPMENT_DR_MODEL", "gpt-5.5")
    monkeypatch.setenv("EQUIPMENT_DR_QUEEN_MODEL", "qwen3.8-flash")
    monkeypatch.delenv("EQUIPMENT_DR_CODEX_QUEEN_MODEL", raising=False)

    assert (
        configured_model(provider="codex_queen", fallback="yaml-model")
        == "qwen3.8-flash"
    )


def test_explicit_unrelated_provider_does_not_inherit_global_model(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_PROVIDER", "codex")
    monkeypatch.setenv("EQUIPMENT_DR_MODEL", "gpt-5.5")

    assert configured_model(provider="custom_provider", fallback="custom-model") == "custom-model"


def test_per_agent_environment_model_overrides_global_model(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_MODEL", "gateway-model")
    monkeypatch.setenv(
        "EQUIPMENT_DR_AGENT_MODELS_JSON",
        json.dumps({"reporter": {"model": "reporter-model"}}),
    )
    profiles = resolve_agent_model_profiles(
        {
            "reporter": {"model": "stale-reporter-model"},
            "orchestrator": {"model": "stale-orchestrator-model"},
            "auditor": {},
        }
    )
    assert profiles["reporter"]["model"] == "reporter-model"
    # Persisted task models stay put; global env only fills empty slots.
    assert profiles["orchestrator"]["model"] == "stale-orchestrator-model"
    assert profiles["auditor"]["model"] == "gateway-model"


def test_global_provider_overrides_legacy_codex_agent_profiles(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_PROVIDER", "claude")
    profiles = resolve_agent_model_profiles(
        {"analyst": {"provider": "codex", "model": "legacy-model"}}
    )
    assert profiles["analyst"]["provider"] == "claude"


def test_dynamic_swarm_model_routes_by_archetype(monkeypatch) -> None:
    monkeypatch.setenv(
        "EQUIPMENT_DR_SWARM_AGENT_MODELS_JSON",
        json.dumps(
            {
                "weak_signal_scout": {"model": "scout-model"},
                "*": "swarm-default-model",
            }
        ),
    )
    payload = {
        "input": {
            "specialist_task": {"archetype": "weak_signal_scout"},
        }
    }
    assert (
        resolve_swarm_model(
            "winning_swarm_weak_signal_scout",
            payload,
            fallback="global-model",
        )
        == "scout-model"
    )
    assert (
        resolve_swarm_model(
            "winning_swarm_unknown",
            {"specialist_task": {"archetype": "unknown"}},
            fallback="global-model",
        )
        == "swarm-default-model"
    )


def test_task_fallback_model_wins_over_global_for_dynamic_swarm(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_MODEL", "gpt-from-env")
    monkeypatch.setenv(
        "EQUIPMENT_DR_SWARM_AGENT_MODELS_JSON",
        json.dumps({"weak_signal_scout": {"model": "stale-gpt-model"}, "*": "old-model"}),
    )
    assert (
        resolve_swarm_model(
            "winning_swarm_weak_signal_scout",
            {"specialist_task": {"archetype": "weak_signal_scout"}},
            fallback="deepseek-from-task",
        )
        == "stale-gpt-model"
    )
    monkeypatch.setenv("EQUIPMENT_DR_SWARM_AGENT_MODELS_JSON", "{}")
    assert (
        resolve_swarm_model(
            "winning_swarm_weak_signal_scout",
            {"specialist_task": {"archetype": "weak_signal_scout"}},
            fallback="deepseek-from-task",
        )
        == "deepseek-from-task"
    )
