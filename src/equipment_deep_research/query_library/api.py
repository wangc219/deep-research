from __future__ import annotations

import base64
import binascii
from typing import Literal

from fastapi import APIRouter, FastAPI, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from equipment_deep_research.query_library.factory import build_service
from equipment_deep_research.query_library.imports import (
    parse_numbered_query_text,
    parse_query_file,
)
from equipment_deep_research.query_library.models import (
    DuplicateQueryError,
    GenerationNotFoundError,
    InvalidStatusTransition,
    QueryNotFoundError,
    QueryLibraryError,
    SourceReference,
    VersionConflictError,
)
from equipment_deep_research.query_library.service import QueryLibraryService


class SourceReferenceBody(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(default="", max_length=3000)
    accessed_at: str = Field(default="", max_length=64)
    relevance_note: str = Field(default="", max_length=1000)
    source_kind: Literal["web", "document"] = "web"

    def to_domain(self) -> SourceReference:
        return SourceReference.from_dict(self.model_dump())


class CreateQueryBody(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    supplemental_information: str = Field(default="", max_length=8000)
    generation_rationale: str = Field(default="", max_length=2000)
    source_references: list[SourceReferenceBody] = Field(
        default_factory=list, max_length=20
    )
    status: Literal["draft", "published"] = "draft"


class UpdateQueryBody(BaseModel):
    expected_version: int = Field(ge=1)
    query: str | None = Field(default=None, min_length=1, max_length=4000)
    supplemental_information: str | None = Field(default=None, max_length=8000)
    generation_rationale: str | None = Field(default=None, max_length=2000)
    source_references: list[SourceReferenceBody] | None = Field(
        default=None, max_length=20
    )


class GenerationBody(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    supplemental_information: str = Field(default="", max_length=8000)
    reference_urls: list[str] = Field(default_factory=list, max_length=12)
    count: int = Field(default=12, ge=1, le=20)
    model_settings: dict[str, str] = Field(default_factory=dict, alias="model_config")


class StatusBody(BaseModel):
    expected_version: int | None = Field(default=None, ge=1)


class BulkStatusBody(BaseModel):
    query_ids: list[str] = Field(min_length=1, max_length=100)
    status: Literal["draft", "published", "archived"]
    versions: dict[str, int] = Field(default_factory=dict)


class ImportFileBody(BaseModel):
    filename: str = Field(min_length=1, max_length=300)
    content_base64: str = Field(min_length=1)
    status: Literal["draft", "published"] = "published"


class ImportTextBody(BaseModel):
    content: str = Field(min_length=1, max_length=100000)
    source_name: str = Field(default="人工导入长 Query", min_length=1, max_length=300)
    status: Literal["draft", "published"] = "published"


def create_router(service: QueryLibraryService) -> APIRouter:
    router = APIRouter(prefix="/api/v1/query-library", tags=["query-library"])

    @router.get("/health")
    def health() -> dict:
        return {"status": "ok", "module": "query-library"}

    @router.get("/model-options")
    def model_options() -> dict:
        return service.get_model_options()

    @router.post("/generations", status_code=status.HTTP_202_ACCEPTED)
    def submit_generation(
        body: GenerationBody,
        idempotency_key: str = Header(default="", alias="Idempotency-Key"),
    ) -> dict:
        try:
            return service.submit_generation(
                topic=body.topic,
                supplemental_information=body.supplemental_information,
                reference_urls=body.reference_urls,
                model_config=body.model_settings,
                count=body.count,
                idempotency_key=idempotency_key,
            ).to_dict()
        except (ValueError, QueryLibraryError) as exc:
            _raise_http(exc)

    @router.get("/generations/{generation_id}")
    def get_generation(generation_id: str) -> dict:
        try:
            return service.get_generation(generation_id)
        except QueryLibraryError as exc:
            _raise_http(exc)

    @router.delete(
        "/generations/{generation_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def delete_generation(generation_id: str) -> Response:
        try:
            service.delete_generation(generation_id)
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except QueryLibraryError as exc:
            _raise_http(exc)

    @router.post("/generations/{generation_id}/cancel")
    def cancel_generation(generation_id: str) -> dict:
        try:
            return service.cancel_generation(generation_id).to_dict()
        except QueryLibraryError as exc:
            _raise_http(exc)

    @router.get("/generations")
    def list_generations(
        generation_status: Literal["queued", "running", "completed", "failed", "cancelled"] | None = Query(
            default=None, alias="status"
        ),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> dict:
        return service.list_generations(status=generation_status, limit=limit)

    @router.post("/generations/{generation_id}/retry")
    def retry_generation(generation_id: str) -> dict:
        try:
            return service.retry_generation(generation_id).to_dict()
        except QueryLibraryError as exc:
            _raise_http(exc)

    @router.get("/queries")
    def list_queries(
        query_status: Literal["draft", "published", "archived"] | None = Query(
            default=None, alias="status"
        ),
        source_type: Literal["manual", "agent", "import"] | None = None,
        search_text: str = Query(default="", alias="search", max_length=500),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> dict:
        return service.list_queries(
            status=query_status,
            source_type=source_type,
            search=search_text,
            limit=limit,
            offset=offset,
        )

    @router.get("/queries/{query_id}")
    def get_query(query_id: str, include_revisions: bool = True) -> dict:
        try:
            return service.get_query(query_id, include_revisions=include_revisions)
        except QueryLibraryError as exc:
            _raise_http(exc)

    @router.post("/imports/file", status_code=status.HTTP_201_CREATED)
    def import_file(body: ImportFileBody) -> dict:
        try:
            content = base64.b64decode(body.content_base64, validate=True)
            if len(content) > 10 * 1024 * 1024:
                raise ValueError("Query import file exceeds 10 MB")
            records = parse_query_file(body.filename, content)
            return service.import_records(
                records,
                source_name=body.filename,
                status=body.status,
            )
        except (ValueError, binascii.Error, QueryLibraryError) as exc:
            _raise_http(exc)

    @router.post("/imports/text", status_code=status.HTTP_201_CREATED)
    def import_text(body: ImportTextBody) -> dict:
        try:
            records = parse_numbered_query_text(
                body.content,
                source_name=body.source_name,
            )
            return service.import_records(
                records,
                source_name=body.source_name,
                status=body.status,
            )
        except (ValueError, QueryLibraryError) as exc:
            _raise_http(exc)

    @router.post("/queries", status_code=status.HTTP_201_CREATED)
    def create_query(body: CreateQueryBody) -> dict:
        try:
            return service.create_query(
                query=body.query,
                supplemental_information=body.supplemental_information,
                generation_rationale=body.generation_rationale,
                source_references=[item.to_domain() for item in body.source_references],
                status=body.status,
            ).to_dict()
        except (ValueError, QueryLibraryError) as exc:
            _raise_http(exc)

    @router.patch("/queries/{query_id}")
    def update_query(query_id: str, body: UpdateQueryBody) -> dict:
        try:
            references = (
                None
                if body.source_references is None
                else [item.to_domain() for item in body.source_references]
            )
            return service.update_query(
                query_id,
                expected_version=body.expected_version,
                query=body.query,
                supplemental_information=body.supplemental_information,
                generation_rationale=body.generation_rationale,
                source_references=references,
            ).to_dict()
        except (ValueError, QueryLibraryError) as exc:
            _raise_http(exc)

    @router.post("/queries/{query_id}/publish")
    def publish_query(query_id: str, body: StatusBody) -> dict:
        try:
            return service.set_status(
                query_id,
                status="published",
                expected_version=body.expected_version,
            ).to_dict()
        except QueryLibraryError as exc:
            _raise_http(exc)

    @router.post("/queries/{query_id}/archive")
    def archive_query(query_id: str, body: StatusBody) -> dict:
        try:
            return service.set_status(
                query_id,
                status="archived",
                expected_version=body.expected_version,
            ).to_dict()
        except QueryLibraryError as exc:
            _raise_http(exc)

    @router.delete("/queries/{query_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_query(query_id: str) -> Response:
        try:
            service.delete_query(query_id)
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        except QueryLibraryError as exc:
            _raise_http(exc)

    @router.post("/queries/bulk-status")
    def bulk_status(body: BulkStatusBody) -> dict:
        try:
            rows = service.bulk_status(
                body.query_ids,
                status=body.status,
                versions=body.versions,
            )
            return {"items": [item.to_dict() for item in rows], "count": len(rows)}
        except (ValueError, QueryLibraryError) as exc:
            _raise_http(exc)

    return router


def create_app(
    service: QueryLibraryService | None = None,
    *,
    database_url: str | None = None,
) -> FastAPI:
    app = FastAPI(title="Equipment Demand Query Library API", version="0.1.0")
    app.include_router(create_router(service or build_service(database_url)))
    return app


def _raise_http(exc: Exception) -> None:
    if isinstance(exc, (QueryNotFoundError, GenerationNotFoundError)):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(
        exc,
        (DuplicateQueryError, VersionConflictError, InvalidStatusTransition),
    ):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise HTTPException(status_code=422, detail=str(exc)) from exc
