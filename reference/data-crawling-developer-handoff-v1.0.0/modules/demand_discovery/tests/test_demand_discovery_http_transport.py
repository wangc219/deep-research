from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import json
from pathlib import Path
import sys
import threading
from unittest.mock import patch

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def _transport_module():
    try:
        return importlib.import_module(
            "knowledgegraph.demand_discovery.tools.http_transport"
        )
    except ModuleNotFoundError:
        pytest.fail("shared demand-discovery HTTP transport is not implemented")


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/text":
            body = "中文正文".encode("gb18030")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=gb18030")
        elif self.path == "/large":
            body = b"0123456789"
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
        elif self.path.startswith("/json"):
            body = json.dumps({"method": "GET", "ok": True}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
        else:
            body = b"not found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        body = json.dumps(
            {"method": "POST", "payload": payload},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def http_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_default_http_transport_truncates_response(http_server: str) -> None:
    transport = _transport_module()

    response = asyncio.run(
        transport.default_http_transport(f"{http_server}/large", 5_000, 4)
    )

    assert response.status_code == 200
    assert response.content == b"0123"
    assert response.truncated is True


def test_decode_response_uses_declared_charset(http_server: str) -> None:
    transport = _transport_module()

    response = transport.request_bytes("GET", f"{http_server}/text")

    assert transport.header_value(response.headers, "content-type").startswith(
        "text/plain"
    )
    assert transport.decode_response(response) == "中文正文"


def test_request_json_supports_get_and_post(http_server: str) -> None:
    transport = _transport_module()

    get_payload = transport.request_json("GET", f"{http_server}/json")
    post_payload = transport.request_json(
        "POST",
        f"{http_server}/post",
        json_body={"query": "无人机"},
    )

    assert get_payload == {"method": "GET", "ok": True}
    assert post_payload == {
        "method": "POST",
        "payload": {"query": "无人机"},
    }


def test_request_bytes_retries_transient_request_failure() -> None:
    transport = _transport_module()

    class _Response:
        url = "https://example.test/final"
        status_code = 200
        headers = {"Content-Type": "text/plain"}
        content = b"ok"

    calls = {"count": 0}

    def request(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise TimeoutError("transient")
        return _Response()

    with patch.object(transport.requests, "request", side_effect=request):
        response = transport.request_bytes(
            "GET",
            "https://example.test/start",
            max_retries=1,
            retry_sleep_seconds=0,
        )

    assert calls["count"] == 2
    assert response.url == "https://example.test/final"
    assert response.content == b"ok"


def test_request_bytes_accepts_method_specific_request_sender() -> None:
    transport = _transport_module()

    class _Response:
        url = "https://example.test/final"
        status_code = 200
        headers = {"Content-Type": "text/plain"}
        content = b"ok"

    calls: list[dict[str, object]] = []

    def get(url: str, **kwargs: object) -> _Response:
        calls.append({"url": url, **kwargs})
        return _Response()

    response = transport.request_bytes(
        "GET",
        "https://example.test/start",
        request_sender=get,
    )

    assert response.url == "https://example.test/final"
    assert calls[0]["url"] == "https://example.test/start"
    assert "method" not in calls[0]
