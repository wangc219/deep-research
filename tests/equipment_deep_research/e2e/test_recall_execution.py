from __future__ import annotations

import json
from pathlib import Path

from equipment_deep_research.agents.provider import AgentRunRequest, AgentRunResult
from equipment_deep_research.domain.models import BaselineFindingPacket, EvidenceCard
from equipment_deep_research.orchestration.runner import DeepResearchRunner


ROOT = Path(__file__).parents[3]
CONFIG = ROOT / "configs/equipment_deep_research"


class LowThenHighProvider:
    def run_baseline_agent(self, request: AgentRunRequest) -> AgentRunResult:
        round_index = request.round_index
        suffix = "" if round_index == 1 else f"-r{round_index}"
        evidence = EvidenceCard(
            f"ev-{request.agent.agent_id}{suffix}", "fixture", f"https://fixture.local/{request.agent.agent_id}{suffix}", "A",
            "可材料化公开证据", "可用于定向补充的直接摘录", "fixture:1", "fixture", request.agent.agent_id,
        )
        confidence = .65 if round_index == 1 else .9
        packet = BaselineFindingPacket(
            f"packet-{request.agent.agent_id}{suffix}", request.agent.agent_id, list(request.agent.capability_tags), request.topic,
            ["结构化发现"], [evidence.evidence_id], confidence, [], [], "定向补充完成", f"round={round_index}",
        )
        return AgentRunResult(packet, [evidence], "structured")


def test_runner_executes_routed_recall_and_resumes_l1(tmp_path: Path) -> None:
    result = DeepResearchRunner(
        project_root=ROOT, output_root=tmp_path, agent_config_path=CONFIG / "agents.yaml", preset_config_path=CONFIG / "presets.yaml", provider=LowThenHighProvider(),
    ).run(mode="fake", topic="定向再调", research_route="new_winning_mechanism", run_id="recall-execution")
    trace = [json.loads(line)["payload"] for line in (Path(result["run_dir"]) / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
    kinds = [row["event_type"] for row in trace]
    assert kinds.index("recall_requested") < kinds.index("recall_task_completed") < kinds.index("winning_stage_resumed")
    assert any(row["event_type"] == "winning_stage_completed" and row["output_refs"] == ["stage-L1-r2"] for row in trace)
    domain = [json.loads(line) for line in (Path(result["run_dir"]) / "domain.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(row["type"] == "BaselineFindingPacket" and row["payload"]["packet_id"].endswith("-r2") for row in domain)
