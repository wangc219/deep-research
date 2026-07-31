"""File-system intervention inbox for long-running demand discovery runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from knowledgegraph.demand_discovery.harness.event_bus import EventBus, RuntimeEvent


@dataclass(frozen=True)
class Intervention:
    kind: str
    text: str
    path: Path
    processed_path: Path


class FileInbox:
    """Poll a run-local inbox directory for human intervention files."""

    _SUPPORTED = {
        "stop": "stop",
        "stop.md": "stop",
        "steer.md": "steer",
        "next_turn.md": "next_turn",
    }
    _ORDER = {"stop": 0, "steer": 1, "next_turn": 2}

    def __init__(self, inbox_dir: str | Path) -> None:
        self.inbox_dir = Path(inbox_dir)
        self.processed_dir = self.inbox_dir / "processed"

    def poll(self) -> list[Intervention]:
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        found: list[tuple[int, Path, str]] = []
        for path in sorted(self.inbox_dir.iterdir()):
            if path.is_dir():
                continue
            kind = self._SUPPORTED.get(path.name)
            if kind is None:
                continue
            found.append((self._ORDER[kind], path, kind))

        interventions: list[Intervention] = []
        for _order, path, kind in sorted(found, key=lambda item: (item[0], item[1].name)):
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            processed_path = self._processed_path(path)
            path.replace(processed_path)
            interventions.append(
                Intervention(
                    kind=kind,
                    text=text,
                    path=path,
                    processed_path=processed_path,
                )
            )
        return interventions

    def _processed_path(self, path: Path) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        candidate = self.processed_dir / f"{stamp}_{path.name}"
        if not candidate.exists():
            return candidate
        return self.processed_dir / f"{stamp}_{uuid4().hex}_{path.name}"


def attach_file_inbox(
    bus: EventBus,
    harness: Any,
    inbox: FileInbox,
    *,
    run_id: str,
    agent_run_id: str = "",
    listen_agent_run_id: str | None = None,
) -> None:
    """Consume inbox files at save-point boundaries and call harness queues."""

    def on_event(event: RuntimeEvent) -> None:
        if event.event_type != "save_point":
            return
        if listen_agent_run_id is not None and event.agent_run_id != listen_agent_run_id:
            return
        for intervention in inbox.poll():
            if intervention.kind == "stop":
                harness.abort()
            elif intervention.kind == "steer":
                harness.steer(intervention.text)
            elif intervention.kind == "next_turn":
                harness.next_turn(intervention.text)
            bus.publish(
                RuntimeEvent(
                    category="intervention",
                    event_type="intervention_consumed",
                    run_id=run_id,
                    agent_run_id=agent_run_id or event.agent_run_id,
                    payload={
                        "kind": intervention.kind,
                        "path": str(intervention.path),
                        "processed_path": str(intervention.processed_path),
                    },
                )
            )

    bus.subscribe(on_event, categories={"agent_runtime"}, run_id=run_id)
