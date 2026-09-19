from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from equipment_deep_research.contracts.catalog import OBJECT_SCOPE_CATALOG, TOOL_CATALOG
from equipment_deep_research.domain.identifiers import validate_internal_identifier


PROFILE_BUDGET_KEYS = frozenset(
    {
        "max_turns",
        "max_searches",
        "max_tool_calls",
        "max_tokens",
        "max_seconds",
        "max_dynamic_instances",
        "min_mission_graph_instances",
        "target_mission_graph_instances",
        "max_concurrency",
        "max_waves",
        "minimum_expected_gain",
        # Deep-divergence runs use stage-specific caps which are consumed by
        # the deep-research coordinator rather than the generic task budget
        # adapter.  Keep them in the profile schema so the catalog can load
        # the profile, while ``task_budget`` below continues to expose only
        # harness-native execution limits.
        "max_s3_slots",
        "max_s4_slots",
        "max_candidates",
    }
)


@dataclass(frozen=True)
class HarnessProfile:
    profile_id: str
    context_policy: dict[str, Any]
    budget: dict[str, int | float]
    evidence_policy: dict[str, Any]
    checkpoint_policy: dict[str, Any]
    stop_conditions: list[str]
    recovery_policy: dict[str, Any]
    phase_tools: dict[str, list[str]] = field(default_factory=dict)

    def validate(self) -> None:
        validate_internal_identifier(self.profile_id, field_name="profile_id")
        unknown_budget = sorted(set(self.budget) - PROFILE_BUDGET_KEYS)
        if unknown_budget:
            raise ValueError(
                f"profile {self.profile_id} declares unknown budget keys: {unknown_budget}"
            )
        for key, value in self.budget.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ValueError(f"profile {self.profile_id} budget {key} must be non-negative")
        bounded_limits = {
            "max_dynamic_instances": 21,
            "min_mission_graph_instances": 21,
            "target_mission_graph_instances": 21,
            # Dynamic winning-swarm v2 uses eight parallel creative seats;
            # legacy profiles remain at their lower configured values.
            "max_concurrency": 8,
            "max_waves": 3,
            "minimum_expected_gain": 1.0,
        }
        for key, maximum in bounded_limits.items():
            if key in self.budget and float(self.budget[key]) > maximum:
                raise ValueError(
                    f"profile {self.profile_id} budget {key} may not exceed {maximum}"
                )
        if not self.stop_conditions:
            raise ValueError(f"profile {self.profile_id} requires stop_conditions")
        for phase_id, tools in self.phase_tools.items():
            validate_internal_identifier(str(phase_id), field_name="phase_id")
            unknown_tools = sorted(set(tools) - TOOL_CATALOG)
            if unknown_tools:
                raise ValueError(
                    f"profile {self.profile_id} phase {phase_id} declares unknown tools: {unknown_tools}"
                )

    def task_budget(self) -> dict[str, int]:
        return {
            key: int(value)
            for key, value in self.budget.items()
            if key in {"max_turns", "max_tool_calls", "max_tokens", "max_seconds"}
        }


@dataclass(frozen=True)
class SkillDefinition:
    skill_id: str
    triggers: list[str]
    allowed_tools: list[str]
    steps: list[str]
    required_artifacts: list[str]
    quality_gates: list[str]
    stop_conditions: list[str]
    object_write_scopes: list[str] = field(default_factory=list)
    budget_override: dict[str, int | float] = field(default_factory=dict)
    shared: bool = False
    knowledge_pack_ids: list[str] = field(default_factory=list)

    def validate(self) -> None:
        validate_internal_identifier(self.skill_id, field_name="skill_id")
        unknown_tools = sorted(set(self.allowed_tools) - TOOL_CATALOG)
        if unknown_tools:
            raise ValueError(f"skill {self.skill_id} declares unknown tools: {unknown_tools}")
        unknown_scopes = sorted(set(self.object_write_scopes) - OBJECT_SCOPE_CATALOG)
        if unknown_scopes:
            raise ValueError(
                f"skill {self.skill_id} declares unknown object scopes: {unknown_scopes}"
            )
        unknown_budget = sorted(set(self.budget_override) - PROFILE_BUDGET_KEYS)
        if unknown_budget:
            raise ValueError(
                f"skill {self.skill_id} declares unknown budget keys: {unknown_budget}"
            )
        if not self.steps or not self.required_artifacts or not self.quality_gates:
            raise ValueError(
                f"skill {self.skill_id} requires steps, required_artifacts and quality_gates"
            )

    def to_agent_skill(self) -> dict[str, Any]:
        return {
            "name": self.skill_id,
            "triggers": list(self.triggers),
            "allowed_tools": list(self.allowed_tools),
            "steps": list(self.steps),
            "required_artifacts": list(self.required_artifacts),
            "quality_gates": list(self.quality_gates),
            "stop_conditions": list(self.stop_conditions),
            "object_write_scopes": list(self.object_write_scopes),
            "budget_override": dict(self.budget_override),
            "shared": self.shared,
            "knowledge_pack_ids": list(self.knowledge_pack_ids),
        }


@dataclass(frozen=True)
class KnowledgePackDefinition:
    knowledge_pack_id: str
    description: str
    source_types: list[str]
    retrieval_policy: dict[str, Any]
    quality_gates: list[str]
    shared: bool = False

    def validate(self) -> None:
        validate_internal_identifier(
            self.knowledge_pack_id,
            field_name="knowledge_pack_id",
        )
        if not self.description.strip():
            raise ValueError(
                f"knowledge pack {self.knowledge_pack_id} requires a description"
            )
        if not self.source_types or not self.quality_gates:
            raise ValueError(
                f"knowledge pack {self.knowledge_pack_id} requires source_types and quality_gates"
            )

    def to_runtime(self) -> dict[str, Any]:
        return {
            "knowledge_pack_id": self.knowledge_pack_id,
            "description": self.description,
            "source_types": list(self.source_types),
            "retrieval_policy": dict(self.retrieval_policy),
            "quality_gates": list(self.quality_gates),
            "shared": self.shared,
        }


@dataclass(frozen=True)
class HarnessCatalog:
    profiles: dict[str, HarnessProfile]
    skills: dict[str, SkillDefinition]
    knowledge_packs: dict[str, KnowledgePackDefinition] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> "HarnessCatalog":
        return cls({}, {}, {})

    @classmethod
    def load(cls, path: str | Path) -> "HarnessCatalog":
        source = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(source, Mapping):
            raise ValueError("harness configuration must be an object")
        profiles: dict[str, HarnessProfile] = {}
        for raw in source.get("profiles", []):
            if not isinstance(raw, Mapping):
                raise ValueError("each harness profile must be an object")
            profile = HarnessProfile(
                profile_id=str(raw["profile_id"]),
                context_policy=dict(raw.get("context_policy", {})),
                budget=dict(raw.get("budget", {})),
                evidence_policy=dict(raw.get("evidence_policy", {})),
                checkpoint_policy=dict(raw.get("checkpoint_policy", {})),
                stop_conditions=[str(item) for item in raw.get("stop_conditions", [])],
                recovery_policy=dict(raw.get("recovery_policy", {})),
                phase_tools={
                    str(key): [str(item) for item in value]
                    for key, value in dict(raw.get("phase_tools", {})).items()
                },
            )
            if profile.profile_id in profiles:
                raise ValueError(f"duplicate harness profile: {profile.profile_id}")
            profile.validate()
            profiles[profile.profile_id] = profile
        knowledge_packs: dict[str, KnowledgePackDefinition] = {}
        for raw in source.get("knowledge_packs", []):
            if not isinstance(raw, Mapping):
                raise ValueError("each knowledge pack definition must be an object")
            knowledge_pack = KnowledgePackDefinition(
                knowledge_pack_id=str(raw["knowledge_pack_id"]),
                description=str(raw.get("description", "")),
                source_types=[str(item) for item in raw.get("source_types", [])],
                retrieval_policy=dict(raw.get("retrieval_policy", {})),
                quality_gates=[str(item) for item in raw.get("quality_gates", [])],
                shared=bool(raw.get("shared", False)),
            )
            if knowledge_pack.knowledge_pack_id in knowledge_packs:
                raise ValueError(
                    f"duplicate knowledge pack: {knowledge_pack.knowledge_pack_id}"
                )
            knowledge_pack.validate()
            knowledge_packs[knowledge_pack.knowledge_pack_id] = knowledge_pack
        skills: dict[str, SkillDefinition] = {}
        for raw in source.get("skills", []):
            if not isinstance(raw, Mapping):
                raise ValueError("each skill definition must be an object")
            skill = SkillDefinition(
                skill_id=str(raw["skill_id"]),
                triggers=[str(item) for item in raw.get("triggers", [])],
                allowed_tools=[str(item) for item in raw.get("allowed_tools", [])],
                steps=[str(item) for item in raw.get("steps", [])],
                required_artifacts=[str(item) for item in raw.get("required_artifacts", [])],
                quality_gates=[str(item) for item in raw.get("quality_gates", [])],
                stop_conditions=[str(item) for item in raw.get("stop_conditions", [])],
                object_write_scopes=[str(item) for item in raw.get("object_write_scopes", [])],
                budget_override=dict(raw.get("budget_override", {})),
                shared=bool(raw.get("shared", False)),
                knowledge_pack_ids=[
                    str(item) for item in raw.get("knowledge_pack_ids", [])
                ],
            )
            if skill.skill_id in skills:
                raise ValueError(f"duplicate skill definition: {skill.skill_id}")
            skill.validate()
            unknown_packs = sorted(
                set(skill.knowledge_pack_ids) - set(knowledge_packs)
            )
            if unknown_packs:
                raise ValueError(
                    f"skill {skill.skill_id} references unknown knowledge packs: {unknown_packs}"
                )
            skills[skill.skill_id] = skill
        return cls(profiles, skills, knowledge_packs)

    def shared_skills(self) -> list[SkillDefinition]:
        return [skill for skill in self.skills.values() if skill.shared]

    def shared_knowledge_packs(self) -> list[KnowledgePackDefinition]:
        return [pack for pack in self.knowledge_packs.values() if pack.shared]
