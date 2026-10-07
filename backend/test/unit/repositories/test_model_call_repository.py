"""模型计量本地持久队列在数据库故障后可幂等补写。"""

import sqlite3

from platform_core.repositories import model_call_repository as repository

record_model_call = repository.record_model_call


def _row(call_id: str = "call-1") -> dict:
    return {
        "id": call_id,
        "model_spec": "provider:model",
        "surface": "知识库嵌入",
        "run_id": "",
        "phase": "",
        "status": "completed",
        "duration_ms": 12.5,
        "input_tokens": 3,
        "output_tokens": 2,
        "total_tokens": 5,
        "error_type": "",
    }


def _pending(path) -> int:
    with sqlite3.connect(path) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM pending_model_calls").fetchone()[0])


def test_database_outage_keeps_call_until_recovery(tmp_path, monkeypatch):
    path = tmp_path / "model-calls.db"
    monkeypatch.setenv(repository.OUTBOX_ENV, str(path))

    def unavailable(_rows):
        raise ConnectionError("postgres unavailable")

    monkeypatch.setattr(repository, "_insert_model_calls", unavailable)
    record_model_call(_row())
    assert _pending(path) == 1

    inserted = []
    monkeypatch.setattr(repository, "_insert_model_calls", lambda rows: inserted.extend(rows))
    result = repository.flush_pending_model_calls()
    assert result == {"flushed": 1, "pending": 0}
    assert inserted == [_row()]


def test_repeated_call_id_is_queued_and_replayed_once(tmp_path, monkeypatch):
    path = tmp_path / "model-calls.db"
    monkeypatch.setenv(repository.OUTBOX_ENV, str(path))
    monkeypatch.setattr(repository, "_insert_model_calls", lambda _rows: (_ for _ in ()).throw(ConnectionError()))
    record_model_call(_row())
    record_model_call(_row())
    assert _pending(path) == 1


def test_without_outbox_uses_postgres_directly(monkeypatch):
    monkeypatch.delenv(repository.OUTBOX_ENV, raising=False)
    inserted = []
    monkeypatch.setattr(repository, "_insert_model_calls", lambda rows: inserted.extend(rows))
    record_model_call(_row())
    assert inserted == [_row()]
