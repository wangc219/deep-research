from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from equipment_deep_research.application.dto import CreateRunCommand
from equipment_deep_research.application.run_service import InvalidRunTransition, ResearchApplicationService


class CreateRunBody(BaseModel):
    topic: str
    research_route: str = "auto"
    selected_agent_ids: list[str] = Field(default_factory=list)
    max_rounds: int = 5


def create_app(service: ResearchApplicationService | None = None) -> FastAPI:
    service = service or ResearchApplicationService()
    app = FastAPI(title="Equipment Deep Research API", version="0.1.0")

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/v1/runs")
    def list_runs() -> list[dict]:
        return [item.__dict__ for item in service.list_runs()]

    @app.post("/api/v1/runs", status_code=201)
    def create_run(body: CreateRunBody) -> dict:
        return service.create_run(CreateRunCommand(body.topic, body.research_route, body.selected_agent_ids, body.max_rounds, "api-user")).__dict__

    @app.post("/api/v1/runs/{run_id}/start")
    def start_run(run_id: str, idempotency_key: str = Header(alias="Idempotency-Key")) -> dict:
        try:
            return service.start_run(run_id, actor="api-user", idempotency_key=idempotency_key).__dict__
        except (KeyError, InvalidRunTransition) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return app
