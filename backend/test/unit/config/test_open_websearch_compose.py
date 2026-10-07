from pathlib import Path

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


def test_initialization_defaults_to_open_websearch_container_dns():
    source = (_project_root() / "scripts/init.sh").read_text()

    assert 'WEB_SEARCH_PROVIDER="open-websearch"' in source
    assert 'echo "OPEN_WEBSEARCH_URL=http://open-websearch:3210"' in source
    assert 'echo "OPEN_WEBSEARCH_ENGINES=bing,duckduckgo"' in source
