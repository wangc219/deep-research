from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Protocol

from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.domain.models import BaselineFindingPacket, EvidenceCard
from equipment_deep_research.providers.base import ModelMessage, ModelProvider


@dataclass(frozen=True)
class AgentRunRequest:
    run_id: str
    agent: AgentDef
    topic: str
    research_route: str
    context: dict
    round_index: int = 1


@dataclass(frozen=True)
class AgentRunResult:
    packet: BaselineFindingPacket
    evidence: list[EvidenceCard]
    raw_message: str


class AgentProvider(Protocol):
    def run_baseline_agent(self, request: AgentRunRequest) -> AgentRunResult:
        ...


class FakeAgentProvider:
    def run_baseline_agent(self, request: AgentRunRequest) -> AgentRunResult:
        agent = request.agent
        prefix = agent.display_name
        topic = request.topic
        suffix = "-1" if request.round_index == 1 else f"-r{request.round_index}"
        evidence = EvidenceCard(
            evidence_id=f"ev-{agent.agent_id}{suffix}",
            source_title=f"{prefix}离线验证材料",
            source_url=f"https://fixture.local/{agent.agent_id}",
            source_tier="A",
            claim=f"{prefix}发现与“{topic}”相关的关键能力信号。",
            excerpt=f"围绕{topic}的公开资料显示，{prefix}维度存在可用于能力画像研判的信号。",
            source_location="fixture:1",
            quality_assessment="offline_fixture",
            created_by=agent.agent_id,
        )
        findings = _findings_for_agent(agent.agent_id, topic, request.research_route)
        packet = BaselineFindingPacket(
            packet_id=(
                f"packet-{agent.agent_id}"
                if request.round_index == 1
                else f"packet-{agent.agent_id}-r{request.round_index}"
            ),
            agent_id=agent.agent_id,
            capability_tags=list(agent.capability_tags),
            topic_focus=topic,
            findings=findings,
            evidence_ids=[evidence.evidence_id],
            confidence=0.78,
            coverage_notes=[
                f"{prefix}维度已形成离线可审计初步发现。",
                "该结果用于验证多agent闭环，真实运行需替换为联网证据。",
            ],
            open_questions=[
                f"{prefix}维度仍需进一步联网补充高置信资料。",
            ],
            handoff_summary=f"{prefix}围绕{topic}形成{len(findings)}条基线发现。",
            checkpoint=f"{agent.agent_id}: baseline round {request.round_index} complete",
        )
        return AgentRunResult(packet=packet, evidence=[evidence], raw_message=packet.handoff_summary)


class RealAgentProvider(FakeAgentProvider):
    """Initial real-mode provider.

    This first deliverable keeps the model-facing runtime pluggable while still
    producing auditable artifacts. It records that public web evidence should be
    materialized through tools; model API integration can replace this provider
    without changing orchestration contracts.
    """

    def run_baseline_agent(self, request: AgentRunRequest) -> AgentRunResult:
        result = super().run_baseline_agent(request)
        public_url = _public_smoke_url_for_agent(request.agent.agent_id)
        evidence = [
            EvidenceCard(
                evidence_id=item.evidence_id.replace("-1", "-real-smoke"),
                source_title=item.source_title.replace("离线验证材料", "真实模式待材料化线索"),
                source_url=public_url,
                source_tier=item.source_tier,
                claim=item.claim,
                excerpt=item.excerpt + " real模式首版保留联网工具接入点。",
                source_location="real-smoke:public-url",
                quality_assessment="real_smoke_public_source",
                created_by=item.created_by,
            )
            for item in result.evidence
        ]
        packet = BaselineFindingPacket(
            **{
                **result.packet.__dict__,
                "evidence_ids": [item.evidence_id for item in evidence],
                "coverage_notes": [
                    *result.packet.coverage_notes,
                    "real模式首版验证运行链路和证据治理边界，后续可接入真实搜索provider。",
                ],
            }
        )
        return AgentRunResult(packet=packet, evidence=evidence, raw_message=packet.handoff_summary)


class ResponsesAgentProvider:
    """Turns a Responses-compatible model result into a constrained handoff.

    This adapter deliberately does not turn model-claimed URLs into evidence.
    Evidence must still be produced by the network tool/materialization chain.
    """

    def __init__(self, provider: ModelProvider, *, model_options: dict[str, Any] | None = None) -> None:
        self.provider = provider
        self.model_options = model_options or {"reasoning_effort": "high", "max_output_tokens": 5000}

    def run_baseline_agent(self, request: AgentRunRequest) -> AgentRunResult:
        text = asyncio.run(self._run(request))
        payload = _parse_baseline_payload(text)
        findings = [str(item) for item in payload.get("findings", []) if str(item).strip()]
        if not findings:
            findings = [f"{request.agent.display_name}未返回可采纳的结构化发现。"]
        confidence = float(payload.get("confidence", 0.45))
        confidence = min(1.0, max(0.0, confidence))
        packet = BaselineFindingPacket(
            packet_id=(
                f"packet-{request.agent.agent_id}"
                if request.round_index == 1
                else f"packet-{request.agent.agent_id}-r{request.round_index}"
            ),
            agent_id=request.agent.agent_id,
            capability_tags=list(request.agent.capability_tags),
            topic_focus=request.topic,
            findings=findings,
            evidence_ids=[],
            confidence=confidence,
            coverage_notes=["模型输出已通过结构化回传适配；正式证据仅由联网工具材料化后写入。"],
            open_questions=[str(item) for item in payload.get("open_questions", [])],
            handoff_summary=str(payload.get("handoff_summary", findings[0])),
            checkpoint=f"{request.agent.agent_id}: model turn complete",
            limitations=["尚未写入可材料化 EvidenceCard，结论必须在证据链补齐后提升置信度。"],
        )
        return AgentRunResult(packet=packet, evidence=[], raw_message=text)

    async def _run(self, request: AgentRunRequest) -> str:
        schema = {
            "findings": ["string"], "confidence": "0..1",
            "open_questions": ["string"], "handoff_summary": "string",
        }
        messages = [
            ModelMessage("system", "你是受限的研究子智能体。不要虚构来源或证据 URL，只输出 JSON。"),
            ModelMessage("user", {
                "agent": request.agent.display_name,
                "capability_tags": request.agent.capability_tags,
                "topic": request.topic,
                "route": request.research_route,
                "context": request.context,
                "output_schema": schema,
            }),
        ]
        fragments: list[str] = []
        async for event in self.provider.stream(messages, [], self.model_options):
            if event.event_type == "text_delta":
                fragments.append(event.delta)
            elif event.event_type == "final" and event.final_turn and event.final_turn.text:
                if not fragments:
                    fragments.append(event.final_turn.text)
        return "".join(fragments).strip()


def _parse_baseline_payload(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {"findings": [text], "confidence": 0.45, "open_questions": [], "handoff_summary": text}
    return value if isinstance(value, dict) else {"findings": [text], "confidence": 0.45}


def _findings_for_agent(agent_id: str, topic: str, route: str) -> list[str]:
    if agent_id == "international_situation":
        return [
            f"围绕{topic}，需要先识别潜在威胁力量和对抗压力。",
            "战略格局变化可能推动新型装备能力从单点性能转向体系贡献。",
        ]
    if agent_id == "combat_scenario":
        return [
            f"{topic}应落入明确任务场景，包含敌方方案、关键时间窗和环境约束。",
            "场景约束决定能力画像不能只写技术方向，必须转化为任务功能。",
        ]
    if agent_id == "weapon_equipment":
        return [
            f"现有装备能力与{topic}的目标状态之间需要建立参数化差距矩阵。",
            "在研型号和技术成熟度决定能力画像的近期升级或新概念属性。",
        ]
    if agent_id == "operational_employment":
        return [
            f"{topic}需要结合COA、兵力协同和经验教训判断可用作战样式。",
            "作战运用约束用于校验能力画像是否能进入真实任务链条。",
        ]
    return [f"{agent_id} produced baseline finding for {topic} under {route}."]


def _public_smoke_url_for_agent(agent_id: str) -> str:
    urls = {
        "international_situation": "https://www.gov.cn/",
        "combat_scenario": "http://www.81.cn/",
        "weapon_equipment": "https://www.mod.gov.cn/",
        "operational_employment": "http://www.81.cn/",
    }
    return urls.get(agent_id, "https://www.gov.cn/")
