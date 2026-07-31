from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from knowledgegraph.demand_discovery.harness.budget import RunBudget  # noqa: E402
from knowledgegraph.demand_discovery.llm.config_env import (  # noqa: E402
    env_value,
    load_demand_discovery_dotenv,
)
from knowledgegraph.demand_discovery.llm.model_config import (  # noqa: E402
    DEFAULT_REAL_MODEL,
    ModelConfig,
)
from knowledgegraph.demand_discovery.llm.responses_adapter import (  # noqa: E402
    build_provider_request,
    ResponsesProvider,
)
from knowledgegraph.demand_discovery.llm.types import LLMContext  # noqa: E402
from knowledgegraph.demand_discovery.manual_source_pack import (  # noqa: E402
    build_fake_source_pack_provider,
    format_manual_source_pack_result,
    load_manual_source_pack,
    run_manual_source_pack_sync,
)


DEFAULT_PACK = (
    PROJECT_ROOT
    / "configs"
    / "demand_discovery"
    / "source_packs"
    / "manual_cuas_low_altitude_v0.json"
)


def main(argv: list[str] | None = None) -> int:
    dotenv = load_demand_discovery_dotenv(PROJECT_ROOT)
    parser = argparse.ArgumentParser(
        description="Run a controlled demand discovery manual source pack."
    )
    parser.add_argument("--mode", choices=["fake", "real"], default="fake")
    parser.add_argument("--source-pack", default=str(DEFAULT_PACK))
    parser.add_argument(
        "--output-root",
        default=str(PROJECT_ROOT / "outputs" / "runs"),
    )
    parser.add_argument("--run-id", default="")
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
    parser.add_argument("--max-tokens", type=int, default=0)
    parser.add_argument("--max-tool-calls", type=int, default=40)
    parser.add_argument("--max-wall-clock-ms", type=int, default=0)
    parser.add_argument("--allow-no-report", action="store_true")
    parser.add_argument("--dry-run-provider-request", action="store_true")
    args = parser.parse_args(argv)

    pack = load_manual_source_pack(args.source_pack)
    budget = _build_budget(args)

    if args.mode == "real":
        api_key = env_value(str(args.api_key_env), dotenv)
        if not api_key:
            print(f"missing API key env {args.api_key_env}", file=sys.stderr)
            return 2
        if args.dry_run_provider_request:
            _print_dry_run_summary(args, pack)
            return 0
        config = ModelConfig(
            provider="real",
            model=str(args.model),
            base_url=str(args.base_url),
            endpoint_mode=str(args.endpoint_mode),
            endpoint_path=str(args.endpoint_path),
            api_key_env=str(args.api_key_env),
        )
        provider = ResponsesProvider(config, api_key)
    else:
        provider = build_fake_source_pack_provider(pack)

    result = run_manual_source_pack_sync(
        provider=provider,
        source_pack_path=Path(args.source_pack),
        output_root=Path(args.output_root),
        run_id=args.run_id or None,
        endpoint_mode=str(args.endpoint_mode) if args.mode == "real" else "fake",
        base_url=str(args.base_url) if args.mode == "real" else "fake://provider",
        model=str(args.model) if args.mode == "real" else "fake-source-pack",
        budget=budget,
        require_report=not args.allow_no_report,
    )
    print(format_manual_source_pack_result(result))
    return 0


def _build_budget(args: argparse.Namespace) -> RunBudget | None:
    if not args.max_tokens and not args.max_tool_calls and not args.max_wall_clock_ms:
        return None
    return RunBudget(
        max_tokens=args.max_tokens or None,
        max_tool_calls=args.max_tool_calls or None,
        max_wall_clock_ms=args.max_wall_clock_ms or None,
    )


def _print_dry_run_summary(args: argparse.Namespace, pack: object) -> None:
    config = ModelConfig(
        provider="real",
        model=str(args.model),
        base_url=str(args.base_url),
        endpoint_mode=str(args.endpoint_mode),
        endpoint_path=str(args.endpoint_path),
        api_key_env=str(args.api_key_env),
    )
    request = build_provider_request(config, LLMContext(messages=[]), [], {})
    print("mode: real")
    print(f"run_id: {args.run_id or '<auto>'}")
    print(f"pack: {getattr(pack, 'pack_id')}")
    print(f"source_pack: {Path(args.source_pack)}")
    print(f"output_root: {Path(args.output_root)}")
    print(f"endpoint_mode: {args.endpoint_mode}")
    print(f"model: {args.model}")
    print(f"url: {request['url']}")
    print(f"payload_keys: {', '.join(sorted(request['payload'].keys()))}")
    print(f"api_key_env: {args.api_key_env}")


if __name__ == "__main__":
    raise SystemExit(main())
