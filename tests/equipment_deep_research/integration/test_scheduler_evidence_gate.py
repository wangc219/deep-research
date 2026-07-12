from __future__ import annotations

from pathlib import Path

from equipment_deep_research.agents.provider import FakeAgentProvider
from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.domain.store import DomainStore, TraceStore
from equipment_deep_research.harness.scheduler import DiscoveryScheduler
from equipment_deep_research.tools.evidence import EvidenceGovernor


def test_scheduler_retains_low_quality_material_but_blocks_formal_evidence(tmp_path: Path) -> None:
    scheduler = DiscoveryScheduler(
        run_id="run",
        run_dir=tmp_path / "run",
        provider=FakeAgentProvider(),
        store=DomainStore(),
        trace=TraceStore(),
        evidence_governor=EvidenceGovernor(minimum_score=0.99),
    )
    try:
        report = scheduler.run_agent(
            agent=AgentDef("agent", "Agent", "", ["threat"], [], {}),
            topic="topic",
            research_route="new_winning_mechanism",
            raise_on_error=True,
        )
        assert report.new_evidence_ids == []
        assert scheduler.source_materials[0]["evidence_assessment"]["decision"] == "rejected"
        assert scheduler.store.baseline_packets[report.packet_id].evidence_ids == []
    finally:
        scheduler.close()
