from __future__ import annotations

from equipment_deep_research.agents.provider import AgentRunRequest, ResponsesAgentProvider
from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.providers.base import ProviderFinalTurn, ProviderStreamEvent
from equipment_deep_research.providers.fake import ScriptedFakeProvider
from equipment_deep_research.orchestration.runner import DeepResearchRunner
from pathlib import Path


def test_responses_adapter_returns_structured_packet_without_model_claimed_evidence() -> None:
    backend = ScriptedFakeProvider([[ProviderStreamEvent.final(ProviderFinalTurn(text='{"findings":["威胁态势上升"],"confidence":0.72,"open_questions":["补充公开证据"],"handoff_summary":"完成初步研判"}'))]])
    agent = AgentDef("a", "国际形势", "", ["threat"], [], {})
    result = ResponsesAgentProvider(backend).run_baseline_agent(AgentRunRequest("r", agent, "topic", "new_winning_mechanism", {}))
    assert result.packet.findings == ["威胁态势上升"]
    assert result.packet.evidence_ids == []
    assert result.packet.confidence == 0.72
    assert backend.inputs[0][1] == ()


def test_explicit_responses_provider_requires_credential(tmp_path: Path, monkeypatch) -> None:
    root = Path(__file__).parents[3]
    monkeypatch.delenv("EQUIPMENT_DR_API_KEY", raising=False)
    runner = DeepResearchRunner(project_root=root, output_root=tmp_path, agent_config_path=root / "configs/equipment_deep_research/agents.yaml", preset_config_path=root / "configs/equipment_deep_research/presets.yaml")
    try:
        runner._select_agent_provider("real", "responses")
    except ValueError as error:
        assert "EQUIPMENT_DR_API_KEY" in str(error)
    else:
        raise AssertionError("credential configuration must be required")
