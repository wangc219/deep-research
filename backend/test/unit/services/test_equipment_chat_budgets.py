"""统一聊天适配器必须保留工作流的调用预算与并发隔离。"""

import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from equipment_deep_research.providers.base import ModelMessage
from equipment_deep_research.providers.openai_compatible import OpenAICompatibleProvider
from equipment_deep_research.providers.responses import ProviderRetryableError


@pytest.fixture
def provider():
    return OpenAICompatibleProvider(
        provider_id="platform", model="chosen", base_url="http://localhost:9000/v1", api_key="test", timeout_seconds=9
    )


@pytest.mark.asyncio
async def test_transient_retry_respects_one_attempt(provider, monkeypatch):
    """上层只允许一次调用时，429 不在适配器内额外重放。"""
    calls = []

    def post(payload):
        calls.append(payload)
        raise ProviderRetryableError("capacity")

    monkeypatch.setattr(provider, "_post", post)
    with pytest.raises(ProviderRetryableError, match="capacity"):
        async for _ in provider.stream([ModelMessage("user", "hello")], [], {"_provider_retry_attempts": 1}):
            pass
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_concurrent_timeout_options_are_request_local(provider, monkeypatch):
    """不同任务的超时设置不能覆盖共享对象。"""
    observed = []

    def post(payload, **kwargs):
        observed.append(kwargs)
        return []

    monkeypatch.setattr(provider, "_post", post)
    await asyncio.gather(
        provider._post_with_transient_retry({}, options={"_provider_timeout_seconds": 2}),
        provider._post_with_transient_retry({}, options={"_disable_provider_timeout": True}),
        provider._post_with_transient_retry({}),
    )
    assert {tuple(row.items()) for row in observed} == {(("timeout_seconds", 2.0),), (("disable_timeout", True),), ()}
    assert provider.timeout_seconds == 9


@pytest.mark.asyncio
async def test_wall_timeout_bounds_live_sse_heartbeat_stream(provider):
    """持续收到 SSE 心跳也必须遵守总调用时限，且不能自动重试。"""
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            import time

            try:
                for _ in range(12):
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    time.sleep(0.15)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    provider.base_url = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
    try:
        started = asyncio.get_running_loop().time()
        with pytest.raises(ProviderRetryableError, match="timed out after 1 seconds"):
            await provider._post_with_transient_retry({}, options={"_provider_timeout_seconds": 1})
        assert asyncio.get_running_loop().time() - started < 1.7
        assert len(calls) == 1
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(timeout=2)
