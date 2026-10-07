from __future__ import annotations

from types import SimpleNamespace

from equipment_deep_research.harness.evolution_trace import (
    begin_retrieval,
    extract_evidence_ids,
    extract_memory_ids,
    extract_packet_ids,
    finish_retrieval,
    set_evolution_context,
    set_evolution_trace_sink,
    stable_hash,
)
from equipment_deep_research.domain.store import TraceStore


def test_evolution_hash_and_id_extractors_are_deterministic() -> None:
    payload = {
        "query": "q",
        "expert_review_feedback": [{"feedback_id": "feedback-1"}],
        "evidence_index": [{"evidence_id": "ev-1"}],
        "upstream_handoffs": [{"packet_id": "packet-1"}],
    }
    assert stable_hash(payload) == stable_hash({key: value for key, value in reversed(list(payload.items()))})
    assert extract_memory_ids(payload) == ["feedback-1"]
    assert extract_evidence_ids(payload) == ["ev-1"]
    assert extract_packet_ids(payload) == ["packet-1"]


def test_retrieval_lifecycle_contains_rebuildable_attribution() -> None:
    trace = TraceStore()
    host = SimpleNamespace(provider=SimpleNamespace(snapshot=lambda: {"type": "fake", "model": "fixture"}))
    set_evolution_context(
        host,
        {
            "run_id": "run-1",
            "prompt_bundle_hash": "sha256:prompt",
            "memory_snapshot_hash": "sha256:memory",
            "memory_ids": ["feedback-1"],
        },
    )
    set_evolution_trace_sink(host, trace.append_evolution_event)
    handle = begin_retrieval(
        host,
        agent_id="winning_s6_image",
        phase="winning_s6_parallel_card_01",
        payload={
            "query": "q",
            "expert_review_feedback": [{"feedback_id": "feedback-1"}],
            "evidence_ids": ["ev-1"],
            "upstream_handoffs": [{"packet_id": "packet-1"}],
        },
        system="reviewed system prompt",
    )
    finish_retrieval(
        handle,
        output="依据反馈采纳 feedback-1",
        metadata={
            "usage": {
                "input_tokens": 12,
                "output_tokens": 8,
                "total_tokens": 20,
            },
            "quality_delta": 0.06,
        },
    )
    rows = trace.snapshot()
    assert [row.event_type for row in rows] == [
        "evolution_retrieval_selected",
        "evolution_retrieval_applied",
        "evolution_retrieval_outcome",
    ]
    outcome = rows[-1].payload
    assert outcome["stage_id"] == "S6"
    assert outcome["selected"] is True
    assert outcome["applied"] is True
    assert outcome["adopted"] is True
    assert outcome["outcome"] == "improved"
    assert outcome["query_hash"].startswith("sha256:")
    assert outcome["evidence_snapshot_hash"].startswith("sha256:")
    assert outcome["upstream_packet_hash"].startswith("sha256:")
    assert outcome["prompt_bundle_hash"] == "sha256:prompt"
    assert outcome["memory_snapshot_hash"] == "sha256:memory"
    assert outcome["token_cost"] == 20
    assert outcome["latency_ms"] >= 0


def test_provider_exposes_evolution_sink_without_changing_progress_api() -> None:
    host = SimpleNamespace(provider=SimpleNamespace(snapshot=lambda: {"type": "fake"}))
    # A lightweight object is enough to exercise the public helper contract;
    # ResponsesAgentProvider itself wires the same methods on production hosts.
    set_evolution_context(host, {"run_id": "r"})
    rows: list[dict] = []
    set_evolution_trace_sink(host, rows.append)
    handle = begin_retrieval(
        host,
        agent_id="winning_s1_opponent",
        phase="winning_s1_standard",
        payload={"query": "q"},
        system="sys",
    )
    finish_retrieval(handle, output="done")
    assert len(rows) == 3
    assert all(item["run_id"] == "r" for item in rows)


def test_explicit_memory_boundaries_capture_scope_and_truncation() -> None:
    """Selected and applied sets must remain auditable after compaction."""

    host = SimpleNamespace(
        provider=SimpleNamespace(snapshot=lambda: {"type": "fake", "model": "fixture"})
    )
    set_evolution_context(
        host,
        {
            "run_id": "run-2",
            "trace_id": "trace-2",
            "scope": {
                "tenant_id": "tenant-a",
                "workspace_id": "workspace-a",
                "project_id": "project-a",
                "profile_id": "profile-a",
                "route": "capability_image",
                "stage_scope": ["S4", "S6"],
            },
        },
    )
    rows: list[dict] = []
    set_evolution_trace_sink(host, rows.append)
    handle = begin_retrieval(
        host,
        agent_id="winning_s6_image",
        phase="winning_s6_card",
        payload={
            "expert_review_feedback": [
                {"feedback_id": "feedback-1"},
                {"feedback_id": "feedback-2"},
            ],
            # Retrieval selected two lessons, but compaction injected only one.
            "selected_memory_ids": ["feedback-1", "feedback-2"],
            "applied_memory_ids": ["feedback-1"],
            "truncation_reason": "token_budget",
        },
        system="sys",
    )
    finish_retrieval(handle, output="依据 feedback-1 完成修订")

    assert len(rows) == 3
    assert all(row["trace_id"] == "trace-2" for row in rows)
    assert all(row["tenant_id"] == "tenant-a" for row in rows)
    assert all(row["workspace_id"] == "workspace-a" for row in rows)
    assert all(row["project_id"] == "project-a" for row in rows)
    assert all(row["profile_id"] == "profile-a" for row in rows)
    assert all(row["route"] == "capability_image" for row in rows)
    assert all(row["stage_scope"] == ["S4", "S6"] for row in rows)
    applied = rows[1]
    assert applied["selected_memory_ids"] == ["feedback-1", "feedback-2"]
    assert applied["applied_memory_ids"] == ["feedback-1"]
    assert applied["applied"] is True
    assert applied["truncation_reason"] == "token_budget"
    outcome = rows[-1]
    assert outcome["adopted"] is True


def test_explicit_empty_applied_set_is_not_inferred_as_adopted() -> None:
    host = SimpleNamespace(provider=SimpleNamespace(snapshot=lambda: {"type": "fake"}))
    rows: list[dict] = []
    set_evolution_trace_sink(host, rows.append)
    handle = begin_retrieval(
        host,
        agent_id="winning_s1_opponent",
        phase="winning_s1_standard",
        payload={
            "expert_review_feedback": [{"feedback_id": "feedback-1"}],
            "selected_memory_ids": ["feedback-1"],
            "applied_memory_ids": [],
            "memory_truncation_reason": "all_lessons_dropped",
        },
        system="sys",
    )
    finish_retrieval(handle, output="依据反馈采纳 feedback-1")
    assert rows[1]["selected"] is True
    assert rows[1]["applied"] is False
    assert rows[1]["retrieval_status"] == "selected_not_applied"
    assert rows[-1]["applied_memory_ids"] == []
    assert rows[-1]["adopted"] is False
    assert rows[-1]["truncation_reason"] == "all_lessons_dropped"


def test_context_boundary_can_explicitly_clear_applied_memory() -> None:
    host = SimpleNamespace(provider=SimpleNamespace(snapshot=lambda: {"type": "fake"}))
    set_evolution_context(
        host,
        {
            "run_id": "run-context-boundary",
            "selected_memory_ids": ["feedback-1"],
            "applied_memory_ids": [],
            "truncation_reason": "context_compaction",
        },
    )
    rows: list[dict] = []
    set_evolution_trace_sink(host, rows.append)
    handle = begin_retrieval(
        host,
        agent_id="winning_s3_breakthrough",
        phase="winning_s3_standard",
        payload={"expert_review_feedback": [{"feedback_id": "feedback-1"}]},
        system="sys",
    )
    finish_retrieval(handle, output="follow feedback-1")
    assert rows[0]["selected_memory_ids"] == ["feedback-1"]
    assert rows[1]["applied_memory_ids"] == []
    assert rows[-1]["applied"] is False
    assert rows[-1]["adopted"] is False
    assert rows[-1]["truncation_reason"] == "context_compaction"
