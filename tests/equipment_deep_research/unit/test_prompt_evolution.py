from pathlib import Path
import json
import asyncio

import pytest

from evals.replay import ReplayObservation, aggregate_replay, build_replay_manifest

from equipment_deep_research.prompt_evolution import (
    create_proposal,
    create_section_patch_proposal,
    list_proposals,
    list_versions,
    propose_with_codex,
    review_proposal,
    rollback_version,
    update_proposal_effect_status,
    validate_section_manifest,
    validate_proposal_for_review,
)
from equipment_deep_research.providers.base import ProviderFinalTurn, ProviderStreamEvent


def test_section_manifest_preflight_is_valid() -> None:
    result = validate_section_manifest()
    assert result["ok"] is True
    assert result["errors"] == []


def test_codex_proposal_prefers_section_patches_without_touching_live_prompt(
    tmp_path: Path,
) -> None:
    prompt_path = (
        Path(__file__).parents[3]
        / "src/equipment_deep_research/agents/prompts/dynamic_winning/S3.md"
    )
    before = prompt_path.read_bytes()

    class SectionPatchProvider:
        async def stream(self, messages, tools, options):
            payload = {
                "section_patches": [
                    {
                        "section_id": "S3:creative",
                        "new_text": (
                            "加强候选本体独立性检查，并要求每个创意绑定可验证的直接效果。"
                        ),
                        "rationale": "减少重复候选并提高证据可核验性",
                        "counterexamples": ["不要把支援节点包装成主装备"],
                        "acceptance_tests": ["每个候选都能说明直接效果和验证方法"],
                    }
                ],
                "hypothesis": "显式独立性检查可降低重复候选率",
            }
            yield ProviderStreamEvent.final(
                ProviderFinalTurn(text=json.dumps(payload, ensure_ascii=False))
            )

    proposal = asyncio.run(
        propose_with_codex(
            project_root=tmp_path,
            output_root=tmp_path / "outputs" / "runs",
            feedback={"comment": "S3候选独立性不足"},
            stages=["S3"],
            provider=SectionPatchProvider(),
        )
    )

    assert proposal["patch_only"] is True
    assert proposal["legacy_compatibility"] is False
    assert proposal["section_patches"][0]["section_id"] == "S3:creative"
    assert proposal["status"] == "pending_review"
    assert prompt_path.read_bytes() == before
from equipment_deep_research.agents.dynamic_prompt_resources import load_dynamic_winning_prompt
from equipment_deep_research.agents.dynamic_prompt_resources import invalidate_dynamic_winning_prompt_cache


def test_s6_runtime_prompt_is_the_exact_reviewable_markdown_resource() -> None:
    prompt_path = (
        Path(__file__).parents[3]
        / "src/equipment_deep_research/agents/prompts/dynamic_winning/S6.md"
    )
    source = prompt_path.read_text(encoding="utf-8")
    expected = source.split("<!-- prompt: system -->\n", 1)[1].split(
        "\n<!-- /prompt -->", 1
    )[0]

    assert load_dynamic_winning_prompt("S6") == expected


def test_proposal_is_pending_and_approval_updates_only_selected_prompt(tmp_path: Path) -> None:
    prompt_dir = Path(__file__).parents[3] / "src/equipment_deep_research/agents/prompts/dynamic_winning"
    original_s3 = (prompt_dir / "S3.md").read_text(encoding="utf-8")
    original_s6 = (prompt_dir / "S6.md").read_text(encoding="utf-8")
    try:
        row = create_proposal(
            output_root=tmp_path / "outputs" / "runs",
            feedback={"comment": "S3候选独立性不足"},
            stages=["S3"],
            proposed_prompts={"S3": "这是一个经过审查的 S3 提示词候选，要求保留严格 JSON 输出契约并加强独立武器本体判断。" * 4},
        )
        assert row["status"] == "pending_review"
        assert row["effect_status"] == "pending_validation"
        assert row["section_patches"][0]["section_id"] == "S3:system"
        assert row["section_patches"][0]["old_hash"].startswith("sha256:")
        assert row["section_patches"][0]["new_hash"].startswith("sha256:")
        assert (prompt_dir / "S3.md").read_text(encoding="utf-8") == original_s3
        approved = review_proposal(
            output_root=tmp_path / "outputs" / "runs",
            proposal_id=row["proposal_id"],
            decision="approved",
            reviewer="developer",
        )
        assert approved["status"] == "approved"
        assert "经过审查的 S3 提示词候选" in (prompt_dir / "S3.md").read_text(encoding="utf-8")
        assert "经过审查的 S3 提示词候选" in load_dynamic_winning_prompt("S3")
        ledger = tmp_path / "outputs" / "knowledge" / "prompt-evolution.json"
        assert ledger.is_file()
        ledger_text = ledger.read_text(encoding="utf-8")
        assert "src/equipment_deep_research/agents/prompts/dynamic_winning/versions" in ledger_text
        versions = list_versions(tmp_path / "outputs" / "runs", "S3")
        assert versions and versions[-1]["record_type"] == "version"
        assert versions[-1]["file"].startswith("src/")
        assert versions[-1]["source_proposal_id"] == row["proposal_id"]
        assert not any(
            str(versions[-1]["scope"].get(key, ""))
            for key in ("tenant_id", "workspace_id", "project_id", "profile_id", "route")
        )
        assert versions[-1]["scope"].get("stage_scope") == []
        assert (prompt_dir / "S6.md").read_text(encoding="utf-8") == original_s6
        assert list_proposals(tmp_path / "outputs" / "runs", status="approved")
    finally:
        (prompt_dir / "S3.md").write_text(original_s3, encoding="utf-8")
        (prompt_dir / "S6.md").write_text(original_s6, encoding="utf-8")
        invalidate_dynamic_winning_prompt_cache()
        for path in (prompt_dir / "versions" / "S3").glob("v*.md"):
            path.unlink()
        try:
            (prompt_dir / "versions" / "S3").rmdir()
            (prompt_dir / "versions").rmdir()
        except OSError:
            pass


def test_scoped_proposal_review_defers_shared_publish_until_admin_cross_scope(
    tmp_path: Path, monkeypatch
) -> None:
    prompt_dir = Path(__file__).parents[3] / "src/equipment_deep_research/agents/prompts/dynamic_winning"
    prompt_path = prompt_dir / "S3.md"
    original = prompt_path.read_text(encoding="utf-8")
    versions_dir = prompt_dir / "versions" / "S3"
    original_versions = {path.name: path.read_bytes() for path in versions_dir.glob("v*.md")}
    try:
        row = create_proposal(
            output_root=tmp_path / "outputs" / "runs",
            feedback={"comment": "tenant-local refinement"},
            stages=["S3"],
            proposed_prompts={
                "S3": "租户范围内的候选提示词，保留严格输出契约并强化证据边界。" * 8
            },
            tenant_id="tenant-a",
            workspace_id="workspace-a",
            profile_id="profile-a",
            stage_scope=["S3"],
        )
        deferred = review_proposal(
            output_root=tmp_path / "outputs" / "runs",
            proposal_id=row["proposal_id"],
            decision="approved",
            reviewer="developer",
        )
        assert deferred["status"] == "approved"
        assert deferred["publish_status"] == "deferred_scoped"
        assert prompt_path.read_text(encoding="utf-8") == original
        published_calls: list[dict[str, object]] = []

        def fake_publish(*args, **kwargs):
            published_calls.append(dict(kwargs))
            return [{"record_type": "version", "stage": "S3", "version": "v9999"}]

        monkeypatch.setattr(
            "equipment_deep_research.prompt_evolution._publish_version",
            fake_publish,
        )
        promoted = review_proposal(
            output_root=tmp_path / "outputs" / "runs",
            proposal_id=row["proposal_id"],
            decision="approved",
            reviewer="admin",
            allow_scoped_publish=True,
        )
        assert promoted["publish_status"] == "published"
        assert len(published_calls) == 1
        assert published_calls[0]["source_proposal_id"] == row["proposal_id"]
        assert published_calls[0]["scope"]["tenant_id"] == "tenant-a"
    finally:
        prompt_path.write_text(original, encoding="utf-8")
        versions_dir.mkdir(parents=True, exist_ok=True)
        for path in versions_dir.glob("v*.md"):
            if path.name not in original_versions:
                path.unlink()
        for name, content in original_versions.items():
            (versions_dir / name).write_bytes(content)
        invalidate_dynamic_winning_prompt_cache()


def test_short_or_unknown_prompt_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        create_proposal(
            output_root=tmp_path / "outputs" / "runs",
            feedback={"comment": "x"},
            stages=["S3"],
            proposed_prompts={"S3": "too short"},
        )


def test_rollback_preserves_scope_and_source_proposal_id_and_requires_admin(
    tmp_path: Path, monkeypatch
) -> None:
    output_root = tmp_path / "outputs" / "runs"
    prompt_dir = Path(__file__).parents[3] / "src/equipment_deep_research/agents/prompts/dynamic_winning"
    prompt_path = prompt_dir / "S3.md"
    original = prompt_path.read_text(encoding="utf-8")
    versions_dir = prompt_dir / "versions" / "S3"
    original_versions = {
        path.name: path.read_bytes() for path in versions_dir.glob("v*.md")
    }
    try:
        row = create_proposal(
            output_root=output_root,
            feedback={"comment": "tenant-local rollback test"},
            stages=["S3"],
            proposed_prompts={"S3": "租户范围内的候选提示词，保留严格输出契约并强化证据边界。" * 8},
            tenant_id="tenant-a",
            workspace_id="workspace-a",
        )
        approved = review_proposal(
            output_root=output_root,
            proposal_id=row["proposal_id"],
            decision="approved",
            reviewer="admin",
            allow_scoped_publish=True,
        )
        version = list_versions(output_root, "S3")[-1]
        assert version["source_proposal_id"] == row["proposal_id"]
        assert version["scope"]["tenant_id"] == "tenant-a"
        with pytest.raises(ValueError, match="global admin"):
            rollback_version(
                output_root=output_root,
                stage="S3",
                version=version["version"],
                reviewer="developer",
            )

        calls: list[dict[str, object]] = []

        def fake_publish(*args, **kwargs):
            calls.append(dict(kwargs))
            return [{
                "record_type": "version",
                "stage": "S3",
                "version": "v9999",
                "source_proposal_id": kwargs.get("source_proposal_id"),
                "scope": kwargs.get("scope"),
                "rollback_from": kwargs.get("rollback_from"),
            }]

        def fake_publish_version(*args, **kwargs):
            calls.append(dict(kwargs))
            return {
                "record_type": "version",
                "stage": "S3",
                "version": "v9999",
                "source_proposal_id": kwargs.get("source_proposal_id"),
                "scope": kwargs.get("scope"),
                "rollback_from": kwargs.get("rollback_from"),
            }

        monkeypatch.setattr("equipment_deep_research.prompt_evolution._publish_version", fake_publish_version)
        rolled = rollback_version(
            output_root=output_root,
            stage="S3",
            version=version["version"],
            reviewer="admin",
            allow_scoped_publish=True,
        )
        assert rolled["source_proposal_id"] == row["proposal_id"]
        assert rolled["scope"]["tenant_id"] == "tenant-a"
        assert rolled["rollback_from"] == version["version"]
        assert calls[0]["source_proposal_id"] == row["proposal_id"]
        assert calls[0]["scope"]["workspace_id"] == "workspace-a"
    finally:
        prompt_path.write_text(original, encoding="utf-8")
        invalidate_dynamic_winning_prompt_cache()
        versions_dir.mkdir(parents=True, exist_ok=True)
        for path in versions_dir.glob("v*.md"):
            if path.name not in original_versions:
                path.unlink()
        for name, content in original_versions.items():
            (versions_dir / name).write_bytes(content)
        try:
            if not original_versions:
                versions_dir.rmdir()
                (prompt_dir / "versions").rmdir()
        except OSError:
            pass


def test_proposal_effect_requires_approval_and_records_replay_evidence(tmp_path: Path) -> None:
    output_root = tmp_path / "outputs" / "runs"
    prompt_dir = Path(__file__).parents[3] / "src/equipment_deep_research/agents/prompts/dynamic_winning"
    s6_path = prompt_dir / "S6.md"
    original_s6 = s6_path.read_text(encoding="utf-8")
    s6_versions_dir = prompt_dir / "versions" / "S6"
    original_s6_versions = {
        path.name: path.read_bytes()
        for path in s6_versions_dir.glob("v*.md")
    }
    prompt = "这是一个经过审查的提示词候选，要求保留严格 JSON 输出契约并加强证据边界与阶段职责。" * 4
    try:
        pending = create_proposal(
            output_root=output_root,
            feedback={"comment": "证据边界不足"},
            stages=["S6"],
            proposed_prompts={"S6": prompt},
        )
        with pytest.raises(ValueError, match="approved"):
            update_proposal_effect_status(
                output_root=output_root,
                proposal_id=pending["proposal_id"],
                effect_status="effective",
            )
        approved = review_proposal(
            output_root=output_root,
            proposal_id=pending["proposal_id"],
            decision="approved",
            reviewer="developer",
        )
        updated = update_proposal_effect_status(
            output_root=output_root,
            proposal_id=approved["proposal_id"],
            effect_status="effective",
            evaluator_id="eval-bot",
            evaluation_id="replay-001",
            reason="paired replay improved evidence-boundary score",
            metrics={"quality": 0.92, "cost_delta": -0.08},
        )
        assert updated["effect_status"] == "effective"
        assert updated["evaluation_status"] == "completed"
        assert updated["evaluation_metrics"]["quality"] == 0.92
        assert list_proposals(output_root, status="approved")[0]["effect_status"] == "effective"
    finally:
        s6_path.write_text(original_s6, encoding="utf-8")
        s6_versions_dir.mkdir(parents=True, exist_ok=True)
        for path in s6_versions_dir.glob("v*.md"):
            if path.name not in original_s6_versions:
                path.unlink()
        for name, content in original_s6_versions.items():
            (s6_versions_dir / name).write_bytes(content)
        invalidate_dynamic_winning_prompt_cache()


def test_proposal_effect_requires_explicit_evaluator_and_evaluation_id(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "outputs" / "runs"
    row = {
        "proposal_id": "evidence-required",
        "status": "approved",
        "effect_status": "pending_validation",
    }
    (output_root.parent / "knowledge").mkdir(parents=True)
    (output_root.parent / "knowledge" / "prompt-evolution.json").write_text(
        json.dumps([row], ensure_ascii=False), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="evaluator_id"):
        update_proposal_effect_status(
            output_root=output_root,
            proposal_id=row["proposal_id"],
            effect_status="validated",
            evaluation_id="replay-1",
        )
    with pytest.raises(ValueError, match="evaluation_id"):
        update_proposal_effect_status(
            output_root=output_root,
            proposal_id=row["proposal_id"],
            effect_status="validated",
            evaluator_id="evaluator-1",
        )


def test_proposal_effect_tombstone_cannot_be_resurrected(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "outputs" / "runs"
    row = {
        "proposal_id": "tombstone-proposal",
        "status": "approved",
        "effect_status": "pending_validation",
    }
    (output_root.parent / "knowledge").mkdir(parents=True)
    (output_root.parent / "knowledge" / "prompt-evolution.json").write_text(
        json.dumps([row], ensure_ascii=False), encoding="utf-8"
    )

    withdrawn = update_proposal_effect_status(
        output_root=output_root,
        proposal_id=row["proposal_id"],
        effect_status="withdrawn",
        evaluator_id="evaluator-1",
        evaluation_id="review-1",
        reason="撤回测试",
    )
    assert withdrawn["effect_status"] == "withdrawn"
    history_count = len(withdrawn["effect_history"])

    with pytest.raises(ValueError, match="immutable prompt"):
        update_proposal_effect_status(
            output_root=output_root,
            proposal_id=row["proposal_id"],
            effect_status="effective",
            evaluator_id="evaluator-2",
            evaluation_id="replay-2",
        )

    retry = update_proposal_effect_status(
        output_root=output_root,
        proposal_id=row["proposal_id"],
        effect_status="withdrawn",
        evaluator_id="evaluator-1",
        evaluation_id="review-1",
        reason="重复投递",
    )
    assert len(retry["effect_history"]) == history_count
    assert retry["effect_reason"] == withdrawn["effect_reason"]


def _valid_replay_summary(tmp_path: Path, *, eval_id: str = "replay-001") -> dict:
    fixture = tmp_path / "fixture.jsonl"
    fixture.write_text(
        "".join(
            json.dumps(
                {
                    "query_id": f"Q-{index}",
                    "query": f"query {index}",
                    "region": "r",
                    "domain": "d",
                    "difficulty": "medium",
                    "split": "pilot",
                    "target_stages": ["S3"],
                    "residual_tags": ["evidence_boundary"],
                    "target_metrics": ["evidence_and_factuality"],
                    "seed": "fixture-v1",
                },
                ensure_ascii=False,
            )
            + "\n"
            for index in (1, 2)
        ),
        encoding="utf-8",
    )
    observations = [
        ReplayObservation(
            eval_id=eval_id,
            query_id=f"Q-{index}",
            arm=arm,
            quality_score=quality,
            estimated_cost=1.0,
            duration_seconds=10.0,
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


def test_attach_replay_evidence_requires_fixture_hash_and_complete_pairs(tmp_path: Path) -> None:
    output_root = tmp_path / "outputs" / "runs"
    pending = create_proposal(
        output_root=output_root,
        feedback={"comment": "evidence boundary"},
        stages=["S3"],
        proposed_prompts={"S3": "经过审查的候选提示词，保留严格输出契约并强化证据边界。" * 8},
    )
    summary = _valid_replay_summary(tmp_path)

    from equipment_deep_research.prompt_evolution import attach_replay_evidence

    attached = attach_replay_evidence(
        output_root=output_root,
        proposal_id=pending["proposal_id"],
        evaluation_id="replay-001",
        replay_summary=summary,
        artifact_path=tmp_path / "summary.json",
    )
    assert attached["evaluation_status"] == "completed"
    assert attached["replay_gate"]["verdict"] == "pass"

    pending_bad_hash = create_proposal(
        output_root=output_root,
        feedback={"comment": "bad hash"},
        stages=["S3"],
        proposed_prompts={"S3": "另一个经过审查的候选提示词，保留严格输出契约并强化证据边界。" * 8},
    )
    bad_hash = json.loads(json.dumps(summary))
    bad_hash["fixture"]["fixture_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="fixture hash"):
        attach_replay_evidence(
            output_root=output_root,
            proposal_id=pending_bad_hash["proposal_id"],
            evaluation_id="replay-001",
            replay_summary=bad_hash,
        )

    pending_incomplete = create_proposal(
        output_root=output_root,
        feedback={"comment": "incomplete pairs"},
        stages=["S3"],
        proposed_prompts={"S3": "第三个经过审查的候选提示词，保留严格输出契约并强化证据边界。" * 8},
    )
    incomplete = json.loads(json.dumps(summary))
    incomplete["complete_case_count"] = 1
    with pytest.raises(ValueError, match="complete_case_count"):
        attach_replay_evidence(
            output_root=output_root,
            proposal_id=pending_incomplete["proposal_id"],
            evaluation_id="replay-001",
            replay_summary=incomplete,
        )


def test_attach_replay_evidence_rejects_manifest_missing_required_arm(tmp_path: Path) -> None:
    output_root = tmp_path / "outputs" / "runs"
    pending = create_proposal(
        output_root=output_root,
        feedback={"comment": "manifest arm coverage"},
        stages=["S3"],
        proposed_prompts={
            "S3": "候选提示词保留严格输出契约并强化证据边界，要求每一项判断都可回放验证。" * 8
        },
    )
    from equipment_deep_research.prompt_evolution import attach_replay_evidence

    summary = _valid_replay_summary(tmp_path, eval_id="manifest-arms")
    summary["manifest"] = dict(summary["manifest"])
    summary["manifest"]["arms"] = ["prompt_only", "both"]
    with pytest.raises(ValueError, match="manifest arms"):
        attach_replay_evidence(
            output_root=output_root,
            proposal_id=pending["proposal_id"],
            evaluation_id="manifest-arms",
            replay_summary=summary,
        )


def test_replay_gate_requires_canonical_pass_verdict_and_evidence(tmp_path: Path) -> None:
    output_root = tmp_path / "outputs" / "runs"
    pending = create_proposal(
        output_root=output_root,
        feedback={"comment": "strict gate"},
        stages=["S3"],
        proposed_prompts={"S3": "严格输出 JSON，强化证据边界并保持阶段职责不变。" * 8},
    )
    from equipment_deep_research.prompt_evolution import attach_replay_evidence

    summary = _valid_replay_summary(tmp_path, eval_id="strict-replay")
    attached = attach_replay_evidence(
        output_root=output_root,
        proposal_id=pending["proposal_id"],
        evaluation_id="strict-replay",
        replay_summary=summary,
    )
    assert validate_proposal_for_review(attached, require_replay=False)["replay_gate_passed"] is True

    not_ok = dict(attached)
    not_ok["replay_gate"] = {"passed": True, "verdict": "ok"}
    assert validate_proposal_for_review(not_ok, require_replay=False)["replay_gate_passed"] is False

    missing_evidence = dict(attached)
    missing_evidence.pop("replay_summary", None)
    assert validate_proposal_for_review(missing_evidence, require_replay=False)["replay_gate_passed"] is False

    string_pass = json.loads(json.dumps(attached))
    string_pass["replay_gate"]["passed"] = "true"
    string_pass["replay_summary"]["gate"]["passed"] = "true"
    assert validate_proposal_for_review(string_pass, require_replay=False)["replay_gate_passed"] is False


def test_section_patch_replay_binds_parent_bundle_and_candidate_hashes(tmp_path: Path) -> None:
    """A passing replay must prove it exercised this exact patch candidate."""

    output_root = tmp_path / "outputs" / "runs"
    pending = create_section_patch_proposal(
        output_root=output_root,
        feedback={"comment": "strict provenance"},
        stages=["S3"],
        section_patches=[
            {
                "section_id": "S3:creative",
                "new_text": "增加候选独立性与可验证效果检查，保持既有输出契约不变。",
            }
        ],
    )
    summary = _valid_replay_summary(tmp_path, eval_id="strict-provenance")
    manifest = dict(summary["manifest"])
    manifest["parent_bundle_hash"] = pending["parent_bundle_hash"]
    manifest["candidate_prompt_hashes"] = dict(pending["candidate_prompt_hashes"])
    summary["manifest"] = manifest

    from equipment_deep_research.prompt_evolution import attach_replay_evidence

    attached = attach_replay_evidence(
        output_root=output_root,
        proposal_id=pending["proposal_id"],
        evaluation_id="strict-provenance",
        replay_summary=summary,
    )
    assert attached["evaluation_status"] == "completed"
    assert validate_proposal_for_review(attached, require_replay=False)[
        "replay_gate_passed"
    ] is True

    # A valid replay envelope from another Bundle cannot be attached.
    other = create_section_patch_proposal(
        output_root=output_root,
        feedback={"comment": "other candidate"},
        stages=["S3"],
        section_patches=[
            {
                "section_id": "S3:creative",
                "new_text": "另一候选修改，仍保留契约并增加反例检查以验证 hash 绑定。",
            }
        ],
    )
    mismatched_parent = json.loads(json.dumps(summary))
    mismatched_parent["manifest"]["parent_bundle_hash"] = "sha256:" + "0" * 64
    with pytest.raises(ValueError, match="bundle identity"):
        attach_replay_evidence(
            output_root=output_root,
            proposal_id=other["proposal_id"],
            evaluation_id="strict-provenance",
            replay_summary=mismatched_parent,
        )

    mismatched_candidate = json.loads(json.dumps(summary))
    mismatched_candidate["manifest"]["candidate_prompt_hashes"]["S3"] = (
        "sha256:" + "1" * 64
    )
    with pytest.raises(ValueError, match="candidate prompt hash"):
        attach_replay_evidence(
            output_root=output_root,
            proposal_id=other["proposal_id"],
            evaluation_id="strict-provenance",
            replay_summary=mismatched_candidate,
        )
