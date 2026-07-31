"""Agent runner for semantic report-context curation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from knowledgegraph.demand_discovery.domain.report_context import CuratedReportItem
from knowledgegraph.demand_discovery.harness.agent_harness import DiscoveryHarness
from knowledgegraph.demand_discovery.harness.context_pack import ContextPack
from knowledgegraph.demand_discovery.harness.model_prompt import DemandDiscoveryPromptBuilder
from knowledgegraph.demand_discovery.harness.report_context import (
    ReportContextCandidatePool,
)
from knowledgegraph.demand_discovery.harness.session_store import JsonlSessionStore
from knowledgegraph.demand_discovery.llm.model_config import DEFAULT_CONTEXT_TOKEN_BUDGET
from knowledgegraph.demand_discovery.tools.report_context import (
    create_record_report_context_curation_tool,
)


async def run_report_context_curator_agent(
    *,
    provider: Any,
    pool: ReportContextCandidatePool,
    session_path: Path,
    system_prompt: str,
) -> list[CuratedReportItem]:
    recorded_items: list[CuratedReportItem] = []

    def on_recorded(items: list[CuratedReportItem]) -> None:
        recorded_items.clear()
        recorded_items.extend(items)

    tools = [create_record_report_context_curation_tool(pool, on_recorded)]
    prompt = DemandDiscoveryPromptBuilder().build(
        ContextPack(
            agent_role="context_curator",
            task_brief="Curate verified report context materials.",
            sections={
                "report_context_candidate_pool": _pool_payload(pool),
                "open_questions": list(pool.required_caveats),
                "trace_summary": {"lineage_trace": list(pool.lineage_trace)},
            },
            token_budget=DEFAULT_CONTEXT_TOKEN_BUDGET,
        ),
        turn_objective=(
            "Merge near-duplicate report materials, choose permitted report uses, "
            "preserve caveats, and call record_report_context_curation exactly once."
        ),
        tools=tools,
        hard_prohibitions=[
            "不得搜索、抓取网页、读取新文档或创建 EvidenceCard",
            "不得新增 ReportContextCandidatePool 中不存在的 material_id",
            "不得把 limitation/open_question 材料策展为确定性 core 结论",
        ],
        authorized_scope={"report_context_bundle_id": pool.bundle_id},
        parallel_tool_calls=False,
    )
    harness = DiscoveryHarness(
        provider=provider,
        tools=tools,
        session_store=JsonlSessionStore(session_path),
        run_id=pool.run_id,
        agent_run_id=f"context-curator-{pool.candidate_id}",
        worker_id="context_curator",
        system_prompt="\n\n".join(
            part for part in [system_prompt.strip(), prompt.base_instructions] if part
        ),
        model_options={"parallel_tool_calls": prompt.parallel_tool_calls},
    )
    await harness.prompt(prompt.render_input())
    if not recorded_items:
        raise RuntimeError("context curator did not record curated report context")
    return list(recorded_items)


def _pool_payload(pool: ReportContextCandidatePool) -> dict[str, Any]:
    return {
        "bundle_id": pool.bundle_id,
        "run_id": pool.run_id,
        "topic": pool.topic,
        "candidate_id": pool.candidate_id,
        "judgement_id": pool.judgement_id,
        "audit_id": pool.audit_id,
        "review_status": pool.review_status,
        "control_brief": dict(pool.control_brief),
        "lineage_trace": list(pool.lineage_trace),
        "materials": [material.to_dict() for material in pool.materials],
        "allowed_evidence_ids": list(pool.allowed_evidence_ids),
        "blocked_claims": list(pool.blocked_claims),
        "required_caveats": list(pool.required_caveats),
    }
