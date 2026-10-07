from __future__ import annotations

from pathlib import Path

import pytest

from equipment_deep_research.persistence.database import create_database_engine
from equipment_deep_research.query_library.persistence import QueryLibraryRepository
from equipment_deep_research.query_library.service import QueryLibraryService


@pytest.fixture
def query_service(tmp_path: Path) -> QueryLibraryService:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'query-library.db'}")
    return QueryLibraryService(QueryLibraryRepository(engine))
