from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import re
import shutil
import stat
from typing import Any

from equipment_deep_research.query_library.models import (
    DuplicateQueryError,
    GenerationArtifactCleanupError,
    GenerationJob,
    InvalidStatusTransition,
    QueryRecord,
    SourceReference,
)
from equipment_deep_research.query_library.persistence import QueryLibraryRepository
from equipment_deep_research.query_library.quality import (
    coverage_plan,
    dedupe_sources,
    sanitize_reference_urls,
)


class QueryLibraryService:
    def __init__(
        self,
        repository: QueryLibraryRepository,
        *,
        generator: object | None = None,
        generator_factory: Callable[[dict[str, Any]], object] | None = None,
        model_options: dict[str, Any] | None = None,
        credential_store: object | None = None,
        artifact_root: str | Path | None = None,
    ) -> None:
        self.repository = repository
        self.generator = generator
        self.generator_factory = generator_factory
        self.model_options = dict(model_options or {})
        self.credential_store = credential_store
        self.artifact_root = (
            None if artifact_root is None else Path(artifact_root).resolve()
        )

    def create_query(
        self,
        *,
        query: str,
        supplemental_information: str = "",
        generation_rationale: str = "",
        source_references: list[SourceReference] | tuple[SourceReference, ...] = (),
        status: str = "draft",
    ) -> QueryRecord:
        _validate_query_input(query, supplemental_information, generation_rationale)
        if status not in {"draft", "published"}:
            raise ValueError("manual Query status must be draft or published")
        return self.repository.create_query(
            query=query,
            supplemental_information=supplemental_information,
            generation_rationale=generation_rationale,
            source_references=dedupe_sources(list(source_references), limit=20),
            status=status,
            source_type="manual",
        )

    def import_records(
        self,
        records: list[dict[str, Any]],
        *,
        source_name: str,
        status: str = "published",
    ) -> dict[str, Any]:
        if status not in {"draft", "published"}:
            raise ValueError("imported Query status must be draft or published")
        if not records:
            raise ValueError("no Query records found")
        if len(records) > 500:
            raise ValueError("one import may contain at most 500 Query records")
        imported: list[dict[str, Any]] = []
        promoted: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for index, record in enumerate(records, start=1):
            row_number = int(record.get("source_row", index) or index)
            try:
                query = str(record.get("query", ""))
                supplement = str(record.get("supplemental_information", ""))
                rationale = str(record.get("generation_rationale", ""))
                _validate_query_input(query, supplement, rationale)
                references = dedupe_sources(
                    [
                        SourceReference.from_dict(item)
                        for item in record.get("source_references", [])
                        if isinstance(item, dict)
                    ],
                    limit=20,
                )
                saved = self.repository.create_query(
                    query=query,
                    supplemental_information=supplement,
                    generation_rationale=rationale,
                    source_references=references,
                    status=status,
                    source_type="import",
                )
                imported.append(saved.to_dict())
            except DuplicateQueryError:
                current = self.repository.find_query_by_text(query)
                if (
                    current is not None
                    and current.status == "draft"
                    and status == "published"
                ):
                    published = self.repository.set_query_status(
                        current.query_id,
                        status="published",
                        expected_version=current.version,
                    )
                    promoted.append(published.to_dict())
                else:
                    skipped.append(
                        {
                            "row": row_number,
                            "reason": "duplicate",
                            "query": str(record.get("query", "")),
                        }
                    )
            except (TypeError, ValueError) as exc:
                errors.append(
                    {
                        "row": row_number,
                        "reason": str(exc),
                        "query": str(record.get("query", "")),
                    }
                )
        return {
            "source_name": source_name,
            "imported_count": len(imported),
            "promoted_count": len(promoted),
            "skipped_count": len(skipped),
            "invalid_count": len(errors),
            "items": [*imported, *promoted],
            "skipped": skipped,
            "errors": errors,
        }

    def get_query(
        self, query_id: str, *, include_revisions: bool = False
    ) -> dict[str, Any]:
        record = self.repository.get_query(query_id)
        payload = record.to_dict()
        if include_revisions:
            payload["revisions"] = [
                item.to_dict() for item in self.repository.list_revisions(query_id)
            ]
        return payload

    def list_queries(
        self,
        *,
        status: str | None = None,
        source_type: str | None = None,
        search: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        rows, total = self.repository.list_queries(
            status=status,
            source_type=source_type,
            search=search,
            limit=limit,
            offset=offset,
        )
        return {
            "items": [item.to_dict() for item in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def update_query(
        self,
        query_id: str,
        *,
        expected_version: int,
        query: str | None = None,
        supplemental_information: str | None = None,
        generation_rationale: str | None = None,
        source_references: list[SourceReference] | None = None,
    ) -> QueryRecord:
        current = self.repository.get_query(query_id)
        _validate_query_input(
            query if query is not None else current.query,
            (
                supplemental_information
                if supplemental_information is not None
                else current.supplemental_information
            ),
            (
                generation_rationale
                if generation_rationale is not None
                else current.generation_rationale
            ),
        )
        sanitized = (
            None
            if source_references is None
            else dedupe_sources(source_references, limit=20)
        )
        return self.repository.update_query(
            query_id,
            expected_version=expected_version,
            query=query,
            supplemental_information=supplemental_information,
            generation_rationale=generation_rationale,
            source_references=sanitized,
        )

    def set_status(
        self,
        query_id: str,
        *,
        status: str,
        expected_version: int | None = None,
    ) -> QueryRecord:
        return self.repository.set_query_status(
            query_id,
            status=status,
            expected_version=expected_version,
        )

    def delete_query(self, query_id: str) -> None:
        self.repository.delete_query(query_id)

    def bulk_status(
        self,
        query_ids: list[str],
        *,
        status: str,
        versions: Mapping[str, int] | None = None,
    ) -> list[QueryRecord]:
        unique_ids = list(
            dict.fromkeys(item.strip() for item in query_ids if item.strip())
        )
        if not unique_ids:
            raise ValueError("at least one query_id is required")
        return [
            self.set_status(
                query_id,
                status=status,
                expected_version=(versions or {}).get(query_id),
            )
            for query_id in unique_ids
        ]

    def submit_generation(
        self,
        *,
        topic: str,
        supplemental_information: str = "",
        reference_urls: list[str] | tuple[str, ...] = (),
        model_config: Mapping[str, Any] | None = None,
        count: int = 12,
        idempotency_key: str = "",
    ) -> GenerationJob:
        topic = topic.strip()
        if not topic:
            raise ValueError("topic is required")
        if len(topic) > 500:
            raise ValueError("topic exceeds 500 characters")
        if len(supplemental_information) > 8000:
            raise ValueError("supplemental_information exceeds 8000 characters")
        sanitized_urls = sanitize_reference_urls(reference_urls)
        raw_model_config = dict(model_config or {})
        api_key = str(raw_model_config.pop("api_key", "")).strip()
        sanitized_model_config = _validate_model_config(raw_model_config)
        if api_key:
            if self.credential_store is None:
                raise ValueError("custom API key storage is unavailable")
            sanitized_model_config["credential_id"] = self.credential_store.save(
                api_key
            )
        coverage_plan(count)
        return self.repository.create_generation(
            topic=topic,
            supplemental_information=supplemental_information,
            reference_urls=sanitized_urls,
            model_config=sanitized_model_config,
            requested_count=count,
            idempotency_key=idempotency_key,
        )

    def get_generation(self, generation_id: str) -> dict[str, Any]:
        return self.repository.get_generation(generation_id).to_dict()

    def list_generations(
        self,
        *,
        status: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        rows = self.repository.list_generations(status=status, limit=limit)
        return {"items": [item.to_dict() for item in rows], "limit": limit}

    def delete_generation(self, generation_id: str) -> None:
        current = self.repository.get_generation(generation_id)
        if current.status in {"queued", "running"}:
            raise InvalidStatusTransition(
                "active Query generation tasks cannot be deleted"
            )
        artifact_directory = self._artifact_directory(generation_id)
        if artifact_directory is not None:
            _remove_generation_artifacts(artifact_directory)
        self.repository.delete_generation(generation_id)

    def cancel_generation(self, generation_id: str) -> GenerationJob:
        return self.repository.cancel_generation(generation_id)

    def _artifact_directory(self, generation_id: str) -> Path | None:
        if self.artifact_root is None:
            return None
        match = re.fullmatch(
            r"generation-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
            generation_id,
        )
        if match is None:
            return None
        target = self.artifact_root / f"query-gen-{match.group(1)}"
        if target.parent.resolve() != self.artifact_root:
            raise ValueError("invalid Query generation artifact path")
        return target
    def get_model_options(self) -> dict[str, Any]:
        return self.model_options

    def retry_generation(self, generation_id: str) -> GenerationJob:
        return self.repository.retry_generation(generation_id)

    async def process_next(self, *, worker_id: str) -> GenerationJob | None:
        job = self.repository.claim_next_generation(worker_id=worker_id)
        if job is None:
            return None
        return await self._process_claimed(job)

    async def process_generation(
        self,
        generation_id: str,
        *,
        worker_id: str,
    ) -> GenerationJob:
        job = self.repository.claim_generation(generation_id, worker_id=worker_id)
        if job.status != "running" or job.lease_owner != worker_id:
            return job
        return await self._process_claimed(job)

    async def _process_claimed(self, job: GenerationJob) -> GenerationJob:
        generator = self.generator
        try:
            if self.generator_factory is not None:
                generator = self.generator_factory(
                    {**job.model_config, "_generation_id": job.generation_id}
                )
        except Exception as exc:
            return self.repository.fail_generation(
                job.generation_id,
                error=f"{type(exc).__name__}: {exc}",
                provider_snapshot={"requested": job.model_config},
            )
        snapshot = dict(getattr(generator, "provider_snapshot", {}) or {})
        if generator is None:
            return self.repository.fail_generation(
                job.generation_id,
                error="generation worker has no configured model provider",
                provider_snapshot=snapshot,
            )
        try:
            generation_task = asyncio.create_task(generator.generate(
                topic=job.topic,
                supplemental_information=job.supplemental_information,
                reference_urls=job.reference_urls,
                count=job.requested_count,
                existing_queries=self.repository.existing_query_texts(),
                on_stage=lambda stage: self.repository.update_generation_stage(
                    job.generation_id, stage
                ),
            ))
            while not generation_task.done():
                await asyncio.wait({generation_task}, timeout=0.5)
                if self.repository.get_generation(job.generation_id).status == "cancelled":
                    generation_task.cancel()
                    try:
                        await generation_task
                    except asyncio.CancelledError:
                        pass
                    return self.repository.get_generation(job.generation_id)
            result = await generation_task
            if self.repository.get_generation(job.generation_id).status == "cancelled":
                return self.repository.get_generation(job.generation_id)
            self.repository.update_generation_stage(job.generation_id, "persisting")
            return self.repository.complete_generation(
                job.generation_id,
                candidates=result.candidates,
                search_queries=result.search_queries,
                source_references=result.source_references,
                provider_snapshot=result.provider_snapshot,
            )
        except Exception as exc:
            current = self.repository.get_generation(job.generation_id)
            if current.status == "cancelled":
                return current
            return self.repository.fail_generation(
                job.generation_id,
                error=f"{type(exc).__name__}: {exc}",
                provider_snapshot=snapshot,
            )

    def import_seed_manifest(self, path: str | Path) -> dict[str, Any]:
        source_path = Path(path)
        payload = json.loads(source_path.read_text(encoding="utf-8"))
        sources = payload.get("sources", [])
        if not isinstance(sources, list):
            raise ValueError("seed manifest sources must be an array")
        source_versions = [
            (
                str(source.get("source_name", "")).strip(),
                str(source.get("source_fingerprint", "")).strip(),
            )
            for source in sources
            if isinstance(source, dict)
        ]
        archived_count = 0
        if payload.get("replace_imported_queries") and any(
            not self.repository.seed_import_exists(
                source_name=source_name, source_fingerprint=source_fingerprint
            )
            for source_name, source_fingerprint in source_versions
        ):
            archived_count = self.repository.archive_imported_queries()
        results: list[dict[str, Any]] = []
        for source in sources:
            if not isinstance(source, dict):
                continue
            records = source.get("records", [])
            if not isinstance(records, list):
                raise ValueError("seed source records must be an array")
            normalized_records: list[dict[str, Any]] = []
            default_source_rows = source.get("source_references", [])
            if not isinstance(default_source_rows, list):
                raise ValueError("seed source_references must be an array")
            for record in records:
                if not isinstance(record, dict):
                    continue
                _validate_query_input(
                    str(record.get("query", "")),
                    str(record.get("supplemental_information", "")),
                    str(record.get("generation_rationale", "")),
                )
                refs = dedupe_sources(
                    [
                        SourceReference.from_dict(item)
                        for item in (
                            record.get("source_references", default_source_rows)
                        )
                        if isinstance(item, dict)
                    ],
                    limit=20,
                )
                normalized_records.append(
                    {**record, "source_references": [item.to_dict() for item in refs]}
                )
            results.append(
                self.repository.import_seed_records(
                    source_name=str(source.get("source_name", "")).strip(),
                    source_fingerprint=str(
                        source.get("source_fingerprint", "")
                    ).strip(),
                    records=normalized_records,
                )
            )
        return {
            "schema_version": str(payload.get("schema_version", "1.0")),
            "sources": results,
            "imported_count": sum(item["imported_count"] for item in results),
            "archived_count": archived_count,
        }


def _remove_generation_artifacts(target: Path) -> None:
    """Remove one isolated generation home without following directory links."""

    try:
        if target.is_symlink():
            target.unlink(missing_ok=True)
            return
        shutil.rmtree(target, onerror=_repair_permissions_and_retry)
    except FileNotFoundError:
        # A previous cleanup or concurrent retry already removed the directory.
        return
    except OSError as exc:
        raise GenerationArtifactCleanupError(
            f"Query 任务本地文件清理失败：{target.name}"
        ) from exc


def _repair_permissions_and_retry(
    function: Callable[[str], None], path: str, _error: object
) -> None:
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    function(path)


def _validate_model_config(value: Mapping[str, Any]) -> dict[str, str]:
    allowed = {"provider", "model", "reasoning_effort", "base_url", "credential_id"}
    unknown = set(value) - allowed
    if unknown:
        raise ValueError(
            f"unsupported model_config fields: {', '.join(sorted(unknown))}"
        )
    provider = str(value.get("provider", "")).strip()
    model = str(value.get("model", "")).strip()
    reasoning = str(value.get("reasoning_effort", "high")).strip() or "high"
    base_url = str(value.get("base_url", "")).strip()
    credential_id = str(value.get("credential_id", "")).strip()
    # Provider IDs are deployment configuration, not a closed application
    # enum.  New CLI/API adapters can be registered in providers.yaml without
    # changing query-library validation; the factory performs the final
    # registry lookup when a generation starts.
    if provider and (
        len(provider) > 80
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", provider)
    ):
        raise ValueError("model_config.provider must be a valid configured provider id")
    if len(model) > 120:
        raise ValueError("model_config.model exceeds 120 characters")
    if reasoning not in {"low", "medium", "high", "xhigh"}:
        raise ValueError("model_config.reasoning_effort is invalid")
    if base_url:
        from urllib.parse import urlsplit

        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("model_config.base_url must be a clean HTTPS URL")
    if credential_id and not credential_id.startswith("credential-"):
        raise ValueError("model_config.credential_id is invalid")
    return {
        key: item
        for key, item in {
            "provider": provider,
            "model": model,
            "reasoning_effort": reasoning,
            "base_url": base_url,
            "credential_id": credential_id,
        }.items()
        if item
    }


def _validate_query_input(
    query: str,
    supplemental_information: str,
    generation_rationale: str,
) -> None:
    if not query.strip():
        raise ValueError("query is required")
    if len(query) > 4000:
        raise ValueError("query exceeds 4000 characters")
    if len(supplemental_information) > 8000:
        raise ValueError("supplemental_information exceeds 8000 characters")
    if len(generation_rationale) > 2000:
        raise ValueError("generation_rationale exceeds 2000 characters")
