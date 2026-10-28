"""AMiner MCP 凭证复用、连接边界和论文路径去重。"""

from unittest.mock import AsyncMock

import jwt
import pytest

from platform_core.agents.mcp.builtin import BUILTIN_MCP_SERVERS
from platform_core.agents.mcp.service import resolve_mcp_runtime_config
from platform_core.config.options import aminer_api_opts
from platform_core.storage.postgres.models_business import MCPServer


@pytest.mark.asyncio
async def test_aminer_runtime_uses_latest_credentials_without_persisting_or_redirecting(monkeypatch):
    """凭证修改即时生效，固定官方目标且不写回 MCP 表。"""
    config = {"enabled": True, "user_id": "user", "api_key": "Bearer eyJ.old.token"}
    monkeypatch.setattr(aminer_api_opts.__class__, "get", AsyncMock(side_effect=lambda _: dict(config)))
    server = MCPServer(
        slug="aminer-official",
        transport="streamable_http",
        url="https://untrusted.invalid/mcp",
        headers={"Authorization": "stale-secret"},
        disabled_tools=["search_paper"],
    )
    first = await resolve_mcp_runtime_config(server, db=object())
    assert first["url"] == "https://mcp.aminer.cn/mcp"
    assert first["headers"] == {"Authorization": "Bearer eyJ.old.token"}
    config["api_key"] = "eyJ.new.token"
    second = await resolve_mcp_runtime_config(server, db=object())
    assert second["headers"] == {"Authorization": "Bearer eyJ.new.token"}
    assert server.headers == {"Authorization": "stale-secret"}
    config["enabled"] = False
    assert await resolve_mcp_runtime_config(server, db=object()) is None


@pytest.mark.asyncio
async def test_raw_key_gets_short_lived_bearer_without_churning_cache(monkeypatch):
    """原始 Key 复用短期签名，五分钟桶内连接配置保持稳定。"""
    secret = "test-secret-key-at-least-32-characters"
    config = {"enabled": True, "user_id": "user", "api_key": secret}
    monkeypatch.setattr(aminer_api_opts.__class__, "get", AsyncMock(return_value=config))
    monkeypatch.setattr("platform_core.agents.mcp.service.time.time", lambda: 1800000010)
    server = MCPServer(slug="aminer-official", transport="streamable_http")
    first = await resolve_mcp_runtime_config(server, db=object())
    monkeypatch.setattr("platform_core.agents.mcp.service.time.time", lambda: 1800000200)
    second = await resolve_mcp_runtime_config(server, db=object())
    assert first == second
    token = first["headers"]["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(token, secret, algorithms=["HS256"], options={"verify_exp": False})
    assert claims["user_id"] == "user"
    assert claims["exp"] - claims["timestamp"] == 600
    assert server.headers is None


def test_builtin_aminer_disables_only_duplicate_paper_paths():
    """保留内置论文预算路径，其余官方 MCP 工具可正常启用。"""
    config = BUILTIN_MCP_SERVERS["aminer-official"]
    assert set(config["disabled_tools"]) == {
        "search_paper",
        "search_paper_by_title",
        "get_paper_detail",
        "get_papers_info",
        "get_paper_citations",
    }
    assert "headers" not in config
