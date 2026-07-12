from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine


def create_database_engine(url: str) -> Engine:
    return create_engine(url, future=True)
