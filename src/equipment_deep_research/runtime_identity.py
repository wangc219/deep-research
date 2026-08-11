"""Process-frozen build identity used to fence queued research work."""

from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path


def _source_build_hash() -> str:
    package_root = Path(__file__).resolve().parent
    digest = sha256()
    for path in sorted(package_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        digest.update(path.relative_to(package_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError:
            continue
        digest.update(b"\0")
    return digest.hexdigest()[:12]


# Frozen once per process.  An old Worker cannot acquire the new identity by
# observing source files that changed after its modules had already loaded.
RUNTIME_BUILD_HASH = (
    str(os.environ.get("EQUIPMENT_DR_BUILD_HASH", "")).strip()
    or _source_build_hash()
)


def pending_queue_status(build_hash: str = RUNTIME_BUILD_HASH) -> str:
    return f"pending:{build_hash[:16]}"


def claimed_queue_status(build_hash: str = RUNTIME_BUILD_HASH) -> str:
    return f"claimed:{build_hash[:16]}"


def versioned_worker_id(worker_id: str, build_hash: str = RUNTIME_BUILD_HASH) -> str:
    base = str(worker_id).strip() or "research-worker"
    suffix = f"@{build_hash[:12]}"
    return base if base.endswith(suffix) else f"{base}{suffix}"
