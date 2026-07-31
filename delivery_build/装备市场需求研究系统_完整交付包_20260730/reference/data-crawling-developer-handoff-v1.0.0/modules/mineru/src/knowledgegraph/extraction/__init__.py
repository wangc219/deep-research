"""Core literature extraction contract, prompts, adapters, and governance helpers."""

from .adapters import (
    BaseAdapter,
    LLMSevenRelationSchemaGuidedAdapter,
    LLMSchemaGuidedAdapter,
    PrecomputedResultAdapter,
    SchemaGuidedOfflineAdapter,
)
from .models import (
    DocumentChunk,
    EvidenceSpan,
    ExtractedEntity,
    ExtractedRelation,
    ExtractionResult,
    ExtractionTrace,
    SourceClaim,
)
from .schema import SCHEMA_VERSION, SEVEN_RELATION_TYPES

__all__ = [
    "BaseAdapter",
    "DocumentChunk",
    "EvidenceSpan",
    "ExtractedEntity",
    "ExtractedRelation",
    "ExtractionResult",
    "ExtractionTrace",
    "LLMSevenRelationSchemaGuidedAdapter",
    "LLMSchemaGuidedAdapter",
    "PrecomputedResultAdapter",
    "SCHEMA_VERSION",
    "SEVEN_RELATION_TYPES",
    "SchemaGuidedOfflineAdapter",
    "SourceClaim",
]
