"""Scripted, deterministic model backend for offline tests and demonstrations."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence

from equipment_deep_research.providers.base import ModelMessage, ProviderStreamEvent
from equipment_deep_research.tools.definitions import ToolDefinition


class ScriptedFakeProvider:
    def __init__(self, steps: Sequence[Sequence[ProviderStreamEvent]]) -> None:
        self._steps = [tuple(step) for step in steps]
        self.inputs: list[tuple[Sequence[ModelMessage], Sequence[ToolDefinition], Mapping[str, object]]] = []
        self.model = "fake"

    @property
    def remaining_steps(self) -> int:
        return len(self._steps)

    def snapshot(self) -> dict[str, str]:
        return {"type": "fake", "model": self.model, "base_url_host": ""}

    async def stream(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolDefinition],
        options: Mapping[str, object],
    ) -> AsyncIterator[ProviderStreamEvent]:
        self.inputs.append((tuple(messages), tuple(tools), dict(options)))
        if not self._steps:
            raise RuntimeError("ScriptedFakeProvider has no remaining step")
        for event in self._steps.pop(0):
            yield event
