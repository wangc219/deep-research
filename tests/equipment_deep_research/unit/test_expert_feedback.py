import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from equipment_deep_research.expert_feedback import (
    _TRUSTED_FEEDBACK_STATUS_TOKEN,
    append_feedback,
    load_feedback_knowledge,
    normalize_feedback,
    process_feedback_memory,
    update_feedback_effect_status,
)


def test_memory_agent_routes_compact_signal_to_relevant_stages() -> None:
    result = process_feedback_memory(
        {
            "capability_name": "近程截击弹能力画像",
            "comment": "候选装备需要补充直接拦截机理和作战部署时序，避免把支援节点当成主装备。",
        }
    )

    assert result["memory_processor"] == "expert_feedback_memory"
    assert result["learning_status"] == "processed"
    assert len(result["target_agent_ids"]) <= 3
    assert {"S2", "S3"}.issubset(result["target_agent_ids"])
    assert result["learning_signal"].startswith("针对近程截击弹能力画像：")


def test_feedback_metadata_distinguishes_processed_from_effective() -> None:
    result = process_feedback_memory(
        {
            "capability_name": "测试卡",
            "comment": "需要补充证据边界和验证方法。",
            "target_agent_ids": ["s4", "S4", "unknown"],
            "effect_status": "not-a-status",
        }
    )

    assert result["learning_status"] == "processed"
    assert result["effect_status"] == "pending_validation"
    assert result["memory_status"] == "candidate"
    assert result["target_agent_ids"] == ["S4"]
    assert result["taxonomy"]
    assert result["raw_comment"] == "需要补充证据边界和验证方法。"
    assert result["derived"] is True


def test_untrusted_caller_cannot_inject_terminal_feedback_status(tmp_path: Path) -> None:
    """Ingestion must keep client-provided terminal states out of memory."""

    saved = append_feedback(
        run_root=tmp_path / "run",
        output_root=tmp_path / "outputs" / "runs",
        feedback={
            "feedback_id": "forged-effective",
            "run_id": "run-1",
            "capability_name": "测试卡",
            "comment": "尝试直接写入长期记忆。",
            "effect_status": "effective",
            "memory_status": "active",
        },
    )

    assert saved["effect_status"] == "pending_validation"
    assert saved["memory_status"] == "candidate"


def test_effect_status_promotion_requires_trusted_evaluator_capability(
    tmp_path: Path,
) -> None:
    saved = append_feedback(
        run_root=tmp_path / "run",
        output_root=tmp_path / "outputs" / "runs",
        feedback={
            "feedback_id": "promotion-guard",
            "run_id": "run-1",
            "capability_name": "测试卡",
            "comment": "等待回放评估。",
        },
    )

    import pytest

    with pytest.raises(PermissionError):
        update_feedback_effect_status(
            output_root=tmp_path / "outputs" / "runs",
            feedback_id=saved["feedback_id"],
            effect_status="validated",
        )


def test_normalize_feedback_sets_enterprise_scope_and_validation_defaults() -> None:
    result = normalize_feedback(
        run_id="run-1",
        capability_id="cap-1",
        capability_name="测试卡",
        comment="请明确候选身份和证据边界。",
        target_agent_ids=["s6"],
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        profile_id="legacy_v1",
    )

    assert result["tenant_id"] == "tenant-1"
    assert result["workspace_id"] == "workspace-1"
    assert result["profile_id"] == "legacy_v1"
    assert result["target_agent_ids"] == ["S6"]
    assert result["effect_status"] == "pending_validation"
    assert result["memory_status"] == "candidate"
    assert result["ttl_days"] == 90


def test_structured_s5_scores_preserve_model_expert_delta_and_route_to_s5() -> None:
    model_scores = {
        "innovation": 0.82,
        "demand": 0.91,
        "feasibility": 0.86,
        "effectiveness": 0.87,
        "development": 0.85,
    }
    expert_scores = {
        "innovation": 0.76,
        "demand": 0.94,
        "feasibility": 0.78,
        "effectiveness": 0.83,
        "development": 0.81,
    }

    normalized = normalize_feedback(
        run_id="run-s5",
        capability_id="hypothesis-1",
        hypothesis_id="hypothesis-1",
        capability_name="时敏断窗打击导弹",
        comment="科学可行性评价偏高，需要补充终端毁伤闭环约束。",
        model_dimension_scores=model_scores,
        expert_dimension_scores=expert_scores,
        stage_scope=["S5"],
    )
    processed = process_feedback_memory(normalized)

    assert normalized["score_schema"] == "s5_five_dimension_v1"
    assert normalized["model_weighted_score"] == 0.863
    assert normalized["expert_weighted_score"] == 0.83
    assert normalized["score_deltas"]["feasibility"] == -0.08
    assert normalized["rating"] == 4
    assert "S5" in processed["target_agent_ids"]
    assert processed["expert_dimension_scores"] == expert_scores


def test_structured_s5_scores_require_complete_expert_dimensions() -> None:
    import pytest

    with pytest.raises(ValueError, match="all five"):
        normalize_feedback(
            run_id="run-s5",
            capability_id="hypothesis-1",
            capability_name="测试卡",
            comment="评分样本不完整。",
            expert_dimension_scores={"innovation": 0.8},
        )


def test_unvalidated_feedback_is_not_retrieved_for_production_runs(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    output_root = tmp_path / "outputs" / "runs"
    append_feedback(
        run_root=run_root,
        output_root=output_root,
        feedback={
            "feedback_id": "pending-1",
            "run_id": "run-1",
            "capability_name": "测试卡",
            "comment": "需要补充证据边界。",
        },
    )

    assert load_feedback_knowledge(output_root, "测试卡") == []
    assert load_feedback_knowledge(
        output_root, "测试卡", include_unvalidated=True
    )[0]["effect_status"] == "pending_validation"


def test_validated_feedback_requires_matching_scope_and_respects_ttl(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    output_root = tmp_path / "outputs" / "runs"
    item = append_feedback(
        run_root=run_root,
        output_root=output_root,
        feedback={
            "feedback_id": "validated-1",
            "run_id": "run-1",
            "capability_name": "测试卡",
            "comment": "需要补充证据边界。",
            "effect_status": "validated",
            "memory_status": "active",
            "tenant_id": "tenant-1",
            "workspace_id": "workspace-1",
            "ttl_days": 1,
            "created_at": (
                datetime.now(timezone.utc) - timedelta(days=2)
            ).isoformat(),
        },
        _trusted_status_token=_TRUSTED_FEEDBACK_STATUS_TOKEN,
    )

    assert load_feedback_knowledge(
        output_root,
        "测试卡",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
    ) == []
    assert load_feedback_knowledge(
        output_root,
        "测试卡",
        tenant_id="other-tenant",
        workspace_id="workspace-1",
    ) == []
    assert item["effect_status"] == "validated"


def test_validated_feedback_stage_scope_is_an_overlap_boundary(tmp_path: Path) -> None:
    output_root = tmp_path / "outputs" / "runs"
    append_feedback(
        run_root=output_root / "run-s4",
        output_root=output_root,
        feedback={
            "feedback_id": "stage-s4",
            "run_id": "run-s4",
            "capability_name": "测试卡",
            "comment": "需要补充能力指标和验证边界。",
            "effect_status": "validated",
            "memory_status": "active",
            "tenant_id": "tenant-1",
            "workspace_id": "workspace-1",
            "stage_scope": ["S4"],
        },
        _trusted_status_token=_TRUSTED_FEEDBACK_STATUS_TOKEN,
    )
    append_feedback(
        run_root=output_root / "run-s6",
        output_root=output_root,
        feedback={
            "feedback_id": "stage-s6",
            "run_id": "run-s6",
            "capability_name": "测试卡",
            "comment": "需要补充画像表达和证据边界。",
            "effect_status": "validated",
            "memory_status": "active",
            "tenant_id": "tenant-1",
            "workspace_id": "workspace-1",
            "stage_scope": ["S6"],
        },
        _trusted_status_token=_TRUSTED_FEEDBACK_STATUS_TOKEN,
    )

    scoped = load_feedback_knowledge(
        output_root,
        "测试卡",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        stage_scope=["S6"],
    )
    assert [item["feedback_id"] for item in scoped] == ["stage-s6"]
    # A scoped production query must not wildcard over records with a
    # different tenant/workspace or over legacy records lacking scope.
    assert load_feedback_knowledge(output_root, "测试卡", stage_scope=["S6"]) == []


def test_effect_status_update_is_explicit_and_updates_audit_copy(tmp_path: Path) -> None:
    output_root = tmp_path / "outputs" / "runs"
    run_root = output_root / "run-1"
    saved = append_feedback(
        run_root=run_root,
        output_root=output_root,
        feedback={
            "feedback_id": "effect-1",
            "run_id": "run-1",
            "capability_name": "测试卡",
            "comment": "需要补充验证边界。",
        },
    )

    updated = update_feedback_effect_status(
        output_root=output_root,
        feedback_id=saved["feedback_id"],
        effect_status="effective",
        evaluator_id="eval-service",
        evaluation_id="evaluation-1",
        reason="paired replay passed",
        utility_delta=0.4,
        _trusted_status_token=_TRUSTED_FEEDBACK_STATUS_TOKEN,
    )

    assert updated["effect_status"] == "effective"
    assert updated["memory_status"] == "active"
    assert updated["effect_evaluation_id"] == "evaluation-1"
    assert updated["utility_ema"] == 0.08
    local = json.loads((run_root / "expert_feedback.json").read_text(encoding="utf-8"))
    assert local[0]["effect_status"] == "effective"
    assert load_feedback_knowledge(output_root, "测试卡")[0]["feedback_id"] == saved["feedback_id"]


def test_effect_status_requires_named_evaluator_and_evaluation_reference(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "outputs" / "runs"
    saved = append_feedback(
        run_root=output_root / "run-1",
        output_root=output_root,
        feedback={
            "feedback_id": "evidence-required",
            "run_id": "run-1",
            "capability_name": "测试卡",
            "comment": "等待可追溯回放评估。",
        },
    )

    import pytest

    with pytest.raises(ValueError, match="evaluator_id"):
        update_feedback_effect_status(
            output_root=output_root,
            feedback_id=saved["feedback_id"],
            effect_status="validated",
            evaluation_id="replay-1",
            _trusted_status_token=_TRUSTED_FEEDBACK_STATUS_TOKEN,
        )
    with pytest.raises(ValueError, match="evaluation_id"):
        update_feedback_effect_status(
            output_root=output_root,
            feedback_id=saved["feedback_id"],
            effect_status="validated",
            evaluator_id="evaluator-1",
            _trusted_status_token=_TRUSTED_FEEDBACK_STATUS_TOKEN,
        )
    assert load_feedback_knowledge(
        output_root, "测试卡", include_unvalidated=True
    )[0]["effect_status"] == "pending_validation"


def test_feedback_tombstone_cannot_be_resurrected_and_same_evidence_is_idempotent(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "outputs" / "runs"
    saved = append_feedback(
        run_root=output_root / "run-1",
        output_root=output_root,
        feedback={
            "feedback_id": "tombstone-1",
            "run_id": "run-1",
            "capability_name": "测试卡",
            "comment": "撤回后不得复活。",
        },
    )

    import pytest

    retired = update_feedback_effect_status(
        output_root=output_root,
        feedback_id=saved["feedback_id"],
        effect_status="withdrawn",
        evaluator_id="evaluator-1",
        evaluation_id="review-1",
        reason="撤回测试",
        _trusted_status_token=_TRUSTED_FEEDBACK_STATUS_TOKEN,
    )
    assert retired["memory_status"] == "retired"
    history_count = len(retired["effect_history"])

    retry = update_feedback_effect_status(
        output_root=output_root,
        feedback_id=saved["feedback_id"],
        effect_status="withdrawn",
        evaluator_id="evaluator-1",
        evaluation_id="review-1",
        reason="重复投递",
        _trusted_status_token=_TRUSTED_FEEDBACK_STATUS_TOKEN,
    )
    assert len(retry["effect_history"]) == history_count
    assert retry["effect_reason"] == retired["effect_reason"]

    with pytest.raises(ValueError, match="immutable feedback"):
        update_feedback_effect_status(
            output_root=output_root,
            feedback_id=saved["feedback_id"],
            effect_status="effective",
            evaluator_id="evaluator-2",
            evaluation_id="replay-2",
            _trusted_status_token=_TRUSTED_FEEDBACK_STATUS_TOKEN,
        )


def test_duplicate_feedback_stays_in_audit_but_not_global_memory(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    output_root = tmp_path / "outputs" / "runs"
    first = append_feedback(
        run_root=run_root,
        output_root=output_root,
        feedback={
            "feedback_id": "feedback-1",
            "run_id": "run-1",
            "capability_name": "测试卡",
            "comment": "需要补充验证边界。",
        },
    )
    second = append_feedback(
        run_root=run_root,
        output_root=output_root,
        feedback={
            "feedback_id": "feedback-2",
            "run_id": "run-1",
            "capability_name": "测试卡",
            "comment": "需要补充验证边界。",
        },
    )

    assert first["dedupe_status"] == "canonical"
    assert second["learning_status"] == "deduplicated"
    assert second["duplicate_of"] == "feedback-1"
    audit_rows = json.loads(
        (run_root / "expert_feedback.json").read_text(encoding="utf-8")
    )
    memory_rows = json.loads(
        (tmp_path / "outputs" / "knowledge" / "expert-review-feedback.json").read_text(
            encoding="utf-8"
        )
    )
    assert len(audit_rows) == 2
    assert len(memory_rows) == 1
