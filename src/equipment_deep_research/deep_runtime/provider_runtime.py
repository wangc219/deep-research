"""Provider-neutral model runtime used by the deep-research Agent Core.

The repository already contains wire adapters under ``providers/``.  This
module supplies the missing nanobot-style boundary above those adapters: the
Agent Core asks for one structured completion, while the selected provider is
free to be Responses, Chat Completions, Codex CLI, a local model, or a test
double.  The wrapper also lets embedded hosts provide their existing
``_run_core_json`` callback without coupling runtime code to a vendor.
"""

from __future__ import annotations

import inspect
import json
import os
import re
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from equipment_deep_research.providers.base import (
    ModelMessage,
    ModelProvider,
    ProviderCapabilities,
    ProviderFinalTurn,
    ProviderStreamEvent,
    ProviderToolCall,
)
from equipment_deep_research.contracts.tools import ToolDefinition


def _text(value: Any, limit: int = 8000) -> str:
    return _sanitize_string(" ".join(str(value or "").split()).strip())[: max(0, int(limit))]


_SENSITIVE_KEY_MARKERS = (
    "authorization",
    "apikey",
    "accesstoken",
    "refreshtoken",
    "password",
    "secret",
    "cookie",
    "credential",
    "privatekey",
    "rawsession",
    "rawmessage",
    "rawresponse",
    "providerresponse",
    "providermetadata",
    "providerheaders",
    "hiddenreasoning",
    "reasoningtrace",
    "chainofthought",
    "internalprompt",
    "systemprompt",
    "reasoning",
    "cot",
    "rawoutput",
    "responsebody",
    "modelresponse",
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|authorization|cookie)\b"
    r"\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_HIDDEN_BLOCK_RE = re.compile(
    r"(?is)<(?:think|analysis|reasoning)>.*?</(?:think|analysis|reasoning)>"
)
_SAFE_SNAPSHOT_KEYS = frozenset(
    {
        "type",
        "providertype",
        "primaryprovidertype",
        "model",
        "baseurlhost",
        "contextisolation",
        "fallbackpolicy",
        "providerchain",
        "capabilities",
        "providerid",
        "adapter",
        "streaming",
        "structuredoutput",
        "functiontools",
        "hostedwebsearch",
        "isolatedsessions",
        "resumablesessions",
        "cancellation",
        "workspacescope",
        "maxoutputtokens",
        "agentruntime",
    }
)

# Execution identity is used by the scheduler/provider gate, never by the
# model.  Keep the projection recursive because deep dialogue payloads carry
# the same envelope inside parent/context objects.
_RUNTIME_METADATA_KEYS = frozenset(
    {
        "run_id",
        "_run_id",
        "_audit_run_id",
        "fairness_key",
        "_fairness_key",
        "priority",
        "_codex_call_priority",
    }
)


def _normalized_key(key: Any) -> str:
    return "".join(character for character in str(key).lower() if character.isalnum())


def _is_sensitive_key(key: Any) -> bool:
    normalized = _normalized_key(key)
    return any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS) or normalized in {
        "token",
        "key",
        "auth",
    }


def _sanitize_string(value: str) -> str:
    value = _HIDDEN_BLOCK_RE.sub("<redacted>", value)
    value = _PRIVATE_KEY_RE.sub("<redacted>", value)
    value = _BEARER_RE.sub("Bearer <redacted>", value)
    return _SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(0).split('=', 1)[0].split(':', 1)[0]}=<redacted>",
        value,
    )


def _bounded(
    value: Any,
    *,
    depth: int = 0,
    max_depth: int = 8,
    max_string_length: int = 2000,
) -> Any:
    """Return a bounded, recursively redacted JSON-compatible projection.

    Nested output schemas may cross this boundary more than once.  Keeping a
    little headroom avoids truncating valid schemas while retaining hard
    collection and string limits.
    """
    if depth >= max(1, int(max_depth)):
        return "<truncated>" if isinstance(value, str) else None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _sanitize_string(value)[:max_string_length]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:48]:
            name = str(key)[:120]
            result[name] = "<redacted>" if _is_sensitive_key(name) else _bounded(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_string_length=max_string_length,
            )
        return result
    if isinstance(value, (list, tuple)):
        return [
            _bounded(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_string_length=max_string_length,
            )
            for item in list(value)[:24]
        ]
    return _sanitize_string(str(value))[:max_string_length]


def _model_visible_payload(value: Any) -> Any:
    """Remove scheduler-only metadata before a payload reaches a provider."""

    if isinstance(value, Mapping):
        return {
            key: _model_visible_payload(item)
            for key, item in value.items()
            if str(key) not in _RUNTIME_METADATA_KEYS
        }
    if isinstance(value, list):
        return [_model_visible_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_model_visible_payload(item) for item in value)
    return value


def _payload_run_id(payload: Mapping[str, Any]) -> str:
    """Read a trusted run identity from the structured request envelope."""

    current: Any = payload
    for _ in range(3):
        if not isinstance(current, Mapping):
            return ""
        for key in ("_run_id", "run_id"):
            value = " ".join(str(current.get(key) or "").split()).strip()
            if value:
                return value[:160]
        nested = current.get("input")
        if not isinstance(nested, Mapping) or nested is current:
            break
        current = nested
    return ""


def _safe_snapshot(value: Any, *, depth: int = 0) -> Any:
    """Allowlist provider metadata after recursive secret redaction."""

    if depth >= 4:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _sanitize_string(value)[:500]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, item in list(value.items())[:32]:
            key = str(raw_key)[:80]
            normalized = _normalized_key(key)
            if _is_sensitive_key(key) or normalized not in _SAFE_SNAPSHOT_KEYS:
                continue
            result[key] = _safe_snapshot(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_snapshot(item, depth=depth + 1) for item in list(value)[:8]]
    return None


def _decode_json_text(value: Any) -> Any | None:
    """Decode a provider JSON value, tolerating common markdown wrappers.

    Providers and legacy host callbacks do not all agree on whether a
    structured response is returned as a mapping or as text.  Keep that
    compatibility at this boundary so tools and subagents see one contract;
    never pass an unbounded raw completion further into the runtime.
    """

    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8", errors="replace")
        except Exception:
            return None
    if not isinstance(value, str):
        return value if isinstance(value, (Mapping, list, tuple)) else None
    # Parse before applying credential patterns: a Bearer token at the end
    # of a JSON string can otherwise consume its closing quote.  Parsed
    # values are sanitized recursively by the completion boundary.
    text = _HIDDEN_BLOCK_RE.sub("<redacted>", value).strip()
    if not text:
        return None
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Some gateways prepend a short label or append a status line.  Decode
        # the first complete JSON object/array without attempting to repair
        # arbitrary model prose.
        starts = [index for index in (text.find("{"), text.find("[")) if index >= 0]
        if not starts:
            return None
        try:
            parsed, _ = json.JSONDecoder().raw_decode(text[min(starts) :])
        except json.JSONDecodeError:
            return None
        return parsed


def _safe_provider_text(value: str) -> str:
    parsed = _decode_json_text(value)
    if isinstance(parsed, (Mapping, list, tuple)):
        return json.dumps(
            _bounded(parsed, max_string_length=12000),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    return _sanitize_string(value)[:96000]


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    """One provider-neutral model request."""

    messages: Sequence[ModelMessage]
    tools: Sequence[ToolDefinition] = field(default_factory=tuple)
    options: Mapping[str, Any] = field(default_factory=dict)
    request_id: str = ""

    def __post_init__(self) -> None:
        messages = tuple(self.messages)
        tools = tuple(self.tools)
        if not all(isinstance(item, ModelMessage) for item in messages):
            raise TypeError("ProviderRequest.messages must contain ModelMessage values")
        if not all(isinstance(item, ToolDefinition) for item in tools):
            raise TypeError("ProviderRequest.tools must contain ToolDefinition values")
        if not isinstance(self.options, Mapping):
            raise TypeError("ProviderRequest.options must be an object")
        object.__setattr__(self, "messages", messages)
        object.__setattr__(self, "tools", tools)
        object.__setattr__(self, "options", _bounded(dict(self.options)))
        object.__setattr__(self, "request_id", _text(self.request_id, 160))


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """Normalized result independent of a provider wire protocol."""

    text: str | None = None
    tool_calls: Sequence[ProviderToolCall] = field(default_factory=tuple)
    finish_reason: str | None = None
    usage: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    provider_id: str = ""
    model: str = ""

    def __post_init__(self) -> None:
        calls = tuple(self.tool_calls)
        if not all(isinstance(item, ProviderToolCall) for item in calls):
            raise TypeError("ProviderResult.tool_calls must contain ProviderToolCall values")
        object.__setattr__(
            self,
            "tool_calls",
            tuple(
                ProviderToolCall(
                    _text(item.call_id, 160),
                    _text(item.name, 128),
                    _bounded(item.arguments),
                )
                for item in calls[:24]
                if _text(item.call_id, 160) and _text(item.name, 128)
            ),
        )
        object.__setattr__(
            self,
            "text",
            None if self.text is None else _safe_provider_text(str(self.text)),
        )
        object.__setattr__(
            self,
            "finish_reason",
            None if self.finish_reason is None else _text(self.finish_reason, 120),
        )
        object.__setattr__(self, "usage", _bounded(dict(self.usage)) if isinstance(self.usage, Mapping) else {})
        object.__setattr__(self, "metadata", _bounded(dict(self.metadata)) if isinstance(self.metadata, Mapping) else {})
        object.__setattr__(self, "provider_id", _text(self.provider_id, 120))
        object.__setattr__(self, "model", _text(self.model, 160))

    def to_plain(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "tool_calls": [_bounded(item.to_plain()) for item in self.tool_calls],
            "finish_reason": self.finish_reason,
            "usage": _bounded(self.usage),
            "metadata": _bounded(self.metadata),
            "provider_id": self.provider_id,
            "model": self.model,
        }


JsonCallback = Callable[..., Any]


class ProviderRuntime:
    """A tiny, observable facade over one model provider.

    ``json_callback`` is intentionally supported for existing hosts.  It is a
    compatibility bridge, not a vendor branch: callers can migrate from a
    host-owned model call to a direct ``ModelProvider`` incrementally.
    """

    def __init__(
        self,
        provider: ModelProvider | None = None,
        *,
        provider_id: str = "",
        model: str = "",
        json_callback: JsonCallback | None = None,
    ) -> None:
        if provider is None and json_callback is None:
            raise ValueError("ProviderRuntime requires a provider or json_callback")
        if provider is not None and not callable(getattr(provider, "stream", None)):
            raise TypeError("provider must expose an async stream method")
        self.provider = provider
        self.provider_id = _text(provider_id, 120) or _text(
            self._provider_snapshot().get("type", "")
            or getattr(provider, "provider_type", ""),
            120,
        )
        self.model = _text(model, 160) or _text(getattr(provider, "model", ""), 160)
        self._json_callback = json_callback

    @classmethod
    def from_host(cls, host: Any) -> "ProviderRuntime | None":
        """Capture the provider surface of an existing workflow host."""

        existing = getattr(host, "deep_provider_runtime", None)
        if isinstance(existing, cls):
            return existing
        callback = getattr(host, "_run_core_json", None)
        provider = getattr(host, "provider", None)
        if provider is None:
            provider = getattr(host, "model_provider", None)
        # A number of legacy hosts expose a high-level provider wrapper under
        # ``provider`` while keeping the actual JSON bridge on the host.  Only
        # wrap objects that satisfy the wire-level stream contract; otherwise
        # prefer the callback instead of rejecting an otherwise valid host.
        if not callable(getattr(provider, "stream", None)):
            provider = None
        if provider is None and not callable(callback):
            return None
        return cls(provider if provider is not None else None, json_callback=callback if callable(callback) else None)

    def _provider_snapshot(self) -> dict[str, Any]:
        if self.provider is None:
            return {}
        snapshot = getattr(self.provider, "snapshot", None)
        try:
            value = snapshot() if callable(snapshot) else {}
        except Exception:
            value = {}
        return dict(value) if isinstance(value, Mapping) else {}

    def capabilities(self) -> ProviderCapabilities:
        if self.provider is None:
            return ProviderCapabilities(agent_runtime=True)
        callback = getattr(self.provider, "capabilities", None)
        try:
            value = callback() if callable(callback) else None
        except Exception:
            value = None
        return value if isinstance(value, ProviderCapabilities) else ProviderCapabilities()

    def snapshot(self) -> dict[str, Any]:
        """Return secret-free provider metadata suitable for runtime output."""

        snapshot = self._provider_snapshot()
        snapshot.pop("api_key", None)
        snapshot.pop("headers", None)
        snapshot.update(
            {
                "provider_id": self.provider_id,
                "model": self.model,
                "capabilities": self.capabilities().to_plain(),
                "adapter": "host_callback" if self._json_callback is not None else "model_provider",
            }
        )
        return _safe_snapshot(snapshot)

    async def stream(self, request: ProviderRequest) -> AsyncIterator[ProviderStreamEvent]:
        if self.provider is None:
            raise RuntimeError("ProviderRuntime has no stream provider")
        result = self.provider.stream(request.messages, request.tools, request.options)
        if not hasattr(result, "__aiter__"):
            raise TypeError("provider.stream must return an async iterator")
        async for event in result:
            if not isinstance(event, ProviderStreamEvent):
                raise TypeError("provider emitted an invalid ProviderStreamEvent")
            yield event

    async def complete(self, request: ProviderRequest) -> ProviderResult:
        """Consume one stream and normalize its terminal event."""

        text_parts: list[str] = []
        calls: list[ProviderToolCall] = []
        final: ProviderFinalTurn | None = None
        async for event in self.stream(request):
            if event.event_type == "text_delta":
                text_parts.append(event.delta)
            elif event.event_type == "reasoning_delta":
                # Hidden reasoning is not a mergeable research artifact.
                continue
            elif event.event_type == "tool_call" and event.tool_call is not None:
                calls.append(event.tool_call)
            elif event.event_type == "final":
                final = event.final_turn
        if final is not None:
            calls = list(final.tool_calls or calls)
            text = final.text if final.text is not None else "".join(text_parts)
            metadata = dict(final.metadata)
            usage = dict(final.usage)
            finish_reason = final.finish_reason
        else:
            text = "".join(text_parts)
            metadata = {}
            usage = {}
            finish_reason = None
        return ProviderResult(
            text=text or None,
            tool_calls=calls,
            finish_reason=finish_reason,
            usage=usage,
            metadata=metadata,
            provider_id=self.provider_id,
            model=self.model,
        )

    async def complete_json(
        self,
        *,
        agent_id: str,
        system: str,
        payload: Mapping[str, Any],
        output_schema: Mapping[str, Any],
        max_output_tokens: int,
        phase: str = "structured_analysis",
    ) -> Any:
        """Request structured JSON through the host callback or provider."""

        if self._json_callback is not None:
            args = (
                agent_id,
                system,
                dict(payload),
                dict(output_schema),
                int(max_output_tokens),
            )
            kwargs = {"phase": phase}
            try:
                inspect.signature(self._json_callback).bind(*args, **kwargs)
            except TypeError:
                # Determine compatibility before invoking the callback.  A
                # TypeError raised inside a synchronous provider must not
                # accidentally issue the same model request a second time.
                kwargs = {}
            except (ValueError, AttributeError):
                pass
            value = self._json_callback(*args, **kwargs)
            if inspect.isawaitable(value):
                value = await value
            if isinstance(value, str | bytes | bytearray):
                parsed = _decode_json_text(value)
                if parsed is None:
                    return {
                        "_provider_error": "invalid_json",
                        "_text": _text(value, 4000),
                    }
                value = parsed
            if isinstance(value, Mapping | list | tuple):
                return _bounded(value, max_string_length=12000)
            if value is None:
                return {}
            return {
                "_provider_error": "invalid_shape",
                "_text": _text(value, 4000),
            }
        run_id = _payload_run_id(payload)
        request_options: dict[str, Any] = {
            # ProviderRequest applies the same projection at its boundary;
            # pass the original schema here so nesting is not counted twice
            # before it reaches the provider adapter.
            "output_schema": dict(output_schema),
            "max_output_tokens": max(1, int(max_output_tokens)),
            "phase": phase,
        }
        if run_id:
            request_options.update(
                {
                    "_run_id": run_id,
                    "_fairness_key": run_id,
                }
            )
        if phase.startswith("deep_contextual_dialogue"):
            # Direct nanobot-style providers do not pass through the legacy
            # workflow priority selector. Keep interactive deep turns ahead
            # of background swarm work when the provider supports priorities.
            request_options.setdefault("_codex_call_priority", "critical")
        if phase.startswith("deep_contextual_dialogue_s6_column_2"):
            # The direct nanobot-style provider path bypasses the legacy
            # workflow option builder. Mirror the bounded technology lane
            # here so Responses and other adapters cannot wait indefinitely
            # or issue the same live search on the recovery attempt.
            try:
                technology_timeout = int(
                    os.environ.get(
                        "EQUIPMENT_DR_DEEP_TECHNOLOGY_TIMEOUT_SECONDS", "180"
                    )
                )
            except (TypeError, ValueError):
                technology_timeout = 180
            request_options.update(
                {
                    "_provider_timeout_seconds": max(
                        45, min(300, technology_timeout)
                    ),
                    "_disable_provider_timeout": False,
                    "_provider_retry_attempts": 1,
                }
            )
            if not any(
                phase.endswith(suffix)
                for suffix in ("_retry", "_model_recovery", "_offline_recovery")
            ):
                request_options.update(
                    {
                        "web_search": {
                            "search_context_size": "medium",
                            "external_web_access": True,
                        },
                        "include_web_sources": True,
                        # Search is preferred for this column, but it is not a
                        # prerequisite for returning engineering prose. A
                        # blocked domestic site or an adapter without
                        # web-search support must not yield an empty column.
                        "require_web_search": False,
                    }
                )
        model_payload = _model_visible_payload(dict(payload))
        request = ProviderRequest(
            messages=(
                ModelMessage("system", system),
                ModelMessage("user", json.dumps(_bounded(model_payload), ensure_ascii=False)),
            ),
            options=request_options,
        )
        result = await self.complete(request)
        if not result.text:
            return {}
        parsed = _decode_json_text(result.text)
        if parsed is not None and isinstance(parsed, (Mapping, list, tuple)):
            return _bounded(parsed, max_string_length=12000)
        else:
            # Keep the provider boundary honest: malformed model output is a
            # structured failure, never an implicit natural-language answer.
            return {
                "_provider_error": "invalid_json",
                "_text": _text(result.text, 4000),
            }


async def run_json_with_provider(
    host: Any,
    agent_id: str,
    system: str,
    payload: Mapping[str, Any],
    output_schema: Mapping[str, Any],
    max_output_tokens: int,
    *,
    phase: str = "structured_analysis",
    runtime: ProviderRuntime | None = None,
) -> Any:
    """Use the common provider facade while retaining legacy host behavior."""

    runtime = runtime or ProviderRuntime.from_host(host)
    if runtime is None:
        raise RuntimeError("research host has no model provider runtime")
    return await runtime.complete_json(
        agent_id=agent_id,
        system=system,
        payload=payload,
        output_schema=output_schema,
        max_output_tokens=max_output_tokens,
        phase=phase,
    )


__all__ = [
    "ProviderRequest",
    "ProviderResult",
    "ProviderRuntime",
    "run_json_with_provider",
]
