"""Capability-card favorite API and persistence coverage."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from fastapi.testclient import TestClient

from equipment_deep_research.api.app import create_app
from equipment_deep_research.application.dto import CreateRunCommand
from equipment_deep_research.application.run_service import ResearchApplicationService
from equipment_deep_research.persistence.database import create_database_engine
from equipment_deep_research.persistence.repositories import SqlRunQueue, SqlRunRepository


MODULE_KEYS = (
    "overview",
    "technology_implementation",
    "operational_process",
    "capability_effects",
    "winning_logic",
)


def _service_with_completed_card(tmp_path: Path, *, repository: bool = True):
    output_root = tmp_path / "runs"
    output_root.mkdir()
    database_url = f"sqlite:///{tmp_path / 'application.db'}"
    if repository:
        engine = create_database_engine(database_url)
        repo = SqlRunRepository(engine)
        service = ResearchApplicationService(
            repository=repo,
            queue=SqlRunQueue(engine),
        )
    else:
        repo = None
        service = ResearchApplicationService()
    run = service.create_run(CreateRunCommand("收藏测试任务", "auto", [], 2, "analyst"))
    run_root = output_root / run.run_id
    run_root.mkdir()
    modules = {key: f"{key} 画像正文。" * 80 for key in MODULE_KEYS}
    (run_root / "capability_images.json").write_text(
        json.dumps(
            [
                {
                    "capability_id": "cap-favorite-1",
                    "card_binding_id": "s6-card-favorite-1",
                    "name": "断链复核巡猎弹",
                    "equipment_category": "远程精确打击弹药",
                    "capability_type": "new_capability",
                    "capability_portrait_modules": modules,
                    "portrait_authoring_status": "s6_authored",
                    "verification_status": "assessed",
                    "confidence": 0.81,
                    "evidence_ids": ["ev-1"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    service.set_result(run.run_id, {"run_dir": str(run_root)})
    service.set_status(run.run_id, "completed")
    return service, repo, run, output_root, database_url


def test_favorite_post_is_idempotent_and_capability_projection_exposes_state(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run, output_root, _ = _service_with_completed_card(tmp_path)
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    client = TestClient(create_app(service))

    created = client.post(
        "/api/v1/favorites",
        json={"run_id": run.run_id, "card_binding_id": "s6-card-favorite-1"},
    )
    assert created.status_code == 201
    favorite = created.json()
    assert favorite["created"] is True
    assert favorite["favorite"]["name"] == "断链复核巡猎弹"
    assert len(favorite["favorite"]["capability_portrait_modules"]) == 5

    duplicate = client.post(
        "/api/v1/favorites",
        json={"run_id": run.run_id, "capability_id": "cap-favorite-1"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["created"] is False
    assert duplicate.json()["favorite_id"] == favorite["favorite_id"]

    listed = client.get("/api/v1/favorites", params={"search": "巡猎"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["source_deleted"] is False

    projected = client.get(f"/api/v1/runs/{run.run_id}/capabilities")
    assert projected.status_code == 200
    assert projected.json()[0]["favorited"] is True
    assert projected.json()[0]["favorite_id"] == favorite["favorite_id"]
    assert repository is not None

    denied = client.delete(f"/api/v1/favorites/{favorite['favorite_id']}")
    assert denied.status_code == 403
    removed = client.delete(
        f"/api/v1/favorites/{favorite['favorite_id']}",
        headers={"X-Role": "admin"},
    )
    assert removed.status_code == 200
    assert client.get("/api/v1/favorites").json()["total"] == 0


def test_same_name_cards_with_distinct_ids_remain_distinct_favorites(
    tmp_path: Path, monkeypatch
) -> None:
    service, _repository, run, output_root, _ = _service_with_completed_card(tmp_path)
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    root = output_root / run.run_id
    payload = json.loads((root / "capability_images.json").read_text(encoding="utf-8"))
    second = dict(payload[0])
    second.update(
        {
            "capability_id": "cap-favorite-2",
            "card_binding_id": "s6-card-favorite-2",
            # Two real cards can share a display title while representing
            # different hypotheses; name aliases must not collapse them.
            "name": payload[0]["name"],
        }
    )
    (root / "capability_images.json").write_text(
        json.dumps([payload[0], second], ensure_ascii=False), encoding="utf-8"
    )
    client = TestClient(create_app(service))

    first = client.post(
        "/api/v1/favorites",
        json={"run_id": run.run_id, "card_binding_id": "s6-card-favorite-1"},
    )
    second_created = client.post(
        "/api/v1/favorites",
        json={"run_id": run.run_id, "card_binding_id": "s6-card-favorite-2"},
    )

    assert first.status_code == 201
    assert second_created.status_code == 201
    assert client.get("/api/v1/favorites").json()["total"] == 2
    projected = client.get(f"/api/v1/runs/{run.run_id}/capabilities")
    assert projected.status_code == 200
    assert {row["favorite_id"] for row in projected.json()} == {
        first.json()["favorite_id"],
        second_created.json()["favorite_id"],
    }


def test_favorite_rejects_incomplete_portrait_and_private_scope_reservation(
    tmp_path: Path, monkeypatch
) -> None:
    service, _repository, run, output_root, _ = _service_with_completed_card(tmp_path)
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    root = output_root / run.run_id
    payload = json.loads((root / "capability_images.json").read_text(encoding="utf-8"))
    payload[0]["capability_portrait_modules"].pop("winning_logic")
    (root / "capability_images.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    client = TestClient(create_app(service))
    rejected = client.post(
        "/api/v1/favorites",
        json={"run_id": run.run_id, "card_binding_id": "s6-card-favorite-1"},
    )
    assert rejected.status_code == 422
    assert "五模块" in rejected.json()["detail"]

    private = client.get("/api/v1/favorites", params={"scope": "private"})
    assert private.status_code == 403
    private_post = client.post(
        "/api/v1/favorites",
        json={
            "run_id": run.run_id,
            "scope": "private",
            "card_binding_id": "s6-card-favorite-1",
        },
        headers={"X-User-ID": "user-1"},
    )
    assert private_post.status_code == 403


def test_favorites_survive_source_run_permanent_delete_and_sqlite_restart(
    tmp_path: Path, monkeypatch
) -> None:
    service, repository, run, output_root, database_url = _service_with_completed_card(tmp_path)
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    client = TestClient(create_app(service))
    created = client.post(
        "/api/v1/favorites",
        json={"run_id": run.run_id, "card_binding_id": "s6-card-favorite-1"},
    )
    assert created.status_code == 201
    favorite_id = created.json()["favorite_id"]

    archived = client.delete(f"/api/v1/runs/{run.run_id}")
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    archived_favorite = client.get("/api/v1/favorites").json()["items"][0]
    assert archived_favorite["source_status"] == "archived"
    assert archived_favorite["source_deleted"] is False

    deleted = client.delete(
        f"/api/v1/runs/{run.run_id}/permanent",
        headers={"X-Role": "admin"},
    )
    assert deleted.status_code == 200
    assert repository is not None
    snapshot = repository.get_favorite(favorite_id)
    assert snapshot is not None
    assert snapshot["source_deleted"] is True
    assert snapshot["source_status"] == "deleted"
    assert snapshot["capability_portrait_modules"]["overview"]

    # The source run is gone, but the immutable favorite remains the
    # idempotency target for network retries.  Exercise both the canonical
    # binding identifier and the legacy capability identifier aliases.
    retry = client.post(
        "/api/v1/favorites",
        json={"run_id": run.run_id, "card_binding_id": "s6-card-favorite-1"},
    )
    assert retry.status_code == 200
    assert retry.json()["created"] is False
    assert retry.json()["idempotent"] is True
    assert retry.json()["favorite_id"] == favorite_id

    alias_retry = client.post(
        "/api/v1/favorites",
        json={"run_id": run.run_id, "capability_id": "cap-favorite-1"},
    )
    assert alias_retry.status_code == 200
    assert alias_retry.json()["created"] is False
    assert alias_retry.json()["favorite_id"] == favorite_id

    restarted_engine = create_database_engine(database_url)
    restarted = ResearchApplicationService(
        repository=SqlRunRepository(restarted_engine),
        queue=SqlRunQueue(restarted_engine),
    )
    restarted_client = TestClient(create_app(restarted))
    listed = restarted_client.get("/api/v1/favorites")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["source_deleted"] is True
    assert listed.json()["items"][0]["name"] == "断链复核巡猎弹"


def test_concurrent_sql_favorite_posts_return_one_created_and_one_idempotent(
    tmp_path: Path, monkeypatch
) -> None:
    """The unique fence prevents duplicates and the response reflects the winner."""

    service, _repository, run, output_root, database_url = _service_with_completed_card(
        tmp_path
    )
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))

    # Force both independent API workers through their pre-check before either
    # INSERT. Without request-local IDs the old API reported 201 from both
    # workers even though SQLite retained only one row.
    save_barrier = Barrier(2)

    class BarrierRepository(SqlRunRepository):
        def save_favorite(self, **values):  # type: ignore[no-untyped-def]
            save_barrier.wait(timeout=5)
            return super().save_favorite(**values)

    first_engine = create_database_engine(database_url)
    second_engine = create_database_engine(database_url)
    first_service = ResearchApplicationService(
        repository=BarrierRepository(first_engine),
        queue=SqlRunQueue(first_engine),
    )
    second_service = ResearchApplicationService(
        repository=BarrierRepository(second_engine),
        queue=SqlRunQueue(second_engine),
    )
    clients = [TestClient(create_app(first_service)), TestClient(create_app(second_service))]

    def post(client: TestClient):
        return client.post(
            "/api/v1/favorites",
            json={"run_id": run.run_id, "card_binding_id": "s6-card-favorite-1"},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(post, clients))

    assert sorted(response.status_code for response in responses) == [200, 201]
    assert sorted(response.json()["created"] for response in responses) == [False, True]
    assert len({response.json()["favorite_id"] for response in responses}) == 1
    assert first_service.repository.list_favorites()["total"] == 1


def test_favorite_rejects_explicit_failure_and_temporary_statuses(
    tmp_path: Path, monkeypatch
) -> None:
    service, _repository, run, output_root, _ = _service_with_completed_card(tmp_path)
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    root = output_root / run.run_id
    payload = json.loads((root / "capability_images.json").read_text(encoding="utf-8"))
    client = TestClient(create_app(service))

    from equipment_deep_research.api.app import _favorite_portrait_eligibility

    for field, value in (
        ("portrait_authoring_status", "authoring_failed"),
        ("portrait_authoring_status", "draft"),
        ("verification_status", "failed"),
        ("s6_authoring_failed", True),
        ("is_temporary", True),
    ):
        candidate = dict(payload[0], **{field: value})
        eligible, _reason = _favorite_portrait_eligibility(candidate)
        assert eligible is False

    # Keep the fixture on disk unchanged and verify the endpoint still works
    # for the original formal card after the direct helper checks.
    accepted = client.post(
        "/api/v1/favorites",
        json={"run_id": run.run_id, "card_binding_id": "s6-card-favorite-1"},
    )
    assert accepted.status_code == 201


def test_memory_service_favorites_work_without_sql_repository(
    tmp_path: Path, monkeypatch
) -> None:
    service, _repository, run, output_root, _ = _service_with_completed_card(
        tmp_path, repository=False
    )
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    client = TestClient(create_app(service))
    created = client.post(
        "/api/v1/favorites",
        json={"run_id": run.run_id, "card_binding_id": "s6-card-favorite-1"},
    )
    assert created.status_code == 201
    assert client.get("/api/v1/favorites").json()["total"] == 1


def test_complete_legacy_portrait_is_eligible_but_explicit_limited_provenance_is_not(
    tmp_path: Path, monkeypatch
) -> None:
    service, _repository, run, output_root, _ = _service_with_completed_card(tmp_path)
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    root = output_root / run.run_id
    payload = json.loads((root / "capability_images.json").read_text(encoding="utf-8"))
    payload[0]["portrait_authoring_status"] = "legacy_v1"
    payload[0]["analysis_provenance_status"] = "structured_migrated"
    payload[0]["is_reference"] = "false"
    payload[0]["confidence_limited"] = "false"
    (root / "capability_images.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    client = TestClient(create_app(service))
    accepted = client.post(
        "/api/v1/favorites",
        json={"run_id": run.run_id, "card_binding_id": "s6-card-favorite-1"},
    )
    assert accepted.status_code == 201
    assert accepted.json()["favorite"]["snapshot"]["name"] == "断链复核巡猎弹"
    assert json.loads(accepted.json()["favorite"]["snapshot_json"])["name"] == "断链复核巡猎弹"

    # A complete stale module blob must not bypass an explicit limited/provisional
    # provenance marker.
    payload[0]["analysis_provenance_status"] = "limited_failure"
    payload[0]["portrait_authoring_status"] = "legacy_v1"
    (root / "capability_images.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    # The first run already has an immutable favorite; eligibility is covered
    # directly by the helper for the explicit rejection case.
    from equipment_deep_research.api.app import _favorite_portrait_eligibility

    eligible, reason = _favorite_portrait_eligibility(payload[0])
    assert eligible is False
    assert "formal S6" in reason


def test_favorite_crud_get_update_put_preserves_snapshot_and_survives_sqlite_restart(
    tmp_path: Path, monkeypatch
) -> None:
    """Mutable presentation metadata must not rewrite the immutable card snapshot."""

    service, repository, run, output_root, database_url = _service_with_completed_card(
        tmp_path
    )
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    client = TestClient(create_app(service))

    created = client.post(
        "/api/v1/favorites",
        json={"run_id": run.run_id, "card_binding_id": "s6-card-favorite-1"},
    )
    assert created.status_code == 201
    favorite = created.json()["favorite"]
    favorite_id = favorite["favorite_id"]
    original_snapshot = favorite["snapshot"]
    original_snapshot_json = favorite["snapshot_json"]

    fetched = client.get(f"/api/v1/favorites/{favorite_id}")
    assert fetched.status_code == 200
    assert fetched.json()["favorite"]["snapshot"] == original_snapshot

    empty_patch = client.patch(
        f"/api/v1/favorites/{favorite_id}",
        json={},
        headers={"X-Role": "analyst"},
    )
    assert empty_patch.status_code == 422

    patched = client.patch(
        f"/api/v1/favorites/{favorite_id}",
        json={
            "display_name": "断链复核 · 重点卡",
            "note": "纳入下一轮装备论证。",
            "tags": ["重点", "装备论证", "重点"],
        },
        headers={"X-Role": "analyst"},
    )
    assert patched.status_code == 200
    patched_favorite = patched.json()["favorite"]
    assert patched.json()["updated"] is True
    assert patched_favorite["display_name"] == "断链复核 · 重点卡"
    assert patched_favorite["note"] == "纳入下一轮装备论证。"
    assert patched_favorite["tags"] == ["重点", "装备论证"]
    assert patched_favorite["snapshot"] == original_snapshot
    assert patched_favorite["snapshot_json"] == original_snapshot_json
    assert patched_favorite["name"] == "断链复核巡猎弹"

    # PUT and compatibility aliases update only the presentation metadata.
    replaced = client.put(
        f"/api/v1/favorites/{favorite_id}",
        json={"title": "复核巡猎弹（已归档）", "memo": "等待专家复核。"},
        headers={"X-Role": "analyst"},
    )
    assert replaced.status_code == 200
    replaced_favorite = replaced.json()["favorite"]
    assert replaced_favorite["display_name"] == "复核巡猎弹（已归档）"
    assert replaced_favorite["note"] == "等待专家复核。"
    assert replaced_favorite["snapshot"] == original_snapshot
    assert replaced_favorite["snapshot_json"] == original_snapshot_json

    # Metadata is included in list/search results as well as single-item GET.
    searched = client.get(
        "/api/v1/favorites", params={"search": "已归档"}
    )
    assert searched.status_code == 200
    assert searched.json()["total"] == 1
    assert searched.json()["items"][0]["display_name"] == "复核巡猎弹（已归档）"

    # A fresh repository sees the mutable columns while preserving the same
    # immutable snapshot JSON.
    assert repository is not None
    restarted_engine = create_database_engine(database_url)
    restarted = ResearchApplicationService(
        repository=SqlRunRepository(restarted_engine),
        queue=SqlRunQueue(restarted_engine),
    )
    restarted_client = TestClient(create_app(restarted))
    restarted_favorite = restarted_client.get(
        f"/api/v1/favorites/{favorite_id}"
    )
    assert restarted_favorite.status_code == 200
    restarted_payload = restarted_favorite.json()["favorite"]
    assert restarted_payload["display_name"] == "复核巡猎弹（已归档）"
    assert restarted_payload["note"] == "等待专家复核。"
    assert restarted_payload["snapshot"] == original_snapshot
    assert restarted_payload["snapshot_json"] == original_snapshot_json

    denied_delete = restarted_client.delete(f"/api/v1/favorites/{favorite_id}")
    assert denied_delete.status_code == 403
    deleted = restarted_client.delete(
        f"/api/v1/favorites/{favorite_id}",
        headers={"X-Role": "admin"},
    )
    assert deleted.status_code == 200
    assert restarted_client.get(f"/api/v1/favorites/{favorite_id}").status_code == 404
    assert (
        restarted_client.patch(
            f"/api/v1/favorites/{favorite_id}",
            json={"note": "after delete"},
            headers={"X-Role": "admin"},
        ).status_code
        == 404
    )
    assert (
        restarted_client.delete(
            f"/api/v1/favorites/{favorite_id}",
            headers={"X-Role": "admin"},
        ).status_code
        == 404
    )


def test_memory_favorite_crud_updates_metadata_without_mutating_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    service, _repository, run, output_root, _database_url = _service_with_completed_card(
        tmp_path, repository=False
    )
    monkeypatch.setenv("EQUIPMENT_DR_OUTPUT_ROOT", str(output_root))
    client = TestClient(create_app(service))
    created = client.post(
        "/api/v1/favorites",
        json={"run_id": run.run_id, "card_binding_id": "s6-card-favorite-1"},
    )
    assert created.status_code == 201
    favorite_id = created.json()["favorite_id"]
    original_snapshot = created.json()["favorite"]["snapshot"]

    updated = client.patch(
        f"/api/v1/favorites/{favorite_id}",
        json={"name": "内存收藏卡", "memo": "仅测试内存仓储。", "tags": ["memory"]},
        headers={"X-Role": "analyst"},
    )
    assert updated.status_code == 200
    assert updated.json()["favorite"]["display_name"] == "内存收藏卡"
    assert updated.json()["favorite"]["note"] == "仅测试内存仓储。"
    assert updated.json()["favorite"]["tags"] == ["memory"]
    assert updated.json()["favorite"]["snapshot"] == original_snapshot

    listed = client.get("/api/v1/favorites", params={"search": "内存收藏"})
    assert listed.status_code == 200
    assert listed.json()["items"][0]["display_name"] == "内存收藏卡"
