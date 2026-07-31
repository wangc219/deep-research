"""Responses-compatible request builders and SSE event mapping."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterable
import json
import threading
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from knowledgegraph.demand_discovery.harness.cancellation import RunCancelled
from knowledgegraph.demand_discovery.harness.event_stream import AsyncEventStream
from knowledgegraph.demand_discovery.harness.types import AssistantContentBlock
from knowledgegraph.demand_discovery.harness.tools import ToolDefinition
from knowledgegraph.demand_discovery.llm.model_config import ModelConfig
from knowledgegraph.demand_discovery.llm.types import (
    AssistantMessage,
    LLMContext,
    ProviderEvent,
)


ProviderTransport = Callable[[dict[str, Any], int], Iterable[str]]


class ResponsesProvider:
    """Provider runtime for Responses-compatible SSE endpoints.

    The adapter builds a sanitized internal request through the existing request
    builders, performs HTTP POST with SSE response parsing, and returns the
    normalized assistant message expected by ``AgentLoop``. Tests can inject a
    local transport to avoid external network calls.
    """

    def __init__(
        self,
        config: ModelConfig,
        api_key: str,
        transport: ProviderTransport | None = None,
    ) -> None:
        self._config = config
        self._api_key = api_key
        self._transport = transport or _default_sse_transport

    def stream(
        self,
        context: LLMContext,
        tools: list[ToolDefinition],
        options: dict[str, Any],
    ) -> AsyncEventStream:
        stream = AsyncEventStream()
        asyncio.ensure_future(self._run(stream, context, tools, options))
        return stream

    async def _run(
        self,
        stream: AsyncEventStream,
        context: LLMContext,
        tools: list[ToolDefinition],
        options: dict[str, Any],
    ) -> None:
        stream.push(ProviderEvent("start", {}))
        cancel_token = options.get("cancel_token")
        request_options = {**dict(options), "api_key": self._api_key}
        request = build_provider_request(self._config, context, tools, request_options)

        try:
            _raise_if_cancelled(cancel_token)
            events: list[ProviderEvent] = []
            async for event in self._send_streaming_with_retries(request):
                _raise_if_cancelled(cancel_token)
                events.append(event)
                stream.push(event)
                if event.type == "error":
                    stream.error(str(event.payload.get("message", "provider error")))
                    return
                if event.type == "done":
                    stream.end(_assistant_from_events(events))
                    return
            stream.end(_assistant_from_events(events))
        except RunCancelled as exc:
            stream.end(
                AssistantMessage(
                    content=[],
                    is_error=True,
                    error_message=str(exc),
                )
            )
        except Exception as exc:
            stream.error(str(exc))
            return

    async def _send_with_retries(self, request: dict[str, Any]) -> list[str]:
        last_error: Exception | None = None
        cancel_token = request.get("options", {}).get("cancel_token")
        attempts = max(0, self._config.max_retries) + 1
        for attempt in range(attempts):
            try:
                _raise_if_cancelled(cancel_token)
                return await asyncio.to_thread(
                    lambda: list(self._transport(request, self._config.timeout_ms))
                )
            except Exception as exc:
                _raise_if_cancelled(cancel_token)
                last_error = exc
                if attempt + 1 >= attempts:
                    break
                await asyncio.sleep(min(0.25 * (attempt + 1), 1.0))
                _raise_if_cancelled(cancel_token)
        assert last_error is not None
        raise last_error

    async def _send_streaming_with_retries(
        self, request: dict[str, Any]
    ) -> AsyncIterator[ProviderEvent]:
        last_error: Exception | None = None
        cancel_token = request.get("options", {}).get("cancel_token")
        attempts = max(0, self._config.max_retries) + 1
        for attempt in range(attempts):
            yielded_event = False
            try:
                _raise_if_cancelled(cancel_token)
                async for event in self._stream_events_once(request):
                    yielded_event = True
                    yield event
                    if event.type in ("done", "error"):
                        return
                return
            except _TransportStreamError as exc:
                _raise_if_cancelled(cancel_token)
                last_error = exc.original
                if yielded_event or attempt + 1 >= attempts:
                    raise exc.original
            except Exception as exc:
                _raise_if_cancelled(cancel_token)
                last_error = exc
                if yielded_event or attempt + 1 >= attempts:
                    raise
            await asyncio.sleep(min(0.25 * (attempt + 1), 1.0))
            _raise_if_cancelled(cancel_token)
        assert last_error is not None
        raise last_error

    async def _stream_events_once(
        self, request: dict[str, Any]
    ) -> AsyncIterator[ProviderEvent]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        stop_reading = threading.Event()

        def put(item: tuple[str, Any]) -> None:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, item)
            except RuntimeError:
                return

        def worker() -> None:
            started = False
            try:
                for line in self._transport(request, self._config.timeout_ms):
                    if stop_reading.is_set():
                        break
                    started = True
                    put(("line", line))
                put(("eof", None))
            except Exception as exc:
                put(("error", {"error": exc, "started": started}))

        worker_task = asyncio.create_task(asyncio.to_thread(worker))
        parser = _SSEParser()
        try:
            while True:
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=0.05)
                except TimeoutError:
                    _raise_if_cancelled(request.get("options", {}).get("cancel_token"))
                    continue
                if kind == "line":
                    for event in parser.feed_line(str(payload)):
                        yield event
                        if event.type in ("done", "error"):
                            stop_reading.set()
                            return
                elif kind == "eof":
                    for event in parser.finish():
                        yield event
                    return
                elif kind == "error":
                    raise _TransportStreamError(
                        payload["error"], started=bool(payload.get("started"))
                    )
        finally:
            stop_reading.set()
            worker_task.add_done_callback(_discard_task_exception)


def build_provider_request(
    config: ModelConfig,
    context: LLMContext,
    tools: list[ToolDefinition],
    options: dict[str, Any],
) -> dict[str, Any]:
    # Legacy configurations are normalized to the supported Responses API.
    # The former Codex backend transport is intentionally not reachable.
    return build_responses_request(config, context, tools, options)


def build_responses_request(
    config: ModelConfig,
    context: LLMContext,
    tools: list[ToolDefinition],
    options: dict[str, Any],
) -> dict[str, Any]:
    """Build a standard `/v1/responses` or custom endpoint request."""

    url = _endpoint_url(config)
    headers = dict(config.headers)
    api_key = options.get("api_key", "")
    if api_key:
        headers[config.auth_header] = (
            f"Bearer {api_key}" if config.auth_header.lower() == "authorization" else api_key
        )
    payload = _base_payload(config, context, tools, options)
    return {"url": url, "headers": headers, "payload": payload, "options": dict(options)}


def build_codex_request(
    config: ModelConfig,
    context: LLMContext,
    tools: list[ToolDefinition],
    options: dict[str, Any],
) -> dict[str, Any]:
    """Build a ChatGPT Codex backend style request."""

    headers = {
        **dict(config.headers),
        "OpenAI-Beta": "responses=experimental",
        "originator": "demand-discovery",
    }
    api_key = options.get("api_key", "")
    if api_key:
        headers[config.auth_header] = (
            f"Bearer {api_key}" if config.auth_header.lower() == "authorization" else api_key
        )
    return {
        "url": _codex_url(config.base_url, config.endpoint_path),
        "headers": headers,
        "payload": _base_payload(config, context, tools, options),
        "options": dict(options),
    }


def parse_sse_lines(lines: list[str]) -> list[ProviderEvent]:
    """Parse SSE lines into provider events, stopping on completion/error."""

    parser = _SSEParser()
    events: list[ProviderEvent] = []
    for raw in lines:
        events.extend(parser.feed_line(raw))
        if events_has_terminal(events):
            break
    if not events_has_terminal(events):
        events.extend(parser.finish())
    return events


def map_responses_event(raw: dict[str, Any]) -> ProviderEvent:
    event_type = raw.get("type", "")
    if event_type in ("response.output_text.delta", "response.text.delta"):
        return ProviderEvent("text_delta", {"text": raw.get("delta", "")})
    if event_type in (
        "response.reasoning_summary_text.delta",
        "response.reasoning_text.delta",
    ):
        return ProviderEvent("thinking_delta", {"text": raw.get("delta", "")})
    if event_type == "response.output_item.done":
        item = dict(raw.get("item", {}) or {})
        if item.get("type") == "function_call":
            return ProviderEvent(
                "toolcall_delta",
                {
                    "id": item.get("call_id") or item.get("id", ""),
                    "name": item.get("name", ""),
                    "arguments": _parse_arguments(item.get("arguments", {})),
                },
            )
    if event_type == "response.completed":
        response = dict(raw.get("response", {}) or {})
        usage = raw.get("usage") or response.get("usage") or {}
        return ProviderEvent("done", {"usage": _normalize_usage(dict(usage))})
    if event_type == "response.failed":
        error = dict(raw.get("error", {}) or {})
        return ProviderEvent("error", {"message": error.get("message", "failed")})
    return ProviderEvent("unknown", {"raw": raw})


def events_has_terminal(events: list[ProviderEvent]) -> bool:
    return any(event.type in ("done", "error") for event in events)


class _SSEParser:
    """Incremental SSE parser with stateful function-call assembly."""

    def __init__(self) -> None:
        self._data_lines: list[str] = []
        self._tool_states: dict[str, dict[str, Any]] = {}
        self._terminal = False

    def feed_line(self, raw: str) -> list[ProviderEvent]:
        if self._terminal:
            return []
        line = raw.strip()
        if not line:
            event = _flush_sse_data(self._data_lines, self._tool_states)
            self._data_lines = []
            return self._events_for(event)
        if line.startswith("data:"):
            self._data_lines.append(line.removeprefix("data:").strip())
        return []

    def finish(self) -> list[ProviderEvent]:
        if self._terminal:
            return []
        events = self._events_for(
            _flush_sse_data(self._data_lines, self._tool_states)
        )
        self._data_lines = []
        if not self._terminal:
            events.extend(_pending_tool_call_events(self._tool_states))
        return events

    def _events_for(self, event: ProviderEvent | None) -> list[ProviderEvent]:
        if event is None:
            return []
        if event.type == "done":
            self._terminal = True
            return [*_pending_tool_call_events(self._tool_states), event]
        if event.type == "error":
            self._terminal = True
        return [event]


class _TransportStreamError(RuntimeError):
    def __init__(self, original: Exception, *, started: bool) -> None:
        super().__init__(str(original))
        self.original = original
        self.started = started


def _discard_task_exception(task: asyncio.Task) -> None:
    try:
        task.exception()
    except asyncio.CancelledError:
        return


def _raise_if_cancelled(cancel_token: Any) -> None:
    if cancel_token is not None and hasattr(cancel_token, "raise_if_cancelled"):
        cancel_token.raise_if_cancelled()


def _base_payload(
    config: ModelConfig,
    context: LLMContext,
    tools: list[ToolDefinition],
    options: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": config.model,
        "input": _messages_to_payload(context.messages),
        "tools": [_tool_to_payload(tool) for tool in tools],
        "stream": True,
    }
    if "parallel_tool_calls" in options:
        payload["parallel_tool_calls"] = bool(options["parallel_tool_calls"])
    verbosity = options.get("text_verbosity") or config.text_verbosity
    text_options: dict[str, Any] = {}
    if verbosity:
        text_options["verbosity"] = verbosity
    output_schema = options.get("output_schema")
    if isinstance(output_schema, dict):
        text_options["format"] = {
            "type": "json_schema",
            "name": _schema_name(str(options.get("output_schema_name", ""))),
            "schema": dict(output_schema),
            "strict": bool(options.get("output_schema_strict", False)),
        }
    if text_options:
        payload["text"] = text_options
    effort = options.get("reasoning_effort") or config.reasoning_effort
    summary = options.get("reasoning_summary") or config.reasoning_summary
    if effort or summary:
        payload["reasoning"] = {}
        if effort:
            payload["reasoning"]["effort"] = effort
        if summary:
            payload["reasoning"]["summary"] = summary
    return payload


def _schema_name(name: str) -> str:
    normalized = "".join(ch if ch.isalnum() else "_" for ch in name.strip().lower())
    normalized = "_".join(part for part in normalized.split("_") if part)
    return normalized or "demand_discovery_output"


def _messages_to_payload(messages: list[Any]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for message in messages:
        payload.extend(_message_to_payload_items(message))
    return payload


def _message_to_payload_items(message: Any) -> list[dict[str, Any]]:
    role = getattr(message, "role", "user")
    content = getattr(message, "content", "")
    if role == "tool_result":
        return [
            {
                "type": "function_call_output",
                "call_id": getattr(message, "tool_call_id", ""),
                "output": str(content),
            }
        ]
    if isinstance(content, list):
        items: list[dict[str, Any]] = []
        text = "".join(
            getattr(block, "text", "")
            for block in content
            if getattr(block, "type", "") == "text"
        )
        if text:
            items.append({"role": role, "content": text})
        for block in content:
            if getattr(block, "type", "") != "tool_call":
                continue
            items.append(
                {
                    "type": "function_call",
                    "call_id": getattr(block, "id", ""),
                    "name": getattr(block, "name", ""),
                    "arguments": json.dumps(dict(getattr(block, "arguments", {}) or {})),
                }
            )
        return items
    else:
        text = str(content)
    return [{"role": role, "content": text}]


def _tool_to_payload(tool: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": dict(tool.parameters_schema),
    }


def _endpoint_url(config: ModelConfig) -> str:
    if config.endpoint_mode == "custom_endpoint":
        return _join_url(config.base_url, config.endpoint_path)
    return _join_url(config.base_url, "/v1/responses")


def _codex_url(base_url: str, endpoint_path: str = "") -> str:
    if endpoint_path:
        return _join_url(base_url, endpoint_path)
    normalized = base_url.rstrip("/")
    if normalized.endswith("/codex/responses") or normalized.endswith("/v1/responses"):
        return normalized
    parsed = urlparse(normalized)
    if parsed.path in ("", "/"):
        return _join_url(normalized, "/v1/responses")
    return f"{normalized}/codex/responses"


def _join_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if not path:
        return base
    if path.startswith("/"):
        root = base.split("/", 3)
        if len(root) >= 3:
            return f"{root[0]}//{root[2]}{path}"
    return f"{base}/{path.lstrip('/')}"


def _flush_sse_data(
    data_lines: list[str],
    tool_states: dict[str, dict[str, Any]] | None = None,
) -> ProviderEvent | None:
    if not data_lines:
        return None
    raw_text = "\n".join(data_lines)
    if raw_text == "[DONE]":
        return ProviderEvent("done", {})
    raw = json.loads(raw_text)
    if tool_states is not None:
        return _map_responses_event_stateful(raw, tool_states)
    return map_responses_event(raw)


def _map_responses_event_stateful(
    raw: dict[str, Any],
    tool_states: dict[str, dict[str, Any]],
) -> ProviderEvent | None:
    event_type = raw.get("type", "")
    if event_type == "response.output_item.added":
        item = dict(raw.get("item", {}) or {})
        if item.get("type") == "function_call":
            _update_tool_state(_tool_state_for(tool_states, raw, item), item)
            return None
    if event_type == "response.function_call_arguments.delta":
        state = _tool_state_for(tool_states, raw, {})
        state["arguments_text"] = str(state.get("arguments_text", "")) + str(
            raw.get("delta", "")
        )
        state["saw_arguments"] = True
        return None
    if event_type == "response.function_call_arguments.done":
        state = _tool_state_for(tool_states, raw, {})
        state["arguments_text"] = str(
            raw.get("arguments", state.get("arguments_text", ""))
        )
        state["arguments"] = _parse_arguments(state.get("arguments_text", ""))
        state["saw_arguments"] = True
        state["arguments_complete"] = True
        return None
    if event_type == "response.output_item.done":
        item = dict(raw.get("item", {}) or {})
        if item.get("type") == "function_call":
            state = _tool_state_for(tool_states, raw, item)
            _update_tool_state(state, item)
            if "arguments" in item:
                state["arguments"] = _parse_arguments(item.get("arguments", {}))
                state["saw_arguments"] = True
                state["arguments_complete"] = True
            return _tool_event_from_state(state, force=True)
    return map_responses_event(raw)


def _tool_state_for(
    tool_states: dict[str, dict[str, Any]],
    raw: dict[str, Any],
    item: dict[str, Any],
) -> dict[str, Any]:
    keys = _tool_state_keys(raw, item)
    state: dict[str, Any] | None = None
    for key in keys:
        if key in tool_states:
            state = tool_states[key]
            break
    if state is None:
        state = {}
    for key in keys:
        tool_states[key] = state
    return state


def _tool_state_keys(raw: dict[str, Any], item: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    item_id = raw.get("item_id") or item.get("id")
    if item_id:
        keys.append(f"item:{item_id}")
    call_id = item.get("call_id")
    if call_id:
        keys.append(f"call:{call_id}")
    if raw.get("output_index") is not None:
        keys.append(f"index:{raw.get('output_index')}")
    return keys or [f"raw:{id(raw)}"]


def _update_tool_state(state: dict[str, Any], item: dict[str, Any]) -> None:
    call_id = item.get("call_id") or item.get("id")
    if call_id:
        state["id"] = call_id
    if item.get("name"):
        state["name"] = item.get("name")


def _pending_tool_call_events(
    tool_states: dict[str, dict[str, Any]],
) -> list[ProviderEvent]:
    events: list[ProviderEvent] = []
    seen: set[int] = set()
    for state in tool_states.values():
        state_identity = id(state)
        if state_identity in seen:
            continue
        seen.add(state_identity)
        event = _tool_event_from_state(state, force=False)
        if event is not None:
            events.append(event)
    return events


def _tool_event_from_state(
    state: dict[str, Any],
    force: bool,
) -> ProviderEvent | None:
    if state.get("emitted"):
        return None
    if not force and not state.get("saw_arguments"):
        return None
    call_id = str(state.get("id", ""))
    name = str(state.get("name", ""))
    if not call_id or not name:
        return None
    if "arguments" not in state:
        state["arguments"] = _parse_arguments(state.get("arguments_text", ""))
    state["emitted"] = True
    return ProviderEvent(
        "toolcall_delta",
        {
            "id": call_id,
            "name": name,
            "arguments": dict(state.get("arguments", {}) or {}),
        },
    )


def _parse_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value:
        return json.loads(value)
    return {}


def _normalize_usage(usage: dict[str, Any]) -> dict[str, Any]:
    plural = usage.get("input_tokens_details")
    singular = usage.get("input_token_details")
    if isinstance(plural, dict) and not isinstance(singular, dict):
        usage["input_token_details"] = dict(plural)
    if isinstance(singular, dict) and not isinstance(plural, dict):
        usage["input_tokens_details"] = dict(singular)
    return usage


def _assistant_from_events(events: list[ProviderEvent]) -> AssistantMessage:
    text_parts: list[str] = []
    tool_blocks: list[AssistantContentBlock] = []
    seen_tool_ids: set[str] = set()
    usage: dict[str, Any] = {}

    for event in events:
        if event.type == "text_delta":
            text_parts.append(str(event.payload.get("text", "")))
        elif event.type == "toolcall_delta":
            call_id = str(event.payload.get("id", ""))
            name = str(event.payload.get("name", ""))
            if call_id and call_id not in seen_tool_ids:
                seen_tool_ids.add(call_id)
                tool_blocks.append(
                    AssistantContentBlock(
                        type="tool_call",
                        id=call_id,
                        name=name,
                        arguments=dict(event.payload.get("arguments", {}) or {}),
                    )
                )
        elif event.type == "done":
            usage = dict(event.payload.get("usage", {}) or {})

    content: list[AssistantContentBlock] = []
    text = "".join(text_parts)
    if text:
        content.append(AssistantContentBlock(type="text", text=text))
    content.extend(tool_blocks)
    return AssistantMessage(content=content, usage=usage)


def _default_sse_transport(request: dict[str, Any], timeout_ms: int) -> Iterable[str]:
    payload = json.dumps(request["payload"]).encode("utf-8")
    headers = {
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        **dict(request.get("headers", {})),
    }
    http_request = urlrequest.Request(
        str(request["url"]),
        data=payload,
        headers=headers,
        method="POST",
    )
    timeout_seconds = max(timeout_ms / 1000, 1)
    try:
        with urlrequest.urlopen(http_request, timeout=timeout_seconds) as response:
            for raw_line in response:
                yield raw_line.decode("utf-8", errors="replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        detail = f": {body[:1000]}" if body else ""
        url = str(request.get("url", ""))
        hint = ""
        if exc.code == 404:
            hint = (
                f" (requested URL: {url}; if this is an OpenAI-compatible proxy, "
                "use --endpoint-mode responses_compatible or set "
                "--endpoint-path /v1/responses)"
            )
        raise RuntimeError(
            f"provider request failed with HTTP {exc.code}{detail}{hint}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"provider request failed: {exc.reason}") from exc
