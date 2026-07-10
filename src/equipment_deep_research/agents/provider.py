from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from equipment_deep_research.agents.registry import AgentDef
from equipment_deep_research.domain.models import BaselineFindingPacket, EvidenceCard


@dataclass(frozen=True)
class AgentRunRequest:
    run_id: str
    agent: AgentDef
    topic: str
    research_route: str
    context: dict


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
        evidence = EvidenceCard(
            evidence_id=f"ev-{agent.agent_id}-1",
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
            packet_id=f"packet-{agent.agent_id}",
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
            checkpoint=f"{agent.agent_id}: baseline complete",
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
