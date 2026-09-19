"""Thin Telegram and Discord adapters for the channel-neutral Agent Core.

These adapters deliberately do not own credentials, HTTP clients, sessions,
or repositories.  A deployment gateway authenticates the platform event,
resolves a server-owned research session, and passes that trusted session key
here.  The normalized message then follows the same MessageBus path as Web
and CLI turns.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
from concurrent.futures import Future
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import threading
import time
from typing import Any, Protocol

from equipment_deep_research.deep_runtime.channel import (
    InboundMessage,
    OutboundHandler,
    OutboundMessage,
    _bounded_public,
    dispatch_channel_call_async,
)


class ChannelPayloadRejected(ValueError):
    """Raised when an external event is malformed or outside its allowlist."""


@dataclass(frozen=True, slots=True)
class GatewayIdentity:
    """Stable platform identity used by a deployment-owned session resolver."""

    channel: str
    sender_id: str
    chat_id: str
    message_id: str
    thread_id: str | None = None


class GatewaySessionResolver(Protocol):
    """Host boundary that maps authenticated platform identity to a session."""

    def resolve_session(
        self, identity: GatewayIdentity, payload: Mapping[str, Any]
    ) -> str | None:
        """Return a server-owned session key, or ``None`` to reject."""


class GatewayDeliveryStore(Protocol):
    """Durable claim/response boundary for platform delivery idempotency.

    Implementations belong to the deployment host.  The Agent Core only sees
    this small protocol, so credentials, SQL connections and HTTP clients do
    not leak into the channel adapter or research loop.
    """

    def claim(
        self,
        key: str,
        *,
        fingerprint: str,
        ttl_seconds: int,
    ) -> Mapping[str, Any]:
        """Atomically claim a delivery or return its current durable row."""

    def get(self, key: str, *, fingerprint: str) -> Mapping[str, Any] | None:
        """Read a durable delivery row for a bounded remote wait."""

    def complete(
        self,
        key: str,
        *,
        fingerprint: str,
        owner_token: str,
        response: Mapping[str, Any],
        ttl_seconds: int,
    ) -> None:
        """Persist a completed public response for replay."""

    def release(self, key: str, *, fingerprint: str, owner_token: str) -> None:
        """Release an unfinished claim after execution failure."""


@dataclass(frozen=True, slots=True)
class WebhookSignaturePolicy:
    """Credential-free HMAC verifier for deployment gateway webhook bodies."""

    secret: bytes = field(init=False, repr=False)
    signature_header: str = "x-deep-gateway-signature"
    timestamp_header: str = "x-deep-gateway-timestamp"
    nonce_header: str = "x-deep-gateway-nonce"
    tolerance_seconds: int = 300

    def __init__(
        self,
        *,
        secret: str | bytes,
        signature_header: str = "x-deep-gateway-signature",
        timestamp_header: str = "x-deep-gateway-timestamp",
        nonce_header: str = "x-deep-gateway-nonce",
        tolerance_seconds: int = 300,
    ) -> None:
        if isinstance(secret, str):
            secret_bytes = secret.encode("utf-8")
        else:
            secret_bytes = bytes(secret)
        if not secret_bytes:
            raise ValueError("webhook signature secret is required")
        if tolerance_seconds <= 0 or tolerance_seconds > 3600:
            raise ValueError("webhook timestamp tolerance must be between 1 and 3600 seconds")
        object.__setattr__(self, "secret", secret_bytes)
        object.__setattr__(self, "signature_header", signature_header.lower())
        object.__setattr__(self, "timestamp_header", timestamp_header.lower())
        object.__setattr__(self, "nonce_header", nonce_header.lower())
        object.__setattr__(self, "tolerance_seconds", int(tolerance_seconds))

    def sign(self, body: bytes | str, *, timestamp: str, nonce: str) -> str:
        body_bytes = body.encode("utf-8") if isinstance(body, str) else bytes(body)
        message = b".".join(
            [timestamp.encode("utf-8"), nonce.encode("utf-8"), body_bytes]
        )
        digest = hmac.new(self.secret, message, hashlib.sha256).hexdigest()
        return f"sha256={digest}"

    def verify(
        self,
        body: bytes | str,
        headers: Mapping[str, Any],
        *,
        now: float | None = None,
        replay_cache: "WebhookReplayCache | None" = None,
    ) -> None:
        signature = _header(headers, self.signature_header)
        timestamp = _header(headers, self.timestamp_header)
        nonce = _header(headers, self.nonce_header)
        if not signature or not timestamp or not nonce:
            raise ChannelPayloadRejected("webhook signature headers are incomplete")
        try:
            signed_at = float(timestamp)
        except ValueError as exc:
            raise ChannelPayloadRejected("webhook timestamp is invalid") from exc
        current = time.time() if now is None else float(now)
        if not math.isfinite(signed_at) or not math.isfinite(current):
            raise ChannelPayloadRejected("webhook timestamp is invalid")
        if abs(current - signed_at) > self.tolerance_seconds:
            raise ChannelPayloadRejected("webhook timestamp is outside the replay window")
        expected = self.sign(body, timestamp=timestamp, nonce=nonce)
        if not hmac.compare_digest(signature, expected):
            raise ChannelPayloadRejected("webhook signature is invalid")
        if replay_cache is not None:
            replay_cache.check_and_store(
                nonce, signed_at=signed_at, now=current,
                ttl_seconds=self.tolerance_seconds,
            )


class WebhookReplayCache:
    """Small in-memory replay guard for one deployment process."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: dict[str, float] = {}

    def check_and_store(
        self,
        nonce: str,
        *,
        signed_at: float,
        now: float | None = None,
        ttl_seconds: int = 300,
    ) -> None:
        value = _identifier(nonce, field="webhook nonce")
        current = time.time() if now is None else float(now)
        with self._lock:
            expired = [key for key, expires_at in self._seen.items() if expires_at <= current]
            for key in expired:
                self._seen.pop(key, None)
            if value in self._seen:
                raise ChannelPayloadRejected("webhook nonce was already used")
            self._seen[value] = max(current, signed_at) + ttl_seconds


@dataclass
class _GatewayDeliveryEntry:
    """Internal single-flight record for one platform message id."""

    completion: Future = field(default_factory=Future)
    fingerprint: str = ""
    expires_at: float = 0.0
    delivery_key: str = ""
    owner_token: str = ""
    remote_pending: bool = False


class GatewayDeliveryCache:
    """Bounded result cache that collapses webhook retries into one turn.

    Platform providers commonly retry a delivery with a fresh request
    signature. The message id is the provider's stable idempotency key, so a
    deployment can safely return the first completed response without running
    the Agent Core twice. Entries are process-local by design; a multi-process
    deployment should place the same contract behind its own shared store.
    """

    def __init__(
        self,
        *,
        ttl_seconds: int = 900,
        max_entries: int = 4096,
        store: GatewayDeliveryStore | None = None,
    ) -> None:
        if type(ttl_seconds) is not int or not 0 < ttl_seconds <= 86_400:
            raise ValueError("gateway delivery TTL must be between 1 and 86400 seconds")
        if type(max_entries) is not int or not 0 < max_entries <= 100_000:
            raise ValueError("gateway delivery cache size is outside the host limit")
        self.ttl_seconds = int(ttl_seconds)
        self.max_entries = int(max_entries)
        self.store = store
        self._lock = threading.Lock()
        self._entries: dict[str, _GatewayDeliveryEntry] = {}

    def _purge(self, now: float) -> None:
        for key, entry in tuple(self._entries.items()):
            if entry.expires_at <= now and entry.completion.done():
                self._entries.pop(key, None)

    def claim(self, key: str, *, fingerprint: str = "", now: float | None = None) -> tuple[bool, _GatewayDeliveryEntry]:
        normalized = _identifier(key, field="gateway delivery key")
        current = time.monotonic() if now is None else float(now)
        with self._lock:
            self._purge(current)
            existing = self._entries.get(normalized)
            if existing is not None:
                if existing.fingerprint != fingerprint:
                    raise ChannelPayloadRejected("gateway message id has conflicting content")
                return False, existing
            if len(self._entries) >= self.max_entries:
                # Evict the oldest completed entry. Never evict an in-flight
                # request, because doing so would re-enable duplicate work.
                completed = [
                    (item.expires_at, item_key)
                    for item_key, item in self._entries.items()
                    if item.completion.done()
                ]
                if not completed:
                    raise ChannelPayloadRejected("gateway delivery cache is busy")
                _, oldest_key = min(completed)
                self._entries.pop(oldest_key, None)
            owner_token = ""
            remote_pending = False
            if self.store is not None:
                try:
                    durable = self.store.claim(
                        normalized,
                        fingerprint=fingerprint,
                        ttl_seconds=self.ttl_seconds,
                    )
                except ValueError as exc:
                    raise ChannelPayloadRejected(str(exc)) from exc
                status = str(durable.get("status", "processing") or "processing").lower()
                durable_fingerprint = str(durable.get("fingerprint", fingerprint) or fingerprint)
                if durable_fingerprint != fingerprint:
                    raise ChannelPayloadRejected("gateway message id has conflicting content")
                if status == "completed":
                    response = durable.get("response")
                    entry = _GatewayDeliveryEntry(
                        fingerprint=fingerprint,
                        delivery_key=normalized,
                        expires_at=current + self.ttl_seconds,
                    )
                    entry.completion.set_result(_gateway_result_from_plain(response))
                    self._entries[normalized] = entry
                    return False, entry
                if status not in {"owner", "claimed", "processing", "in_flight"}:
                    raise ChannelPayloadRejected("gateway delivery store returned an invalid status")
                owner_token = str(durable.get("owner_token", "") or "")
                remote_pending = status in {"processing", "in_flight"} and not owner_token
            entry = _GatewayDeliveryEntry(
                fingerprint=fingerprint,
                delivery_key=normalized,
                expires_at=current + self.ttl_seconds,
                owner_token=owner_token,
                remote_pending=remote_pending,
            )
            self._entries[normalized] = entry
            return not remote_pending, entry

    def complete(
        self,
        key: str,
        entry: _GatewayDeliveryEntry,
        result: "GatewayDispatchResult",
        *,
        now: float | None = None,
    ) -> None:
        current = time.monotonic() if now is None else float(now)
        normalized_key = _identifier(key, field="gateway delivery key")
        with self._lock:
            current_entry = self._entries.get(normalized_key)
            if current_entry is entry:
                entry.expires_at = current + self.ttl_seconds
                if self.store is not None and entry.owner_token:
                    self.store.complete(
                        normalized_key,
                        fingerprint=entry.fingerprint,
                        owner_token=entry.owner_token,
                        response=_gateway_result_to_plain(result),
                        ttl_seconds=self.ttl_seconds,
                    )
                entry.completion.set_result(result)

    def fail(self, key: str, entry: _GatewayDeliveryEntry) -> None:
        normalized_key = _identifier(key, field="gateway delivery key")
        with self._lock:
            if self._entries.get(normalized_key) is entry:
                if self.store is not None and entry.owner_token:
                    self.store.release(
                        normalized_key,
                        fingerprint=entry.fingerprint,
                        owner_token=entry.owner_token,
                    )
                self._entries.pop(normalized_key, None)
                entry.completion.set_result(None)

    async def wait(self, entry: _GatewayDeliveryEntry) -> "GatewayDispatchResult | None":
        # A hung first delivery must not hold a retry forever. The entry is
        # removed by the first request's failure path; a timeout leaves the
        # duplicate caller with a bounded rejection instead of executing a
        # second turn concurrently.
        if not entry.remote_pending or self.store is None:
            try:
                return await asyncio.wait_for(
                    asyncio.shield(asyncio.wrap_future(entry.completion)), timeout=30
                )
            except TimeoutError:
                return None
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            durable = await asyncio.to_thread(
                self.store.get, entry.delivery_key,
                fingerprint=entry.fingerprint,
            )
            if durable and str(durable.get("status", "")).lower() == "completed":
                result = _gateway_result_from_plain(durable.get("response"))
                if result is not None:
                    with self._lock:
                        entry.remote_pending = False
                        if not entry.completion.done():
                            entry.completion.set_result(result)
                    return result
            await asyncio.sleep(0.05)
        return None


def _header(headers: Mapping[str, Any], name: str) -> str:
    for key, value in headers.items():
        if str(key).lower() == name.lower():
            return str(value or "").strip()
    return ""


def _signed_payload(body: bytes | str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Execute the JSON whose bytes were authenticated, never a side payload."""
    try:
        decoded = json.loads(body)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ChannelPayloadRejected("signed webhook body must be valid JSON") from exc
    if not isinstance(decoded, dict) or decoded != payload:
        raise ChannelPayloadRejected("gateway payload does not match signed body")
    return decoded


def _identifier(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 240:
        raise ChannelPayloadRejected(f"{field} is missing or invalid")
    return text


def _content(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ChannelPayloadRejected("message content is empty")
    return text[:12_000]


def _allowed(value: str, allowlist: frozenset[str]) -> bool:
    return "*" in allowlist or value in allowlist


def _chunks(text: str, limit: int) -> tuple[str, ...]:
    """Split text at useful boundaries without dropping any content."""

    remaining = str(text or "").strip()
    if not remaining:
        return ()
    result: list[str] = []
    while remaining:
        if len(remaining) <= limit:
            result.append(remaining)
            break
        boundary = max(
            remaining.rfind("\n\n", 0, limit + 1),
            remaining.rfind("\n", 0, limit + 1),
            remaining.rfind("。", 0, limit + 1),
            remaining.rfind(" ", 0, limit + 1),
        )
        if boundary < limit // 3:
            boundary = limit
        elif remaining[boundary : boundary + 1] == "。":
            boundary += 1
        chunk = remaining[:boundary].rstrip()
        if not chunk:
            chunk = remaining[:limit]
            boundary = limit
        result.append(chunk)
        remaining = remaining[boundary:].lstrip()
    return tuple(result)


class ChannelGatewayAdapter(Protocol):
    channel: str

    def identity(self, payload: Mapping[str, Any]) -> GatewayIdentity:
        """Return authenticated platform identity without trusting session hints."""

    def parse(self, payload: Mapping[str, Any], *, session_key: str) -> InboundMessage:
        """Normalize one authenticated platform event."""

    def render(self, message: OutboundMessage) -> tuple[dict[str, Any], ...]:
        """Return credential-free platform request bodies."""


@dataclass(frozen=True, slots=True)
class TelegramGatewayAdapter:
    """Normalize Telegram Bot API updates and render sendMessage bodies."""

    allowed_senders: frozenset[str]
    allowed_chats: frozenset[str] = frozenset({"*"})
    channel: str = "telegram"

    def __init__(
        self,
        *,
        allowed_senders: Sequence[str],
        allowed_chats: Sequence[str] = ("*",),
    ) -> None:
        object.__setattr__(self, "allowed_senders", frozenset(str(item) for item in allowed_senders))
        object.__setattr__(self, "allowed_chats", frozenset(str(item) for item in allowed_chats))
        object.__setattr__(self, "channel", "telegram")

    def _parts(
        self, payload: Mapping[str, Any]
    ) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
        if not isinstance(payload, Mapping):
            raise ChannelPayloadRejected("Telegram update must be an object")
        raw = payload.get("message") or payload.get("edited_message")
        if not isinstance(raw, Mapping):
            raise ChannelPayloadRejected("Telegram update has no supported message")
        sender = raw.get("from")
        chat = raw.get("chat")
        if not isinstance(sender, Mapping) or not isinstance(chat, Mapping):
            raise ChannelPayloadRejected("Telegram sender or chat is missing")
        if sender.get("is_bot") is True:
            raise ChannelPayloadRejected("Telegram bot-authored messages are ignored")
        return raw, sender, chat

    def identity(self, payload: Mapping[str, Any]) -> GatewayIdentity:
        raw, sender, chat = self._parts(payload)
        sender_id = _identifier(sender.get("id"), field="Telegram sender")
        chat_id = _identifier(chat.get("id"), field="Telegram chat")
        if not _allowed(sender_id, self.allowed_senders):
            raise ChannelPayloadRejected("Telegram sender is not allowed")
        if not _allowed(chat_id, self.allowed_chats):
            raise ChannelPayloadRejected("Telegram chat is not allowed")
        return GatewayIdentity(
            channel=self.channel,
            sender_id=sender_id,
            chat_id=chat_id,
            message_id=f"telegram:{_identifier(raw.get('message_id'), field='Telegram message')}",
            thread_id=(
                str(raw.get("message_thread_id"))
                if raw.get("message_thread_id") is not None else None
            ),
        )

    def parse(self, payload: Mapping[str, Any], *, session_key: str) -> InboundMessage:
        raw, _sender, _chat = self._parts(payload)
        identity = self.identity(payload)
        trusted_session = _identifier(session_key, field="trusted session key")
        return InboundMessage(
            channel=self.channel,
            sender_id=identity.sender_id,
            chat_id=identity.chat_id,
            content=_content(raw.get("text") or raw.get("caption")),
            message_id=identity.message_id,
            session_key_override=trusted_session,
            metadata={
                "update_id": payload.get("update_id"),
                "message_thread_id": raw.get("message_thread_id"),
                "reply_to_message_id": (
                    raw.get("reply_to_message", {}).get("message_id")
                    if isinstance(raw.get("reply_to_message"), Mapping)
                    else None
                ),
            },
        )

    def render(self, message: OutboundMessage) -> tuple[dict[str, Any], ...]:
        if message.channel != self.channel:
            raise ChannelPayloadRejected("outbound channel does not match Telegram")
        return tuple(
            {
                "method": "sendMessage",
                "chat_id": message.chat_id,
                "text": chunk,
                **(
                    {"reply_parameters": {"message_id": message.reply_to.split(":", 1)[-1]}}
                    if message.reply_to and message.reply_to.startswith("telegram:")
                    else {}
                ),
            }
            for chunk in _chunks(message.content, 4096)
        )


@dataclass(frozen=True, slots=True)
class DiscordGatewayAdapter:
    """Normalize Discord message events and render create-message bodies."""

    allowed_senders: frozenset[str]
    allowed_channels: frozenset[str] = frozenset({"*"})
    channel: str = "discord"

    def __init__(
        self,
        *,
        allowed_senders: Sequence[str],
        allowed_channels: Sequence[str] = ("*",),
    ) -> None:
        object.__setattr__(self, "allowed_senders", frozenset(str(item) for item in allowed_senders))
        object.__setattr__(self, "allowed_channels", frozenset(str(item) for item in allowed_channels))
        object.__setattr__(self, "channel", "discord")

    def _author(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(payload, Mapping):
            raise ChannelPayloadRejected("Discord event must be an object")
        author = payload.get("author")
        if not isinstance(author, Mapping):
            raise ChannelPayloadRejected("Discord author is missing")
        if author.get("bot") is True or payload.get("webhook_id"):
            raise ChannelPayloadRejected("Discord bot/webhook messages are ignored")
        return author

    def identity(self, payload: Mapping[str, Any]) -> GatewayIdentity:
        author = self._author(payload)
        sender_id = _identifier(author.get("id"), field="Discord sender")
        channel_id = _identifier(payload.get("channel_id"), field="Discord channel")
        if not _allowed(sender_id, self.allowed_senders):
            raise ChannelPayloadRejected("Discord sender is not allowed")
        if not _allowed(channel_id, self.allowed_channels):
            raise ChannelPayloadRejected("Discord channel is not allowed")
        return GatewayIdentity(
            channel=self.channel,
            sender_id=sender_id,
            chat_id=channel_id,
            message_id=f"discord:{_identifier(payload.get('id'), field='Discord message')}",
            thread_id=str(payload.get("thread_id")) if payload.get("thread_id") else None,
        )

    def parse(self, payload: Mapping[str, Any], *, session_key: str) -> InboundMessage:
        identity = self.identity(payload)
        trusted_session = _identifier(session_key, field="trusted session key")
        return InboundMessage(
            channel=self.channel,
            sender_id=identity.sender_id,
            chat_id=identity.chat_id,
            content=_content(payload.get("content")),
            message_id=identity.message_id,
            session_key_override=trusted_session,
            metadata={
                "guild_id": payload.get("guild_id"),
                "thread_id": payload.get("thread_id"),
                "referenced_message_id": (
                    payload.get("message_reference", {}).get("message_id")
                    if isinstance(payload.get("message_reference"), Mapping)
                    else None
                ),
            },
        )

    def render(self, message: OutboundMessage) -> tuple[dict[str, Any], ...]:
        if message.channel != self.channel:
            raise ChannelPayloadRejected("outbound channel does not match Discord")
        return tuple(
            {
                "channel_id": message.chat_id,
                "content": chunk,
                **(
                    {"message_reference": {"message_id": message.reply_to.split(":", 1)[-1]}}
                    if message.reply_to and message.reply_to.startswith("discord:")
                    else {}
                ),
            }
            for chunk in _chunks(message.content, 2000)
        )


def _resolve_session(
    resolver: GatewaySessionResolver | Callable[[GatewayIdentity, Mapping[str, Any]], str | None],
    identity: GatewayIdentity,
    payload: Mapping[str, Any],
) -> str:
    if hasattr(resolver, "resolve_session"):
        session_key = resolver.resolve_session(identity, payload)  # type: ignore[union-attr]
    else:
        session_key = resolver(identity, payload)  # type: ignore[operator]
    if not session_key:
        raise ChannelPayloadRejected("gateway identity is not mapped to a session")
    return _identifier(session_key, field="trusted session key")


@dataclass(frozen=True, slots=True)
class GatewayDispatchResult:
    """Credential-free result of one verified platform ingress dispatch."""

    identity: GatewayIdentity
    session_key: str
    result: Any
    outbound: tuple[OutboundMessage, ...]
    deliveries: tuple[dict[str, Any], ...]

    def to_plain(self) -> dict[str, Any]:
        return {
            "identity": {
                "channel": self.identity.channel,
                "sender_id": self.identity.sender_id,
                "chat_id": self.identity.chat_id,
                "message_id": self.identity.message_id,
                "thread_id": self.identity.thread_id,
            },
            "session_key": self.session_key,
            # The host may keep the complete private execution result for
            # durable commit, but a gateway response is public transport
            # output. Apply the same bounded redaction contract as channel
            # metadata before it can cross a webhook boundary.
            "result": _bounded_public(self.result),
            "outbound": [message.to_plain() for message in self.outbound],
            "deliveries": list(self.deliveries),
        }


def _gateway_result_to_plain(value: Any) -> dict[str, Any]:
    """Convert a completed dispatch into the credential-free replay shape."""

    if isinstance(value, GatewayDispatchResult):
        return value.to_plain()
    if isinstance(value, Mapping):
        bounded = _bounded_public(value)
        return dict(bounded) if isinstance(bounded, Mapping) else {"result": bounded}
    return {"result": _bounded_public(value)}


def _gateway_result_from_plain(value: Any) -> Any:
    """Rehydrate a durable replay without exposing private host state."""

    if not isinstance(value, Mapping):
        return value
    identity_raw = value.get("identity")
    if not isinstance(identity_raw, Mapping):
        return dict(value)
    try:
        identity = GatewayIdentity(
            channel=_identifier(identity_raw.get("channel"), field="gateway channel"),
            sender_id=_identifier(identity_raw.get("sender_id"), field="gateway sender"),
            chat_id=_identifier(identity_raw.get("chat_id"), field="gateway chat"),
            message_id=_identifier(identity_raw.get("message_id"), field="gateway message"),
            thread_id=(
                str(identity_raw.get("thread_id"))
                if identity_raw.get("thread_id") is not None else None
            ),
        )
        outbound: list[OutboundMessage] = []
        for raw in value.get("outbound", ()):
            if isinstance(raw, Mapping):
                outbound.append(OutboundMessage(**dict(raw)))
        deliveries = tuple(
            dict(item) for item in value.get("deliveries", ()) if isinstance(item, Mapping)
        )
        return GatewayDispatchResult(
            identity=identity,
            session_key=_identifier(value.get("session_key"), field="gateway session"),
            result=value.get("result"),
            outbound=tuple(outbound),
            deliveries=deliveries,
        )
    except (TypeError, ValueError, KeyError):
        # A host may intentionally persist a generic result rather than the
        # full GatewayDispatchResult. Preserve it as a plain bounded mapping.
        return dict(value)


HostPayloadFactory = Callable[[GatewayIdentity, Mapping[str, Any], str], Mapping[str, Any]]


@dataclass(slots=True)
class VerifiedChannelGateway:
    """Deployment-facing webhook boundary without credentials or network I/O.

    A host route owns raw body parsing, platform secrets, token delivery and
    session repositories.  This object owns the reusable verified-ingress
    sequence: HMAC/replay check, platform allowlist, server-owned session
    resolution, shared MessageBus dispatch and credential-free delivery-body
    rendering.
    """

    adapter: ChannelGatewayAdapter
    signature_policy: WebhookSignaturePolicy
    session_resolver: GatewaySessionResolver | Callable[[GatewayIdentity, Mapping[str, Any]], str | None]
    execute: Callable[[Mapping[str, Any]], Any]
    replay_cache: WebhookReplayCache = field(default_factory=WebhookReplayCache)
    delivery_cache: GatewayDeliveryCache = field(default_factory=GatewayDeliveryCache)
    _dispatch_tasks: set[asyncio.Task] = field(default_factory=set, init=False, repr=False)

    async def dispatch(
        self,
        payload: Mapping[str, Any],
        *,
        body: bytes | str,
        headers: Mapping[str, Any],
        host_payload: Mapping[str, Any] | HostPayloadFactory | None = None,
        now: float | None = None,
    ) -> GatewayDispatchResult:
        if not isinstance(payload, Mapping):
            raise ChannelPayloadRejected("gateway payload must be an object")
        self.signature_policy.verify(
            body, headers, replay_cache=self.replay_cache, now=now
        )
        payload = _signed_payload(body, payload)
        identity = self.adapter.identity(payload)
        trusted_session = _resolve_session(self.session_resolver, identity, payload)
        # Telegram message ids are unique only within a chat. Include the
        # authenticated sender and resolved session so retries can never
        # replay another chat's result or an old session binding's result.
        delivery_key = hashlib.sha256(json.dumps([
            identity.channel, identity.chat_id, identity.sender_id,
            identity.thread_id, trusted_session, identity.message_id,
        ], ensure_ascii=False).encode()).hexdigest()
        fingerprint = hashlib.sha256(json.dumps(
            dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        owner, delivery_entry = self.delivery_cache.claim(delivery_key, fingerprint=fingerprint)
        if not owner:
            cached = await self.delivery_cache.wait(delivery_entry)
            if cached is None:
                raise ChannelPayloadRejected("gateway delivery is still processing")
            return cached
        task = asyncio.create_task(self._dispatch_owned(
            identity, payload, trusted_session, host_payload, delivery_key, delivery_entry
        ))
        self._dispatch_tasks.add(task)

        def finished(completed: asyncio.Task) -> None:
            self._dispatch_tasks.discard(completed)
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(finished)
        # Disconnecting a webhook waiter must not release ownership while a
        # synchronous provider is still executing in its worker thread.
        return await asyncio.shield(task)

    async def _dispatch_owned(
        self,
        identity: GatewayIdentity,
        payload: Mapping[str, Any],
        trusted_session: str,
        host_payload: Mapping[str, Any] | HostPayloadFactory | None,
        delivery_key: str,
        delivery_entry: _GatewayDeliveryEntry,
    ) -> GatewayDispatchResult:
        observed: list[OutboundMessage] = []
        try:
            if callable(host_payload):
                resolved_host_payload = host_payload(identity, payload, trusted_session)
            else:
                resolved_host_payload = host_payload or {}
            if not isinstance(resolved_host_payload, Mapping):
                raise ChannelPayloadRejected("gateway host payload must be an object")
            result = await dispatch_gateway_payload(
                self.adapter,
                payload,
                session_key=trusted_session,
                execute=self.execute,
                host_payload=resolved_host_payload,
                observer=observed.append,
            )
            deliveries: list[dict[str, Any]] = []
            for message in observed:
                deliveries.extend(self.adapter.render(message))
            dispatch_result = GatewayDispatchResult(
                identity=identity,
                session_key=trusted_session,
                result=result,
                outbound=tuple(observed),
                deliveries=tuple(deliveries),
            )
            self.delivery_cache.complete(delivery_key, delivery_entry, dispatch_result)
            return dispatch_result
        except BaseException:
            self.delivery_cache.fail(delivery_key, delivery_entry)
            raise


async def dispatch_gateway_payload(
    adapter: ChannelGatewayAdapter,
    payload: Mapping[str, Any],
    *,
    session_key: str,
    execute: Callable[[Mapping[str, Any]], Any],
    host_payload: Mapping[str, Any],
    observer: OutboundHandler | None = None,
) -> Any:
    """Normalize one platform event and dispatch it through the shared core."""

    inbound = adapter.parse(payload, session_key=session_key)
    return await dispatch_channel_call_async(
        execute,
        inbound,
        host_payload=host_payload,
        observer=observer,
    )


async def dispatch_verified_gateway_payload(
    adapter: ChannelGatewayAdapter,
    payload: Mapping[str, Any],
    *,
    body: bytes | str,
    headers: Mapping[str, Any],
    signature_policy: WebhookSignaturePolicy,
    session_resolver: GatewaySessionResolver
    | Callable[[GatewayIdentity, Mapping[str, Any]], str | None],
    execute: Callable[[Mapping[str, Any]], Any],
    host_payload: Mapping[str, Any],
    replay_cache: WebhookReplayCache | None = None,
    observer: OutboundHandler | None = None,
    now: float | None = None,
) -> Any:
    """Verify platform ingress, resolve a host session, then share Agent Core."""

    signature_policy.verify(body, headers, replay_cache=replay_cache, now=now)
    payload = _signed_payload(body, payload)
    identity = adapter.identity(payload)
    trusted_session = _resolve_session(session_resolver, identity, payload)
    return await dispatch_gateway_payload(
        adapter,
        payload,
        session_key=trusted_session,
        execute=execute,
        host_payload=host_payload,
        observer=observer,
    )


__all__ = [
    "ChannelGatewayAdapter",
    "ChannelPayloadRejected",
    "DiscordGatewayAdapter",
    "GatewayDispatchResult",
    "GatewayDeliveryCache",
    "GatewayDeliveryStore",
    "GatewayIdentity",
    "GatewaySessionResolver",
    "TelegramGatewayAdapter",
    "WebhookReplayCache",
    "VerifiedChannelGateway",
    "WebhookSignaturePolicy",
    "dispatch_gateway_payload",
    "dispatch_verified_gateway_payload",
]
