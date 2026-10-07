"""Chat Completions 的 SSE 终止标记必须结束读取，不等待服务端断开。"""

import pytest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread

from equipment_deep_research.providers import openai_compatible


@pytest.mark.parametrize("terminal", [b"data: [DONE]\n", b"data:[DONE]\r\n"])
def test_chat_done_closes_response_without_reading_trailing_heartbeat(monkeypatch, terminal):
    """网关发出协议终态后仍保活时，结果和 usage 应立即交给业务层。"""
    class Response:
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.closed = True

        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"[DONE] is text"}}]}\n'
            yield b'\n'
            yield b'data: {"choices":[],"usage":{"total_tokens":5}}\n'
            yield b'\n'
            yield terminal
            raise AssertionError("terminal stream must not wait for more bytes")

    response = Response()
    monkeypatch.setattr(openai_compatible, "urlopen", lambda *args, **kwargs: response)
    provider = openai_compatible.OpenAICompatibleProvider(
        provider_id="test", model="neutral", base_url="http://localhost/v1", api_key="test-only",
    )
    lines = provider._post({"model": "neutral"}, disable_timeout=True)
    assert response.closed
    events = list(openai_compatible.iter_chat_sse(lines))
    assert any(event.get("usage", {}).get("total_tokens") == 5 for event in events)
    assert "[DONE] is text" in "".join(lines)


def test_chat_done_returns_over_http_while_gateway_keeps_connection_open():
    """真实 HTTP 网关不关闭响应时，终态仍能释放客户端连接。"""
    release = Event()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b'data: {"choices":[],"usage":{"total_tokens":5}}\n\ndata: [DONE]\n\n')
            self.wfile.flush()
            release.wait(5)
            self.close_connection = True

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        provider = openai_compatible.OpenAICompatibleProvider(
            provider_id="test", model="neutral",
            base_url=f"http://127.0.0.1:{server.server_port}/v1", api_key="test-only",
        )
        lines = provider._post({"model": "neutral"}, timeout_seconds=0.5)
        assert any(event.get("usage", {}).get("total_tokens") == 5 for event in openai_compatible.iter_chat_sse(lines))
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
