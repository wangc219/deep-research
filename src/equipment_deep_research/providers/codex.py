"""OpenAI Codex CLI provider adapter.

This adapter follows the same process-isolation principles used by OpenOPC's
Codex adapter while exposing the small ``ModelProvider`` contract used by the
equipment research harness.  Each model turn is an ephemeral ``codex exec``
session, so detailed agents keep independent context and cannot accidentally
reuse another agent's conversation.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
import json
import logging
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

from equipment_deep_research.domain.proposals import thaw_plain
from equipment_deep_research.providers.base import (
    ModelMessage,
    ProviderFinalTurn,
    ProviderStreamEvent,
)
from equipment_deep_research.providers.responses import ProviderRequestError
from equipment_deep_research.tools.definitions import ToolDefinition
from equipment_deep_research.providers.codex_optimizations import (
    render_prompt_optimized,
    get_perf_monitor,
)


logger = logging.getLogger(__name__)


_PARENT_CODEX_RUNTIME_ENV_VARS = {
    "CODEX_INTERNAL_ORIGINATOR_OVERRIDE",
    "CODEX_SANDBOX_NETWORK_DISABLED",
    "CODEX_THREAD_ID",
}

_RUNTIME_API_KEY_ENV = "EQUIPMENT_DR_CODEX_RUNTIME_API_KEY"
_RUNTIME_PROVIDER_ID = "equipment_research_gateway"


class CodexCliProvider:
    """Run one isolated Codex CLI process for each model turn."""

    provider_type = "codex_cli"

    def __init__(
        self,
        *,
        command: str = "codex",
        model: str = "",
        workspace_path: str | Path = ".",
        codex_home: str | Path | None = None,
        source_codex_home: str | Path | None = None,
        inherit_user_config: bool = True,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int = 900,
        sandbox_mode: str = "read-only",
        extra_args: Sequence[str] = (),
        search_extra_args: Sequence[str] = (),
        skill_paths: Sequence[str | Path] = (),
        include_default_skills: bool = True,
        retry_attempts: int = 2,
        isolation_id: str = "shared",
    ) -> None:
        if timeout_seconds < 1:
            raise ValueError("Codex timeout_seconds must be positive")
        if sandbox_mode not in {"read-only", "workspace-write", "danger-full-access"}:
            raise ValueError(f"unsupported Codex sandbox mode: {sandbox_mode}")
        if retry_attempts < 1 or retry_attempts > 3:
            raise ValueError("Codex retry_attempts must be between 1 and 3")
        resolved = shutil.which(command)
        if resolved is None:
            raise ProviderRequestError(f"Codex CLI not found: {command}")
        workspace = Path(workspace_path).resolve()
        if not workspace.is_dir():
            raise ValueError(f"Codex workspace does not exist: {workspace}")
        self.command = resolved
        self.model = model
        self.workspace_path = workspace
        self.codex_home = Path(
            codex_home or workspace / "outputs" / "runtime" / "codex-home"
        ).resolve()
        self.source_codex_home = (
            Path(source_codex_home or Path.home() / ".codex").expanduser().resolve()
        )
        self.api_key = str(api_key or "").strip()
        self.base_url = str(base_url or "").strip()
        self.inherit_user_config = bool(
            inherit_user_config and not (self.api_key or self.base_url)
        )
        if self.base_url:
            parsed_base_url = urlsplit(self.base_url)
            if (
                parsed_base_url.scheme != "https"
                or not parsed_base_url.hostname
                or parsed_base_url.username
                or parsed_base_url.password
                or parsed_base_url.query
                or parsed_base_url.fragment
            ):
                raise ValueError(
                    "Codex base URL must be HTTPS without credentials, query, or fragment"
                )
        self._prepare_codex_home()
        self.timeout_seconds = timeout_seconds
        self.sandbox_mode = sandbox_mode
        self.extra_args = tuple(str(item) for item in extra_args)
        self.search_extra_args = tuple(str(item) for item in search_extra_args)
        self.retry_attempts = retry_attempts
        self.isolation_id = str(isolation_id or "shared")
        default_skill = (
            self.workspace_path
            / "configs"
            / "equipment_deep_research"
            / "codex_skills"
            / "js-equipment-agent-runtime"
            / "SKILL.md"
        )
        configured_skills = [Path(item).expanduser().resolve() for item in skill_paths]
        if (
            include_default_skills
            and default_skill.is_file()
            and default_skill.resolve() not in configured_skills
        ):
            configured_skills.append(default_skill.resolve())
        shared_winning_skill = (
            self.workspace_path
            / "configs"
            / "equipment_deep_research"
            / "codex_skills"
            / "js-winning-shared-layer"
            / "SKILL.md"
        )
        if (
            include_default_skills
            and
            shared_winning_skill.is_file()
            and shared_winning_skill.resolve() not in configured_skills
        ):
            configured_skills.append(shared_winning_skill.resolve())
        self.skill_paths = tuple(configured_skills)

        # 性能优化：初始化缓存和预热
        # 命令缓存必须按 provider 实例隔离：全局单例会把上一个实例
        # （可能不同 base_url/model/skills）的命令泄漏给新实例。
        from equipment_deep_research.providers.codex_optimizations import CommandCache

        self._command_cache = CommandCache()
        self._perf_monitor = get_perf_monitor()
        self._base_command = self._build_base_command()

    def _build_base_command(self) -> list[str]:
        """构建不变的基础命令部分"""
        command = [
            self.command,
            "exec",
            "-C",
            str(self.workspace_path),
            "--skip-git-repo-check",
            "--json",
            "--ephemeral",
            "--sandbox",
            self.sandbox_mode,
        ]
        if self.model:
            command.extend(["--model", self.model])

        # 添加固定的配置项
        if self.base_url and self.api_key:
            # requires_openai_auth=true 使 Codex CLI 保留 hosted web_search 工具；
            # env_key 自定义 provider 会禁用 hosted 搜索，导致证据发现为空。
            # API key 通过 OPENAI_API_KEY 进程环境注入（见 _execute），不落盘。
            command.extend(
                [
                    "--config",
                    f"model_provider={json.dumps(_RUNTIME_PROVIDER_ID)}",
                    "--config",
                    (
                        f"model_providers.{_RUNTIME_PROVIDER_ID}="
                        '{name="Equipment Research Gateway",'
                        f"base_url={json.dumps(self.base_url)},"
                        'wire_api="responses",requires_openai_auth=true,'
                        "supports_websockets=false}"
                    ),
                ]
            )
        elif self.base_url:
            command.extend(["--config", f"openai_base_url={json.dumps(self.base_url)}"])

        # Skills 配置
        if self.skill_paths:
            skills_config = ",".join(
                "{path=" + json.dumps(str(path)) + ",enabled=true}"
                for path in self.skill_paths
            )
            command.extend(["--config", f"skills.config=[{skills_config}]"])

        # 固定参数
        command.extend(self.extra_args)

        return command

    def __repr__(self) -> str:
        model = self.model or "(cli default)"
        return (
            f"CodexCliProvider(model={model!r}, command={Path(self.command).name!r}, "
            f"sandbox={self.sandbox_mode!r})"
        )

    def snapshot(self) -> dict[str, str]:
        return {
            "type": self.provider_type,
            "model": self.model or "(cli default)",
            "command": Path(self.command).name,
            "sandbox_mode": self.sandbox_mode,
            "base_url_host": urlsplit(self.base_url).hostname or "",
            "context_isolation": self.isolation_id,
            "execution_backend": "independent_codex_cli",
            "session_mode": "ephemeral",
            "process_isolation": "new_process_per_turn",
        }

    def isolated_copy(self, isolation_id: str) -> CodexCliProvider:
        """Create a role/task-scoped CLI adapter with a separate runtime home.

        Every turn is already a fresh ``codex exec --ephemeral`` process.  A
        scoped copy additionally separates Codex runtime/config state for a
        dynamically recruited specialist while preserving the governed model,
        sandbox and Skill configuration of the parent adapter.
        """

        safe_id = "".join(
            character if character.isalnum() or character in {"-", "_"} else "-"
            for character in str(isolation_id or "specialist")
        ).strip("-")[:96] or "specialist"
        return CodexCliProvider(
            command=self.command,
            model=self.model,
            workspace_path=self.workspace_path,
            codex_home=self.codex_home / "isolated" / safe_id,
            source_codex_home=self.source_codex_home,
            inherit_user_config=self.inherit_user_config,
            api_key=self.api_key,
            base_url=self.base_url,
            timeout_seconds=self.timeout_seconds,
            sandbox_mode=self.sandbox_mode,
            extra_args=self.extra_args,
            search_extra_args=self.search_extra_args,
            skill_paths=self.skill_paths,
            include_default_skills=False,
            retry_attempts=self.retry_attempts,
            isolation_id=str(isolation_id or "specialist"),
        )

    def _prepare_codex_home(self) -> None:
        self.codex_home.mkdir(parents=True, exist_ok=True)
        try:
            self.codex_home.chmod(0o700)
        except OSError:
            pass
        inherited_files = [] if self.api_key else ["auth.json"]
        if self.inherit_user_config:
            inherited_files.append("config.toml")
        else:
            config_target = self.codex_home / "config.toml"
            if config_target.exists() or config_target.is_symlink():
                config_target.unlink(missing_ok=True)
        for name in inherited_files:
            source = self.source_codex_home / name
            target = self.codex_home / name
            if not source.is_file():
                continue
            try:
                if target.is_symlink() and target.resolve() == source.resolve():
                    continue
                if target.exists() or target.is_symlink():
                    target.unlink(missing_ok=True)
                target.symlink_to(source)
            except (OSError, NotImplementedError):
                if not target.exists() or target.read_bytes() != source.read_bytes():
                    target.write_bytes(source.read_bytes())
                try:
                    target.chmod(0o600)
                except OSError:
                    pass
        if self.api_key:
            auth_target = self.codex_home / "auth.json"
            auth_payload = json.dumps(
                {
                    "auth_mode": "apikey",
                    "OPENAI_API_KEY": self.api_key,
                },
                separators=(",", ":"),
            )
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix="auth-",
                suffix=".json",
                dir=self.codex_home,
                delete=False,
            ) as handle:
                handle.write(auth_payload)
                auth_temp = Path(handle.name)
            try:
                auth_temp.chmod(0o600)
                os.replace(auth_temp, auth_target)
                auth_target.chmod(0o600)
            finally:
                auth_temp.unlink(missing_ok=True)

    async def stream(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolDefinition],
        options: Mapping[str, Any],
    ) -> AsyncIterator[ProviderStreamEvent]:
        if tools:
            raise ProviderRequestError(
                "Codex CLI model turns do not accept harness function tools; "
                "tools remain governed and executed by the local harness"
            )

        started_at = monotonic()

        # 优化：使用优化的 prompt 渲染
        prompt_start = monotonic()
        prompt = render_prompt_optimized(messages, options)
        self._perf_monitor.record('prompt_render', monotonic() - prompt_start)

        schema_path = self._write_output_schema(options.get("output_schema"))
        requested_timeout_seconds = max(
            30,
            int(options.get("_provider_timeout_seconds", self.timeout_seconds)),
        )
        extended_timeout_allowed = bool(
            options.get("_allow_extended_provider_timeout", False)
        )
        timeout_ceiling_seconds = self.timeout_seconds
        if extended_timeout_allowed:
            timeout_ceiling_seconds = max(
                self.timeout_seconds,
                _configured_positive_int(
                    "EQUIPMENT_DR_CODEX_MAX_TIMEOUT_SECONDS",
                    3600,
                ),
            )
        execution_timeout_seconds = min(
            requested_timeout_seconds,
            timeout_ceiling_seconds,
        )
        retry_attempts = min(
            self.retry_attempts,
            max(1, int(options.get("_provider_retry_attempts", self.retry_attempts))),
        )

        try:
            # 优化：使用缓存的命令构建
            cmd_start = monotonic()
            command = self._build_command(
                options,
                output_schema_path=schema_path,
            )
            self._perf_monitor.record('command_build', monotonic() - cmd_start)

            result: subprocess.CompletedProcess[str] | None = None
            failure_detail = ""
            attempts_used = 0

            for attempt in range(retry_attempts):
                attempts_used = attempt + 1

                # 优化：使用预热的环境变量
                exec_start = monotonic()
                if "_execute" in self.__dict__:
                    # Keep the injectable synchronous seam used by tests and
                    # custom embedders. Production instances use a cancellable
                    # asyncio subprocess.
                    result = await asyncio.to_thread(self._execute, command, prompt)
                else:
                    result = await self._execute_async(
                        command,
                        prompt,
                        timeout_seconds=execution_timeout_seconds,
                    )
                self._perf_monitor.record('process_execute', monotonic() - exec_start)

                if result.returncode == 0:
                    break
                failure_detail = _codex_failure_detail(result.stdout, result.stderr)
                if attempt + 1 >= retry_attempts or not _is_retryable_failure(
                    failure_detail
                ):
                    break
                await asyncio.sleep(min(2**attempt, 4))
        finally:
            if schema_path is not None:
                schema_path.unlink(missing_ok=True)

        assert result is not None

        # 优化：记录解析时间
        parse_start = monotonic()
        text, metadata, usage = _parse_codex_jsonl(result.stdout)
        self._perf_monitor.record('output_parse', monotonic() - parse_start)

        elapsed_seconds = monotonic() - started_at
        self._perf_monitor.record('total', elapsed_seconds)

        if result.returncode != 0:
            raise ProviderRequestError(
                f"Codex CLI exited with status {result.returncode} "
                f"after {attempts_used} attempt(s): {failure_detail}"
            )
        if not text.strip():
            raise ProviderRequestError(
                "Codex CLI completed without a final agent message"
            )
        yield ProviderStreamEvent.final(
            ProviderFinalTurn(
                text=text,
                finish_reason="completed",
                usage=usage,
                metadata={
                    **metadata,
                    "provider": self.provider_type,
                    "sandbox_mode": self.sandbox_mode,
                    "elapsed_seconds": round(elapsed_seconds, 3),
                    "attempts": attempts_used,
                    "provider_timeout_seconds": execution_timeout_seconds,
                    "extended_provider_timeout": extended_timeout_allowed,
                    "prompt_chars": len(prompt),
                    "output_chars": len(text),
                },
            )
        )

    def _build_command(
        self,
        options: Mapping[str, Any],
        *,
        output_schema_path: Path | None = None,
    ) -> list[str]:
        """优化的命令构建 - 使用缓存"""
        # 构建缓存键
        cache_key = self._command_cache.get_cache_key(
            options,
            has_schema=output_schema_path is not None
        )

        # 尝试从缓存获取
        cached_command = self._command_cache.get(cache_key)
        if cached_command is not None:
            # 缓存命中 - 只需要添加动态的 schema 路径
            if output_schema_path is not None:
                command = list(cached_command)
                # 在倒数第二个位置插入 schema（最后一个是 "-"）
                command[-1:-1] = ["--output-schema", str(output_schema_path)]
                return command
            return cached_command

        # 缓存未命中 - 构建命令
        command = list(self._base_command)

        # 添加可变配置
        reasoning_effort = str(options.get("reasoning_effort", "")).strip().lower()
        if reasoning_effort in {"low", "medium", "high", "xhigh"}:
            command.extend(
                [
                    "--config",
                    f"model_reasoning_effort={json.dumps(reasoning_effort)}",
                ]
            )

        model_verbosity = str(options.get("model_verbosity", "")).strip().lower()
        if model_verbosity in {"low", "medium", "high"}:
            command.extend(
                [
                    "--config",
                    f"model_verbosity={json.dumps(model_verbosity)}",
                ]
            )

        search_options = options.get("web_search")
        if isinstance(search_options, Mapping):
            context_size = str(search_options.get("search_context_size", "high"))
            if context_size not in {"low", "medium", "high"}:
                context_size = "high"
            command.extend(
                [
                    "--config",
                    'web_search="live"',
                    "--config",
                    f'tools.web_search={{context_size="{context_size}"}}',
                ]
            )
            command.extend(self.search_extra_args)

        command.append("-")

        # 缓存命令（不包含 schema，因为它是动态的）
        if output_schema_path is None:
            self._command_cache.put(cache_key, command)

        # 添加 schema（如果有）
        if output_schema_path is not None:
            # 在最后的 "-" 之前插入
            command[-1:-1] = ["--output-schema", str(output_schema_path)]

        return command

    def _write_output_schema(self, contract: object) -> Path | None:
        if not isinstance(contract, Mapping):
            return None
        schema_dir = self.codex_home / "output-schemas"
        schema_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            prefix="agent-output-",
            dir=schema_dir,
            delete=False,
        ) as handle:
            json.dump(
                _contract_to_json_schema(contract),
                handle,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            path = Path(handle.name)
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return path

    def _execute(
        self, command: Sequence[str], prompt: str
    ) -> subprocess.CompletedProcess[str]:
        env = {
            str(key): str(value)
            for key, value in os.environ.items()
            if str(key).upper() not in _PARENT_CODEX_RUNTIME_ENV_VARS
        }
        env["CODEX_HOME"] = str(self.codex_home)
        if self.api_key:
            env[_RUNTIME_API_KEY_ENV] = self.api_key
            # requires_openai_auth=true 的自定义 provider 通过 OPENAI_API_KEY 认证
            env["OPENAI_API_KEY"] = self.api_key

        try:
            # Debug: 记录关键配置
            logger.debug(f"Executing Codex with base_url={self.base_url}, has_api_key={bool(self.api_key)}")
            if self.base_url and self.api_key:
                logger.debug(f"Custom provider config: env[{_RUNTIME_API_KEY_ENV}] set")

            return subprocess.run(
                list(command),
                cwd=self.workspace_path,
                input=prompt,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProviderRequestError(
                f"Codex CLI timed out after {self.timeout_seconds} seconds"
            ) from exc
        except OSError as exc:
            raise ProviderRequestError(f"Codex CLI could not start: {exc}") from exc

    async def _execute_async(
        self,
        command: Sequence[str],
        prompt: str,
        *,
        timeout_seconds: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        """Launch a cancellable Codex child and terminate its process group."""
        env = {
            str(key): str(value)
            for key, value in os.environ.items()
            if str(key).upper() not in _PARENT_CODEX_RUNTIME_ENV_VARS
        }
        env["CODEX_HOME"] = str(self.codex_home)
        if self.api_key:
            env[_RUNTIME_API_KEY_ENV] = self.api_key
            env["OPENAI_API_KEY"] = self.api_key
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
            raise ProviderRequestError(f"Codex CLI could not start: {exc}") from exc
        try:
            effective_timeout = int(timeout_seconds or self.timeout_seconds)
            stdout, stderr = await asyncio.wait_for(
                process.communicate(prompt.encode("utf-8")),
                timeout=effective_timeout,
            )
        except asyncio.CancelledError:
            await _terminate_process_group(process)
            raise
        except TimeoutError as exc:
            await _terminate_process_group(process)
            raise ProviderRequestError(
                f"Codex CLI timed out after {effective_timeout} seconds"
            ) from exc
        return subprocess.CompletedProcess(
            args=list(command),
            returncode=int(process.returncode or 0),
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
        )


async def _terminate_process_group(
    process: asyncio.subprocess.Process,
) -> None:
    process_group_id = process.pid
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass

    deadline = monotonic() + 3.0
    while monotonic() < deadline:
        if not _process_group_exists(process_group_id):
            if process.returncode is None:
                await process.wait()
            return
        await asyncio.sleep(0.05)

    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
    if process.returncode is None:
        await process.wait()


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _configured_positive_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(1, value)


def _render_prompt(
    messages: Sequence[ModelMessage],
    options: Mapping[str, Any],
) -> str:
    rows = [
        "You are a bounded research agent invoked by a multi-agent orchestration system.",
        "Complete only the supplied role task. Do not edit workspace files or change system state.",
        "Return only the requested final content; when a JSON schema is supplied, output strict JSON.",
    ]
    if isinstance(options.get("web_search"), Mapping):
        rows.append(
            "Use Codex web research/search capabilities when available. Cite only public HTTPS URLs "
            "that you actually inspected; if search is unavailable, state that limitation explicitly."
        )
    effort = str(options.get("reasoning_effort", "")).strip()
    max_tokens = options.get("max_output_tokens")
    if effort:
        rows.append(f"Requested reasoning effort: {effort}.")
    if max_tokens is not None:
        rows.append(f"Requested maximum output tokens: {max_tokens}.")
    rows.append("\nConversation:")
    for message in messages:
        content = thaw_plain(message.content)
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
        rows.append(f"\n[{message.role.upper()}]\n{content}")
    return "\n".join(rows).strip() + "\n"


def _contract_to_json_schema(value: object) -> dict[str, Any]:
    """Translate the repository's compact output contracts to JSON Schema."""
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
        item = value[0] if value else "string"
        return {"type": "array", "items": _contract_to_json_schema(item)}
    descriptor = str(value).strip()
    if descriptor == "boolean":
        return {"type": "boolean"}
    if descriptor in {"0..1", "0..1 number"}:
        return {"type": "number", "minimum": 0, "maximum": 1}
    if descriptor in {"1..5", "1..5 number"}:
        return {"type": "integer", "minimum": 1, "maximum": 5}
    if descriptor in {"1..6 or 0", "0..6"}:
        return {"type": "integer", "minimum": 0, "maximum": 6}
    if descriptor == "1..6":
        return {"type": "integer", "minimum": 1, "maximum": 6}
    if descriptor == "P1..P8":
        return {"type": "string", "enum": [f"P{index}" for index in range(1, 9)]}
    if descriptor in {"string | object | array", "string|object|array"}:
        # Strict Responses JSON schemas cannot contain an unconstrained object:
        # every object must declare properties and additionalProperties=false.
        # These flexible analysis-section values are supplemental to the typed
        # payload, so preserve useful scalar/list forms instead of emitting an
        # invalid arbitrary-object branch that rejects the entire model call.
        return {
            "anyOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "string"}},
            ]
        }
    if "|" in descriptor and all(
        token.strip() and " " not in token.strip() for token in descriptor.split("|")
    ):
        return {
            "type": "string",
            "enum": [token.strip() for token in descriptor.split("|")],
        }
    return {"type": "string"}


def _parse_codex_jsonl(
    output: str,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    final_message = ""
    last_message = ""
    thread_id = ""
    usage: dict[str, Any] = {}
    for raw_line in output.splitlines():
        try:
            envelope = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(envelope, Mapping):
            continue
        event = (
            envelope.get("msg")
            if isinstance(envelope.get("msg"), Mapping)
            else envelope
        )
        if not isinstance(event, Mapping):
            continue
        event_type = str(event.get("type", ""))
        if event_type == "thread.started":
            thread_id = str(event.get("thread_id", ""))
        elif event_type in {"item.started", "item.completed"}:
            item = event.get("item")
            if (
                not isinstance(item, Mapping)
                or str(item.get("type", "")) != "agent_message"
            ):
                continue
            text = str(item.get("text", "")).strip()
            if text:
                last_message = text
                if event_type == "item.completed":
                    final_message = text
        elif event_type in {"turn.completed", "response.completed"}:
            raw_usage = event.get("usage")
            if isinstance(raw_usage, Mapping):
                usage = {str(key): value for key, value in raw_usage.items()}
    return (
        final_message or last_message,
        {"codex_thread_id": thread_id} if thread_id else {},
        usage,
    )


def _codex_failure_detail(stdout: str, stderr: str) -> str:
    """Prefer structured Codex failure events over unrelated CLI warnings."""

    failures: list[str] = []
    for raw_line in str(stdout or "").splitlines():
        try:
            envelope = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(envelope, Mapping):
            continue
        event = (
            envelope.get("msg")
            if isinstance(envelope.get("msg"), Mapping)
            else envelope
        )
        if not isinstance(event, Mapping):
            continue
        event_type = str(event.get("type", "")).lower()
        if not event_type and isinstance(event.get("error"), Mapping):
            event_type = "error"
        if event_type not in {
            "error",
            "turn.failed",
            "response.failed",
            "response.incomplete",
        }:
            continue
        candidates = [
            event.get("message"),
            event.get("error"),
            event.get("detail"),
        ]
        response = event.get("response")
        if isinstance(response, Mapping):
            candidates.extend(
                [response.get("error"), response.get("incomplete_details")]
            )
        for value in candidates:
            if isinstance(value, Mapping):
                value = value.get("message") or value.get("reason") or value
            text = str(value or "").strip()
            if text and text not in failures:
                failures.append(text)
    if failures:
        return _trim(" | ".join(failures), 4000)

    warning_free = [
        line
        for line in str(stderr or "").splitlines()
        if " WARN " not in line and "warning" not in line.lower()
    ]
    fallback = "\n".join(warning_free).strip() or str(stdout or "").strip()
    if not fallback:
        fallback = str(stderr or "").strip()
    return _trim(fallback or "no diagnostic output", 4000)


def _is_retryable_failure(detail: str) -> bool:
    normalized = str(detail or "").lower()
    # Some OpenAI-compatible relay gateways transiently return a credential-
    # shaped 401 while rotating or reloading their upstream pool.  A single
    # provider-level retry is safe: a genuinely invalid key still fails on the
    # second attempt, while a healthy key is not allowed to invalidate a whole
    # checkpointed research run because of one relay response.
    transient_relay_auth = (
        "401" in normalized
        and "unauthorized" in normalized
        and "invalid api key" in normalized
    )
    return transient_relay_auth or any(
        signal in normalized
        for signal in (
            "429",
            "500",
            "502",
            "503",
            "504",
            "connection",
            "network",
            "temporarily unavailable",
            "timeout",
            "timed out",
            "stream disconnected",
            "upstream",
            "internal server error",
            "response failed",
            "no diagnostic output",
        )
    )


def _trim(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    head = max(1, limit // 3)
    tail = max(1, limit - head - 20)
    return text[:head].rstrip() + "\n… output omitted …\n" + text[-tail:].lstrip()


__all__ = ["CodexCliProvider", "_contract_to_json_schema"]
