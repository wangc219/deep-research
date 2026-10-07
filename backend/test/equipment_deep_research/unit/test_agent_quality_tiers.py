from equipment_deep_research.agents.provider import _phase_reasoning_effort


def test_quality_critical_codex_agents_keep_high_reasoning() -> None:
    for agent_id, phase in (
        ("winning_s1_opponent", "winning_s1_deep"),
        ("auditor", "audit_review"),
    ):
        assert _phase_reasoning_effort(agent_id, phase, "high") == "high"


def test_auxiliary_codex_phases_may_use_medium_reasoning() -> None:
    assert (
        _phase_reasoning_effort("orchestrator", "agent_selection", "high") == "medium"
    )
    assert _phase_reasoning_effort("convergence_fusion", "analysis", "high") == "medium"
    assert _phase_reasoning_effort("reporter", "report_generation", "high") == "high"
    assert _phase_reasoning_effort("reporter", "report_generation", "xhigh") == "xhigh"
    assert (
        _phase_reasoning_effort(
            "winning_step_critic",
            "winning_step_review",
            "high",
        )
        == "medium"
    )
    assert (
        _phase_reasoning_effort(
            "winning_round_critic",
            "winning_round_rereview",
            "high",
        )
        == "medium"
    )
    assert (
        _phase_reasoning_effort(
            "winning_dynamic_specialist",
            "winning_dynamic_specialist",
            "high",
        )
        == "medium"
    )


def test_winning_reasoning_is_layered_for_enterprise_latency(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_ENTERPRISE_LATENCY_PROFILE", "1")
    assert (
        _phase_reasoning_effort(
            "winning_s1_opponent",
            "winning_s1_opponent_light",
            "high",
        )
        == "low"
    )
    assert (
        _phase_reasoning_effort(
            "winning_s3_breakthrough",
            "winning_s3_breakthrough_deep",
            "high",
        )
        == "high"
    )
    assert (
        _phase_reasoning_effort(
            "winning_s4_capability",
            "winning_s4_capability_deep",
            "high",
        )
        == "medium"
    )
    assert (
        _phase_reasoning_effort(
            "winning_s6_image",
            "winning_s6_image_deep",
            "high",
        )
        == "medium"
    )
    assert (
        _phase_reasoning_effort(
            "winning_s6_image",
            "winning_s6_targeted_repair",
            "high",
        )
        == "high"
    )
    assert (
        _phase_reasoning_effort(
            "winning_s6_image",
            "winning_s6_card_repair",
            "high",
        )
        == "low"
    )
