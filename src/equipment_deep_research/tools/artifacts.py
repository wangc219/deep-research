from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from equipment_deep_research.domain.workspace import RunWorkspace, _RootedAtomicWriter


@dataclass(frozen=True)
class ArtifactRecord:
    ref: str
    path: Path
    meta_path: Path
    meta: dict[str, Any]


class SecureArtifactStore:
    """Content-addressed artifacts written through rooted dirfd operations."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        if self.root.is_symlink():
            raise ValueError("artifact root must not be a symlink")
        self.root.mkdir(parents=True, exist_ok=True)
        self._write_bytes: Callable[[str, bytes], None] = self._directory_write
        self._read_bytes: Callable[[str], bytes] = self._directory_read
        self._is_regular: Callable[[str], bool] = self._directory_is_regular
        self._list_names: Callable[[], list[str]] = self._directory_list_names

    @classmethod
    def for_workspace(cls, workspace: RunWorkspace) -> "SecureArtifactStore":
        store = cls.__new__(cls)
        store.root = workspace.artifacts_dir
        store._write_bytes = workspace.write_artifact_bytes
        store._read_bytes = workspace.read_artifact_bytes
        store._is_regular = workspace.artifact_file_is_regular
        store._list_names = workspace.artifact_file_names
        return store

    def put(self, content: bytes | str, *, kind: str, meta: dict[str, Any]) -> str:
        data = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        sha = hashlib.sha256(data).hexdigest()
        short = sha[:16]
        safe_kind = _safe_kind(kind)
        ref = f"{safe_kind}:{short}"
        ext = _extension_for(safe_kind, content, meta)
        content_name = f"{safe_kind}-{short}.{ext}"
        meta_name = f"{safe_kind}-{short}.meta.json"
        stored_meta = {
            **dict(meta),
            "artifact_ref": ref,
            "kind": safe_kind,
            "sha256": sha,
            "content_path": content_name,
            "encoding": "utf-8" if isinstance(content, str) else None,
        }
        self._write_bytes(content_name, data)
        self._write_bytes(
            meta_name,
            json.dumps(
                stored_meta,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            ).encode("utf-8"),
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
        return self._read_bytes(record.path.name).decode(
            str(encoding),
            errors="replace",
        )

    def get_meta(self, ref: str) -> dict[str, Any]:
        return dict(self._record(ref).meta)

    def iter_records(self, kind: str | None = None) -> list[ArtifactRecord]:
        prefix = f"{_safe_kind(kind)}-" if kind else ""
        records: list[ArtifactRecord] = []
        for name in self._list_names():
            if not name.startswith(prefix) or not name.endswith(".meta.json"):
                continue
            try:
                meta = json.loads(self._read_bytes(name).decode("utf-8"))
                ref = str(meta.get("artifact_ref", ""))
                if ref:
                    records.append(self._record(ref))
            except (KeyError, UnicodeDecodeError, json.JSONDecodeError):
                continue
        return records

    def _record(self, ref: str) -> ArtifactRecord:
        kind, short = _parse_ref(ref)
        meta_name = f"{kind}-{short}.meta.json"
        if not self._is_regular(meta_name):
            raise KeyError(ref)
        try:
            meta = json.loads(self._read_bytes(meta_name).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise KeyError(ref) from exc
        content_name = meta.get("content_path")
        if (
            not isinstance(content_name, str)
            or not content_name
            or Path(content_name).name != content_name
            or not self._is_regular(content_name)
        ):
            raise KeyError(ref)
        return ArtifactRecord(
            ref=ref,
            path=self.root / content_name,
            meta_path=self.root / meta_name,
            meta=meta,
        )

    def _directory_write(self, name: str, content: bytes) -> None:
        _RootedAtomicWriter(self.root).write(name, content)

    def _directory_read(self, name: str) -> bytes:
        return _RootedAtomicWriter(self.root).read(name)

    def _directory_is_regular(self, name: str) -> bool:
        return _RootedAtomicWriter(self.root).is_regular_file(name)

    def _directory_list_names(self) -> list[str]:
        return _RootedAtomicWriter(self.root).list_regular_file_names(".")


def _parse_ref(ref: str) -> tuple[str, str]:
    if ":" not in ref:
        raise KeyError(ref)
    kind, short = ref.split(":", 1)
    if len(short) != 16 or any(ch not in "0123456789abcdef" for ch in short):
        raise KeyError(ref)
    return _safe_kind(kind), short


def _safe_kind(kind: str) -> str:
    normalized = "".join(
        ch for ch in kind.lower().strip() if ch.isalnum() or ch == "_"
    )
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


__all__ = ["ArtifactRecord", "SecureArtifactStore"]
