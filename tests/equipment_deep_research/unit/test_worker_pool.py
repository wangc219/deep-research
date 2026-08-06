from pathlib import Path
from types import SimpleNamespace

from equipment_deep_research.interfaces.worker_pool import ResearchWorkerPool


class _Process:
    def __init__(self, *, exited: bool = False) -> None:
        self.exited = exited

    def poll(self):
        return 1 if self.exited else None


def _pool(tmp_path: Path, monkeypatch, desired: int) -> ResearchWorkerPool:
    monkeypatch.setenv("EQUIPMENT_DR_WORKER_POOL_CONFIG", str(tmp_path / "pool.json"))
    monkeypatch.setenv("EQUIPMENT_DR_RESEARCH_WORKER_CONCURRENCY", str(desired))
    pool = ResearchWorkerPool(
        project_root=tmp_path,
        output_root=tmp_path / "runs",
        database_url=None,
        initial_capacity=desired,
    )
    pool.service = SimpleNamespace(runtime_health=lambda: {"workers": []}, touch_worker=lambda *args, **kwargs: None)
    return pool


def test_reconcile_starts_new_real_slots(tmp_path: Path, monkeypatch) -> None:
    pool = _pool(tmp_path, monkeypatch, 4)
    spawned = []
    monkeypatch.setattr(pool, "_spawn", lambda slot: spawned.append(slot) or _Process())

    pool.reconcile()

    assert spawned == [1, 2, 3, 4]
    assert sorted(pool.processes) == [1, 2, 3, 4]


def test_reconcile_removes_only_idle_slots_when_scaling_down(tmp_path: Path, monkeypatch) -> None:
    pool = _pool(tmp_path, monkeypatch, 2)
    pool.processes = {slot: _Process() for slot in range(1, 5)}
    pool.service = SimpleNamespace(
        runtime_health=lambda: {
            "workers": [
                {"worker_id": "research-worker-3", "status": "idle", "current_run_id": ""},
                {"worker_id": "research-worker-4", "status": "working", "current_run_id": "run-4"},
            ]
        },
        touch_worker=lambda *args, **kwargs: None,
    )
    stopped = []
    monkeypatch.setattr(pool, "_terminate", lambda process: stopped.append(process))

    pool.reconcile()

    assert sorted(pool.processes) == [1, 2, 4]
    assert len(stopped) == 1


def test_reconcile_restarts_an_exited_target_slot(tmp_path: Path, monkeypatch) -> None:
    pool = _pool(tmp_path, monkeypatch, 2)
    pool.processes = {1: _Process(), 2: _Process(exited=True)}
    spawned = []
    monkeypatch.setattr(pool, "_spawn", lambda slot: spawned.append(slot) or _Process())

    pool.reconcile()

    assert spawned == [2]
    assert sorted(pool.processes) == [1, 2]
