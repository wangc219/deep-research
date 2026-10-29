from pathlib import Path
import subprocess

import pytest
import yaml


def _project_root() -> Path:
    """定位包含 Compose 文件的仓库根目录。"""

    for parent in Path(__file__).resolve().parents:
        if (parent / "compose.yaml").exists():
            return parent
    pytest.skip("当前测试环境未挂载仓库根目录")


@pytest.mark.parametrize("filename", ["compose.yaml", "compose.prod.yaml"])
def test_open_websearch_is_portable_and_shared_by_api_and_worker(filename):
    compose = yaml.safe_load((_project_root() / filename).read_text())
    shared_environment = compose["x-api-worker-env"]
    service = compose["services"]["open-websearch"]

    assert shared_environment["WEB_SEARCH_PROVIDER"] == "${WEB_SEARCH_PROVIDER:-open-websearch}"
    assert shared_environment["OPEN_WEBSEARCH_URL"] == "${OPEN_WEBSEARCH_URL:-http://open-websearch:3210}"
    assert shared_environment["OPEN_WEBSEARCH_ENGINES"] == "${OPEN_WEBSEARCH_ENGINES:-bing,duckduckgo}"
    assert "open-websearch" in shared_environment["NO_PROXY"]
    assert "@sha256:" in service["image"]
    assert service["command"] == [
        "node",
        "build/index.js",
        "serve",
        "--host",
        "0.0.0.0",
        "--port",
        "3210",
    ]
    assert service["expose"] == ["3210"]
    assert "ports" not in service
    assert compose["services"]["api"]["depends_on"]["open-websearch"]["condition"] == "service_healthy"
    assert compose["services"]["worker"]["depends_on"]["open-websearch"]["condition"] == "service_healthy"


@pytest.mark.parametrize("filename", ["compose.yaml", "compose.prod.yaml"])
def test_searxng_is_internal_optional_and_shared_by_api_and_worker(filename):
    compose = yaml.safe_load((_project_root() / filename).read_text())
    shared_environment = compose["x-api-worker-env"]
    service = compose["services"]["searxng"]

    assert shared_environment["SEARXNG_URL"] == "${SEARXNG_URL:-http://searxng:8080}"
    assert "searxng" in shared_environment["NO_PROXY"]
    assert service["image"].endswith("@sha256:268a4b460136dcefc8f2e896b6098ba3f770c8218dbbddcb86811b06b06816f1}")
    assert service["expose"] == ["8080"]
    assert "ports" not in service
    assert service["healthcheck"]["test"][-1].endswith("/healthz | grep -qx OK")
    assert any(value.endswith(":/etc/searxng/settings.yml:ro") for value in service["volumes"])
    assert compose["services"]["api"]["depends_on"]["searxng"]["condition"] == "service_started"
    assert compose["services"]["worker"]["depends_on"]["searxng"]["condition"] == "service_started"


def test_initialization_defaults_to_open_websearch_container_dns():
    source = (_project_root() / "scripts/init.sh").read_text()

    assert 'WEB_SEARCH_PROVIDER="open-websearch"' in source
    assert 'echo "OPEN_WEBSEARCH_URL=http://open-websearch:3210"' in source
    assert 'echo "OPEN_WEBSEARCH_ENGINES=bing,duckduckgo"' in source
    assert 'ensure_security_secret "SEARXNG_SECRET"' in source


def test_searxng_settings_enable_only_json_and_the_reviewed_engine_catalog():
    settings = yaml.safe_load((_project_root() / "configs/searxng/settings.yml").read_text())
    engines = settings["use_default_settings"]["engines"]["keep_only"]

    assert settings["search"]["formats"] == ["json"]
    assert settings["server"]["limiter"] is False
    assert settings["server"]["public_instance"] is False
    assert {"brave", "baidu", "sogou", "arxiv", "semantic scholar", "pubmed", "reuters"}.issubset(engines)


def test_environment_migration_adds_one_independent_searxng_secret_idempotently(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("JWT_SECRET_KEY=0123456789abcdef0123456789abcdef\n")
    script = _project_root() / "scripts/migrate-environment.sh"

    subprocess.run(["bash", str(script), str(env_file)], check=True, capture_output=True, text=True)
    first = env_file.read_text().splitlines()
    subprocess.run(["bash", str(script), str(env_file)], check=True, capture_output=True, text=True)
    second = env_file.read_text().splitlines()

    secrets = [line.split("=", 1)[1] for line in second if line.startswith("SEARXNG_SECRET=")]
    assert first == second
    assert len(secrets) == 1
    assert len(secrets[0]) >= 64
