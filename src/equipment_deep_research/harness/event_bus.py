from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from threading import Event as CompletionEvent
from threading import Lock, get_ident
from typing import Any, Callable

from equipment_deep_research.harness.events import RuntimeEvent


EventHandler = Callable[[RuntimeEvent], None]

_SENSITIVE_KEY_SUFFIXES = (
    "authorization",
    "apikey",
    "password",
    "secret",
    "token",
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
    def __init__(self, *, max_string_length: int = 1000) -> None:
        if max_string_length < 1:
            raise ValueError("max_string_length must be positive")
        self.max_string_length = max_string_length
        self.listener_error_count = 0
        self._sequences: dict[str, int] = {}
        self._run_queues: dict[str, _RunQueue] = {}
        self._subscribers: list[tuple[EventHandler, set[str] | None, str | None]] = []
        self._lock = Lock()

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
        safe_payload = _redact(event.payload, max_string_length=self.max_string_length)
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
        while True:
            with self._lock:
                if not run_queue.deliveries:
                    run_queue.draining = False
                    run_queue.drainer_thread_id = None
                    return
                delivery = run_queue.deliveries.popleft()
            self._deliver(delivery)
            delivery.completed.set()

    def _deliver(self, delivery: _Delivery) -> None:
        for handler, categories, run_id in delivery.subscribers:
            safe_event = delivery.event
            if categories is not None and safe_event.category not in categories:
                continue
            if run_id is not None and safe_event.run_id != run_id:
                continue
            try:
                handler(safe_event)
            except Exception:
                with self._lock:
                    self.listener_error_count += 1


def _redact(value: Any, *, max_string_length: int) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): (
                "<redacted>"
                if _is_sensitive_key(str(key))
                else _redact(item, max_string_length=max_string_length)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item, max_string_length=max_string_length) for item in value]
    if isinstance(value, str) and len(value) > max_string_length:
        return value[:max_string_length].rstrip() + "<truncated>"
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = "".join(character for character in key.lower() if character.isalnum())
    return normalized.endswith(_SENSITIVE_KEY_SUFFIXES)
