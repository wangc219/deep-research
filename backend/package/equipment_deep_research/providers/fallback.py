"""Failure-aware provider chain used for explicit external-agent fallback."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
import logging
from typing import Any

from equipment_deep_research.providers.base import (
    ModelMessage,
    ModelProvider,
    ProviderCapabilities,
    ProviderFinalTurn,
    ProviderStreamEvent,
)
from equipment_deep_research.providers.responses import (
    ProviderCapacityError,
    ProviderRequestError,
)
from equipment_deep_research.contracts.tools import ToolDefinition


logger = logging.getLogger(__name__)


class FallbackProvider:
    """Try providers in order until one completes a model turn."""

    provider_type = "fallback_chain"

    def __init__(
        self,
        providers: Sequence[ModelProvider],
        *,
        fallback_policy: str = "any",
    ) -> None:
        if not providers:
            raise ValueError("fallback chain requires at least one provider")
        if fallback_policy not in {"any", "capacity_only"}:
            raise ValueError("fallback policy must be 'any' or 'capacity_only'")
        self.providers = tuple(providers)
        self.fallback_policy = fallback_policy

    def capabilities(self) -> ProviderCapabilities:
        values = [provider.capabilities() for provider in self.providers]
        if self.fallback_policy == "capacity_only":
            # This chain is an emergency route for saturation only.  Preserve
            # the primary provider's advertised contract so enabling an
            # optional backup does not disable Codex-only orchestration paths
            # (isolated sessions, hosted search, or agent runtime) before a
            # fallback is actually needed.
            return values[0]
        return ProviderCapabilities(
            streaming=all(item.streaming for item in values),
            structured_output=all(item.structured_output for item in values),
            function_tools=all(item.function_tools for item in values),
            hosted_web_search=any(item.hosted_web_search for item in values),
            isolated_sessions=all(item.isolated_sessions for item in values),
            resumable_sessions=all(item.resumable_sessions for item in values),
            cancellation=all(item.cancellation for item in values),
            workspace_scope=all(item.workspace_scope for item in values),
            max_output_tokens=min(
                (item.max_output_tokens for item in values if item.max_output_tokens is not None),
                default=None,
            ),
            agent_runtime=all(item.agent_runtime for item in values),
        )

    def snapshot(self) -> dict[str, Any]:
        primary_snapshot = getattr(self.providers[0], "snapshot", lambda: {})()
        return {
            "type": self.provider_type,
            "fallback_policy": self.fallback_policy,
            "primary_provider_type": str(
                getattr(self.providers[0], "provider_type", "")
                or (
                    primary_snapshot.get("type", "")
                    if isinstance(primary_snapshot, Mapping)
                    else ""
                )
            ),
            "provider_chain": [
                dict(getattr(provider, "snapshot", lambda: {})())
                for provider in self.providers
            ],
            "capabilities": self.capabilities().to_plain(),
        }

    def isolated_copy(self, isolation_id: str, *, model: str | None = None) -> FallbackProvider:
        copies = []
        for provider in self.providers:
            factory = getattr(provider, "isolated_copy", None)
            if callable(factory):
                try:
                    copies.append(factory(isolation_id, model=model))
                except TypeError:
                    copies.append(factory(isolation_id))
            else:
                copies.append(provider)
        return FallbackProvider(copies, fallback_policy=self.fallback_policy)

    def has_backup_provider(self) -> bool:
        """Whether this chain has a provider that can be selected explicitly.

        The normal chain remains policy driven (``capacity_only`` is still
        capacity-only).  Reporter recovery uses this read-only capability to
        distinguish a configured DeepSeek backup from a primary-only provider
        before asking the stream to force a switch.
        """

        return len(self.providers) > 1

    def close(self) -> None:
        for provider in self.providers:
            close = getattr(provider, "close", None)
            if callable(close):
                close()

    async def stream(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolDefinition],
        options: Mapping[str, Any],
    ) -> AsyncIterator[ProviderStreamEvent]:
        forced = bool(options.get("_force_fallback_provider", False))
        fallback_origin = ""
        fallback_reason = ""
        start_index = 0
        if forced and len(self.providers) < 2:
            raise ProviderRequestError(
                "explicit provider fallback requested but no backup provider is configured"
            )
        if forced and len(self.providers) > 1:
            start_index = 1
            primary = self.providers[0]
            primary_snapshot = getattr(primary, "snapshot", lambda: {})()
            fallback_origin = str(
                getattr(primary, "provider_type", "")
                or (
                    primary_snapshot.get("type", "provider")
                    if isinstance(primary_snapshot, Mapping)
                    else "provider"
                )
            )
            fallback_reason = str(
                options.get("_fallback_reason")
                or "forced_reporter_fallback"
            )
            logger.warning(
                "Forced provider fallback activated; skipping primary provider %s",
                fallback_origin,
            )
        for index, provider in enumerate(self.providers[start_index:], start=start_index):
            emitted = False
            try:
                async for event in provider.stream(messages, tools, options):
                    emitted = True
                    if (
                        fallback_reason
                        and event.event_type == "final"
                        and event.final_turn is not None
                    ):
                        metadata = dict(event.final_turn.metadata)
                        metadata.update(
                            {
                                "fallback_activated": True,
                                "fallback_reason": fallback_reason,
                                "fallback_from": fallback_origin,
                                "fallback_provider": dict(
                                    getattr(provider, "snapshot", lambda: {})()
                                ),
                            }
                        )
                        event = ProviderStreamEvent.final(
                            ProviderFinalTurn(
                                text=event.final_turn.text,
                                tool_calls=event.final_turn.tool_calls,
                                finish_reason=event.final_turn.finish_reason,
                                usage=event.final_turn.usage,
                                metadata=metadata,
                            )
                        )
                    yield event
                return
            except Exception as exc:
                # An explicitly requested recovery wave may continue through a
                # second configured backup, but it must never silently return
                # to the exhausted primary provider.
                if (
                    not forced
                    and self.fallback_policy == "capacity_only"
                    and not isinstance(exc, ProviderCapacityError)
                ):
                    raise
                if emitted or index + 1 >= len(self.providers):
                    raise
                logger.warning(
                    "Provider fallback activated after %s failure; switching from index %s to index %s",
                    type(exc).__name__,
                    index,
                    index + 1,
                )
                provider_snapshot = getattr(provider, "snapshot", lambda: {})()
                fallback_origin = str(
                    getattr(provider, "provider_type", "")
                    or (
                        provider_snapshot.get("type", "provider")
                        if isinstance(provider_snapshot, Mapping)
                        else "provider"
                    )
                )
                fallback_reason = (
                    "capacity" if isinstance(exc, ProviderCapacityError) else type(exc).__name__
                )


__all__ = ["FallbackProvider"]
