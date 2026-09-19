from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import re
from typing import Any, Literal
from uuid import uuid4


QueryStatus = Literal["draft", "published", "archived"]
QuerySourceType = Literal["manual", "agent", "import"]
GenerationStatus = Literal["queued", "running", "completed", "failed", "cancelled"]

SOURCE_DISCLAIMER = "Query 生成参考线索，不等同于后续研究结论的正式证据。"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def normalize_query(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value).lower())


def query_fingerprint(value: str) -> str:
    return sha256(normalize_query(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SourceReference:
    title: str
    url: str = ""
    accessed_at: str = field(default_factory=now_iso)
    relevance_note: str = ""
    source_kind: Literal["web", "document"] = "web"

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SourceReference":
        return cls(
            title=str(value.get("title", "")).strip(),
            url=str(value.get("url", "")).strip(),
            accessed_at=str(value.get("accessed_at", "")).strip() or now_iso(),
            relevance_note=str(value.get("relevance_note", "")).strip(),
            source_kind=(
                "document"
                if str(value.get("source_kind", "web")) == "document"
                else "web"
            ),
        )


@dataclass(frozen=True)
class QueryRecord:
    query_id: str
    query: str
    supplemental_information: str
    generation_rationale: str
    source_references: tuple[SourceReference, ...]
    status: QueryStatus
    source_type: QuerySourceType
    generation_id: str
    version: int
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "source_references": [item.to_dict() for item in self.source_references],
            "source_disclaimer": SOURCE_DISCLAIMER,
        }


@dataclass(frozen=True)
class QueryRevision:
    revision_id: int
    query_id: str
    version: int
    change_type: str
    snapshot: dict[str, Any]
    changed_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GenerationJob:
    generation_id: str
    topic: str
    supplemental_information: str
    reference_urls: tuple[str, ...]
    model_config: dict[str, Any]
    requested_count: int
    status: GenerationStatus
    stage: str
    search_queries: tuple[str, ...]
    source_references: tuple[SourceReference, ...]
    result_query_ids: tuple[str, ...]
    error: str
    provider_snapshot: dict[str, Any]
    attempts: int
    lease_owner: str
    lease_expires_at: str
    created_at: str
    updated_at: str
    started_at: str
    completed_at: str

    def to_dict(self) -> dict[str, Any]:
        public_model_config = {
            key: value
            for key, value in self.model_config.items()
            if key in {"provider", "model", "reasoning_effort", "base_url"}
        }
        public_model_config["credential_configured"] = bool(
            self.model_config.get("credential_id")
        )
        return {
            **asdict(self),
            "model_config": public_model_config,
            "reference_urls": list(self.reference_urls),
            "search_queries": list(self.search_queries),
            "source_references": [item.to_dict() for item in self.source_references],
            "result_query_ids": list(self.result_query_ids),
            "source_disclaimer": SOURCE_DISCLAIMER,
        }


@dataclass(frozen=True)
class GeneratedCandidate:
    coverage_slot: str
    query: str
    supplemental_information: str
    generation_rationale: str
    source_references: tuple[SourceReference, ...]


@dataclass(frozen=True)
class GenerationResult:
    candidates: tuple[GeneratedCandidate, ...]
    source_references: tuple[SourceReference, ...]
    provider_snapshot: dict[str, Any]
    search_queries: tuple[str, ...] = ()


class QueryLibraryError(RuntimeError):
    pass


class QueryNotFoundError(QueryLibraryError):
    pass


class GenerationNotFoundError(QueryLibraryError):
    pass


class DuplicateQueryError(QueryLibraryError):
    pass


class VersionConflictError(QueryLibraryError):
    pass


class InvalidStatusTransition(QueryLibraryError):
    pass


class GenerationValidationError(QueryLibraryError):
    pass


class GenerationArtifactCleanupError(QueryLibraryError):
    pass
