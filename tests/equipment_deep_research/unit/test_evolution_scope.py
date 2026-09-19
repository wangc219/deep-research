"""Compatibility contracts for run-scoped self-evolution metadata."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from equipment_deep_research.api.app import create_app
from equipment_deep_research.application.run_service import ResearchApplicationService
from equipment_deep_research.orchestration.runner import DeepResearchRunner


def _runner(project_root: Path) -> DeepResearchRunner:
    return DeepResearchRunner(
        project_root=project_root,
        output_root=project_root / "outputs" / "runs",
        agent_config_path=project_root / "agents.yaml",
        preset_config_path=project_root / "presets.yaml",
    )


def test_evolution_snapshot_is_scope_bound_and_excludes_history(tmp_path: Path) -> None:
    prompt_root = (
        tmp_path
        / "src"
        / "equipment_deep_research"
        / "agents"
        / "prompts"
        / "dynamic_winning"
    )
    prompt_root.mkdir(parents=True)
    (prompt_root / "S6.md").write_text("active prompt", encoding="utf-8")
    (prompt_root / "section_manifest.json").write_text(
        json.dumps({"schema_version": "1.0"}), encoding="utf-8"
    )
    versions = prompt_root / "versions" / "S6"
    versions.mkdir(parents=True)
    (versions / "v0001.md").write_text("historical prompt", encoding="utf-8")

    runner = _runner(tmp_path)
    snapshot = runner._evolution_snapshot(
        [
            {
                "feedback_id": "feedback-1",
                "tenant_id": "tenant-a",
                "workspace_id": "workspace-a",
                "stage_scope": ["S6"],
            }
        ],
        scope={
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
            "project_id": "project-a",
            "profile_id": "profile-a",
            "route": "traditional_gap",
            "stage_scope": ["S6"],
        },
    )

    assert "versions/S6/v0001.md" not in snapshot["prompt_files"]
    assert any(path.endswith("section_manifest.json") for path in snapshot["prompt_files"])
    assert snapshot["scope"]["tenant_id"] == "tenant-a"
    assert snapshot["scope"]["stage_scope"] == ["S6"]

    # Empty (or identical) feedback must still produce a namespace-specific
    # memory identity; otherwise caches/replay tooling could mistake two
    # tenants for sharing the same effective memory snapshot.
    empty_scope_snapshot = runner._evolution_snapshot(
        [],
        scope={
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
            "project_id": "project-a",
            "profile_id": "profile-a",
            "route": "traditional_gap",
            "stage_scope": ["S6"],
        },
    )
    other_scope_snapshot = runner._evolution_snapshot(
        [],
        scope={
            "tenant_id": "tenant-b",
            "workspace_id": "workspace-a",
            "project_id": "project-a",
            "profile_id": "profile-a",
            "route": "traditional_gap",
            "stage_scope": ["S6"],
        },
    )
    assert empty_scope_snapshot["memory_snapshot_hash"] != other_scope_snapshot["memory_snapshot_hash"]


def test_create_run_persists_evolution_scope_from_gateway_headers() -> None:
    service = ResearchApplicationService()
    client = TestClient(create_app(service))
    response = client.post(
        "/api/v1/runs",
        json={"topic": "scoped task", "stage_scope": ["S4", "S6"]},
        headers={
            "X-Tenant-ID": "tenant-a",
            "X-Workspace-ID": "workspace-a",
            "X-Project-ID": "project-a",
            "X-Profile-ID": "profile-a",
            "X-Evolution-Stage-Scope": "S6",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["tenant_id"] == "tenant-a"
    assert payload["workspace_id"] == "workspace-a"
    assert payload["project_id"] == "project-a"
    assert payload["profile_id"] == "profile-a"
    assert payload["stage_scope"] == ["S6"]


def test_create_run_merges_stage_header_without_clearing_body_scope() -> None:
    service = ResearchApplicationService()
    client = TestClient(create_app(service))
    response = client.post(
        "/api/v1/runs",
        json={
            "topic": "scoped task",
            "tenant_id": "tenant-from-body",
            "workspace_id": "workspace-from-body",
            "project_id": "project-from-body",
            "profile_id": "profile-from-body",
            "stage_scope": ["S4", "S6"],
        },
        headers={"X-Evolution-Stage-Scope": "S6"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["tenant_id"] == "tenant-from-body"
    assert payload["workspace_id"] == "workspace-from-body"
    assert payload["project_id"] == "project-from-body"
    assert payload["profile_id"] == "profile-from-body"
    assert payload["stage_scope"] == ["S6"]


def test_update_run_cannot_relabel_evolution_tenant() -> None:
    service = ResearchApplicationService()
    client = TestClient(create_app(service))
    created = client.post(
        "/api/v1/runs",
        json={"topic": "scoped task"},
        headers={"X-Tenant-ID": "tenant-a"},
    ).json()
    run_id = created["run_id"]
    response = client.patch(
        f"/api/v1/runs/{run_id}",
        json={
            "topic": "scoped task",
            "research_route": "auto",
            "selected_agent_ids": [],
            "max_rounds": 2,
        },
        headers={"X-Tenant-ID": "tenant-b"},
    )

    assert response.status_code == 403
