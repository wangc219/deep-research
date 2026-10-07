"""Prompt loading helpers for demand discovery workers."""

from __future__ import annotations

from typing import Any

from knowledgegraph.demand_discovery.workers.agent_defs import AgentDef
from knowledgegraph.demand_discovery.workers.roles import (
    AUDIT_WORKER,
    HORIZON_SCANNER,
    READER,
    SYNTHESIZER,
)


ROLE_PROMPTS: dict[str, str] = {
    HORIZON_SCANNER: "Find source signals within the allowed source scope.",
    READER: "Read selected material and produce evidence-oriented summaries.",
    SYNTHESIZER: "Synthesize evidence into candidate demand proposals.",
    AUDIT_WORKER: "Audit candidate demands against evidence and uncertainty.",
}

WRAP_UP_PROMPT = (
    "预算已进入收尾态。停止发起新检索、新阅读或新 worker；"
    "只能整理已有发现，写入已确认的来源、证据、候选、审核和报告；"
    "列出未解问题与下一步建议后结束。"
)

COMPACTION_PROMPT = (
    "Summarize the earlier demand-discovery research memory. Preserve current "
    "demand assumptions, key evidence claims, counter-evidence, excluded "
    "directions, open questions, and next investigation steps."
)


def prompt_for_role(role: str) -> str:
    return ROLE_PROMPTS.get(role, "")


def render_system_prompt(agent_def: AgentDef, run_context: dict[str, Any]) -> str:
    """Render an agent markdown prompt with runtime context appended."""

    context_lines = [
        "",
        "Runtime context:",
        f"- run_id: {run_context.get('run_id', '')}",
        f"- date: {run_context.get('date', '')}",
        "- source_registry_summary: "
        f"{run_context.get('source_registry_summary', 'not configured')}",
    ]
    if "budget" in run_context:
        context_lines.append(f"- budget: {run_context['budget']}")
    return agent_def.system_prompt.rstrip() + "\n" + "\n".join(context_lines)
