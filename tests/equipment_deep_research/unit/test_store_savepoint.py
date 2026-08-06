from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

import pytest

from equipment_deep_research.domain.proposals import (
    DomainWriteProposal,
    TraceProposal,
)
from equipment_deep_research.domain.store import (
    SqliteRunStore,
    StoreConflictError,
    StoreValidationError,
)
from equipment_deep_research.domain import store as store_module
from equipment_deep_research.domain.workspace import RunWorkspace
from equipment_deep_research.harness import session as session_module
from equipment_deep_research.harness.event_bus import EventBus
from equipment_deep_research.harness.events import RuntimeEvent
from equipment_deep_research.harness.session import JsonlSessionStore
from equipment_deep_research.harness.recovery import RecoveryState
from equipment_deep_research.orchestration.runner import _RunResourceScope


CREATED_AT = "2026-07-11T00:00:00+00:00"


def _domain(
    proposal_id: str = "p1",
    *,
    evidence_id: str = "e1",
    idempotency_key: str = "save-e1",
    operation: str = "upsert",
    claim: str = "claim",
) -> DomainWriteProposal:
    return DomainWriteProposal(
        proposal_id,
        "EvidenceCard",
        operation,  # type: ignore[arg-type]
        {
            "evidence_id": evidence_id,
            "claim": claim,
            "schema_version": "1.0",
            "created_at": CREATED_AT,
        },
        idempotency_key,
    )


def _trace(proposal_id: str = "t1", *, evidence_id: str = "e1") -> TraceProposal:
    return TraceProposal(
        proposal_id,
        "evidence_saved",
        "agent-a",
        {"evidence_id": evidence_id},
    )


def test_savepoint_is_atomic_and_idempotent(tmp_path: Path) -> None:
    store = SqliteRunStore(tmp_path / "run.db", run_id="run-1")
    domain = [_domain()]
    trace = [_trace()]

    checkpoint_1 = store.commit(domain, trace)
    checkpoint_2 = store.commit(domain, trace)

    assert checkpoint_1 == checkpoint_2
    assert store.count("EvidenceCard") == 1
    assert store.trace_count() == 1


def test_same_proposal_set_is_idempotent_when_order_changes(tmp_path: Path) -> None:
    store = SqliteRunStore(tmp_path / "run.db", run_id="run-1")
    domain = [
        _domain("p1", evidence_id="e1", idempotency_key="save-e1"),
        _domain("p2", evidence_id="e2", idempotency_key="save-e2"),
    ]
    trace = [_trace("t1", evidence_id="e1"), _trace("t2", evidence_id="e2")]

    first = store.commit(domain, trace)
    second = store.commit(list(reversed(domain)), list(reversed(trace)))

    assert first == second
    assert store.object_count() == 2
    assert store.trace_count() == 2


def test_invalid_object_rolls_back_whole_savepoint(tmp_path: Path) -> None:
    store = SqliteRunStore(tmp_path / "run.db", run_id="run-1")
    invalid_packet = DomainWriteProposal(
        "p2",
        "BaselineFindingPacket",
        "upsert",
        {
            "schema_version": "1.0",
            "created_at": CREATED_AT,
        },
        "save-packet",
    )

    with pytest.raises(StoreValidationError, match="packet_id"):
        store.commit([_domain(), invalid_packet], [_trace()])

    assert store.object_count() == 0
    assert store.trace_count() == 0
    assert store.recover()["last_checkpoint"] is None


def test_unknown_object_type_and_missing_metadata_are_rejected(tmp_path: Path) -> None:
    store = SqliteRunStore(tmp_path / "run.db", run_id="run-1")
    unknown = DomainWriteProposal(
        "p1",
        "MysteryObject",
        "upsert",
        {"object_id": "x", "schema_version": "1.0", "created_at": CREATED_AT},
        "save-x",
    )
    missing_metadata = DomainWriteProposal(
        "p2",
        "EvidenceCard",
        "upsert",
        {"evidence_id": "e1"},
        "save-e1",
    )

    with pytest.raises(StoreValidationError, match="unsupported object_type"):
        store.commit([unknown], [])
    with pytest.raises(StoreValidationError, match="schema_version"):
        store.commit([missing_metadata], [])

    assert store.object_count() == 0


def test_idempotency_key_is_not_used_as_missing_object_id(tmp_path: Path) -> None:
    store = SqliteRunStore(tmp_path / "run.db", run_id="run-1")
    proposal = DomainWriteProposal(
        "p1",
        "EvidenceCard",
        "upsert",
        {"schema_version": "1.0", "created_at": CREATED_AT},
        "e1",
    )

    with pytest.raises(StoreValidationError, match="evidence_id"):
        store.commit([proposal], [])


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        (_domain(claim="changed"), "proposal_id"),
        (_domain("p2", claim="changed"), "idempotency"),
    ],
)
def test_proposal_and_idempotency_conflicts_fail_explicitly(
    tmp_path: Path,
    replacement: DomainWriteProposal,
    message: str,
) -> None:
    store = SqliteRunStore(tmp_path / "run.db", run_id="run-1")
    store.commit([_domain()], [_trace()])

    with pytest.raises(StoreConflictError, match=message):
        store.commit([replacement], [])

    assert store.count("EvidenceCard") == 1
    assert store.trace_count() == 1


def test_trace_proposal_conflict_rolls_back_domain_write(tmp_path: Path) -> None:
    store = SqliteRunStore(tmp_path / "run.db", run_id="run-1")
    store.commit([_domain()], [_trace()])
    conflicting_trace = TraceProposal(
        "t1",
        "different_event",
        "agent-b",
        {"evidence_id": "e2"},
    )

    with pytest.raises(StoreConflictError, match="proposal_id"):
        store.commit(
            [_domain("p2", evidence_id="e2", idempotency_key="save-e2")],
            [conflicting_trace],
        )

    assert store.object_count() == 1
    assert store.trace_count() == 1


def test_exception_during_writes_rolls_back_objects_trace_and_savepoint(
    tmp_path: Path,
) -> None:
    store = SqliteRunStore(tmp_path / "run.db", run_id="run-1")
    store.commit(
        [_domain("existing", operation="append")],
        [],
    )

    with pytest.raises(StoreConflictError, match="append"):
        store.commit(
            [
                _domain("new", evidence_id="e2", idempotency_key="save-e2"),
                _domain(
                    "duplicate",
                    operation="append",
                    idempotency_key="append-e1-again",
                ),
            ],
            [_trace()],
        )

    assert store.object_count() == 1
    assert store.trace_count() == 0
    assert store.recover()["object_count"] == 1


def test_db_preflight_rejects_append_conflict_before_any_domain_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SqliteRunStore(tmp_path / "run.db", run_id="run-1")
    store.commit([_domain("existing", operation="append")], [])
    write_calls = 0
    original_write = store._write_domain

    def spy_write(*args: object, **kwargs: object) -> None:
        nonlocal write_calls
        write_calls += 1
        original_write(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(store, "_write_domain", spy_write)

    with pytest.raises(StoreConflictError, match="append"):
        store.commit(
            [
                _domain("new", evidence_id="e2", idempotency_key="save-e2"),
                _domain(
                    "duplicate",
                    operation="append",
                    idempotency_key="append-e1-again",
                ),
            ],
            [_trace()],
        )

    assert write_calls == 0
    assert store.object_count() == 1
    assert store.trace_count() == 0


def test_db_preflight_rejects_same_batch_object_conflict_before_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SqliteRunStore(tmp_path / "run.db", run_id="run-1")
    write_calls = 0
    original_write = store._write_domain

    def spy_write(*args: object, **kwargs: object) -> None:
        nonlocal write_calls
        write_calls += 1
        original_write(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(store, "_write_domain", spy_write)

    with pytest.raises(StoreConflictError, match="batch object"):
        store.commit(
            [
                _domain("p1", idempotency_key="first-write"),
                _domain("p2", idempotency_key="second-write", claim="changed"),
            ],
            [],
        )

    assert write_calls == 0
    assert store.object_count() == 0


def test_concurrent_identical_commits_share_one_checkpoint(tmp_path: Path) -> None:
    database = tmp_path / "run.db"
    stores = [SqliteRunStore(database, run_id="run-1") for _ in range(4)]

    with ThreadPoolExecutor(max_workers=4) as executor:
        checkpoints = list(
            executor.map(lambda store: store.commit([_domain()], [_trace()]), stores)
        )

    assert len(set(checkpoints)) == 1
    assert stores[0].object_count() == 1
    assert stores[0].trace_count() == 1
    assert all(
        store._connection.execute("PRAGMA journal_mode").fetchone()[0] == "memory"
        for store in stores
        if store._connection is not None
    )
    assert not Path(f"{database}-wal").exists()
    assert not Path(f"{database}-shm").exists()
    for store in stores:
        store.close()


def test_concurrent_event_buses_allocate_unique_durable_runtime_sequences(
    tmp_path: Path,
) -> None:
    database = tmp_path / "run.db"
    stores = [SqliteRunStore(database, run_id="run-1") for _ in range(2)]
    buses = [EventBus(), EventBus()]
    for bus, store in zip(buses, stores, strict=True):
        bus.bind_sequence_allocator("run-1", store.allocate_runtime_event_sequence)

    def publish(index: int) -> int:
        event = buses[index % len(buses)].publish(
            RuntimeEvent("agent_harness", f"event-{index}", "run-1")
        )
        return event.sequence

    with ThreadPoolExecutor(max_workers=8) as executor:
        sequences = list(executor.map(publish, range(80)))

    assert sorted(sequences) == list(range(1, 81))
    assert stores[0].last_runtime_event_sequence() == 80
    for store in stores:
        store.close()


def test_runtime_sequence_state_migrates_existing_database_and_survives_reopen(
    tmp_path: Path,
) -> None:
    database = tmp_path / "run.db"
    legacy = SqliteRunStore(database, run_id="run-1")
    legacy.commit((), (_trace("t1"), _trace("t2"), _trace("t3")))
    legacy.close()
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE IF EXISTS runtime_event_state")

    migrated = SqliteRunStore(database, run_id="run-1")
    assert migrated.last_runtime_event_sequence() == 3
    assert migrated.allocate_runtime_event_sequence() == 4
    migrated.close()

    recovered = SqliteRunStore(database, run_id="run-1")
    assert recovered.last_runtime_event_sequence() == 4
    assert recovered.allocate_runtime_event_sequence() == 5
    recovered.close()


def test_runtime_sequence_allocation_does_not_change_domain_trace_atomicity(
    tmp_path: Path,
) -> None:
    store = SqliteRunStore(tmp_path / "run.db", run_id="run-1")
    assert [store.allocate_runtime_event_sequence() for _ in range(5)] == [
        1,
        2,
        3,
        4,
        5,
    ]

    checkpoint = store.commit([_domain()], [_trace()])
    with pytest.raises(StoreValidationError, match="packet_id"):
        store.commit(
            [
                DomainWriteProposal(
                    "invalid",
                    "BaselineFindingPacket",
                    "upsert",
                    {"schema_version": "1.0", "created_at": CREATED_AT},
                    "invalid",
                )
            ],
            [TraceProposal("rolled-back", "must_not_commit", "agent-a", {})],
        )

    assert checkpoint == store.recover()["last_checkpoint"]
    assert store.object_count() == 1
    assert store.trace_count() == 1
    assert store.last_runtime_event_sequence() == 5


def test_recover_and_trace_export_expose_run_monotonic_sequences(
    tmp_path: Path,
) -> None:
    store = SqliteRunStore(tmp_path / "run.db", run_id="run-1")
    checkpoint = store.commit(
        [_domain()],
        [_trace("t1"), _trace("t2")],
    )

    recovered = store.recover()
    events = store.trace_events(after_sequence=0)

    assert recovered["run_id"] == "run-1"
    assert recovered["checkpoint_id"] == checkpoint
    assert recovered["last_checkpoint"] == checkpoint
    assert recovered["object_count"] == 1
    assert recovered["trace_count"] == 2
    assert recovered["last_trace_sequence"] == 2
    assert recovered["object_counts"] == {"EvidenceCard": 1}
    assert store.last_trace_sequence() == 2
    assert [event["sequence"] for event in events] == [1, 2]
    assert store.trace_events(after_sequence=1)[0]["proposal_id"] == "t2"


def test_exports_are_strict_jsonl_type_payload_records(tmp_path: Path) -> None:
    store = SqliteRunStore(tmp_path / "run.db", run_id="run-1")
    store.commit([_domain()], [_trace()])
    domain_path = tmp_path / "domain.jsonl"
    trace_path = tmp_path / "trace.jsonl"

    store.export_domain_jsonl(domain_path)
    store.export_trace_jsonl(trace_path)

    domain_rows = [json.loads(line) for line in domain_path.read_text().splitlines()]
    trace_rows = [json.loads(line) for line in trace_path.read_text().splitlines()]
    assert domain_rows == [
        {
            "type": "EvidenceCard",
            "payload": {
                "claim": "claim",
                "created_at": CREATED_AT,
                "evidence_id": "e1",
                "schema_version": "1.0",
            },
        }
    ]
    assert trace_rows[0]["type"] == "TraceEvent"
    assert trace_rows[0]["payload"]["sequence"] == 1
    assert trace_rows[0]["payload"]["proposal_id"] == "t1"
    for row in [*domain_rows, *trace_rows]:
        json.dumps(row, allow_nan=False)


def test_jsonl_session_store_appends_flushes_and_reads_tail(tmp_path: Path) -> None:
    path = tmp_path / "agent.jsonl"
    store = JsonlSessionStore("agent.jsonl", root_dir=tmp_path)

    store.append({"sequence": 1, "text": "first"})
    store.append({"sequence": 2, "text": "second\nline"})

    assert store.read_all() == [
        {"sequence": 1, "text": "first"},
        {"sequence": 2, "text": "second\nline"},
    ]
    assert store.read_tail(1) == [{"sequence": 2, "text": "second\nline"}]
    assert store.tail(1) == store.read_tail(1)
    file_descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(file_descriptor)
    finally:
        os.close(file_descriptor)


def test_jsonl_session_store_normalizes_nested_read_only_mappings(
    tmp_path: Path,
) -> None:
    from types import MappingProxyType

    store = JsonlSessionStore("agent.jsonl", root_dir=tmp_path)
    store.append(
        {
            "metadata": MappingProxyType(
                {
                    "usage": MappingProxyType({"input_tokens": 12}),
                    "lanes": (MappingProxyType({"name": "search"}),),
                }
            )
        }
    )

    assert store.read_all() == [
        {
            "metadata": {
                "usage": {"input_tokens": 12},
                "lanes": [{"name": "search"}],
            }
        }
    ]


def test_jsonl_session_store_is_thread_safe_and_rejects_non_finite_values(
    tmp_path: Path,
) -> None:
    store = JsonlSessionStore("nested/agent.jsonl", root_dir=tmp_path)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda value: store.append({"value": value}), range(100)))

    rows = store.read_all()
    assert sorted(row["value"] for row in rows) == list(range(100))
    with pytest.raises(ValueError):
        store.append({"value": float("nan")})
    assert len(store.read_all()) == 100


def test_jsonl_session_path_lock_registry_releases_last_owner(tmp_path: Path) -> None:
    baseline_keys = set(session_module._PATH_LOCKS)
    first = JsonlSessionStore("agent.jsonl", root_dir=tmp_path)
    second = JsonlSessionStore("agent.jsonl", root_dir=tmp_path)
    shared_lock = first._lock

    assert second._lock is shared_lock
    assert len(set(session_module._PATH_LOCKS) - baseline_keys) == 1

    first.close()
    third = JsonlSessionStore("agent.jsonl", root_dir=tmp_path)
    assert third._lock is shared_lock
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(
            executor.map(
                lambda item: item[0].append({"value": item[1]}),
                ((second, 1), (third, 2)),
            )
        )

    second.close()
    third.close()
    assert set(session_module._PATH_LOCKS) == baseline_keys


def test_jsonl_session_store_rejects_symlink(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    root.mkdir()
    target = tmp_path / "target.jsonl"
    target.write_text("", encoding="utf-8")
    link = root / "agent.jsonl"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="symlink"):
        JsonlSessionStore("agent.jsonl", root_dir=root)


def test_jsonl_session_constructor_failure_cannot_double_close_reused_fd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_file = tmp_path / "not-a-directory"
    root_file.write_text("root", encoding="utf-8")
    root_fd = os.open(root_file, os.O_RDONLY)
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("sentinel", encoding="utf-8")
    real_dup = session_module.os.dup
    real_close = session_module.os.close
    owned: list[int] = []
    sentinel_fd: list[int] = []

    def capture_dup(descriptor: int) -> int:
        duplicated = real_dup(descriptor)
        owned.append(duplicated)
        return duplicated

    def reuse_after_close(descriptor: int) -> None:
        real_close(descriptor)
        if owned and descriptor == owned[0] and not sentinel_fd:
            sentinel_fd.append(os.open(sentinel, os.O_RDONLY))

    monkeypatch.setattr(session_module.os, "dup", capture_dup)
    monkeypatch.setattr(session_module.os, "close", reuse_after_close)
    try:
        with pytest.raises(ValueError, match="directory"):
            JsonlSessionStore("agent.jsonl", root_fd=root_fd)
        assert sentinel_fd == owned
        assert os.fstat(sentinel_fd[0]).st_size == len("sentinel")
    finally:
        real_close(root_fd)
        if sentinel_fd:
            real_close(sentinel_fd[0])


def test_jsonl_session_store_rejects_leaf_replaced_after_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sessions"
    root.mkdir()
    target = root / "agent.jsonl"
    target.write_text("existing\n", encoding="utf-8")
    external = tmp_path / "external-session.jsonl"
    external.write_text("external\n", encoding="utf-8")
    store = JsonlSessionStore("agent.jsonl", root_dir=root)
    real_open_at = session_module._open_at

    def racing_open_at(
        path: str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int,
    ) -> int:
        if path == "agent.jsonl" and flags & os.O_APPEND:
            target.unlink()
            target.symlink_to(external)
        return real_open_at(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(session_module, "_open_at", racing_open_at)

    with pytest.raises(ValueError, match="symlink"):
        store.append({"blocked": True})

    assert external.read_text(encoding="utf-8") == "external\n"


def test_jsonl_session_store_rejects_ancestor_symlink(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        JsonlSessionStore("linked/agent.jsonl", root_dir=root)


def test_jsonl_session_store_anchor_rejects_replaced_session_component(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "runs"
    sessions = output_root / "run-1" / "agent_sessions"
    sessions.mkdir(parents=True)
    store = JsonlSessionStore(
        "run-1/agent_sessions/agent.jsonl",
        anchor_dir=output_root.resolve(strict=True),
    )
    external = tmp_path / "external-sessions"
    external.mkdir()
    sessions.rmdir()
    sessions.symlink_to(external, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        store.append({"blocked": True})

    assert list(external.iterdir()) == []


def test_jsonl_session_store_root_fd_remains_bound_after_path_replacement(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    root_fd = os.open(sessions, os.O_RDONLY | os.O_DIRECTORY)
    store = JsonlSessionStore("agent.jsonl", root_fd=root_fd)
    os.close(root_fd)
    bound = tmp_path / "bound-sessions"
    sessions.rename(bound)
    attacker = tmp_path / "attacker-sessions"
    attacker.mkdir()
    sessions.symlink_to(attacker, target_is_directory=True)

    store.append({"bound": True})
    store.close()

    assert (bound / "agent.jsonl").is_file()
    assert list(attacker.iterdir()) == []


@pytest.mark.parametrize("candidate", ["../outside.jsonl", "nested/../../outside.jsonl"])
def test_jsonl_session_store_rejects_paths_outside_root(
    tmp_path: Path,
    candidate: str,
) -> None:
    root = tmp_path / "sessions"
    root.mkdir()

    with pytest.raises(ValueError, match="within root_dir"):
        JsonlSessionStore(candidate, root_dir=root)

    with pytest.raises(ValueError, match="within root_dir"):
        JsonlSessionStore(tmp_path / "outside.jsonl", root_dir=root)


def test_jsonl_session_store_resolves_trusted_root_symlink(tmp_path: Path) -> None:
    real_root = tmp_path / "real-sessions"
    real_root.mkdir()
    root_alias = tmp_path / "sessions-alias"
    root_alias.symlink_to(real_root, target_is_directory=True)

    store = JsonlSessionStore("agent.jsonl", root_dir=root_alias)
    store.append({"ok": True})

    assert store.read_all() == [{"ok": True}]
    assert (real_root / "agent.jsonl").is_file()


def test_jsonl_session_store_accepts_resolved_tmp_root() -> None:
    with TemporaryDirectory(dir="/tmp") as directory:
        requested_root = Path(directory)
        store = JsonlSessionStore("agent.jsonl", root_dir=requested_root)

        store.append({"root": "resolved"})

        assert store.root_dir == requested_root.resolve(strict=True)
        assert store.read_all() == [{"root": "resolved"}]


@pytest.mark.parametrize("missing", ["dir_fd", "O_NOFOLLOW", "O_DIRECTORY"])
def test_jsonl_session_store_fails_closed_when_secure_capability_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    target = tmp_path / "nested" / "agent.jsonl"
    if missing == "dir_fd":
        monkeypatch.setattr(session_module.os, "supports_dir_fd", set())
    else:
        monkeypatch.setattr(session_module.os, missing, 0)

    with pytest.raises(RuntimeError, match="secure session path operations require"):
        JsonlSessionStore("nested/agent.jsonl", root_dir=tmp_path)

    assert not target.exists()


@pytest.mark.parametrize("operation", ["append", "read"])
def test_jsonl_session_store_io_fails_closed_without_opening_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    target = tmp_path / "agent.jsonl"
    store = JsonlSessionStore("agent.jsonl", root_dir=tmp_path)
    real_open = session_module.os.open
    open_calls: list[object] = []

    def tracking_open(*args: object, **kwargs: object) -> int:
        open_calls.append(args[0])
        return real_open(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(session_module.os, "supports_dir_fd", set())
    monkeypatch.setattr(session_module.os, "open", tracking_open)

    with pytest.raises(RuntimeError, match="secure session path operations"):
        if operation == "append":
            store.append({"unsafe": False})
        else:
            store.read_all()

    assert open_calls == []
    assert not target.exists()


def test_store_validates_created_at_is_timezone_aware(tmp_path: Path) -> None:
    store = SqliteRunStore(tmp_path / "run.db", run_id="run-1")
    proposal = DomainWriteProposal(
        "p1",
        "EvidenceCard",
        "upsert",
        {
            "evidence_id": "e1",
            "schema_version": "1.0",
            "created_at": datetime.now().isoformat(),
        },
        "save-e1",
    )

    with pytest.raises(StoreValidationError, match="timezone"):
        store.commit([proposal], [])


def test_store_rejects_non_finite_payload_without_partial_write(tmp_path: Path) -> None:
    store = SqliteRunStore(tmp_path / "run.db", run_id="run-1")

    with pytest.raises(ValueError):
        proposal = _domain()
        object.__setattr__(proposal, "payload", {**dict(proposal.payload), "score": float("inf")})
        store.commit([proposal], [_trace()])

    assert store.object_count() == 0
    assert store.trace_count() == 0


def test_sqlite_store_close_releases_persistent_connection(tmp_path: Path) -> None:
    store = SqliteRunStore(tmp_path / "run.db", run_id="run-1")

    store.close()

    with pytest.raises(RuntimeError, match="closed"):
        store.recover()


def test_unbound_sqlite_path_api_does_not_require_descriptor_auditing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable() -> Path:
        raise RuntimeError("SQLite descriptor auditing is unavailable")

    monkeypatch.setattr(store_module, "_descriptor_directory", unavailable)
    store = SqliteRunStore(tmp_path / "run.db", run_id="run-1")
    try:
        assert store.object_count() == 0
    finally:
        store.close()


@pytest.mark.parametrize("failure_stage", ["database_dup", "directory_dup", "audit"])
def test_bound_sqlite_constructor_releases_partial_fd_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    workspace = RunWorkspace.create(tmp_path / "runs", "run-1")
    database_fd = workspace.dup_database_fd()
    directory_fd = workspace.dup_run_fd()
    real_dup = store_module.os.dup
    duplicated: list[int] = []
    calls = 0

    def injected_dup(descriptor: int) -> int:
        nonlocal calls
        calls += 1
        if failure_stage == "database_dup" and calls == 1:
            raise OSError("injected database dup failure")
        if failure_stage == "directory_dup" and calls == 2:
            raise OSError("injected directory dup failure")
        value = real_dup(descriptor)
        duplicated.append(value)
        return value

    monkeypatch.setattr(store_module.os, "dup", injected_dup)
    if failure_stage == "audit":
        monkeypatch.setattr(
            store_module,
            "_open_descriptor_stats",
            lambda: (_ for _ in ()).throw(RuntimeError("injected audit failure")),
        )
    try:
        with pytest.raises((RuntimeError, ValueError), match="injected|must be open"):
            SqliteRunStore(
                workspace.database_path,
                run_id="run-1",
                database_fd=database_fd,
                database_dir_fd=directory_fd,
            )
        for descriptor in duplicated:
            with pytest.raises(OSError):
                os.fstat(descriptor)
        os.fstat(database_fd)
        os.fstat(directory_fd)
    finally:
        os.close(database_fd)
        os.close(directory_fd)
        workspace.close()


@pytest.mark.parametrize("failure_stage", ["database", "directory"])
def test_workspace_store_factory_releases_acquired_inputs_on_dup_failure(
    tmp_path: Path,
    failure_stage: str,
) -> None:
    database = tmp_path / "run.db"
    database.touch()
    database_source = os.open(database, os.O_RDWR)
    directory_source = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    acquired: list[int] = []

    class FailingWorkspace:
        database_path = database

        def dup_database_fd(self) -> int:
            if failure_stage == "database":
                raise OSError("injected database acquisition failure")
            descriptor = os.dup(database_source)
            acquired.append(descriptor)
            return descriptor

        def dup_run_fd(self) -> int:
            raise OSError("injected directory acquisition failure")

    try:
        with pytest.raises(OSError, match="injected"):
            SqliteRunStore.for_workspace(FailingWorkspace(), run_id="run-1")  # type: ignore[arg-type]
        for descriptor in acquired:
            with pytest.raises(OSError):
                os.fstat(descriptor)
    finally:
        os.close(database_source)
        os.close(directory_source)


@pytest.mark.parametrize("close_position", [1, 2])
def test_workspace_store_factory_closes_all_inputs_when_one_close_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    close_position: int,
) -> None:
    database = tmp_path / "run.db"
    database.touch()
    database_source = os.open(database, os.O_RDWR)
    directory_source = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    acquired: list[int] = []

    class Workspace:
        database_path = database

        def dup_database_fd(self) -> int:
            descriptor = os.dup(database_source)
            acquired.append(descriptor)
            return descriptor

        def dup_run_fd(self) -> int:
            descriptor = os.dup(directory_source)
            acquired.append(descriptor)
            return descriptor

    class StubStore(SqliteRunStore):
        instance: "StubStore | None" = None

        def __init__(self, *args: object, **kwargs: object) -> None:
            self.closed = False
            type(self).instance = self

        def close(self) -> None:
            self.closed = True

    real_close = store_module.os.close
    close_calls = 0

    def injected_close(descriptor: int) -> None:
        nonlocal close_calls
        close_calls += 1
        real_close(descriptor)
        if close_calls == close_position:
            raise OSError(f"injected close failure {close_position}")

    monkeypatch.setattr(store_module.os, "close", injected_close)
    try:
        with pytest.raises(OSError, match="injected close failure"):
            StubStore.for_workspace(Workspace(), run_id="run-1")  # type: ignore[arg-type]
        assert StubStore.instance is not None and StubStore.instance.closed
        for descriptor in acquired:
            with pytest.raises(OSError):
                os.fstat(descriptor)
    finally:
        real_close(database_source)
        real_close(directory_source)


def test_sqlite_close_failure_still_releases_every_owned_descriptor(tmp_path: Path) -> None:
    store = SqliteRunStore(tmp_path / "run.db", run_id="run-1")
    store.close()
    database_fd = os.open(tmp_path / "run.db", os.O_RDWR)
    directory_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    sqlite_fd = os.dup(database_fd)

    class FailingConnection:
        def close(self) -> None:
            raise RuntimeError("injected SQLite close failure")

    store._connection = FailingConnection()  # type: ignore[assignment]
    store._database_fd = database_fd
    store._database_dir_fd = directory_fd
    store._sqlite_handle_fd = sqlite_fd

    with pytest.raises(RuntimeError, match="injected SQLite close failure"):
        store.close()

    for descriptor in (database_fd, directory_fd, sqlite_fd):
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_resource_scopes_close_workspace_after_store_close_failure() -> None:
    events: list[str] = []

    class FailingStore:
        def close(self) -> None:
            events.append("store")
            raise RuntimeError("injected close failure")

    class Workspace:
        def close(self) -> None:
            events.append("workspace")

    scope = _RunResourceScope()
    scope.sqlite_store = FailingStore()  # type: ignore[assignment]
    scope.workspace = Workspace()  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="injected close failure"):
        scope.close()
    assert events == ["store", "workspace"]

    events.clear()
    state = object.__new__(RecoveryState)
    object.__setattr__(state, "sqlite_store", FailingStore())
    object.__setattr__(state, "workspace", Workspace())
    with pytest.raises(RuntimeError, match="injected close failure"):
        state.close()
    assert events == ["store", "workspace"]


def test_run_resource_scope_closes_provider_and_all_resources_after_failure() -> None:
    events: list[str] = []

    class Scheduler:
        def close(self) -> None:
            events.append("scheduler")
            raise RuntimeError("scheduler close failed")

    class Provider:
        def close(self) -> None:
            events.append("provider")

    class Store:
        def close(self) -> None:
            events.append("store")

    class Workspace:
        def close(self) -> None:
            events.append("workspace")

    scope = _RunResourceScope()
    scope.scheduler = Scheduler()  # type: ignore[assignment]
    scope.provider = Provider()
    scope.sqlite_store = Store()  # type: ignore[assignment]
    scope.workspace = Workspace()  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="scheduler close failed"):
        scope.close()

    assert events == ["scheduler", "provider", "store", "workspace"]
