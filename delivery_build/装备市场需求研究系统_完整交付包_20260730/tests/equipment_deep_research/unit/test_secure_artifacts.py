from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from equipment_deep_research.domain import workspace as workspace_module
from equipment_deep_research.domain.workspace import RunWorkspace
from equipment_deep_research.tools.artifacts import SecureArtifactStore


def test_secure_artifact_store_preserves_legacy_ref_and_metadata(
    tmp_path: Path,
) -> None:
    workspace = RunWorkspace.create(tmp_path, "run-1")
    store = SecureArtifactStore.for_workspace(workspace)
    content = "artifact body"
    digest = sha256(content.encode("utf-8")).hexdigest()

    ref = store.put(
        content,
        kind="text",
        meta={"content_type": "text/plain", "source": "fixture"},
    )

    assert ref == f"text:{digest[:16]}"
    content_path = workspace.artifacts_dir / f"text-{digest[:16]}.txt"
    meta_path = workspace.artifacts_dir / f"text-{digest[:16]}.meta.json"
    assert content_path.read_text(encoding="utf-8") == content
    assert json.loads(meta_path.read_text(encoding="utf-8")) == {
        "artifact_ref": ref,
        "content_path": content_path.name,
        "content_type": "text/plain",
        "encoding": "utf-8",
        "kind": "text",
        "sha256": digest,
        "source": "fixture",
    }
    assert store.get_text(ref) == content
    assert store.get_meta(ref)["artifact_ref"] == ref
    assert [record.ref for record in store.iter_records()] == [ref]


def test_content_addressed_artifact_merges_multiple_evidence_owners(
    tmp_path: Path,
) -> None:
    store = SecureArtifactStore(tmp_path)

    first = store.put(
        "same page",
        kind="text",
        meta={"content_type": "text/plain", "evidence_id": "ev-a"},
    )
    second = store.put(
        "same page",
        kind="text",
        meta={"content_type": "text/plain", "evidence_id": "ev-b"},
    )

    assert first == second
    assert store.get_meta(first)["evidence_ids"] == ["ev-a", "ev-b"]
    assert store.get_meta(first)["evidence_id"] == "ev-a"


def test_secure_artifact_store_fails_closed_without_workspace_primitives(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = RunWorkspace.create(tmp_path, "run-1")
    store = SecureArtifactStore.for_workspace(workspace)
    monkeypatch.setattr(workspace_module.os, "supports_dir_fd", set())

    with pytest.raises(RuntimeError, match="secure workspace path operations"):
        store.put("blocked", kind="text", meta={"content_type": "text/plain"})

    assert list(workspace.artifacts_dir.iterdir()) == []
