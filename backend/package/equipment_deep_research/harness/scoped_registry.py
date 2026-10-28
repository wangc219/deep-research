"""Immutable hierarchical registrations for one agent execution scope."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Generic, TypeVar


T = TypeVar("T")
_MISSING = object()


class ScopedRegistry(Generic[T]):
    """作用域注册表；子作用域可覆盖或隐藏绑定且不会污染父作用域。"""

    def __init__(
        self,
        scope_id: str,
        bindings: Mapping[str, T] | None = None,
        *,
        parent: ScopedRegistry[T] | None = None,
        hidden: frozenset[str] | None = None,
    ) -> None:
        normalized_scope_id = str(scope_id).strip()
        if not normalized_scope_id:
            raise ValueError("scope_id must not be empty")
        normalized_bindings = {str(key): value for key, value in (bindings or {}).items()}
        if any(not key for key in normalized_bindings):
            raise ValueError("registry keys must not be empty")
        normalized_hidden = frozenset(str(key) for key in (hidden or ()))
        if "" in normalized_hidden:
            raise ValueError("hidden registry keys must not be empty")
        if set(normalized_bindings) & normalized_hidden:
            raise ValueError("a scope cannot both bind and hide the same key")

        self.scope_id = normalized_scope_id
        self.parent = parent
        self._bindings = MappingProxyType(normalized_bindings)
        self._hidden = normalized_hidden

    def child(
        self,
        scope_id: str,
        bindings: Mapping[str, T] | None = None,
        *,
        hidden: frozenset[str] | None = None,
    ) -> ScopedRegistry[T]:
        """创建隔离子作用域，适合 Run、Turn 或插件生命周期。"""

        return ScopedRegistry(
            scope_id,
            bindings,
            parent=self,
            hidden=hidden,
        )

    def get(self, key: str, default: T | None = None) -> T | None:
        value = self._lookup(str(key))
        return default if value is _MISSING else value

    def require(self, key: str) -> T:
        value = self._lookup(str(key))
        if value is _MISSING:
            raise KeyError(key)
        return value

    def snapshot(self) -> Mapping[str, T]:
        """返回当前作用域可见绑定的只读快照。"""

        visible = dict(self.parent.snapshot()) if self.parent is not None else {}
        for key in self._hidden:
            visible.pop(key, None)
        visible.update(self._bindings)
        return MappingProxyType(visible)

    def _lookup(self, key: str) -> T | object:
        if key in self._bindings:
            return self._bindings[key]
        if key in self._hidden or self.parent is None:
            return _MISSING
        return self.parent._lookup(key)


__all__ = ["ScopedRegistry"]
