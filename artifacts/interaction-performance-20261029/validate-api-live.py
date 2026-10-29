"""在真实 PostgreSQL 和只读产物上验证实际 HTTP 投影契约。"""
import asyncio
import gzip
import json
import time

import httpx
from fastapi import FastAPI
from sqlalchemy import select
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import User
from platform_core.storage.postgres.models_equipment import EquipmentResearchRun
from server.routers.equipment_router import equipment
from server.utils.auth_middleware import get_required_user


async def main():
    pg_manager.initialize()
    run_id = "run-0badd47fc5231bd49a80187718ba6bb9"
    async with pg_manager.get_async_session_context() as db:
        run = await db.get(EquipmentResearchRun, run_id)
        user = await db.scalar(select(User).where(User.uid == run.owner_uid))
        assert user is not None
    app = FastAPI()
    app.include_router(equipment, prefix="/api")
    app.dependency_overrides[get_required_user] = lambda: user
    results = {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://validation") as client:
        for compact in (True, False):
            started = time.monotonic()
            response = await client.get(f"/api/equipment/runs/{run_id}/interactions", params={"compact": str(compact).lower()})
            response.raise_for_status()
            body = response.json()
            results[str(compact)] = {
                "seconds": round(time.monotonic() - started, 3),
                "events": body["counts"]["events"],
                "returned_events": len(body["events"]),
                "bytes": len(response.content),
                "gzip_bytes": len(gzip.compress(response.content)),
                "last_sequence": max(e["sequence"] for e in body["events"]),
            }
            assert body["counts"]["events"] == 2480
            assert body["workflow"]["status"] == "completed"
            assert len(body["events"]) == (120 if compact else 2480)
        assert results["True"]["last_sequence"] == results["False"]["last_sequence"] == 4012
    print(json.dumps({"actual_http_postgres_validation": results}))
    await pg_manager.close()


asyncio.run(main())
