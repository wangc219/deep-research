from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from equipment_deep_research.domain.messages import RecallEnvelope, TaskEnvelope
from equipment_deep_research.domain.models import (
    AgentRecommendation,
    AuditResult,
    BaselineFindingPacket,
    CapabilityImageItem,
    EvidenceCard,
    RecallRequest,
    ResearchProblem,
    ResearchReport,
    TraceEvent,
    WinningMechanismStageOutput,
    to_plain,
)
from equipment_deep_research.domain.planning import ResearchPlanGraph, ResearchPlanNode
from equipment_deep_research.harness.scheduler import WorkerReport


def _task(**overrides: object) -> TaskEnvelope:
    values = {
        "task_id": "task-1",
        "run_id": "run-1",
        "round_index": 1,
        "parent_task_id": None,
        "target_agent_id": "international_situation",
        "target_capability_tags": [],
        "objective": "研究威胁",
        "research_questions": ["潜在威胁是什么？"],
        "context_refs": [],
        "evidence_refs": [],
        "allowed_tools": ["search_sources"],
        "object_read_scopes": ["ResearchProblem"],
        "object_write_scopes": ["BaselineFindingPacket"],
        "budget": {"max_turns": 8},
        "return_contract": "BaselineFindingPacket",
        "return_node": "baseline_reduce",
    }
    values.update(overrides)
    return TaskEnvelope(**values)


def _recall(**overrides: object) -> RecallEnvelope:
    values = {
        "recall_id": "recall-1",
        "source_layer": "L1",
        "target_agent_id": None,
        "target_capability_tag": "threat",
        "reason": "缺少威胁证据",
        "required_data": ["威胁类型"],
        "evidence_gaps": ["近期公开来源"],
        "return_node": "winning_l1",
        "urgency": "high",
        "attempt": 1,
        "status": "pending",
    }
    values.update(overrides)
    return RecallEnvelope(**values)


def _assert_transport_metadata(value: object, id_field: str) -> None:
    payload = to_plain(value)
    stable_id = getattr(value, id_field)
    assert stable_id
    assert payload[id_field] == stable_id
    assert payload["schema_version"] == "1.0"
    created_at = datetime.fromisoformat(payload["created_at"])
    assert created_at.utcoffset() == timezone.utc.utcoffset(created_at)
    json.dumps(payload, ensure_ascii=False, sort_keys=True)


def test_task_envelope_requires_one_target() -> None:
    task = _task(target_agent_id="", target_capability_tags=[])

    with pytest.raises(ValueError, match="target"):
        task.validate()


def test_task_envelope_requires_objective_and_return_contract() -> None:
    with pytest.raises(ValueError, match="objective and return contract"):
        _task(objective=" ").validate()


def test_recall_envelope_resolves_agent_before_capability_target() -> None:
    recall = _recall(target_agent_id="weapon_equipment")

    assert recall.target_key() == "weapon_equipment"
    assert replace(recall, target_agent_id=None).target_key() == "threat"
    assert replace(recall, target_agent_id=None, target_capability_tag=None).target_key() == "unroutable"


def test_plan_node_rejects_self_dependency() -> None:
    node = ResearchPlanNode("n1", "baseline", ["n1"], "pending", "agent-1", ["threat"])

    with pytest.raises(ValueError, match="depend"):
        node.validate()


def test_plan_graph_returns_only_dependency_ready_nodes() -> None:
    graph = ResearchPlanGraph(
        nodes=[
            ResearchPlanNode("n1", "baseline", [], "pending", "international_situation", ["threat"]),
            ResearchPlanNode("n2", "reduce", ["n1"], "pending", "orchestrator", ["threat"]),
        ]
    )

    assert [node.node_id for node in graph.ready_nodes()] == ["n1"]
    completed = replace(graph.nodes[0], status="completed")
    advanced = replace(graph, nodes=[completed, graph.nodes[1]])
    assert [node.node_id for node in advanced.ready_nodes()] == ["n2"]


def test_new_transport_objects_are_versioned_json_serializable_and_identified() -> None:
    task = _task()
    recall = _recall()
    node = ResearchPlanNode("n1", "baseline", [], "pending", "agent-1", ["threat"])
    graph = ResearchPlanGraph(nodes=[node])
    packet = BaselineFindingPacket(
        packet_id="packet-1",
        agent_id="agent-1",
        capability_tags=["threat"],
        topic_focus="低空威胁",
        findings=["发现"],
        evidence_ids=["evidence-1"],
        confidence=0.8,
        coverage_notes=[],
        open_questions=[],
        handoff_summary="完成",
        checkpoint="agent-1: complete",
    )

    _assert_transport_metadata(task, "task_id")
    _assert_transport_metadata(recall, "recall_id")
    _assert_transport_metadata(node, "node_id")
    _assert_transport_metadata(graph, "plan_id")
    _assert_transport_metadata(packet, "packet_id")


def test_baseline_packet_keeps_old_construction_and_defaults_compatibility_fields() -> None:
    packet = BaselineFindingPacket(
        packet_id="packet-1",
        agent_id="agent-1",
        capability_tags=["threat"],
        topic_focus="低空威胁",
        findings=["发现"],
        evidence_ids=["evidence-1"],
        confidence=0.8,
        coverage_notes=[],
        open_questions=[],
        handoff_summary="完成",
        checkpoint="agent-1: complete",
    )

    assert packet.claim_ids == []
    assert packet.search_log == []
    assert packet.limitations == []


def test_persisted_objects_are_versioned_json_serializable_and_identified() -> None:
    recall = RecallRequest(
        recall_id="recall-1",
        source_layer="L1",
        target_agent_id=None,
        target_capability_tag="threat",
        reason="missing evidence",
        required_data=["source"],
        return_node="L1",
        urgency="high",
    )
    values = [
        (ResearchProblem(topic="topic"), "problem_id"),
        (
            EvidenceCard(
                "evidence-1",
                "source",
                "https://example.com",
                "A",
                "claim",
                "excerpt",
                "page:1",
                "accepted",
                "agent-1",
            ),
            "evidence_id",
        ),
        (recall, "recall_id"),
        (
            AgentRecommendation("recommendation-1", "threat", "gap", "new agent"),
            "recommendation_id",
        ),
        (
            WinningMechanismStageOutput(
                "stage-1",
                "L1",
                "stage",
                {"result": "value"},
                0.8,
                ["evidence-1"],
                True,
                [],
                [recall],
            ),
            "stage_id",
        ),
        (
            CapabilityImageItem(
                "capability-1",
                "capability",
                "equipment",
                "upgrade",
                "logic",
                "scenario",
                "high",
                "gap",
                "image",
                ["evidence-1"],
                0.8,
            ),
            "capability_id",
        ),
        (AuditResult("audit-1", "approved", {"coverage": True}, []), "audit_id"),
        (
            ResearchReport("report-1", "title", "body", ["capability-1"], ["evidence-1"], "audit-1"),
            "report_id",
        ),
        (TraceEvent("trace-1", "event", "actor", "summary"), "event_id"),
        (
            WorkerReport("agent-1", "completed", ["evidence-1"], "packet-1", "done", "session.jsonl"),
            "worker_report_id",
        ),
    ]

    for value, id_field in values:
        _assert_transport_metadata(value, id_field)


def test_new_metadata_fields_preserve_old_positional_and_keyword_construction() -> None:
    created_at = "2026-07-10T00:00:00+00:00"
    problem = ResearchProblem("topic", "auto", [], [], created_at)
    evidence = EvidenceCard(
        "evidence-1",
        "source",
        "https://example.com",
        "A",
        "claim",
        "excerpt",
        "page:1",
        "accepted",
        "agent-1",
        [],
        created_at,
    )
    worker = WorkerReport(
        agent_id="agent-1",
        status="completed",
        new_evidence_ids=[],
        packet_id="packet-1",
        handoff_summary="done",
        session_path="session.jsonl",
    )

    assert problem.created_at == created_at
    assert problem.problem_id
    assert evidence.created_at == created_at
    assert evidence.schema_version == "1.0"
    assert worker.worker_report_id
    assert worker.schema_version == "1.0"
