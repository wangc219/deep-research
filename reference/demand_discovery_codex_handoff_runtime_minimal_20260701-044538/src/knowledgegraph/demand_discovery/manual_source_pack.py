"""Manual source-pack runner for controlled real-provider practice runs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Any

from knowledgegraph.demand_discovery.domain.audit_rubric import load_default_rubric
from knowledgegraph.demand_discovery.domain.report import REQUIRED_SECTIONS
from knowledgegraph.demand_discovery.domain.store import DomainStore
from knowledgegraph.demand_discovery.domain.tools import build_domain_tools
from knowledgegraph.demand_discovery.harness.agent_harness import DiscoveryHarness
from knowledgegraph.demand_discovery.harness.budget import RunBudget
from knowledgegraph.demand_discovery.harness.context_pack import ContextPackBuilder
from knowledgegraph.demand_discovery.harness.event_bus import EventBus
from knowledgegraph.demand_discovery.harness.intervention import (
    FileInbox,
    attach_file_inbox,
)
from knowledgegraph.demand_discovery.harness.session_store import JsonlSessionStore
from knowledgegraph.demand_discovery.harness.trace_store import DomainTraceStore
from knowledgegraph.demand_discovery.llm.fake_provider import FakeProvider, FakeResponse


@dataclass
class ManualSourcePack:
    pack_id: str
    path: Path
    raw: dict[str, Any]
    topic_brief: str
    research_goal: str
    allowed_tools: list[str]
    disallowed_tools: list[str]
    suggested_ids: dict[str, str]
    sources: list[dict[str, Any]]


@dataclass
class ManualSourcePackRunResult:
    run_id: str
    run_dir: Path
    pack_id: str
    source_count: int
    evidence_count: int
    candidate_id: str
    audit_conclusion: str
    report_id: str
    trace_event_count: int
    lineage_event_types: list[str]
    report_path: Path
    domain_path: Path
    trace_path: Path
    run_config_path: Path


def load_manual_source_pack(path: str | Path) -> ManualSourcePack:
    pack_path = Path(path)
    data = json.loads(pack_path.read_text(encoding="utf-8"))
    pack_id = _required_str(data, "pack_id")
    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("source pack must include at least one source")
    constraints = data.get("run_constraints")
    if not isinstance(constraints, dict):
        raise ValueError("source pack missing run_constraints")
    allowed_tools = _required_str_list(constraints, "allowed_tools")
    disallowed_tools = [
        str(item) for item in constraints.get("disallowed_tools", []) if str(item)
    ]
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError(f"source at index {index} must be an object")
        _required_str(source, "source_id")
        evidence_seed = source.get("evidence_seed")
        if not isinstance(evidence_seed, dict):
            raise ValueError(f"source {source['source_id']} missing evidence_seed")
        _required_str(evidence_seed, "evidence_id")
        _required_str(evidence_seed, "excerpt")
        _required_str(evidence_seed, "source_location")
    return ManualSourcePack(
        pack_id=pack_id,
        path=pack_path,
        raw=data,
        topic_brief=_required_str(data, "topic_brief"),
        research_goal=str(data.get("research_goal", "")),
        allowed_tools=allowed_tools,
        disallowed_tools=disallowed_tools,
        suggested_ids=dict(data.get("suggested_ids", {})),
        sources=list(sources),
    )


async def run_manual_source_pack(
    *,
    provider: Any,
    source_pack_path: str | Path,
    output_root: str | Path,
    run_id: str | None = None,
    endpoint_mode: str = "",
    base_url: str = "",
    model: str = "",
    budget: RunBudget | None = None,
    require_report: bool = True,
) -> ManualSourcePackRunResult:
    pack = load_manual_source_pack(source_pack_path)
    resolved_run_id = run_id or _default_run_id(pack.pack_id)
    run_dir = Path(output_root) / resolved_run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    store = DomainStore()
    trace_store = DomainTraceStore()
    bus = EventBus()
    session_store = JsonlSessionStore(run_dir / "session.jsonl", run_id=resolved_run_id)
    tools = _allowed_domain_tools(pack, store)
    harness = DiscoveryHarness(
        provider=provider,
        tools=tools,
        session_store=session_store,
        trace_store=trace_store,
        domain_store=store,
        context_builder=ContextPackBuilder(),
        run_id=resolved_run_id,
        agent_run_id="orchestrator",
        worker_id="orchestrator",
        budget=budget,
        event_bus=bus,
    )
    attach_file_inbox(
        bus,
        harness,
        FileInbox(run_dir / "inbox"),
        run_id=resolved_run_id,
        agent_run_id="orchestrator",
        listen_agent_run_id="orchestrator",
    )
    harness.set_active_tools(pack.allowed_tools)

    _write_run_config(
        run_dir / "run_config.json",
        pack=pack,
        run_id=resolved_run_id,
        endpoint_mode=endpoint_mode,
        base_url=base_url,
        model=model,
        budget=budget,
    )
    _copy_review_checklist(pack.path, run_dir / "manual_review_checklist.md")

    assistant = await harness.prompt(build_manual_source_pack_prompt(pack))
    if assistant.is_error:
        _write_outputs(run_dir, store, trace_store, report_id="")
        error_message = assistant.metadata.get("error_message", "")
        raise RuntimeError(f"provider error: {error_message or 'unknown error'}")

    report_id = next(iter(store.demand_reports.keys()), "")
    _write_outputs(run_dir, store, trace_store, report_id=report_id)
    if require_report and not report_id:
        raise RuntimeError(
            "manual source pack run did not produce a demand report "
            f"(sources={len(store.sources)}, evidence={len(store.evidence)}, "
            f"candidates={len(store.candidates)}, audits={len(store.audit_reports)})"
        )

    lineage = trace_store.get_report_trace(report_id) if report_id else []
    candidate_id = next(iter(store.candidates.keys()), "")
    audit = next(iter(store.audit_reports.values()), None)
    return ManualSourcePackRunResult(
        run_id=resolved_run_id,
        run_dir=run_dir,
        pack_id=pack.pack_id,
        source_count=len(store.sources),
        evidence_count=len(store.evidence),
        candidate_id=candidate_id,
        audit_conclusion=audit.conclusion if audit is not None else "",
        report_id=report_id,
        trace_event_count=len(trace_store.events()),
        lineage_event_types=[event.event_type for event in lineage],
        report_path=run_dir / "report.md",
        domain_path=run_dir / "domain.jsonl",
        trace_path=run_dir / "trace.jsonl",
        run_config_path=run_dir / "run_config.json",
    )


def run_manual_source_pack_sync(**kwargs: Any) -> ManualSourcePackRunResult:
    return asyncio.run(run_manual_source_pack(**kwargs))


def build_manual_source_pack_prompt(pack: ManualSourcePack) -> str:
    prompt_pack = {
        "pack_id": pack.pack_id,
        "topic_brief": pack.topic_brief,
        "research_goal": pack.research_goal,
        "run_constraints": pack.raw.get("run_constraints", {}),
        "suggested_ids": pack.suggested_ids,
        "candidate_guidance": pack.raw.get("candidate_guidance", {}),
        "audit_expectations": pack.raw.get("audit_expectations", {}),
        "audit_rubric_item_ids": load_default_rubric().item_ids,
        "sources": pack.sources,
    }
    return (
        "Run a controlled manual source-pack demand discovery practice.\n"
        "Use only the allowed tools. Do not search, fetch, browse, read new "
        "documents, or call tools outside the source pack constraints.\n"
        "Register every source exactly once with create_source_record. Create "
        "every SourceRecord first, then wait for tool results before creating "
        "EvidenceCard records. After evidence tool results return, synthesize at "
        "most one CandidateDemand using the suggested candidate id when evidence "
        "supports a task scenario and capability gap. After candidate tool results "
        "return, run audit. After audit tool results return, only call "
        "generate_demand_report if the audit conclusion is approved, pass, or "
        "通过 and the report gate is met.\n"
        "Demand type rule: default to demand_type inferred for multi-source "
        "synthesis, combined signals, trend-to-gap reasoning, or residual-gap "
        "analysis; only use explicit when a source directly states an equivalent "
        "demand statement rather than merely describing a trend, hotspot, "
        "constraint, or solution clue.\n"
        "When generating the report, prefer structured sections with these keys: "
        f"{', '.join(REQUIRED_SECTIONS)}. Keep the writing in zh-CN unless source "
        "titles or identifiers are in English.\n\n"
        "SOURCE_PACK_JSON:\n"
        f"{json.dumps(prompt_pack, ensure_ascii=False, indent=2, sort_keys=True)}"
    )


def build_fake_source_pack_provider(pack: ManualSourcePack) -> FakeProvider:
    provider = FakeProvider()
    provider.set_responses(_fake_responses(pack))
    return provider


def format_manual_source_pack_result(result: ManualSourcePackRunResult) -> str:
    return "\n".join(
        [
            f"Run ID: {result.run_id}",
            f"Pack: {result.pack_id}",
            f"Sources: {result.source_count}",
            f"Evidence: {result.evidence_count}",
            f"Candidate ID: {result.candidate_id}",
            f"Audit: {result.audit_conclusion}",
            f"Report ID: {result.report_id}",
            f"Trace events: {result.trace_event_count}",
            f"Lineage events: {', '.join(result.lineage_event_types)}",
            f"Run dir: {result.run_dir}",
        ]
    )


def _allowed_domain_tools(pack: ManualSourcePack, store: DomainStore) -> list[Any]:
    available = {tool.name: tool for tool in build_domain_tools(store)}
    unknown = [name for name in pack.allowed_tools if name not in available]
    if unknown:
        raise ValueError(f"source pack references unknown allowed tool: {unknown[0]}")
    return [available[name] for name in pack.allowed_tools]


def _write_outputs(
    run_dir: Path,
    store: DomainStore,
    trace_store: DomainTraceStore,
    *,
    report_id: str,
) -> None:
    store.export_jsonl(run_dir / "domain.jsonl")
    _write_jsonl(
        run_dir / "trace.jsonl",
        [
            {"type": "DomainTraceEvent", "payload": event.to_dict()}
            for event in trace_store.events()
        ],
    )
    (run_dir / "report.md").write_text(
        _render_report_markdown(store, trace_store, report_id),
        encoding="utf-8",
    )


def _render_report_markdown(
    store: DomainStore,
    trace_store: DomainTraceStore,
    report_id: str,
) -> str:
    lines: list[str] = []
    if report_id and report_id in store.demand_reports:
        report = store.demand_reports[report_id]
        candidate = store.candidates.get(report.candidate_id)
        audit = store.audit_reports.get(report.audit_id)
        lines.extend([report.body.strip(), "", "## Run Metadata"])
        lines.append(f"- report_id: {report.report_id}")
        lines.append(f"- candidate_id: {report.candidate_id}")
        lines.append(f"- audit_id: {report.audit_id}")
        if candidate is not None:
            lines.append(f"- candidate_status: {candidate.status}")
        if audit is not None:
            lines.append(f"- audit_conclusion: {audit.conclusion}")
            lines.append(f"- audit_comments: {audit.comments}")
        lines.append("")
        lineage = trace_store.get_report_trace(report_id)
    else:
        lines.extend(["# Manual Source Pack Run", "", "No DemandReport generated.", ""])
        lineage = trace_store.events()
    lines.extend(["## Trace Lineage"])
    for event in lineage:
        lines.append(
            "- "
            f"{event.event_type} | {event.target_type}:{event.target_id} | "
            f"inputs={','.join(event.input_refs)} | "
            f"outputs={','.join(event.output_refs)}"
        )
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def _write_run_config(
    path: Path,
    *,
    pack: ManualSourcePack,
    run_id: str,
    endpoint_mode: str,
    base_url: str,
    model: str,
    budget: RunBudget | None,
) -> None:
    payload = {
        "run_id": run_id,
        "pack_id": pack.pack_id,
        "source_pack_path": str(pack.path),
        "created_at": _now_iso(),
        "topic_brief": pack.topic_brief,
        "research_goal": pack.research_goal,
        "allowed_tools": list(pack.allowed_tools),
        "disallowed_tools": list(pack.disallowed_tools),
        "provider": {
            "endpoint_mode": endpoint_mode,
            "base_url": base_url,
            "model": model,
        },
        "budget": budget.remaining_summary() if budget is not None else None,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _copy_review_checklist(pack_path: Path, target: Path) -> None:
    source = pack_path.with_name(f"{pack_path.stem}_review_checklist.md")
    if source.exists():
        shutil.copyfile(source, target)
        return
    target.write_text(
        "# Manual Review Checklist\n\nNo source-pack checklist was found.\n",
        encoding="utf-8",
    )


def _fake_responses(pack: ManualSourcePack) -> list[FakeResponse]:
    source_calls: list[dict[str, Any]] = []
    evidence_calls: list[dict[str, Any]] = []
    evidence_ids: list[str] = []
    for source in pack.sources:
        source_payload = {
            key: value
            for key, value in source.items()
            if key != "evidence_seed"
        }
        source_calls.append(
            {
                "id": f"call-source-{source['source_id']}",
                "name": "create_source_record",
                "arguments": source_payload,
            }
        )
    for source in pack.sources:
        seed = dict(source["evidence_seed"])
        seed["source_id"] = source["source_id"]
        evidence_ids.append(str(seed["evidence_id"]))
        evidence_calls.append(
            {
                "id": f"call-evidence-{seed['evidence_id']}",
                "name": "create_evidence_card",
                "arguments": seed,
            }
        )
    candidate_id = pack.suggested_ids.get(
        "candidate_id", f"cand-{pack.pack_id}"
    )
    audit_id = pack.suggested_ids.get("audit_id", f"audit-{pack.pack_id}")
    report_id = pack.suggested_ids.get("report_id", f"report-{pack.pack_id}")
    fake_expectations = dict(pack.raw.get("fake_run_expectations", {}))
    audit_conclusion = str(fake_expectations.get("audit_conclusion", "approved"))
    required_rework = [
        str(item) for item in fake_expectations.get("required_rework", [])
    ]
    audit_conclusion = str(fake_expectations.get("audit_conclusion", "approved"))
    scorecard_verdict = str(fake_expectations.get("scorecard_verdict", "pass"))
    rubric = load_default_rubric()
    scorecard = {
        item_id: {
            "verdict": _fake_scorecard_verdict(
                item_id,
                scorecard_verdict,
                audit_conclusion,
                rubric.veto_ids,
            ),
            "reason": "manual source pack fake fixture covers this rubric item",
        }
        for item_id in rubric.item_ids
    }
    scorecard["evidence_support"] = {
        "verdict": (
            "pass"
            if audit_conclusion.strip().lower() in {"approved", "pass", "通过"}
            else "doubt"
        ),
        "reason": "manual source pack fake fixture reviews every evidence seed",
        "evidence_reviews": {
            evidence_id: {
                "evidence_id": evidence_id,
                "support_level": "direct",
                "support_type": "inferred_gap",
                "used_for_core": True,
                "reason": "source pack body evidence is provided as direct fixture support",
                "missing_link": "",
            }
            for evidence_id in evidence_ids
        },
    }
    generate_report = bool(
        fake_expectations.get(
            "generate_report",
            audit_conclusion.strip().lower() in {"approved", "pass", "通过"},
        )
    )
    demand_statement = str(
        pack.raw.get("candidate_guidance", {}).get(
            "possible_demand_statement_seed",
            pack.topic_brief,
        )
    )
    responses = [
        FakeResponse(tool_calls=source_calls),
        FakeResponse(tool_calls=evidence_calls),
        FakeResponse(
            tool_calls=[
                {
                "id": "call-candidate",
                "name": "create_or_update_candidate",
                "arguments": {
                    "candidate_id": candidate_id,
                    "title": str(
                        fake_expectations.get(
                            "candidate_title",
                            "低空小型无人机探测预警与协同防护能力缺口",
                        )
                    ),
                    "demand_statement": demand_statement,
                    "evidence_ids": evidence_ids,
                    "open_questions": list(
                        pack.raw.get("audit_expectations", {}).get(
                            "expected_open_questions", []
                        )
                    ),
                    "solution_signals": list(
                        fake_expectations.get(
                            "solution_signals",
                            [
                                "多源探测",
                                "分布式被动感知",
                                "跨组织态势共享",
                            ],
                        )
                    ),
                },
                }
            ]
        ),
        FakeResponse(
            tool_calls=[
                {
                "id": "call-audit",
                "name": "run_audit",
                "arguments": {
                    "audit_id": audit_id,
                    "candidate_id": candidate_id,
                    "conclusion": audit_conclusion,
                    "scorecard": scorecard,
                    "comments": str(
                        fake_expectations.get(
                            "audit_comments",
                            "manual source pack fake run; human review still required",
                        )
                    ),
                    "required_rework": required_rework,
                },
                }
            ]
        ),
    ]
    if generate_report:
        responses.append(
            FakeResponse(
                tool_calls=[
                    {
                    "id": "call-report",
                    "name": "generate_demand_report",
                    "arguments": {
                        "report_id": report_id,
                        "candidate_id": candidate_id,
                        "title": str(
                            fake_expectations.get(
                                "report_title",
                                "低空小型无人机探测预警与协同防护能力缺口调查报告",
                            )
                        ),
                        "sections": _fake_report_sections(pack),
                        "demand_type": str(
                            pack.raw.get("candidate_guidance", {}).get(
                                "demand_type", "inferred"
                            )
                        ),
                        "related_technical_directions": list(
                            fake_expectations.get(
                                "related_technical_directions",
                                [
                                    "低空多源探测",
                                    "早期预警与 cue 生成",
                                    "跨站点态势共享",
                                ],
                            )
                        ),
                        "solution_clues": list(
                            fake_expectations.get(
                                "solution_clues",
                                [
                                    "分布式被动传感是线索之一，但不是唯一方案",
                                ],
                            )
                        ),
                        "evidence_ids": evidence_ids,
                        "audit_id": audit_id,
                    },
                    }
                ]
            )
        )
    responses.append(FakeResponse(text="manual source pack run complete"))
    return responses


def _fake_scorecard_verdict(
    item_id: str,
    requested_verdict: str,
    audit_conclusion: str,
    veto_ids: set[str],
) -> str:
    verdict = requested_verdict.strip().lower()
    if (
        verdict == "fail"
        and item_id in veto_ids
        and audit_conclusion.strip().lower() not in {"rejected", "不通过"}
    ):
        return "doubt"
    return verdict


def _fake_report_sections(pack: ManualSourcePack) -> dict[str, str]:
    guidance = pack.raw.get("candidate_guidance", {})
    open_questions = pack.raw.get("audit_expectations", {}).get(
        "expected_open_questions", []
    )
    return {
        "core_conclusion": str(guidance.get("preferred_focus", pack.topic_brief)),
        "task_scenario": "要地、机场、设施和行动单元面对低空小型无人机活动时，需要形成可审计的探测和预警闭环。",
        "threat_or_environment": "公开资料显示，小型无人机活动增加，部署环境受低空遮蔽、复杂空域、法律与协同流程约束影响。",
        "capability_gap": str(
            guidance.get("possible_demand_statement_seed", pack.topic_brief)
        ),
        "existing_solutions_and_residual_gaps": (
            "声学等分布式被动感知是方案线索，但报告主结论不绑定单一传感器；"
            "残余缺口在于多源告警、跨组织共享和真实部署约束下的验证。"
        ),
        "counter_evidence_and_limits": "不同场景不能直接外推；机场、国土防御和战场经验需要分开验证。",
        "risks_and_constraints": "需避免写成武器方案，保留法律、空域、电磁兼容、误报和跨部门流程约束。",
        "open_questions": "\n".join(f"- {item}" for item in open_questions),
        "next_steps": "人工复盘证据可追溯性、候选需求表述、审核拦截效果和报告结构，再决定是否修 prompt/量表/模板。",
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"source pack missing required string: {key}")
    return value


def _required_str_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list) or not value:
        raise ValueError(f"source pack missing required list: {key}")
    return [str(item) for item in value if str(item)]


def _default_run_id(pack_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{pack_id}-{stamp}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
