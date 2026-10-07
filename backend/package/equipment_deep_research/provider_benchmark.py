"""Provider benchmark report helpers for deep-research runtime validation."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any

from equipment_deep_research.deep_runtime.provider_runtime import (
    ProviderRequest,
    ProviderRuntime,
)
from equipment_deep_research.providers.base import ModelMessage
from equipment_deep_research.providers.registry import (
    ProviderConfigurationError,
    ProviderRegistry,
)


DEFAULT_PROMPT = (
    "针对单一武器装备进行一轮深度发散调研，输出三个互相正交的研究方向，"
    "每个方向包含一个关键假设和一个需要验证的不确定性。"
)


@dataclass(frozen=True, slots=True)
class ProviderBenchmarkSpec:
    provider_id: str
    execute: bool = False
    prompt: str = DEFAULT_PROMPT
    max_output_tokens: int = 512


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _provider_options(registry: ProviderRegistry) -> dict[str, dict[str, Any]]:
    return {
        item["id"]: dict(item)
        for item in registry.public_options().get("providers", [])
        if isinstance(item, Mapping)
    }


def _readiness(option: Mapping[str, Any], snapshot: Mapping[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    provider_type = str(option.get("type", ""))
    command = str(option.get("command", "")).strip()
    if provider_type in {"codex_cli", "external_cli"} and not bool(option.get("available")):
        reasons.append(f"command unavailable: {command or provider_type}")
    key_env = str(option.get("default_api_key_env", "")).strip()
    if key_env and not os.environ.get(key_env, "").strip():
        reasons.append(f"credential missing: {key_env}")
    base_url = str(option.get("default_base_url", "")).strip()
    if provider_type in {"openai_compatible", "chat_completions"} and not base_url:
        reasons.append("base URL not configured")
    model = str(snapshot.get("model", "")).strip()
    if provider_type in {"openai_compatible", "chat_completions", "responses_http"} and not model:
        reasons.append("model not configured")
    return not reasons, reasons


async def run_provider_benchmark(
    registry: ProviderRegistry,
    spec: ProviderBenchmarkSpec,
    *,
    workspace_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return one secret-free benchmark row.

    The function never invents benchmark numbers.  When ``execute`` is false
    or required deployment inputs are absent, the row is explicitly marked
    ``not_executed`` with reasons.
    """

    options = _provider_options(registry)
    option = options.get(spec.provider_id)
    try:
        snapshot = registry.profile_snapshot(spec.provider_id)
    except ProviderConfigurationError as exc:
        return {
            "provider_id": spec.provider_id,
            "status": "not_executed",
            "reasons": [str(exc)],
            "created_at": _utc_now(),
        }
    if option is None:
        return {
            "provider_id": spec.provider_id,
            "status": "not_executed",
            "snapshot": snapshot,
            "reasons": ["provider is not exposed in public provider options"],
            "created_at": _utc_now(),
        }
    ready, reasons = _readiness(option, snapshot)
    row: dict[str, Any] = {
        "provider_id": spec.provider_id,
        "status": "ready" if ready else "not_executed",
        "snapshot": snapshot,
        "created_at": _utc_now(),
        "reasons": list(reasons),
    }
    if not spec.execute:
        row["status"] = "not_executed"
        row["reasons"] = [*row["reasons"], "execution disabled; pass --execute"]
        return row
    if not ready:
        return row
    started = time.perf_counter()
    try:
        provider = registry.create(
            spec.provider_id,
            workspace_path=workspace_path or Path.cwd(),
            isolation_key=f"provider-benchmark-{spec.provider_id}",
        )
        runtime = ProviderRuntime(provider)
        result = await runtime.complete(
            ProviderRequest(
                messages=(ModelMessage("user", spec.prompt),),
                options={"max_output_tokens": int(spec.max_output_tokens)},
                request_id=f"provider-benchmark-{spec.provider_id}",
            )
        )
    except Exception as exc:
        row["status"] = "failed"
        row["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
        row["error"] = exc.__class__.__name__
        row["reasons"] = ["provider execution failed"]
        return row
    row["status"] = "executed"
    row["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)
    row["finish_reason"] = result.finish_reason
    row["usage"] = dict(result.usage)
    row["text_chars"] = len(result.text or "")
    row["tool_call_count"] = len(result.tool_calls)
    return row


async def build_provider_benchmark_report(
    *,
    config_path: str | Path,
    provider_ids: Sequence[str] = (),
    execute: bool = False,
    prompt: str = DEFAULT_PROMPT,
    max_output_tokens: int = 512,
    workspace_path: str | Path | None = None,
) -> dict[str, Any]:
    registry = ProviderRegistry.load(config_path)
    options = _provider_options(registry)
    selected = tuple(provider_ids) or tuple(options)
    rows = [
        await run_provider_benchmark(
            registry,
            ProviderBenchmarkSpec(
                provider_id=provider_id,
                execute=execute,
                prompt=prompt,
                max_output_tokens=max_output_tokens,
            ),
            workspace_path=workspace_path,
        )
        for provider_id in selected
    ]
    return {
        "schema_version": "deep-provider-benchmark-v1",
        "created_at": _utc_now(),
        "execute": bool(execute),
        "providers": rows,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark configured deep-research providers.")
    parser.add_argument(
        "--config",
        default="configs/equipment_deep_research/providers.yaml",
        help="Provider YAML path.",
    )
    parser.add_argument(
        "--provider",
        action="append",
        dest="providers",
        default=[],
        help="Provider id to include. Repeat for multiple providers.",
    )
    parser.add_argument("--execute", action="store_true", help="Run real provider calls.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Benchmark prompt.")
    parser.add_argument("--max-output-tokens", type=int, default=512)
    parser.add_argument("--output", default="", help="Optional JSON output file.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = asyncio.run(
        build_provider_benchmark_report(
            config_path=args.config,
            provider_ids=tuple(args.providers),
            execute=bool(args.execute),
            prompt=str(args.prompt),
            max_output_tokens=int(args.max_output_tokens),
        )
    )
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


__all__ = [
    "DEFAULT_PROMPT",
    "ProviderBenchmarkSpec",
    "build_provider_benchmark_report",
    "main",
    "parse_args",
    "run_provider_benchmark",
]
