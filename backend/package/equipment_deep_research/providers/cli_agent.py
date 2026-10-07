"""Provider-neutral adapter for non-interactive external agent CLIs.

The orchestration layer owns prompts, evidence, tools and output validation.
This module only translates a governed model turn into one isolated CLI
process and normalizes its result into the shared provider event contract.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
from typing import Any

from equipment_deep_research.domain.proposals import thaw_plain
from equipment_deep_research.providers.base import (
    ModelMessage,
    ProviderCapabilities,
    ProviderFinalTurn,
    ProviderStreamEvent,
)
from equipment_deep_research.providers.responses import ProviderRequestError
from equipment_deep_research.runtime_process_registry import (
    register_process_group,
    release_process_group,
)
from equipment_deep_research.contracts.tools import ToolDefinition


_SUPPORTED_PROTOCOLS = {"claude_json", "json", "jsonl", "text"}


class ExternalCliProvider:
    """Execute one ephemeral external-agent process for each model turn."""

    provider_type = "external_cli"

    def __init__(
        self,
        *,
        provider_id: str,
        command: str,
        protocol: str,
        model: str = "",
        workspace_path: str | Path = ".",
        runtime_home: str | Path | None = None,
        timeout_seconds: int = 900,
        retry_attempts: int = 1,
        model_flag: str = "--model",
        schema_flag: str = "",
        schema_mode: str = "file",
        base_args: Sequence[str] = (),
        extra_args: Sequence[str] = (),
        api_key: str = "",
        api_key_target_env: str = "",
        base_url: str = "",
        base_url_target_env: str = "",
        isolation_id: str = "shared",
        hosted_web_search: bool = False,
    ) -> None:
        if protocol not in _SUPPORTED_PROTOCOLS:
            raise ValueError(f"unsupported external CLI protocol: {protocol}")
        if timeout_seconds < 1:
            raise ValueError("external CLI timeout_seconds must be positive")
        if retry_attempts < 1 or retry_attempts > 3:
            raise ValueError("external CLI retry_attempts must be between 1 and 3")
        resolved = shutil.which(command)
        if resolved is None:
            raise ProviderRequestError(f"external agent CLI not found: {command}")
        workspace = Path(workspace_path).resolve()
        if not workspace.is_dir():
            raise ValueError(f"external CLI workspace does not exist: {workspace}")
        if schema_mode not in {"file", "inline"}:
            raise ValueError("external CLI schema_mode must be file or inline")

        self.provider_id = str(provider_id).strip()
        self.command = resolved
        self.protocol = protocol
        self.model = str(model).strip()
        self.workspace_path = workspace
        self.runtime_home = Path(
            runtime_home
            or workspace / "outputs" / "runtime" / "external-cli-homes" / self.provider_id
        ).resolve()
        self.runtime_home.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = timeout_seconds
        self.retry_attempts = retry_attempts
        self.model_flag = str(model_flag).strip()
        self.schema_flag = str(schema_flag).strip()
        self.schema_mode = schema_mode
        self.base_args = tuple(str(item) for item in base_args)
        self.extra_args = tuple(str(item) for item in extra_args)
        self.api_key = str(api_key).strip()
        self.api_key_target_env = str(api_key_target_env).strip()
        self.base_url = str(base_url).strip()
        self.base_url_target_env = str(base_url_target_env).strip()
        self.isolation_id = str(isolation_id or "shared")
        self.hosted_web_search = bool(hosted_web_search)
        self._active_process_groups: set[int] = set()

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            streaming=False,
            structured_output=bool(self.schema_flag),
            function_tools=False,
            hosted_web_search=self.hosted_web_search,
            isolated_sessions=True,
            resumable_sessions=False,
            cancellation=True,
            workspace_scope=True,
            agent_runtime=True,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "type": self.provider_type,
            "provider_id": self.provider_id,
            "driver": self.protocol,
            "model": self.model or "(cli default)",
            "command": Path(self.command).name,
            "base_url_host": "",
            "context_isolation": self.isolation_id,
            "execution_backend": f"independent_{self.provider_id}_cli",
            "session_mode": "ephemeral",
            "process_isolation": "new_process_per_turn",
            "capabilities": self.capabilities().to_plain(),
        }

    def isolated_copy(
        self,
        isolation_id: str,
        *,
        model: str | None = None,
    ) -> ExternalCliProvider:
        safe_id = _safe_component(isolation_id, "agent")
        return ExternalCliProvider(
            provider_id=self.provider_id,
            command=self.command,
            protocol=self.protocol,
            model=str(model or self.model),
            workspace_path=self.workspace_path,
            runtime_home=self.runtime_home / "isolated" / safe_id,
            timeout_seconds=self.timeout_seconds,
            retry_attempts=self.retry_attempts,
            model_flag=self.model_flag,
            schema_flag=self.schema_flag,
            schema_mode=self.schema_mode,
            base_args=self.base_args,
            extra_args=self.extra_args,
            api_key=self.api_key,
            api_key_target_env=self.api_key_target_env,
            base_url=self.base_url,
            base_url_target_env=self.base_url_target_env,
            isolation_id=isolation_id,
            hosted_web_search=self.hosted_web_search,
        )

    def close(self) -> None:
        for process_group_id in tuple(self._active_process_groups):
            _terminate_process_group_sync(process_group_id)
            release_process_group(process_group_id)
            self._active_process_groups.discard(process_group_id)

    async def stream(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolDefinition],
        options: Mapping[str, Any],
    ) -> AsyncIterator[ProviderStreamEvent]:
        if tools:
            raise ProviderRequestError(
                "external CLI turns do not receive harness tools directly"
            )
        prompt = _render_prompt(messages, options)
        schema_path, schema_json = self._prepare_schema(options.get("output_schema"))
        try:
            command = self._build_command(
                options,
                schema_path=schema_path,
                schema_json=schema_json,
            )
            result: subprocess.CompletedProcess[str] | None = None
            for attempt in range(self.retry_attempts):
                disable_timeout = bool(options.get("_disable_provider_timeout", False))
                if disable_timeout:
                    result = await self._execute(
                        command,
                        prompt,
                        disable_timeout=True,
                    )
                else:
                    # Preserve the small two-argument injection seam used by
                    # embedders and legacy tests for ordinary CLI turns.
                    # The workflow may provide a tighter per-call ceiling
                    # (blueprint, discovery lane, S6 card). Keep the provider
                    # constructor timeout as the hard upper bound, but enforce
                    # the call-level value around the existing two-argument
                    # execution seam so stalled CLI processes are terminated.
                    try:
                        requested_timeout = int(
                            options.get(
                                "_provider_timeout_seconds",
                                self.timeout_seconds,
                            )
                        )
                    except (TypeError, ValueError):
                        requested_timeout = self.timeout_seconds
                    call_timeout = max(
                        1,
                        min(self.timeout_seconds, requested_timeout),
                    )
                    result = await asyncio.wait_for(
                        self._execute(command, prompt),
                        timeout=call_timeout,
                    )
                if result.returncode == 0:
                    break
                if attempt + 1 < self.retry_attempts:
                    await asyncio.sleep(min(2**attempt, 4))
            assert result is not None
            if result.returncode != 0:
                detail = " ".join(result.stderr.split())[:1200]
                raise ProviderRequestError(
                    f"external CLI {self.provider_id} exited with status "
                    f"{result.returncode}: {detail or 'no diagnostic output'}"
                )
            final = self._parse_output(result.stdout)
            if not str(final.text or "").strip():
                raise ProviderRequestError(
                    f"external CLI {self.provider_id} completed without final text"
                )
            yield ProviderStreamEvent.final(final)
        finally:
            if schema_path is not None:
                schema_path.unlink(missing_ok=True)

    def _build_command(
        self,
        options: Mapping[str, Any],
        *,
        schema_path: Path | None,
        schema_json: str,
    ) -> list[str]:
        command = [self.command, *self.base_args]
        if self.model and self.model_flag:
            command.extend([self.model_flag, self.model])
        effort = str(options.get("reasoning_effort", "")).strip().lower()
        if self.protocol == "claude_json" and effort in {
            "low", "medium", "high", "xhigh", "max"
        }:
            command.extend(["--effort", effort])
        if self.schema_flag and schema_json:
            schema_value = (
                schema_json
                if self.schema_mode == "inline"
                else str(schema_path or "")
            )
            command.extend([self.schema_flag, schema_value])
        command.extend(self.extra_args)
        return command

    def _prepare_schema(self, contract: object) -> tuple[Path | None, str]:
        if not isinstance(contract, Mapping) or not self.schema_flag:
            return None, ""
        schema_json = json.dumps(
            _contract_to_json_schema(contract),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if self.schema_mode == "inline":
            return None, schema_json
        schema_dir = self.runtime_home / "output-schemas"
        schema_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            prefix="agent-output-",
            dir=schema_dir,
            delete=False,
        ) as handle:
            handle.write(schema_json)
            return Path(handle.name), schema_json

    async def _execute(
        self,
        command: Sequence[str],
        prompt: str,
        *,
        disable_timeout: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        env = {str(key): str(value) for key, value in os.environ.items()}
        if self.api_key and self.api_key_target_env:
            env[self.api_key_target_env] = self.api_key
        if self.base_url and self.base_url_target_env:
            env[self.base_url_target_env] = self.base_url
        env["EQUIPMENT_DR_EXTERNAL_AGENT_HOME"] = str(self.runtime_home)
        try:
            process = await asyncio.create_subprocess_exec(
                *list(command),
                cwd=str(self.workspace_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                start_new_session=True,
            )
        except OSError as exc:
            raise ProviderRequestError(
                f"external CLI {self.provider_id} could not start: {exc}"
            ) from exc
        process_group_id = process.pid
        self._active_process_groups.add(process_group_id)
        register_process_group(
            process_group_id,
            command_hint=Path(self.command).name,
        )
        try:
            communicate = process.communicate(prompt.encode("utf-8"))
            if disable_timeout:
                # Reporter delivery is a deferred artifact.  The orchestration
                # layer still owns cancellation/cleanup, but must not impose a
                # wall-clock cutoff on this individual external CLI turn.
                stdout, stderr = await communicate
            else:
                stdout, stderr = await asyncio.wait_for(
                    communicate,
                    timeout=self.timeout_seconds,
                )
        except asyncio.CancelledError:
            await _terminate_process_group(process)
            raise
        except TimeoutError as exc:
            await _terminate_process_group(process)
            raise ProviderRequestError(
                f"external CLI {self.provider_id} timed out after "
                f"{self.timeout_seconds} seconds"
            ) from exc
        finally:
            if process.returncode is None:
                await _terminate_process_group(process)
            self._active_process_groups.discard(process_group_id)
            release_process_group(process_group_id)
        return subprocess.CompletedProcess(
            args=list(command),
            returncode=int(process.returncode or 0),
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )

    def _parse_output(self, output: str) -> ProviderFinalTurn:
        if self.protocol == "text":
            return ProviderFinalTurn(
                text=output.strip(),
                finish_reason="completed",
                metadata={"provider": self.provider_id, "driver": self.protocol},
            )
        payload = _last_json_payload(output, jsonl=self.protocol == "jsonl")
        text = _text_from_payload(payload)
        usage = payload.get("usage", {}) if isinstance(payload, Mapping) else {}
        metadata: dict[str, Any] = {
            "provider": self.provider_id,
            "driver": self.protocol,
        }
        if isinstance(payload, Mapping):
            for key in ("session_id", "request_id", "cost_usd", "duration_ms"):
                if key in payload:
                    metadata[key] = payload[key]
        return ProviderFinalTurn(
            text=text,
            finish_reason=str(
                payload.get("subtype") or payload.get("status") or "completed"
            ),
            usage=usage if isinstance(usage, Mapping) else {},
            metadata=metadata,
        )


def _last_json_payload(output: str, *, jsonl: bool) -> Mapping[str, Any]:
    candidates = output.splitlines() if jsonl else [output]
    for raw in reversed(candidates):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(value, Mapping):
            return value
    raise ProviderRequestError("external CLI returned invalid JSON")


def _render_prompt(messages: Sequence[ModelMessage], options: Mapping[str, Any]) -> str:
    parts = [
        "You are a bounded research agent invoked by a multi-agent orchestration system.",
        "Complete only the supplied role task and return the requested final content.",
    ]
    effort = str(options.get("reasoning_effort", "")).strip()
    if effort:
        parts.append(f"Requested reasoning effort: {effort}.")
    for message in messages:
        content = message.content
        if not isinstance(content, str):
            content = thaw_plain(content)
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
        parts.append(f"\n[{message.role.upper()}]\n{content}")
    return "\n".join(parts).strip() + "\n"


def _contract_to_json_schema(value: object) -> dict[str, Any]:
    """Translate the repository's compact output contract without Codex coupling."""
    if isinstance(value, Mapping):
        properties = {
            str(key): _contract_to_json_schema(item) for key, item in value.items()
        }
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }
    if isinstance(value, list):
        return {
            "type": "array",
            "items": _contract_to_json_schema(value[0] if value else "string"),
        }
    descriptor = str(value).strip()
    if descriptor == "boolean":
        return {"type": "boolean"}
    if descriptor in {"0..1", "0..1 number"}:
        return {"type": "number", "minimum": 0, "maximum": 1}
    if descriptor in {"1..5", "1..5 number"}:
        return {"type": "integer", "minimum": 1, "maximum": 5}
    if "|" in descriptor and all(
        token.strip() and " " not in token.strip() for token in descriptor.split("|")
    ):
        return {"type": "string", "enum": [token.strip() for token in descriptor.split("|")]}
    return {"type": "string"}


def _text_from_payload(payload: Mapping[str, Any]) -> str:
    for key in (
        "structured_output",
        "result",
        "final",
        "text",
        "output",
        "content",
        "message",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (Mapping, list)):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return ""


def _safe_component(value: object, fallback: str) -> str:
    safe = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in str(value or "").strip()
    ).strip("-")
    return safe[:96] or fallback


async def _terminate_process_group(process: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        if process.returncode is None:
            process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=3)
    except TimeoutError:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            if process.returncode is None:
                process.kill()
        await process.wait()


def _terminate_process_group_sync(process_group_id: int) -> None:
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return


__all__ = ["ExternalCliProvider"]
