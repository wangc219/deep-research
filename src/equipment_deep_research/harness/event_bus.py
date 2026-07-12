from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
import re
from threading import Event as CompletionEvent
from threading import Lock, get_ident
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from equipment_deep_research.harness.events import RuntimeEvent


EventHandler = Callable[[RuntimeEvent], None]

_SENSITIVE_KEY_SUFFIXES = (
    "authorization",
    "apikey",
    "accesstoken",
    "refreshtoken",
    "password",
    "secret",
    "token",
    "cookie",
    "credential",
    "credentials",
    "privatekey",
)
_URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_PEM_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
    r"-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_COOKIE_HEADER_PATTERN = re.compile(
    r"(?i)\b(?:cookie|set-cookie)\s*:\s*[^\r\n]+"
)
_CREDENTIAL_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?:access[_-]?token|refresh[_-]?token|api[_-]?key|token|password|"
    r"secret|cookie|authorization)\b\s*[:=]\s*"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)


@dataclass
class _Delivery:
    event: RuntimeEvent
    subscribers: list[tuple[EventHandler, set[str] | None, str | None]]
    completed: CompletionEvent = field(default_factory=CompletionEvent)


@dataclass
class _RunQueue:
    deliveries: deque[_Delivery] = field(default_factory=deque)
    draining: bool = False
    drainer_thread_id: int | None = None


class EventBus:
    def __init__(
        self,
        *,
        max_string_length: int = 1000,
        initial_sequences: Mapping[str, int] | None = None,
    ) -> None:
        if max_string_length < 1:
            raise ValueError("max_string_length must be positive")
        self.max_string_length = max_string_length
        self.listener_error_count = 0
        self._sequences: dict[str, int] = {}
        self._run_queues: dict[str, _RunQueue] = {}
        self._subscribers: list[tuple[EventHandler, set[str] | None, str | None]] = []
        self._lock = Lock()
        for run_id, sequence in (initial_sequences or {}).items():
            self.seed(str(run_id), sequence)

    def seed(self, run_id: str, sequence: int) -> None:
        """Advance a run to an authoritative persisted sequence without rewinding."""
        if not run_id:
            raise ValueError("run_id must not be empty")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ValueError("sequence seed must be a non-negative integer")
        with self._lock:
            self._sequences[run_id] = max(self._sequences.get(run_id, 0), sequence)

    def subscribe(
        self,
        handler: EventHandler,
        *,
        categories: set[str] | None = None,
        run_id: str | None = None,
    ) -> Callable[[], None]:
        record = (handler, set(categories) if categories else None, run_id)
        with self._lock:
            self._subscribers.append(record)

        def unsubscribe() -> None:
            with self._lock:
                try:
                    self._subscribers.remove(record)
                except ValueError:
                    pass

        return unsubscribe

    def publish(self, event: RuntimeEvent) -> RuntimeEvent:
        """Publish synchronously, except same-run reentrant calls only enqueue.

        A normal concurrent publisher returns after its own event has reached all
        matching listeners. A listener that publishes to the run currently being
        drained returns after enqueueing, which avoids deadlock; that nested event
        is delivered after every listener for the current event has returned.
        """
        safe_payload = sanitize_runtime_payload(
            event.payload,
            max_string_length=self.max_string_length,
        )
        current_thread_id = get_ident()
        with self._lock:
            sequence = self._sequences.get(event.run_id, 0) + 1
            self._sequences[event.run_id] = sequence
            safe_event = replace(event, payload=safe_payload, sequence=sequence)
            delivery = _Delivery(safe_event, list(self._subscribers))
            run_queue = self._run_queues.setdefault(event.run_id, _RunQueue())
            run_queue.deliveries.append(delivery)
            is_reentrant = (
                run_queue.draining
                and run_queue.drainer_thread_id == current_thread_id
            )
            should_drain = not run_queue.draining
            if should_drain:
                run_queue.draining = True
                run_queue.drainer_thread_id = current_thread_id

        if should_drain:
            self._drain(run_queue)
        elif not is_reentrant:
            delivery.completed.wait()
        return safe_event

    def _drain(self, run_queue: _RunQueue) -> None:
        process_error: KeyboardInterrupt | SystemExit | None = None
        while True:
            with self._lock:
                if not run_queue.deliveries:
                    run_queue.draining = False
                    run_queue.drainer_thread_id = None
                    break
                delivery = run_queue.deliveries.popleft()
            try:
                self._deliver(delivery)
            except (KeyboardInterrupt, SystemExit) as exc:
                if process_error is None:
                    process_error = exc
            finally:
                delivery.completed.set()
        if process_error is not None:
            raise process_error

    def _deliver(self, delivery: _Delivery) -> None:
        for handler, categories, run_id in delivery.subscribers:
            safe_event = delivery.event
            if categories is not None and safe_event.category not in categories:
                continue
            if run_id is not None and safe_event.run_id != run_id:
                continue
            try:
                handler(safe_event)
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException:
                with self._lock:
                    self.listener_error_count += 1


def sanitize_runtime_payload(value: Any, *, max_string_length: int = 1000) -> Any:
    """Return a recursively redacted, truncated plain-JSON projection."""
    if max_string_length < 1:
        raise ValueError("max_string_length must be positive")
    if isinstance(value, Mapping):
        return {
            str(key): (
                "<redacted>"
                if _is_sensitive_key(str(key))
                else sanitize_runtime_payload(
                    item,
                    max_string_length=max_string_length,
                )
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            sanitize_runtime_payload(item, max_string_length=max_string_length)
            for item in value
        ]
    if isinstance(value, str):
        safe = _sanitize_string(value)
        if len(safe) > max_string_length:
            return safe[:max_string_length].rstrip() + "<truncated>"
        return safe
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = "".join(character for character in key.lower() if character.isalnum())
    return normalized.endswith(_SENSITIVE_KEY_SUFFIXES)


def _sanitize_string(value: str) -> str:
    safe = _PEM_PRIVATE_KEY_PATTERN.sub("<redacted-private-key>", value)
    safe = _URL_PATTERN.sub(_sanitize_url_match, safe)
    safe = _COOKIE_HEADER_PATTERN.sub("Cookie: <redacted>", safe)
    safe = _BEARER_PATTERN.sub("Bearer <redacted>", safe)
    return _CREDENTIAL_ASSIGNMENT_PATTERN.sub(_redact_assignment, safe)


def _sanitize_url_match(match: re.Match[str]) -> str:
    value = match.group(0)
    try:
        parts = urlsplit(value)
        query = parse_qsl(parts.query, keep_blank_values=True)
    except ValueError:
        return "<redacted-url>"
    if not query and parts.username is None and parts.password is None:
        return value

    changed = False
    safe_query: list[tuple[str, str]] = []
    for key, item in query:
        if _is_sensitive_key(key):
            safe_query.append((key, "<redacted>"))
            changed = True
        else:
            safe_query.append((key, item))

    try:
        hostname = parts.hostname or ""
        if parts.port is not None:
            hostname = f"{hostname}:{parts.port}"
    except ValueError:
        return "<redacted-url>"
    netloc = hostname
    if parts.username is not None or parts.password is not None:
        netloc = f"<redacted>@{hostname}"
        changed = True
    if not changed:
        return value
    return urlunsplit(
        (
            parts.scheme,
            netloc,
            parts.path,
            urlencode(safe_query, doseq=True),
            parts.fragment,
        )
    )


def _redact_assignment(match: re.Match[str]) -> str:
    prefix = re.split(r"[:=]", match.group(0), maxsplit=1)[0].strip()
    return f"{prefix}=<redacted>"


__all__ = ["EventBus", "EventHandler", "sanitize_runtime_payload"]
