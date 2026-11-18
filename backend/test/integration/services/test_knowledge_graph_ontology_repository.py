from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select

from server.routers import graph_router
from platform_core.knowledge.graphs.defense_ontology import ontology_payload
from platform_core.repositories.knowledge_graph_governance_repository import KnowledgeGraphGovernanceRepository
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_knowledge import OntologyVersion

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_ontology_repository_persists_effective_version_lineage_and_lists_it():
    suffix = uuid4().hex[:10]
    base_version = f"pytest-ontology-{suffix}-1.0"
    next_version = f"pytest-ontology-{suffix}-1.1"
    base = deepcopy(ontology_payload())
    base["version"] = base_version
    base["name"] = "测试基础本体"
    extended = deepcopy(base)
    extended["version"] = next_version
    extended["name"] = "测试扩展本体"
    extended["entity_types"].append(
        {"code": "OperationalConcept", "name_zh": "作战概念", "description": "测试扩展类型"}
    )
    repository = KnowledgeGraphGovernanceRepository()

    try:
        pg_manager.initialize()
        await pg_manager.upgrade_knowledge_schema_v16_to_v17()
        assert (
            await repository.register_ontology(
                base,
                created_by="ontology-admin",
                change_reason="建立测试基础版本",
            )
            == base_version
        )
        assert (
            await repository.register_ontology(
                extended,
                created_by="ontology-admin",
                previous_version=base_version,
                change_reason="增加作战概念层",
            )
            == next_version
        )
        assert (
            await repository.register_ontology(
                extended,
                created_by="ontology-admin",
                previous_version=base_version,
                change_reason="增加作战概念层",
            )
            == next_version
        )

        record = await repository.get_ontology_version(next_version)
        assert record is not None
        assert record["previous_version"] == base_version
        assert record["change_reason"] == "增加作战概念层"
        assert record["effective_at"] is not None
        assert record["entity_type_count"] == 13
        versions = await repository.list_ontology_versions(limit=200)
        assert next_version in {item["version"] for item in versions}

        async with pg_manager.get_async_session_context() as session:
            stored = await session.scalar(select(OntologyVersion).where(OntologyVersion.version == next_version))
            assert stored is not None
            assert stored.effective_at is not None
    finally:
        async with pg_manager.get_async_session_context() as session:
            await session.execute(
                delete(OntologyVersion).where(OntologyVersion.version.in_([base_version, next_version]))
            )


async def test_ontology_version_http_round_trip_uses_real_postgres():
    suffix = uuid4().hex[:10]
    base_version = f"pytest-http-ontology-{suffix}-1.0"
    next_version = f"pytest-http-ontology-{suffix}-1.1"
    base = deepcopy(ontology_payload())
    base["version"] = base_version
    base["name"] = "HTTP 测试基础本体"
    extended = deepcopy(base)
    extended["version"] = next_version
    extended["name"] = "HTTP 测试扩展本体"
    extended["entity_types"].append(
        {"code": "OperationalConcept", "name_zh": "作战概念", "description": "跨领域任务运用概念"}
    )
    extended["relation_types"].append(
        {
            "code": "SUPPORTS_CONCEPT",
            "name_zh": "支撑概念",
            "description": "能力支撑作战概念",
            "head_types": ["Capability"],
            "tail_types": ["OperationalConcept"],
            "directed": True,
            "allow_self": False,
            "hypothesis_only": False,
        }
    )
    pg_manager.initialize()
    await pg_manager.upgrade_knowledge_schema_v16_to_v17()
    app = FastAPI()
    app.include_router(graph_router.graph)
    app.dependency_overrides[graph_router.get_admin_user] = lambda: SimpleNamespace(uid="ontology-admin")

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            base_response = await client.post(
                "/graph/ontology/versions",
                json={**base, "previous_version": None, "change_reason": "建立 HTTP 测试基础版本"},
            )
            next_response = await client.post(
                "/graph/ontology/versions",
                json={
                    **extended,
                    "previous_version": base_version,
                    "change_reason": "增加作战概念扩展层",
                },
            )
            detail_response = await client.get(f"/graph/ontology/versions/{next_version}")
            list_response = await client.get("/graph/ontology/versions")

        assert base_response.status_code == 200, base_response.text
        assert next_response.status_code == 200, next_response.text
        assert next_response.json()["data"]["effective_at"] is not None
        assert next_response.json()["data"]["change_set"]["entity_types"]["added"][0]["code"] == ("OperationalConcept")
        assert detail_response.status_code == 200, detail_response.text
        assert detail_response.json()["data"]["previous_version"] == base_version
        assert next_version in {item["version"] for item in list_response.json()["data"]["items"]}
    finally:
        async with pg_manager.get_async_session_context() as session:
            await session.execute(
                delete(OntologyVersion).where(OntologyVersion.version.in_([base_version, next_version]))
            )
