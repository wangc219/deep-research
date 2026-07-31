from __future__ import annotations

from pathlib import Path
import json

from equipment_deep_research.agents.provider import (
    AgentRunResult,
    FakeAgentProvider,
    ResponsesAgentProvider,
)
from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.domain.models import BaselineFindingPacket, EvidenceCard
from equipment_deep_research.domain.store import DomainStore, TraceStore
from equipment_deep_research.harness.scheduler import DiscoveryScheduler
from equipment_deep_research.tools.evidence import EvidenceGovernor
from equipment_deep_research.providers.base import ProviderFinalTurn, ProviderStreamEvent
from equipment_deep_research.providers.fake import ScriptedFakeProvider
from equipment_deep_research.tools.materialization import MaterializedEvidence


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


def test_real_scheduler_streams_hosted_search_then_fetch_and_evidence_tools(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_EVIDENCE_ACCEPT_TARGET", "1")
    backend = ScriptedFakeProvider(
        [[
            ProviderStreamEvent.final(
                ProviderFinalTurn(
                    text="发现装备能力约束公开报告",
                    metadata={
                        "search_queries": ["装备 能力约束"],
                        "web_sources": [
                            {"url": "https://example.org/report", "title": "Report"}
                        ],
                    },
                )
            )
        ], [
            ProviderStreamEvent.final(
                ProviderFinalTurn(text=(
                    '{"findings":["公开资料发现能力约束"],"confidence":0.8,'
                    '"open_questions":[],"handoff_summary":"完成",'
                    '"source_claims":[{"url":"https://example.org/report",'
                    '"claim":"报告支撑能力约束判断"}]}'
                ))
            )
        ]]
    )

    def materialize(self, evidence, *, mode):
        updated = type(evidence)(
            **{
                **evidence.__dict__,
                "excerpt": "公开报告正文明确描述了相关能力约束和验证结果。",
                "source_location": "artifact:test#p1",
                "artifact_refs": ["artifact:test"],
            }
        )
        return MaterializedEvidence(
            updated,
            {
                "status": "fetched",
                "artifact_refs": ["artifact:test"],
                "formal_evidence_allowed": True,
            },
        )

    monkeypatch.setattr(
        "equipment_deep_research.tools.materialization.EvidenceMaterializer.materialize",
        materialize,
    )
    scheduler = DiscoveryScheduler(
        run_id="run-real-tools",
        run_dir=tmp_path / "run-real-tools",
        provider=ResponsesAgentProvider(backend),
        store=DomainStore(),
        trace=TraceStore(),
        mode="real",
    )
    try:
        scheduler.run_agent(
            agent=AgentDef("agent", "Agent", "", ["threat"], [], {}),
            topic="topic",
            research_route="new_winning_mechanism",
            raise_on_error=True,
        )
        rows = [
            json.loads(line)
            for line in (scheduler.sessions_dir / "agent.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        calls = [row["tool_name"] for row in rows if row["event_type"] == "tool_call"]
        assert calls == ["search_sources", "fetch_page", "create_evidence_card"]
        assert any(
            event.event_type == "baseline_materialization_progress"
            for event in scheduler.trace.events
        )
    finally:
        scheduler.close()


def test_materialization_stops_after_governed_quality_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("EQUIPMENT_DR_EVIDENCE_ACCEPT_TARGET", "1")
    monkeypatch.setenv("EQUIPMENT_DR_EVIDENCE_MIN_COUNT", "1")
    monkeypatch.setenv("EQUIPMENT_DR_EVIDENCE_MIN_DOMAINS", "1")
    monkeypatch.setenv("EQUIPMENT_DR_EVIDENCE_MATERIALIZE_ATTEMPTS", "5")
    monkeypatch.setenv("EQUIPMENT_DR_EVIDENCE_MATERIALIZE_CONCURRENCY", "2")

    class MultiEvidenceProvider(FakeAgentProvider):
        def run_baseline_agent(self, request):
            evidence = [
                EvidenceCard(
                    f"ev-{index}",
                    f"Source {index}",
                    f"https://source-{index}.example/report",
                    "A",
                    f"独立来源{index}支撑能力判断",
                    f"来源{index}正文给出可核验事实与边界。",
                    "report#p1",
                    "authoritative",
                    request.agent.agent_id,
                )
                for index in range(5)
            ]
            packet = BaselineFindingPacket(
                packet_id="packet-multi",
                agent_id=request.agent.agent_id,
                capability_tags=request.agent.capability_tags,
                topic_focus=request.topic,
                findings=["多点证据形成一致方向判断"],
                evidence_ids=[item.evidence_id for item in evidence],
                confidence=0.8,
                coverage_notes=[],
                open_questions=[],
                handoff_summary="完成多点证据研判",
                checkpoint="complete",
            )
            return AgentRunResult(packet, evidence, "complete")

    def materialize(self, evidence, *, mode):
        return MaterializedEvidence(
            evidence,
            {
                "status": "fetched",
                "artifact_refs": [],
                "formal_evidence_allowed": True,
                "fetch_cache_hit": False,
            },
        )

    monkeypatch.setattr(
        "equipment_deep_research.tools.materialization.EvidenceMaterializer.materialize",
        materialize,
    )
    scheduler = DiscoveryScheduler(
        run_id="run-multi-evidence",
        run_dir=tmp_path / "run-multi-evidence",
        provider=MultiEvidenceProvider(),
        store=DomainStore(),
        trace=TraceStore(),
        mode="real",
    )
    try:
        report = scheduler.run_agent(
            agent=AgentDef(
                "agent",
                "Agent",
                "",
                ["threat"],
                [],
                {},
                research_policy={"require_counter_evidence": False},
            ),
            topic="topic",
            research_route="new_winning_mechanism",
            raise_on_error=True,
        )
        progress = [
            event
            for event in scheduler.trace.events
            if event.event_type == "baseline_materialization_progress"
        ]
        assert len(report.new_evidence_ids) == 1
        assert all(not event.payload["continued_after_threshold"] for event in progress)
        assert progress[-1].payload["quality_target_met"] is True
        assert progress[-1].payload["parallel_batch_size"] == 1
    finally:
        scheduler.close()


def test_real_codex_baseline_with_one_formal_source_is_limited_not_fatal(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("EQUIPMENT_DR_ALLOW_LIMITED_BASELINE", raising=False)
    monkeypatch.setenv("EQUIPMENT_DR_EVIDENCE_ACCEPT_TARGET", "4")
    monkeypatch.setenv("EQUIPMENT_DR_EVIDENCE_MIN_COUNT", "3")

    class OneEvidenceCodexProvider:
        provider_kind = "codex_cli"
        enforce_profile_stops = True
        uses_hosted_web_search = False

        def run_baseline_agent(self, request):
            evidence = EvidenceCard(
                "ev-one",
                "Authoritative source",
                "https://example.org/one",
                "A",
                "公开材料支持一项初步判断",
                "公开材料正文",
                "source#p1",
                "candidate",
                request.agent.agent_id,
            )
            packet = BaselineFindingPacket(
                packet_id=f"packet-{request.agent.agent_id}",
                agent_id=request.agent.agent_id,
                capability_tags=request.agent.capability_tags,
                topic_focus=request.topic,
                findings=["形成一项有边界的初步判断"],
                evidence_ids=[evidence.evidence_id],
                confidence=0.78,
                coverage_notes=[],
                open_questions=["仍需补充第二来源"],
                handoff_summary="单源初步交接",
                checkpoint="complete",
                limitations=["证据域不足"],
                schema_version="2.0",
                payload_type="strategic_assessment_v1",
                payload={
                    "situation_assessment": "初步态势",
                    "threat_assessment": "初步威胁",
                    "strategic_pattern": "公开资料模式",
                    "opponent_moves": ["公开动向"],
                    "warning_indicators": ["预警指标"],
                    "alternative_hypotheses": ["替代假设"],
                    "scenario_drivers": ["场景驱动"],
                },
            )
            return AgentRunResult(packet, [evidence], packet.handoff_summary)

    def materialize(self, evidence, *, mode):
        del self, mode
        updated = type(evidence)(
            **{
                **evidence.__dict__,
                "artifact_refs": ["artifact:one"],
                "quality_assessment": "materialized",
            }
        )
        return MaterializedEvidence(
            updated,
            {
                "status": "fetched",
                "artifact_refs": ["artifact:one"],
                "formal_evidence_allowed": True,
            },
        )

    monkeypatch.setattr(
        "equipment_deep_research.tools.materialization.EvidenceMaterializer.materialize",
        materialize,
    )
    scheduler = DiscoveryScheduler(
        run_id="run-limited",
        run_dir=tmp_path / "run-limited",
        provider=OneEvidenceCodexProvider(),
        store=DomainStore(),
        trace=TraceStore(),
        mode="real",
    )
    try:
        report = scheduler.run_agent(
            agent=AgentDef(
                "international_situation",
                "国际形势",
                "",
                ["threat"],
                [],
                {},
            ),
            topic="topic",
            research_route="new_winning_mechanism",
            raise_on_error=True,
        )
        packet = scheduler.store.baseline_packets[report.packet_id]
        assert packet.evidence_ids == ["ev-one"]
        assert packet.confidence == 0.49
        assert any("正式证据少于3条" in item for item in packet.limitations)
    finally:
        scheduler.close()
