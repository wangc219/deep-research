import pytest

from equipment_deep_research.harness.scoped_registry import ScopedRegistry


def test_child_scope_can_override_and_hide_without_mutating_parent() -> None:
    root = ScopedRegistry("root", {"search": "root-search", "write": "root-write"})
    child = root.child(
        "run-1",
        {"search": "run-search", "read": "run-read"},
        hidden=frozenset({"write"}),
    )

    assert dict(root.snapshot()) == {"search": "root-search", "write": "root-write"}
    assert dict(child.snapshot()) == {"search": "run-search", "read": "run-read"}
    assert child.require("search") == "run-search"
    assert child.get("write") is None


def test_nested_scope_inherits_only_current_visible_bindings() -> None:
    root = ScopedRegistry("root", {"a": 1, "b": 2})
    run = root.child("run", {"b": 3})
    turn = run.child("turn", {"c": 4}, hidden=frozenset({"a"}))

    assert dict(turn.snapshot()) == {"b": 3, "c": 4}
    with pytest.raises(KeyError):
        turn.require("a")


@pytest.mark.parametrize("scope_id", ["", "   "])
def test_scope_id_must_be_explicit(scope_id: str) -> None:
    with pytest.raises(ValueError, match="scope_id"):
        ScopedRegistry(scope_id)
