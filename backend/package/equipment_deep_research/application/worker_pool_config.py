from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any


MIN_WORKER_CAPACITY = 1
MAX_WORKER_CAPACITY = 8


def clamp_worker_capacity(value: Any, *, fallback: int = 2) -> int:
    try:
        capacity = int(value)
    except (TypeError, ValueError):
        capacity = fallback
    return min(MAX_WORKER_CAPACITY, max(MIN_WORKER_CAPACITY, capacity))


def worker_pool_config_path() -> Path:
    project_root = Path(
        os.environ.get("EQUIPMENT_DR_PROJECT_ROOT", Path.cwd())
    ).expanduser().resolve()
    configured = os.environ.get("EQUIPMENT_DR_WORKER_POOL_CONFIG", "").strip()
    path = Path(configured).expanduser() if configured else Path(
        "outputs/runtime/research-worker-pool.json"
    )
    return path.resolve() if path.is_absolute() else (project_root / path).resolve()


def environment_worker_capacity() -> int:
    raw_value = os.environ.get("EQUIPMENT_DR_RESEARCH_WORKER_CONCURRENCY")
    if raw_value is None:
        return 2
    return clamp_worker_capacity(raw_value, fallback=1)


def read_worker_capacity(*, fallback: int | None = None) -> int:
    default = environment_worker_capacity() if fallback is None else clamp_worker_capacity(fallback)
    path = worker_pool_config_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    if not isinstance(payload, dict):
        return default
    return clamp_worker_capacity(payload.get("desired_capacity"), fallback=default)


def write_worker_capacity(capacity: int, *, updated_by: str = "system") -> dict[str, Any]:
    desired = clamp_worker_capacity(capacity)
    path = worker_pool_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "desired_capacity": desired,
        "updated_by": str(updated_by or "system")[:80],
    }
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix="worker-pool-",
        suffix=".json.tmp",
        dir=path.parent,
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.flush()
        temporary_path = Path(handle.name)
    try:
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return payload


def ensure_worker_capacity_config(initial_capacity: int | None = None) -> int:
    path = worker_pool_config_path()
    if path.is_file():
        return read_worker_capacity(fallback=initial_capacity)
    desired = environment_worker_capacity() if initial_capacity is None else clamp_worker_capacity(initial_capacity)
    write_worker_capacity(desired, updated_by="startup")
    return desired
