"""Backward-compatible import location for agent configuration contracts.

The catalogs are shared configuration vocabulary, not agent implementation
details, so their canonical home is ``equipment_deep_research.contracts``.
"""

from equipment_deep_research.contracts.catalog import (
    CONTRACT_CATALOG,
    DEFAULT_MODEL_PROFILE,
    LEGACY_SYSTEM_AGENT_IDS,
    OBJECT_SCOPE_CATALOG,
    TOOL_CATALOG,
    VISIBLE_SECTION_CATALOG,
    default_output_contract,
    validate_agent_extension,
    validate_model_profile,
    validate_named_contract,
)

__all__ = [
    "CONTRACT_CATALOG", "DEFAULT_MODEL_PROFILE", "LEGACY_SYSTEM_AGENT_IDS",
    "OBJECT_SCOPE_CATALOG", "TOOL_CATALOG", "VISIBLE_SECTION_CATALOG",
    "default_output_contract", "validate_model_profile", "validate_agent_extension",
    "validate_named_contract",
]
