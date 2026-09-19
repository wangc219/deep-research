"""Mutable turn state shared by the planner, runner and domain tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from equipment_deep_research.deep_runtime.planner import InboundTurn


@dataclass
class TurnState:
    host: Any
    payload: dict[str, Any]
    inbound: InboundTurn
    plan: list[str]
    results: dict[str, Any] = field(default_factory=dict)
    completed_tools: list[str] = field(default_factory=list)
    interrupted: bool = False
    conductor: dict[str, Any] = field(default_factory=dict)
    active_skills: list[dict[str, Any]] = field(default_factory=list)
    skill_prompt: str = ""
    capabilities: dict[str, Any] = field(default_factory=dict)
    # The loop receives a per-turn capability snapshot.  Keeping this optional
    # preserves compatibility with callers/tests that construct TurnState
    # directly; the runner lazily builds a registry when it is absent.
    tool_registry: Any | None = None
    observations: list[dict[str, Any]] = field(default_factory=list)
    policy_trace: list[dict[str, Any]] = field(default_factory=list)
    current_action: str = ""
    turn_count: int = 0
    tool_call_count: int = 0
    max_turns: int = 4
    max_tool_calls: int = 4
    status: str = "running"
    stop_reason: str = ""
    # Optional nanobot-style provider/subagent boundaries.  They are kept out
    # of the serialized payload and only exist for the current turn.
    provider_runtime: Any | None = None
    subagent_runner: Any | None = None
    subagent_results: list[dict[str, Any]] = field(default_factory=list)
    # File-backed state is an in-process dependency.  It must never be placed
    # back into ``payload`` because that mapping is used to build model input.
    workspace: Any | None = None
