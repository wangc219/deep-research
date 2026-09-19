"""API contracts for enterprise evolution scope and review governance."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from evals.replay import ReplayObservation, aggregate_replay, build_replay_manifest
from equipment_deep_research.api.app import create_app
from equipment_deep_research.application.run_service import ResearchApplicationService


def _client(tmp_path: Path, monkeypatch) -> tuple[TestClient, Path]:
    output_root = tmp_path / "outputs" / "runs"
    knowledge = output_root.parent / "knowledge"
    knowledge.mkdir(parents=True)
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    return TestClient(create_app(service=ResearchApplicationService())), output_root


def _write_feedback(output_root: Path, rows: list[dict]) -> None:
    path = output_root.parent / "knowledge" / "expert-review-feedback.json"
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def _write_proposals(output_root: Path, rows: list[dict]) -> None:
    path = output_root.parent / "knowledge" / "prompt-evolution.json"
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def _valid_replay_summary(tmp_path: Path, *, eval_id: str = "replay-1") -> dict:
    """Build the same immutable replay wire contract accepted in production."""

    fixture = tmp_path / f"{eval_id}.fixture.jsonl"
    rows = [
        {
            "query_id": f"Q-{index}",
            "query": f"fixed query {index}",
            "region": "test",
            "domain": "test",
            "difficulty": "medium",
            "split": "pilot",
            "target_stages": ["S1"],
            "residual_tags": ["evidence_boundary"],
            "target_metrics": ["quality"],
            "seed": "fixture-v1",
        }
        for index in (1, 2)
    ]
    fixture.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    observations = [
        ReplayObservation(
            eval_id=eval_id,
            query_id=f"Q-{index}",
            arm=arm,
            quality_score=quality,
            estimated_cost=1.0,
            duration_seconds=1.0,
        )
        for index in (1, 2)
        for arm, quality in (
            ("prompt_only", 0.60),
            ("memory_only", 0.61),
            ("both", 0.72),
        )
    ]
    summary = aggregate_replay(
        observations,
        fixture=fixture,
        eval_id=eval_id,
        expected_arms=("prompt_only", "memory_only", "both"),
        reference_arm="prompt_only",
        candidate_arm="both",
        bootstrap_samples=100,
        seed=7,
    )
    summary["manifest"] = build_replay_manifest(
        fixture_path=fixture,
        eval_id=eval_id,
        bundle_id="bundle-1",
        seed="fixture-v1",
        project_root=tmp_path,
    )
    return summary


def test_feedback_index_is_tenant_isolated_and_admin_cross_scope_is_explicit(
    tmp_path: Path, monkeypatch
) -> None:
    client, output_root = _client(tmp_path, monkeypatch)
    _write_feedback(
        output_root,
        [
            {"feedback_id": "a", "tenant_id": "tenant-a", "comment": "a"},
            {"feedback_id": "b", "tenant_id": "tenant-b", "comment": "b"},
            {"feedback_id": "global", "comment": "legacy global"},
        ],
    )

    tenant_a = client.get(
        "/api/v1/expert-feedback",
        headers={"X-Tenant-ID": "tenant-a"},
    )
    assert tenant_a.status_code == 200
    assert [item["feedback_id"] for item in tenant_a.json()["items"]] == ["a"]

    no_scope = client.get("/api/v1/expert-feedback")
    assert no_scope.status_code == 200
    assert [item["feedback_id"] for item in no_scope.json()["items"]] == ["global"]

    admin_default = client.get(
        "/api/v1/expert-feedback", headers={"X-Role": "admin"}
    )
    assert [item["feedback_id"] for item in admin_default.json()["items"]] == [
        "global"
    ]
    admin_all = client.get(
        "/api/v1/expert-feedback",
        headers={"X-Role": "admin", "X-Evolution-Cross-Scope": "true"},
    )
    assert [item["feedback_id"] for item in admin_all.json()["items"]] == [
        "a",
        "b",
        "global",
    ]


def test_feedback_effect_rejects_scope_mismatch(tmp_path: Path, monkeypatch) -> None:
    client, output_root = _client(tmp_path, monkeypatch)
    _write_feedback(
        output_root,
        [{"feedback_id": "f-1", "tenant_id": "tenant-a", "comment": "a"}],
    )
    response = client.post(
        "/api/v1/expert-feedback/f-1/effect",
        headers={"X-Tenant-ID": "tenant-b"},
        json={"effect_status": "validated", "evaluation_id": "eval-1"},
    )
    assert response.status_code == 403


def test_feedback_effect_requires_explicit_evaluator_and_evaluation_reference(
    tmp_path: Path, monkeypatch
) -> None:
    client, output_root = _client(tmp_path, monkeypatch)
    _write_feedback(
        output_root,
        [{"feedback_id": "f-evidence", "comment": "candidate", "effect_status": "pending_validation"}],
    )

    missing_evaluator = client.post(
        "/api/v1/expert-feedback/f-evidence/effect",
        json={"effect_status": "validated", "evaluation_id": "eval-1"},
    )
    assert missing_evaluator.status_code == 422
    assert "evaluator_id" in missing_evaluator.json()["detail"]

    missing_evaluation = client.post(
        "/api/v1/expert-feedback/f-evidence/effect",
        json={"effect_status": "validated", "evaluator_id": "reviewer-1"},
    )
    assert missing_evaluation.status_code == 422
    assert "evaluation_id" in missing_evaluation.json()["detail"]


def test_prompt_effect_api_blocks_tombstone_resurrection(
    tmp_path: Path, monkeypatch
) -> None:
    client, output_root = _client(tmp_path, monkeypatch)
    _write_proposals(
        output_root,
        [
            {
                "proposal_id": "p-tombstone",
                "status": "approved",
                "effect_status": "pending_validation",
                "scope": {},
            }
        ],
    )

    withdrawn = client.post(
        "/api/v1/prompt-evolution/proposals/p-tombstone/effect",
        json={
            "effect_status": "withdrawn",
            "evaluator_id": "reviewer-1",
            "evaluation_id": "review-1",
            "reason": "撤回测试",
        },
    )
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["proposal"]["effect_status"] == "withdrawn"

    resurrect = client.post(
        "/api/v1/prompt-evolution/proposals/p-tombstone/effect",
        json={
            "effect_status": "effective",
            "evaluator_id": "reviewer-2",
            "evaluation_id": "replay-2",
        },
    )
    assert resurrect.status_code == 422
    assert "immutable prompt" in resurrect.json()["detail"]


def test_prompt_review_scope_mismatch_is_checked_before_password(
    tmp_path: Path, monkeypatch
) -> None:
    client, output_root = _client(tmp_path, monkeypatch)
    _write_proposals(
        output_root,
        [
            {
                "proposal_id": "p-1",
                "status": "pending_review",
                "scope": {"tenant_id": "tenant-a"},
            }
        ],
    )
    response = client.post(
        "/api/v1/prompt-evolution/proposals/p-1/review",
        headers={"X-Tenant-ID": "tenant-b"},
        json={"decision": "approved", "review_password": "wrong"},
    )
    assert response.status_code == 403


def test_prompt_review_fails_closed_when_password_is_unconfigured(
    tmp_path: Path, monkeypatch
) -> None:
    client, output_root = _client(tmp_path, monkeypatch)
    monkeypatch.delenv("EQUIPMENT_DR_PROMPT_EVOLUTION_REVIEW_PASSWORD", raising=False)
    monkeypatch.delenv("EQUIPMENT_DR_ALLOW_DEFAULT_REVIEW_PASSWORD", raising=False)
    monkeypatch.delenv("EQUIPMENT_DR_ENV", raising=False)
    _write_proposals(
        output_root,
        [{"proposal_id": "p-1", "status": "pending_review", "scope": {}}],
    )
    response = client.post(
        "/api/v1/prompt-evolution/proposals/p-1/review",
        json={"decision": "rejected", "review_password": "anything"},
    )
    assert response.status_code == 503


def test_scoped_prompt_version_rollback_cannot_write_shared_bundle(
    tmp_path: Path, monkeypatch
) -> None:
    client, output_root = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("EQUIPMENT_DR_PROMPT_EVOLUTION_REVIEW_PASSWORD", "secret")
    _write_proposals(
        output_root,
        [
            {
                "proposal_id": "p-scoped",
                "status": "approved",
                "scope": {"tenant_id": "tenant-a"},
            },
            {
                "record_type": "version",
                "stage": "S1",
                "version": "v0001",
                "active": True,
                "source": "p-scoped",
                "file": "missing-snapshot.md",
            },
        ],
    )
    response = client.post(
        "/api/v1/prompt-evolution/versions/S1/v0001/rollback",
        headers={"X-Tenant-ID": "tenant-a"},
        json={"decision": "approved", "review_password": "secret"},
    )
    assert response.status_code == 403
    assert "scoped prompt version" in response.json()["detail"]


def test_prompt_review_passes_replay_first_flag_to_domain_service(
    tmp_path: Path, monkeypatch
) -> None:
    client, output_root = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("EQUIPMENT_DR_PROMPT_EVOLUTION_REVIEW_PASSWORD", "secret")
    _write_proposals(
        output_root,
        [{"proposal_id": "p-1", "status": "pending_review", "scope": {}}],
    )
    captured: dict[str, object] = {}

    def fake_review(**kwargs):
        captured.update(kwargs)
        return {"proposal_id": kwargs["proposal_id"], "status": "rejected"}

    monkeypatch.setattr("equipment_deep_research.api.app.review_proposal", fake_review)
    response = client.post(
        "/api/v1/prompt-evolution/proposals/p-1/review",
        json={"decision": "rejected", "review_password": "secret"},
    )
    assert response.status_code == 200
    assert captured["require_replay"] is True


def test_scoped_prompt_review_is_recorded_without_shared_publish_for_same_tenant(
    tmp_path: Path, monkeypatch
) -> None:
    client, output_root = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("EQUIPMENT_DR_PROMPT_EVOLUTION_REVIEW_PASSWORD", "secret")
    _write_proposals(
        output_root,
        [
            {
                "proposal_id": "p-1",
                "status": "pending_review",
                "scope": {"tenant_id": "tenant-a"},
                "replay_refs": [],
            }
        ],
    )

    replay = client.post(
        "/api/v1/prompt-evolution/proposals/p-1/replay",
        headers={"X-Tenant-ID": "tenant-a"},
        json={
            "evaluation_id": "replay-1",
            "replay_summary": _valid_replay_summary(tmp_path),
        },
    )
    assert replay.status_code == 200
    assert replay.json()["proposal"]["evaluation_status"] == "completed"

    captured: dict[str, object] = {}

    def fake_review(**kwargs):
        captured.update(kwargs)
        return {"proposal_id": kwargs["proposal_id"], "status": "approved"}

    monkeypatch.setattr("equipment_deep_research.api.app.review_proposal", fake_review)
    reviewed = client.post(
        "/api/v1/prompt-evolution/proposals/p-1/review",
        headers={"X-Tenant-ID": "tenant-a"},
        json={"decision": "approved", "review_password": "secret"},
    )
    assert reviewed.status_code == 200
    assert captured["require_replay"] is True
    assert captured["allow_scoped_publish"] is False

    # Promotion into the deployment-wide Prompt bundle is a separate,
    # explicit platform-admin operation.
    global_review = client.post(
        "/api/v1/prompt-evolution/proposals/p-1/review",
        headers={
            "X-Role": "admin",
            "X-Evolution-Cross-Scope": "true",
        },
        json={"decision": "approved", "review_password": "secret"},
    )
    assert global_review.status_code == 200
    assert captured["allow_scoped_publish"] is True


def test_attach_replay_then_domain_review_succeeds_without_touching_prompt(
    tmp_path: Path, monkeypatch
) -> None:
    client, output_root = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("EQUIPMENT_DR_PROMPT_EVOLUTION_REVIEW_PASSWORD", "secret")
    _write_proposals(
        output_root,
        [
            {
                "schema_version": "2.1",
                "proposal_id": "p-1",
                "status": "pending_review",
                "scope": {"tenant_id": "tenant-a"},
                "section_patches": [{"section_id": "S1:system"}],
                "stages": ["S1"],
                "impacted_stages": ["S1"],
                "static_checks": {
                    "schema": "pass",
                    "manifest": "pass",
                    "mutable_sections": "pass",
                    "protected_sections": "pass",
                    "compare_and_swap": "pass",
                },
                    "replay_refs": [],
                    "after_sources": {"S1": "candidate"},
                    "patch_only": True,
                    "parent_bundle_hash": "sha256:parent",
                }
        ],
    )
    replay = client.post(
        "/api/v1/prompt-evolution/proposals/p-1/replay",
        headers={"X-Tenant-ID": "tenant-a"},
        json={
            "evaluation_id": "replay-1",
            "replay_summary": _valid_replay_summary(tmp_path),
        },
    )
    assert replay.status_code == 200
    publish_calls: list[dict[str, object]] = []

    def fake_publish(*args, **kwargs):
        publish_calls.append(dict(kwargs))
        return [{"record_type": "version", "stage": "S1", "version": "v0001"}]

    monkeypatch.setattr(
        "equipment_deep_research.prompt_evolution._publish_sources_atomic",
        fake_publish,
    )
    reviewed = client.post(
        "/api/v1/prompt-evolution/proposals/p-1/review",
        headers={"X-Tenant-ID": "tenant-a"},
        json={"decision": "approved", "review_password": "secret"},
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["proposal"]["status"] == "approved"
    assert reviewed.json()["proposal"]["publish_status"] == "deferred_scoped"
    assert publish_calls == []

    promoted = client.post(
        "/api/v1/prompt-evolution/proposals/p-1/review",
        headers={
            "X-Role": "admin",
            "X-Evolution-Cross-Scope": "true",
        },
        json={"decision": "approved", "review_password": "secret"},
    )
    assert promoted.status_code == 200, promoted.text
    assert promoted.json()["proposal"]["publish_status"] == "published"
    assert len(publish_calls) == 1
