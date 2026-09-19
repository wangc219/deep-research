"""Pure, typed deployment settings.

Environment variables are an adapter at the process boundary.  Keeping their
parsing here prevents every entry point from inventing its own defaults and
makes the application easy to construct in tests or a future service host.
Secrets are intentionally never stored in :class:`Settings`.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit

DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _text(env: Mapping[str, str], name: str, default: str = "") -> str:
    return str(env.get(name, default) or "").strip()


def _bool(env: Mapping[str, str], name: str, default: bool = False) -> bool:
    value = _text(env, name)
    if not value:
        return default
    return value.lower() in {"1", "true", "yes", "on", "y"}


def _int(
    env: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    try:
        value = int(_text(env, name, str(default)))
    except (TypeError, ValueError):
        value = default
    bounded = max(minimum, value)
    return min(maximum, bounded) if maximum is not None else bounded


def _root(env: Mapping[str, str], project_root: str | Path | None) -> Path:
    selected = (
        project_root
        or _text(env, "EQUIPMENT_DR_PROJECT_ROOT")
        or DEFAULT_PROJECT_ROOT
    )
    return Path(selected).expanduser().resolve()


def _database_url(env: Mapping[str, str], name: str, fallback: Path) -> str:
    configured = _text(env, name)
    return configured or f"sqlite:///{fallback}"


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    """Canonical filesystem locations used by all composition roots."""

    root: Path
    output: Path
    runs: Path
    runtime: Path
    config: Path

    @classmethod
    def from_environment(
        cls,
        env: Mapping[str, str] | None = None,
        project_root: str | Path | None = None,
    ) -> "ProjectPaths":
        values = os.environ if env is None else env
        root = _root(values, project_root)
        output = Path(
            _text(values, "EQUIPMENT_DR_OUTPUT_ROOT", str(root / "outputs"))
        ).expanduser()
        if not output.is_absolute():
            output = root / output
        output = output.resolve()
        return cls(
            root=root,
            output=output,
            runs=output / "runs",
            runtime=output / "runtime",
            config=root / "configs" / "equipment_deep_research",
        )


@dataclass(frozen=True, slots=True)
class Settings:
    """Non-secret process settings shared by API, CLI and workers."""

    paths: ProjectPaths
    database_url: str
    query_library_database_url: str
    mode: str
    provider: str
    profile_id: str
    execution_profile_id: str
    web_host: str
    web_port: int
    auth_mode: str
    require_trusted_identity: bool
    worker_concurrency: int
    codex_timeout_seconds: int

    @classmethod
    def from_environment(
        cls,
        env: Mapping[str, str] | None = None,
        project_root: str | Path | None = None,
    ) -> "Settings":
        values = os.environ if env is None else env
        paths = ProjectPaths.from_environment(values, project_root)
        return cls(
            paths=paths,
            database_url=_database_url(values, "EQUIPMENT_DR_APP_DB", paths.output / "application.db"),
            query_library_database_url=_database_url(
                values,
                "EQUIPMENT_DR_QUERY_LIBRARY_DB",
                paths.output / "query-library.db",
            ),
            mode=_text(values, "EQUIPMENT_DR_MODE", "fake") or "fake",
            provider=_text(values, "EQUIPMENT_DR_PROVIDER"),
            profile_id=_text(values, "EQUIPMENT_DR_PROFILE"),
            execution_profile_id=(
                _text(values, "EQUIPMENT_DR_EXECUTION_PROFILE_ID", "winning_swarm_dynamic_v2")
                or "winning_swarm_dynamic_v2"
            ),
            web_host=_text(values, "EQUIPMENT_DR_WEB_HOST", "127.0.0.1") or "127.0.0.1",
            web_port=_int(values, "EQUIPMENT_DR_WEB_PORT", 5173, minimum=1, maximum=65535),
            auth_mode=_text(values, "EQUIPMENT_DR_AUTH_MODE", "local") or "local",
            require_trusted_identity=_bool(values, "EQUIPMENT_DR_REQUIRE_TRUSTED_IDENTITY"),
            worker_concurrency=_int(values, "EQUIPMENT_DR_RESEARCH_WORKER_CONCURRENCY", 1, minimum=1),
            codex_timeout_seconds=_int(values, "EQUIPMENT_DR_CODEX_TIMEOUT_SECONDS", 900, minimum=1),
        )

    def public_dict(self) -> dict[str, object]:
        """Return a safe diagnostic snapshot without credentials."""

        return {
            "project_root": str(self.paths.root),
            "output_root": str(self.paths.output),
            "database_url": _redact_url(self.database_url),
            "query_library_database_url": _redact_url(self.query_library_database_url),
            "mode": self.mode,
            "provider": self.provider,
            "profile_id": self.profile_id,
            "execution_profile_id": self.execution_profile_id,
            "web_host": self.web_host,
            "web_port": self.web_port,
            "auth_mode": self.auth_mode,
            "require_trusted_identity": self.require_trusted_identity,
            "worker_concurrency": self.worker_concurrency,
            "codex_timeout_seconds": self.codex_timeout_seconds,
        }


def load_settings(
    env: Mapping[str, str] | None = None,
    *,
    project_root: str | Path | None = None,
) -> Settings:
    """Load settings from an explicit environment mapping or the process env."""

    return Settings.from_environment(env, project_root)


def _redact_url(value: str) -> str:
    """Hide credentials embedded in a diagnostic database URL."""

    parsed = urlsplit(str(value))
    if not parsed.username and not parsed.password:
        return str(value)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))


__all__ = ["ProjectPaths", "Settings", "load_settings"]
