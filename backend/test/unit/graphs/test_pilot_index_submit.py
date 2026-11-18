"""Pilot 待入库提交脚本的输入边界测试。"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "submit_knowledge_graph_pilot_indexing.py"
SPEC = importlib.util.spec_from_file_location("submit_knowledge_graph_pilot_indexing", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_load_kb_id_from_local_access_manifest(tmp_path: Path):
    path = tmp_path / "pilot-access.json"
    path.write_text(json.dumps({"knowledge_base": {"kb_id": "kb-local"}}), encoding="utf-8")

    assert MODULE.load_kb_id(path) == "kb-local"


def test_load_kb_id_rejects_missing_identity(tmp_path: Path):
    path = tmp_path / "pilot-access.json"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="kb_id"):
        MODULE.load_kb_id(path)
