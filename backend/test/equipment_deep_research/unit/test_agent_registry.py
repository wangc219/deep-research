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


def test_reporter_has_dedicated_military_delivery_contract() -> None:
    root = Path(__file__).parents[3]
    reporter = AgentRegistry.load(
        root / "configs/equipment_deep_research/agents.yaml"
    ).get("reporter")

    assert reporter.system_agent is True
    assert reporter.skill_ids == ["evidence_based_delivery"]
    assert reporter.knowledge_pack_ids == []
    assert reporter.tools == ["write_report"]
    assert reporter.output_contract["name"] == "research_report"
    assert "military_synthesis" in reporter.capability_tags
    assert reporter.research_policy["required_outputs"]
    assert reporter.research_policy["writing_priorities"]
    assert reporter.research_policy["evidence_policy"]
    assert reporter.research_policy["structure_policy"]
    assert reporter.research_policy["stopping_conditions"]


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


def test_default_registry_resolves_named_profiles_and_skills() -> None:
    root = Path(__file__).parents[3]
    registry = AgentRegistry.load(root / "configs/equipment_deep_research/agents.yaml")

    strategic = registry.get("international_situation")
    assert strategic.harness_profile == "strategic_research_v1"
    assert strategic.skill_ids == [
        "strategic_osint",
        "threat_forecasting",
        "force_posture_tracking",
    ]
    assert registry.get_harness_profile(strategic.harness_profile).budget["max_searches"] == 16
    assert registry.get_skill("threat_forecasting").required_artifacts == [
        "StrategicAssessment"
    ]


def test_registry_rejects_unknown_named_profile_or_skill(tmp_path: Path) -> None:
    harness_path = tmp_path / "harness.yaml"
    harness_path.write_text("profiles: []\nskills: []\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unknown harness profile"):
        AgentRegistry.load(
            _write_agents(tmp_path, [_agent("analyst", harness_profile="missing")]),
            harness_path,
        )
    with pytest.raises(ValueError, match="unknown skills"):
        AgentRegistry.load(
            _write_agents(tmp_path, [_agent("analyst", skill_ids=["missing"])]),
            harness_path,
        )
