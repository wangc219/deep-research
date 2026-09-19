#!/usr/bin/env python3
"""Export a non-invasive audit bundle for one equipment research run."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


MODEL_OUTPUT_KEYS = {
    "raw_message",
    "model_output",
    "response_text",
    "final_text",
    "output_text",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    try:
        temporary.chmod(0o600)
        temporary.replace(path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    try:
        destination.chmod(0o600)
    except OSError:
        pass


def _walk_model_outputs(value: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            nested_path = f"{path}.{key}"
            if str(key) in MODEL_OUTPUT_KEYS:
                yield nested_path, nested
            yield from _walk_model_outputs(nested, nested_path)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _walk_model_outputs(nested, f"{path}[{index}]")


def _jsonl_records(session_path: Path) -> Iterable[tuple[int, str, Mapping[str, Any]]]:
    with session_path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            raw = raw_line.rstrip("\n")
            if not raw.strip():
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"_invalid_json": True, "raw": raw}
            if not isinstance(payload, Mapping):
                payload = {"value": payload}
            yield line_number, raw, payload


def _sqlite_backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as source_db:
        with sqlite3.connect(destination) as destination_db:
            source_db.backup(destination_db)
    destination.chmod(0o600)


def export_run(workspace: Path, run_id: str, *, api_base: str = "") -> Path:
    run_dir = workspace / "outputs" / "runs" / run_id
    if not run_dir.is_dir():
        raise SystemExit(f"run directory not found: {run_dir}")
    bundle = run_dir / "codex_audit" / "legacy_capture"
    raw_root = bundle / "raw"
    bundle.mkdir(parents=True, exist_ok=True)
    try:
        bundle.chmod(0o700)
    except OSError:
        pass

    source_files: list[Path] = []
    for directory_name in ("agent_sessions", "checkpoints", "artifacts"):
        source_dir = run_dir / directory_name
        if source_dir.is_dir():
            source_files.extend(path for path in source_dir.rglob("*") if path.is_file())
    source_files.extend(
        path
        for path in run_dir.iterdir()
        if path.is_file() and path.name != "run.db"
    )
    transcript_root = run_dir / "codex_cli_transcripts"
    if transcript_root.is_dir():
        source_files.extend(path for path in transcript_root.rglob("*") if path.is_file())

    copied: list[dict[str, Any]] = []
    for source in sorted(set(source_files)):
        relative = source.relative_to(run_dir)
        destination = raw_root / relative
        _copy_file(source, destination)
        copied.append(
            {
                "source": str(relative),
                "bytes": source.stat().st_size,
                "sha256": _sha256(destination),
            }
        )

    database_source = run_dir / "run.db"
    if database_source.is_file():
        database_destination = raw_root / "run.db"
        _sqlite_backup(database_source, database_destination)
        copied.append(
            {
                "source": "run.db",
                "bytes": database_destination.stat().st_size,
                "sha256": _sha256(database_destination),
                "copy_method": "sqlite_online_backup",
            }
        )

    api_snapshots: list[dict[str, Any]] = []
    if api_base:
        endpoints = (
            "",
            "/interactions",
            "/capabilities",
            "/winning-mechanism",
            "/summary",
            "/trace",
            "/manifest",
            "/deliverables",
        )
        for suffix in endpoints:
            endpoint_name = suffix.strip("/") or "run"
            url = f"{api_base.rstrip('/')}/api/v1/runs/{run_id}{suffix}"
            try:
                with urlopen(url, timeout=15) as response:  # noqa: S310 - local explicit API
                    body = response.read().decode("utf-8", errors="replace")
                _atomic_text(raw_root / "api" / f"{endpoint_name}.json", body)
                api_snapshots.append(
                    {
                        "endpoint": suffix or "/",
                        "status": "captured",
                        "bytes": len(body.encode("utf-8")),
                    }
                )
            except (HTTPError, URLError, TimeoutError) as exc:
                api_snapshots.append(
                    {
                        "endpoint": suffix or "/",
                        "status": "unavailable",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

    line_index: list[dict[str, Any]] = []
    output_index: list[dict[str, Any]] = []
    handoff_timeline: list[dict[str, Any]] = []
    session_root = run_dir / "agent_sessions"
    if session_root.is_dir():
        for session_path in sorted(session_root.glob("*.jsonl")):
            for line_number, raw, payload in _jsonl_records(session_path):
                event_type = str(payload.get("event_type", payload.get("type", "")))
                record = {
                    "session_file": session_path.name,
                    "line_number": line_number,
                    "line_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                    "event_type": event_type,
                    "agent_id": str(payload.get("agent_id", "")),
                    "agent_instance_id": str(payload.get("agent_instance_id", "")),
                    "phase": str(payload.get("phase", "")),
                    "session_ref": str(payload.get("session_ref", "")),
                }
                line_index.append(record)
                for field_path, value in _walk_model_outputs(payload):
                    output_index.append(
                        {
                            **record,
                            "field_path": field_path,
                            "value": value,
                        }
                    )
                if any(
                    marker in event_type
                    for marker in (
                        "session_",
                        "handoff",
                        "candidate_branch",
                        "candidate_ledger",
                        "model_result",
                        "baseline_result",
                    )
                ):
                    handoff_timeline.append(
                        {
                            **record,
                            "graph_id": str(payload.get("graph_id", "")),
                            "mission_node": str(payload.get("mission_node", "")),
                            "task_id": str(payload.get("task_id", "")),
                            "depends_on": payload.get("depends_on", []),
                            "merge_target": str(payload.get("merge_target", "")),
                            "handoff_schema": payload.get("handoff_schema", {}),
                            "candidate_handoff_count": payload.get(
                                "candidate_handoff_count"
                            ),
                            "evidence_handoff_count": payload.get(
                                "evidence_handoff_count"
                            ),
                            "handoff_total_chars": payload.get("handoff_total_chars"),
                        }
                    )

    _atomic_text(
        bundle / "line_index.jsonl",
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in line_index),
    )
    _atomic_text(
        bundle / "model_outputs.jsonl",
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in output_index),
    )
    _atomic_text(
        bundle / "handoff_timeline.jsonl",
        "".join(
            json.dumps(row, ensure_ascii=False) + "\n" for row in handoff_timeline
        ),
    )
    generated_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "schema_version": "1.0",
        "run_id": run_id,
        "generated_at": generated_at,
        "capture_mode": "legacy_provider_compatibility",
        "source_file_count": len(copied),
        "session_line_count": len(line_index),
        "parsed_model_output_count": len(output_index),
        "handoff_event_count": len(handoff_timeline),
        "api_snapshots": api_snapshots,
        "files": copied,
        "limitations": [
            "The running worker predates provider-level transcript capture.",
            "raw/agent_sessions preserves every harness event and parsed raw_message available for this run.",
            "The original rendered Codex prompt, CLI stdout JSONL, stderr, and retry envelopes cannot be reconstructed for calls that already completed.",
            "New workers write exact exchanges to codex_cli_transcripts for future calls.",
        ],
    }
    _atomic_text(
        bundle / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2),
    )
    _atomic_text(
        bundle / "README.md",
        "\n".join(
            [
                f"# Codex CLI audit bundle: {run_id}",
                "",
                "This is an append-safe compatibility capture for a run started before exact provider transcript archiving was loaded.",
                "",
                "- `raw/agent_sessions/`: exact harness session JSONL files.",
                "- `raw/checkpoints/`, `raw/artifacts/`, `raw/run.db`: handoff state and persisted outputs.",
                "- `line_index.jsonl`: source line, event identity, and SHA-256 for tamper checks.",
                "- `model_outputs.jsonl`: every explicitly stored parsed model-output field, without truncation.",
                "- `handoff_timeline.jsonl`: cross-Agent session and handoff events with source locations.",
                "- `manifest.json`: file hashes and capture limitations.",
                "",
                "Exact rendered prompts and original Codex CLI stdout/stderr are unavailable for calls completed by the pre-patch worker. Do not treat this compatibility bundle as a raw CLI transcript.",
                "",
            ]
        ),
    )
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_id")
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--api-base", default="")
    args = parser.parse_args()
    bundle = export_run(
        args.workspace.resolve(),
        args.run_id,
        api_base=str(args.api_base),
    )
    print(bundle)


if __name__ == "__main__":
    main()
