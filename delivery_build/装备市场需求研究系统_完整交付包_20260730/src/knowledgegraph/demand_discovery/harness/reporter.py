"""Reporter-agent wrapper for autonomous demand-discovery reports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from knowledgegraph.demand_discovery.domain.store import DomainStore
from knowledgegraph.demand_discovery.domain.tools import generate_demand_report_tool
from knowledgegraph.demand_discovery.harness.agent_harness import DiscoveryHarness
from knowledgegraph.demand_discovery.harness.context_pack import ContextPack
from knowledgegraph.demand_discovery.harness.model_prompt import (
    DemandDiscoveryPromptBuilder,
)
from knowledgegraph.demand_discovery.harness.session_store import JsonlSessionStore
from knowledgegraph.demand_discovery.llm.model_config import DEFAULT_CONTEXT_TOKEN_BUDGET
from knowledgegraph.demand_discovery.tools.report_context import (
    create_expand_report_context_tool,
)


@dataclass(frozen=True)
class ReporterRunResult:
    report_id: str
    session_path: str
    final_text: str


async def run_reporter_agent(
    *,
    provider: Any,
    store: DomainStore,
    artifacts: Any,
    bundle_id: str,
    session_path: Path,
    system_prompt: str,
) -> ReporterRunResult:
    bundle = store.report_context_bundles[bundle_id]
    tools = [
        generate_demand_report_tool(store),
        create_expand_report_context_tool(bundle, artifacts),
    ]
    prompt = DemandDiscoveryPromptBuilder().build(
        ContextPack(
            agent_role="reporter",
            task_brief=(
                "Write the final Chinese military equipment demand report in the "
                "fixed three-layer, nine-item structure."
            ),
            sections={
                "report_context_bundle": bundle.to_dict(),
                "trace_summary": {"lineage_trace": list(bundle.lineage_trace)},
                "evidence_index": [
                    material.to_dict()
                    for material in bundle.materials
                    if material.material_type == "evidence"
                ],
                "open_questions": list(bundle.required_caveats),
            },
            token_budget=DEFAULT_CONTEXT_TOKEN_BUDGET,
        ),
        turn_objective=(
            "Use the Query as the primary reasoning anchor, compress the verified "
            "ReportContextBundle into high-value evidence, write the Chinese report "
            "with exactly three layers and nine items, and call "
            "generate_demand_report exactly once."
        ),
        tools=tools,
        hard_prohibitions=[
            "不得搜索、抓取网页、浏览器操作或创建新 EvidenceCard",
            "不得新增未在 ReportContextBundle 中出现的核心事实或引用 id",
            "审计不通过或证据不足时写成解释性降级报告，而不是虚构结论",
        ],
        authorized_scope={"report_context_bundle_id": bundle_id},
        parallel_tool_calls=False,
    )
    harness = DiscoveryHarness(
        provider=provider,
        tools=tools,
        domain_store=store,
        session_store=JsonlSessionStore(session_path),
        run_id=bundle.run_id,
        agent_run_id=f"reporter-{bundle.candidate_id}",
        worker_id="reporter",
        system_prompt="\n\n".join(
            part for part in [system_prompt.strip(), prompt.base_instructions] if part
        ),
        model_options={"parallel_tool_calls": prompt.parallel_tool_calls},
    )
    before = set(store.demand_reports)
    final = await harness.prompt(prompt.render_input())
    new_report_ids = [item for item in store.demand_reports if item not in before]
    report_id = new_report_ids[-1] if new_report_ids else ""
    if not report_id:
        raise RuntimeError("reporter did not generate a DemandReport")
    if isinstance(final.content, str):
        final_text = final.content
    else:
        final_text = "\n".join(block.text for block in final.content if block.text)
    return ReporterRunResult(
        report_id=report_id,
        session_path=str(session_path),
        final_text=final_text,
    )
