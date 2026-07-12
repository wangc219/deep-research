from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
import yaml

from equipment_deep_research.agents.registry import AgentDef, AgentRegistry


def _agent(agent_id: str, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "agent_id": agent_id,
        "display_name": agent_id,
        "description": "test agent",
        "capability_tags": ["threat"],
        "tools": ["search_sources"],
        "context_policy": {"visible_sections": ["task", "evidence_policy"]},
        "input_contract": "research_task",
        "output_contract": "baseline_finding_packet",
        "object_read_scopes": ["ResearchProblem", "EvidenceCard"],
        "object_write_scopes": ["EvidenceCard", "BaselineFindingPacket"],
    }
    row.update(overrides)
    return row


def _write_agents(tmp_path: Path, agents: list[dict[str, Any]]) -> Path:
    path = tmp_path / "agents.yaml"
    path.write_text(yaml.safe_dump({"agents": agents}), encoding="utf-8")
    return path


def test_registry_rejects_duplicate_ids_and_unknown_contract(tmp_path: Path) -> None:
    duplicate_path = _write_agents(tmp_path, [_agent("same"), _agent("same")])
    with pytest.raises(ValueError, match="duplicate agent_id"):
        AgentRegistry.load(duplicate_path)

    unknown_contract_path = _write_agents(
        tmp_path,
        [_agent("analyst", output_contract="missing_contract")],
    )
    with pytest.raises(ValueError, match="unknown output_contract"):
        AgentRegistry.load(unknown_contract_path)

    unknown_inline_contract_path = _write_agents(
        tmp_path,
        [_agent("analyst", input_contract={"name": "missing_contract"})],
    )
    with pytest.raises(ValueError, match="unknown input_contract"):
        AgentRegistry.load(unknown_inline_contract_path)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"capability_tags": []}, "capability_tags"),
        ({"tools": ["not_a_tool"]}, "unknown tools"),
        (
            {"context_policy": {"visible_sections": ["raw_other_agent_session"]}},
            "visible sections",
        ),
        ({"object_read_scopes": ["SecretObject"]}, "read scopes"),
        ({"object_write_scopes": ["SecretObject"]}, "write scopes"),
    ],
)
def test_registry_rejects_invalid_agent_declarations(
    tmp_path: Path,
    override: dict[str, Any],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        AgentRegistry.load(_write_agents(tmp_path, [_agent("analyst", **override)]))


def test_custom_agent_can_cover_multiple_default_capabilities(tmp_path: Path) -> None:
    registry = AgentRegistry.load(
        _write_agents(
            tmp_path,
            [
                _agent(
                    "integrated_research",
                    capability_tags=[
                        "situation",
                        "threat",
                        "scenario",
                        "equipment",
                        "operation",
                    ],
                )
            ],
        )
    )

    selected = registry.select_agents(["integrated_research"])

    assert len(selected) == 1
    assert {"situation", "threat", "scenario", "equipment", "operation"} <= set(
        selected[0].capability_tags
    )
    assert registry.resolve_capability("scenario", selected).agent_id == "integrated_research"


def test_default_selection_excludes_declared_and_legacy_system_agents(
    tmp_path: Path,
) -> None:
    registry = AgentRegistry.load(
        _write_agents(
            tmp_path,
            [
                _agent("baseline"),
                _agent("custom_system", system_agent=True),
                _agent("auditor", capability_tags=["audit"]),
            ],
        )
    )

    assert [agent.agent_id for agent in registry.select_agents()] == ["baseline"]
    assert registry.select_agents(["custom_system"])[0].system_agent is True


def test_model_profile_defaults_to_responses_gpt_5_5_and_rejects_secrets(
    tmp_path: Path,
) -> None:
    registry = AgentRegistry.load(_write_agents(tmp_path, [_agent("analyst")]))

    assert registry.get("analyst").model_profile == {
        "provider": "responses",
        "model": "gpt-5.5",
    }
    assert "api_key" not in repr(asdict(registry.get("analyst"))).lower()

    secret_path = _write_agents(
        tmp_path,
        [
            _agent(
                "unsafe",
                model_profile={
                    "provider": "responses",
                    "model": "gpt-5.5",
                    "headers": {"Authorization": "Bearer secret"},
                },
            )
        ],
    )
    with pytest.raises(ValueError, match="model_profile.*headers"):
        AgentRegistry.load(secret_path)


def test_agent_validate_supports_existing_direct_construction() -> None:
    agent = AgentDef(
        agent_id="direct_agent",
        display_name="Direct",
        description="constructed by an existing caller",
        capability_tags=["threat"],
        tools=[],
        context_policy={},
    )

    agent.validate()

    assert agent.model_profile == {"provider": "responses", "model": "gpt-5.5"}
