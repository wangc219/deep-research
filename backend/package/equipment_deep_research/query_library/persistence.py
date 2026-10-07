from __future__ import annotations

import hashlib

from equipment_deep_research.domain.platform_identity import platform_identity

from datetime import UTC, datetime, timedelta
import json
from threading import Lock
from typing import Any

from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    and_,
    delete,
    func,
    inspect,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from equipment_deep_research.query_library.models import (
    DuplicateQueryError,
    GeneratedCandidate,
    GenerationJob,
    GenerationNotFoundError,
    InvalidStatusTransition,
    QueryNotFoundError,
    QueryRecord,
    QueryRevision,
    SourceReference,
    VersionConflictError,
    new_id,
    normalize_knowledge_ids,
    now_iso,
    query_fingerprint,
)


metadata = MetaData()

query_items = Table(
    "query_library_items",
    metadata,
    Column("query_id", String(128), primary_key=True),
    Column("owner_uid", String(128), nullable=False, server_default="", index=True),
    Column("query", Text, nullable=False),
    Column("query_fingerprint", String(64), nullable=False, unique=True, index=True),
    Column("supplemental_information", Text, nullable=False),
    Column("generation_rationale", Text, nullable=False),
    Column("source_references", Text, nullable=False),
    Column("status", String(32), nullable=False, index=True),
    Column("source_type", String(32), nullable=False, index=True),
    Column("generation_id", String(128), nullable=False, index=True),
    Column("knowledge_enabled", Integer, nullable=False, default=1, server_default="1"),
    # SQL NULL means all currently owner-visible knowledge bases; JSON []
    # means disabled and a non-empty JSON array is a narrowing hint.
    Column("knowledge_ids", Text, nullable=True),
    Column("version", Integer, nullable=False),
    Column("created_at", String(64), nullable=False),
    Column("updated_at", String(64), nullable=False),
)

query_revisions = Table(
    "query_library_revisions",
    metadata,
    Column("revision_id", Integer, primary_key=True, autoincrement=True),
    Column("query_id", String(128), nullable=False, index=True),
    Column("version", Integer, nullable=False),
    Column("change_type", String(64), nullable=False),
    Column("snapshot", Text, nullable=False),
    Column("changed_at", String(64), nullable=False),
)

generation_jobs = Table(
    "query_generation_jobs",
    metadata,
    Column("generation_id", String(128), primary_key=True),
    Column("owner_uid", String(128), nullable=False, server_default="", index=True),
    Column("idempotency_key", String(200), nullable=True, unique=True),
    Column("topic", String(500), nullable=False),
    Column("supplemental_information", Text, nullable=False),
    Column("reference_urls", Text, nullable=False),
    Column("model_config", Text, nullable=False),
    Column("knowledge_enabled", Integer, nullable=False, default=1, server_default="1"),
    Column("knowledge_ids", Text, nullable=True),
    Column("requested_count", Integer, nullable=False),
    Column("status", String(32), nullable=False, index=True),
    Column("stage", String(64), nullable=False),
    Column("search_queries", Text, nullable=False),
    Column("source_references", Text, nullable=False),
    Column("result_query_ids", Text, nullable=False),
    Column("error", Text, nullable=False),
    Column("provider_snapshot", Text, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("lease_owner", String(128), nullable=False),
    Column("lease_expires_at", String(64), nullable=False),
    Column("created_at", String(64), nullable=False),
    Column("updated_at", String(64), nullable=False),
    Column("started_at", String(64), nullable=False),
    Column("completed_at", String(64), nullable=False),
)

seed_imports = Table(
    "query_library_seed_imports",
    metadata,
    Column("source_name", String(300), primary_key=True),
    Column("source_fingerprint", String(64), primary_key=True),
    Column("imported_count", Integer, nullable=False),
    Column("imported_at", String(64), nullable=False),
)

provider_credentials = Table(
    "query_library_provider_credentials",
    metadata,
    Column("credential_id", String(128), primary_key=True),
    Column("encrypted_secret", Text, nullable=False),
    Column("created_at", String(64), nullable=False),
)


def _owner_uid() -> str:
    """仅从已验证的平台请求获取作者。"""
    identity = platform_identity.get()
    return identity.uid if identity else ""


def _owned(table):
    """读取按所有者过滤；超级管理员可以读取全局记录。"""
    identity = platform_identity.get()
    return table.c.owner_uid == identity.uid if identity and not identity.superadmin else text("1=1")


def _writable(table):
    """写入限定真实所有者；超级管理员可以管理全局记录。"""

    identity = platform_identity.get()
    return table.c.owner_uid == identity.uid if identity and not identity.superadmin else text("1=1")


def _fingerprint(query: str, owner_uid: str | None = None) -> str:
    """不同用户允许拥有相同 Query，旧库指纹保持兼容。"""
    owner = _owner_uid() if owner_uid is None else owner_uid
    raw = query_fingerprint(query)
    return hashlib.sha256(f"{owner}:{raw}".encode()).hexdigest() if owner else raw


class QueryLibraryRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self._lock = Lock()
        # 在旧库建索引之前补齐列；已有数据保持无归属，不以首次访问者认领。
        for table in (query_items, generation_jobs):
            inspector = inspect(engine)
            exists = inspector.has_table(table.name)
            has_owner = exists and "owner_uid" in {
                column["name"] for column in inspector.get_columns(table.name)
            }
            if exists and not has_owner:
                with engine.begin() as connection:
                    connection.execute(
                        text(f"ALTER TABLE {table.name} ADD COLUMN owner_uid VARCHAR(128) NOT NULL DEFAULT ''")
                    )
        metadata.create_all(engine)
        self._ensure_knowledge_scope_columns("query_library_items")
        self._ensure_knowledge_scope_columns("query_generation_jobs")
        self._ensure_generation_reference_urls_column()
        self._ensure_generation_model_config_column()

    def _ensure_knowledge_scope_columns(self, table_name: str) -> None:
        """Add scope metadata without changing the meaning of legacy rows."""

        columns = {
            item["name"] for item in inspect(self.engine).get_columns(table_name)
        }
        additions = {
            "knowledge_enabled": (
                f"ALTER TABLE {table_name} "
                "ADD COLUMN knowledge_enabled INTEGER NOT NULL DEFAULT 1"
            ),
            "knowledge_ids": (
                f"ALTER TABLE {table_name} ADD COLUMN knowledge_ids TEXT NULL"
            ),
        }
        for column_name, statement in additions.items():
            if column_name in columns:
                continue
            with self.engine.begin() as connection:
                connection.execute(text(statement))

    def _ensure_generation_reference_urls_column(self) -> None:
        columns = {
            item["name"]
            for item in inspect(self.engine).get_columns("query_generation_jobs")
        }
        if "reference_urls" in columns:
            return
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE query_generation_jobs "
                    "ADD COLUMN reference_urls TEXT NOT NULL DEFAULT '[]'"
                )
            )

    def _ensure_generation_model_config_column(self) -> None:
        columns = {
            item["name"]
            for item in inspect(self.engine).get_columns("query_generation_jobs")
        }
        if "model_config" in columns:
            return
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE query_generation_jobs "
                    "ADD COLUMN model_config TEXT NOT NULL DEFAULT '{}'"
                )
            )

    def create_query(
        self,
        *,
        query: str,
        supplemental_information: str,
        generation_rationale: str,
        source_references: tuple[SourceReference, ...],
        status: str = "draft",
        source_type: str = "manual",
        generation_id: str = "",
        query_id: str | None = None,
        knowledge_enabled: bool = True,
        knowledge_ids: tuple[str, ...] | list[str] | None = None,
    ) -> QueryRecord:
        timestamp = now_iso()
        values = {
            "query_id": query_id or new_id("query"),
            "owner_uid": _owner_uid(),
            "query": query.strip(),
            "query_fingerprint": _fingerprint(query),
            "supplemental_information": supplemental_information.strip(),
            "generation_rationale": generation_rationale.strip(),
            "source_references": _dump_sources(source_references),
            "status": status,
            "source_type": source_type,
            "generation_id": generation_id,
            "knowledge_enabled": int(bool(knowledge_enabled)),
            "knowledge_ids": _dump_knowledge_ids(knowledge_ids),
            "version": 1,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        try:
            with self._lock, self.engine.begin() as connection:
                connection.execute(query_items.insert().values(**values))
        except IntegrityError as exc:
            raise DuplicateQueryError("an exact Query already exists") from exc
        return self.get_query(str(values["query_id"]))

    def get_query(self, query_id: str) -> QueryRecord:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(query_items).where(query_items.c.query_id == query_id, _owned(query_items))
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise QueryNotFoundError(f"Query not found: {query_id}")
        return _row_to_query(row)

    def find_query_by_text(self, query: str) -> QueryRecord | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(query_items).where(
                        query_items.c.query_fingerprint == _fingerprint(query)
                    )
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else _row_to_query(row)

    def list_queries(
        self,
        *,
        status: str | None = None,
        source_type: str | None = None,
        search: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[QueryRecord], int]:
        conditions = [_owned(query_items)]
        if status:
            conditions.append(query_items.c.status == status)
        if source_type:
            conditions.append(query_items.c.source_type == source_type)
        if search.strip():
            pattern = f"%{search.strip()}%"
            conditions.append(
                or_(
                    query_items.c.query.like(pattern),
                    query_items.c.supplemental_information.like(pattern),
                    query_items.c.generation_rationale.like(pattern),
                )
            )
        where = and_(*conditions) if conditions else None
        statement = select(query_items)
        count_statement = select(func.count()).select_from(query_items)
        if where is not None:
            statement = statement.where(where)
            count_statement = count_statement.where(where)
        statement = (
            statement.order_by(query_items.c.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
            total = int(connection.execute(count_statement).scalar_one())
        return [_row_to_query(row) for row in rows], total

    def update_query(
        self,
        query_id: str,
        *,
        expected_version: int,
        query: str | None = None,
        supplemental_information: str | None = None,
        generation_rationale: str | None = None,
        source_references: tuple[SourceReference, ...] | None = None,
        knowledge_enabled: bool | None = None,
        knowledge_ids: tuple[str, ...] | list[str] | None = None,
        knowledge_ids_present: bool = False,
        change_type: str = "edited",
    ) -> QueryRecord:
        with self._lock, self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(query_items).where(query_items.c.query_id == query_id, _writable(query_items))
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise QueryNotFoundError(f"Query not found: {query_id}")
            if int(row["version"]) != expected_version:
                raise VersionConflictError(
                    f"expected version {expected_version}, current version is {row['version']}"
                )
            connection.execute(
                query_revisions.insert().values(
                    query_id=query_id,
                    version=int(row["version"]),
                    change_type=change_type,
                    snapshot=json.dumps(
                        _query_snapshot(row), ensure_ascii=False, sort_keys=True
                    ),
                    changed_at=now_iso(),
                )
            )
            values: dict[str, Any] = {
                "version": int(row["version"]) + 1,
                "updated_at": now_iso(),
            }
            if query is not None:
                values["query"] = query.strip()
                values["query_fingerprint"] = _fingerprint(query, str(row["owner_uid"]))
            if supplemental_information is not None:
                values["supplemental_information"] = supplemental_information.strip()
            if generation_rationale is not None:
                values["generation_rationale"] = generation_rationale.strip()
            if source_references is not None:
                values["source_references"] = _dump_sources(source_references)
            if knowledge_enabled is not None:
                values["knowledge_enabled"] = int(bool(knowledge_enabled))
            if knowledge_ids_present:
                values["knowledge_ids"] = _dump_knowledge_ids(knowledge_ids)
            try:
                connection.execute(
                    update(query_items)
                    .where(
                        query_items.c.query_id == query_id,
                        query_items.c.version == expected_version,
                        _writable(query_items),
                    )
                    .values(**values)
                )
            except IntegrityError as exc:
                raise DuplicateQueryError("an exact Query already exists") from exc
        return self.get_query(query_id)

    def set_query_status(
        self,
        query_id: str,
        *,
        status: str,
        expected_version: int | None = None,
    ) -> QueryRecord:
        current = self.get_query(query_id)
        version = current.version if expected_version is None else expected_version
        if status not in {"draft", "published", "archived"}:
            raise InvalidStatusTransition(f"unsupported Query status: {status}")
        with self._lock, self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(query_items).where(query_items.c.query_id == query_id, _writable(query_items))
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise QueryNotFoundError(f"Query not found: {query_id}")
            if int(row["version"]) != version:
                raise VersionConflictError(
                    f"expected version {version}, current version is {row['version']}"
                )
            connection.execute(
                query_revisions.insert().values(
                    query_id=query_id,
                    version=int(row["version"]),
                    change_type=f"status:{row['status']}->{status}",
                    snapshot=json.dumps(
                        _query_snapshot(row), ensure_ascii=False, sort_keys=True
                    ),
                    changed_at=now_iso(),
                )
            )
            connection.execute(
                update(query_items)
                .where(
                    query_items.c.query_id == query_id,
                    query_items.c.version == version,
                    _writable(query_items),
                )
                .values(status=status, version=version + 1, updated_at=now_iso())
            )
        return self.get_query(query_id)

    def delete_query(self, query_id: str) -> None:
        """Permanently remove one Query and detach it from generation results."""
        with self._lock, self.engine.begin() as connection:
            existing = connection.execute(
                select(query_items.c.query_id).where(
                    query_items.c.query_id == query_id, _writable(query_items)
                )
            ).scalar_one_or_none()
            if existing is None:
                raise QueryNotFoundError(f"Query not found: {query_id}")

            connection.execute(
                delete(query_revisions).where(query_revisions.c.query_id == query_id)
            )
            connection.execute(
                delete(query_items).where(query_items.c.query_id == query_id, _writable(query_items))
            )

            # Generation jobs keep result IDs as a JSON array. Keep the task
            # record usable after a result is deleted from the library.
            rows = connection.execute(
                select(
                    generation_jobs.c.generation_id,
                    generation_jobs.c.result_query_ids,
                )
            ).mappings().all()
            for row in rows:
                ids = json.loads(row["result_query_ids"] or "[]")
                if query_id not in ids:
                    continue
                connection.execute(
                    update(generation_jobs)
                    .where(
                        generation_jobs.c.generation_id
                        == row["generation_id"]
                    )
                    .values(
                        result_query_ids=json.dumps(
                            [item for item in ids if item != query_id],
                            ensure_ascii=False,
                        ),
                        updated_at=now_iso(),
                    )
                )

    def list_revisions(self, query_id: str) -> list[QueryRevision]:
        self.get_query(query_id)
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    select(query_revisions)
                    .where(query_revisions.c.query_id == query_id)
                    .order_by(query_revisions.c.revision_id.desc())
                )
                .mappings()
                .all()
            )
        return [
            QueryRevision(
                revision_id=int(row["revision_id"]),
                query_id=str(row["query_id"]),
                version=int(row["version"]),
                change_type=str(row["change_type"]),
                snapshot=json.loads(row["snapshot"]),
                changed_at=str(row["changed_at"]),
            )
            for row in rows
        ]

    def existing_query_texts(self) -> list[str]:
        with self.engine.connect() as connection:
            return [
                str(value)
                for value in connection.execute(select(query_items.c.query).where(_owned(query_items))).scalars()
            ]

    def create_provider_credential(self, encrypted_secret: str) -> str:
        credential_id = new_id("credential")
        with self.engine.begin() as connection:
            connection.execute(
                provider_credentials.insert().values(
                    credential_id=credential_id,
                    encrypted_secret=encrypted_secret,
                    created_at=now_iso(),
                )
            )
        return credential_id

    def get_provider_credential(self, credential_id: str) -> str:
        with self.engine.connect() as connection:
            value = connection.execute(
                select(provider_credentials.c.encrypted_secret).where(
                    provider_credentials.c.credential_id == credential_id
                )
            ).scalar_one_or_none()
        if value is None:
            raise ValueError("provider credential is unavailable")
        return str(value)

    def create_generation(
        self,
        *,
        topic: str,
        supplemental_information: str,
        reference_urls: tuple[str, ...],
        model_config: dict[str, Any],
        requested_count: int,
        idempotency_key: str = "",
        knowledge_enabled: bool = True,
        knowledge_ids: tuple[str, ...] | list[str] | None = None,
    ) -> GenerationJob:
        normalized_key = idempotency_key.strip() or None
        if normalized_key and _owner_uid():
            normalized_key = hashlib.sha256(f"{_owner_uid()}:{normalized_key}".encode()).hexdigest()
        if normalized_key:
            with self.engine.connect() as connection:
                existing = (
                    connection.execute(
                        select(generation_jobs).where(
                            generation_jobs.c.idempotency_key == normalized_key
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
            if existing is not None:
                return _row_to_generation(existing)
        timestamp = now_iso()
        values = {
            "generation_id": new_id("generation"),
            "owner_uid": _owner_uid(),
            "idempotency_key": normalized_key,
            "topic": topic.strip(),
            "supplemental_information": supplemental_information.strip(),
            "reference_urls": json.dumps(list(reference_urls), ensure_ascii=False),
            "model_config": json.dumps(
                model_config, ensure_ascii=False, sort_keys=True
            ),
            "knowledge_enabled": int(bool(knowledge_enabled)),
            "knowledge_ids": _dump_knowledge_ids(knowledge_ids),
            "requested_count": requested_count,
            "status": "queued",
            "stage": "queued",
            "search_queries": "[]",
            "source_references": "[]",
            "result_query_ids": "[]",
            "error": "",
            "provider_snapshot": "{}",
            "attempts": 0,
            "lease_owner": "",
            "lease_expires_at": "",
            "created_at": timestamp,
            "updated_at": timestamp,
            "started_at": "",
            "completed_at": "",
        }
        try:
            with self._lock, self.engine.begin() as connection:
                connection.execute(generation_jobs.insert().values(**values))
        except IntegrityError:
            if not normalized_key:
                raise
            with self.engine.connect() as connection:
                row = (
                    connection.execute(
                        select(generation_jobs).where(
                            generation_jobs.c.idempotency_key == normalized_key
                        )
                    )
                    .mappings()
                    .one()
                )
            return _row_to_generation(row)
        return self.get_generation(str(values["generation_id"]))

    def get_generation(self, generation_id: str) -> GenerationJob:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(generation_jobs).where(
                        generation_jobs.c.generation_id == generation_id, _owned(generation_jobs)
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise GenerationNotFoundError(f"generation not found: {generation_id}")
        return _row_to_generation(row)

    def list_generations(
        self,
        *,
        status: str | None = None,
        limit: int = 20,
    ) -> list[GenerationJob]:
        statement = select(generation_jobs).where(_owned(generation_jobs))
        if status:
            statement = statement.where(generation_jobs.c.status == status)
        statement = statement.order_by(generation_jobs.c.created_at.desc()).limit(limit)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [_row_to_generation(row) for row in rows]

    def delete_generation(self, generation_id: str) -> None:
        with self._lock, self.engine.begin() as connection:
            row = connection.execute(
                select(generation_jobs.c.status).where(
                    generation_jobs.c.generation_id == generation_id, _writable(generation_jobs)
                )
            ).one_or_none()
            if row is None:
                raise GenerationNotFoundError(f"generation not found: {generation_id}")
            if str(row[0]) in {"queued", "running"}:
                raise InvalidStatusTransition(
                    "active Query generation tasks cannot be deleted"
                )
            connection.execute(
                delete(generation_jobs).where(
                    generation_jobs.c.generation_id == generation_id, _writable(generation_jobs)
                )
            )

    def cancel_generation(self, generation_id: str) -> GenerationJob:
        timestamp = now_iso()
        with self._lock, self.engine.begin() as connection:
            row = connection.execute(
                select(generation_jobs.c.status).where(
                    generation_jobs.c.generation_id == generation_id, _writable(generation_jobs)
                )
            ).one_or_none()
            if row is None:
                raise GenerationNotFoundError(f"generation not found: {generation_id}")
            if str(row[0]) not in {"queued", "running"}:
                raise InvalidStatusTransition(
                    "only queued or running Query generation tasks can be cancelled"
                )
            connection.execute(
                update(generation_jobs)
                .where(
                    generation_jobs.c.generation_id == generation_id,
                    generation_jobs.c.status.in_(("queued", "running")),
                    _writable(generation_jobs),
                )
                .values(
                    status="cancelled",
                    stage="cancelled",
                    error="用户已终止该 Query 发散任务。",
                    lease_owner="",
                    lease_expires_at="",
                    completed_at=timestamp,
                    updated_at=timestamp,
                )
            )
        return self.get_generation(generation_id)

    def claim_next_generation(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 21600,
    ) -> GenerationJob | None:
        self._requeue_stale_generations()
        with self._lock, self.engine.begin() as connection:
            generation_id = connection.execute(
                select(generation_jobs.c.generation_id)
                .where(generation_jobs.c.status == "queued")
                .order_by(generation_jobs.c.created_at)
                .limit(1)
            ).scalar_one_or_none()
            if generation_id is None:
                return None
            timestamp = now_iso()
            result = connection.execute(
                update(generation_jobs)
                .where(
                    generation_jobs.c.generation_id == generation_id,
                    generation_jobs.c.status == "queued",
                )
                .values(
                    status="running",
                    stage="web_validation",
                    attempts=generation_jobs.c.attempts + 1,
                    lease_owner=worker_id,
                    lease_expires_at=_future_iso(lease_seconds),
                    started_at=timestamp,
                    completed_at="",
                    error="",
                    updated_at=timestamp,
                )
            )
            if result.rowcount != 1:
                return None
        return self.get_generation(str(generation_id))

    def claim_generation(
        self,
        generation_id: str,
        *,
        worker_id: str,
        lease_seconds: int = 21600,
    ) -> GenerationJob:
        self._requeue_stale_generations()
        with self._lock, self.engine.begin() as connection:
            row = (
                connection.execute(
                    select(generation_jobs).where(
                        generation_jobs.c.generation_id == generation_id, _owned(generation_jobs)
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise GenerationNotFoundError(f"generation not found: {generation_id}")
            if row["status"] != "queued":
                return _row_to_generation(row)
            timestamp = now_iso()
            connection.execute(
                update(generation_jobs)
                .where(
                    generation_jobs.c.generation_id == generation_id,
                    generation_jobs.c.status == "queued",
                )
                .values(
                    status="running",
                    stage="web_validation",
                    attempts=int(row["attempts"]) + 1,
                    lease_owner=worker_id,
                    lease_expires_at=_future_iso(lease_seconds),
                    started_at=timestamp,
                    completed_at="",
                    error="",
                    updated_at=timestamp,
                )
            )
        return self.get_generation(generation_id)

    def update_generation_stage(self, generation_id: str, stage: str) -> None:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(generation_jobs)
                .where(
                    generation_jobs.c.generation_id == generation_id,
                    generation_jobs.c.status == "running",
                )
                .values(stage=stage, updated_at=now_iso())
            )
        if result.rowcount != 1:
            raise GenerationNotFoundError(
                f"running generation not found: {generation_id}"
            )

    def complete_generation(
        self,
        generation_id: str,
        *,
        candidates: tuple[GeneratedCandidate, ...],
        search_queries: tuple[str, ...],
        source_references: tuple[SourceReference, ...],
        provider_snapshot: dict[str, Any],
    ) -> GenerationJob:
        timestamp = now_iso()
        query_ids: list[str] = []
        try:
            with self._lock, self.engine.begin() as connection:
                job = (
                    connection.execute(
                        select(generation_jobs).where(
                            generation_jobs.c.generation_id == generation_id, _owned(generation_jobs)
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if job is None or job["status"] != "running":
                    raise GenerationNotFoundError(
                        f"running generation not found: {generation_id}"
                    )
                for candidate in candidates:
                    query_id = new_id("query")
                    query_ids.append(query_id)
                    connection.execute(
                        query_items.insert().values(
                            query_id=query_id,
                            query=candidate.query,
                            query_fingerprint=_fingerprint(candidate.query, str(job["owner_uid"])),
                            owner_uid=str(job["owner_uid"]),
                            supplemental_information=candidate.supplemental_information,
                            generation_rationale=candidate.generation_rationale,
                            source_references=_dump_sources(
                                candidate.source_references
                            ),
                            status="draft",
                            source_type="agent",
                            generation_id=generation_id,
                            knowledge_enabled=int(bool(job["knowledge_enabled"])),
                            knowledge_ids=job["knowledge_ids"],
                            version=1,
                            created_at=timestamp,
                            updated_at=timestamp,
                        )
                    )
                connection.execute(
                    update(generation_jobs)
                    .where(generation_jobs.c.generation_id == generation_id)
                    .values(
                        status="completed",
                        stage="completed",
                        search_queries=json.dumps(
                            list(search_queries), ensure_ascii=False
                        ),
                        source_references=_dump_sources(source_references),
                        result_query_ids=json.dumps(query_ids, ensure_ascii=False),
                        error="",
                        provider_snapshot=json.dumps(
                            provider_snapshot, ensure_ascii=False, sort_keys=True
                        ),
                        lease_owner="",
                        lease_expires_at="",
                        completed_at=timestamp,
                        updated_at=timestamp,
                    )
                )
        except IntegrityError as exc:
            raise DuplicateQueryError(
                "generated batch conflicts with an existing exact Query"
            ) from exc
        return self.get_generation(generation_id)

    def fail_generation(
        self,
        generation_id: str,
        *,
        error: str,
        provider_snapshot: dict[str, Any] | None = None,
    ) -> GenerationJob:
        timestamp = now_iso()
        with self.engine.begin() as connection:
            result = connection.execute(
                update(generation_jobs)
                .where(
                    generation_jobs.c.generation_id == generation_id,
                    generation_jobs.c.status != "cancelled",
                )
                .values(
                    status="failed",
                    stage="failed",
                    error=error[:8000],
                    provider_snapshot=json.dumps(
                        provider_snapshot or {}, ensure_ascii=False, sort_keys=True
                    ),
                    lease_owner="",
                    lease_expires_at="",
                    completed_at=timestamp,
                    updated_at=timestamp,
                )
            )
        if result.rowcount != 1:
            current = self.get_generation(generation_id)
            if current.status == "cancelled":
                return current
            raise GenerationNotFoundError(f"generation not found: {generation_id}")
        return self.get_generation(generation_id)

    def retry_generation(self, generation_id: str) -> GenerationJob:
        with self._lock, self.engine.begin() as connection:
            status = connection.execute(
                select(generation_jobs.c.status).where(
                    generation_jobs.c.generation_id == generation_id,
                    _writable(generation_jobs),
                )
            ).scalar_one_or_none()
            if status is None:
                raise GenerationNotFoundError(f"generation not found: {generation_id}")
            if status != "failed":
                raise InvalidStatusTransition("only failed generation jobs can be retried")
            result = connection.execute(
                update(generation_jobs)
                .where(
                    generation_jobs.c.generation_id == generation_id,
                    generation_jobs.c.status == "failed",
                    _writable(generation_jobs),
                )
                .values(
                    status="queued",
                    stage="queued",
                    error="",
                    search_queries="[]",
                    source_references="[]",
                    result_query_ids="[]",
                    provider_snapshot="{}",
                    lease_owner="",
                    lease_expires_at="",
                    started_at="",
                    completed_at="",
                    updated_at=now_iso(),
                )
            )
            if result.rowcount != 1:
                raise GenerationNotFoundError(f"generation not found: {generation_id}")
        return self.get_generation(generation_id)

    def import_seed_records(
        self,
        *,
        source_name: str,
        source_fingerprint: str,
        records: list[dict[str, Any]],
    ) -> dict[str, Any]:
        with self.engine.connect() as connection:
            existing = (
                connection.execute(
                    select(seed_imports).where(
                        seed_imports.c.source_name == source_name,
                        seed_imports.c.source_fingerprint == source_fingerprint,
                    )
                )
                .mappings()
                .one_or_none()
            )
        if existing is not None:
            return {
                "source_name": source_name,
                "source_fingerprint": source_fingerprint,
                "imported_count": 0,
                "existing_count": int(existing["imported_count"]),
                "already_imported": True,
            }

        timestamp = now_iso()
        imported = 0
        with self._lock, self.engine.begin() as connection:
            for record in records:
                query = str(record["query"]).strip()
                fingerprint = query_fingerprint(query)
                duplicate = connection.execute(
                    select(query_items.c.query_id).where(
                        query_items.c.query_fingerprint == fingerprint
                    )
                ).scalar_one_or_none()
                if duplicate is not None:
                    continue
                references = tuple(
                    SourceReference.from_dict(item)
                    for item in record.get("source_references", [])
                    if isinstance(item, dict)
                )
                connection.execute(
                    query_items.insert().values(
                        query_id=new_id("query"),
                        query=query,
                        query_fingerprint=fingerprint,
                        supplemental_information=str(
                            record.get("supplemental_information", "")
                        ).strip(),
                        generation_rationale=str(
                            record.get("generation_rationale", "")
                        ).strip(),
                        source_references=_dump_sources(references),
                        status="draft",
                        source_type="import",
                        generation_id="",
                        knowledge_enabled=int(
                            bool(record.get("knowledge_enabled", True))
                        ),
                        knowledge_ids=_dump_knowledge_ids(
                            record.get("knowledge_ids")
                        ),
                        version=1,
                        created_at=timestamp,
                        updated_at=timestamp,
                    )
                )
                imported += 1
            connection.execute(
                seed_imports.insert().values(
                    source_name=source_name,
                    source_fingerprint=source_fingerprint,
                    imported_count=imported,
                    imported_at=timestamp,
                )
            )
        return {
            "source_name": source_name,
            "source_fingerprint": source_fingerprint,
            "imported_count": imported,
            "existing_count": 0,
            "already_imported": False,
        }

    def seed_import_exists(self, *, source_name: str, source_fingerprint: str) -> bool:
        with self.engine.connect() as connection:
            return (
                connection.execute(
                    select(seed_imports.c.source_name).where(
                        seed_imports.c.source_name == source_name,
                        seed_imports.c.source_fingerprint == source_fingerprint,
                    )
                ).scalar_one_or_none()
                is not None
            )

    def archive_imported_queries(self) -> int:
        timestamp = now_iso()
        with self._lock, self.engine.begin() as connection:
            rows = (
                connection.execute(
                    select(query_items).where(
                        query_items.c.source_type == "import",
                        query_items.c.status != "archived",
                    )
                )
                .mappings()
                .all()
            )
            for row in rows:
                connection.execute(
                    query_revisions.insert().values(
                        query_id=str(row["query_id"]),
                        version=int(row["version"]),
                        change_type="seed-migration:archived",
                        snapshot=json.dumps(
                            _query_snapshot(row), ensure_ascii=False, sort_keys=True
                        ),
                        changed_at=timestamp,
                    )
                )
                connection.execute(
                    update(query_items)
                    .where(query_items.c.query_id == row["query_id"])
                    .values(
                        status="archived",
                        version=int(row["version"]) + 1,
                        updated_at=timestamp,
                    )
                )
        return len(rows)

    def _requeue_stale_generations(self) -> None:
        timestamp = now_iso()
        with self.engine.begin() as connection:
            connection.execute(
                update(generation_jobs)
                .where(
                    generation_jobs.c.status == "running",
                    generation_jobs.c.lease_expires_at != "",
                    generation_jobs.c.lease_expires_at < timestamp,
                )
                .values(
                    status="queued",
                    stage="queued",
                    error="worker lease expired; generation requeued",
                    lease_owner="",
                    lease_expires_at="",
                    updated_at=timestamp,
                )
            )


def _row_to_query(row: Any) -> QueryRecord:
    return QueryRecord(
        owner_uid=str(row["owner_uid"]),
        query_id=str(row["query_id"]),
        query=str(row["query"]),
        supplemental_information=str(row["supplemental_information"]),
        generation_rationale=str(row["generation_rationale"]),
        source_references=_load_sources(row["source_references"]),
        status=str(row["status"]),  # type: ignore[arg-type]
        source_type=str(row["source_type"]),  # type: ignore[arg-type]
        generation_id=str(row["generation_id"]),
        version=int(row["version"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        knowledge_enabled=bool(row["knowledge_enabled"]),
        knowledge_ids=_load_knowledge_ids(row["knowledge_ids"]),
    )


def _row_to_generation(row: Any) -> GenerationJob:
    return GenerationJob(
        owner_uid=str(row["owner_uid"]),
        generation_id=str(row["generation_id"]),
        topic=str(row["topic"]),
        supplemental_information=str(row["supplemental_information"]),
        reference_urls=tuple(json.loads(row["reference_urls"] or "[]")),
        model_config=json.loads(row["model_config"] or "{}"),
        requested_count=int(row["requested_count"]),
        status=str(row["status"]),  # type: ignore[arg-type]
        stage=str(row["stage"]),
        search_queries=tuple(json.loads(row["search_queries"] or "[]")),
        source_references=_load_sources(row["source_references"]),
        result_query_ids=tuple(json.loads(row["result_query_ids"] or "[]")),
        error=str(row["error"]),
        provider_snapshot=json.loads(row["provider_snapshot"] or "{}"),
        attempts=int(row["attempts"]),
        lease_owner=str(row["lease_owner"]),
        lease_expires_at=str(row["lease_expires_at"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        started_at=str(row["started_at"]),
        completed_at=str(row["completed_at"]),
        knowledge_enabled=bool(row["knowledge_enabled"]),
        knowledge_ids=_load_knowledge_ids(row["knowledge_ids"]),
    )


def _query_snapshot(row: Any) -> dict[str, Any]:
    return {
        "query": str(row["query"]),
        "supplemental_information": str(row["supplemental_information"]),
        "generation_rationale": str(row["generation_rationale"]),
        "source_references": json.loads(row["source_references"] or "[]"),
        "status": str(row["status"]),
        "source_type": str(row["source_type"]),
        "generation_id": str(row["generation_id"]),
        "knowledge_enabled": bool(row["knowledge_enabled"]),
        "knowledge_ids": (
            None
            if row["knowledge_ids"] is None
            else list(_load_knowledge_ids(row["knowledge_ids"]) or ())
        ),
        "version": int(row["version"]),
    }


def _dump_sources(values: tuple[SourceReference, ...]) -> str:
    return json.dumps(
        [item.to_dict() for item in values], ensure_ascii=False, sort_keys=True
    )


def _load_sources(value: str) -> tuple[SourceReference, ...]:
    rows = json.loads(value or "[]")
    return tuple(
        SourceReference.from_dict(item) for item in rows if isinstance(item, dict)
    )


def _dump_knowledge_ids(value: Any) -> str | None:
    normalized = normalize_knowledge_ids(value)
    if normalized is None:
        return None
    return json.dumps(list(normalized), ensure_ascii=False)


def _load_knowledge_ids(value: Any) -> tuple[str, ...] | None:
    if value is None:
        return None
    try:
        decoded = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        # Corrupt historical scope must fail closed rather than broaden to all.
        return ()
    try:
        return normalize_knowledge_ids(decoded)
    except ValueError:
        return ()


def _future_iso(seconds: int) -> str:
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat()
