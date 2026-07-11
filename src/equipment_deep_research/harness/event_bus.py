from __future__ import annotations

from dataclasses import replace
from threading import Lock
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


class EventBus:
    def __init__(self, *, max_string_length: int = 1000) -> None:
        if max_string_length < 1:
            raise ValueError("max_string_length must be positive")
        self.max_string_length = max_string_length
        self.listener_error_count = 0
        self._sequences: dict[str, int] = {}
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
        with self._lock:
            sequence = self._sequences.get(event.run_id, 0) + 1
            self._sequences[event.run_id] = sequence
            subscribers = list(self._subscribers)

        safe_event = replace(
            event,
            payload=_redact(event.payload, max_string_length=self.max_string_length),
            sequence=sequence,
        )
        for handler, categories, run_id in subscribers:
            if categories is not None and safe_event.category not in categories:
                continue
            if run_id is not None and safe_event.run_id != run_id:
                continue
            try:
                handler(safe_event)
            except Exception:
                with self._lock:
                    self.listener_error_count += 1
        return safe_event


def _redact(value: Any, *, max_string_length: int) -> Any:
    if isinstance(value, dict):
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
