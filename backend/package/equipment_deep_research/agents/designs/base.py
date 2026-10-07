"""Agent-local design hooks shared by execution workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


class AgentDesign(Protocol):
    agent_id: str
    search_mode: str

    def analysis_specialization(self, *, optimized: bool) -> str: ...

    def role_focus(self, *, optimized: bool) -> str: ...

    def discovery_instruction(self) -> str: ...

    def output_schema_extensions(self) -> Mapping[str, Any]: ...

    def phase_options(self, phase: str) -> Mapping[str, Any]: ...

    def prompt_guidance(self) -> Mapping[str, Any]: ...

    def normalize_output(self, payload: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class AgentDesignSpec:
    agent_id: str
    focus: str
    optimized_focus: str = ""
    specialization: str = ""
    optimized_specialization: str = ""
    discovery: str = ""
    schema_extensions: Mapping[str, Any] = field(default_factory=dict)
    phase_overrides: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    search_mode: str = "standard"
    guidance: Mapping[str, Any] = field(default_factory=dict)

    def analysis_specialization(self, *, optimized: bool) -> str:
        if optimized and self.optimized_specialization:
            return self.optimized_specialization
        return self.specialization

    def role_focus(self, *, optimized: bool) -> str:
        if optimized and self.optimized_focus:
            return self.optimized_focus
        return self.focus

    def discovery_instruction(self) -> str:
        return self.discovery

    def output_schema_extensions(self) -> Mapping[str, Any]:
        return dict(self.schema_extensions)

    def phase_options(self, phase: str) -> Mapping[str, Any]:
        return dict(self.phase_overrides.get(phase, {}))

    def prompt_guidance(self) -> Mapping[str, Any]:
        return dict(self.guidance)

    def normalize_output(self, payload: dict[str, Any]) -> dict[str, Any]:
        return dict(payload)
