"""Phase 5 network worker-round executor for autonomous demand discovery.

The Phase 5 research loop owns orchestration, judgement, audit and report
generation. This module only runs one evidence-collection worker round with
network, browser and open-search tools.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from knowledgegraph.demand_discovery.domain.audit_rubric import load_default_rubric
from knowledgegraph.demand_discovery.domain.open_search import open_search_plan_from_dict
from knowledgegraph.demand_discovery.domain.source_registry import (
    SourceRegistry,
    default_source_whitelist_path,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore
from knowledgegraph.demand_discovery.domain.tools import build_all_tools
from knowledgegraph.demand_discovery.harness.agent_harness import DiscoveryHarness
from knowledgegraph.demand_discovery.harness.context_pack import ContextPackBuilder
from knowledgegraph.demand_discovery.harness.session_store import JsonlSessionStore
from knowledgegraph.demand_discovery.harness.tools import ToolDefinition
from knowledgegraph.demand_discovery.harness.trace_store import DomainTraceStore
from knowledgegraph.demand_discovery.llm.fake_provider import FakeProvider, FakeResponse
from knowledgegraph.demand_discovery.llm.model_config import DEFAULT_REAL_MODEL, ModelConfig
from knowledgegraph.demand_discovery.llm.responses_adapter import ResponsesProvider
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore
from knowledgegraph.demand_discovery.tools.network import (
    HttpTransport,
    build_whitelist_hook,
)
from knowledgegraph.demand_discovery.tools.open_search_adapters import (
    default_open_search_adapters_path,
    load_open_search_adapters,
)
from knowledgegraph.demand_discovery.tools.search import OpenSearchAdapter


@dataclass(frozen=True)
class NetworkWorkerRoundResult:
    run_id: str
    run_dir: Path
    domain_path: Path
    trace_path: Path
    progress_path: Path
    artifact_dir: Path
    evidence_ids: list[str]
    trace_event_count: int
    report_trace_event_count: int = 0
    error: str = ""
    final_text: str = ""


async def run_network_worker_round(
    *,
    mode: str,
    topic: str,
    seed_urls: list[str] | None,
    output_root: Path,
    run_id: str,
    round_id: str = "",
    source_whitelist_path: str | Path | None = None,
    endpoint_mode: str = "responses_compatible",
    base_url: str = "https://api.openai.com",
    endpoint_path: str = "",
    model: str = DEFAULT_REAL_MODEL,
    api_key_env: str = "DEMAND_DISCOVERY_API_KEY",
    api_key: str | None = None,
    http_transport: HttpTransport | None = None,
    allow_browser: bool = False,
    source_guidance: list[dict[str, Any]] | None = None,
    planned_tasks: list[dict[str, Any]] | None = None,
    allow_open_search: bool = False,
    open_search_plan_id: str = "",
    open_search_plan_payload: dict[str, Any] | None = None,
    open_search_adapters: list[OpenSearchAdapter] | None = None,
    open_search_config_path: str | Path | None = None,
) -> NetworkWorkerRoundResult:
    """Run one Phase 5 network worker round without candidate/audit/report tools."""

    if mode not in {"fake", "real"}:
        raise ValueError("mode must be fake or real")
    seed_urls = list(seed_urls or [])
    if not seed_urls:
        raise ValueError("network worker round requires at least one seed URL")

    run_dir = output_root / run_id
    artifact_dir = run_dir / "artifacts"
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    registry = SourceRegistry.load(source_whitelist_path or default_source_whitelist_path())
    for url in seed_urls:
        if registry.match(url) is None:
            raise ValueError(f"seed URL is outside source whitelist: {url}")

    artifacts = ArtifactStore(artifact_dir)
    store = DomainStore(tier_status_cap=registry.tier_status_cap)
    resolved_open_search_adapters: list[OpenSearchAdapter] = []
    if allow_open_search:
        if open_search_plan_payload is None:
            raise ValueError("open_search_plan_payload is required when allow_open_search is enabled")
        plan = open_search_plan_from_dict(open_search_plan_payload)
        if open_search_plan_id and plan.plan_id != open_search_plan_id:
            raise ValueError("open_search_plan_id does not match open_search_plan_payload")
        open_search_plan_id = plan.plan_id
        store.upsert_open_search_plan(plan)
        resolved_open_search_adapters = (
            list(open_search_adapters)
            if open_search_adapters is not None
            else load_open_search_adapters(
                open_search_config_path or default_open_search_adapters_path()
            )
        )
        if not resolved_open_search_adapters:
            raise ValueError(
                "open search adapters are required when allow_open_search is enabled"
            )
    trace_store = DomainTraceStore()
    rubric = load_default_rubric()
    round_label = round_id or "round-1"
    provider = (
        _fake_worker_round_provider(seed_urls)
        if mode == "fake"
        else _real_provider(
            api_key=api_key,
            api_key_env=api_key_env,
            endpoint_mode=endpoint_mode,
            base_url=base_url,
            endpoint_path=endpoint_path,
            model=model,
        )
    )
    tools = _worker_round_tools(
        store,
        registry,
        artifacts,
        rubric=rubric,
        fetch_http_transport=http_transport,
        allow_browser=allow_browser,
        allow_open_search=allow_open_search,
        open_search_adapters=resolved_open_search_adapters,
    )
    harness = DiscoveryHarness(
        provider=provider,
        tools=tools,
        session_store=JsonlSessionStore(run_dir / "worker.jsonl", run_id=run_id),
        trace_store=trace_store,
        domain_store=store,
        context_builder=ContextPackBuilder(),
        run_id=run_id,
        agent_run_id="network-worker",
        worker_id="reader",
        system_prompt=_load_reader_prompt(),
        before_tool_call=build_whitelist_hook(registry),
    )
    assistant = await harness.prompt(
        _worker_round_brief(
            topic,
            seed_urls,
            round_label,
            source_guidance=list(source_guidance or []),
            planned_tasks=list(planned_tasks or []),
            allow_open_search=allow_open_search,
            open_search_plan_id=open_search_plan_id,
            open_search_queries=(
                list(store.open_search_plans[open_search_plan_id].queries)
                if open_search_plan_id in store.open_search_plans
                else []
            ),
            allow_browser=allow_browser,
        )
    )
    error = ""
    if assistant.is_error:
        error = str(assistant.metadata.get("error_message", "") or "network worker failed")

    domain_path = run_dir / "domain.jsonl"
    trace_path = run_dir / "trace.jsonl"
    progress_path = run_dir / "progress.md"
    store.export_jsonl(domain_path)
    _write_trace_jsonl(trace_path, trace_store)
    _write_worker_round_progress(
        progress_path,
        run_id=run_id,
        topic=topic,
        round_id=round_label,
        evidence_ids=sorted(store.evidence),
        error=error,
    )
    _write_run_config(
        run_dir / "run_config.json",
        {
            "run_id": run_id,
            "mode": mode,
            "topic": topic,
            "round_id": round_label,
            "seed_urls": seed_urls,
            "source_whitelist_path": str(source_whitelist_path or default_source_whitelist_path()),
            "endpoint_mode": endpoint_mode if mode == "real" else None,
            "model": model if mode == "real" else None,
            "allow_browser": allow_browser,
            "allow_open_search": allow_open_search,
            "open_search_plan_id": open_search_plan_id,
            "open_search_config_path": (
                str(open_search_config_path or default_open_search_adapters_path())
                if allow_open_search and open_search_adapters is None
                else None
            ),
            "open_search_adapter_count": len(resolved_open_search_adapters),
            "source_guidance": list(source_guidance or []),
            "planned_tasks": list(planned_tasks or []),
            "path": "phase5_network_worker_round",
        },
    )
    if error and not store.evidence:
        raise RuntimeError(f"network worker round failed: {error}")

    return NetworkWorkerRoundResult(
        run_id=run_id,
        run_dir=run_dir,
        domain_path=domain_path,
        trace_path=trace_path,
        progress_path=progress_path,
        artifact_dir=artifact_dir,
        evidence_ids=sorted(store.evidence),
        trace_event_count=len(trace_store.events()),
        report_trace_event_count=0,
        error=error,
        final_text=_assistant_text(assistant),
    )


def run_network_worker_round_sync(**kwargs) -> NetworkWorkerRoundResult:
    return asyncio.run(run_network_worker_round(**kwargs))


def _load_reader_prompt() -> str:
    prompt_path = Path(__file__).resolve().parent / "workers" / "agents" / "reader.md"
    return prompt_path.read_text(encoding="utf-8")


def _assistant_text(message) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    return "\n".join(
        str(getattr(block, "text", ""))
        for block in list(content or [])
        if getattr(block, "type", "") == "text"
    )


_NETWORK_WORKER_ROUND_TOOL_NAMES = {
    "acquire_whitelist_documents",
    "read_acquired_document",
    "search_sources",
    "open_search_sources",
    "open_search_sources_batch",
    "fetch_open_source_page",
    "fetch_page",
    "classify_source_page",
    "discover_articles",
    "download_document",
    "read_document",
    "extract_summary",
    "browser_observe",
    "browser_execute",
    "create_source_record",
    "assess_source_quality",
    "create_evidence_card",
}


def _worker_round_tools(
    store: DomainStore,
    registry: SourceRegistry,
    artifacts: ArtifactStore,
    *,
    rubric,
    fetch_http_transport: HttpTransport | None,
    allow_browser: bool,
    allow_open_search: bool = False,
    open_search_adapters: list[OpenSearchAdapter] | None = None,
) -> list[ToolDefinition]:
    return [
        tool
        for tool in build_all_tools(
            store,
            registry,
            artifacts,
            rubric=rubric,
            fetch_http_transport=fetch_http_transport,
            enable_browser_tools=allow_browser,
            enable_open_search_tools=allow_open_search,
            open_search_adapters=open_search_adapters,
        )
        if tool.name in _NETWORK_WORKER_ROUND_TOOL_NAMES
    ]


def _real_provider(
    *,
    api_key: str | None,
    api_key_env: str,
    endpoint_mode: str,
    base_url: str,
    endpoint_path: str,
    model: str,
) -> ResponsesProvider:
    resolved_api_key = api_key if api_key is not None else os.environ.get(api_key_env, "")
    if not resolved_api_key:
        raise ValueError(f"missing API key env {api_key_env}")
    return ResponsesProvider(
        ModelConfig(
            provider="real",
            model=model,
            base_url=base_url,
            endpoint_mode=endpoint_mode,
            endpoint_path=endpoint_path,
            api_key_env=api_key_env,
            timeout_ms=180_000,
            max_retries=2,
        ),
        resolved_api_key,
    )


def _fake_worker_round_provider(seed_urls: list[str]) -> FakeProvider:
    provider = FakeProvider()
    seed_url = seed_urls[0]
    source_id = _source_id_for_url(seed_url)

    def classify_after_fetch(context, state):
        artifact_ref = _last_artifact_ref(context.messages)
        return FakeResponse(
            tool_calls=[
                {
                    "id": "classify-seed",
                    "name": "classify_source_page",
                    "arguments": {
                        "url": seed_url,
                        "artifact_ref": artifact_ref,
                        "topic": "低空无人机探测预警能力缺口",
                    },
                }
            ]
        ).build(context, state)

    def read_after_classify(context, state):
        ref = _last_simplified_ref(context.messages)
        return FakeResponse(
            tool_calls=[
                {
                    "id": "read-seed",
                    "name": "read_document",
                    "arguments": {
                        "artifact_ref": ref,
                        "offset": 0,
                        "limit": 5,
                    },
                }
            ]
        ).build(context, state)

    def evidence_after_read(context, state):
        ref = _last_simplified_ref(context.messages)
        return FakeResponse(
            tool_calls=[
                {
                    "id": "evidence-seed",
                    "name": "create_evidence_card",
                    "arguments": {
                        "evidence_id": "ev-network-worker-1",
                        "source_id": source_id,
                        "claim": "复杂低空环境暴露探测预警能力缺口",
                        "evidence_summary": (
                            "正文材料显示低空无人机探测预警仍需多源融合和快速告警。"
                        ),
                        "excerpt": "复杂环境下低空无人机探测预警能力需求仍有短板。",
                        "source_location": f"{ref}#para:0",
                        "evidence_assessment": "strong",
                    },
                }
            ]
        ).build(context, state)

    provider.set_responses(
        [
            FakeResponse(
                tool_calls=[
                    {
                        "id": "fetch-seed",
                        "name": "fetch_page",
                        "arguments": {"url": seed_url, "force_refresh": True},
                    }
                ]
            ),
            FakeResponse(factory=classify_after_fetch),
            FakeResponse(factory=read_after_classify),
            FakeResponse(factory=evidence_after_read),
            FakeResponse(
                text=(
                    "findings:\n"
                    "- 复杂低空环境暴露探测预警能力缺口\n"
                    "open_questions:\n"
                    "- 继续补充白名单正文材料交叉验证能力缺口\n"
                    "risks:\n"
                    "- 需要核验不同信源对探测、防护链路的覆盖差异\n"
                    "need_more_sources: true"
                )
            ),
        ]
    )
    return provider


def _worker_round_brief(
    topic: str,
    seed_urls: list[str],
    round_id: str,
    *,
    source_guidance: list[dict[str, Any]] | None = None,
    planned_tasks: list[dict[str, Any]] | None = None,
    allow_open_search: bool = False,
    open_search_plan_id: str = "",
    open_search_queries: list[str] | None = None,
    allow_browser: bool = False,
) -> str:
    guidance_text = _source_guidance_brief(source_guidance or [])
    planned_tasks_text = _planned_tasks_brief(planned_tasks or [])
    open_search_text = _open_search_brief(
        allow_open_search=allow_open_search,
        open_search_plan_id=open_search_plan_id,
        open_search_queries=open_search_queries or [],
        allow_browser=allow_browser,
    )
    browser_text = _browser_research_brief(allow_browser=allow_browser)
    return (
        "Run one Phase 5 autonomous research worker round. "
        f"Round id: {round_id}. "
        f"Topic / hypothesis: {topic}. "
        "Use only the provided whitelisted seed URLs: "
        f"{', '.join(seed_urls)}. "
        f"{guidance_text}"
        f"{planned_tasks_text}"
        f"{open_search_text}"
        f"{browser_text}"
        "Use acquire_whitelist_documents as the default whitelist acquisition path: "
        "call it with a query_bundle derived from the topic, worker assignment, or "
        "judge follow-up task before manually chaining lower-level source tools. "
        "Use query_bundle.queries rows with text, language, and intent fields; do "
        "not call this tool with a legacy top-level query field. It searches "
        "whitelisted sources through tool-side routing and "
        "returns compact document previews, document_id values, and per-source control status. "
        "After reviewing previews, select useful document_id values and call "
        "read_acquired_document for deeper paragraph reading. Do not request, invent, "
        "or rely on internal artifact references for acquired documents. "
        "The low-level fetch/search tools are fallback tools for targeted rereads, "
        "debugging a failed route, or following an exact URL returned by "
        "acquire_whitelist_documents. Derive narrower follow-up "
        "queries from the topic, worker findings, or previous next_round_plan; "
        "do not fall back to static source default-query terms. "
        "Use the target source language for search and discovery: Chinese-language "
        "sites should be queried in Chinese, English-language sites in English. "
        "When looking for additional research website leads, formulate the "
        "discovery/search query in the target site's language. "
        "Always write analytic outputs in Chinese, including findings, "
        "EvidenceCard.claim, EvidenceCard.evidence_summary, open_questions, and "
        "risks; keep source titles, excerpts, and quoted text in the original "
        "source language when needed. "
        "Worker self-check is mandatory before finalizing your answer. If current "
        "evidence is adjacent-only, listing/search-only, or missing article/PDF "
        "body evidence, continue with follow-up research instead of finalizing. "
        "You may revise query language, use source profile routes, inspect "
        "browser/API candidates, download documents, or mark the source blocked "
        "after exhausting the budget. Do not output strong findings without "
        "evidence refs. Put unsupported claims into discarded_findings or "
        "remaining blind spots. "
        "Find whitelisted article leads; search_sources may discover JavaScript-backed "
        "same-site search APIs without needing site-specific instructions. "
        "Fetch/read the most relevant whitelisted search hit when it looks like "
        "an article or document. "
        "For each seed URL, first use fetch_page and classify_source_page. "
        "If the page is listing, site_home, or search_page, use discover_articles; "
        "then fetch or download at least one exact URL printed under "
        "discover_articles selected_leads; do not guess or rewrite article years, "
        "paths, or slugs. Use read_document on the selected article body or "
        "downloaded document body. "
        "If a seed page is already an article, use read_document on the fetched "
        "simplified_ref before creating evidence. "
        "EvidenceCard is allowed only after reading an article body or downloaded "
        "document body; source_location must be the exact simplified_ref#para:n "
        "shown by read_document. Do not create EvidenceCard from listing pages, "
        "site home pages, search results, navigation text, 404/access-status pages, "
        "or outside-whitelist URLs. "
        "This is a worker-only round: do not create candidates, do not run audit, "
        "do not generate a demand report, and do not record judgement. "
        "End with compact sections named findings, open_questions, risks, and "
        "need_more_sources."
    )


def _browser_research_brief(*, allow_browser: bool) -> str:
    if not allow_browser:
        return ""
    return (
        "Browser tools are enabled. Use browser_observe only after HTTP/search/"
        "download/read_document cannot discover a needed article, document, "
        "search form, pagination link, or download target. Use browser_execute "
        "target_action with target_id values from browser_observe. JavaScript "
        "mode is allowed only after an observation_ref exists, with a clear "
        "intent, expected_result, why_standard_actions_are_insufficient, "
        "result_sink, and fallback, for public same-origin read-only page "
        "inspection or API probing. result_sink must keep JavaScript output in "
        "lead/artifact/diagnosis/recipe only, never EvidenceCard. Use "
        "capture_current_document to save the "
        "current article/search/download page as an artifact, then use "
        "read_document before evidence creation. Do not create EvidenceCard "
        "from browser observation, search result pages, listing pages, or raw "
        "JavaScript API responses. "
    )


def _planned_tasks_brief(planned_tasks: list[dict[str, Any]]) -> str:
    if not planned_tasks:
        return ""
    rows = ["Planned judge follow-up tasks:"]
    for task in planned_tasks:
        task_id = str(task.get("task_id", "")).strip()
        objective = str(task.get("objective", "")).strip()
        routing_hint = str(task.get("routing_hint", "")).strip()
        source_scope = str(task.get("source_scope", "")).strip()
        worker_brief = str(task.get("worker_brief", "")).strip()
        query_revisions = task.get("query_revisions", [])
        queries: list[str] = []
        if isinstance(query_revisions, list):
            for item in query_revisions:
                if isinstance(item, dict):
                    query = str(item.get("query", "")).strip()
                else:
                    query = str(item).strip()
                if query:
                    queries.append(query)
        rows.append(
            "- "
            f"{task_id or 'task'} | objective={objective} | "
            f"routing_hint={routing_hint} | source_scope={source_scope} | "
            f"queries={'; '.join(queries)} | brief={worker_brief}"
        )
    return " ".join(rows) + " "


def _open_search_brief(
    *,
    allow_open_search: bool,
    open_search_plan_id: str,
    open_search_queries: list[str],
    allow_browser: bool = False,
) -> str:
    if not allow_open_search:
        return ""
    queries = "; ".join(open_search_queries)
    browser_anchor = ""
    if allow_browser:
        browser_anchor = (
            "Use provider-backed open_search_sources_batch/open_search_sources as the open-web search path. "
            "If provider-returned URLs require rendering or interaction, use "
            "browser_observe/browser_execute only within the authorized URL scope to "
            "capture article, document, or download-page leads. If provider search "
            "returns no usable hits, record a blind spot instead of inventing a "
            "search-engine results-page anchor. "
        )
    return (
        "A controller-authorized OpenSearchPlan is active for this round. "
        f"open_search_plan_id={open_search_plan_id}. "
        f"Allowed open search queries: {queries}. "
        "Prefer open_search_sources_batch with all useful allowed queries in one call; "
        "use open_search_sources only for a single exact allowed query or targeted retry. "
        f"{browser_anchor}"
        "For open_web leads, use fetch_open_source_page, then read_document, "
        "then assess_source_quality with basis_artifact_refs and body_location_refs "
        "from the fetched body before creating SourceRecord/EvidenceCard. "
        "Do not use open search results directly as evidence. "
    )


def _source_guidance_brief(source_guidance: list[dict[str, Any]]) -> str:
    if not source_guidance:
        return ""
    rows = ["Source search-language guidance:"]
    for item in source_guidance:
        languages = ", ".join(str(value) for value in item.get("content_languages", []))
        queries = "; ".join(str(value) for value in item.get("planned_queries", [])[:3])
        rows.append(
            "- "
            f"{item.get('url', '')} | {item.get('source_name', '')} | "
            f"languages={languages or 'unknown'} | planned_queries={queries}"
        )
    return " ".join(rows) + " "


def _source_id_for_url(url: str) -> str:
    return f"src-{hashlib.sha256(url.encode('utf-8')).hexdigest()[:12]}"


def _last_artifact_ref(messages: list[Any]) -> str:
    for message in reversed(messages):
        content = getattr(message, "content", "")
        if not isinstance(content, str):
            continue
        match = re.search(r"artifact_ref:\s*([a-z_]+:[0-9a-f]{16})", content)
        if match:
            return match.group(1)
    raise RuntimeError("fetch_page did not return artifact_ref")


def _last_simplified_ref(messages: list[Any]) -> str:
    for message in reversed(messages):
        content = getattr(message, "content", "")
        if not isinstance(content, str):
            continue
        match = re.search(r"simplified_ref:\s*([a-z_]+:[0-9a-f]{16})", content)
        if match:
            return match.group(1)
    raise RuntimeError("fetch_page did not return simplified_ref")


def _write_trace_jsonl(path: Path, trace_store: DomainTraceStore) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for event in trace_store.events():
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _write_worker_round_progress(
    path: Path,
    *,
    run_id: str,
    topic: str,
    round_id: str,
    evidence_ids: list[str],
    error: str,
) -> None:
    rows = [
        f"# {run_id}",
        "",
        "Phase 5 network worker round.",
        f"- round_id: {round_id}",
        f"- topic: {topic}",
        f"- evidence: {len(evidence_ids)}",
    ]
    if evidence_ids:
        rows.append(f"- evidence_ids: {', '.join(evidence_ids)}")
    if error:
        rows.append(f"- error: {error}")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _write_run_config(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
