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
        if (
            not run_id.strip()
            or Path(run_id).is_absolute()
            or run_id in {".", ".."}
            or "/" in run_id
            or "\\" in run_id
        ):
            raise ValueError("run_id must be a single relative path component")

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
