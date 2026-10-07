from __future__ import annotations

from pathlib import Path

from equipment_deep_research.application.run_service import ResearchApplicationService
from equipment_deep_research.config.settings import Settings, load_settings
from equipment_deep_research.persistence.database import create_database_engine
from equipment_deep_research.persistence.repositories import SqlRunQueue, SqlRunRepository
from equipment_deep_research.runtime_identity import RUNTIME_BUILD_HASH


def build_application_service(
    database_url: str | None = None,
    *,
    settings: Settings | None = None,
) -> ResearchApplicationService:
    """Build the run service at the composition root.

    ``settings`` is injectable for tests and alternate hosts.  The legacy
    ``database_url`` argument remains supported for CLI compatibility.
    """

    resolved = settings or load_settings()
    url = database_url or resolved.database_url
    if url.startswith("sqlite:///"):
        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    engine = create_database_engine(url)
    return ResearchApplicationService(
        repository=SqlRunRepository(engine),
        queue=SqlRunQueue(engine, generation=RUNTIME_BUILD_HASH),
    )
