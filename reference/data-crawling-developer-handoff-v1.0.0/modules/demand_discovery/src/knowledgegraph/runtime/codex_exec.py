"""Codex CLI execution helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
from typing import Any


@dataclass(frozen=True)
class CodexExecConfig:
    codex_home: Path
    model: str = "gpt-5.5"
    reasoning_effort: str = "high"
    timeout_seconds: int = 240


class CodexExecError(RuntimeError):
    """Raised when Codex CLI invocation fails."""


def build_codex_exec_command(config: CodexExecConfig, output_path: Path, project_root: Path) -> list[str]:
    codex_executable = shutil.which("codex") or "codex"
    return [
        codex_executable,
        "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "-C",
        str(project_root),
        "--model",
        config.model,
        "-c",
        f'model_reasoning_effort="{config.reasoning_effort}"',
        "--output-last-message",
        str(output_path),
        "-",
    ]


def build_codex_exec_env(config: CodexExecConfig, base_env: os._Environ[str] | dict[str, str]) -> dict[str, str]:
    env = dict(base_env)
    env["CODEX_HOME"] = str(config.codex_home)
    return env


def run_codex_exec_process(
    command: list[str],
    prompt: str,
    env: dict[str, str],
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    creationflags = 0
    if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
        creationflags=creationflags,
    )
    try:
        stdout, stderr = process.communicate(input=prompt, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        terminate_process_tree(process)
        try:
            process.communicate(timeout=5)
        except Exception:
            pass
        raise CodexExecError(f"Codex CLI timed out after {timeout_seconds}s") from exc
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def invoke_codex_exec(prompt: str, config: CodexExecConfig, project_root: Path) -> str:
    if not config.codex_home.exists():
        raise CodexExecError(f"CODEX_HOME does not exist: {config.codex_home}")
    with tempfile.TemporaryDirectory(prefix="codex_exec_") as temp_dir:
        output_path = Path(temp_dir) / "last_message.txt"
        command = build_codex_exec_command(config=config, output_path=output_path, project_root=project_root)
        completed = run_codex_exec_process(
            command=command,
            prompt=prompt,
            env=build_codex_exec_env(config=config, base_env=os.environ),
            timeout_seconds=config.timeout_seconds,
        )
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "").strip()
            raise CodexExecError(f"Codex CLI failed with exit {completed.returncode}: {message}")
        if not output_path.exists():
            raise CodexExecError("Codex CLI did not write --output-last-message file")
        content = output_path.read_text(encoding="utf-8").strip()
        if not content:
            raise CodexExecError("Codex CLI returned an empty final message")
        return content


def terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return
    process.kill()


def extract_json_payload_from_text(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        last_marker = stripped.rfind("```")
        if first_newline >= 0 and last_marker > first_newline:
            stripped = stripped[first_newline:last_marker].strip()
    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char != "{":
            continue
        payload, _ = decoder.raw_decode(stripped[index:])
        if isinstance(payload, dict):
            return payload
    raise json.JSONDecodeError("No JSON object found in Codex final message", stripped, 0)
