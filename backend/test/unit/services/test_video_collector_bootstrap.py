"""验证重复双击不会创建两个竞争同一设备任务的连接进程。"""

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest


def test_connection_lock_is_released_when_process_handle_closes(tmp_path):
    """系统锁阻止重复启动，正常或异常退出后允许再次连接。"""
    path = Path(__file__).resolve().parents[3] / "video_collector/bootstrap.py"
    spec = importlib.util.spec_from_file_location("video_bootstrap", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    first = module.acquire_connection_lock(tmp_path)
    assert first is not None
    try:
        assert module.acquire_connection_lock(tmp_path) is None
    finally:
        first.close()
    resumed = module.acquire_connection_lock(tmp_path)
    assert resumed is not None
    resumed.close()


def test_first_launch_uses_server_and_prepares_actual_proxy(tmp_path, monkeypatch):
    """双击连接包走与 video_text 一致的 server 模式，准备采集通道后才连接网站。"""
    from platform_core.knowledge import wxchannels

    path = Path(__file__).resolve().parents[3] / "video_collector/bootstrap.py"
    spec = importlib.util.spec_from_file_location("video_bootstrap_start", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    commands = []
    binary = tmp_path / "bin/darwin-arm64/video-downloader"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"test")

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url):
            raise httpx.ConnectError("not started")

        def post(self, url):
            return httpx.Response(200, json={"code": 0}, request=httpx.Request("POST", url))

    prepare, run = AsyncMock(), AsyncMock()
    monkeypatch.setattr(module.httpx, "Client", Client)
    monkeypatch.setattr(module.subprocess, "Popen", lambda command, **kwargs: commands.append(command))
    monkeypatch.setattr(module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(module.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(wxchannels, "prepare_collector_connection", prepare)
    monkeypatch.setattr(module, "prepare_local_certificate", AsyncMock())
    monkeypatch.setenv("FFMPEG_PATH", "/test/original-ffmpeg")
    module.start({}, tmp_path, tmp_path, "/test/ffmpeg", run)
    assert commands == [[str(binary), "server", "--workdir", str(tmp_path / "downloader")]]
    assert prepare.await_count == 1
    run.assert_awaited_once_with({}, "http://127.0.0.1:2022/mcp")


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_trusted, consented", [(True, True), (False, True), (False, False)])
async def test_certificate_setup_reuses_existing_trust_or_waits_for_system_authorization(initial_trusted, consented):
    """已授权环境不重新装证书；首次授权未完成时不能继续启用代理。"""
    path = Path(__file__).resolve().parents[3] / "video_collector/bootstrap.py"
    spec = importlib.util.spec_from_file_location("video_bootstrap_certificate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    requests, generated, installed = [], initial_trusted, initial_trusted

    def respond(request):
        nonlocal generated, installed
        requests.append(request)
        assert request.url.host == "127.0.0.1"
        if request.url.path.endswith("generate"):
            generated = True
        if request.url.path.endswith("install"):
            installed = consented
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "is_legacy": not generated,
                    "installed": installed,
                    "trusted": installed,
                    "configured": {"file": "local-cert.pem"},
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        if initial_trusted or consented:
            await module.prepare_local_certificate(client)
        else:
            with pytest.raises(RuntimeError, match="系统授权"):
                await module.prepare_local_certificate(client)
    writes = [r.url.path for r in requests if r.method == "POST"]
    assert writes == ([] if initial_trusted else ["/api/proxy/certificate/generate", "/api/proxy/certificate/install"])
