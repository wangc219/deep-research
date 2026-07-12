from __future__ import annotations

import asyncio

import pytest

from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.domain.messages import TaskEnvelope
from equipment_deep_research.domain.proposals import DomainWriteProposal
from equipment_deep_research.tools.definitions import ToolCall, ToolDefinition, ToolExecutionContext, ToolResult
from equipment_deep_research.tools.registry import ToolRegistry


def _agent() -> AgentDef:
    return AgentDef(
        agent_id="limited_researcher",
        display_name="Limited",
        description="test",
        capability_tags=["threat"],
        tools=["fetch_page"],
        context_policy={},
        object_read_scopes=["ResearchProblem"],
        object_write_scopes=["BaselineFindingPacket"],
    )


def _task(**changes: object) -> TaskEnvelope:
    payload: dict[str, object] = {
        "task_id": "task-1", "run_id": "run-1", "round_index": 1,
        "parent_task_id": None, "target_agent_id": "limited_researcher",
        "target_capability_tags": [], "objective": "research", "research_questions": [],
        "context_refs": [], "evidence_refs": [], "allowed_tools": ["fetch_page"],
        "object_read_scopes": ["ResearchProblem"],
        "object_write_scopes": ["BaselineFindingPacket"], "budget": {},
        "return_contract": "baseline_finding_packet", "return_node": "baseline",
    }
    payload.update(changes)
    return TaskEnvelope(**payload)  # type: ignore[arg-type]


async def _writes_evidence(call: ToolCall, context: ToolExecutionContext) -> ToolResult:
    del context
    return ToolResult(
        call.call_id,
        "created",
        domain_proposals=(DomainWriteProposal("p-1", "EvidenceCard", "upsert", {}, "key-1"),),
    )


def _registry() -> ToolRegistry:
    return ToolRegistry([
        ToolDefinition("fetch_page", "fetch", {"type": "object"}, _writes_evidence),
        ToolDefinition("search_sources", "search", {"type": "object"}, _writes_evidence),
    ])


def test_task_cannot_expand_agent_tool_permissions() -> None:
    registry = _registry()
    with pytest.raises(PermissionError, match="agent allowlist"):
        registry.active_for(_agent(), _task(allowed_tools=["fetch_page", "search_sources"]))


def test_tool_result_with_forbidden_object_scope_is_rejected() -> None:
    registry = _registry()
    task = _task()
    context = registry.execution_context(_agent(), task)
    with pytest.raises(PermissionError, match="EvidenceCard"):
        asyncio.run(registry.execute(ToolCall("c-1", "fetch_page", {}), context))


def test_execution_requires_active_intersection() -> None:
    registry = _registry()
    task = _task()
    context = registry.execution_context(_agent(), task)
    with pytest.raises(PermissionError, match="active tool allowlist"):
        asyncio.run(registry.execute(ToolCall("c-1", "search_sources", {}), context))
