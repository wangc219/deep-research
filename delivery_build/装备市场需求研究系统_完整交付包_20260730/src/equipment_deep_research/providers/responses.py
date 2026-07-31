"""Responses-compatible HTTPS/SSE model provider.

The provider only translates model events. Tool execution remains exclusively
inside the Harness, so credentials and network authority never leak to agents.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from http.client import RemoteDisconnected
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
from equipment_deep_research.domain.proposals import thaw_plain
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
    declared_tools: list[dict[str, Any]] = []
    web_search = options.get("web_search")
    if isinstance(web_search, Mapping):
        declared_tools.append({"type": "web_search", **thaw_plain(web_search)})
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
        payload["tool_choice"] = {"type": "web_search"}
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

    def snapshot(self) -> dict[str, str]:
        return {"type": "responses", "model": self.model, "base_url_host": urlsplit(self.base_url).hostname or ""}

    async def stream(
        self, messages: Sequence[ModelMessage], tools: Sequence[ToolDefinition], options: Mapping[str, Any]
    ) -> AsyncIterator[ProviderStreamEvent]:
        payload = build_request_payload(model=self.model, messages=messages, tools=tools, options=options)
        lines: list[str] | None = None
        for attempt in range(3):
            try:
                lines = await asyncio.to_thread(self._post, payload)
                break
            except ProviderRetryableError:
                if attempt == 2:
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

    def _post(self, payload: Mapping[str, Any]) -> list[str]:
        request = Request(
            self.base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "text/event-stream", "Authorization": f"Bearer {self._api_key}"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # nosec B310: HTTPS validated at construction
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
    "ProviderAuthenticationError", "ProviderRequestError", "ProviderRetryableError",
    "ResponsesProvider", "assistant_from_events", "build_request_payload",
    "iter_sse_frames", "parse_sse_event", "parse_sse_frame",
]
