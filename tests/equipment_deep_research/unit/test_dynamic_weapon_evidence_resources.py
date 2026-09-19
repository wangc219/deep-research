from __future__ import annotations

from equipment_deep_research.agents.dynamic_prompt_resources import (
    load_dynamic_winning_json,
)
from equipment_deep_research.agents.workflows.coordinator import (
    _weapon_specialized_evidence_channels,
)


def test_weapon_specialized_evidence_channels_are_loaded_from_common_resource() -> None:
    resource = load_dynamic_winning_json(
        "common", section="weapon_specialized_evidence_channels"
    )

    assert isinstance(resource, list)
    assert len(resource) == 7
    assert all(
        {
            "channel_id",
            "name",
            "focus",
            "preferred_sources",
            "required_result",
        }
        <= set(item)
        for item in resource
        if isinstance(item, dict)
    )
    assert all(
        isinstance(item.get("source_anchors", []), list)
        for item in resource
        if isinstance(item, dict)
    )


def test_weapon_specialized_channels_keep_query_anchor_after_resource_load() -> None:
    rows = _weapon_specialized_evidence_channels("Query资源化回归")

    assert [row["channel_id"] for row in rows] == [
        "query_target_threat_combat_effect",
        "query_specific_weapon_architecture_baseline",
        "query_countermeasure_failure_boundary",
        "query_weapon_engineering_acquisition",
    ]
    assert all(row["query_anchor"] == "Query资源化回归" for row in rows)
