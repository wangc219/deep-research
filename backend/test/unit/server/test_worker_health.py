"""轻量探针必须检查独立 Worker 的有效健康租约。"""

from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from server import worker_health


@pytest.mark.parametrize("ttl,healthy", [(3000, True), (0, False), (7000, False)])
def test_health_probe_uses_own_pool_and_bounded_lease(monkeypatch, ttl, healthy):
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("AGENT_WORKER_KIND", "deep")
    client = SimpleNamespace(get=MagicMock(return_value=b"healthy"), pttl=MagicMock(return_value=ttl))
    context = MagicMock()
    context.__enter__.return_value = client
    monkeypatch.setattr(worker_health.Redis, "from_url", lambda *args, **kwargs: context)
    if healthy:
        worker_health.main()
    else:
        with pytest.raises(SystemExit):
            worker_health.main()
    client.get.assert_called_once_with("deep-research:worker:health:agent-run-v1:deep")
