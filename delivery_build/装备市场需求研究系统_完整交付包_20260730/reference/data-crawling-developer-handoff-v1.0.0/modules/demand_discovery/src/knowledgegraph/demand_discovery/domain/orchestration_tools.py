"""Orchestration tools that let an orchestrator spawn worker harnesses."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from knowledgegraph.demand_discovery.harness.budget import RunBudget
from knowledgegraph.demand_discovery.harness.context_pack import ContextPack
from knowledgegraph.demand_discovery.harness.scheduler import (
    DiscoveryScheduler,
    WorkerSpec,
)
from knowledgegraph.demand_discovery.harness.tools import (
    ToolDefinition,
    ToolExecutionContext,
)
from knowledgegraph.demand_discovery.harness.types import ToolCall, ToolResult
from knowledgegraph.demand_discovery.workers.agent_defs import (
    AgentDef,
    discover_agents,
)


def spawn_worker_tool(
    *,
    scheduler: DiscoveryScheduler,
    agent_dir: str | Path,
    available_tool_names: set[str],
) -> ToolDefinition:
    """Build the orchestrator-facing ``spawn_worker`` tool.

    Worker domain writes are committed by worker harness save points. This tool
    returns only report digests and never emits domain proposals itself.
    """

    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        agents = discover_agents(agent_dir)
        try:
            mode, items = _parse_request(call.arguments)
            _validate_items(items, agents)
        except ValueError as exc:
            return ToolResult(call.id, call.name, str(exc), {}, is_error=True)

        missing_tools_by_agent: dict[str, list[str]] = {}
        reports = []
        if mode in {"single", "parallel"}:
            specs = [
                _spec_from_item(
                    item,
                    agents[str(item["agent"])],
                    available_tool_names,
                    missing_tools_by_agent,
                )
                for item in items
            ]
            reports = await scheduler.run_workers(
                specs,
                parent_event_id=call.id,
                parent_cancel_token=ctx.cancel_token,
            )
        else:
            previous = ""
            for item in items:
                item = dict(item)
                item["task"] = str(item["task"]).replace("{previous}", previous)
                spec = _spec_from_item(
                    item,
                    agents[str(item["agent"])],
                    available_tool_names,
                    missing_tools_by_agent,
                )
                step_reports = await scheduler.run_workers(
                    [spec],
                    parent_event_id=call.id,
                    parent_cancel_token=ctx.cancel_token,
                )
                reports.extend(step_reports)
                if not step_reports:
                    break
                previous = step_reports[-1].to_digest()
                if step_reports[-1].status in {"failed", "cancelled"}:
                    break

        content = "\n\n".join(report.to_digest() for report in reports)
        return ToolResult(
            call.id,
            call.name,
            content[:2000].rstrip() + ("...<truncated>" if len(content) > 2000 else ""),
            {
                "mode": mode,
                "reports": [report.to_dict() for report in reports],
                "missing_tools_by_agent": missing_tools_by_agent,
            },
            domain_proposals=[],
            trace_proposals=[],
            is_error=any(report.status == "failed" for report in reports),
        )

    return ToolDefinition(
        name="spawn_worker",
        description="Spawn one or more demand-discovery worker agents.",
        parameters_schema={
            "type": "object",
            "properties": {
                "agent": {"type": "string"},
                "task": {"type": "string"},
                "tasks": {"type": "array"},
                "chain": {"type": "array"},
            },
            "additionalProperties": False,
        },
        execute=execute,
        execution_mode="sequential",
        timeout_ms=600_000,
    )


def _parse_request(args: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    has_single = "agent" in args or "task" in args
    has_parallel = "tasks" in args
    has_chain = "chain" in args
    if sum([has_single, has_parallel, has_chain]) != 1:
        raise ValueError("spawn_worker accepts exactly one of single, tasks, or chain")
    if has_single:
        if "agent" not in args or "task" not in args:
            raise ValueError("single spawn requires agent and task")
        return "single", [{"agent": args["agent"], "task": args["task"]}]
    if has_parallel:
        tasks = list(args.get("tasks") or [])
        if len(tasks) > 8:
            raise ValueError("spawn_worker parallel mode accepts at most 8 tasks")
        return "parallel", [dict(item) for item in tasks]
    chain = list(args.get("chain") or [])
    if len(chain) > 8:
        raise ValueError("spawn_worker chain mode accepts at most 8 steps")
    return "chain", [dict(item) for item in chain]


def _validate_items(
    items: list[dict[str, Any]],
    agents: dict[str, AgentDef],
) -> None:
    if not items:
        raise ValueError("spawn_worker requires at least one task")
    for item in items:
        agent_name = str(item.get("agent", ""))
        task = str(item.get("task", ""))
        if agent_name not in agents:
            raise ValueError(f"unknown worker agent: {agent_name}")
        if not task.strip():
            raise ValueError("worker task must not be empty")


def _spec_from_item(
    item: dict[str, Any],
    agent: AgentDef,
    available_tool_names: set[str],
    missing_tools_by_agent: dict[str, list[str]],
) -> WorkerSpec:
    active_tools = [name for name in agent.tools if name in available_tool_names]
    missing = [name for name in agent.tools if name not in available_tool_names]
    if missing:
        missing_tools_by_agent[agent.name] = missing
    task = str(item["task"])
    return WorkerSpec(
        role=agent.name,
        task_brief=task,
        tools=active_tools,
        budget=_clone_budget(agent.budget),
        context_pack=ContextPack(
            agent_role=agent.name,
            task_brief=task,
            sections={"agent_description": agent.description},
            token_budget=1200,
        ),
        system_prompt=agent.system_prompt,
    )


def _clone_budget(budget: RunBudget) -> RunBudget:
    return RunBudget(
        max_tokens=budget.max_tokens,
        max_tool_calls=budget.max_tool_calls,
        max_wall_clock_ms=budget.max_wall_clock_ms,
    )
