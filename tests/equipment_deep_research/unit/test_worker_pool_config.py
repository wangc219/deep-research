from pathlib import Path

from equipment_deep_research.application.worker_pool_config import (
    ensure_worker_capacity_config,
    read_worker_capacity,
    write_worker_capacity,
)


def _isolate_config(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "worker-pool.json"
    monkeypatch.setenv("EQUIPMENT_DR_WORKER_POOL_CONFIG", str(path))
    return path


def test_worker_capacity_uses_environment_until_config_exists(tmp_path: Path, monkeypatch) -> None:
    path = _isolate_config(tmp_path, monkeypatch)
    monkeypatch.setenv("EQUIPMENT_DR_RESEARCH_WORKER_CONCURRENCY", "3")

    assert read_worker_capacity() == 3
    assert ensure_worker_capacity_config() == 3
    assert path.is_file()


def test_worker_capacity_is_persisted_and_reloaded(tmp_path: Path, monkeypatch) -> None:
    _isolate_config(tmp_path, monkeypatch)

    payload = write_worker_capacity(5, updated_by="analyst")

    assert payload == {"desired_capacity": 5, "updated_by": "analyst"}
    assert read_worker_capacity() == 5


def test_worker_capacity_is_clamped_to_supported_range(tmp_path: Path, monkeypatch) -> None:
    _isolate_config(tmp_path, monkeypatch)

    write_worker_capacity(0)
    assert read_worker_capacity() == 1
    write_worker_capacity(99)
    assert read_worker_capacity() == 8
