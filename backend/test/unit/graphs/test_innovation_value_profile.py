from __future__ import annotations

from platform_core.knowledge.graphs.innovation_value_profile import build_innovation_value_profile


def _path() -> dict:
    return {
        "route_kind": "combined",
        "semantic_coverage": 0.8,
        "nodes": [
            {"semantic_role": "principle"},
            {"semantic_role": "technology"},
            {"semantic_role": "technology"},
            {"semantic_role": "capability"},
            {"semantic_role": "application"},
        ],
        "relations": [
            {"properties": {"confidence": 0.82}},
            {"properties": {"confidence": 0.76}},
            {"properties": {"confidence": 0.79}},
        ],
        "relation_ids": ["r1", "r2", "r3"],
        "evidence": {
            "mention_count": 3,
            "file_ids": ["file-1", "file-2"],
            "support_level": "multi_source",
        },
        "evidence_gaps": ["缺少系统级样机验证"],
        "research_inspiration": {
            "military_value_dimensions": ["体系协同", "抗干扰"],
            "expected_capability_gains": ["提升复杂电磁环境感知"],
            "application_directions": ["无人平台协同探测"],
            "applicable_conditions": ["低功耗", "通信受限"],
            "value_signals": [
                {"label": "新质技术", "text": "跨域融合的新机理"},
            ],
        },
    }


def test_profile_distinguishes_weak_signal_from_untraceable_guess():
    profile = build_innovation_value_profile(
        _path(),
        discovery_mode="bottom_up",
        relation_type="TRANSFERABLE_TO",
    )

    assert profile["mode"] == "bottom_up"
    assert profile["dimensions"]["military_value"] > 0.5
    assert profile["dimensions"]["novelty"] > 0.5
    assert profile["dimensions"]["evidence_strength"] > 0.35
    assert profile["signals"]["cross_document"] is True
    assert profile["advisory_only"] is True

    unsupported = _path()
    unsupported["evidence"] = {"mention_count": 0, "file_ids": []}
    unsupported["relations"] = []
    unsupported["evidence_gaps"] = ["无直接证据", "无独立来源", "无验证"]
    unsupported_profile = build_innovation_value_profile(
        unsupported,
        discovery_mode="bottom_up",
        relation_type="TRANSFERABLE_TO",
    )

    assert unsupported_profile["dimensions"]["evidence_strength"] < profile["dimensions"]["evidence_strength"]
    assert unsupported_profile["dimensions"]["weak_signal_potential"] < profile["dimensions"]["weak_signal_potential"]


def test_top_down_and_bottom_up_use_different_business_weights():
    top_down = build_innovation_value_profile(
        _path(),
        discovery_mode="top_down",
        relation_type="TRANSFERABLE_TO",
    )
    bottom_up = build_innovation_value_profile(
        _path(),
        discovery_mode="bottom_up",
        relation_type="TRANSFERABLE_TO",
    )

    assert top_down["weights"]["military_value"] > bottom_up["weights"]["military_value"]
    assert bottom_up["weights"]["novelty"] > top_down["weights"]["novelty"]
    assert sum(top_down["weights"].values()) == 1.0
    assert sum(bottom_up["weights"].values()) == 1.0
