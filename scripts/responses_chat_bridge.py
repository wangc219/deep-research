#!/usr/bin/env python3
"""Generic local Responses-to-Chat-Completions bridge for Codex CLI.

Codex CLI speaks the OpenAI Responses wire protocol.  Many providers expose
the otherwise equivalent Chat Completions protocol.  This process translates
between the two without making the orchestration layer provider-specific.
Configure the upstream with ``EQUIPMENT_DR_BRIDGE_*`` environment variables.
"""

from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


HOST = os.environ.get("EQUIPMENT_DR_BRIDGE_HOST", os.environ.get("DEEPSEEK_BRIDGE_HOST", "127.0.0.1"))
PORT = int(os.environ.get("EQUIPMENT_DR_BRIDGE_PORT", os.environ.get("DEEPSEEK_BRIDGE_PORT", "8787")))
UPSTREAM_URL = os.environ.get(
    "EQUIPMENT_DR_BRIDGE_UPSTREAM_URL",
    os.environ.get("EQUIPMENT_DR_DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1/chat/completions"),
).strip()
UPSTREAM_KEY_ENV = os.environ.get(
    "EQUIPMENT_DR_BRIDGE_API_KEY_ENV",
    os.environ.get("EQUIPMENT_DR_DEEPSEEK_API_KEY_ENV", "DEEPSEEK_API_KEY"),
).strip()
API_KEY = os.environ.get(UPSTREAM_KEY_ENV, os.environ.get("DEEPSEEK_API_KEY", "")).strip()
MODEL = os.environ.get(
    "EQUIPMENT_DR_BRIDGE_MODEL",
    os.environ.get("EQUIPMENT_DR_DEEPSEEK_MODEL", ""),
).strip()
THINKING = os.environ.get("EQUIPMENT_DR_BRIDGE_THINKING", "").strip().lower()
try:
    TOKEN_RESERVE = max(0, int(os.environ.get("EQUIPMENT_DR_BRIDGE_REASONING_RESERVE_TOKENS", "4096")))
except (TypeError, ValueError):
    TOKEN_RESERVE = 4096
try:
    MAX_UPSTREAM_TOKENS = max(1024, int(os.environ.get("EQUIPMENT_DR_BRIDGE_MAX_UPSTREAM_TOKENS", "32768")))
except (TypeError, ValueError):
    MAX_UPSTREAM_TOKENS = 32768


def _messages(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return [{"role": "user", "content": str(value or "")}]
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type", ""))
        if item_type == "function_call_output":
            result.append(
                {
                    "role": "tool",
                    "tool_call_id": str(item.get("call_id", "")),
                    "content": str(item.get("output", "")),
                }
            )
            continue
        if item_type == "function_call":
            arguments = item.get("arguments", "{}")
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments, ensure_ascii=False)
            result.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": str(item.get("call_id", item.get("id", ""))),
                            "type": "function",
                            "function": {
                                "name": str(item.get("name", "")),
                                "arguments": arguments,
                            },
                        }
                    ],
                }
            )
            continue
        role = str(item.get("role", "user"))
        if role == "developer":
            role = "system"
        if role == "assistant" and isinstance(item.get("tool_calls"), list):
            result.append(
                {
                    "role": "assistant",
                    "content": item.get("content"),
                    "tool_calls": item["tool_calls"],
                }
            )
            continue
        content = item.get("content", item.get("input", ""))
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("text") is not None:
                    parts.append(str(part["text"]))
                elif part.get("content") is not None:
                    parts.append(str(part["content"]))
            content = "\n".join(parts)
        result.append({"role": role, "content": str(content)})
    return result or [{"role": "user", "content": ""}]


def _request_payload(payload: dict[str, Any]) -> dict[str, Any]:
    request: dict[str, Any] = {
        "model": str(payload.get("model") or MODEL),
        "messages": _messages(payload.get("input", payload.get("messages", []))),
        "stream": False,
    }
    if payload.get("max_output_tokens") is not None:
        # Responses max_output_tokens describes visible output, while many
        # reasoning models also charge hidden thinking tokens to the upstream
        # Chat Completions max_tokens. Reserve room for both budgets.
        request["max_tokens"] = min(
            MAX_UPSTREAM_TOKENS,
            int(payload["max_output_tokens"]) + TOKEN_RESERVE,
        )
    # Reasoning-capable upstreams may spend the entire max_tokens budget on
    # hidden reasoning, leaving structured JSON truncated.  This remains an
    # opt-in, provider-neutral setting because not every upstream supports it.
    if THINKING in {"enabled", "disabled"}:
        request["thinking"] = {"type": THINKING}
    tools: list[dict[str, Any]] = []
    for tool in payload.get("tools", []) if isinstance(payload.get("tools"), list) else []:
        if not isinstance(tool, dict):
            continue
        if isinstance(tool.get("function"), dict):
            tools.append(tool)
        elif str(tool.get("type", "")) == "function" and tool.get("name"):
            tools.append({"type": "function", "function": {
                "name": str(tool["name"]),
                "description": str(tool.get("description", "")),
                "parameters": tool.get("parameters", {"type": "object"}),
            }})
    if tools:
        request["tools"] = tools
    if isinstance(payload.get("tool_choice"), (str, dict)):
        request["tool_choice"] = payload["tool_choice"]
    # Preserve the structured-output intent when the upstream supports the
    # Chat Completions response_format field.  Providers that do not support
    # it can opt out with EQUIPMENT_DR_BRIDGE_STRUCTURED_OUTPUT=0.
    text_config = payload.get("text")
    if os.environ.get("EQUIPMENT_DR_BRIDGE_STRUCTURED_OUTPUT", "1") == "1" and isinstance(text_config, dict):
        fmt = text_config.get("format")
        if isinstance(fmt, dict):
            if fmt.get("type") in {"json_schema", "json_object"}:
                request["response_format"] = {"type": "json_object"}
    return request


def _usage(value: Any) -> dict[str, int]:
    usage = value if isinstance(value, dict) else {}
    inp = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
    out = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
    return {"input_tokens": inp, "output_tokens": out, "total_tokens": int(usage.get("total_tokens", inp + out) or 0)}


def _post_upstream(request_payload: dict[str, Any]) -> dict[str, Any]:
    """POST to the configured Chat Completions endpoint with budget retries.

    The payload is intentionally mutated between attempts so an upstream
    ``finish_reason=length`` caused by hidden reasoning tokens gets a larger
    *JSON* ``max_tokens`` value on the next request.
    """
    upstream = None
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            request = Request(
                UPSTREAM_URL,
                data=json.dumps(request_payload).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {API_KEY}",
                },
                method="POST",
            )
            with urlopen(request, timeout=300) as response:  # noqa: S310
                upstream = json.loads(response.read().decode("utf-8"))
            choice = (upstream.get("choices") or [{}])[0]
            if (
                str(choice.get("finish_reason", "")) == "length"
                and attempt < 2
                and int(request_payload.get("max_tokens", 0) or 0) < MAX_UPSTREAM_TOKENS
            ):
                current_max_tokens = int(request_payload.get("max_tokens", 0) or 0)
                # If the caller omitted a visible-output budget, start from a
                # reserve-sized cap rather than retrying with zero forever.
                request_payload["max_tokens"] = min(
                    MAX_UPSTREAM_TOKENS,
                    max(
                        current_max_tokens * 2,
                        current_max_tokens + TOKEN_RESERVE,
                        TOKEN_RESERVE,
                    ),
                )
                upstream = None
                continue
            break
        except HTTPError as exc:
            # Preserve the provider's diagnostic body; otherwise Codex only
            # sees a generic 502 and model-adapter debugging becomes opaque.
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:1000]
            except Exception:  # noqa: BLE001
                detail = ""
            last_error = RuntimeError(
                f"upstream HTTP {exc.code}: {detail or exc.reason}"
            )
            # Validation errors are deterministic and should not be retried;
            # transient 5xx responses still use the normal retry budget.
            if int(exc.code) < 500:
                break
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    if upstream is None:
        raise RuntimeError(f"upstream request failed after 3 attempts: {last_error}")
    return upstream


def _responses_events(upstream: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert one Chat Completions response into Responses SSE events."""
    choice = (upstream.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    text = str(message.get("content") or message.get("reasoning_content") or "")
    response_id = str(upstream.get("id") or "resp_gateway")
    upstream_tool_calls = message.get("tool_calls")
    tool_calls = upstream_tool_calls if isinstance(upstream_tool_calls, list) else []
    output: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = [
        {"type": "response.created", "response": {"id": response_id, "object": "response", "status": "in_progress", "model": str(upstream.get("model") or MODEL)}},
    ]
    if tool_calls:
        for output_index, raw_call in enumerate(tool_calls):
            if not isinstance(raw_call, dict):
                continue
            function = raw_call.get("function") or {}
            if not isinstance(function, dict):
                function = {}
            call_id = str(raw_call.get("id") or f"call_{response_id}_{output_index}")
            name = str(function.get("name") or raw_call.get("name") or "")
            arguments = function.get("arguments", raw_call.get("arguments", "{}"))
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments, ensure_ascii=False)
            item = {"id": call_id, "type": "function_call", "call_id": call_id, "name": name, "arguments": arguments, "status": "completed"}
            output.append(item)
            events.extend([
                {"type": "response.output_item.added", "output_index": output_index, "item": {"id": call_id, "type": "function_call", "call_id": call_id, "name": name, "arguments": ""}},
                {"type": "response.function_call_arguments.delta", "item_id": call_id, "output_index": output_index, "name": name, "delta": arguments},
                {"type": "response.function_call_arguments.done", "item_id": call_id, "output_index": output_index, "name": name, "arguments": arguments},
                {"type": "response.output_item.done", "output_index": output_index, "item": item},
            ])
    else:
        item_id = f"msg_{response_id}"
        output_item = {"id": item_id, "type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}], "status": "completed"}
        output.append(output_item)
        events.extend([
            {"type": "response.output_item.added", "output_index": 0, "item": {"id": item_id, "type": "message", "role": "assistant", "content": []}},
            {"type": "response.content_part.added", "item_id": item_id, "output_index": 0, "content_index": 0, "part": {"type": "output_text", "text": ""}},
            {"type": "response.output_text.delta", "item_id": item_id, "output_index": 0, "content_index": 0, "delta": text},
            {"type": "response.output_text.done", "item_id": item_id, "output_index": 0, "content_index": 0, "text": text},
            {"type": "response.output_item.done", "output_index": 0, "item": output_item},
        ])
    response_payload = {"id": response_id, "object": "response", "status": "completed", "model": str(upstream.get("model") or MODEL), "output": output, "output_text": "" if tool_calls else text, "usage": _usage(upstream.get("usage", {}))}
    events.append({"type": "response.completed", "response": response_payload})
    return events


class Handler(BaseHTTPRequestHandler):
    server_version = "ResponsesChatBridge/1.0"

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") in {"", "/health"}:
            self._json(200, {"ok": True, "upstream_host": UPSTREAM_URL.split("/", 3)[2] if "://" in UPSTREAM_URL else "", "model": MODEL or "(request model)"})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.rstrip("/").endswith("/responses"):
            self._json(404, {"error": "expected /responses"})
            return
        try:
            length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(length))
            request_payload = _request_payload(payload)
            upstream = _post_upstream(request_payload)
            events = _responses_events(upstream)
            body = b"".join(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode() for event in events) + b"data: [DONE]\n\n"
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:  # noqa: BLE001
            self._json(502, {"error": {"message": str(exc)[:800]}})

    def _json(self, status: int, value: dict[str, Any]) -> None:
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: Any) -> None:
        return


if __name__ == "__main__":
    if not UPSTREAM_URL:
        raise SystemExit("EQUIPMENT_DR_BRIDGE_UPSTREAM_URL is required")
    if not API_KEY:
        raise SystemExit(f"missing upstream API key environment variable: {UPSTREAM_KEY_ENV}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
