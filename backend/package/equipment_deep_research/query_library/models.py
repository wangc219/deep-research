from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
import re
from typing import Any, Literal
from uuid import uuid4


QueryStatus = Literal["draft", "published", "archived"]
QuerySourceType = Literal["manual", "agent", "import"]
GenerationStatus = Literal["queued", "running", "completed", "failed", "cancelled"]

SOURCE_DISCLAIMER = "Query 生成参考线索，不等同于后续研究结论的正式证据。"


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def normalize_query(value: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", str(value).lower())


def query_fingerprint(value: str) -> str:
    return sha256(normalize_query(value).encode("utf-8")).hexdigest()


def normalize_knowledge_ids(value: Any) -> tuple[str, ...] | None:
    """Preserve None=all visible and ()=disabled while normalizing IDs."""

    if value is None:
        return None
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise ValueError("knowledge_ids must be an array or null")
    normalized: list[str] = []
    for raw_id in value:
        if not isinstance(raw_id, str):
            raise ValueError("knowledge_ids may only contain strings")
        knowledge_id = raw_id.strip()
        if not knowledge_id or knowledge_id in normalized:
            continue
        if len(knowledge_id) > 256:
            raise ValueError("knowledge_ids item exceeds 256 characters")
        normalized.append(knowledge_id)
    if len(normalized) > 64:
        raise ValueError("knowledge_ids may contain at most 64 items")
    return tuple(normalized)


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
    def from_dict(cls, value: dict[str, Any]) -> SourceReference:
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
    owner_uid: str = ""
    knowledge_enabled: bool = True
    knowledge_ids: tuple[str, ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "source_references": [item.to_dict() for item in self.source_references],
            "knowledge_ids": (
                None if self.knowledge_ids is None else list(self.knowledge_ids)
            ),
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
    owner_uid: str = ""
    knowledge_enabled: bool = True
    knowledge_ids: tuple[str, ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        public_model_config = {
            key: value
            for key, value in self.model_config.items()
            if key in {"provider", "model", "model_spec", "reasoning_effort", "base_url"}
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
            "knowledge_ids": (
                None if self.knowledge_ids is None else list(self.knowledge_ids)
            ),
            "source_disclaimer": SOURCE_DISCLAIMER,
        }


@dataclass(frozen=True)
class GeneratedCandidate:
    coverage_slot: str
    query: str
    supplemental_information: str
    generation_rationale: str
    source_references: tuple[SourceReference, ...]
    demand_chain: dict[str, str] = field(default_factory=dict)
    quality_review: dict[str, str] = field(default_factory=dict)


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
