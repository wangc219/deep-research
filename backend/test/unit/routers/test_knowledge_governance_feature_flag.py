import importlib

import pytest
from fastapi import FastAPI, HTTPException

from server.routers.knowledge_governance_router import (
    require_source_governance_enabled,
    source_governance_enabled,
)


@pytest.mark.asyncio
async def test_source_governance_enabled_for_local_development(monkeypatch):
    monkeypatch.setenv("DEEP_RESEARCH_SOURCE_GOVERNANCE_ENABLED", "true")

    assert source_governance_enabled() is True
    assert await require_source_governance_enabled() is None


@pytest.mark.asyncio
async def test_source_governance_hidden_when_cloud_flag_is_disabled(monkeypatch):
    monkeypatch.setenv("DEEP_RESEARCH_SOURCE_GOVERNANCE_ENABLED", "false")

    assert source_governance_enabled() is False
    with pytest.raises(HTTPException) as error:
        await require_source_governance_enabled()
    assert error.value.status_code == 404


def test_cloud_does_not_register_source_governance_routes(monkeypatch):
    monkeypatch.setenv("DEEP_RESEARCH_SOURCE_GOVERNANCE_ENABLED", "false")
    knowledge_router = importlib.import_module("server.routers.knowledge_router")
    disabled_router = importlib.reload(knowledge_router)

    try:
        app = FastAPI()
        app.include_router(disabled_router.knowledge)
        paths = set(app.openapi()["paths"])
        assert "/knowledge/categories" not in paths
        assert "/knowledge/sources" not in paths
        assert "/knowledge/staging" not in paths
        assert "/knowledge/briefs" in paths
    finally:
        monkeypatch.setenv("DEEP_RESEARCH_SOURCE_GOVERNANCE_ENABLED", "true")
        importlib.reload(knowledge_router)
