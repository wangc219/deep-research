from __future__ import annotations

import json
from pathlib import Path

import yaml

from equipment_deep_research.agents.registry import AgentRegistry


ROOT = Path(__file__).resolve().parents[3]
CONFIG_ROOT = ROOT / "configs" / "equipment_deep_research"


def test_default_model_and_agent_policies() -> None:
    registry = AgentRegistry.load(CONFIG_ROOT / "agents.yaml")

    assert registry.default_model == "gpt-5.5"
    for agent in registry.enabled_baseline_agents():
        assert agent.tools
        assert agent.context_policy["hide_other_agent_raw_sessions"] is True
        assert agent.object_read_scopes
        assert agent.object_write_scopes == [
            "EvidenceCard",
            "BaselineFindingPacket",
            "WorkingCheckpoint",
        ]


def test_evidence_policy_uses_quality_threshold_not_domains() -> None:
    policy = yaml.safe_load((CONFIG_ROOT / "evidence.yaml").read_text(encoding="utf-8"))

    assert policy == {
        "acceptance": {
            "min_quality_score": 0.62,
            "min_direct_support": 0.55,
            "min_independent_sources_for_high_confidence": 2,
        },
        "weights": {
            "relevance": 0.30,
            "transparency": 0.15,
            "freshness": 0.15,
            "direct_support": 0.25,
            "extraction_quality": 0.15,
        },
        "deduplication": {
            "normalized_url": True,
            "content_similarity_threshold": 0.88,
        },
        "contradiction": {"preserve_counter_evidence": True},
        "network_safety": {
            "allowed_schemes": ["http", "https"],
            "deny_private_networks": True,
            "max_response_bytes": 5242880,
            "max_redirects": 5,
        },
    }
    assert "allowed" + "_domains" not in json.dumps(policy)


def test_provider_and_tool_configuration_are_structured() -> None:
    providers = yaml.safe_load((CONFIG_ROOT / "providers.yaml").read_text(encoding="utf-8"))
    tools = yaml.safe_load((CONFIG_ROOT / "tools.yaml").read_text(encoding="utf-8"))
    registry = AgentRegistry.load(CONFIG_ROOT / "agents.yaml")

    assert providers["default_provider"] == "responses"
    assert providers["providers"]["responses"] == {
        "type": "responses_http",
        "model": "gpt-5.5",
        "base_url_env": "EQUIPMENT_DR_BASE_URL",
        "api_key_env": "EQUIPMENT_DR_API_KEY",
        "timeout_seconds": 120,
    }
    configured_tools = set(tools["tools"])
    declared_tools = {tool for agent_id in registry.all_agent_ids() for tool in registry.get(agent_id).tools}
    assert declared_tools <= configured_tools
