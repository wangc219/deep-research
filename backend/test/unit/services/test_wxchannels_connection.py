"""验证微信采集连接使用实际系统代理状态，而非仅检查 MCP 端口。"""

from unittest.mock import AsyncMock

import httpx
import pytest

from platform_core.knowledge.wxchannels import WxChannelsError, prepare_collector_connection


@pytest.mark.asyncio
async def test_disabled_system_proxy_is_repaired_and_confirmed(monkeypatch):
    """MCP 已启用但系统代理关闭时自动恢复；重启期间短暂断线可恢复。"""
    from platform_core.knowledge import wxchannels

    monkeypatch.setattr(wxchannels.asyncio, "sleep", AsyncMock())
    requests, checks = [], 0

    def respond(request):
        nonlocal checks
        requests.append(request)
        if request.url.path == "/api/mcp/enable":
            return httpx.Response(200, json={"code": 0, "data": {"enabled": True}})
        if request.url.path == "/api/proxy/config":
            return httpx.Response(200, json={"code": 0})
        checks += 1
        if checks == 2:
            raise httpx.ConnectError("restarting")
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "certificate": {"installed": True, "trusted": True, "is_legacy": False},
                    "config": {"enabled": True, "system": True},
                    "service": {"listening": True},
                    "system_proxy": {"matched": checks > 2},
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await prepare_collector_connection(client, "http://native:2022")
    assert result == {"proxy_ready": True, "certificate_ready": True}
    assert checks == 3
    changes = [r for r in requests if r.url.path == "/api/proxy/config"]
    assert len(changes) == 1
    assert b'"proxy.system":true' in changes[0].content
    assert not any("certificate/" in r.url.path for r in requests)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "certificate",
    [
        {"installed": False, "trusted": False, "is_legacy": False},
        {"installed": True, "trusted": True, "is_legacy": True},
    ],
)
async def test_untrusted_or_legacy_certificate_does_not_enable_proxy(certificate):
    """证书未完成系统授权时保留明确错误，不自动生成或扩大信任。"""
    requests = []

    def respond(request):
        requests.append(request)
        data = (
            {"enabled": True}
            if request.url.path.endswith("enable")
            else {
                "certificate": certificate,
                "service": {"listening": True},
                "system_proxy": {"matched": False},
            }
        )
        return httpx.Response(200, json={"code": 0, "data": data})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(WxChannelsError, match="信任"):
            await prepare_collector_connection(client, "http://native:2022")
    assert [r.url.path for r in requests] == ["/api/mcp/enable", "/api/proxy/status"]


@pytest.mark.asyncio
async def test_mcp_business_error_does_not_report_connection_success():
    """HTTP 200 下的业务失败也必须阻止伪成功。"""
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"code": 5001, "data": {"enabled": True}})
        )
    ) as client:
        with pytest.raises(WxChannelsError, match="MCP"):
            await prepare_collector_connection(client, "http://native:2022")
