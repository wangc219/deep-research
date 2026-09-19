"""Channel-neutral message transport for the deep-research Agent Core.

The HTTP API is only one transport for a research turn.  This module keeps
channel adapters (Web, CLI, chat connectors, or a future websocket) unaware of
the research workflow: adapters publish an :class:`InboundMessage`, while the
runtime publishes an :class:`OutboundMessage` back to the same bus.

The implementation follows nanobot's useful boundary but is deliberately
small.  It carries public, bounded payloads and never owns sessions, provider
credentials, or domain persistence.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from equipment_deep_research.domain.proposals import freeze_plain, thaw_plain


class MessageBusClosed(RuntimeError):
    """Raised when a channel attempts to use a closed bus."""


class DurableMessageBus(Protocol):
    """Host-owned durable broker contract for optional cross-process buses."""

    def publish_inbound(self, message: "InboundMessage") -> str:
        """Persist an inbound message and return its delivery id."""

    def claim_inbound(self, consumer_id: str) -> Mapping[str, Any] | None:
        """Claim one inbound message under a short visibility lease."""

    def ack_inbound(self, delivery_id: str, consumer_id: str) -> None:
        """Acknowledge one claimed inbound message."""

    def publish_outbound(self, message: "OutboundMessage") -> str:
        """Persist an outbound message and return its delivery id."""

    def claim_outbound(self, consumer_id: str) -> Mapping[str, Any] | None:
        """Claim one outbound message under a short visibility lease."""

    def ack_outbound(self, delivery_id: str, consumer_id: str) -> None:
        """Acknowledge one claimed outbound message."""

    def close(self) -> None:
        """Release host resources; repeated close calls are harmless."""


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
    "internalprompt",
    "systemprompt",
    "reasoning",
    "chainofthought",
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


def _text(value: Any, limit: int = 4000) -> str:
    return _sanitize_string(" ".join(str(value or "").split()).strip())[: max(0, int(limit))]


def _content(value: Any, limit: int) -> str:
    return _sanitize_string(str(value or "").strip())[:limit]


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
    return _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(0).split('=', 1)[0].split(':', 1)[0]}=<redacted>", value)


def _bounded_public(value: Any, *, depth: int = 0) -> Any:
    """Project channel metadata to a small JSON-safe public shape.

    Channel metadata is untrusted input.  It is useful for routing and UI
    hints, but it must not become an accidental transcript/provider sidecar.
    """

    if depth >= 4:
        return "<truncated>" if isinstance(value, str) else None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _sanitize_string(value)[:1000]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:32]:
            name = str(key)[:100]
            if not name.strip():
                continue
            result[name] = "<redacted>" if _is_sensitive_key(name) else _bounded_public(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_bounded_public(item, depth=depth + 1) for item in list(value)[:16]]
    return _sanitize_string(str(value))[:1000]


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """A channel-originated request understood by the Agent Core."""

    channel: str
    sender_id: str
    chat_id: str
    content: str
    message_id: str = field(default_factory=lambda: f"msg-{uuid4().hex[:16]}")
    session_key_override: str | None = None
    target_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    payload: Mapping[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        channel = _text(self.channel, 80)
        sender = _text(self.sender_id, 240)
        chat = _text(self.chat_id, 240)
        content = _content(self.content, 12000)
        if not channel:
            raise ValueError("inbound channel must not be empty")
        if not sender:
            raise ValueError("inbound sender_id must not be empty")
        if not chat:
            raise ValueError("inbound chat_id must not be empty")
        if not content:
            raise ValueError("inbound content must not be empty")
        if not isinstance(self.metadata, Mapping):
            raise TypeError("inbound metadata must be an object")
        if not isinstance(self.payload, Mapping):
            raise TypeError("inbound payload must be an object")
        timestamp = self.timestamp
        if not isinstance(timestamp, datetime):
            raise TypeError("inbound timestamp must be a datetime")
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = timestamp.astimezone(timezone.utc)
        object.__setattr__(self, "channel", channel)
        object.__setattr__(self, "sender_id", sender)
        object.__setattr__(self, "chat_id", chat)
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "message_id", _text(self.message_id, 160) or f"msg-{uuid4().hex[:16]}")
        object.__setattr__(self, "session_key_override", _text(self.session_key_override, 320) or None)
        object.__setattr__(self, "target_id", _text(self.target_id, 320) or None)
        object.__setattr__(self, "metadata", freeze_plain(_bounded_public(self.metadata)))
        object.__setattr__(self, "payload", freeze_plain(_bounded_public(self.payload)))
        object.__setattr__(self, "timestamp", timestamp)

    @property
    def session_key(self) -> str:
        """Return the stable conversation key shared by all transports."""

        return self.session_key_override or f"{self.channel}:{self.chat_id}"

    def to_plain(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "sender_id": self.sender_id,
            "chat_id": self.chat_id,
            "content": self.content,
            "message_id": self.message_id,
            "session_key": self.session_key,
            "target_id": self.target_id,
            "metadata": thaw_plain(self.metadata),
            "payload": thaw_plain(self.payload),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    """A channel-routed response produced by the Agent Core."""

    channel: str
    chat_id: str
    content: str = ""
    message_id: str = field(default_factory=lambda: f"out-{uuid4().hex[:16]}")
    correlation_id: str | None = None
    reply_to: str | None = None
    event_type: str = "assistant"
    payload: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        channel = _text(self.channel, 80)
        chat = _text(self.chat_id, 240)
        if not channel or not chat:
            raise ValueError("outbound channel and chat_id are required")
        if not isinstance(self.payload, Mapping) or not isinstance(self.metadata, Mapping):
            raise TypeError("outbound payload and metadata must be objects")
        object.__setattr__(self, "channel", channel)
        object.__setattr__(self, "chat_id", chat)
        object.__setattr__(self, "content", _content(self.content, 20000))
        object.__setattr__(self, "message_id", _text(self.message_id, 160) or f"out-{uuid4().hex[:16]}")
        object.__setattr__(self, "correlation_id", _text(self.correlation_id, 160) or None)
        object.__setattr__(self, "reply_to", _text(self.reply_to, 160) or None)
        object.__setattr__(self, "event_type", _text(self.event_type, 80) or "assistant")
        object.__setattr__(self, "payload", freeze_plain(_bounded_public(self.payload)))
        object.__setattr__(self, "metadata", freeze_plain(_bounded_public(self.metadata)))

    def to_plain(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "chat_id": self.chat_id,
            "content": self.content,
            "message_id": self.message_id,
            "correlation_id": self.correlation_id,
            "reply_to": self.reply_to,
            "event_type": self.event_type,
            "payload": thaw_plain(self.payload),
            "metadata": thaw_plain(self.metadata),
        }


def _inbound_from_plain(value: Mapping[str, Any]) -> InboundMessage:
    """Rebuild a bounded inbound message from a durable public projection."""

    raw_timestamp = value.get("timestamp")
    timestamp = datetime.now(timezone.utc)
    if isinstance(raw_timestamp, str):
        try:
            timestamp = datetime.fromisoformat(raw_timestamp)
        except ValueError:
            pass
    channel = str(value.get("channel", "") or "")
    chat_id = str(value.get("chat_id", "") or "")
    session_key = str(value.get("session_key", "") or "").strip()
    default_session_key = f"{channel.strip()}:{chat_id.strip()}"
    return InboundMessage(
        channel=channel,
        sender_id=str(value.get("sender_id", "") or ""),
        chat_id=chat_id,
        content=str(value.get("content", "") or ""),
        message_id=str(value.get("message_id", "") or ""),
        session_key_override=session_key if session_key and session_key != default_session_key else None,
        target_id=value.get("target_id"),
        metadata=value.get("metadata") if isinstance(value.get("metadata"), Mapping) else {},
        payload=value.get("payload") if isinstance(value.get("payload"), Mapping) else {},
        timestamp=timestamp,
    )


def _outbound_from_plain(value: Mapping[str, Any]) -> OutboundMessage:
    """Rebuild a bounded outbound message from a durable public projection."""

    return OutboundMessage(
        channel=str(value.get("channel", "") or ""),
        chat_id=str(value.get("chat_id", "") or ""),
        content=str(value.get("content", "") or ""),
        message_id=str(value.get("message_id", "") or ""),
        correlation_id=value.get("correlation_id"),
        reply_to=value.get("reply_to"),
        event_type=str(value.get("event_type", "assistant") or "assistant"),
        payload=value.get("payload") if isinstance(value.get("payload"), Mapping) else {},
        metadata=value.get("metadata") if isinstance(value.get("metadata"), Mapping) else {},
    )


Handler = Callable[[InboundMessage], Mapping[str, Any] | OutboundMessage | Awaitable[Mapping[str, Any] | OutboundMessage]]
OutboundHandler = Callable[[OutboundMessage], Any]


def _result_content(value: Any) -> str:
    if not isinstance(value, Mapping):
        return str(value or "")
    direct = value.get("content")
    if isinstance(direct, str) and direct.strip():
        return direct
    summaries = value.get("visible_summary")
    if isinstance(summaries, (list, tuple)):
        return "\n".join(
            str(item).strip()
            for item in summaries[:3]
            if str(item).strip()
        )
    return ""


class MessageBus:
    """Small async inbound/outbound bus shared by every channel adapter.

    ``publish`` only queues messages.  The optional ``serve`` helper owns the
    agent-core callback and returns responses through the outbound queue, so a
    WebSocket, CLI and HTTP adapter can use exactly the same execution path.
    """

    def __init__(
        self,
        *,
        maxsize: int = 0,
        backend: DurableMessageBus | None = None,
        consumer_id: str | None = None,
        poll_interval: float = 0.08,
    ) -> None:
        if isinstance(maxsize, bool) or maxsize < 0:
            raise ValueError("maxsize must be a non-negative integer")
        self.inbound: asyncio.Queue[InboundMessage | None] = asyncio.Queue(maxsize=maxsize)
        self.outbound: asyncio.Queue[OutboundMessage | None] = asyncio.Queue(maxsize=maxsize)
        self.backend = backend
        self.consumer_id = str(consumer_id or f"bus-{uuid4().hex}")[:160]
        self.poll_interval = max(0.01, min(float(poll_interval), 2.0))
        self._inbound_claims: dict[int, tuple[str, str]] = {}
        self._closed = False
        self._outbound_subscribers: list[OutboundHandler] = []

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def inbound_size(self) -> int:
        return self.inbound.qsize()

    @property
    def outbound_size(self) -> int:
        return self.outbound.qsize()

    async def publish_inbound(self, message: InboundMessage) -> None:
        if self._closed:
            raise MessageBusClosed("message bus is closed")
        if not isinstance(message, InboundMessage):
            raise TypeError("publish_inbound expects InboundMessage")
        if self.backend is not None:
            await asyncio.to_thread(self.backend.publish_inbound, message)
            return
        await self.inbound.put(message)

    async def consume_inbound(self) -> InboundMessage:
        if self.backend is not None:
            while True:
                if self._closed:
                    raise MessageBusClosed("message bus is closed")
                claim = await asyncio.to_thread(self.backend.claim_inbound, self.consumer_id)
                if claim is None:
                    await asyncio.sleep(self.poll_interval)
                    continue
                delivery_id = str(claim.get("delivery_id", "") or "")
                payload = claim.get("payload")
                if not delivery_id or not isinstance(payload, Mapping):
                    continue
                message = _inbound_from_plain(payload)
                self._inbound_claims[id(message)] = (delivery_id, self.consumer_id)
                return message
        while True:
            if self._closed and self.inbound.empty():
                raise MessageBusClosed("message bus is closed")
            try:
                message = await asyncio.wait_for(self.inbound.get(), timeout=0.25)
            except asyncio.TimeoutError:
                continue
            self.inbound.task_done()
            if message is None:
                raise MessageBusClosed("message bus is closed")
            return message

    async def publish_outbound(self, message: OutboundMessage) -> None:
        if self._closed:
            raise MessageBusClosed("message bus is closed")
        if not isinstance(message, OutboundMessage):
            raise TypeError("publish_outbound expects OutboundMessage")
        if self.backend is not None:
            await asyncio.to_thread(self.backend.publish_outbound, message)
        else:
            await self.outbound.put(message)
        # Subscribers are local observers (UI projections, metrics, tests).
        # Delivery errors never prevent the channel queue from receiving the
        # response.
        for handler in tuple(self._outbound_subscribers):
            try:
                result = handler(message)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                continue

    def subscribe(self, handler: OutboundHandler) -> Callable[[], None]:
        """Subscribe to outbound responses and return an idempotent remover."""

        if not callable(handler):
            raise TypeError("handler must be callable")
        self._outbound_subscribers.append(handler)
        active = True

        def unsubscribe() -> None:
            nonlocal active
            if not active:
                return
            active = False
            try:
                self._outbound_subscribers.remove(handler)
            except ValueError:
                pass

        return unsubscribe

    async def publish_event(
        self,
        event: Any,
        *,
        channel: str,
        chat_id: str,
        correlation_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Publish a typed/runtime event without teaching channels its shape."""

        payload = event.to_plain() if hasattr(event, "to_plain") else _bounded_public(event)
        await self.publish_outbound(
            OutboundMessage(
                channel=channel,
                chat_id=chat_id,
                correlation_id=correlation_id,
                event_type=type(event).__name__,
                payload=payload if isinstance(payload, Mapping) else {"event": payload},
                metadata=metadata or {},
            )
        )

    async def consume_outbound(self) -> OutboundMessage:
        if self.backend is not None:
            while True:
                if self._closed:
                    raise MessageBusClosed("message bus is closed")
                claim = await asyncio.to_thread(self.backend.claim_outbound, self.consumer_id)
                if claim is None:
                    await asyncio.sleep(self.poll_interval)
                    continue
                delivery_id = str(claim.get("delivery_id", "") or "")
                payload = claim.get("payload")
                if not delivery_id or not isinstance(payload, Mapping):
                    continue
                message = _outbound_from_plain(payload)
                await asyncio.to_thread(self.backend.ack_outbound, delivery_id, self.consumer_id)
                return message
        while True:
            if self._closed and self.outbound.empty():
                raise MessageBusClosed("message bus is closed")
            try:
                message = await asyncio.wait_for(self.outbound.get(), timeout=0.25)
            except asyncio.TimeoutError:
                continue
            self.outbound.task_done()
            if message is None:
                raise MessageBusClosed("message bus is closed")
            return message

    async def drain(self) -> None:
        """Wait until queued inbound and outbound messages are acknowledged."""
        if self.backend is not None:
            return
        if self._closed:
            # Shutdown is terminal: discard messages that no channel consumer
            # claimed before close, acknowledging them so ``drain`` cannot
            # strand a worker on a bounded queue.
            for queue in (self.inbound, self.outbound):
                while True:
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    else:
                        queue.task_done()
            return
        await self.inbound.join()
        await self.outbound.join()

    async def serve(
        self,
        handler: Handler,
        *,
        stop_event: asyncio.Event | None = None,
        once: bool = False,
    ) -> None:
        """Run the channel-independent Agent Core callback.

        A handler may return an ``OutboundMessage`` or a mapping.  Mappings are
        normalized using the inbound route and correlation id, keeping channel
        formatting outside the core.
        """

        if not callable(handler):
            raise TypeError("handler must be callable")
        while not self._closed:
            if stop_event is not None and stop_event.is_set():
                return
            if stop_event is None:
                try:
                    message = await self.consume_inbound()
                except MessageBusClosed:
                    return
            else:
                # ``consume_inbound`` deliberately keeps waiting through short
                # queue timeouts.  Wrapping that loop in ``wait_for`` cannot
                # observe a stop event, so race one consumer task against the
                # event and cancel the loser on idle shutdown.
                consume_task = asyncio.create_task(self.consume_inbound())
                stop_task = asyncio.create_task(stop_event.wait())
                done, pending = await asyncio.wait(
                    (consume_task, stop_task),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                if stop_task in done:
                    if not consume_task.done():
                        consume_task.cancel()
                        await asyncio.gather(consume_task, return_exceptions=True)
                    return
                try:
                    message = consume_task.result()
                except MessageBusClosed:
                    return
            result = handler(message)
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, OutboundMessage):
                outbound = result
            else:
                data = dict(result) if isinstance(result, Mapping) else {"content": str(result or "")}
                outbound = OutboundMessage(
                    channel=message.channel,
                    chat_id=message.chat_id,
                    content=str(data.pop("content", "") or ""),
                    correlation_id=message.message_id,
                    reply_to=message.message_id,
                    event_type=str(data.pop("event_type", "assistant") or "assistant"),
                    payload=data.pop("payload", data),
                    metadata={"session_key": message.session_key},
                )
            await self.publish_outbound(outbound)
            if self.backend is not None:
                claim = self._inbound_claims.pop(id(message), None)
                if claim is not None:
                    await asyncio.to_thread(self.backend.ack_inbound, claim[0], claim[1])
            if once:
                return

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.backend is not None:
            await asyncio.to_thread(self.backend.close)
            self._inbound_claims.clear()
            self._outbound_subscribers.clear()
            return
        # Wake consumers without blocking on a bounded queue.  Consumers also
        # observe ``_closed`` when the queue is empty, so a full queue cannot
        # strand shutdown behind an awaited sentinel insertion.
        try:
            self.inbound.put_nowait(None)
        except asyncio.QueueFull:
            pass
        try:
            self.outbound.put_nowait(None)
        except asyncio.QueueFull:
            pass
        self._outbound_subscribers.clear()


async def dispatch_channel_call_async(
    execute: Callable[[Mapping[str, Any]], Any],
    message: InboundMessage,
    *,
    host_payload: Mapping[str, Any],
    observer: OutboundHandler | None = None,
) -> Any:
    """Dispatch one host-bound call through a job-local bus.

    The private result returns to the host for its own validation and durable
    commit; observers receive only the bounded public projection. A local bus
    avoids sharing asyncio queues across HTTP worker threads or event loops.
    """

    if not callable(execute):
        raise TypeError("execute must be callable")
    if not isinstance(message, InboundMessage):
        raise TypeError("message must be an InboundMessage")
    if not isinstance(host_payload, Mapping):
        raise TypeError("host_payload must be an object")
    bus = MessageBus(maxsize=1)
    result: Any = None

    async def handle(inbound: InboundMessage):
        nonlocal result
        request = dict(host_payload)
        # The gateway owns final delivery. Do not ask a nested runtime to
        # enqueue another final response on this bounded queue.
        request.pop("message_bus", None)
        request.update({
            "question": inbound.content,
            "channel": inbound.channel,
            "sender_id": inbound.sender_id,
            "chat_id": inbound.chat_id,
            "session_key": inbound.session_key,
            "inbound_message": inbound,
        })
        # Synchronous providers often own asyncio.run internally. Keep them
        # outside this event loop while preserving contextvars with to_thread.
        result = await asyncio.to_thread(execute, request)
        if inspect.isawaitable(result):
            result = await result
        return OutboundMessage(
            channel=inbound.channel,
            chat_id=inbound.chat_id,
            content=_result_content(result),
            correlation_id=inbound.message_id,
            reply_to=inbound.message_id,
            event_type="agent.completed",
            payload=result if isinstance(result, Mapping) else {},
            metadata={"session_key": inbound.session_key},
        )

    if observer is not None:
        bus.subscribe(observer)
    try:
        await bus.publish_inbound(message)
        await bus.serve(handle, once=True)
        await bus.consume_outbound()
        await bus.drain()
        return result
    finally:
        await bus.close()
        await bus.drain()


def dispatch_channel_call(
    execute: Callable[[Mapping[str, Any]], Any],
    message: InboundMessage,
    *,
    host_payload: Mapping[str, Any],
    observer: OutboundHandler | None = None,
) -> Any:
    """Synchronous gateway for existing HTTP and CLI workers."""

    return asyncio.run(dispatch_channel_call_async(
        execute, message, host_payload=host_payload, observer=observer,
    ))


# Readable aliases for callers migrating from nanobot's bus contract.
DeepInboundMessage = InboundMessage
DeepOutboundMessage = OutboundMessage


__all__ = [
    "DeepInboundMessage",
    "DeepOutboundMessage",
    "InboundMessage",
    "DurableMessageBus",
    "MessageBus",
    "MessageBusClosed",
    "OutboundMessage",
    "dispatch_channel_call",
    "dispatch_channel_call_async",
]
