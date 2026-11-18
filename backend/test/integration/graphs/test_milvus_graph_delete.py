from __future__ import annotations

from uuid import uuid4

import pytest

from platform_core.knowledge.graphs.milvus_graph_service import MilvusGraphService
from platform_core.storage.neo4j import get_shared_neo4j_connection, safe_neo4j_label


@pytest.mark.integration
def test_delete_file_graph_preserves_shared_and_unrelated_entities():
    kb_id = f"pytest_delete_graph_{uuid4().hex}"
    label = safe_neo4j_label(kb_id)
    connection = get_shared_neo4j_connection()
    service = MilvusGraphService(neo4j_connection=connection)

    try:
        with connection.driver.session() as session:
            session.run(
                f"""
                CREATE (f1:Chunk:MilvusKB:`{label}` {{kb_id: $kb_id, file_id: 'f1'}}),
                       (f2:Chunk:MilvusKB:`{label}` {{kb_id: $kb_id, file_id: 'f2'}}),
                       (shared:Entity:MilvusKB:`{label}` {{kb_id: $kb_id, name: 'shared'}}),
                       (f1_only:Entity:MilvusKB:`{label}` {{kb_id: $kb_id, name: 'f1_only'}}),
                       (unrelated_orphan:Entity:MilvusKB:`{label}` {{kb_id: $kb_id, name: 'unrelated_orphan'}}),
                       (f1)-[:MENTIONS {{kb_id: $kb_id, file_id: 'f1'}}]->(shared),
                       (f1)-[:MENTIONS {{kb_id: $kb_id, file_id: 'f1'}}]->(f1_only),
                       (f2)-[:MENTIONS {{kb_id: $kb_id, file_id: 'f2'}}]->(shared)
                """,
                kb_id=kb_id,
            ).consume()

        service._delete_file_graph_from_neo4j(kb_id, "f1")

        with connection.driver.session() as session:
            remaining_entities = set(
                session.run(f"MATCH (e:Entity:MilvusKB:`{label}`) RETURN e.name AS name").value("name")
            )
            remaining_files = set(
                session.run(f"MATCH (c:Chunk:MilvusKB:`{label}`) RETURN c.file_id AS file_id").value("file_id")
            )

        assert remaining_entities == {"shared", "unrelated_orphan"}
        assert remaining_files == {"f2"}

        service._delete_file_graph_from_neo4j(kb_id, "f2")

        with connection.driver.session() as session:
            remaining_entities = set(
                session.run(f"MATCH (e:Entity:MilvusKB:`{label}`) RETURN e.name AS name").value("name")
            )

        assert remaining_entities == {"unrelated_orphan"}
    finally:
        with connection.driver.session() as session:
            session.run(f"MATCH (n:MilvusKB:`{label}`) DETACH DELETE n").consume()


@pytest.mark.integration
def test_entity_redirect_projection_updates_real_neo4j():
    kb_id = f"pytest_redirect_graph_{uuid4().hex}"
    label = safe_neo4j_label(kb_id)
    connection = get_shared_neo4j_connection()
    service = MilvusGraphService(neo4j_connection=connection)

    try:
        with connection.driver.session() as session:
            session.run(
                f"""
                CREATE (source:Entity:MilvusKB:`{label}` {{
                    kb_id: $kb_id,
                    entity_id: 'entity_source',
                    name: '源实体'
                }}),
                (target:Entity:MilvusKB:`{label}` {{
                    kb_id: $kb_id,
                    entity_id: 'entity_target',
                    name: '目标实体'
                }})
                """,
                kb_id=kb_id,
            ).consume()

        service.project_projection_payload(
            {
                "event_type": "entity_redirect",
                "version": 1,
                "kb_id": kb_id,
                "source_entity_id": "entity_source",
                "target_entity_ids": ["entity_target"],
                "operation": "merge",
                "redirect_id": "redirect_1",
                "reason": "真实 Neo4j 投影验证",
            }
        )

        with connection.driver.session() as session:
            record = session.run(
                f"""
                MATCH (source:Entity:MilvusKB:`{label}` {{entity_id: 'entity_source'}})
                      -[redirect:ENTITY_REDIRECT]->
                      (target:Entity:MilvusKB:`{label}` {{entity_id: 'entity_target'}})
                RETURN source.lifecycle_status AS lifecycle_status,
                       source.superseded_by_entity_id AS superseded_by_entity_id,
                       redirect.operation AS operation,
                       redirect.reason AS reason,
                       redirect.governance_edge AS governance_edge
                """
            ).single()

        assert record is not None
        assert record["lifecycle_status"] == "redirected"
        assert record["superseded_by_entity_id"] == "entity_target"
        assert record["operation"] == "merge"
        assert record["reason"] == "真实 Neo4j 投影验证"
        assert record["governance_edge"] is True
    finally:
        with connection.driver.session() as session:
            session.run(f"MATCH (n:MilvusKB:`{label}`) DETACH DELETE n").consume()
