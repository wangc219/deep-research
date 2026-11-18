from platform_core.knowledge.graphs.entity_semantic_profile import build_entity_semantic_profile


def test_entity_semantic_profile_merges_aliases_and_directed_accepted_neighbors():
    content = build_entity_semantic_profile(
        entity_id="entity-1",
        name="宽带射频收发器",
        normalized_name="宽带射频收发器",
        label="Component",
        accepted_mentions=["宽带射频模块", "宽带射频模块"],
        trusted_aliases=["Wideband RF Transceiver", "宽带射频收发器"],
        accepted_relations=[
            {
                "source_entity_id": "entity-1",
                "target_entity_id": "capability-1",
                "relation_type": "ENABLES_CAPABILITY",
                "target_name": "抗干扰能力",
                "target_label": "Capability",
            },
            {
                "source_entity_id": "technology-1",
                "target_entity_id": "entity-1",
                "relation_type": "IMPLEMENTED_BY",
                "source_name": "频率捷变技术",
                "source_label": "KeyTechnology",
            },
        ],
    )

    assert content.startswith("宽带射频收发器\n实体类型：Component")
    assert "已审核别名：宽带射频模块、Wideband RF Transceiver" in content
    assert "ENABLES_CAPABILITY → 抗干扰能力 [Capability]" in content
    assert "频率捷变技术 [KeyTechnology] → IMPLEMENTED_BY" in content


def test_entity_semantic_profile_is_deterministic_bounded_and_ignores_unrelated_relations():
    content = build_entity_semantic_profile(
        entity_id="entity-1",
        name="实体",
        normalized_name="entity",
        label="Component",
        accepted_mentions=["别名乙", "别名甲"],
        accepted_relations=[
            {
                "source_entity_id": "other-1",
                "target_entity_id": "other-2",
                "relation_type": "RELATED_TO",
                "source_name": "无关甲",
                "target_name": "无关乙",
            }
        ],
        max_aliases=1,
        max_chars=48,
    )

    assert len(content) <= 48
    assert "别名乙" in content
    assert "别名甲" not in content
    assert "无关" not in content
