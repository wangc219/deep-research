from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import zipfile

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _builder_module():
    try:
        from scripts.data_crawling_handoff import package_builder
    except ModuleNotFoundError:
        pytest.fail("data crawling handoff package builder is not implemented")
    return package_builder


@pytest.fixture()
def fixture_root(tmp_path):
    builder = _builder_module()
    root = tmp_path / "fixture-repository"
    root.mkdir()

    directory_files = {
        "scripts/journal": [
            "download_zsdd.py",
            "download_all_journals.py",
            "journal_download_common.py",
        ],
        "cnki_keyword_crawler": ["cnki_keyword_downloader.py", "README.md"],
        "wechat_mp_collector": [
            "collect.py",
            "wechat_mp_collector/cli.py",
            "wechat_mp_collector/session.json",
        ],
        "src/knowledgegraph/demand_discovery": ["tools/acquisition.py"],
        "src/knowledgegraph/runtime": ["provider_config.py", "retry.py"],
        "configs/demand_discovery": ["source_whitelist.yaml"],
        "tests/fixtures": ["demand_discovery_pages/article.html"],
    }
    for mappings in builder.MODULE_MAPPINGS.values():
        for source_name, _destination_name in mappings:
            source = root / source_name
            if source_name in directory_files:
                for relative in directory_files[source_name]:
                    _write(source / relative, "fixture\n")
            elif source.suffix:
                _write(source, "fixture\n")
            else:
                _write(source / "fixture.py", "fixture\n")

    handoff_root = root / "scripts" / "data_crawling_handoff"
    for relative in builder.HANDOFF_SOURCE_FILES:
        _write(handoff_root / relative, "fixture\n")
    for relative in builder.ROOT_TEMPLATE_FILES:
        source_template = (
            PROJECT_ROOT
            / "scripts"
            / "data_crawling_handoff"
            / "templates"
            / relative
        )
        if relative in {
            "Dockerfile",
            ".dockerignore",
            "compose.yaml",
            "bin/start-novnc.sh",
        }:
            content = source_template.read_text(encoding="utf-8")
        elif relative == ".env.example":
            content = "DEMAND_DISCOVERY_API_KEY=replace-with-your-key\n"
        else:
            content = f"fixture template: {relative}\n"
        _write(handoff_root / "templates" / relative, content)
    _write(root / "scripts" / "package_data_crawling_handoff.py", "fixture\n")
    for relative in builder.HANDOFF_TEST_FILES:
        _write(root / relative, "fixture\n")

    _write(root / "scripts" / "journal" / ".env", "API_KEY=secret-value\n")
    _write(root / "cnki_keyword_crawler" / "cookie.txt", "secret-cookie\n")
    _write(root / "wechat_mp_collector" / "session.json", "secret-session\n")
    _write(root / "wechat_mp_collector" / "wx_qrcode.png", "not-an-image\n")
    return root


def test_package_excludes_secrets_and_writes_checksums(fixture_root, tmp_path):
    builder = _builder_module()

    result = builder.build_package(
        project_root=fixture_root,
        output_root=tmp_path / "packages",
        version="v1.0.0",
    )
    package_root = result.package_root

    assert not any(path.name == ".env" for path in package_root.rglob("*"))
    assert not any(path.name == "session.json" for path in package_root.rglob("*"))
    assert not any(path.name == "cookie.txt" for path in package_root.rglob("*"))
    assert not any(path.name == "wx_qrcode.png" for path in package_root.rglob("*"))
    assert result.checksum_path == package_root / "MANIFEST.sha256"
    assert result.checksum_path.exists()
    assert result.zip_path.exists()


def test_package_preserves_module_relative_layout(fixture_root, tmp_path):
    builder = _builder_module()

    result = builder.build_package(
        project_root=fixture_root,
        output_root=tmp_path / "packages",
        version="v1.0.0",
    )

    assert (
        result.package_root
        / "modules/journal/scripts/journal/download_zsdd.py"
    ).exists()
    assert (
        result.package_root
        / "modules/demand_discovery/src/knowledgegraph/demand_discovery/tools/acquisition.py"
    ).exists()
    assert (result.package_root / "crawler.py").exists()
    assert (result.package_root / "scripts/data_crawling_handoff/commands.py").exists()


def test_checksum_manifest_matches_sorted_package_files(fixture_root, tmp_path):
    builder = _builder_module()
    result = builder.build_package(
        project_root=fixture_root,
        output_root=tmp_path / "packages",
        version="v1.0.0",
    )

    rows = result.checksum_path.read_text(encoding="utf-8").splitlines()
    relative_paths = [row.split("  ", 1)[1] for row in rows]

    assert relative_paths == sorted(relative_paths)
    for row in rows:
        digest, relative = row.split("  ", 1)
        assert len(digest) == 64
        assert hashlib.sha256((result.package_root / relative).read_bytes()).hexdigest() == digest


def test_zip_has_single_top_level_directory_and_is_deterministic(fixture_root, tmp_path):
    builder = _builder_module()
    output_root = tmp_path / "packages"

    first = builder.build_package(fixture_root, output_root, "v1.0.0")
    first_digest = hashlib.sha256(first.zip_path.read_bytes()).hexdigest()
    second = builder.build_package(fixture_root, output_root, "v1.0.0")
    second_digest = hashlib.sha256(second.zip_path.read_bytes()).hexdigest()

    assert first_digest == second_digest
    with zipfile.ZipFile(second.zip_path) as archive:
        top_levels = {name.split("/", 1)[0] for name in archive.namelist() if name}
    assert top_levels == {second.package_root.name}


def test_package_rejects_secret_content_without_echoing_secret(fixture_root, tmp_path):
    builder = _builder_module()
    secret = "sk-" + "abcdefghijklmnop1234567890"
    _write(fixture_root / "scripts" / "journal" / "leak.py", f'TOKEN = "{secret}"\n')

    with pytest.raises(ValueError, match="secret pattern") as exc_info:
        builder.build_package(
            project_root=fixture_root,
            output_root=tmp_path / "packages",
            version="v1.0.0",
        )

    assert secret not in str(exc_info.value)
    assert "modules/journal/scripts/journal/leak.py" in str(exc_info.value)


def test_package_allows_marked_fake_credentials_in_test_fixtures(fixture_root, tmp_path):
    builder = _builder_module()
    _write(
        fixture_root / "scripts" / "journal" / "tests" / "fixture_config.py",
        'API_KEY = "fixture-test-value"\n',
    )

    result = builder.build_package(fixture_root, tmp_path / "packages", "v1.0.0")

    assert (
        result.package_root
        / "modules/journal/scripts/journal/tests/fixture_config.py"
    ).exists()


def test_generated_docker_templates_define_cli_and_browser_runtime(fixture_root, tmp_path):
    builder = _builder_module()
    result = builder.build_package(fixture_root, tmp_path / "packages", "v1.0.0")

    dockerfile = (result.package_root / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (result.package_root / ".dockerignore").read_text(encoding="utf-8")
    compose = (result.package_root / "compose.yaml").read_text(encoding="utf-8")
    start_script = (result.package_root / "bin/start-novnc.sh").read_text(
        encoding="utf-8"
    )

    assert "python:3.11" in dockerfile or "playwright/python" in dockerfile
    for dependency in ("chromium", "xvfb", "x11vnc", "novnc", "websockify", "openbox"):
        assert dependency in dockerfile.lower()
    assert "python -m playwright install chromium" in dockerfile
    for excluded in (".env", "runtime/", "data/"):
        assert excluded in dockerignore
    assert "profiles:" in compose and "browser" in compose
    assert "7900:7900" in compose
    assert "CRAWLER_DATA_ROOT: /workspace/data" in compose
    assert "./runtime:/workspace/runtime" in compose
    assert "shm_size: 2gb" in compose
    for command in ("set -eu", "Xvfb", "openbox", "x11vnc", "websockify"):
        assert command in start_script


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
