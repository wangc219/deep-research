from __future__ import annotations

import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _commands_module():
    try:
        from scripts.data_crawling_handoff import commands
    except ModuleNotFoundError:
        pytest.fail("data crawling handoff command mapping is not implemented")
    return commands


def _doctor_module():
    try:
        from scripts.data_crawling_handoff import doctor
    except ModuleNotFoundError:
        pytest.fail("data crawling handoff doctor is not implemented")
    return doctor


def test_resolve_data_root_prefers_explicit_value_then_environment(tmp_path, monkeypatch):
    commands = _commands_module()
    env_root = tmp_path / "env-data"
    explicit_root = tmp_path / "explicit-data"
    monkeypatch.setenv("CRAWLER_DATA_ROOT", str(env_root))

    assert commands.resolve_data_root(explicit_root) == explicit_root.resolve()
    assert commands.resolve_data_root(None) == env_root.resolve()


def test_journal_command_maps_common_data_root(tmp_path):
    commands = _commands_module()
    journal_root = (
        PROJECT_ROOT / "modules" / "journal"
        if (PROJECT_ROOT / "modules" / "journal").exists()
        else PROJECT_ROOT
    )

    command = commands.build_module_command(
        module="journal",
        project_root=PROJECT_ROOT,
        data_root=tmp_path,
        passthrough=["--journal", "zsdd", "--max-issues", "1"],
    )

    assert command[:2] == [
        sys.executable,
        str(journal_root / "scripts" / "journal" / "download_all_journals.py"),
    ]
    assert command[2:6] == [
        "--output-root",
        str(tmp_path / "raw"),
        "--manifest",
        str(tmp_path / "raw" / "journal_batch_manifest.jsonl"),
    ]


def test_wechat_output_option_is_placed_after_collect_subcommand(tmp_path):
    commands = _commands_module()

    command = commands.build_module_command(
        module="wechat",
        project_root=PROJECT_ROOT,
        data_root=tmp_path,
        passthrough=["collect", "测试公众号", "--max-articles", "1"],
    )

    assert command[1].endswith("wechat_mp_collector\\collect.py") or command[1].endswith(
        "wechat_mp_collector/collect.py"
    )
    assert command[-2:] == ["--output", str(tmp_path / "raw" / "wechat")]


def test_mineru_and_demand_commands_map_processed_roots(tmp_path):
    commands = _commands_module()

    mineru = commands.build_module_command(
        "mineru", PROJECT_ROOT, tmp_path, ["--limit", "1"]
    )
    demand = commands.build_module_command(
        "demand", PROJECT_ROOT, tmp_path, ["--topic", "保障需求"]
    )

    assert "--work-root" in mineru
    assert str(tmp_path / "processed" / "extraction_experiments") in mineru
    assert "--artifact-root" in mineru
    assert str(tmp_path / "processed" / "mineru_artifacts") in mineru
    assert demand[2:4] == [
        "--output-root",
        str(tmp_path / "demand_discovery"),
    ]


def test_unknown_module_is_rejected(tmp_path):
    commands = _commands_module()

    with pytest.raises(ValueError, match="unknown module"):
        commands.build_module_command("unknown", PROJECT_ROOT, tmp_path, [])


def test_doctor_reports_secret_configuration_without_values(tmp_path):
    doctor = _doctor_module()
    secret = "sk-do-not-print-this-value"
    project_root = tmp_path / "project"
    project_root.mkdir()

    checks = doctor.collect_checks(
        project_root=project_root,
        data_root=tmp_path / "data",
        runtime_root=tmp_path / "runtime",
        env={"DEMAND_DISCOVERY_API_KEY": secret},
    )
    payload = json.dumps(checks, ensure_ascii=False)

    assert secret not in payload
    env_check = next(item for item in checks if item["name"] == "configured_environment")
    assert env_check["configured"] == ["DEMAND_DISCOVERY_API_KEY"]
    assert all("value" not in item for item in checks)


def test_doctor_does_not_require_docker_cli_inside_container(tmp_path):
    doctor = _doctor_module()

    with patch.object(doctor.shutil, "which", return_value=None):
        checks = doctor.collect_checks(
            project_root=PROJECT_ROOT,
            data_root=tmp_path / "data",
            runtime_root=tmp_path / "runtime",
            env={},
            containerized=True,
        )

    docker_check = next(item for item in checks if item["name"] == "docker")
    assert docker_check == {
        "name": "docker",
        "ok": True,
        "command_available": False,
        "containerized": True,
    }


def test_doctor_reports_dotenv_names_without_values(tmp_path):
    doctor = _doctor_module()
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / ".env").write_text(
        "TAVILY_API_KEY=do-not-print-tavily\n"
        '$env:MINERU_TOKEN="do-not-print-mineru"\n',
        encoding="utf-8",
    )

    checks = doctor.collect_checks(
        project_root=project_root,
        data_root=tmp_path / "data",
        runtime_root=tmp_path / "runtime",
        env={},
    )
    payload = json.dumps(checks, ensure_ascii=False)

    configured = next(
        item for item in checks if item["name"] == "configured_environment"
    )["configured"]
    assert configured == ["MINERU_TOKEN", "TAVILY_API_KEY"]
    assert "do-not-print-tavily" not in payload
    assert "do-not-print-mineru" not in payload
