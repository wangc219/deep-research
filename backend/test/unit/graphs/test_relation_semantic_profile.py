from platform_core.knowledge.graphs.relation_semantic_profile import build_relation_semantic_profile


def test_relation_profile_aggregates_only_supplied_reviewed_cross_document_evidence():
    profile = build_relation_semantic_profile(
        relation_type="ENABLES_CAPABILITY",
        source_name="宽带射频收发器",
        source_label="Component",
        target_name="抗干扰能力",
        target_label="Capability",
        base_content="宽带射频收发器 → ENABLES_CAPABILITY → 抗干扰能力",
        relation_mentions=[
            {
                "file_id": "paper-a",
                "claim_level": "Fact",
                "review_status": "accepted",
                "evidence_quote": "频率捷变提高抗干扰能力。",
                "applicable_conditions": ["宽带工作模式"],
            },
            {
                "file_id": "paper-b",
                "claim_level": "Inference",
                "review_status": "pending",
                "evidence_quote": "多通道接收降低压制式干扰影响。",
                "applicable_conditions": ["宽带工作模式", "多通道接收"],
            },
            {
                "file_id": "paper-b",
                "claim_level": "Inference",
                "review_status": "pending",
                "evidence_quote": "频率捷变提高抗干扰能力。",
                "applicable_conditions": [],
            },
        ],
    )

    assert "源实体：宽带射频收发器 [Component]" in profile
    assert "目标实体：抗干扰能力 [Capability]" in profile
    assert "独立来源数：2" in profile
    assert "知识层级：Fact、Inference" in profile
    assert "证据状态：accepted、pending" in profile
    assert "适用条件：宽带工作模式；多通道接收" in profile
    assert profile.count("频率捷变提高抗干扰能力。") == 1
    assert "多通道接收降低压制式干扰影响。" in profile


def test_relation_profile_is_deterministically_bounded():
    profile = build_relation_semantic_profile(
        relation_type="USES_TECHNOLOGY",
        source_name="系统",
        source_label="ProductSystem",
        target_name="技术",
        target_label="KeyTechnology",
        relation_mentions=[
            {"file_id": f"paper-{index}", "claim_level": "Fact", "evidence_quote": "证据" * 20} for index in range(20)
        ],
        max_evidence=2,
        max_chars=120,
    )

    assert len(profile) <= 120
    assert profile.startswith("系统 [ProductSystem] → USES_TECHNOLOGY → 技术 [KeyTechnology]")


def test_relation_profile_keeps_pending_status_and_relation_rationale_without_separate_preview():
    profile = build_relation_semantic_profile(
        relation_type="ENABLES_CAPABILITY",
        source_name="分布式态势感知技术",
        source_label="KeyTechnology",
        target_name="持续感知能力",
        target_label="Capability",
        relation_mentions=[
            {
                "file_id": "paper-a",
                "claim_level": "Inference",
                "review_status": "pending",
                "evidence_quote": "分布式节点可保持连续态势更新。",
                "reasoning_basis": "原文明确连接分布式节点与连续态势更新",
                "applicable_conditions": ["节点通信可用"],
            }
        ],
    )

    assert "证据状态：pending" in profile
    assert "pending_preview" not in profile
    assert "关系依据：原文明确连接分布式节点与连续态势更新" in profile
    assert "跨文档证据" in profile
    assert "节点通信可用" in profile
