from equipment_deep_research.domain.models import BaselineFindingPacket, EvidenceCard
from equipment_deep_research.orchestration.winning_reasoning import SixStepReasoner
from equipment_deep_research.domain.store import DomainStore, TraceStore
from equipment_deep_research.orchestration.winning import WinningMechanismEngine


def test_six_steps_are_linked_and_evidence_backed() -> None:
    packet = BaselineFindingPacket("p", "a", ["threat"], "topic", ["finding"], ["ev"], .8, [], [], "handoff", "cp")
    evidence = EvidenceCard("ev", "source", "https://example.org/a", "B", "claim", "excerpt", "p:1", "quality", "a")
    result = SixStepReasoner().run(topic="topic", route="new_winning_mechanism", packets=[packet], evidence=[evidence])
    assert result.winning_paths.input_refs == [result.defense_decomposition.object_id]
    assert result.effect_chain.input_refs == [result.winning_paths.object_id]
    assert result.capability_mapping.input_refs == [result.effect_chain.object_id]
    assert result.gap_matrix.input_refs == [result.capability_mapping.object_id]
    assert result.image_drafts[0].input_refs == [result.gap_matrix.object_id]
    assert all(node.evidence_ids and 0 <= node.confidence <= 1 for node in result.critical_nodes())


def test_winning_engine_records_six_steps_in_trace_and_stage_refs() -> None:
    packet = BaselineFindingPacket("p", "a", ["threat"], "topic", ["finding"], ["ev"], .8, [], [], "handoff", "cp")
    evidence = EvidenceCard("ev", "source", "https://example.org/a", "B", "claim", "excerpt", "p:1", "quality", "a")
    store, trace = DomainStore(), TraceStore()
    store.add_baseline_packet(packet)
    store.add_evidence(evidence)
    stages, _, _ = WinningMechanismEngine().run(topic="topic", route="new_winning_mechanism", store=store, trace=trace, coverage={"missing_required_tags": [], "coverage_passed": True})
    assert sum(event.event_type == "winning_reasoning_step_completed" for event in trace.events) == 6
    assert all(stage.outputs["reasoning_refs"] for stage in stages)
