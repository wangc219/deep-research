from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
import os
from pathlib import Path
from typing import Any

from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.domain.messages import AgentExecutionResult, TaskEnvelope
from equipment_deep_research.domain.models import new_stable_id
from equipment_deep_research.harness.agent_harness import AgentHarness
from equipment_deep_research.harness.profiles import HarnessCatalog
from equipment_deep_research.harness.session import JsonlSessionStore
from equipment_deep_research.orchestration.execution_contracts import (
    is_quality_execution_profile_id,
)
from equipment_deep_research.providers.base import (
    ModelMessage,
    ProviderFinalTurn,
    ProviderStreamEvent,
)
from equipment_deep_research.tools.definitions import ToolDefinition
from equipment_deep_research.tools.domain_tools import build_domain_tool_definitions
from equipment_deep_research.tools.permissions import effective_tool_names


class WinningCoreHarness:
    def __init__(
        self,
        *,
        run_id: str,
        agent: AgentDef,
        catalog: HarnessCatalog,
        sessions_dir: Path,
        workspace: Any,
        store: Any,
    ) -> None:
        self.run_id = run_id
        self.agent = agent
        self.catalog = catalog
        self.sessions_dir = Path(sessions_dir)
        self.workspace = workspace
        self.store = store

    def execute(
        self,
        advisor: Callable[[dict[str, Any]], dict[str, Any]],
        payload: dict[str, Any],
        *,
        attempt: int,
        resume_from: str,
    ) -> tuple[dict[str, Any], AgentExecutionResult, list[str]]:
        profile = self.catalog.profiles[self.agent.harness_profile]
        optimized_v2 = is_quality_execution_profile_id(
            payload.get("execution_profile_id")
        )
        skills = [self.catalog.skills[item] for item in self.agent.skill_ids]
        active_tools = list(
            effective_tool_names(
                agent_allowlist=self.agent.tools,
                task_allowlist=self.agent.tools,
                skill_allowlists=(skill.allowed_tools for skill in skills),
                phase_allowlist=profile.phase_tools.get("winning", self.agent.tools),
            )
        )
        if optimized_v2:
            # The wrapper only delegates one structured advisor call.  S1-S6
            # tool semantics are enforced inside the provider's logical roles,
            # so replaying the full six-skill/tool catalog here adds no quality.
            active_tools = [
                item
                for item in (
                    "write_reasoning_node",
                    "write_stage_output",
                    "create_capability_image",
                )
                if item in active_tools
            ]
        active_skill_ids = (
            list(self.agent.skill_ids[:1])
            if optimized_v2
            else list(self.agent.skill_ids)
        )
        task_budget = _winning_task_budget(
            profile.task_budget(),
            optimized_v2=optimized_v2,
        )
        provider = _WinningAdvisorProvider(advisor, payload)
        harness = AgentHarness(
            provider,
            build_domain_tool_definitions(active_tools),
            _BufferedHarnessStore(self.store, self.run_id),
            sessions_root=self.sessions_dir,
            model_name=str(self.agent.model_profile.get("model", "gpt-5.5")),
            model_options={
                key: value
                for key, value in self.agent.model_profile.items()
                if key not in {"provider", "model"}
            },
            session_store_factory=lambda session_ref, _root: self._session(session_ref),
        )
        task = TaskEnvelope(
            task_id=f"winning-core:r{attempt}",
            run_id=self.run_id,
            round_index=attempt,
            parent_task_id="orchestrator",
            target_agent_id=self.agent.agent_id,
            target_capability_tags=list(self.agent.capability_tags),
            objective="消费 typed baseline packets，执行六步制胜推理和 L1/L2/L3 门控。",
            research_questions=[str(payload.get("topic", ""))],
            context_refs=[str(item.get("packet_id", "")) for item in payload.get("packets", [])],
            evidence_refs=[
                str(item.get("evidence_id", ""))
                for item in payload.get("evidence_index", [])
            ],
            allowed_tools=active_tools,
            object_read_scopes=list(self.agent.object_read_scopes),
            object_write_scopes=list(self.agent.object_write_scopes),
            budget=task_budget,
            return_contract="winning_mechanism_stage_output",
            return_node=resume_from,
            runtime_profile_id=self.agent.harness_profile,
            active_skill_ids=active_skill_ids,
            phase_id="winning",
        )
        result = asyncio.run(harness.execute(task))
        if result.status != "completed":
            if provider.error is not None:
                raise provider.error
            raise RuntimeError(result.error or f"winning AgentHarness stopped: {result.status}")
        return provider.result or {}, result, active_tools

    def _session(self, session_ref: str) -> JsonlSessionStore:
        root_fd = self.workspace.dup_sessions_fd()
        try:
            return JsonlSessionStore(
                session_ref,
                root_fd=root_fd,
                root_label=self.sessions_dir,
            )
        finally:
            os.close(root_fd)


class _WinningAdvisorProvider:
    def __init__(
        self,
        advisor: Callable[[dict[str, Any]], dict[str, Any]],
        payload: dict[str, Any],
    ) -> None:
        self.advisor = advisor
        self.payload = payload
        self.result: dict[str, Any] | None = None
        self.error: BaseException | None = None

    async def stream(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolDefinition],
        options: Mapping[str, Any],
    ) -> AsyncIterator[ProviderStreamEvent]:
        del messages, tools, options
        try:
            self.result = await asyncio.to_thread(self.advisor, self.payload)
        except BaseException as exc:
            self.error = exc
            raise
        yield ProviderStreamEvent.final(
            ProviderFinalTurn(
                text="winning core structured analysis completed",
                finish_reason="completed",
                metadata={"structured_result": bool(self.result)},
            )
        )


def _winning_task_budget(
    configured: Mapping[str, int],
    *,
    optimized_v2: bool,
) -> dict[str, int]:
    task_budget = dict(configured)
    if not optimized_v2:
        return task_budget
    # The advisor owns the run-scoped Harness v2 soft/hard deadlines and
    # performs several bounded model calls inside one blocking worker thread.
    # A second 900-second AgentHarness deadline cannot cancel that thread; it
    # only discards an otherwise complete S6 result and marks the whole run
    # failed with ``wall-clock budget expired``.  Keep turn/tool/token
    # governance here and let the execution contract govern elapsed time.
    return {
        "max_turns": 1,
        "max_tool_calls": 1,
        "max_tokens": min(int(task_budget.get("max_tokens", 12000)), 9000),
    }


class _BufferedHarnessStore:
    def __init__(self, delegate: Any, run_id: str) -> None:
        self.delegate = delegate
        self.run_id = run_id
        self.commits: list[tuple[tuple[Any, ...], tuple[Any, ...]]] = []

    def commit(self, domains: Sequence[Any], traces: Sequence[Any]) -> str:
        self.commits.append((tuple(domains), tuple(traces)))
        return new_stable_id("winning-harness-checkpoint")


__all__ = ["WinningCoreHarness"]
