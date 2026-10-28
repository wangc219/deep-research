"""Model-call liveness middleware for every conversational agent.

Business agents keep ownership of prompts and decisions.  This middleware only
projects long waits into the run event stream and enforces one cancellable wall-clock
boundary around a logical model step.  Provider/network retries remain the concern of
``NetworkRetryMiddleware`` so streamed output is never replayed here.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware, ModelRequest, ModelResponse
from langgraph.config import get_stream_writer

from equipment_deep_research.harness.model_calls import ModelCallEvent, ModelCallPolicy, ModelCallSupervisor
from platform_core.config import get_int_env


class ModelCallSupervisorMiddleware(AgentMiddleware):
    """Expose typed wait events without changing model reasoning or retrying streams."""

    def __init__(
        self,
        *,
        timeout_seconds: int | None = None,
        feedback_interval_seconds: int | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds or get_int_env(
            "AGENT_MODEL_CALL_TIMEOUT_SECONDS", 1800, minimum=60, maximum=3600
        )
        self.feedback_interval_seconds = feedback_interval_seconds or get_int_env(
            "AGENT_MODEL_WAIT_FEEDBACK_SECONDS", 30, minimum=10, maximum=120
        )

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        # Production chat execution is asynchronous.  Keep the synchronous seam
        # behavior-preserving instead of creating an event loop inside a caller.
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        async def factory(_attempt: int) -> ModelResponse[Any]:
            return await handler(request)

        supervisor = ModelCallSupervisor[ModelResponse[Any]](
            ModelCallPolicy(
                total_timeout_seconds=float(self.timeout_seconds),
                attempt_timeout_seconds=float(self.timeout_seconds),
                max_attempts=1,
                feedback_interval_seconds=float(self.feedback_interval_seconds),
            )
        )
        return await supervisor.run(factory, observer=self._project_event)

    @staticmethod
    async def _project_event(event: ModelCallEvent) -> None:
        if event.kind not in {"waiting", "completed"}:
            return
        try:
            writer = get_stream_writer()
        except RuntimeError:
            return
        writer(
            {
                "type": "platform_core.model_call_progress",
                "status": event.kind,
                "attempt": event.attempt,
                "elapsed_seconds": round(event.elapsed_seconds, 1),
            }
        )
