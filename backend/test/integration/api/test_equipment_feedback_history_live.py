"""真实 PostgreSQL 与 HTTP 验证反馈归属、即时回读、校准和回滚审计。"""

from uuid import uuid4

import pytest
from sqlalchemy import delete

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Project
from platform_core.storage.postgres.models_equipment import EquipmentCapabilityVersion, EquipmentResearchRun

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_feedback_history_committed_scores_and_rollback(test_client, standard_user):
    """合成画像仅作边界夹具；反馈全部通过运行中的 API 和真实数据库处理。"""
    uid = standard_user["user"]["uid"]
    headers = standard_user["headers"]
    suffix = uuid4().hex
    project_id = "feedback-project-" + suffix
    run_ids = ["feedback-run-" + suffix + ending for ending in ("-a", "-b")]
    version_ids = ["feedback-version-" + suffix + ending for ending in ("-a", "-b")]
    dimensions = ("innovation", "demand", "feasibility", "effectiveness", "development")
    async with pg_manager.get_async_session_context() as db:
        db.add(
            Project(
                id=project_id,
                uid=uid,
                name="pytest feedback history",
                selection_status="selectable",
                directory_mode="managed",
                workdir_path="feedback-" + suffix,
                status="active",
            )
        )
        await db.flush()
        for run_id, version_id in zip(run_ids, version_ids):
            db.add(
                EquipmentResearchRun(
                    id=run_id,
                    project_id=project_id,
                    owner_uid=uid,
                    topic="合成反馈验收，不生成真实研究结论",
                    research_route="auto",
                    status="draft",
                    payload={},
                )
            )
            await db.flush()
            db.add(
                EquipmentCapabilityVersion(
                    id=version_id,
                    project_id=project_id,
                    owner_uid=uid,
                    run_id=run_id,
                    snapshot={
                        "capability_id": "same-card-id",
                        "name": "合成验收画像",
                        "version_no": 1,
                        "s5_dimension_scores": dict.fromkeys(dimensions, 0.6),
                    },
                )
            )
        await db.commit()
    base = f"/api/equipment/runs/{run_ids[0]}/expert-feedback"
    payload = {
        "capability_id": "same-card-id",
        "capability_version_id": version_ids[0],
        "comment": "合成反馈验收，请勿视为实际专家评价。",
        "verdict": "needs_revision",
        "model_dimension_scores": dict.fromkeys(dimensions, 0.1),
        "expert_dimension_scores": dict.fromkeys(dimensions, 0.8),
        "expert_weighted_score": 0.99,
        "target_agent_ids": ["S5"],
        "stage_scope": ["S5"],
    }
    try:
        cards = (await test_client.get("/api/equipment/capabilities", headers=headers)).json()
        card = next(row for row in cards if row["id"] == version_ids[0])
        assert card["version_id"] == version_ids[0]
        wrong = await test_client.post(base, headers=headers, json=payload | {"capability_version_id": version_ids[1]})
        assert wrong.status_code == 422
        malformed = await test_client.post(
            base, headers=headers, json=payload | {"expert_dimension_scores": {"innovation": 1.2}}
        )
        assert malformed.status_code == 422
        created = []
        for index in range(5):
            response = await test_client.post(
                base, headers=headers, json=payload | {"comment": payload["comment"] + str(index)}
            )
            assert response.status_code == 200, response.text
            item = response.json()["feedback"]
            created.append(item)
            assert item["expert_weighted_score"] == pytest.approx(0.8)
            assert set(item["model_dimension_scores"].values()) == {0.6}
            assert item["score_deltas"]["innovation"] == pytest.approx(0.2)
            assert item["capability_version_id"] == version_ids[0]
            assert item["reviewer_uid"] == uid
            assert item["learning_status"] == "processed"
            assert item["effect_status"] == "pending_validation"
            assert item["created_at"].endswith("Z")
        rows = (await test_client.get(base, headers=headers, params={"include_rolled_back": "true"})).json()
        assert [row["feedback_id"] for row in rows] == [row["feedback_id"] for row in reversed(created)]
        last = created[-1]["feedback_id"]
        response = await test_client.post(base + f"/{last}/rollback", headers=headers, json={"reason": "合成验收回滚"})
        assert response.status_code == 200, response.text
        assert response.json()["feedback"]["status"] == "rolled_back"
        active = (await test_client.get(base, headers=headers)).json()
        assert len(active) == 4
        history = (await test_client.get(base, headers=headers, params={"include_rolled_back": "true"})).json()
        assert len(history) == 5 and history[0]["feedback_id"] == last
        assert history[0]["memory_status"] == "retired"
        assert history[0]["rolled_back_by"] == uid
        assert history[0]["rolled_back_at"].endswith("Z")
        assert history[0]["rollback_reason"] == "合成验收回滚"
    finally:
        async with pg_manager.get_async_session_context() as db:
            await db.execute(delete(EquipmentCapabilityVersion).where(EquipmentCapabilityVersion.id.in_(version_ids)))
            await db.execute(delete(EquipmentResearchRun).where(EquipmentResearchRun.id.in_(run_ids)))
            await db.execute(delete(Project).where(Project.id == project_id))
            await db.commit()
