"""Responses-compatible HTTPS/SSE model provider.

The provider only translates model events. Tool execution remains exclusively
inside the Harness, so credentials and network authority never leak to agents.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

from equipment_deep_research.providers.base import (
    ModelMessage,
    ProviderFinalTurn,
    ProviderStreamEvent,
    ProviderToolCall,
)
from equipment_deep_research.tools.definitions import ToolDefinition


class ProviderAuthenticationError(RuntimeError):
    pass


class ProviderRetryableError(RuntimeError):
    pass


class ProviderRequestError(RuntimeError):
    pass


def build_request_payload(
    *, model: str, messages: Sequence[ModelMessage], tools: Sequence[ToolDefinition], options: Mapping[str, Any]
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "input": [_message_to_response_input(message) for message in messages],
        "stream": True,
    }
    if tools:
        payload["tools"] = [
            {"type": "function", "name": tool.name, "description": tool.description, "parameters": dict(tool.input_schema)}
            for tool in tools
        ]
    effort = options.get("reasoning_effort")
    if effort:
        payload["reasoning"] = {"effort": effort}
    if "max_output_tokens" in options:
        payload["max_output_tokens"] = options["max_output_tokens"]
    return payload


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


def assistant_from_events(events: Iterable[tuple[str, Mapping[str, Any]]]) -> ProviderFinalTurn:
    text: list[str] = []
    reasoning: list[str] = []
    calls: dict[str, dict[str, Any]] = {}
    final_payload: Mapping[str, Any] = {}
    for kind, event in events:
        if kind in {"response.output_text.delta", "response.output_text.done"}:
            text.append(str(event.get("delta", event.get("text", ""))))
        elif kind in {"response.reasoning_summary_text.delta", "response.reasoning_text.delta"}:
            reasoning.append(str(event.get("delta", "")))
        elif kind in {"response.function_call_arguments.delta", "response.function_call_arguments.done"}:
            item_id = str(event.get("item_id", event.get("call_id", "")))
            current = calls.setdefault(item_id, {"name": event.get("name", ""), "arguments": ""})
            if event.get("name"):
                current["name"] = event["name"]
            current["arguments"] += str(event.get("delta", event.get("arguments", "")))
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
    return ProviderFinalTurn(
        text="".join(text) or None,
        tool_calls=tool_calls or None,
        finish_reason=str(final_payload.get("status", "completed")),
        usage=usage if isinstance(usage, Mapping) else {},
        metadata={"reasoning": "".join(reasoning)},
    )


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

    def snapshot(self) -> dict[str, str]:
        return {"type": "responses", "model": self.model, "base_url_host": urlsplit(self.base_url).hostname or ""}

    async def stream(
        self, messages: Sequence[ModelMessage], tools: Sequence[ToolDefinition], options: Mapping[str, Any]
    ) -> AsyncIterator[ProviderStreamEvent]:
        payload = build_request_payload(model=self.model, messages=messages, tools=tools, options=options)
        lines = await asyncio.to_thread(self._post, payload)
        events: list[tuple[str, Mapping[str, Any]]] = []
        for line in lines:
            parsed = parse_sse_event(line)
            if parsed is None:
                continue
            kind, event = parsed
            events.append((kind, event))
            if kind == "response.output_text.delta":
                yield ProviderStreamEvent.text_delta(str(event.get("delta", "")))
            elif kind in {"response.reasoning_summary_text.delta", "response.reasoning_text.delta"}:
                yield ProviderStreamEvent.reasoning_delta(str(event.get("delta", "")))
        yield ProviderStreamEvent.final(assistant_from_events(events))

    def _post(self, payload: Mapping[str, Any]) -> list[str]:
        request = Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "text/event-stream", "Authorization": f"Bearer {self._api_key}"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # nosec B310: HTTPS validated at construction
                return [line.decode("utf-8") for line in response.readlines()]
        except HTTPError as exc:
            request_id = exc.headers.get("x-request-id", "") if exc.headers else ""
            message = f"Responses request failed: status={exc.code} request_id={request_id}".strip()
            if exc.code == 401:
                raise ProviderAuthenticationError(message) from exc
            if exc.code == 429 or exc.code >= 500:
                raise ProviderRetryableError(message) from exc
            raise ProviderRequestError(message) from exc
        except URLError as exc:
            raise ProviderRetryableError("Responses network request failed") from exc


def _message_to_response_input(message: ModelMessage) -> dict[str, Any]:
    content = message.content
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    return {"role": message.role, "content": content}


__all__ = [
    "ProviderAuthenticationError", "ProviderRequestError", "ProviderRetryableError",
    "ResponsesProvider", "assistant_from_events", "build_request_payload", "parse_sse_event",
]
