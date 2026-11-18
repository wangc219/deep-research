from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_knowledge import (
    KnowledgeDocumentCard,
    KnowledgeFile,
    KnowledgeResearchThread,
    KnowledgeSourceDocument,
    OntologyVersion,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def _create_dify_database(test_client, admin_headers) -> str:
    response = await test_client.post(
        "/api/knowledge/databases",
        json={
            "database_name": f"pytest_graph_dify_{uuid.uuid4().hex[:8]}",
            "description": "Graph router Dify negative test",
            "kb_type": "dify",
            "additional_params": {
                "dify_api_url": "https://api.dify.ai/v1",
                "dify_token": "test-token",
                "dify_dataset_id": f"dataset-{uuid.uuid4().hex[:8]}",
            },
        },
        headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["kb_id"]


async def _delete_database(test_client, admin_headers, kb_id: str) -> None:
    await test_client.delete(f"/api/knowledge/databases/{kb_id}", headers=admin_headers)


async def test_graph_routes_require_auth(test_client):
    response = await test_client.get("/api/graph/list")
    ontology_response = await test_client.get("/api/graph/ontology")

    assert response.status_code == 401
    assert ontology_response.status_code == 401


async def test_standard_user_cannot_access_graph_endpoints(test_client, standard_user):
    response = await test_client.get("/api/graph/list", headers=standard_user["headers"])
    assert response.status_code == 403


async def test_graph_ontology_http_contract(test_client, admin_headers):
    register_response = await test_client.post(
        "/api/graph/ontology/register-default",
        headers=admin_headers,
    )
    read_response = await test_client.get(
        "/api/graph/ontology",
        params={"version": "defense-kg-1.0"},
        headers=admin_headers,
    )

    assert register_response.status_code == 200, register_response.text
    assert read_response.status_code == 200, read_response.text
    definition = read_response.json()["data"]
    assert definition["version"] == "defense-kg-1.0"
    assert len(definition["entity_types"]) == 12
    assert len(definition["relation_types"]) == 19


async def test_graph_ontology_version_extension_http_contract(test_client, admin_headers):
    suffix = uuid.uuid4().hex[:10]
    version = f"defense-kg-pytest-{suffix}"
    await test_client.post("/api/graph/ontology/register-default", headers=admin_headers)
    default_response = await test_client.get(
        "/api/graph/ontology",
        params={"version": "defense-kg-1.0"},
        headers=admin_headers,
    )
    definition = default_response.json()["data"]
    definition["version"] = version
    definition["name"] = "HTTP 多领域扩展测试本体"
    definition["entity_types"].append(
        {"code": "OperationalConcept", "name_zh": "作战概念", "description": "跨领域任务运用概念"}
    )
    definition["relation_types"].append(
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

    try:
        registered = await test_client.post(
            "/api/graph/ontology/versions",
            json={
                **definition,
                "previous_version": "defense-kg-1.0",
                "change_reason": "增加作战概念扩展层",
            },
            headers=admin_headers,
        )
        detail = await test_client.get(f"/api/graph/ontology/versions/{version}", headers=admin_headers)
        versions = await test_client.get("/api/graph/ontology/versions", headers=admin_headers)

        assert registered.status_code == 200, registered.text
        assert registered.json()["data"]["effective_at"] is not None
        assert registered.json()["data"]["change_set"]["entity_types"]["added"][0]["code"] == "OperationalConcept"
        assert detail.status_code == 200, detail.text
        assert detail.json()["data"]["previous_version"] == "defense-kg-1.0"
        assert version in {item["version"] for item in versions.json()["data"]["items"]}
    finally:
        async with pg_manager.get_async_session_context() as session:
            await session.execute(delete(OntologyVersion).where(OntologyVersion.version == version))


async def test_authenticated_annotator_can_read_graph_ontology(test_client, standard_user):
    response = await test_client.get("/api/graph/ontology", headers=standard_user["headers"])

    assert response.status_code == 200, response.text
    assert response.json()["data"]["version"] == "defense-kg-1.0"


async def test_graph_review_and_projection_routes_enforce_knowledge_permissions(
    test_client,
    standard_user,
    knowledge_database,
):
    kb_id = knowledge_database["kb_id"]

    queue_response = await test_client.get(
        "/api/graph/review-queue",
        params={"kb_id": kb_id},
        headers=standard_user["headers"],
    )
    decision_response = await test_client.post(
        f"/api/graph/databases/{kb_id}/review-decisions",
        json={
            "target_type": "entity_mention",
            "target_id": "1",
            "decision": "accepted",
        },
        headers=standard_user["headers"],
    )
    replay_response = await test_client.post(
        "/api/graph/projections/replay",
        params={"kb_id": kb_id},
        headers=standard_user["headers"],
    )
    conflicts_response = await test_client.get(
        f"/api/graph/databases/{kb_id}/conflicts",
        headers=standard_user["headers"],
    )
    register_conflict_response = await test_client.post(
        f"/api/graph/databases/{kb_id}/conflicts",
        json={
            "conflict_type": "relation_direction",
            "left_target_type": "relation",
            "left_target_id": "relation-1",
            "severity": "high",
            "summary": "关系方向冲突",
        },
        headers=standard_user["headers"],
    )

    assert queue_response.status_code == 403
    assert decision_response.status_code == 403
    assert replay_response.status_code == 403
    assert conflicts_response.status_code == 403
    assert register_conflict_response.status_code == 403


async def test_graph_innovation_and_evolution_routes_enforce_knowledge_permissions(
    test_client,
    standard_user,
    knowledge_database,
):
    kb_id = knowledge_database["kb_id"]

    discover_response = await test_client.post(
        f"/api/graph/databases/{kb_id}/innovation/discover",
        json={"query": "复杂环境感知", "discovery_mode": "top_down"},
        headers=standard_user["headers"],
    )
    solution_response = await test_client.post(
        f"/api/graph/databases/{kb_id}/innovation/solution",
        json={
            "query": "复杂环境感知",
            "discovery_mode": "top_down",
            "llm_enabled": False,
        },
        headers=standard_user["headers"],
    )
    candidates_response = await test_client.get(
        f"/api/graph/databases/{kb_id}/innovation/candidates",
        headers=standard_user["headers"],
    )
    evolution_response = await test_client.post(
        f"/api/graph/databases/{kb_id}/entities/entity-1/evolution/analyze",
        headers=standard_user["headers"],
    )
    redirect_response = await test_client.post(
        f"/api/graph/databases/{kb_id}/entities/entity-1/redirect",
        json={"operation": "merge", "target_entity_ids": ["entity-2"], "reason": "test"},
        headers=standard_user["headers"],
    )

    assert discover_response.status_code == 403
    assert solution_response.status_code == 403
    assert candidates_response.status_code == 403
    assert evolution_response.status_code == 403
    assert redirect_response.status_code == 403


async def test_graph_path_reranking_missing_model_is_rejected_at_http_boundary(
    test_client,
    admin_headers,
    knowledge_database,
):
    """缺少模型的 LLM 重排不能继续执行图检索或模型调用。"""
    response = await test_client.get(
        "/api/graph/paths",
        params={
            "kb_id": knowledge_database["kb_id"],
            "query": "复杂电磁环境感知",
            "path_reranking_enabled": True,
        },
        headers=admin_headers,
    )

    assert response.status_code == 422
    assert "path_reranking_model_spec" in response.json()["detail"]


async def test_graph_acceptance_routes_enforce_read_and_manage_permissions(
    test_client,
    standard_user,
    knowledge_database,
):
    kb_id = knowledge_database["kb_id"]

    status_response = await test_client.get(
        f"/api/graph/databases/{kb_id}/acceptance/status",
        headers=standard_user["headers"],
    )
    record_response = await test_client.post(
        f"/api/graph/databases/{kb_id}/acceptance/evaluations",
        json={
            "pipeline_revision": "hybrid-v2-r1",
            "gold_manifest_sha256": "a" * 64,
            "prediction_sha256": "b" * 64,
            "report": {},
        },
        headers=standard_user["headers"],
    )
    runs_response = await test_client.get(
        f"/api/graph/databases/{kb_id}/build-runs",
        headers=standard_user["headers"],
    )

    assert status_response.status_code == 403
    assert record_response.status_code == 403
    assert runs_response.status_code == 403


async def test_graph_document_card_routes_enforce_knowledge_permissions(
    test_client,
    standard_user,
    knowledge_database,
):
    kb_id = knowledge_database["kb_id"]

    list_response = await test_client.get(
        f"/api/graph/databases/{kb_id}/document-cards",
        headers=standard_user["headers"],
    )
    detail_response = await test_client.get(
        f"/api/graph/databases/{kb_id}/document-cards/missing",
        headers=standard_user["headers"],
    )

    assert list_response.status_code == 403
    assert detail_response.status_code == 403


async def test_graph_document_card_http_contract(test_client, admin_headers, knowledge_database):
    kb_id = knowledge_database["kb_id"]
    suffix = uuid.uuid4().hex[:12]
    file_id = f"file-{suffix}"
    document_id = f"doc-{suffix}"
    card_id = f"card-{suffix}"
    thread_id = f"thread-{suffix}"
    evidence_ref = {
        "block_id": f"block-{suffix}",
        "page": 3,
        "start": 12,
        "end": 28,
    }

    empty_response = await test_client.get(
        f"/api/graph/databases/{kb_id}/document-cards",
        headers=admin_headers,
    )
    assert empty_response.status_code == 200, empty_response.text
    assert empty_response.json()["data"] == {"items": [], "count": 0}

    async with pg_manager.get_async_session_context() as session:
        session.add(
            KnowledgeFile(
                file_id=file_id,
                kb_id=kb_id,
                filename="document-audit-http-contract.pdf",
            )
        )
        await session.flush()
        session.add(
            KnowledgeSourceDocument(
                document_id=document_id,
                kb_id=kb_id,
                file_id=file_id,
                source_type="paper",
                language="zh",
                current_version=1,
            )
        )
        await session.flush()
        session.add(
            KnowledgeResearchThread(
                thread_id=thread_id,
                kb_id=kb_id,
                document_id=document_id,
                document_version=1,
                thread_key="main:radar",
                thread_type="main",
                title="雷达抗干扰研究主线",
                evidence_refs=[evidence_ref],
                confidence=0.91,
                pipeline_revision="hybrid-v2-r1",
                governance_status="accepted",
            )
        )
        session.add(
            KnowledgeDocumentCard(
                card_id=card_id,
                kb_id=kb_id,
                document_id=document_id,
                document_version=1,
                title="雷达抗干扰研究论文",
                source_summary={"source_type": "paper", "language": "zh"},
                triage={"document_kind": "research_article"},
                content_overview="论文研究自适应抗干扰技术。",
                main_thread_id=thread_id,
                core_entity_ids=["entity-1"],
                core_relation_ids=["relation-1"],
                technology_families=["自适应抗干扰"],
                capability_gains=["复杂电磁环境感知"],
                application_directions=["雷达探测"],
                evidence_refs=[evidence_ref],
                uncertainty="仍需更多工程验证证据。",
                pipeline_revision="hybrid-v2-r1",
                ontology_version="defense-kg-1.0",
                governance_status="accepted",
            )
        )

    list_response = await test_client.get(
        f"/api/graph/databases/{kb_id}/document-cards",
        params={"governance_status": "accepted"},
        headers=admin_headers,
    )
    detail_response = await test_client.get(
        f"/api/graph/databases/{kb_id}/document-cards/{card_id}",
        headers=admin_headers,
    )
    missing_response = await test_client.get(
        f"/api/graph/databases/{kb_id}/document-cards/missing",
        headers=admin_headers,
    )

    assert list_response.status_code == 200, list_response.text
    assert list_response.json()["data"]["count"] == 1
    assert list_response.json()["data"]["items"][0]["card_id"] == card_id
    assert "evidence_refs" not in list_response.json()["data"]["items"][0]
    assert detail_response.status_code == 200, detail_response.text
    assert detail_response.json()["data"]["evidence_refs"] == [evidence_ref]
    assert detail_response.json()["data"]["threads"][0]["thread_id"] == thread_id
    assert missing_response.status_code == 404, missing_response.text


async def test_graph_innovation_and_evolution_empty_list_contracts(
    test_client,
    admin_headers,
    knowledge_database,
):
    kb_id = knowledge_database["kb_id"]

    candidates_response = await test_client.get(
        f"/api/graph/databases/{kb_id}/innovation/candidates",
        headers=admin_headers,
    )
    evolution_response = await test_client.get(
        f"/api/graph/databases/{kb_id}/entities/missing/evolution",
        headers=admin_headers,
    )
    history_response = await test_client.get(
        f"/api/graph/databases/{kb_id}/entities/missing/history",
        headers=admin_headers,
    )

    assert candidates_response.status_code == 200, candidates_response.text
    assert candidates_response.json()["data"] == {"items": [], "count": 0}
    assert evolution_response.status_code == 200, evolution_response.text
    assert evolution_response.json()["data"] == {"items": [], "count": 0}
    assert history_response.status_code == 404, history_response.text


async def test_graph_review_validation_and_empty_projection_replay(
    test_client,
    admin_headers,
    knowledge_database,
):
    kb_id = knowledge_database["kb_id"]

    invalid_decision = await test_client.post(
        f"/api/graph/databases/{kb_id}/review-decisions",
        json={
            "target_type": "entity_mention",
            "target_id": "not-a-number",
            "decision": "accepted",
        },
        headers=admin_headers,
    )
    missing_decision = await test_client.post(
        f"/api/graph/databases/{kb_id}/review-decisions",
        json={
            "target_type": "entity_mention",
            "target_id": "999999999",
            "decision": "accepted",
        },
        headers=admin_headers,
    )
    replay_response = await test_client.post(
        "/api/graph/projections/replay",
        params={"kb_id": kb_id, "limit": 10},
        headers=admin_headers,
    )

    assert invalid_decision.status_code == 422, invalid_decision.text
    assert missing_decision.status_code == 404, missing_decision.text
    assert replay_response.status_code == 200, replay_response.text
    assert replay_response.json()["data"] == {"claimed": 0, "completed": 0, "failed": 0}


async def test_get_graphs_list_only_returns_milvus(test_client, admin_headers, knowledge_database):
    response = await test_client.get("/api/graph/list", headers=admin_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert isinstance(payload["data"], list)
    assert payload["data"]
    assert all(graph["type"] == "milvus" for graph in payload["data"])
    assert any(graph["id"] == knowledge_database["kb_id"] for graph in payload["data"])


@pytest.mark.parametrize("path", ["/api/graph/subgraph", "/api/graph/stats", "/api/graph/labels"])
async def test_graph_endpoints_reject_non_milvus_types(test_client, admin_headers, path):
    kb_id = await _create_dify_database(test_client, admin_headers)
    try:
        response = await test_client.get(path, params={"kb_id": kb_id}, headers=admin_headers)
    finally:
        await _delete_database(test_client, admin_headers, kb_id)

    assert response.status_code == 404
    assert "only supports Milvus" in response.text


@pytest.mark.parametrize(
    ("path", "params", "expected_keys"),
    [
        ("/api/graph/subgraph", {"node_label": "*", "max_nodes": 10}, ("nodes", "edges")),
        ("/api/graph/stats", {}, ("total_nodes", "total_edges", "entity_types")),
        ("/api/graph/labels", {}, ("labels",)),
    ],
)
async def test_milvus_graph_endpoints(test_client, admin_headers, knowledge_database, path, params, expected_keys):
    response = await test_client.get(
        path,
        params={"kb_id": knowledge_database["kb_id"], **params},
        headers=admin_headers,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["success"] is True
    for key in expected_keys:
        assert key in payload["data"]


@pytest.mark.parametrize(
    "path",
    [
        "/api/graph/neo4j/nodes",
        "/api/graph/neo4j/node",
        "/api/graph/neo4j/info",
        "/api/graph/neo4j/index-entities",
        "/api/graph/neo4j/add-entities",
    ],
)
async def test_neo4j_upload_routes_are_removed(test_client, admin_headers, path):
    method = test_client.post if path.endswith(("index-entities", "add-entities")) else test_client.get
    response = await method(path, headers=admin_headers)
    assert response.status_code == 404
