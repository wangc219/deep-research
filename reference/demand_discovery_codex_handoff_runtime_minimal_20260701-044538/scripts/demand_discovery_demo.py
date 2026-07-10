from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from knowledgegraph.demand_discovery.demo import (  # noqa: E402
    build_dry_run_provider_request,
    format_demo_result,
    run_fake_demo_sync,
    run_fake_watch_demo_sync,
    run_real_demo_sync,
)
from knowledgegraph.demand_discovery.harness.event_bus import EventBus, RuntimeEvent  # noqa: E402
from knowledgegraph.demand_discovery.llm.config_env import (  # noqa: E402
    env_value,
    load_demand_discovery_dotenv,
)
from knowledgegraph.demand_discovery.llm.model_config import DEFAULT_REAL_MODEL  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    dotenv = load_demand_discovery_dotenv(PROJECT_ROOT)
    parser = argparse.ArgumentParser(description="Run demand discovery demo.")
    parser.add_argument("--mode", choices=["fake", "real"], default="fake")
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "outputs" / "demand_discovery_demo.jsonl"),
    )
    parser.add_argument(
        "--output-root",
        default=str(PROJECT_ROOT / "outputs" / "runs"),
    )
    parser.add_argument("--run-id", default="")
    parser.add_argument("--watch", action="store_true")
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
    parser.add_argument("--dry-run-provider-request", action="store_true")
    args = parser.parse_args(argv)

    if args.mode == "real":
        api_key = env_value(args.api_key_env, dotenv)
        if not api_key:
            print(f"missing API key env {args.api_key_env}", file=sys.stderr)
            return 2
        if args.dry_run_provider_request:
            request = build_dry_run_provider_request(
                endpoint_mode=args.endpoint_mode,
                base_url=args.base_url,
                endpoint_path=args.endpoint_path,
                model=args.model,
                api_key_env=args.api_key_env,
            )
            print(f"endpoint_mode: {request['endpoint_mode']}")
            print(f"model: {request['model']}")
            print(f"url: {request['url']}")
            print(f"payload_keys: {', '.join(request['payload_keys'])}")
            print(f"api_key_env: {request['api_key_env']}")
            return 0
        result = run_real_demo_sync(
            Path(args.output),
            endpoint_mode=args.endpoint_mode,
            base_url=args.base_url,
            endpoint_path=args.endpoint_path,
            model=args.model,
            api_key_env=args.api_key_env,
            api_key=api_key,
        )
        print(format_demo_result(result))
        return 0

    if args.watch:
        bus = EventBus()
        bus.subscribe(_print_watch_event, categories={"scheduler"})
        result = run_fake_watch_demo_sync(
            output_path=Path(args.output),
            output_root=Path(args.output_root),
            run_id=args.run_id or "demand-discovery-demo-watch",
            event_bus=bus,
        )
        print(format_demo_result(result))
        return 0

    result = run_fake_demo_sync(Path(args.output))
    print(format_demo_result(result))
    return 0


def _print_watch_event(event: RuntimeEvent) -> None:
    if not event.event_type.startswith("worker_"):
        return
    payload = event.payload
    role = payload.get("role", "")
    status = payload.get("status", "")
    print(
        f"[watch] {event.event_type} {role} {event.agent_run_id} {status}",
        flush=True,
    )


if __name__ == "__main__":
    raise SystemExit(main())
