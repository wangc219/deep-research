"""Async event stream used by providers and the agent loop.

A lightweight async-iterable queue: producers ``push`` events and call ``end``
(with an optional final result) or ``error``; consumers iterate with
``async for``. Backed by :class:`asyncio.Queue`, so consumers await rather than
busy-wait.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncIterator


_DONE = object()


@dataclass
class StreamErrorEvent:
    """Terminal event emitted by :meth:`AsyncEventStream.error`."""

    message: str
    type: str = "error"

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "message": self.message}


class StreamError(RuntimeError):
    """Raised by :meth:`AsyncEventStream.result` when the stream errored."""


class AsyncEventStream:
    """An async iterable of events with a single final result.

    ``push`` adds an event. ``end`` finishes the stream and records the final
    result returned by ``result()``. ``error`` emits a terminal
    :class:`StreamErrorEvent`, finishes the stream, and marks ``result()`` to
    raise.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._finished = False
        self._result: Any = None
        self._error: str | None = None

    def push(self, event: Any) -> None:
        if self._finished:
            raise RuntimeError("cannot push onto a finished stream")
        self._queue.put_nowait(event)

    def end(self, result: Any = None) -> None:
        if self._finished:
            return
        self._finished = True
        self._result = result
        self._queue.put_nowait(_DONE)

    def error(self, message: str) -> None:
        if self._finished:
            return
        self._error = message
        self._queue.put_nowait(StreamErrorEvent(message=message))
        self._finished = True
        self._queue.put_nowait(_DONE)

    def result(self) -> Any:
        if self._error is not None:
            raise StreamError(self._error)
        return self._result

    async def __aiter__(self) -> AsyncIterator[Any]:
        while True:
            item = await self._queue.get()
            if item is _DONE:
                return
            yield item
