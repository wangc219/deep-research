from __future__ import annotations

from pathlib import Path

from equipment_deep_research.architecture import (
    find_import_cycles,
    find_violations,
    module_metrics,
    oversized_modules,
)


def test_layer_boundaries_have_no_forbidden_direct_imports() -> None:
    root = Path(__file__).resolve().parents[3] / "src" / "equipment_deep_research"
    violations = find_violations(root)
    assert violations == [], "\n".join(str(item) for item in violations)


def test_import_time_graph_is_acyclic() -> None:
    root = Path(__file__).resolve().parents[3] / "src" / "equipment_deep_research"
    assert find_import_cycles(root) == []


def test_contracts_are_importable_without_runtime_adapters() -> None:
    from equipment_deep_research.contracts import ToolDefinition, TOOL_CATALOG

    assert ToolDefinition.__module__ == "equipment_deep_research.contracts.tools"
    assert "search_sources" in TOOL_CATALOG


def test_module_metrics_make_refactoring_hotspots_explicit() -> None:
    root = Path(__file__).resolve().parents[3] / "src" / "equipment_deep_research"
    metrics = module_metrics(root)
    names = {item.module for item in metrics}

    assert "equipment_deep_research.api.app" in names
    assert all(item.lines > 0 for item in metrics)
    oversized = {item.module for item in oversized_modules(root, line_limit=1000)}
    assert {
        "equipment_deep_research.api.app",
        "equipment_deep_research.orchestration.runner",
    } <= oversized


def test_legacy_facades_resolve_to_canonical_domain_modules() -> None:
    from equipment_deep_research.deep_conversation import branch_message_path as old_path
    from equipment_deep_research.domain.conversation import branch_message_path
    from equipment_deep_research.domain.capability_portrait import (
        capability_portrait_quality_issues,
    )
    from equipment_deep_research.orchestration.capability_portrait import (
        capability_portrait_quality_issues as old_quality,
    )

    assert old_path is branch_message_path
    assert old_quality is capability_portrait_quality_issues


def test_swarm_state_and_runtime_ports_have_canonical_contracts() -> None:
    from equipment_deep_research.agents.workflows.winning_flows.ports import (
        SwarmRuntime as legacy_swarm_runtime,
    )
    from equipment_deep_research.agents.workflows.winning_flows.state import (
        SwarmState as legacy_swarm_state,
    )
    from equipment_deep_research.contracts.runtime import SwarmRuntime
    from equipment_deep_research.domain.swarm_strategy import SwarmState

    assert legacy_swarm_runtime is SwarmRuntime
    assert legacy_swarm_state is SwarmState
