from __future__ import annotations

from collections.abc import Mapping
from typing import Any


DEFAULT_MODEL_PROFILE: dict[str, str] = {
    "provider": "responses",
    "model": "gpt-5.5",
}

# Task 2 can attach handlers to these names without making agent configuration
# depend on executable registry objects.
TOOL_CATALOG = frozenset(
    {
        "search_sources",
        "fetch_page",
        "create_evidence_card",
        "write_stage_output",
        "create_recall_request",
        "create_capability_image",
        "write_audit",
        "write_report",
    }
)

CONTRACT_CATALOG = frozenset(
    {
        "AgentExecutionResult",
        "AuditResult",
        "BaselineFindingPacket",
        "ResearchReport",
        "TaskEnvelope",
        "WinningMechanismStageOutput",
        "research_task",
        "task_envelope",
        "agent_execution_result",
        "baseline_finding_packet",
        "winning_mechanism_stage_output",
        "audit_result",
        "research_report",
    }
)

VISIBLE_SECTION_CATALOG = frozenset(
    {
        "task",
        "evidence_policy",
        "own_checkpoint",
        "recall_request",
        "baseline_summaries",
        "evidence_index",
        "coverage",
        "checkpoints",
        "stage_outputs",
        "capability_images",
        "trace_summary",
        "audit",
    }
)

OBJECT_SCOPE_CATALOG = frozenset(
    {
        "ResearchProblem",
        "EvidenceCard",
        "BaselineFindingPacket",
        "WorkingCheckpoint",
        "RecallRequest",
        "AgentRecommendation",
        "WinningMechanismStageOutput",
        "CapabilityImageItem",
        "AuditResult",
        "ResearchReport",
        "TraceEvent",
        "SearchLead",
        "SourceMaterial",
    }
)

LEGACY_SYSTEM_AGENT_IDS = frozenset({"winning_mechanism", "auditor", "reporter"})

_SYSTEM_OUTPUT_CONTRACTS = {
    "winning_mechanism": "winning_mechanism_stage_output",
    "auditor": "audit_result",
    "reporter": "research_report",
}

_SECRET_PROFILE_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "credentials",
        "headers",
        "secret",
        "token",
    }
)


def default_output_contract(agent_id: str) -> str:
    return _SYSTEM_OUTPUT_CONTRACTS.get(agent_id, "baseline_finding_packet")


def validate_named_contract(value: str | Mapping[str, Any], *, field_name: str) -> None:
    if isinstance(value, str):
        if value not in CONTRACT_CATALOG:
            raise ValueError(f"unknown {field_name}: {value}")
        return
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{field_name} must name or define an existing contract")
    reference = next(
        (
            value[key]
            for key in ("name", "contract", "$ref")
            if key in value
        ),
        None,
    )
    if reference is not None and (
        not isinstance(reference, str) or reference not in CONTRACT_CATALOG
    ):
        raise ValueError(f"unknown {field_name}: {reference}")


def validate_model_profile(value: Mapping[str, Any]) -> None:
    provider = value.get("provider")
    model = value.get("model")
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError("model_profile provider must be a non-empty string")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("model_profile model must be a non-empty string")

    forbidden = sorted(_find_secret_keys(value))
    if forbidden:
        raise ValueError(f"model_profile cannot contain secret fields: {forbidden}")


def _find_secret_keys(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        found = {
            str(key)
            for key in value
            if str(key).lower().replace("-", "_") in _SECRET_PROFILE_KEYS
        }
        for item in value.values():
            found.update(_find_secret_keys(item))
        return found
    if isinstance(value, (list, tuple)):
        found: set[str] = set()
        for item in value:
            found.update(_find_secret_keys(item))
        return found
    return set()


__all__ = [
    "CONTRACT_CATALOG",
    "DEFAULT_MODEL_PROFILE",
    "LEGACY_SYSTEM_AGENT_IDS",
    "OBJECT_SCOPE_CATALOG",
    "TOOL_CATALOG",
    "VISIBLE_SECTION_CATALOG",
    "default_output_contract",
    "validate_model_profile",
    "validate_named_contract",
]
