"""Responses-compatible HTTPS/SSE model provider.

The provider only translates model events. Tool execution remains exclusively
inside the Harness, so credentials and network authority never leak to agents.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from http.client import RemoteDisconnected
import json
import os
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from equipment_deep_research.providers.base import (
    ModelMessage,
    ProviderCapabilities,
    ProviderFinalTurn,
    ProviderStreamEvent,
    ProviderToolCall,
)
from equipment_deep_research.domain.proposals import thaw_plain
from equipment_deep_research.contracts.tools import ToolDefinition


class ProviderAuthenticationError(RuntimeError):
    pass


class ProviderRetryableError(RuntimeError):
    pass


class ProviderRequestError(RuntimeError):
    pass


class ProviderCapacityError(ProviderRequestError):
    """A provider refused a request because the selected model is saturated."""

    pass


def build_request_payload(
    *, model: str, messages: Sequence[ModelMessage], tools: Sequence[ToolDefinition], options: Mapping[str, Any]
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "input": [_message_to_response_input(message) for message in messages],
        "stream": True,
    }
    declared_tools: list[dict[str, Any]] = []
    web_search = options.get("web_search")
    if isinstance(web_search, Mapping):
        web_search_payload = thaw_plain(web_search)
        if isinstance(web_search_payload, dict):
            search_context_mode = os.environ.get(
                "EQUIPMENT_DR_SEARCH_CONTEXT_SIZE_MODE", "send"
            ).strip().lower()
            if search_context_mode in {"omit", "none", "disabled"}:
                web_search_payload.pop("search_context_size", None)
        declared_tools.append({"type": "web_search", **web_search_payload})
    if tools:
        declared_tools.extend([
            {"type": "function", "name": tool.name, "description": tool.description, "parameters": thaw_plain(tool.input_schema)}
            for tool in tools
        ])
    if declared_tools:
        payload["tools"] = declared_tools
    if options.get("include_web_sources"):
        payload["include"] = ["web_search_call.action.sources"]
    if options.get("require_web_search"):
        # DashScope's Qwen Responses endpoint rejects an object/required
        # ``tool_choice`` while reasoning (thinking) mode is enabled.  The
        # request is otherwise valid and the gateway will select web_search
        # when offered, so use ``auto`` for those deployment models.  Keep the
        # strict choice for OpenAI-compatible gateways that support it.
        if str(model).strip().lower().startswith(("qwen", "qwen3")):
            payload["tool_choice"] = "auto"
        else:
            payload["tool_choice"] = {"type": "web_search"}
    effort = options.get("reasoning_effort")
    if effort:
        payload["reasoning"] = {"effort": effort}
    if "max_output_tokens" in options:
        payload["max_output_tokens"] = options["max_output_tokens"]
    output_schema = options.get("output_schema")
    if isinstance(output_schema, Mapping):
        payload["text"] = {
            "format": {
                "type": "json_schema",
                "name": "equipment_research_output",
                "strict": True,
                "schema": _compact_contract_to_json_schema(output_schema),
            }
        }
    return payload


def _without_optional_web_search(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Remove only the hosted-search decoration from a retry payload.

    Some Responses-compatible gateways implement the core endpoint but reject
    the optional ``web_search`` tool.  Keep function tools, schemas and model
    input intact so the caller still receives a useful structured answer.
    """
    downgraded = dict(payload)
    declared_tools = payload.get("tools")
    if isinstance(declared_tools, list):
        remaining_tools = [
            item
            for item in declared_tools
            if not (isinstance(item, Mapping) and item.get("type") == "web_search")
        ]
        if remaining_tools:
            downgraded["tools"] = remaining_tools
        else:
            downgraded.pop("tools", None)
    include = payload.get("include")
    if isinstance(include, list):
        remaining_include = [
            item
            for item in include
            if str(item) != "web_search_call.action.sources"
        ]
        if remaining_include:
            downgraded["include"] = remaining_include
        else:
            downgraded.pop("include", None)
    tool_choice = payload.get("tool_choice")
    if isinstance(tool_choice, Mapping) and tool_choice.get("type") == "web_search":
        downgraded.pop("tool_choice", None)
    return downgraded


def _can_downgrade_optional_web_search(
    exc: BaseException,
    options: Mapping[str, Any],
) -> bool:
    """Allow a single search-less retry for optional-tool request rejects."""
    if not isinstance(options.get("web_search"), Mapping):
        return False
    if bool(options.get("require_web_search")):
        return False
    detail = str(exc).lower()
    # Gateways format the same rejection as ``status=400``, ``status_code:
    # 400`` or ``HTTP Error 400``.  Read only the status token and keep the
    # allow-list narrow so authentication, quota and server failures are
    # never hidden behind a search-less retry.
    status_matches = re.findall(
        r"(?:status(?:_code)?\s*[:=]\s*|http(?:\s+error)?\s+)(\d{3})\b",
        detail,
    )
    return any(int(value) in {400, 404, 405, 422} for value in status_matches)


def _compact_contract_to_json_schema(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        properties = {
            str(key): _compact_contract_to_json_schema(item)
            for key, item in value.items()
        }
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }
    if isinstance(value, list):
        item = value[0] if value else "string"
        return {"type": "array", "items": _compact_contract_to_json_schema(item)}
    descriptor = str(value).strip()
    if descriptor == "boolean":
        return {"type": "boolean"}
    if descriptor in {"0..1", "0..1 number"}:
        return {"type": "number", "minimum": 0, "maximum": 1}
    if descriptor in {"1..5", "1..5 number"}:
        return {"type": "integer", "minimum": 1, "maximum": 5}
    if descriptor == "1..6":
        return {"type": "integer", "minimum": 1, "maximum": 6}
    if descriptor in {"1..6 or 0", "0..6"}:
        return {"type": "integer", "minimum": 0, "maximum": 6}
    if "|" in descriptor and all(
        token.strip() and " " not in token.strip()
        for token in descriptor.split("|")
    ):
        return {"type": "string", "enum": [item.strip() for item in descriptor.split("|")]}
    return {"type": "string"}


def parse_sse_event(line: str) -> tuple[str, dict[str, Any]] | None:
    """Parse one SSE data line; malformed JSON is a provider protocol error."""
    if not line.startswith("data:"):
        return None
    value = line[5:].strip()
    if not value or value == "[DONE]":
        return None
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ProviderRequestError("Responses SSE contained invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ProviderRequestError("Responses SSE event must be an object")
    return str(payload.get("type", "")), payload


def iter_sse_frames(lines: Iterable[str]) -> Iterable[str]:
    """Assemble SSE frames: consecutive ``data:`` lines joined per the SSE spec.

    Large events (e.g. ``response.completed``) may be split across multiple
    ``data:`` lines within one frame; joining them before JSON parsing is
    required for gateway compatibility.
    """
    buffer: list[str] = []
    for line in lines:
        stripped = line.rstrip("\r\n")
        if not stripped:
            if buffer:
                yield "\n".join(buffer)
                buffer = []
            continue
        if stripped.startswith("data:"):
            buffer.append(stripped[5:].lstrip(" "))
    if buffer:
        yield "\n".join(buffer)


def parse_sse_frame(data: str) -> tuple[str, dict[str, Any]] | None:
    """Parse an assembled SSE data frame into a Responses event."""
    value = data.strip()
    if not value or value == "[DONE]":
        return None
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ProviderRequestError("Responses SSE contained invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ProviderRequestError("Responses SSE event must be an object")
    return str(payload.get("type", "")), payload


def assistant_from_events(events: Iterable[tuple[str, Mapping[str, Any]]]) -> ProviderFinalTurn:
    text: list[str] = []
    text_delta_seen = False
    reasoning: list[str] = []
    calls: dict[str, dict[str, Any]] = {}
    final_payload: Mapping[str, Any] = {}
    for kind, event in events:
        if kind == "response.output_text.delta":
            text_delta_seen = True
            text.append(str(event.get("delta", "")))
        elif kind == "response.output_text.done" and not text_delta_seen:
            text.append(str(event.get("text", "")))
        elif kind in {"response.reasoning_summary_text.delta", "response.reasoning_text.delta"}:
            reasoning.append(str(event.get("delta", "")))
        elif kind in {"response.function_call_arguments.delta", "response.function_call_arguments.done"}:
            item_id = str(event.get("item_id", event.get("call_id", "")))
            current = calls.setdefault(item_id, {"name": event.get("name", ""), "arguments": ""})
            if event.get("name"):
                current["name"] = event["name"]
            if kind == "response.function_call_arguments.delta":
                current["arguments"] += str(event.get("delta", ""))
            elif not current["arguments"]:
                current["arguments"] = str(event.get("arguments", ""))
        elif kind in {"response.completed", "response.failed"}:
            final_payload = event.get("response", event)
    tool_calls: list[ProviderToolCall] = []
    for call_id, call in calls.items():
        try:
            arguments = json.loads(call["arguments"] or "{}")
        except json.JSONDecodeError as exc:
            raise ProviderRequestError("Responses function call arguments are invalid JSON") from exc
        tool_calls.append(ProviderToolCall(call_id, str(call["name"]), arguments))
    usage = final_payload.get("usage", {}) if isinstance(final_payload, Mapping) else {}
    web_sources, search_queries = _web_search_metadata(final_payload)
    return ProviderFinalTurn(
        text="".join(text) or None,
        tool_calls=tool_calls or None,
        finish_reason=str(final_payload.get("status", "completed")),
        usage=usage if isinstance(usage, Mapping) else {},
        metadata={
            "reasoning": "".join(reasoning),
            "web_sources": web_sources,
            "search_queries": search_queries,
        },
    )


def _web_search_metadata(payload: Mapping[str, Any]) -> tuple[list[dict[str, str]], list[str]]:
    sources: dict[str, dict[str, str]] = {}
    queries: list[str] = []
    output = payload.get("output", [])
    if not isinstance(output, list):
        return [], []
    for item in output:
        if not isinstance(item, Mapping):
            continue
        action = item.get("action", {})
        if isinstance(action, Mapping):
            query = str(action.get("query", "")).strip()
            if query and query not in queries:
                queries.append(query)
            action_sources = action.get("sources", [])
            if isinstance(action_sources, list):
                for source in action_sources:
                    _add_web_source(sources, source)
        content = item.get("content", [])
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, Mapping):
                continue
            annotations = part.get("annotations", [])
            if isinstance(annotations, list):
                for annotation in annotations:
                    _add_web_source(sources, annotation)
    return list(sources.values()), queries


def _add_web_source(target: dict[str, dict[str, str]], value: object) -> None:
    if not isinstance(value, Mapping):
        return
    url = str(value.get("url", "")).strip()
    if not url or url in target:
        return
    target[url] = {
        "url": url,
        "title": str(value.get("title", "")).strip(),
        "snippet": str(value.get("snippet", "")).strip(),
    }


class ResponsesProvider:
    def __init__(self, *, model: str, base_url: str, api_key: str, timeout_seconds: int = 120) -> None:
        if not api_key:
            raise ProviderAuthenticationError("Responses API key is required")
        parsed = urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Responses base URL must be HTTPS")
        self.model = model
        self.base_url = base_url
        self._api_key = api_key
        self.timeout_seconds = timeout_seconds

    def __repr__(self) -> str:
        return f"ResponsesProvider(model={self.model!r}, base_url_host={urlsplit(self.base_url).hostname!r})"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            streaming=True,
            structured_output=True,
            function_tools=True,
            hosted_web_search=True,
        )

    def snapshot(self) -> dict[str, str]:
        return {"type": "responses", "model": self.model, "base_url_host": urlsplit(self.base_url).hostname or ""}

    async def stream(
        self, messages: Sequence[ModelMessage], tools: Sequence[ToolDefinition], options: Mapping[str, Any]
    ) -> AsyncIterator[ProviderStreamEvent]:
        payload = build_request_payload(model=self.model, messages=messages, tools=tools, options=options)
        lines: list[str] | None = None
        # Respect the workflow's retry budget.  Blueprint design and other
        # short routing turns explicitly use one attempt; a fixed three-turn
        # replay here silently multiplied their latency and made a single
        # transient gateway stall look like a model long-tail.
        try:
            retry_attempts = max(
                1,
                min(3, int(options.get("_provider_retry_attempts", 3))),
            )
        except (TypeError, ValueError):
            retry_attempts = 3
        requested_timeout = options.get("_provider_timeout_seconds")
        call_timeout: float | None = None
        if (
            not bool(options.get("_disable_provider_timeout", False))
            and requested_timeout is not None
        ):
            try:
                call_timeout = max(1.0, float(requested_timeout))
            except (TypeError, ValueError):
                call_timeout = None
        for attempt in range(retry_attempts):
            try:
                post_call = asyncio.to_thread(
                    self._post_for_options,
                    payload,
                    options,
                )
                if call_timeout is None:
                    lines = await post_call
                else:
                    # urllib's timeout applies to an individual socket read;
                    # an SSE stream can otherwise keep a small routing turn
                    # alive indefinitely.  Enforce the workflow's total
                    # provider-call budget at the async boundary as well.
                    lines = await asyncio.wait_for(post_call, timeout=call_timeout)
                break
            except asyncio.TimeoutError as exc:
                raise ProviderRetryableError(
                    f"Responses request timed out after {call_timeout:g} seconds"
                ) from exc
            except ProviderRetryableError:
                if attempt + 1 >= retry_attempts:
                    raise
                await asyncio.sleep(2 ** attempt)
        assert lines is not None
        events: list[tuple[str, Mapping[str, Any]]] = []
        for frame in iter_sse_frames(lines):
            parsed = parse_sse_frame(frame)
            if parsed is None:
                continue
            kind, event = parsed
            events.append((kind, event))
            if kind == "response.output_text.delta":
                yield ProviderStreamEvent.text_delta(str(event.get("delta", "")))
            elif kind in {"response.reasoning_summary_text.delta", "response.reasoning_text.delta"}:
                yield ProviderStreamEvent.reasoning_delta(str(event.get("delta", "")))
        yield ProviderStreamEvent.final(assistant_from_events(events))

    def _post_for_options(
        self, payload: Mapping[str, Any], options: Mapping[str, Any]
    ) -> list[str]:
        """Apply workflow-level timeout policy without changing direct callers.

        Reporter delivery explicitly opts out of a wall-clock cutoff. Other
        Responses calls retain the provider's normal transport timeout.
        Keeping the default path as a one-argument ``_post`` call preserves
        the small injection seam used by tests and embedders.
        """

        post_kwargs: dict[str, Any] = {}
        if bool(options.get("_disable_provider_timeout", False)):
            post_kwargs["disable_timeout"] = True
        else:
            requested = options.get("_provider_timeout_seconds")
            if requested is not None:
                try:
                    ceiling = float(self.timeout_seconds)
                    if bool(options.get("_allow_extended_provider_timeout", False)):
                        try:
                            configured_ceiling = float(
                                os.environ.get(
                                    "EQUIPMENT_DR_BLUEPRINT_MAX_TIMEOUT_SECONDS",
                                    "180",
                                )
                            )
                        except (TypeError, ValueError):
                            configured_ceiling = 180.0
                        ceiling = max(ceiling, configured_ceiling)
                    post_kwargs["timeout_seconds"] = max(
                        1.0,
                        min(ceiling, float(requested)),
                    )
                except (TypeError, ValueError):
                    post_kwargs["timeout_seconds"] = float(self.timeout_seconds)
        try:
            return self._post(payload, **post_kwargs)
        except ProviderRequestError as exc:
            if not _can_downgrade_optional_web_search(exc, options):
                raise
            # Search is an enrichment path for these workflows.  A gateway
            # that rejects the optional tool can still complete the same
            # contract without silently losing the whole discovery lane.
            return self._post(_without_optional_web_search(payload), **post_kwargs)

    def _post(
        self,
        payload: Mapping[str, Any],
        *,
        timeout_seconds: float | None = None,
        disable_timeout: bool = False,
    ) -> list[str]:
        request = Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "text/event-stream", "Authorization": f"Bearer {self._api_key}"},
            method="POST",
        )
        try:
            request_timeout = (
                None
                if disable_timeout
                else self.timeout_seconds
                if timeout_seconds is None
                else timeout_seconds
            )
            with urlopen(request, timeout=request_timeout) as response:  # nosec B310: HTTPS validated at construction
                lines: list[str] = []
                frame: list[str] = []

                def _is_terminal(data: str) -> bool:
                    try:
                        parsed = parse_sse_frame(data)
                    except ProviderRequestError:
                        return False
                    return parsed is not None and parsed[0] in {
                        "response.completed",
                        "response.failed",
                        "response.incomplete",
                    }

                for raw_line in response:
                    line = raw_line.decode("utf-8")
                    lines.append(line)
                    stripped = line.rstrip("\r\n")
                    if stripped.startswith("data:"):
                        value = stripped[5:].lstrip(" ")
                        if value.strip() == "[DONE]":
                            break
                        # 常见情况：单行即完整事件，立即检测终止事件。
                        if _is_terminal(value):
                            break
                        frame.append(value)
                        continue
                    if stripped:
                        continue
                    # 空行为帧边界：检测跨行拼接后的终止事件。
                    if frame and len(frame) > 1 and _is_terminal("\n".join(frame)):
                        frame = []
                        break
                    frame = []
                return lines
        except HTTPError as exc:
            request_id = exc.headers.get("x-request-id", "") if exc.headers else ""
            message = f"Responses request failed: status={exc.code} request_id={request_id}".strip()
            if exc.code == 401:
                raise ProviderAuthenticationError(message) from exc
            if exc.code == 429 or exc.code >= 500:
                raise ProviderRetryableError(message) from exc
            raise ProviderRequestError(message) from exc
        except (URLError, TimeoutError, RemoteDisconnected) as exc:
            raise ProviderRetryableError("Responses network request failed") from exc


def _message_to_response_input(message: ModelMessage) -> dict[str, Any]:
    content = thaw_plain(message.content)
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    return {"role": message.role, "content": content}


__all__ = [
    "ProviderAuthenticationError", "ProviderRequestError", "ProviderCapacityError", "ProviderRetryableError",
    "ResponsesProvider", "assistant_from_events", "build_request_payload",
    "iter_sse_frames", "parse_sse_event", "parse_sse_frame",
]
