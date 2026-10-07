"""Content-addressed artifact storage for fetched and simplified documents."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ArtifactRecord:
    ref: str
    path: Path
    meta_path: Path
    meta: dict[str, Any]


class ArtifactStore:
    """Small content-addressed file store.

    The public reference is ``"{kind}:{sha256[:16]}"``. Metadata is stored
    beside the content and carries the full hash, extension, and caller-supplied
    fields so the short ref stays stable while avoiding context bloat.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, content: bytes | str, *, kind: str, meta: dict[str, Any]) -> str:
        data = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        sha = hashlib.sha256(data).hexdigest()
        short = sha[:16]
        safe_kind = _safe_kind(kind)
        ref = f"{safe_kind}:{short}"
        ext = _extension_for(safe_kind, content, meta)
        path = self.root / f"{safe_kind}-{short}.{ext}"
        meta_path = self.root / f"{safe_kind}-{short}.meta.json"
        if not path.exists():
            path.write_bytes(data)
        stored_meta = {
            **dict(meta),
            "artifact_ref": ref,
            "kind": safe_kind,
            "sha256": sha,
            "content_path": path.name,
            "encoding": "utf-8" if isinstance(content, str) else None,
        }
        meta_path.write_text(
            json.dumps(stored_meta, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        return ref

    def exists(self, ref: str) -> bool:
        try:
            self._record(ref)
        except KeyError:
            return False
        return True

    def get_text(self, ref: str) -> str:
        record = self._record(ref)
        encoding = record.meta.get("encoding") or "utf-8"
        return record.path.read_text(encoding=str(encoding), errors="replace")

    def get_meta(self, ref: str) -> dict[str, Any]:
        return dict(self._record(ref).meta)

    def iter_records(self, kind: str | None = None) -> list[ArtifactRecord]:
        records: list[ArtifactRecord] = []
        prefix = f"{_safe_kind(kind)}-" if kind else ""
        for meta_path in sorted(self.root.glob(f"{prefix}*.meta.json")):
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            ref = str(meta.get("artifact_ref", ""))
            if not ref:
                continue
            try:
                records.append(self._record(ref))
            except KeyError:
                continue
        return records

    def _record(self, ref: str) -> ArtifactRecord:
        kind, short = _parse_ref(ref)
        meta_path = self.root / f"{kind}-{short}.meta.json"
        if not meta_path.exists():
            raise KeyError(ref)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        content_name = meta.get("content_path")
        if not isinstance(content_name, str) or not content_name:
            raise KeyError(ref)
        path = self.root / content_name
        if not path.exists():
            raise KeyError(ref)
        return ArtifactRecord(ref=ref, path=path, meta_path=meta_path, meta=meta)


def _parse_ref(ref: str) -> tuple[str, str]:
    if ":" not in ref:
        raise KeyError(ref)
    kind, short = ref.split(":", 1)
    if not kind or not short:
        raise KeyError(ref)
    return _safe_kind(kind), short


def _safe_kind(kind: str) -> str:
    normalized = "".join(ch for ch in kind.lower().strip() if ch.isalnum() or ch == "_")
    if not normalized:
        raise ValueError("artifact kind is required")
    return normalized


def _extension_for(kind: str, content: bytes | str, meta: dict[str, Any]) -> str:
    content_type = str(meta.get("content_type", "")).lower()
    if kind in {"html", "page_html"} or "html" in content_type:
        return "html"
    if isinstance(content, str) or kind in {"text", "summary"}:
        return "txt"
    return "bin"
