from pathlib import Path
import subprocess
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
                {"worker_id": pool._worker_id(3), "status": "idle", "current_run_id": ""},
                {"worker_id": pool._worker_id(4), "status": "working", "current_run_id": "run-4"},
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


def test_reconcile_adds_replacement_for_internal_s6_owner(
    tmp_path: Path, monkeypatch
) -> None:
    pool = _pool(tmp_path, monkeypatch, 2)
    pool.service = SimpleNamespace(
        runtime_health=lambda: {
            "workers": [
                {
                    "worker_id": pool._worker_id(1),
                    "status": "internal",
                    "current_run_id": "run-s6",
                    "online": True,
                },
                {
                    "worker_id": pool._worker_id(2),
                    "status": "idle",
                    "current_run_id": "",
                    "online": True,
                },
            ]
        },
        touch_worker=lambda *args, **kwargs: None,
    )
    spawned = []
    monkeypatch.setattr(pool, "_spawn", lambda slot: spawned.append(slot) or _Process())

    pool.reconcile()

    assert spawned == [3]
    assert sorted(pool.processes) == [3]


def test_reconcile_ignores_an_online_worker_from_an_older_generation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pool = _pool(tmp_path, monkeypatch, 2)
    pool.service = SimpleNamespace(
        runtime_health=lambda: {
            "workers": [
                {
                    "worker_id": "research-worker-1",
                    "status": "working",
                    "current_run_id": "run-active",
                    "online": True,
                }
            ]
        },
        touch_worker=lambda *args, **kwargs: None,
    )
    spawned = []
    monkeypatch.setattr(pool, "_spawn", lambda slot: spawned.append(slot) or _Process())

    pool.reconcile()

    assert spawned == [1, 2]
    assert sorted(pool.processes) == [1, 2]


def test_reconcile_does_not_duplicate_same_generation_external_slot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pool = _pool(tmp_path, monkeypatch, 2)
    pool.service = SimpleNamespace(
        runtime_health=lambda: {
            "workers": [
                {
                    "worker_id": pool._worker_id(1),
                    "status": "working",
                    "current_run_id": "run-active",
                    "online": True,
                }
            ]
        },
        touch_worker=lambda *args, **kwargs: None,
    )
    spawned = []
    monkeypatch.setattr(pool, "_spawn", lambda slot: spawned.append(slot) or _Process())

    pool.reconcile()

    assert spawned == [2]
    assert sorted(pool.processes) == [2]


def test_reconcile_reaps_idle_worker_from_older_generation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pool = _pool(tmp_path, monkeypatch, 2)
    touched = []
    pool.service = SimpleNamespace(
        runtime_health=lambda: {
            "workers": [
                {
                    "worker_id": "research-worker-1",
                    "status": "idle",
                    "current_run_id": "",
                    "online": True,
                },
                {
                    "worker_id": pool._worker_id(1),
                    "status": "idle",
                    "current_run_id": "",
                    "online": True,
                },
                {
                    "worker_id": pool._worker_id(2),
                    "status": "idle",
                    "current_run_id": "",
                    "online": True,
                },
            ]
        },
        touch_worker=lambda worker_id, **kwargs: touched.append(
            (worker_id, kwargs)
        ),
    )
    monkeypatch.setattr(
        pool,
        "_local_worker_processes",
        lambda: [
            {
                "pid": 1201,
                "pgid": 1201,
                "worker_id": "research-worker-1",
                "runtime_generation": "",
            }
        ],
    )
    terminated = []
    monkeypatch.setattr(
        pool,
        "_terminate_external_worker",
        lambda pid, pgid: terminated.append((pid, pgid)),
    )

    pool.reconcile()

    assert terminated == [(1201, 1201)]
    assert touched == [("research-worker-1", {"status": "stopped"})]


def test_reconcile_preserves_working_worker_from_older_generation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pool = _pool(tmp_path, monkeypatch, 1)
    pool.service = SimpleNamespace(
        runtime_health=lambda: {
            "workers": [
                {
                    "worker_id": "research-worker-1",
                    "status": "working",
                    "current_run_id": "run-active",
                    "online": True,
                },
                {
                    "worker_id": pool._worker_id(1),
                    "status": "idle",
                    "current_run_id": "",
                    "online": True,
                },
            ]
        },
        touch_worker=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        pool,
        "_local_worker_processes",
        lambda: [
            {
                "pid": 1202,
                "pgid": 1202,
                "worker_id": "research-worker-1",
                "runtime_generation": "",
            }
        ],
    )
    terminated = []
    monkeypatch.setattr(
        pool,
        "_terminate_external_worker",
        lambda pid, pgid: terminated.append((pid, pgid)),
    )

    pool.reconcile()

    assert terminated == []


def test_local_worker_processes_preserves_paths_with_spaces(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "equipment research"
    output_root = project_root / "outputs" / "runs"
    project_root.mkdir()
    output_root.mkdir(parents=True)
    pool = ResearchWorkerPool(
        project_root=project_root,
        output_root=output_root,
        database_url=None,
        initial_capacity=2,
        runtime_generation="current-build",
    )
    command = (
        "1201 1201 /usr/bin/python -m equipment_deep_research.interfaces.worker "
        f"--project-root {project_root} --output-root {output_root} "
        "--worker-id research-worker-3@old-build --runtime-generation old-build "
        "--poll-interval 1\n"
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=command),
    )

    assert pool._local_worker_processes() == [
        {
            "pid": 1201,
            "pgid": 1201,
            "worker_id": "research-worker-3@old-build",
            "runtime_generation": "old-build",
        }
    ]


def test_reconcile_reaps_versioned_idle_worker_from_older_generation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pool = _pool(tmp_path, monkeypatch, 2)
    stale_worker_id = "research-worker-3@old-build"
    touched = []
    pool.service = SimpleNamespace(
        runtime_health=lambda: {
            "workers": [
                {
                    "worker_id": stale_worker_id,
                    "status": "idle",
                    "current_run_id": "",
                    "online": True,
                },
                {
                    "worker_id": pool._worker_id(1),
                    "status": "idle",
                    "current_run_id": "",
                    "online": True,
                },
                {
                    "worker_id": pool._worker_id(2),
                    "status": "idle",
                    "current_run_id": "",
                    "online": True,
                },
            ]
        },
        touch_worker=lambda worker_id, **kwargs: touched.append(
            (worker_id, kwargs)
        ),
    )
    monkeypatch.setattr(
        pool,
        "_local_worker_processes",
        lambda: [
            {
                "pid": 1203,
                "pgid": 1203,
                "worker_id": stale_worker_id,
                "runtime_generation": "old-build",
            }
        ],
    )
    terminated = []
    monkeypatch.setattr(
        pool,
        "_terminate_external_worker",
        lambda pid, pgid: terminated.append((pid, pgid)),
    )

    pool.reconcile()

    assert terminated == [(1203, 1203)]
    assert touched == [(stale_worker_id, {"status": "stopped"})]
