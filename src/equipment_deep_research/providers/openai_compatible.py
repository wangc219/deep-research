"""Provider-neutral OpenAI Chat Completions adapter.

This covers DeepSeek and other gateways exposing the widely adopted
``/chat/completions`` contract.  The orchestration layer only sees the shared
provider events, so model/vendor names never enter the execution flow.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

from equipment_deep_research.domain.proposals import thaw_plain
from equipment_deep_research.providers.base import (
    ModelMessage,
    ProviderCapabilities,
    ProviderFinalTurn,
    ProviderStreamEvent,
    ProviderToolCall,
)
from equipment_deep_research.providers.responses import (
    ProviderAuthenticationError,
    ProviderRequestError,
    ProviderRetryableError,
    _compact_contract_to_json_schema,
)
from equipment_deep_research.contracts.tools import ToolDefinition


def normalize_chat_completions_url(value: str) -> str:
    """Accept API root, ``/v1``, or a full ``/chat/completions`` endpoint."""

    raw = str(value or "").strip()
    if not raw:
        return raw
    parsed = urlsplit(raw)
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        return urlunsplit(
            (parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment)
        )
    if path.endswith("/responses"):
        path = path[: -len("/responses")]
    if not path.endswith("/v1"):
        path = f"{path}/v1" if path else "/v1"
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            f"{path}/chat/completions",
            parsed.query,
            parsed.fragment,
        )
    )


class OpenAICompatibleProvider:
    provider_type = "chat_completions"

    def __init__(self, *, provider_id: str, model: str, base_url: str, api_key: str, timeout_seconds: int = 120, structured_mode: str = "json_schema") -> None:
        if not model.strip():
            raise ValueError("Chat Completions model is required")
        if not api_key:
            raise ProviderAuthenticationError(f"{provider_id} API key is required")
        normalized = normalize_chat_completions_url(base_url)
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise ValueError("Chat Completions base URL must be an HTTP(S) URL")
        if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("Chat Completions HTTP URLs are only allowed for localhost")
        self.provider_id, self.model, self.base_url = provider_id, model.strip(), normalized
        self._api_key, self.timeout_seconds = api_key, timeout_seconds
        self.structured_mode = structured_mode if structured_mode in {"json_schema", "json_object", "none"} else "json_schema"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(streaming=True, structured_output=self.structured_mode != "none", function_tools=True, cancellation=True)

    def snapshot(self) -> dict[str, str]:
        return {"type": self.provider_type, "provider_id": self.provider_id, "model": self.model, "base_url_host": urlsplit(self.base_url).hostname or ""}

    async def stream(self, messages: Sequence[ModelMessage], tools: Sequence[ToolDefinition], options: Mapping[str, Any]) -> AsyncIterator[ProviderStreamEvent]:
        payload = build_chat_payload(self.model, messages, tools, options, structured_mode=self.structured_mode)
        active_payload = payload
        structured_output_fallback = False
        try:
            lines = await self._post_with_transient_retry(
                active_payload,
                disable_timeout=bool(options.get("_disable_provider_timeout", False)),
            )
        except ProviderRequestError as exc:
            # A number of OpenAI-compatible gateways advertise the Chat
            # Completions route but do not implement response_format yet.
            # Keep the provider usable by negotiating down to plain JSON
            # content once, rather than failing the whole DeepSeek run.  The
            # JSON protocol marker is already present in the json_object
            # payload, so downstream contract parsing remains unchanged.
            if "response_format" not in active_payload or not _is_response_format_rejection(str(exc)):
                raise
            active_payload = dict(active_payload)
            active_payload.pop("response_format", None)
            structured_output_fallback = True
            lines = await self._post_with_transient_retry(
                active_payload,
                disable_timeout=bool(options.get("_disable_provider_timeout", False)),
            )
        events = list(iter_chat_sse(lines))
        # DeepSeek-style reasoning models may spend the whole initial
        # ``max_tokens`` allowance on hidden reasoning and finish with an
        # empty ``content`` field.  They can also emit a *prefix* of a JSON
        # answer and report ``finish_reason=length``.  The latter used to be
        # treated as authoritative, which made long baseline prompts look
        # like successful model turns but left the outer validator with no
        # usable findings.  Retry boundedly for both forms.  A second retry
        # is allowed when the first enlarged response is still truncated;
        # this is important for reasoning models because hidden tokens share
        # the same upstream budget as visible output.
        retry_attempts = 0
        retry_tokens_used: list[int] = []
        retry_cap = max(
            4096,
            int(
                os.environ.get(
                    "EQUIPMENT_DR_CHAT_COMPLETIONS_RETRY_MAX_TOKENS", "32768"
                )
            ),
        )
        max_retries = max(
            1,
            min(
                3,
                int(
                    os.environ.get(
                        "EQUIPMENT_DR_CHAT_COMPLETIONS_MAX_RETRIES", "2"
                    )
                ),
            ),
        )
        while retry_attempts < max_retries and _needs_structured_retry(
            events, has_schema=isinstance(active_payload.get("response_format"), Mapping)
        ):
            current_tokens = int(active_payload.get("max_tokens") or 0)
            retry_tokens = min(
                retry_cap,
                max(
                    current_tokens * 4,
                    8192 if retry_attempts == 0 else 16384,
                ),
            )
            if retry_tokens <= current_tokens:
                break
            retry_payload = dict(active_payload)
            retry_payload["max_tokens"] = retry_tokens
            # A reasoning gateway can consume the first budget entirely in
            # hidden ``reasoning_content`` and omit ``finish_reason``.  The
            # recovery request is deliberately concise and disables hidden
            # thinking where the OpenLux-compatible endpoint supports it;
            # this preserves the caller's schema while guaranteeing a visible
            # JSON envelope for the downstream contract validator.
            if _visible_text(events) == "" and not _has_tool_call(events):
                retry_payload["thinking"] = {"type": "disabled"}
                retry_payload["messages"] = _recovery_messages(
                    retry_payload.get("messages", []),
                    has_schema=isinstance(retry_payload.get("response_format"), Mapping),
                )
            try:
                retry_attempts += 1
                retry_tokens_used.append(retry_tokens)
                # Use the same transient retry policy as the initial call;
                # capacity/rate-limit responses must not discard recovery.
                retry_lines = await self._post_with_transient_retry(
                    retry_payload,
                    disable_timeout=bool(options.get("_disable_provider_timeout", False)),
                )
                retry_events = list(iter_chat_sse(retry_lines))
                if _visible_text(retry_events) or not _needs_structured_retry(
                    retry_events,
                    has_schema=isinstance(
                        retry_payload.get("response_format"), Mapping
                    ),
                ):
                    events = retry_events
                active_payload = retry_payload
            except ProviderRetryableError:
                # Keep the best response already received when the bounded
                # recovery attempt is rate-limited or unavailable.
                break
        text: list[str] = []
        calls: dict[str, dict[str, Any]] = {}
        usage: Mapping[str, Any] = {}
        finish = "completed"
        for event in events:
            choices = event.get("choices", [])
            if isinstance(choices, list) and choices and isinstance(choices[0], Mapping):
                choice = choices[0]
                finish = str(choice.get("finish_reason") or finish)
                delta = choice.get("delta", {})
                if isinstance(delta, Mapping):
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        text.append(content); yield ProviderStreamEvent.text_delta(content)
                    for call in delta.get("tool_calls", []) if isinstance(delta.get("tool_calls", []), list) else []:
                        if not isinstance(call, Mapping): continue
                        idx = str(call.get("index", len(calls))); current = calls.setdefault(idx, {"id": call.get("id", idx), "name": "", "arguments": ""})
                        fn = call.get("function", {}); fn = fn if isinstance(fn, Mapping) else {}
                        current["name"] = str(fn.get("name") or current["name"]); current["arguments"] += str(fn.get("arguments") or "")
            if isinstance(event.get("usage"), Mapping): usage = event["usage"]
        tool_calls = []
        for call in calls.values():
            try: args = json.loads(call["arguments"] or "{}")
            except json.JSONDecodeError as exc: raise ProviderRequestError("Chat Completions tool arguments are invalid JSON") from exc
            tool_calls.append(ProviderToolCall(str(call["id"]), str(call["name"]), args))
        final_metadata: dict[str, Any] = {
            "provider": self.provider_id,
            "visible_text_chars": len("".join(text)),
            "finish_reason": finish,
            "response_format_used": (
                str(active_payload.get("response_format", {}).get("type", ""))
                if isinstance(active_payload.get("response_format"), Mapping)
                else "none"
            ),
        }
        if structured_output_fallback:
            final_metadata["structured_output_fallback"] = True
        if retry_attempts:
            final_metadata.update(
                {
                    "empty_answer_retry": True,
                    "retry_attempts": retry_attempts,
                    "retry_max_tokens": retry_tokens_used[-1]
                    if retry_tokens_used
                    else None,
                    "retry_max_tokens_history": retry_tokens_used,
                }
            )
        yield ProviderStreamEvent.final(ProviderFinalTurn(text="".join(text) or None, tool_calls=tool_calls or None, finish_reason=finish, usage=usage, metadata=final_metadata))

    async def _post_with_transient_retry(
        self, payload: Mapping[str, Any], *, disable_timeout: bool = False
    ) -> list[str]:
        """Post once, retrying only transport/upstream transient failures."""

        try:
            if disable_timeout:
                return await asyncio.to_thread(
                    self._post, payload, disable_timeout=True
                )
            return await asyncio.to_thread(self._post, payload)
        except ProviderRetryableError:
            await asyncio.sleep(1)
            if disable_timeout:
                return await asyncio.to_thread(
                    self._post, payload, disable_timeout=True
                )
            return await asyncio.to_thread(self._post, payload)

    def _post(
        self, payload: Mapping[str, Any], *, disable_timeout: bool = False
    ) -> list[str]:
        request = Request(self.base_url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", "Accept": "text/event-stream", "Authorization": f"Bearer {self._api_key}"}, method="POST")
        try:
            with urlopen(
                request,
                timeout=None if disable_timeout else self.timeout_seconds,
            ) as response:
                return [line.decode("utf-8", errors="replace") for line in response]
        except HTTPError as exc:
            try:
                detail = exc.read(800).decode("utf-8", errors="replace").strip()
            except Exception:
                detail = ""
            # Gateways often return the actionable validation reason in the
            # response body (for example an unsupported structured-output
            # combination).  Preserve only a short, credential-free excerpt.
            suffix = f" detail={detail[:500]}" if detail else ""
            message = f"{self.provider_id} Chat Completions request failed: status={exc.code}{suffix}"
            if exc.code == 401: raise ProviderAuthenticationError(message) from exc
            if exc.code == 429 or exc.code >= 500: raise ProviderRetryableError(message) from exc
            raise ProviderRequestError(message) from exc
        except (URLError, TimeoutError) as exc:
            raise ProviderRetryableError(f"{self.provider_id} network request failed") from exc


def build_chat_payload(model: str, messages: Sequence[ModelMessage], tools: Sequence[ToolDefinition], options: Mapping[str, Any], *, structured_mode: str = "json_schema") -> dict[str, Any]:
    message_payloads = [_message(m) for m in messages]
    payload: dict[str, Any] = {"model": model, "messages": message_payloads, "stream": True, "stream_options": {"include_usage": True}}
    if tools:
        payload["tools"] = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": thaw_plain(t.input_schema)}} for t in tools]
    schema = options.get("output_schema")
    if isinstance(schema, Mapping) and structured_mode != "none":
        if structured_mode == "json_object":
            # DeepSeek-compatible gateways require the prompt to mention JSON
            # when ``response_format=json_object`` is used.  Add a minimal
            # protocol instruction only when the caller's messages do not
            # already contain that marker; no provider URL or credential is
            # embedded in the request.
            serialized = json.dumps(message_payloads, ensure_ascii=False).lower()
            if "json" not in serialized:
                message_payloads.insert(
                    0,
                    {
                        "role": "system",
                        "content": "Return the final answer as valid JSON matching the requested structure.",
                    },
                )
            payload["response_format"] = {"type": "json_object"}
        else: payload["response_format"] = {"type": "json_schema", "json_schema": {"name": "equipment_research_output", "strict": True, "schema": _compact_contract_to_json_schema(schema)}}
    if options.get("max_output_tokens") is not None: payload["max_tokens"] = int(options["max_output_tokens"])
    if options.get("_disable_hidden_reasoning") or options.get("disable_thinking"):
        # OpenLux accepts the DeepSeek-compatible thinking switch.  This is
        # used only by the baseline/recovery paths where a visible structured
        # packet is mandatory; S3-S6 creative calls retain their normal
        # reasoning budget unless the caller opts in.
        payload["thinking"] = {"type": "disabled"}
    return payload


def _message(message: ModelMessage) -> dict[str, Any]:
    content = thaw_plain(message.content); content = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    value: dict[str, Any] = {"role": message.role, "content": content}
    if message.tool_call_id:
        value["tool_call_id"] = message.tool_call_id
    if message.name:
        value["name"] = message.name
    if message.tool_calls:
        value["tool_calls"] = [
            {
                "id": call.call_id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(
                        thaw_plain(call.arguments), ensure_ascii=False, separators=(",", ":")
                    ),
                },
            }
            for call in message.tool_calls
        ]
    return value


def iter_chat_sse(lines: Iterable[str]) -> Iterable[dict[str, Any]]:
    for line in lines:
        value = line[5:].strip() if line.startswith("data:") else ""
        if not value or value == "[DONE]": continue
        try: payload = json.loads(value)
        except json.JSONDecodeError as exc: raise ProviderRequestError("Chat Completions SSE contained invalid JSON") from exc
        if isinstance(payload, Mapping): yield dict(payload)


def _empty_answer_turn(events: Sequence[Mapping[str, Any]]) -> bool:
    """Whether a streamed turn has no answer content or tool request.

    Some OpenAI-compatible reasoning gateways report ``stop`` even when the
    visible answer is empty.  A single bounded recovery attempt is safe for
    those turns as well as the more explicit ``length``/``max_tokens`` case;
    non-empty or tool-calling turns remain authoritative.
    """

    saw_content = False
    saw_tool_call = False
    saw_choice = False
    for event in events:
        choices = event.get("choices", [])
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
            continue
        saw_choice = True
        choice = choices[0]
        delta = choice.get("delta", {})
        if not isinstance(delta, Mapping):
            continue
        content = delta.get("content")
        saw_content = saw_content or (isinstance(content, str) and bool(content.strip()))
        tool_calls = delta.get("tool_calls", [])
        saw_tool_call = saw_tool_call or isinstance(tool_calls, list) and bool(tool_calls)
    # Some gateways omit ``finish_reason`` on the terminal chunk when the
    # model spent the whole turn in hidden reasoning.  Once a choice has been
    # streamed with neither visible content nor a tool call, the response is
    # unusable regardless of the reported/omitted finish reason and should
    # enter the bounded recovery path.
    return saw_choice and not saw_content and not saw_tool_call


def _has_tool_call(events: Sequence[Mapping[str, Any]]) -> bool:
    for event in events:
        choices = event.get("choices", [])
        if not isinstance(choices, list) or not choices:
            continue
        choice = choices[0]
        if not isinstance(choice, Mapping):
            continue
        delta = choice.get("delta", {})
        if not isinstance(delta, Mapping):
            continue
        calls = delta.get("tool_calls", [])
        if isinstance(calls, list) and calls:
            return True
    return False


def _recovery_messages(messages: Any, *, has_schema: bool) -> list[dict[str, Any]]:
    """Add a provider-neutral short repair instruction without leaking data."""

    rows = [dict(item) for item in messages if isinstance(item, Mapping)]
    instruction = (
        "Previous response contained no visible answer. Return the requested "
        "result now as concise valid JSON only; do not emit reasoning, prose, "
        "or markdown."
        if has_schema
        else "Previous response contained no visible answer. Return a concise "
        "answer now; do not emit hidden reasoning or markdown."
    )
    rows.append({"role": "user", "content": instruction})
    return rows


def _visible_text(events: Sequence[Mapping[str, Any]]) -> str:
    """Collect visible assistant text without interpreting reasoning chunks."""

    parts: list[str] = []
    for event in events:
        choices = event.get("choices", [])
        if not isinstance(choices, list) or not choices:
            continue
        choice = choices[0]
        if not isinstance(choice, Mapping):
            continue
        delta = choice.get("delta", {})
        if isinstance(delta, Mapping) and isinstance(delta.get("content"), str):
            parts.append(delta["content"])
    return "".join(parts).strip()


def _finish_reason(events: Sequence[Mapping[str, Any]]) -> str:
    """Return the terminal finish reason reported by the gateway, if any."""

    finish = ""
    for event in events:
        choices = event.get("choices", [])
        if not isinstance(choices, list) or not choices:
            continue
        choice = choices[0]
        if isinstance(choice, Mapping) and choice.get("finish_reason"):
            finish = str(choice["finish_reason"])
    return finish


def _needs_structured_retry(
    events: Sequence[Mapping[str, Any]], *, has_schema: bool
) -> bool:
    """Identify an incomplete Chat Completions turn worth retrying.

    ``reasoning_content`` is intentionally ignored: it is not an answer and
    must not prevent recovery.  Empty turns are retried even without a
    schema, while ``length``/``max_tokens`` turns are retried only for
    structured requests so ordinary long-form text is not replaced.
    """

    if _empty_answer_turn(events):
        return True
    if not has_schema:
        return False
    # A non-empty prefix can still be an unterminated JSON document.  Some
    # OpenLux responses incorrectly report ``stop`` after cutting the visible
    # JSON at the upstream token boundary, so validate only the JSON envelope
    # (not the caller's full schema) before deciding whether to retry.
    if _finish_reason(events) in {"length", "max_tokens"}:
        return True
    visible = _visible_text(events).strip()
    if _finish_reason(events) == "stop" and visible[:1] in {"{", "["}:
        try:
            json.loads(visible)
        except json.JSONDecodeError:
            return True
    return False


def _is_response_format_rejection(detail: str) -> bool:
    """Return whether a gateway rejected only the structured-output option."""

    normalized = str(detail or "").lower()
    return (
        "response_format" in normalized
        and any(
            marker in normalized
            for marker in (
                "unavailable",
                "unsupported",
                "not support",
                "invalid",
                "unknown",
            )
        )
    )


__all__ = [
    "OpenAICompatibleProvider",
    "build_chat_payload",
    "iter_chat_sse",
    "normalize_chat_completions_url",
]
