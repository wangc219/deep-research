from __future__ import annotations

import os
from pathlib import Path

from equipment_deep_research.application.run_service import ResearchApplicationService
from equipment_deep_research.persistence.database import create_database_engine
from equipment_deep_research.persistence.repositories import SqlRunQueue, SqlRunRepository
from equipment_deep_research.runtime_identity import RUNTIME_BUILD_HASH


def build_application_service(database_url: str | None = None) -> ResearchApplicationService:
    url = database_url or os.environ.get("EQUIPMENT_DR_APP_DB", "sqlite:///outputs/application.db")
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_database_engine(url)
    return ResearchApplicationService(
        repository=SqlRunRepository(engine),
        queue=SqlRunQueue(engine, generation=RUNTIME_BUILD_HASH),
    )
