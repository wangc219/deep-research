from __future__ import annotations

import asyncio
import json
from pathlib import Path

from equipment_deep_research.provider_benchmark import (
    build_provider_benchmark_report,
    main,
)


def _provider_config(tmp_path: Path) -> Path:
    path = tmp_path / "providers.yaml"
    path.write_text(
        """default_provider: responses
providers:
  responses:
    type: responses_http
    model: gpt-5.5
    api_key_env: TEST_PROVIDER_KEY
  deepseek:
    type: openai_compatible
    model: deepseek-chat
    base_url_env: TEST_DEEPSEEK_URL
    api_key_env: TEST_DEEPSEEK_KEY
  fake:
    type: fake
""",
        encoding="utf-8",
    )
    return path


def test_provider_benchmark_reports_not_executed_without_credentials(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _provider_config(tmp_path)
    monkeypatch.delenv("TEST_PROVIDER_KEY", raising=False)
    monkeypatch.delenv("TEST_DEEPSEEK_KEY", raising=False)
    monkeypatch.setenv("TEST_DEEPSEEK_URL", "https://deepseek.example/v1/chat/completions")

    report = asyncio.run(
        build_provider_benchmark_report(
            config_path=config,
            provider_ids=("responses", "deepseek"),
            execute=True,
        )
    )

    assert report["schema_version"] == "deep-provider-benchmark-v1"
    rows = {item["provider_id"]: item for item in report["providers"]}
    assert rows["responses"]["status"] == "not_executed"
    assert "credential missing: TEST_PROVIDER_KEY" in rows["responses"]["reasons"]
    assert rows["deepseek"]["status"] == "not_executed"
    assert "credential missing: TEST_DEEPSEEK_KEY" in rows["deepseek"]["reasons"]
    assert "secret" not in json.dumps(report).lower()


def test_provider_benchmark_does_not_execute_without_explicit_flag(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _provider_config(tmp_path)
    monkeypatch.setenv("TEST_PROVIDER_KEY", "secret-value")

    report = asyncio.run(
        build_provider_benchmark_report(
            config_path=config,
            provider_ids=("responses",),
            execute=False,
        )
    )

    row = report["providers"][0]
    assert row["status"] == "not_executed"
    assert "execution disabled; pass --execute" in row["reasons"]
    assert "secret-value" not in json.dumps(report)


def test_provider_benchmark_cli_writes_json_report(tmp_path: Path, monkeypatch) -> None:
    config = _provider_config(tmp_path)
    output = tmp_path / "benchmark.json"
    monkeypatch.delenv("TEST_PROVIDER_KEY", raising=False)

    exit_code = main([
        "--config",
        str(config),
        "--provider",
        "responses",
        "--output",
        str(output),
    ])

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["providers"][0]["provider_id"] == "responses"
    assert payload["providers"][0]["status"] == "not_executed"
