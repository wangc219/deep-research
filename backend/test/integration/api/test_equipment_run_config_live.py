"""通过真实 HTTP 与 PostgreSQL 验证启动配置；只创建草稿，不启动模型。"""

from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import User
from platform_core.utils.auth_utils import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_research_catalog_preview_and_draft_config_round_trip():
    pg_manager.initialize()
    async with pg_manager.get_async_session_context() as db:
        user = await db.scalar(select(User).where(User.role == "superadmin", User.is_deleted == 0).limit(1))
        if user is None:
            pytest.skip("需要本地已初始化的平台管理员")
        headers = {"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(user.id)})}
    async with httpx.AsyncClient(base_url="http://127.0.0.1:5050", timeout=30) as client:
        assert (await client.get("/api/equipment/catalog")).status_code == 401
        response = await client.get("/api/equipment/catalog", headers=headers)
        assert response.status_code == 200, response.text
        catalog = response.json()
        assert len(catalog["discovery_branches"]) == 8
        assert next(item["id"] for item in catalog["report_templates"] if item["default"]) == "project_argument_v1"
        preview = await client.post(
            "/api/equipment/agent-selection-preview",
            headers=headers,
            json={"topic": "民用应急照明可靠性研究", "discovery_branch": "B"},
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["primary_branch"] == "B"
        assert preview.json()["selected_agent_ids"]
        invalid = await client.post(
            "/api/equipment/agent-selection-preview",
            headers=headers,
            json={"topic": "民用照明", "discovery_branch": "invalid"},
        )
        assert invalid.status_code == 422
        for template in ["project_argument_v1", "three_layer_nine_item"]:
            run_id = None
            try:
                config = {
                    "interaction_mode": "autonomous",
                    "discovery_branch": "B",
                    "execution_profile_id": "legacy_v1",
                    "report_template_mode": template,
                    "max_rounds": 5,
                    "selected_agent_ids": ["weapon_equipment"],
                }
                response = await client.post(
                    "/api/equipment/runs",
                    headers={**headers, "Idempotency-Key": "config-regression-" + uuid4().hex},
                    json={"topic": "配置迁移回归验证（草稿，不启动）", **config},
                )
                assert response.status_code == 200, response.text
                run_id = response.json()["run_id"]
                response = await client.get(f"/api/equipment/runs/{run_id}", headers=headers)
                assert response.status_code == 200, response.text
                run = response.json()
                assert run["status"] == "draft"
                for key, value in config.items():
                    assert run["payload"][key] == value, key
            finally:
                if run_id:
                    deleted = await client.delete(f"/api/equipment/runs/{run_id}", headers=headers)
                    assert deleted.status_code == 200, deleted.text
