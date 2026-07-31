from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from equipment_deep_research.agents.contracts import (
    DEFAULT_MODEL_PROFILE,
    LEGACY_SYSTEM_AGENT_IDS,
    OBJECT_SCOPE_CATALOG,
    TOOL_CATALOG,
    VISIBLE_SECTION_CATALOG,
    default_output_contract,
    validate_model_profile,
    validate_agent_extension,
    validate_named_contract,
)
from equipment_deep_research.domain.identifiers import validate_internal_identifier
from equipment_deep_research.harness.profiles import (
    HarnessCatalog,
    HarnessProfile,
    SkillDefinition,
)


@dataclass(frozen=True)
class AgentDef:
    agent_id: str
    display_name: str
    description: str
    capability_tags: list[str]
    tools: list[str]
    context_policy: dict[str, Any]
    enabled: bool = True
    input_contract: str | dict[str, Any] = "research_task"
    output_contract: str | dict[str, Any] = "baseline_finding_packet"
    object_read_scopes: list[str] = field(default_factory=list)
    object_write_scopes: list[str] = field(default_factory=list)
    model_profile: dict[str, Any] = field(
        default_factory=lambda: dict(DEFAULT_MODEL_PROFILE)
    )
    skills: list[dict[str, Any]] = field(default_factory=list)
    research_policy: dict[str, Any] = field(default_factory=dict)
    handoff_policy: dict[str, Any] = field(default_factory=dict)
    system_agent: bool = False
    harness_profile: str = ""
    skill_ids: list[str] = field(default_factory=list)
    shared_skills: list[dict[str, Any]] = field(default_factory=list)
    knowledge_pack_ids: list[str] = field(default_factory=list)
    knowledge_packs: list[dict[str, Any]] = field(default_factory=list)

    def validate(self) -> None:
        validate_internal_identifier(self.agent_id, field_name="agent_id")
        capabilities = [tag for tag in self.capability_tags if str(tag).strip()]
        if not capabilities or len(capabilities) != len(self.capability_tags):
            raise ValueError(f"agent {self.agent_id} requires non-empty capability_tags")

        unknown_tools = sorted(set(self.tools) - TOOL_CATALOG)
        if unknown_tools:
            raise ValueError(
                f"agent {self.agent_id} declares unknown tools: {unknown_tools}"
            )

        validate_named_contract(self.input_contract, field_name="input_contract")
        validate_named_contract(self.output_contract, field_name="output_contract")

        visible_sections = self.context_policy.get("visible_sections", [])
        if not isinstance(visible_sections, list):
            raise ValueError("context_policy visible_sections must be a list")
        unknown_sections = sorted(set(visible_sections) - VISIBLE_SECTION_CATALOG)
        if unknown_sections:
            raise ValueError(
                f"agent {self.agent_id} declares unknown visible sections: "
                f"{unknown_sections}"
            )

        _validate_scopes(
            self.agent_id,
            self.object_read_scopes,
            scope_kind="read",
        )
        _validate_scopes(
            self.agent_id,
            self.object_write_scopes,
            scope_kind="write",
        )
        validate_model_profile(self.model_profile)
        if self.skills and not all(
            isinstance(item, Mapping) and str(item.get("name", "")).strip()
            for item in self.skills
        ):
            raise ValueError(f"agent {self.agent_id} skills must be named objects")
        if self.shared_skills and not all(
            isinstance(item, Mapping) and str(item.get("name", "")).strip()
            for item in self.shared_skills
        ):
            raise ValueError(
                f"agent {self.agent_id} shared_skills must be named objects"
            )
        if self.knowledge_packs and not all(
            isinstance(item, Mapping)
            and str(item.get("knowledge_pack_id", "")).strip()
            for item in self.knowledge_packs
        ):
            raise ValueError(
                f"agent {self.agent_id} knowledge_packs must be named objects"
            )
        validate_agent_extension(self.research_policy, field_name="research_policy")
        validate_agent_extension(self.handoff_policy, field_name="handoff_policy")


class AgentRegistry:
    def __init__(
        self,
        agents: dict[str, AgentDef],
        default_model: str,
        *,
        harness_catalog: HarnessCatalog | None = None,
    ) -> None:
        self._agents = dict(agents)
        self.default_model = default_model
        self.harness_catalog = harness_catalog or HarnessCatalog.empty()

    @classmethod
    def load(
        cls,
        path: str | Path,
        harness_config_path: str | Path | None = None,
    ) -> "AgentRegistry":
        config_path = Path(path)
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, Mapping):
            raise ValueError("agent registry configuration must be an object")
        rows = data.get("agents", [])
        if not isinstance(rows, list):
            raise ValueError("agents must be a list")
        candidate_harness_path = (
            Path(harness_config_path)
            if harness_config_path is not None
            else config_path.parent / "harness.yaml"
        )
        harness_catalog = (
            HarnessCatalog.load(candidate_harness_path)
            if candidate_harness_path.is_file()
            else HarnessCatalog.empty()
        )
        agents: dict[str, AgentDef] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("each agent definition must be an object")
            agent_id = validate_internal_identifier(
                str(row["agent_id"]),
                field_name="agent_id",
            )
            if agent_id in agents:
                raise ValueError(f"duplicate agent_id: {agent_id}")
            input_contract = row.get("input_contract", "research_task")
            output_contract = row.get(
                "output_contract",
                default_output_contract(agent_id),
            )
            model_profile = row.get("model_profile", DEFAULT_MODEL_PROFILE)
            if not isinstance(model_profile, Mapping):
                raise ValueError("model_profile must be an object")
            harness_profile = str(row.get("harness_profile", "")).strip()
            if harness_profile and harness_profile not in harness_catalog.profiles:
                raise ValueError(
                    f"agent {agent_id} references unknown harness profile: {harness_profile}"
                )
            skill_ids = [str(item) for item in row.get("skill_ids", [])]
            unknown_skills = sorted(set(skill_ids) - set(harness_catalog.skills))
            if unknown_skills:
                raise ValueError(
                    f"agent {agent_id} references unknown skills: {unknown_skills}"
                )
            legacy_skills = row.get(
                "skills",
                [{"name": "general_research", "objective": agent_id}],
            )
            resolved_skills = (
                [harness_catalog.skills[item].to_agent_skill() for item in skill_ids]
                if skill_ids
                else [dict(item) for item in legacy_skills]
            )
            shared_skills = (
                []
                if agent_id == "reporter"
                else [
                    item.to_agent_skill()
                    for item in harness_catalog.shared_skills()
                ]
            )
            requested_pack_ids = [
                str(item) for item in row.get("knowledge_pack_ids", [])
            ]
            unknown_packs = sorted(
                set(requested_pack_ids) - set(harness_catalog.knowledge_packs)
            )
            if unknown_packs:
                raise ValueError(
                    f"agent {agent_id} references unknown knowledge packs: {unknown_packs}"
                )
            shared_pack_ids = (
                []
                if agent_id == "reporter"
                else [
                    item.knowledge_pack_id
                    for item in harness_catalog.shared_knowledge_packs()
                ]
            )
            knowledge_pack_ids = list(
                dict.fromkeys(
                    [
                        *shared_pack_ids,
                        *(
                            pack_id
                            for skill_id in skill_ids
                            for pack_id in harness_catalog.skills[skill_id].knowledge_pack_ids
                        ),
                        *requested_pack_ids,
                    ]
                )
            )
            knowledge_packs = [
                harness_catalog.knowledge_packs[item].to_runtime()
                for item in knowledge_pack_ids
            ]
            agent = AgentDef(
                agent_id=agent_id,
                display_name=str(row.get("display_name", row["agent_id"])),
                description=str(row.get("description", "")),
                capability_tags=list(row.get("capability_tags", [])),
                tools=list(row.get("tools", [])),
                context_policy=dict(row.get("context_policy", {})),
                enabled=bool(row.get("enabled", True)),
                input_contract=_copy_contract(input_contract),
                output_contract=_copy_contract(output_contract),
                object_read_scopes=list(row.get("object_read_scopes", [])),
                object_write_scopes=list(row.get("object_write_scopes", [])),
                model_profile=dict(model_profile),
                skills=resolved_skills,
                research_policy=dict(row.get("research_policy", {})),
                handoff_policy=dict(row.get("handoff_policy", {})),
                system_agent=bool(
                    row.get(
                        "system_agent",
                        row.get("is_system", agent_id in LEGACY_SYSTEM_AGENT_IDS),
                    )
                ),
                harness_profile=harness_profile,
                skill_ids=skill_ids,
                shared_skills=shared_skills,
                knowledge_pack_ids=knowledge_pack_ids,
                knowledge_packs=knowledge_packs,
            )
            agent.validate()
            agents[agent.agent_id] = agent
        return cls(
            agents=agents,
            default_model=str(data.get("default_model", "gpt-5.5")),
            harness_catalog=harness_catalog,
        )

    def get(self, agent_id: str) -> AgentDef:
        if agent_id not in self._agents:
            raise KeyError(f"unknown agent_id: {agent_id}")
        return self._agents[agent_id]

    def enabled_baseline_agents(self) -> list[AgentDef]:
        return [
            agent
            for agent in self._agents.values()
            if agent.enabled and not agent.system_agent
        ]

    def select_agents(self, requested_ids: list[str] | None = None) -> list[AgentDef]:
        if requested_ids:
            return [self.get(agent_id) for agent_id in requested_ids]
        return self.enabled_baseline_agents()

    def execution_order(self, selected: list[AgentDef]) -> list[AgentDef]:
        """Topologically order selected agents by declared handoff dependencies."""
        return [agent for wave in self.execution_waves(selected) for agent in wave]

    def execution_waves(self, selected: list[AgentDef]) -> list[list[AgentDef]]:
        """Build dependency-safe waves whose members may execute concurrently.

        ``handoff_policy.wait_for`` declares hard scheduling dependencies.  When
        it is absent we retain the original behavior and treat ``accept_from``
        as hard dependencies.  ``accept_from`` itself remains the broader list
        of upstream packets an agent is allowed to consume when they are
        already available.
        """
        selected_ids = {agent.agent_id for agent in selected}
        pending = {agent.agent_id: agent for agent in selected}
        waves: list[list[AgentDef]] = []
        while pending:
            ready = [
                agent
                for agent in pending.values()
                if not (
                    set(
                        agent.handoff_policy.get(
                            "wait_for",
                            agent.handoff_policy.get("accept_from", []),
                        )
                    )
                    & selected_ids
                    & set(pending)
                )
            ]
            if not ready:
                raise ValueError("selected agent handoff policies contain a dependency cycle")
            ready.sort(key=lambda item: self.all_agent_ids().index(item.agent_id))
            waves.append(ready)
            for agent in ready:
                pending.pop(agent.agent_id)
        return waves

    def agents_for_capability(self, tag: str, selected: list[AgentDef]) -> list[AgentDef]:
        return [agent for agent in selected if tag in agent.capability_tags]

    def resolve_capability(
        self,
        tag: str,
        selected: list[AgentDef] | None = None,
    ) -> AgentDef:
        candidates = self.agents_for_capability(
            tag,
            self.select_agents() if selected is None else selected,
        )
        if not candidates:
            raise KeyError(f"no selected agent provides capability: {tag}")
        return candidates[0]

    def all_agent_ids(self) -> list[str]:
        return sorted(self._agents)

    def get_harness_profile(self, profile_id: str) -> HarnessProfile:
        if profile_id not in self.harness_catalog.profiles:
            raise KeyError(f"unknown harness profile: {profile_id}")
        return self.harness_catalog.profiles[profile_id]

    def get_skill(self, skill_id: str) -> SkillDefinition:
        if skill_id not in self.harness_catalog.skills:
            raise KeyError(f"unknown skill: {skill_id}")
        return self.harness_catalog.skills[skill_id]

    def shared_skill_catalog(self) -> list[dict[str, Any]]:
        return [item.to_agent_skill() for item in self.harness_catalog.shared_skills()]

    def knowledge_pack_catalog(self) -> list[dict[str, Any]]:
        return [item.to_runtime() for item in self.harness_catalog.knowledge_packs.values()]


def _copy_contract(value: Any) -> str | dict[str, Any]:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return dict(value)
    raise ValueError("agent contracts must be a name or object")


def _validate_scopes(
    agent_id: str,
    scopes: list[str],
    *,
    scope_kind: str,
) -> None:
    unknown = sorted(set(scopes) - OBJECT_SCOPE_CATALOG)
    if unknown:
        raise ValueError(
            f"agent {agent_id} declares unknown object {scope_kind} scopes: {unknown}"
        )
