"""装备 Query/Run HTTP 边界保持知识范围三态。"""

import pytest
from pydantic import ValidationError

from server.routers.equipment_router import (
    EquipmentQueryCreate,
    EquipmentQueryGenerate,
    EquipmentRunCreate,
    EquipmentRunUpdate,
)


def test_run_update_distinguishes_omitted_null_and_empty_knowledge_ids() -> None:
    assert EquipmentRunUpdate().model_dump(exclude_unset=True) == {}
    assert EquipmentRunUpdate(knowledge_ids=None).model_dump(exclude_unset=True) == {
        "knowledge_ids": None
    }
    assert EquipmentRunUpdate(knowledge_ids=[]).model_dump(exclude_unset=True) == {
        "knowledge_ids": []
    }


def test_create_schemas_expose_canonical_knowledge_scope() -> None:
    run = EquipmentRunCreate(project_id="project-1", topic="topic")
    query = EquipmentQueryCreate(project_id="project-1", query="query")
    generation = EquipmentQueryGenerate(project_id="project-1", topic="topic")

    for body in (run, query, generation):
        assert body.knowledge_enabled is True
        assert body.knowledge_ids is None


def test_query_generation_accepts_all_twenty_divergence_dimensions() -> None:
    assert EquipmentQueryGenerate(project_id="project-1", topic="topic", count=20).count == 20
    with pytest.raises(ValidationError):
        EquipmentQueryGenerate(project_id="project-1", topic="topic", count=21)
