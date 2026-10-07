"""Runtime registry that enforces tool and object-scope boundaries."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from equipment_deep_research.contracts.agents import AgentSpec
from equipment_deep_research.domain.messages import TaskEnvelope
from equipment_deep_research.tools.definitions import ToolCall, ToolDefinition, ToolExecutionContext, ToolResult
from equipment_deep_research.tools.permissions import ToolAuthorizationPolicy


class ToolRegistry:
    """A configured tool set with load-time and call-time authorization.

    A task may narrow an agent's permissions, but it can never grant a tool or
    write scope the selected agent did not declare.  The same intersection is
    checked once more after a tool returns proposals.
    """

    def __init__(
        self,
        tools: Sequence[ToolDefinition] | Mapping[str, ToolDefinition],
        *,
        authorization_policy: ToolAuthorizationPolicy | None = None,
    ) -> None:
        values = tuple(tools.values()) if isinstance(tools, Mapping) else tuple(tools)
        if not all(isinstance(item, ToolDefinition) for item in values):
            raise TypeError("tools must contain ToolDefinition values")
        names = [item.name for item in values]
        if len(names) != len(set(names)):
            raise ValueError("tool names must be unique")
        self._tools = {item.name: item for item in values}
        self.policy = authorization_policy or ToolAuthorizationPolicy.default()

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def active_for(self, agent: AgentSpec, task: TaskEnvelope) -> tuple[ToolDefinition, ...]:
        self._validate_task_identity(agent, task)
        requested = set(task.allowed_tools)
        undeclared = sorted(requested - set(agent.tools))
        if undeclared:
            raise PermissionError(
                f"task requests tools outside agent allowlist: {undeclared}"
            )
        unknown = sorted(requested - set(self._tools))
        if unknown:
            raise ValueError(f"task requests unknown tools: {unknown}")
        return tuple(self._tools[name] for name in task.allowed_tools)

    def execution_context(self, agent: AgentSpec, task: TaskEnvelope) -> ToolExecutionContext:
        active = self.active_for(agent, task)
        agent_read = set(agent.object_read_scopes)
        agent_write = set(agent.object_write_scopes)
        task_read = set(task.object_read_scopes)
        task_write = set(task.object_write_scopes)
        if not task_read <= agent_read:
            raise PermissionError("task requests object read scopes outside agent allowlist")
        if not task_write <= agent_write:
            raise PermissionError("task requests object write scopes outside agent allowlist")
        return ToolExecutionContext(
            run_id=task.run_id,
            agent_id=agent.agent_id,
            permissions={
                "active_tool_names": [definition.name for definition in active],
                "object_read_scopes": sorted(task_read),
                "object_write_scopes": sorted(task_write),
            },
        )

    async def execute(self, call: ToolCall, context: ToolExecutionContext) -> ToolResult:
        permissions = context.permissions
        active = tuple(str(item) for item in permissions.get("active_tool_names", ()))
        definition = self._tools.get(call.name)
        if definition is None:
            raise PermissionError(f"unknown tool: {call.name}")
        self.policy.authorize(
            call.name,
            active_tool_names=active,
            object_read_scopes=permissions.get("object_read_scopes", ()),
            object_write_scopes=permissions.get("object_write_scopes", ()),
        )
        result = await definition.handler(call, context)
        if not isinstance(result, ToolResult):
            raise TypeError("tool handler must return ToolResult")
        return self.policy.authorize_result(
            call.name,
            result,
            active_tool_names=active,
            object_read_scopes=permissions.get("object_read_scopes", ()),
            object_write_scopes=permissions.get("object_write_scopes", ()),
            agent_id=context.agent_id,
            call_id=call.call_id,
        )

    @staticmethod
    def _validate_task_identity(agent: AgentSpec, task: TaskEnvelope) -> None:
        if task.target_agent_id and task.target_agent_id != agent.agent_id:
            raise PermissionError("task target agent does not match execution agent")
