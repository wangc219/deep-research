from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from knowledgegraph.demand_discovery.autonomous_research import (  # noqa: E402
    run_autonomous_research_sync,
)
from knowledgegraph.demand_discovery.codex_workflow import (  # noqa: E402
    CodexWorkflowConfig,
    run_codex_workflow_sync,
)
from knowledgegraph.demand_discovery.llm.config_env import (  # noqa: E402
    env_value,
    load_demand_discovery_dotenv,
)
from knowledgegraph.demand_discovery.llm.model_config import DEFAULT_REAL_MODEL  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    dotenv = load_demand_discovery_dotenv(PROJECT_ROOT)
    parser = argparse.ArgumentParser(
        description="Run Phase 5 topic-only autonomous demand discovery research."
    )
    parser.add_argument("--mode", choices=["fake", "real", "codex"], default="fake")
    parser.add_argument("--topic", required=True)
    parser.add_argument(
        "--output-root",
        default=str(PROJECT_ROOT / "outputs" / "runs"),
    )
    parser.add_argument("--run-id", default="demand-discovery-autonomous-research")
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument("--seed-url", action="append", default=[])
    parser.add_argument("--allow-browser", action="store_true")
    parser.add_argument(
        "--endpoint-mode",
        choices=["responses_compatible", "codex_backend", "custom_endpoint"],
        default=env_value(
            "DEMAND_DISCOVERY_ENDPOINT_MODE",
            dotenv,
            "responses_compatible",
        ),
    )
    parser.add_argument(
        "--base-url",
        default=env_value(
            "DEMAND_DISCOVERY_BASE_URL",
            dotenv,
            "https://api.openai.com",
        ),
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
        "--source-whitelist",
        default=str(PROJECT_ROOT / "configs" / "demand_discovery" / "source_whitelist.yaml"),
    )
    parser.add_argument("--codex-home", default="")
    parser.add_argument(
        "--codex-model",
        default=env_value("DEMAND_DISCOVERY_CODEX_MODEL", dotenv, "gpt-5.5"),
    )
    parser.add_argument(
        "--codex-reasoning-effort",
        default=env_value("DEMAND_DISCOVERY_CODEX_REASONING_EFFORT", dotenv, "high"),
    )
    parser.add_argument("--codex-timeout", type=int, default=900)
    parser.add_argument("--codex-no-search", action="store_true")
    parser.add_argument("--codex-max-worker-tasks-per-round", type=int, default=3)
    parser.add_argument("--codex-max-report-rewrites", type=int, default=1)
    args = parser.parse_args(argv)

    if args.mode == "codex":
        result = run_codex_workflow_sync(
            CodexWorkflowConfig(
                topic=args.topic,
                output_root=Path(args.output_root),
                run_id=args.run_id,
                source_whitelist_path=Path(args.source_whitelist),
                seed_urls=list(args.seed_url),
                allow_browser=bool(args.allow_browser),
                max_rounds=args.max_rounds,
                project_root=PROJECT_ROOT,
                codex_home=Path(args.codex_home) if args.codex_home else None,
                codex_model=args.codex_model,
                reasoning_effort=args.codex_reasoning_effort,
                timeout_seconds=args.codex_timeout,
                enable_web_search=not bool(args.codex_no_search),
                max_worker_tasks_per_round=args.codex_max_worker_tasks_per_round,
                max_report_rewrites=args.codex_max_report_rewrites,
            )
        )
        print(f"Run dir: {result.run_dir}")
        print(f"Source strategy: {result.source_strategy_id}")
        print(f"Round summary: {result.round_summary_path}")
        print(f"Report: {result.report_path}")
        return 0

    result = run_autonomous_research_sync(
        mode=args.mode,
        topic=args.topic,
        output_root=Path(args.output_root),
        run_id=args.run_id,
        max_rounds=args.max_rounds,
        seed_urls=list(args.seed_url),
        allow_browser=bool(args.allow_browser),
        source_whitelist_path=Path(args.source_whitelist),
        endpoint_mode=args.endpoint_mode,
        base_url=args.base_url,
        endpoint_path=args.endpoint_path,
        model=args.model,
        api_key_env=args.api_key_env,
    )
    print(f"Run dir: {result.run_dir}")
    print(f"Source strategy: {result.source_strategy_id}")
    print(f"Round summary: {result.round_summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
