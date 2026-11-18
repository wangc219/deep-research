from __future__ import annotations

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from platform_core.knowledge.graphs.defense_ontology import ontology_payload
from platform_core.knowledge.graphs.ontology_versioning import (
    build_ontology_change_set,
    normalize_ontology_definition,
)
from platform_core.services.knowledge_graph_governance_service import KnowledgeGraphGovernanceService


def _extended_definition() -> dict:
    definition = deepcopy(ontology_payload())
    definition["version"] = "defense-kg-1.1"
    definition["name"] = "军事武器装备技术扩展本体"
    definition["entity_types"].append(
        {
            "code": "OperationalConcept",
            "name_zh": "作战概念",
            "description": "跨领域任务编组和运用概念",
        }
    )
    definition["entity_types"][1]["description"] = "经过工程验证或进入集成阶段的关键技术方案"
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
    return definition


def test_ontology_versioning_validates_extensions_and_builds_deterministic_change_set():
    previous = ontology_payload()
    current = normalize_ontology_definition(_extended_definition())

    changes = build_ontology_change_set(previous, current)

    assert [item["code"] for item in changes["entity_types"]["added"]] == ["OperationalConcept"]
    assert [item["code"] for item in changes["entity_types"]["modified"]] == ["KeyTechnology"]
    assert changes["entity_types"]["deprecated"] == []
    assert [item["code"] for item in changes["relation_types"]["added"]] == ["SUPPORTS_CONCEPT"]


def test_ontology_versioning_rejects_unknown_relation_endpoint_and_duplicate_codes():
    unknown_endpoint = _extended_definition()
    unknown_endpoint["relation_types"][-1]["tail_types"] = ["UnknownType"]
    with pytest.raises(ValueError, match="未知终点实体类型"):
        normalize_ontology_definition(unknown_endpoint)

    duplicate = _extended_definition()
    duplicate["entity_types"].append(deepcopy(duplicate["entity_types"][0]))
    with pytest.raises(ValueError, match="实体类型编码不能重复"):
        normalize_ontology_definition(duplicate)


@pytest.mark.asyncio
async def test_governance_service_registers_version_with_previous_snapshot_and_change_mapping():
    repository = AsyncMock()
    previous = ontology_payload()
    current = normalize_ontology_definition(_extended_definition())
    repository.get_ontology.return_value = previous
    repository.get_ontology_version.return_value = {
        "version": current["version"],
        "name": current["name"],
        "status": "active",
        "previous_version": previous["version"],
        "change_reason": "增加作战概念层",
        "created_by": "ontology-admin",
        "effective_at": "2026-10-30T12:00:00+00:00",
        "created_at": "2026-10-30T12:00:00+00:00",
        "definition": current,
    }
    service = KnowledgeGraphGovernanceService(repository=repository)

    result = await service.register_ontology_version(
        definition=_extended_definition(),
        previous_version=previous["version"],
        change_reason="增加作战概念层",
        created_by="ontology-admin",
    )

    repository.register_ontology.assert_awaited_once_with(
        current,
        created_by="ontology-admin",
        previous_version="defense-kg-1.0",
        change_reason="增加作战概念层",
    )
    assert result["change_set"]["entity_types"]["added"][0]["code"] == "OperationalConcept"


@pytest.mark.asyncio
async def test_governance_service_rejects_missing_previous_version():
    repository = AsyncMock()
    repository.get_ontology.return_value = None
    service = KnowledgeGraphGovernanceService(repository=repository)

    with pytest.raises(LookupError, match="前序本体版本不存在"):
        await service.register_ontology_version(
            definition=_extended_definition(),
            previous_version="missing-version",
            change_reason="测试缺失前序",
            created_by="ontology-admin",
        )
    repository.register_ontology.assert_not_awaited()
