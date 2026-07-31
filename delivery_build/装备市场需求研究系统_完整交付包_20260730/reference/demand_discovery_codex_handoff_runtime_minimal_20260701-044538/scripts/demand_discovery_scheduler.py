from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from knowledgegraph.demand_discovery.domain.audit_rubric import load_default_rubric  # noqa: E402
from knowledgegraph.demand_discovery.domain.source_registry import (  # noqa: E402
    SourceRegistry,
    default_source_whitelist_path,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.domain.tools import build_all_tools  # noqa: E402
from knowledgegraph.demand_discovery.harness.agent_harness import DiscoveryHarness  # noqa: E402
from knowledgegraph.demand_discovery.harness.budget import RunBudget  # noqa: E402
from knowledgegraph.demand_discovery.harness.cancellation import CancelToken  # noqa: E402
from knowledgegraph.demand_discovery.harness.context_pack import ContextPackBuilder  # noqa: E402
from knowledgegraph.demand_discovery.harness.event_bus import EventBus, ProgressWriter  # noqa: E402
from knowledgegraph.demand_discovery.harness.intervention import (  # noqa: E402
    FileInbox,
    attach_file_inbox,
)
from knowledgegraph.demand_discovery.harness.scheduled_runner import (  # noqa: E402
    ScheduledRunner,
)
from knowledgegraph.demand_discovery.harness.session_store import JsonlSessionStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.trace_store import DomainTraceStore  # noqa: E402
from knowledgegraph.demand_discovery.llm.config_env import (  # noqa: E402
    env_value,
    load_demand_discovery_dotenv,
)
from knowledgegraph.demand_discovery.llm.fake_provider import FakeProvider, FakeResponse  # noqa: E402
from knowledgegraph.demand_discovery.llm.model_config import (  # noqa: E402
    DEFAULT_REAL_MODEL,
    ModelConfig,
)
from knowledgegraph.demand_discovery.llm.responses_adapter import ResponsesProvider  # noqa: E402
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    dotenv = load_demand_discovery_dotenv(PROJECT_ROOT)
    parser = argparse.ArgumentParser(description="Run demand discovery scheduled tasks.")
    parser.add_argument("--mode", choices=["fake", "real"], default="fake")
    parser.add_argument(
        "--tasks-dir",
        default=str(PROJECT_ROOT / "configs" / "demand_discovery" / "scheduled_tasks"),
    )
    parser.add_argument(
        "--done-dir",
        default=str(PROJECT_ROOT / "outputs" / "scheduled" / "done"),
    )
    parser.add_argument(
        "--output-root",
        default=str(PROJECT_ROOT / "outputs" / "scheduled" / "runs"),
    )
    parser.add_argument(
        "--source-whitelist",
        default=str(default_source_whitelist_path()),
    )
    parser.add_argument(
        "--endpoint-mode",
        choices=["responses_compatible", "codex_backend", "custom_endpoint"],
        default=env_value("DEMAND_DISCOVERY_ENDPOINT_MODE", dotenv, "responses_compatible"),
    )
    parser.add_argument(
        "--base-url",
        default=env_value("DEMAND_DISCOVERY_BASE_URL", dotenv, "https://api.openai.com"),
    )
    parser.add_argument(
        "--endpoint-path",
        default=env_value("DEMAND_DISCOVERY_ENDPOINT_PATH", dotenv, ""),
    )
    parser.add_argument(
        "--model",
        default=env_value("DEMAND_DISCOVERY_MODEL", dotenv, DEFAULT_REAL_MODEL),
    )
    parser.add_argument(
        "--api-key-env",
        default=env_value(
            "DEMAND_DISCOVERY_API_KEY_ENV",
            dotenv,
            "DEMAND_DISCOVERY_API_KEY",
        ),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one scheduler tick instead of polling forever.",
    )
    parser.add_argument("--poll-interval-seconds", type=int, default=60)
    args = parser.parse_args(argv)

    runner = ScheduledRunner(
        args.tasks_dir,
        args.done_dir,
        _run_factory(args, dotenv),
        poll_interval_s=args.poll_interval_seconds,
        log_path=PROJECT_ROOT / "outputs" / "scheduled" / "runner.log",
    )
    if args.once:
        triggered = asyncio.run(runner.tick())
        print("\n".join(triggered))
        return 0
    try:
        asyncio.run(runner.run_forever())
    except KeyboardInterrupt:
        return 130
    return 0


def _run_factory(args, dotenv):
    async def run(task) -> dict:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"sched-{stamp}-{task.task_name}"
        run_dir = Path(args.output_root) / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        artifact_dir = run_dir / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        registry = SourceRegistry.load(args.source_whitelist)
        artifacts = ArtifactStore(artifact_dir)
        store = DomainStore(tier_status_cap=registry.tier_status_cap)
        trace_store = DomainTraceStore()
        rubric = load_default_rubric()
        bus = EventBus()
        progress_path = run_dir / "progress.md"
        progress_writer = ProgressWriter(progress_path)
        provider = _provider_for_task(args, dotenv, task)
        budget = _run_budget_from_task(task)
        cancel_token = _cancel_token_from_task(task)
        harness = DiscoveryHarness(
            provider=provider,
            tools=build_all_tools(store, registry, artifacts, rubric=rubric),
            session_store=JsonlSessionStore(run_dir / "orchestrator.jsonl", run_id=run_id),
            trace_store=trace_store,
            domain_store=store,
            context_builder=ContextPackBuilder(),
            run_id=run_id,
            agent_run_id="orchestrator",
            worker_id="orchestrator",
            event_bus=bus,
            budget=budget,
            cancel_token=cancel_token,
        )
        inbox = FileInbox(run_dir / "inbox")
        attach_file_inbox(
            bus,
            harness,
            inbox,
            run_id=run_id,
            agent_run_id="orchestrator",
            listen_agent_run_id="orchestrator",
        )
        assistant = await harness.prompt(_task_prompt(task))
        if assistant.is_error:
            raise RuntimeError(assistant.metadata.get("error_message", "scheduled run failed"))
        progress_writer.write(
            run_id=run_id,
            task_brief=task.task_brief,
            worker_states=[],
            domain_store=store,
        )
        domain_path = run_dir / "domain.jsonl"
        trace_path = run_dir / "trace.jsonl"
        store.export_jsonl(domain_path)
        _write_trace_jsonl(trace_path, trace_store)
        return {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "sources": len(store.sources),
            "evidence": len(store.evidence),
            "candidates": len(store.candidates),
            "reports": len(store.demand_reports),
            "progress_path": str(progress_path),
            "domain_path": str(domain_path),
            "trace_path": str(trace_path),
            "inbox_path": str(inbox.inbox_dir),
            "budget": budget.remaining_summary() if budget is not None else None,
        }

    return run


def _run_budget_from_task(task) -> RunBudget | None:
    budget = dict(getattr(task, "budget", {}) or {})
    max_tokens = _positive_int_or_none(budget.get("max_tokens"))
    max_tool_calls = _positive_int_or_none(budget.get("max_tool_calls"))
    max_wall_clock_ms = _positive_int_or_none(budget.get("max_wall_clock_ms"))
    if max_tokens is None and max_tool_calls is None and max_wall_clock_ms is None:
        return None
    return RunBudget(
        max_tokens=max_tokens,
        max_tool_calls=max_tool_calls,
        max_wall_clock_ms=max_wall_clock_ms,
    )


def _cancel_token_from_task(task) -> CancelToken | None:
    budget = dict(getattr(task, "budget", {}) or {})
    timeout_ms = _positive_int_or_none(budget.get("max_wall_clock_ms"))
    if timeout_ms is None:
        return None
    return CancelToken(timeout_ms=timeout_ms)


def _positive_int_or_none(value) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _provider_for_task(args, dotenv, task):
    if args.mode == "fake":
        provider = FakeProvider()
        provider.set_responses(
            [
                FakeResponse(
                    tool_calls=[
                        {
                            "id": "scheduled-signal",
                            "name": "create_or_update_candidate",
                            "arguments": {
                                "candidate_id": f"sched-{task.task_name}",
                                "title": task.task_name,
                                "demand_statement": task.task_brief or task.task_name,
                                "status": "raw_signal",
                                "evidence_ids": [],
                                "open_questions": [
                                    "Fake scheduled run only verifies runner wiring."
                                ],
                            },
                        }
                    ]
                ),
                FakeResponse(text="scheduled fake run completed"),
            ]
        )
        return provider
    api_key = env_value(args.api_key_env, dotenv)
    if not api_key:
        raise ValueError(f"missing API key env {args.api_key_env}")
    return ResponsesProvider(
        ModelConfig(
            provider="real",
            model=args.model,
            base_url=args.base_url,
            endpoint_mode=args.endpoint_mode,
            endpoint_path=args.endpoint_path,
            api_key_env=args.api_key_env,
            timeout_ms=180_000,
            max_retries=0,
        ),
        api_key,
    )


def _task_prompt(task) -> str:
    return (
        "Run this scheduled demand-discovery task. "
        "Keep outputs in signal/candidate registries; do not generate a formal "
        "demand report unless the task brief explicitly asks for one. "
        f"Task name: {task.task_name}. "
        f"Task brief: {task.task_brief}. "
        f"Source filter: {json.dumps(task.source_filter, ensure_ascii=False)}. "
        f"Budget: {json.dumps(task.budget, ensure_ascii=False)}."
    )


def _write_trace_jsonl(path: Path, trace_store: DomainTraceStore) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for event in trace_store.events():
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True))
            handle.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
