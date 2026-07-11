from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RunWorkspace:
    run_dir: Path
    sessions_dir: Path
    artifacts_dir: Path
    checkpoints_dir: Path
    database_path: Path

    @classmethod
    def create(cls, output_root: str | Path, run_id: str) -> "RunWorkspace":
        _validate_run_id(run_id)

        output_root = Path(output_root)
        output_root.mkdir(parents=True, exist_ok=True)
        resolved_root = output_root.resolve()
        run_dir = output_root / run_id
        run_dir.mkdir(exist_ok=False)
        if run_dir.resolve(strict=True).parent != resolved_root:
            raise ValueError("run_id must stay within output_root")

        sessions_dir = run_dir / "agent_sessions"
        artifacts_dir = run_dir / "artifacts"
        checkpoints_dir = run_dir / "checkpoints"
        for path in (sessions_dir, artifacts_dir, checkpoints_dir):
            path.mkdir(exist_ok=False)
        return cls(
            run_dir=run_dir,
            sessions_dir=sessions_dir,
            artifacts_dir=artifacts_dir,
            checkpoints_dir=checkpoints_dir,
            database_path=run_dir / "run.db",
        )

    @classmethod
    def open_existing(cls, output_root: str | Path, run_id: str) -> "RunWorkspace":
        _validate_run_id(run_id)
        output_root = Path(output_root)
        if not output_root.exists():
            raise FileNotFoundError(f"output_root does not exist: {output_root}")
        if not output_root.is_dir():
            raise ValueError("output_root must be a directory")
        resolved_root = output_root.resolve(strict=True)
        run_dir = output_root / run_id
        if not run_dir.exists():
            raise FileNotFoundError(f"run directory does not exist: {run_dir}")
        _require_directory(run_dir, "run_dir")
        resolved_run = run_dir.resolve(strict=True)
        if resolved_run.parent != resolved_root:
            raise ValueError("run_dir must stay within output_root")

        sessions_dir = run_dir / "agent_sessions"
        artifacts_dir = run_dir / "artifacts"
        checkpoints_dir = run_dir / "checkpoints"
        for path, label in (
            (sessions_dir, "agent_sessions"),
            (artifacts_dir, "artifacts"),
            (checkpoints_dir, "checkpoints"),
        ):
            _require_directory(path, label)
            if path.resolve(strict=True).parent != resolved_run:
                raise ValueError(f"{label} must stay within run_dir")

        database_path = run_dir / "run.db"
        if not database_path.exists():
            raise FileNotFoundError(f"run database does not exist: {database_path}")
        if database_path.is_symlink():
            raise ValueError("run.db must not be a symlink")
        if not database_path.is_file():
            raise ValueError("run.db must be a regular file")
        if database_path.resolve(strict=True).parent != resolved_run:
            raise ValueError("run.db must stay within run_dir")
        return cls(
            run_dir=run_dir,
            sessions_dir=sessions_dir,
            artifacts_dir=artifacts_dir,
            checkpoints_dir=checkpoints_dir,
            database_path=database_path,
        )


def _validate_run_id(run_id: str) -> None:
    if (
        not isinstance(run_id, str)
        or not run_id.strip()
        or Path(run_id).is_absolute()
        or run_id in {".", ".."}
        or "/" in run_id
        or "\\" in run_id
    ):
        raise ValueError("run_id must be a single relative path component")


def _require_directory(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    if not path.is_dir():
        raise ValueError(f"{label} must be a directory")
