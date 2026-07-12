from __future__ import annotations

import json

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from equipment_deep_research.application.dto import CreateRunCommand
from equipment_deep_research.application.run_service import InvalidRunTransition, ResearchApplicationService


class CreateRunBody(BaseModel):
    topic: str
    research_route: str = "auto"
    selected_agent_ids: list[str] = Field(default_factory=list)
    max_rounds: int = 5


def create_app(service: ResearchApplicationService | None = None, event_repository: object | None = None) -> FastAPI:
    service = service or ResearchApplicationService()
    app = FastAPI(title="Equipment Deep Research API", version="0.1.0")

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/runs")
    def list_runs(x_role: str = Header(default="analyst", alias="X-Role")) -> list[dict]:
        _require_role(x_role, {"analyst", "reviewer", "auditor", "admin"})
        return [item.__dict__ for item in service.list_runs()]

    @app.get("/api/v1/runs/{run_id}")
    def get_run(run_id: str) -> dict:
        try:
            return service.get_run(run_id).__dict__
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc

    @app.get("/api/v1/catalog")
    def catalog() -> dict:
        return {
            "routes": [
                {"id": "new_winning_mechanism", "name": "新制胜机理", "required_tags": ["situation", "threat", "scenario", "equipment", "operation"]},
                {"id": "traditional_gap", "name": "传统能力缺口", "required_tags": ["scenario", "equipment", "capability_gap", "operation"]},
                {"id": "war_case_learning", "name": "局部战争案例", "required_tags": ["situation", "scenario", "equipment", "lessons"]},
            ],
            "agents": [
                {"agent_id": "international_situation", "display_name": "国际形势", "capability_tags": ["situation", "threat", "strategy"]},
                {"agent_id": "combat_scenario", "display_name": "作战场景", "capability_tags": ["scenario", "coa", "environment"]},
                {"agent_id": "weapon_equipment", "display_name": "武器装备", "capability_tags": ["equipment", "capability_gap", "technology_readiness"]},
                {"agent_id": "operational_employment", "display_name": "作战运用", "capability_tags": ["operation", "coordination", "lessons"]},
            ],
            "provider": {"type": "responses", "model": "gpt-5.5"},
        }

    @app.post("/api/v1/runs", status_code=201)
    def create_run(body: CreateRunBody, x_role: str = Header(default="analyst", alias="X-Role")) -> dict:
        _require_role(x_role, {"analyst", "admin"})
        return service.create_run(CreateRunCommand(body.topic, body.research_route, body.selected_agent_ids, body.max_rounds, "api-user")).__dict__

    @app.post("/api/v1/runs/{run_id}/start")
    def start_run(run_id: str, idempotency_key: str = Header(alias="Idempotency-Key"), x_role: str = Header(default="analyst", alias="X-Role")) -> dict:
        _require_role(x_role, {"analyst", "admin"})
        try:
            return service.start_run(run_id, actor="api-user", idempotency_key=idempotency_key).__dict__
        except (KeyError, InvalidRunTransition) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/runs/{run_id}/events")
    def replay_events(run_id: str, last_event_id: int = Header(default=0, alias="Last-Event-ID")) -> StreamingResponse:
        rows = [] if event_repository is None else event_repository.events_after(run_id, last_event_id)
        def stream():
            for row in rows:
                yield f"id: {row['sequence']}\nevent: {row['event_type']}\ndata: {json.dumps(row['payload'], ensure_ascii=False)}\n\n"
        return StreamingResponse(stream(), media_type="text/event-stream")
    return app


def _require_role(role: str, allowed: set[str]) -> None:
    if role not in allowed:
        raise HTTPException(status_code=403, detail="insufficient role")
