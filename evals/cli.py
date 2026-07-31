from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any, Callable
import argparse
import json
import os

from .ablations import (
    ArtifactViewAblationAdapter,
    NoDomainAgentsAdapter,
    NoWinningMechanismAdapter,
)
from .adapters import SystemAdapter, make_adapter
from .aggregate import aggregate_pairwise
from .config import config_status, load_eval_config, resolved_system_config
from .judging import judge_pair_file
from .models import EvalQuery, EvalRunResult, read_jsonl, write_jsonl
from .pairwise import build_blind_pairs
from .query_import import import_expert_workbook


SYSTEM_IDS = (
    "full_method",
    "generic_deep_research",
    "generic_agent",
    "bare_llm",
    "zhipu_llm",
    "no_domain_agents",
    "no_winning_chain",
    "no_feedback_loops",
    "no_multisource_baseline",
    "no_winning_mechanism",
)


def main(argv: list[str] | None = None) -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Sidecar benchmark for equipment deep research")
    sub = parser.add_subparsers(dest="command", required=True)

    config_cmd = sub.add_parser("config-check", help="validate real baseline configuration without exposing secrets")
    config_cmd.add_argument("--config", default=str(project_root / "evals" / "config.yaml"))
    config_cmd.add_argument("--systems", default=None, help="comma-separated systems to require")
    config_cmd.add_argument("--require-ready", action="store_true")

    import_cmd = sub.add_parser("import-queries", help="import expert-reviewed queries from Excel")
    import_cmd.add_argument("--workbook", required=True)
    import_cmd.add_argument("--output", default=str(project_root / "evals" / "data" / "expert_queries_v1"))
    import_cmd.add_argument("--total", type=int, default=132)
    import_cmd.add_argument("--pilot-count", type=int, default=12)
    import_cmd.add_argument("--seed", type=int, default=20260718)
    import_cmd.add_argument(
        "--allow-unreviewed",
        action="store_true",
        help="import candidate queries for local testing when expert columns are incomplete",
    )

    validate_cmd = sub.add_parser("validate", help="validate an imported public query set")
    validate_cmd.add_argument("--queries", required=True)
    validate_cmd.add_argument("--pilot-count", type=int, default=12)
    validate_cmd.add_argument("--test-count", type=int, default=120)

    run_cmd = sub.add_parser("run", help="run one or more benchmark systems")
    run_cmd.add_argument("--queries", required=True)
    run_cmd.add_argument("--eval-id", required=True)
    run_cmd.add_argument("--systems", default="full_method,generic_deep_research")
    run_cmd.add_argument("--split", choices=["pilot", "test", "all"], default="pilot")
    run_cmd.add_argument("--limit", type=int, default=None)
    run_cmd.add_argument("--fake", action="store_true")
    run_cmd.add_argument("--resume", action="store_true")
    run_cmd.add_argument("--output-root", default=str(project_root / "outputs" / "evals"))
    run_cmd.add_argument("--config", default=str(project_root / "evals" / "config.yaml"))

    pair_cmd = sub.add_parser("pair", help="create blinded A/B pairs")
    pair_cmd.add_argument("--queries", required=True)
    pair_cmd.add_argument("--results", required=True)
    pair_cmd.add_argument("--left", required=True, choices=SYSTEM_IDS)
    pair_cmd.add_argument("--right", required=True, choices=SYSTEM_IDS)
    pair_cmd.add_argument("--output", required=True)
    pair_cmd.add_argument("--seed", type=int, default=20260718)
    pair_cmd.add_argument("--single-order", action="store_true")

    judge_cmd = sub.add_parser("judge", help="judge blinded pairs")
    judge_cmd.add_argument("--pairs", required=True)
    judge_cmd.add_argument("--prompt", default=str(project_root / "evals" / "pairwise_prompt_v1.md"))
    judge_cmd.add_argument("--judges", default="gpt-5.6-sol,gpt-5.4")
    judge_cmd.add_argument("--output", required=True)
    judge_cmd.add_argument("--fake", action="store_true")

    aggregate_cmd = sub.add_parser("aggregate", help="aggregate pairwise judgments")
    aggregate_cmd.add_argument("--judgments", required=True)
    aggregate_cmd.add_argument("--mapping", required=True)
    aggregate_cmd.add_argument("--results", default=None)
    aggregate_cmd.add_argument("--output", required=True)
    aggregate_cmd.add_argument("--bootstrap-samples", type=int, default=5000)

    smoke_cmd = sub.add_parser("smoke", help="run a one-query offline end-to-end smoke test")
    smoke_cmd.add_argument("--queries", required=True)
    smoke_cmd.add_argument("--eval-id", default="sidecar-smoke")
    smoke_cmd.add_argument("--output-root", default=str(project_root / "outputs" / "evals"))
    smoke_cmd.add_argument("--config", default=str(project_root / "evals" / "config.yaml"))

    args = parser.parse_args(argv)
    if args.command == "config-check":
        config = load_eval_config(args.config, project_root=project_root)
        selected = _parse_systems(args.systems) if args.systems else None
        status = config_status(config, selected_systems=selected)
        print(json.dumps(status, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if status["ready"] or not args.require_ready else 1
    if args.command == "import-queries":
        manifest = import_expert_workbook(
            args.workbook,
            args.output,
            total=args.total,
            pilot_count=args.pilot_count,
            seed=args.seed,
            require_expert_approval=not args.allow_unreviewed,
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "validate":
        result = validate_query_file(args.queries, pilot_count=args.pilot_count, test_count=args.test_count)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "run":
        output_root = _safe_eval_output(project_root, args.output_root)
        systems = _parse_systems(args.systems)
        config = load_eval_config(args.config, project_root=project_root)
        result = run_systems(
            project_root=project_root,
            queries_path=args.queries,
            eval_id=args.eval_id,
            systems=systems,
            split=args.split,
            output_root=output_root,
            limit=args.limit,
            fake=args.fake,
            resume=args.resume,
            config=config,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "pair":
        queries = [EvalQuery.from_dict(row) for row in read_jsonl(args.queries)]
        results = [EvalRunResult.from_dict(row) for row in read_jsonl(args.results)]
        result = build_blind_pairs(
            queries,
            results,
            args.output,
            left_system=args.left,
            right_system=args.right,
            seed=args.seed,
            include_reverse=not args.single_order,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "judge":
        judges = [item.strip() for item in args.judges.split(",") if item.strip()]
        result = judge_pair_file(args.pairs, args.prompt, args.output, judge_models=judges, fake=args.fake)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "aggregate":
        result = aggregate_pairwise(
            args.judgments,
            args.mapping,
            args.results,
            bootstrap_samples=args.bootstrap_samples,
        )
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "smoke":
        output_root = _safe_eval_output(project_root, args.output_root)
        config = load_eval_config(args.config, project_root=project_root)
        result = run_smoke(project_root, args.queries, args.eval_id, output_root, config=config)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    return 2


def validate_query_file(path: str | Path, *, pilot_count: int = 12, test_count: int = 120) -> dict[str, Any]:
    raw_rows = read_jsonl(path)
    queries = [EvalQuery.from_dict(row) for row in raw_rows]
    if len({item.query_id for item in queries}) != len(queries):
        raise ValueError("duplicate query_id found")
    if len({item.query.strip() for item in queries}) != len(queries):
        raise ValueError("duplicate query text found")
    actual_pilot = sum(item.split == "pilot" for item in queries)
    actual_test = sum(item.split == "test" for item in queries)
    if actual_pilot != pilot_count or actual_test != test_count:
        raise ValueError(f"expected {pilot_count}/{test_count} pilot/test queries; found {actual_pilot}/{actual_test}")
    expected_fields = {"query_id", "query", "region", "domain", "difficulty", "split"}
    if any(set(row) != expected_fields for row in raw_rows):
        raise ValueError("public query rows contain non-minimal or missing fields")
    return {
        "query_count": len(queries),
        "pilot_count": actual_pilot,
        "test_count": actual_test,
        "regions": sorted({item.region for item in queries}),
        "domains": sorted({item.domain for item in queries}),
    }


def run_systems(
    *,
    project_root: Path,
    queries_path: str | Path,
    eval_id: str,
    systems: list[str],
    split: str,
    output_root: Path,
    limit: int | None,
    fake: bool,
    resume: bool,
    config: dict[str, Any],
    system_overrides: dict[str, dict[str, Any]] | None = None,
    query_ids: list[str] | None = None,
    max_workers: int | None = None,
    injected_results: list[EvalRunResult] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    queries = [EvalQuery.from_dict(row) for row in read_jsonl(queries_path)]
    if query_ids:
        query_map = {item.query_id: item for item in queries}
        queries = [query_map[query_id] for query_id in query_ids if query_id in query_map]
    else:
        if split != "all":
            queries = [item for item in queries if item.split == split]
        if limit is not None:
            queries = queries[:limit]
    eval_root = output_root / eval_id
    eval_root.mkdir(parents=True, exist_ok=True)
    results_path = eval_root / "results.jsonl"
    existing_rows = read_jsonl(results_path) if resume and results_path.is_file() else []
    result_map = {
        (str(row["query_id"]), str(row["system_id"])): EvalRunResult.from_dict(row)
        for row in existing_rows
    }
    injected_keys: set[tuple[str, str]] = set()
    for item in injected_results or []:
        key = (item.query_id, item.system_id)
        result_map[key] = item
        injected_keys.add(key)
    tasks = [
        (system_id, query)
        for system_id in systems
        for query in queries
        if not (
            (query.query_id, system_id) in result_map
            and result_map[(query.query_id, system_id)].status == "completed"
            and (
                resume
                or (query.query_id, system_id) in injected_keys
            )
        )
    ]
    scheduled_systems = {system_id for system_id, _ in tasks}
    adapters = {
        system_id: _build_adapter(
            project_root,
            eval_root,
            system_id,
            fake=fake,
            config=config,
            system_overrides=system_overrides,
        )
        for system_id in systems
        if system_id in scheduled_systems
    }
    state_lock = Lock()
    completed_tasks = 0
    cancelled_tasks = 0

    def _flush() -> None:
        write_jsonl(results_path, [item.to_dict() for _, item in sorted(result_map.items())])

    def _run_task(system_id: str, query: EvalQuery) -> None:
        nonlocal completed_tasks, cancelled_tasks
        if cancel_requested is not None and cancel_requested():
            with state_lock:
                cancelled_tasks += 1
            return
        run_output = eval_root / "systems" / system_id / query.query_id
        run_output.mkdir(parents=True, exist_ok=True)
        # 参测系统之间相互独立、各自写入独立运行目录，回答内容与串行执行完全一致；
        # 并行只压缩墙钟等待，不改变任何单次运行的输入或产物。
        result = adapters[system_id].run(query, eval_id=eval_id, output_dir=run_output)
        with state_lock:
            result_map[(query.query_id, system_id)] = result
            _flush()
            completed_tasks += 1
            if progress_callback is not None:
                progress_callback(completed_tasks, len(tasks))

    # Persist injected reports even when every selected system is fully satisfied
    # by the shared report library and no adapter call is scheduled.
    _flush()
    workers = _system_worker_count(len(tasks), max_workers, fake=fake)
    if workers <= 1:
        for system_id, query in tasks:
            if cancel_requested is not None and cancel_requested():
                cancelled_tasks += len(tasks) - completed_tasks
                break
            _run_task(system_id, query)
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="eval-system") as pool:
            for future in [pool.submit(_run_task, system_id, query) for system_id, query in tasks]:
                future.result()
    results = list(result_map.values())
    evaluated_systems = {item.system_id for item in results}
    return {
        "eval_id": eval_id,
        "query_count": len(queries),
        "system_count": len(evaluated_systems),
        "result_count": len(results),
        "completed": sum(item.status == "completed" for item in results),
        "failed": sum(item.status == "failed" for item in results),
        "cancelled": bool(cancel_requested is not None and cancel_requested()),
        "cancelled_tasks": cancelled_tasks,
        "scheduled_tasks": len(tasks),
        "parallel_workers": workers,
        "results": str(results_path),
    }


def _system_worker_count(task_count: int, max_workers: int | None, *, fake: bool) -> int:
    if task_count <= 1:
        return 1
    if max_workers is not None:
        configured = max_workers
    else:
        env_value = os.environ.get("EQUIPMENT_EVAL_SYSTEM_CONCURRENCY", "")
        configured = int(env_value) if env_value.isdigit() and int(env_value) > 0 else 1
    return max(1, min(int(configured), task_count))


def run_smoke(
    project_root: Path,
    queries_path: str | Path,
    eval_id: str,
    output_root: Path,
    *,
    config: dict[str, Any],
) -> dict[str, Any]:
    run_result = run_systems(
        project_root=project_root,
        queries_path=queries_path,
        eval_id=eval_id,
        systems=["full_method", "generic_deep_research"],
        split="pilot",
        output_root=output_root,
        limit=1,
        fake=True,
        resume=False,
        config=config,
    )
    eval_root = output_root / eval_id
    query_rows = [EvalQuery.from_dict(row) for row in read_jsonl(queries_path)]
    query = next(item for item in query_rows if item.split == "pilot")
    results = [EvalRunResult.from_dict(row) for row in read_jsonl(eval_root / "results.jsonl")]
    pair_result = build_blind_pairs(
        [query],
        results,
        eval_root / "pairs",
        left_system="full_method",
        right_system="generic_deep_research",
    )
    judge_result = judge_pair_file(
        eval_root / "pairs" / "pairs.public.jsonl",
        project_root / "evals" / "pairwise_prompt_v1.md",
        eval_root / "judgments.jsonl",
        judge_models=["fake-judge-a", "fake-judge-b"],
        fake=True,
    )
    aggregate = aggregate_pairwise(
        eval_root / "judgments.jsonl",
        eval_root / "pairs" / "pairs.admin.jsonl",
        eval_root / "results.jsonl",
        bootstrap_samples=200,
    )
    (eval_root / "summary.json").write_text(json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"run": run_result, "pairs": pair_result, "judges": judge_result, "summary": str(eval_root / "summary.json")}


def _build_adapter(
    project_root: Path,
    eval_root: Path,
    system_id: str,
    *,
    fake: bool,
    config: dict[str, Any],
    system_overrides: dict[str, dict[str, Any]] | None = None,
) -> SystemAdapter:
    if system_id in {"full_method", "generic_deep_research", "generic_agent", "bare_llm", "zhipu_llm"}:
        system_config = (
            resolved_system_config(config, system_id)
            if system_id in {"generic_deep_research", "generic_agent", "bare_llm", "zhipu_llm"}
            else None
        )
        if system_config is not None and system_id in (system_overrides or {}):
            system_config.update(dict((system_overrides or {})[system_id]))
        return make_adapter(system_id, project_root, fake=fake, system_config=system_config)
    if system_id == "no_domain_agents":
        return NoDomainAgentsAdapter(project_root, eval_root / "sandboxes" / system_id, mode="fake" if fake else "real")
    if system_id == "no_multisource_baseline":
        return NoDomainAgentsAdapter(
            project_root,
            eval_root / "sandboxes" / system_id,
            mode="fake" if fake else "real",
            system_id=system_id,
        )
    if system_id == "no_winning_mechanism":
        return NoWinningMechanismAdapter(
            project_root,
            mode="fake" if fake else "real",
        )
    if system_id in {"no_winning_chain", "no_feedback_loops"}:
        return ArtifactViewAblationAdapter(project_root, system_id, mode="fake" if fake else "real")
    raise ValueError(f"unknown system: {system_id}")


def _parse_systems(value: str) -> list[str]:
    systems = list(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))
    unknown = sorted(set(systems) - set(SYSTEM_IDS))
    if unknown:
        raise ValueError(f"unknown systems: {', '.join(unknown)}")
    return systems


def _safe_eval_output(project_root: Path, value: str | Path) -> Path:
    target = Path(value).resolve()
    allowed = (project_root / "outputs" / "evals").resolve()
    if target != allowed and allowed not in target.parents:
        raise ValueError(f"benchmark output must stay under {allowed}")
    return target


if __name__ == "__main__":
    raise SystemExit(main())
