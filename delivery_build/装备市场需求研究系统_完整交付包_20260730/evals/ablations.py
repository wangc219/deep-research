from __future__ import annotations

from pathlib import Path
from typing import Any
import json

import yaml

from .adapters import FullMethodAdapter, SystemAdapter
from .models import EvalQuery, EvalRunResult


DOMAIN_AGENT_IDS = {
    "international_situation",
    "combat_scenario",
    "weapon_equipment",
    "operational_employment",
    "scenario_divergence",
    "case_research",
    "technology_radar",
    "opponent_monitoring",
    "system_confrontation",
    "cross_domain_fusion",
    "nontraditional_security",
}


def build_no_domain_agents_config(project_root: str | Path, sandbox_dir: str | Path) -> Path:
    """Create an eval-local registry without changing the production registry."""
    project_root = Path(project_root)
    sandbox_dir = Path(sandbox_dir)
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    source_path = project_root / "configs" / "equipment_deep_research" / "agents.yaml"
    payload = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}
    agents = [
        dict(item)
        for item in payload.get("agents", [])
        if str(item.get("agent_id", "")) not in DOMAIN_AGENT_IDS
    ]
    template = next(
        dict(item)
        for item in payload.get("agents", [])
        if str(item.get("agent_id")) == "weapon_equipment"
    )
    template.update(
        {
            "agent_id": "generic_researcher",
            "display_name": "受限通用检索Agent",
            "description": (
                "只进行通用公开资料检索和事实摘录，不承担军事场景建模、装备能力映射、"
                "技术成熟度判断、作战运用综合或多专业融合。"
            ),
            "harness_profile": "discovery_research_v1",
            "skill_ids": [],
            "knowledge_pack_ids": [],
            # Do not grant synthetic coverage for the specialist roles being
            # ablated.  The downstream chain must see the real information
            # loss instead of treating one generic packet as nine experts.
            "capability_tags": ["general_research", "open_source_retrieval"],
            "tools": ["search_sources", "fetch_page", "create_evidence_card"],
            "skills": [
                {
                    "name": "general_public_research",
                    "objective": "进行非垂类公开资料检索、来源整理和事实摘录。",
                    "method": (
                        "按Query关键词检索并摘录来源；禁止生成装备需求、能力差距、作战机理、"
                        "成熟度结论或跨来源军事综合。"
                    ),
                }
            ],
            "research_policy": {
                "search_tracks": ["通用公开资料"],
                "target_source_count": 2,
                "evidence_accept_target": 2,
                "evidence_min_count": 1,
                "evidence_min_domains": 1,
                "evidence_materialize_attempts": 2,
                "search_intensity": "light",
                "max_search_batches": 1,
                "min_source_families": 1,
                "require_counter_evidence": False,
                "required_outputs": ["来源清单", "事实摘录", "来源冲突", "未决问题"],
                "stopping_conditions": ["核心关键词已有公开来源", "事实与推断已分离"],
            },
            "model_profile": {
                "provider": "codex",
                "model": payload.get("default_model", "gpt-5.5"),
                "reasoning_effort": "medium",
                "max_output_tokens": 1800,
                "search_context_size": "low",
            },
            "context_policy": {
                "visible_sections": [
                    "task",
                    "evidence_policy",
                    "own_checkpoint",
                    "recall_request",
                ],
                "token_budget": 2800,
                "max_items_per_section": 4,
                "hide_other_agent_raw_sessions": True,
            },
            "handoff_policy": {
                "accept_from": [],
                "wait_for": [],
                "publish_to": ["winning_mechanism"],
                "publish_fields": ["findings", "evidence_ids", "confidence", "open_questions"],
            },
            "output_contract": {
                "name": "baseline_finding_packet",
                "properties": ["source_summary", "fact_extracts", "source_conflicts", "open_questions"],
            },
            "object_read_scopes": ["ResearchProblem", "EvidenceCard", "WorkingCheckpoint"],
            "object_write_scopes": ["EvidenceCard", "BaselineFindingPacket", "WorkingCheckpoint"],
            "enabled": True,
            "system_agent": False,
        }
    )
    agents.append(template)
    target = sandbox_dir / "agents.no-domain.yaml"
    target.write_text(
        yaml.safe_dump({"default_model": payload.get("default_model", "gpt-5.5"), "agents": agents}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    # The registry resolves harness.yaml next to the generated agent config.
    harness_source = source_path.parent / "harness.yaml"
    (sandbox_dir / "harness.yaml").write_bytes(harness_source.read_bytes())
    return target


class NoDomainAgentsAdapter(FullMethodAdapter):
    def __init__(
        self,
        project_root: str | Path,
        sandbox_dir: str | Path,
        *,
        mode: str = "fake",
        system_id: str = "no_domain_agents",
    ) -> None:
        agent_config = build_no_domain_agents_config(project_root, sandbox_dir)
        super().__init__(
            project_root,
            mode=mode,
            agent_config=agent_config,
            agent_ids=["generic_researcher"],
            max_rounds=None,
            stage_policy_id="no_multisource_baseline",
            system_id=system_id,
        )


class NoWinningMechanismAdapter(FullMethodAdapter):
    def __init__(self, project_root: str | Path, *, mode: str = "fake") -> None:
        super().__init__(
            project_root,
            mode=mode,
            max_rounds=1,
            stage_policy_id="no_winning_mechanism",
            system_id="no_winning_mechanism",
        )


class ArtifactViewAblationAdapter(SystemAdapter):
    """Ablate downstream reasoning by exposing only allowed run artifacts.

    The production process remains untouched.  These variants are quality
    ablations, not latency ablations, because the source run still completes.
    """

    def __init__(self, project_root: str | Path, variant: str, *, mode: str = "fake") -> None:
        if variant not in {"no_winning_chain", "no_feedback_loops"}:
            raise ValueError(f"unsupported artifact-view ablation: {variant}")
        self.system_id = variant
        self.project_root = Path(project_root)
        self.source_system_id = f"{variant}_source"
        self.source = FullMethodAdapter(
            project_root,
            mode=mode,
            max_rounds=1 if variant == "no_feedback_loops" else None,
            system_id=self.source_system_id,
        )

    def run(self, query: EvalQuery, *, eval_id: str, output_dir: Path) -> EvalRunResult:
        source_result = self.source.run(query, eval_id=eval_id, output_dir=output_dir)
        if source_result.status != "completed":
            source_result.system_id = self.system_id
            return source_result
        run_dir = output_dir / "runtime" / f"{self.source_system_id}-{query.query_id.lower()}"
        try:
            rows = _read_domain_rows(run_dir / "domain.jsonl")
            if self.system_id == "no_winning_chain":
                answer, citations = _baseline_only_report(query.query, rows)
            else:
                answer, citations = _first_pass_report(query.query, rows)
            return EvalRunResult(
                eval_id=eval_id,
                query_id=query.query_id,
                system_id=self.system_id,
                status="completed",
                answer=answer,
                citations=citations,
                sources=citations,
                duration_seconds=source_result.duration_seconds,
                usage=source_result.usage,
                model_snapshot={**source_result.model_snapshot, "ablation_view": self.system_id},
                artifact_refs=source_result.artifact_refs,
            )
        except Exception as exc:
            return EvalRunResult(
                eval_id=eval_id,
                query_id=query.query_id,
                system_id=self.system_id,
                status="failed",
                error=str(exc)[:5000],
            )


def _read_domain_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _baseline_only_report(topic: str, rows: list[dict[str, Any]]) -> tuple[str, list[str]]:
    packets = [row["payload"] for row in rows if row.get("type") == "BaselineFindingPacket"]
    evidence = [row["payload"] for row in rows if row.get("type") == "EvidenceCard"]
    if not packets:
        raise ValueError("run has no baseline packets")
    lines = [f"# {topic}", "", "## 基础研究发现"]
    for packet in packets:
        lines.append(f"\n### {packet.get('agent_id', 'research')}\n")
        for finding in packet.get("findings", []):
            lines.append(f"- {finding}")
        for question in packet.get("open_questions", []):
            lines.append(f"- 待验证：{question}")
    citations = sorted({str(item.get("source_url")) for item in evidence if item.get("source_url")})
    lines.extend(["", "## 公开来源", *[f"- {url}" for url in citations]])
    lines.extend(["", "该版本仅汇总基础研究Agent结果，不使用S1–S6、L1–L3或能力画像。"])
    return "\n".join(lines), citations


def _first_pass_report(topic: str, rows: list[dict[str, Any]]) -> tuple[str, list[str]]:
    first_packets: dict[str, dict[str, Any]] = {}
    first_nodes: dict[int, dict[str, Any]] = {}
    evidence: list[dict[str, Any]] = []
    for row in rows:
        payload = row.get("payload", {})
        if row.get("type") == "EvidenceCard":
            evidence.append(payload)
        elif row.get("type") == "BaselineFindingPacket":
            first_packets.setdefault(str(payload.get("agent_id", "research")), payload)
        elif row.get("type") == "WinningReasoningNode":
            try:
                step = int(payload.get("step", 0))
            except (TypeError, ValueError):
                step = 0
            if step:
                first_nodes.setdefault(step, payload)
    lines = [f"# {topic}", "", "## 单轮研究发现"]
    for packet in first_packets.values():
        lines.extend(f"- {finding}" for finding in packet.get("findings", []))
    if first_nodes:
        lines.extend(["", "## 首轮分析"])
        for step, node in sorted(first_nodes.items()):
            lines.append(f"- S{step} {node.get('title', '')}：{node.get('summary', '')}")
    citations = sorted({str(item.get("source_url")) for item in evidence if item.get("source_url")})
    lines.extend(["", "## 公开来源", *[f"- {url}" for url in citations]])
    lines.extend(["", "该版本只保留每个Agent和分析步骤的首次结果，不使用后续Recall、批判或回溯结果。"])
    return "\n".join(lines), citations
