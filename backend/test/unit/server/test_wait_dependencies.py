"""验证启动等待不会提前放行，超时也不会伪装成就绪。"""

import httpx
import pytest

from server import wait_dependencies


@pytest.mark.asyncio
async def test_transient_connection_and_unhealthy_status_wait_for_success(monkeypatch):
    replies = [httpx.ConnectError("not ready"), 503, 200]
    sleeps = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def get(self, _url):
            reply = replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return httpx.Response(reply)

    async def sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(wait_dependencies.httpx, "AsyncClient", lambda **_: Client())
    monkeypatch.setattr(wait_dependencies.asyncio, "sleep", sleep)
    await wait_dependencies.wait_for_milvus("http://milvus:9091/healthz")
    assert not replies
    assert len(sleeps) == 2


@pytest.mark.asyncio
async def test_unhealthy_dependency_times_out(monkeypatch):
    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def get(self, _url):
            return httpx.Response(503)

    monkeypatch.setattr(wait_dependencies.httpx, "AsyncClient", lambda **_: Client())
    with pytest.raises(RuntimeError, match="startup timeout"):
        await wait_dependencies.wait_for_milvus("http://milvus:9091/healthz", timeout=0)
