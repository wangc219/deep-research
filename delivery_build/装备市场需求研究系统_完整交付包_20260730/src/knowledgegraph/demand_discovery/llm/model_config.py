"""Model/provider configuration for demand discovery LLM adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DEFAULT_REASONING_EFFORT = "xhigh"
DEFAULT_REAL_MODEL = "gpt-5.5"
GPT55_CONTEXT_WINDOW_TOKENS = 256_000
DEFAULT_AGENT_MAX_TOKENS = 240_000
DEFAULT_CONTEXT_TOKEN_BUDGET = 200_000


@dataclass
class ModelConfig:
    provider: str
    model: str
    api_key_env: str = "DEMAND_DISCOVERY_API_KEY"
    base_url: str = "https://api.openai.com"
    endpoint_mode: str = "responses_compatible"
    endpoint_path: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    auth_header: str = "Authorization"
    timeout_ms: int = 60_000
    max_retries: int = 2
    reasoning_effort: str = DEFAULT_REASONING_EFFORT
    reasoning_summary: str = ""
    cache_retention: str = ""
    text_verbosity: str = ""

    def to_trace_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "api_key_env": self.api_key_env,
            "base_url": self.base_url,
            "endpoint_mode": self.endpoint_mode,
            "endpoint_path": self.endpoint_path,
            "headers": _sanitize_headers(self.headers, self.auth_header),
            "auth_header": self.auth_header,
            "timeout_ms": self.timeout_ms,
            "max_retries": self.max_retries,
            "reasoning_effort": self.reasoning_effort,
            "reasoning_summary": self.reasoning_summary,
            "cache_retention": self.cache_retention,
            "text_verbosity": self.text_verbosity,
        }


_SENSITIVE_HEADER_NAMES = {
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "api-key",
    "apikey",
    "openai-api-key",
    "x-openai-api-key",
}


def _sanitize_headers(headers: dict[str, str], auth_header: str) -> dict[str, str]:
    sensitive = {*_SENSITIVE_HEADER_NAMES, auth_header.lower()}
    return {
        key: "<redacted>" if key.lower() in sensitive else value
        for key, value in headers.items()
    }
