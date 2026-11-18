"""Pilot 来源元数据闭集映射测试。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "backfill_knowledge_graph_pilot_source_metadata.py"
SPEC = importlib.util.spec_from_file_location("backfill_knowledge_graph_pilot_source_metadata", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _manifest() -> dict:
    return {
        "document_id": "src-a",
        "content_sha256": "a" * 64,
        "filename": "论文.pdf",
        "source_type": "paper",
        "language": "zh",
        "acceptance_languages": ["zh"],
        "manifest_version": "pilot-v1",
        "domain": "",
    }


def _checkpoint() -> dict:
    return {
        "document_id": "src-a",
        "content_sha256": "a" * 64,
        "filename": "论文.pdf",
        "file_id": "file-a",
        "status": "added",
    }


def test_source_metadata_binds_manifest_to_imported_file():
    result = MODULE.build_source_metadata([_manifest()], [_checkpoint()], expected_count=1)

    assert result == {
        "file-a": {
            "source_type": "paper",
            "language": "zh",
            "domain": "",
            "source_manifest_document_id": "src-a",
            "source_manifest_version": "pilot-v1",
            "acceptance_languages": ["zh"],
            "source_content_sha256": "a" * 64,
        }
    }


@pytest.mark.parametrize(
    ("manifest_update", "error"),
    [
        ({"source_type": "patent"}, "禁止非论文来源"),
        ({"language": "en", "acceptance_languages": ["en"]}, "只验收中文"),
    ],
)
def test_source_metadata_rejects_out_of_scope_sources(manifest_update: dict, error: str):
    manifest = {**_manifest(), **manifest_update}

    with pytest.raises(MODULE.SourceMetadataError, match=error):
        MODULE.build_source_metadata([manifest], [_checkpoint()], expected_count=1)


def test_source_metadata_rejects_incomplete_checkpoint():
    with pytest.raises(MODULE.SourceMetadataError, match="不闭合"):
        MODULE.build_source_metadata([_manifest()], [], expected_count=1)
