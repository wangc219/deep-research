from __future__ import annotations

import importlib.util
import json
import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest


SCRIPT_PATH = Path(__file__).parents[4] / "scripts" / "production_release_gate.py"
sys.path.insert(0, str(SCRIPT_PATH.parent))
SPEC = importlib.util.spec_from_file_location("production_release_gate", SCRIPT_PATH)
assert SPEC and SPEC.loader
release_gate = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release_gate
SPEC.loader.exec_module(release_gate)


def _args(tmp_path: Path) -> Namespace:
    return Namespace(
        candidate_image="deepquest-web:release-20261111-01",
        current_container="deepquest-web-1",
        component="api",
        release_id="release-20261111-01",
        source_revision="abc123",
        output=tmp_path / "candidate.json",
    )


def test_candidate_gate_rejects_noop_image(tmp_path: Path) -> None:
    candidate = {
        "Id": "sha256:same",
        "Config": {
            "Labels": {
                "com.deepquest.release.id": "release-20261111-01",
                "com.deepquest.release.component": "api",
                "org.opencontainers.image.revision": "abc123",
            }
        },
    }
    current = {"Image": "sha256:same", "Config": {"Image": "deepquest-api:old"}}

    with (
        patch.object(release_gate, "_docker_inspect", side_effect=[candidate, current]),
        patch.object(release_gate, "_verify_api_image_contract"),
        patch.object(release_gate, "_verify_api_runtime"),
    ):
        with pytest.raises(RuntimeError, match="没有实质变更"):
            release_gate.verify_candidate(_args(tmp_path))


def test_candidate_gate_records_distinct_release(tmp_path: Path) -> None:
    candidate = {
        "Id": "sha256:new",
        "Config": {
            "Labels": {
                "com.deepquest.release.id": "release-20261111-01",
                "com.deepquest.release.component": "api",
                "org.opencontainers.image.revision": "abc123",
            }
        },
    }
    current = {"Image": "sha256:old", "Config": {"Image": "deepquest-api:old"}}
    args = _args(tmp_path)

    with (
        patch.object(release_gate, "_docker_inspect", side_effect=[candidate, current]),
        patch.object(
            release_gate,
            "_verify_api_image_contract",
            return_value={"sources": ["innovation_brief"]},
        ),
        patch.object(
            release_gate,
            "_verify_api_runtime",
            return_value=["wechat_mp_import"],
        ) as runtime,
    ):
        release_gate.verify_candidate(args)

    evidence = json.loads(args.output.read_text(encoding="utf-8"))
    assert evidence["status"] == "passed"
    assert evidence["candidate_image_id"] == "sha256:new"
    assert evidence["current_image_id"] == "sha256:old"
    assert evidence["runtime_checks"] == ["wechat_mp_import"]
    runtime.assert_called_once_with(args.candidate_image)


def test_api_runtime_gate_reports_import_failure() -> None:
    result = release_gate.subprocess.CompletedProcess(
        args=["docker"],
        returncode=1,
        stdout="",
        stderr="ImportError: missing helper",
    )

    with patch.object(release_gate.subprocess, "run", return_value=result):
        with pytest.raises(RuntimeError, match="公众号运行时导入失败"):
            release_gate._verify_api_runtime("deepquest-api:candidate")


@pytest.mark.parametrize("value", ["development", "unknown", "bad/value", ""])
def test_production_release_values_are_strict(value: str) -> None:
    with pytest.raises(RuntimeError):
        release_gate._validated_release_value("release_id", value)
