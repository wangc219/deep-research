from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[3]
ROUTER = ROOT / "scripts" / "deepseek-codex-routing.sh"


def _route(url: str, **environment: str) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "EQUIPMENT_DR_DEEPSEEK_BASE_URL": url,
        "EQUIPMENT_DR_DEEPSEEK_MODEL": "deepseek-v4-flash",
        "EQUIPMENT_DR_DEEPSEEK_API_KEY_ENV": "TEST_DEEPSEEK_KEY",
        **environment,
    }
    script = f"""
source {subprocess.list2cmdline([str(ROUTER)])}
configure_deepseek_codex_route
printf '%s\\n' \\
  "route=$EQUIPMENT_DR_DEEPSEEK_CODEX_ROUTE" \\
  "bridge=$EQUIPMENT_DR_DEEPSEEK_BRIDGE_REQUIRED" \\
  "base=$EQUIPMENT_DR_CODEX_DEEPSEEK_BASE_URL" \\
  "upstream=${{EQUIPMENT_DR_BRIDGE_UPSTREAM_URL:-}}" \\
  "key_env=$EQUIPMENT_DR_CODEX_DEEPSEEK_API_KEY_ENV"
"""
    result = subprocess.run(
        ["bash", "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return dict(line.split("=", 1) for line in result.stdout.splitlines())


def test_official_deepseek_uses_native_responses_even_with_legacy_chat_path() -> None:
    route = _route("https://api.deepseek.com/v1/chat/completions")

    assert route == {
        "route": "native_responses",
        "bridge": "0",
        "base": "https://api.deepseek.com/",
        "upstream": "",
        "key_env": "TEST_DEEPSEEK_KEY",
    }


def test_official_deepseek_scheme_and_host_are_case_insensitive() -> None:
    route = _route("HTTPS://API.DEEPSEEK.COM/responses")

    assert route["route"] == "native_responses"
    assert route["bridge"] == "0"


def test_third_party_deepseek_uses_bridge_and_normalizes_v1_endpoint() -> None:
    route = _route("https://relay.example.test/v1")

    assert route["route"] == "chat_bridge"
    assert route["bridge"] == "1"
    assert route["base"] == "http://127.0.0.1:8787/v1"
    assert route["upstream"] == "https://relay.example.test/v1/chat/completions"


def test_third_party_bridge_can_use_a_dedicated_credential_alias() -> None:
    route = _route(
        "https://relay.example.test/v1",
        EQUIPMENT_DR_BRIDGE_API_KEY_ENV="RELAY_KEY",
    )

    assert route["key_env"] == "RELAY_KEY"


def test_deepseek_lookalike_hostname_is_not_treated_as_official() -> None:
    route = _route("https://api.deepseek.com.relay.example/v1/chat/completions")

    assert route["route"] == "chat_bridge"
