from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from typing import Any, Callable
import json
import os
import shutil
import subprocess
import time

import requests

from .adapters import normalize_llm_base_url, parse_codex_jsonl
from .models import PairwiseJudgment, read_jsonl, write_jsonl
from .pairwise import parse_judgment, render_judge_prompt


_CODEX_PARENT_ENV_VARS = {
    "CODEX_INTERNAL_ORIGINATOR_OVERRIDE",
    "CODEX_SANDBOX_NETWORK_DISABLED",
    "CODEX_THREAD_ID",
    "CODEX_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "CODEX_BASE_URL",
    "EQUIPMENT_EVAL_JUDGE_CODEX_RUNTIME_API_KEY",
}
_JUDGE_CODEX_API_KEY_ENV = "EQUIPMENT_EVAL_JUDGE_CODEX_RUNTIME_API_KEY"
_JUDGE_CODEX_PROVIDER_ID = "equipment_eval_judge_openai"


class JudgeClient:
    def __init__(
        self,
        model: str,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        api_protocol: str = "responses",
        judge_id: str | None = None,
        temperature: float | None = 0.0,
        max_output_tokens: int = 2500,
        fake: bool = False,
        timeout_seconds: int = 600,
        connection_retries: int = 1,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self.model = model
        self.judge_id = str(judge_id or model)
        protocol = str(api_protocol or "responses").strip().lower()
        if protocol not in {"responses", "chat_completions"}:
            raise ValueError(f"unsupported judge API protocol: {protocol}")
        self.api_protocol = protocol
        raw_base_url = (
            base_url
            or _env_first("EQUIPMENT_EVAL_OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        )
        self.base_url = normalize_llm_base_url(raw_base_url)
        self.api_key = api_key or _env_first("EQUIPMENT_EVAL_OPENAI_API_KEY")
        self.temperature = None if temperature is None else float(temperature)
        self.max_output_tokens = int(max_output_tokens)
        self.fake = fake
        self.timeout_seconds = timeout_seconds
        self.connection_retries = max(0, int(connection_retries))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))
        self.last_usage: dict[str, Any] = {}

    def judge(self, prompt: str, *, pair_id: str) -> PairwiseJudgment:
        if self.fake:
            if "route_task_fulfillment" in prompt:
                dimensions = {
                    "route_task_fulfillment": "tie",
                    "evidence_and_factuality": "tie",
                    "causal_and_mechanism_depth": "tie",
                    "military_operational_value": "tie",
                    "capability_mapping_and_demand_quality": "tie",
                    "novelty_and_foresight": "tie",
                    "system_and_cross_scenario_robustness": "tie",
                    "uncertainty_and_validation": "tie",
                }
            else:
                dimensions = {
                    "task_fulfillment": "tie",
                    "facts_and_citations": "tie",
                    "analysis_depth": "tie",
                    "equipment_demand_value": "tie",
                    "uncertainty": "tie",
                }
            payload = {
                "winner": "tie",
                "confidence": 0.5,
                "dimensions": dimensions,
                "reason": "offline judge fixture",
                "citation_issues": [],
                "hard_failures": [],
            }
            if "route_task_fulfillment" in prompt:
                payload.update(
                    {
                        "primary_route": "OTHER",
                        "secondary_routes": [],
                        "route_confidence": 0.5,
                        "preference_strength": "slight",
                        "route_deliverable_check": {},
                        "adjudication_required": True,
                        "adjudication_reasons": ["offline_fixture"],
                    }
                )
            return parse_judgment(json.dumps(payload), pair_id=pair_id, judge_id=self.judge_id)
        if not self.api_key:
            raise RuntimeError("judge API key is not configured")
        try:
            request_payload = self.build_request_payload(prompt)
            response = self._post(request_payload)
            if (
                not response.ok
                and self.api_protocol == "chat_completions"
                and response.status_code in {400, 422}
                and "response_format" in request_payload
            ):
                fallback_payload = dict(request_payload)
                fallback_payload.pop("response_format", None)
                response = self._post(fallback_payload)
            if not response.ok:
                raise RuntimeError(
                    f"judge API returned HTTP {response.status_code}: {_response_error_detail(response)}"
                )
            payload = dict(response.json())
            self.last_usage = dict(payload.get("usage") or {})
            output_text = (
                payload.get("output_text") or _response_text(payload)
                if self.api_protocol == "responses"
                else _chat_response_text(payload)
            )
            return parse_judgment(
                _extract_json_object(str(output_text)),
                pair_id=pair_id,
                judge_id=self.judge_id,
            )
        except Exception as exc:
            raise RuntimeError(_redact_secret(str(exc), self.api_key)) from exc

    def _post(self, payload: dict[str, Any]) -> requests.Response:
        for attempt in range(self.connection_retries + 1):
            try:
                return requests.post(
                    self.endpoint,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=(30, min(self.timeout_seconds, 900)),
                )
            except requests.exceptions.ConnectionError:
                if attempt >= self.connection_retries:
                    raise
                delay = self.retry_backoff_seconds * (2**attempt)
                if delay > 0:
                    time.sleep(delay)
        raise RuntimeError("judge connection retry exhausted")

    @property
    def endpoint(self) -> str:
        suffix = "/responses" if self.api_protocol == "responses" else "/chat/completions"
        return f"{self.base_url}{suffix}"

    def build_request_payload(self, prompt: str) -> dict[str, Any]:
        if self.api_protocol == "responses":
            payload: dict[str, Any] = {
                "model": self.model,
                "input": prompt,
                "text": {"format": {"type": "json_object"}},
            }
            if self.temperature is not None:
                payload["temperature"] = self.temperature
            if self.max_output_tokens > 0:
                payload["max_output_tokens"] = self.max_output_tokens
            return payload
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.max_output_tokens > 0:
            payload["max_tokens"] = self.max_output_tokens
        return payload


class CodexJudgeClient:
    """Run the pairwise judge prompt through an isolated Codex CLI session."""

    def __init__(
        self,
        model: str,
        *,
        judge_id: str,
        runtime_root: str | Path,
        command: str = "codex",
        base_url: str | None = None,
        api_key: str | None = None,
        auth_mode: str = "codex_login",
        reasoning_effort: str = "high",
        timeout_seconds: int = 600,
        fake: bool = False,
    ) -> None:
        self.model = str(model)
        self.judge_id = str(judge_id)
        self.runtime_root = Path(runtime_root).resolve() / _safe_runtime_name(self.judge_id)
        self.command = str(command or "codex")
        self.base_url = normalize_llm_base_url(str(base_url or "")) if base_url else ""
        self.api_key = str(api_key or "")
        self.auth_mode = str(auth_mode or "codex_login")
        self.reasoning_effort = str(reasoning_effort or "high")
        self.timeout_seconds = int(timeout_seconds)
        self.fake = fake
        self.last_usage: dict[str, Any] = {}

    def judge(self, prompt: str, *, pair_id: str) -> PairwiseJudgment:
        if self.fake:
            return JudgeClient(self.model, judge_id=self.judge_id, fake=True).judge(
                prompt,
                pair_id=pair_id,
            )
        executable = shutil.which(self.command)
        if not executable:
            raise RuntimeError(f"Codex CLI not found: {self.command}")
        if self.auth_mode not in {"codex_login", "eval_api_key"}:
            raise RuntimeError("invalid Codex judge auth mode")
        source_auth = Path.home() / ".codex" / "auth.json"
        if self.auth_mode == "codex_login" and not source_auth.is_file():
            raise RuntimeError("Codex login auth is not available")
        if self.auth_mode == "eval_api_key" and (not self.base_url or not self.api_key):
            raise RuntimeError("Codex judge custom API URL/key is not configured")
        codex_home = self.runtime_root / "codex-home"
        workspace = self.runtime_root / "workspace"
        codex_home.mkdir(parents=True, exist_ok=True)
        workspace.mkdir(parents=True, exist_ok=True)
        auth_link: Path | None = None
        if self.auth_mode == "codex_login":
            auth_link = codex_home / "auth.json"
            if auth_link.exists() or auth_link.is_symlink():
                auth_link.unlink()
            auth_link.symlink_to(source_auth)
        env = {
            str(key): str(value)
            for key, value in os.environ.items()
            if str(key).upper() not in _CODEX_PARENT_ENV_VARS
        }
        env["CODEX_HOME"] = str(codex_home)
        if self.auth_mode == "eval_api_key":
            env[_JUDGE_CODEX_API_KEY_ENV] = self.api_key
            env["CODEX_API_KEY"] = self.api_key
        try:
            process = subprocess.run(
                self.build_command(executable, workspace),
                cwd=workspace,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
                env=env,
            )
            stdout = _redact_secret(process.stdout, self.api_key)
            stderr = _redact_secret(process.stderr, self.api_key)
            answer, _, _, usage, metadata = parse_codex_jsonl(stdout)
            self.last_usage = usage
            if process.returncode != 0:
                detail = stderr.strip() or str(metadata.get("error") or "") or stdout[-2000:]
                raise RuntimeError(f"Codex judge exited {process.returncode}: {detail}")
            if not answer:
                raise RuntimeError("Codex judge returned no final answer")
            return parse_judgment(
                _extract_json_object(answer),
                pair_id=pair_id,
                judge_id=self.judge_id,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Codex judge timed out") from exc
        except Exception as exc:
            raise RuntimeError(_redact_secret(str(exc), self.api_key)) from exc
        finally:
            if auth_link is not None and auth_link.is_symlink():
                auth_link.unlink()

    def build_command(self, executable: str, workspace: Path) -> list[str]:
        command = [
            executable,
            "exec",
            "-C",
            str(workspace),
            "--skip-git-repo-check",
            "--json",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--ignore-user-config",
            "--ignore-rules",
            "--model",
            self.model,
            "--config",
            'approval_policy="never"',
            "--config",
            f"model_reasoning_effort={json.dumps(self.reasoning_effort)}",
        ]
        if self.auth_mode == "eval_api_key":
            command.extend(
                [
                    "--config",
                    f"model_provider={json.dumps(_JUDGE_CODEX_PROVIDER_ID)}",
                    "--config",
                    (
                        f"model_providers.{_JUDGE_CODEX_PROVIDER_ID}="
                        '{name="Benchmark Judge Provider",'
                        f"base_url={json.dumps(self.base_url)},"
                        f"env_key={json.dumps(_JUDGE_CODEX_API_KEY_ENV)},"
                        'wire_api="responses",supports_websockets=false}'
                    ),
                ]
            )
        command.append("-")
        return command


def judge_pair_file(
    pairs_path: str | Path,
    prompt_path: str | Path,
    output_path: str | Path,
    *,
    judge_models: list[str] | None = None,
    judge_configs: list[dict[str, Any]] | None = None,
    fake: bool = False,
    max_workers: int | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    pairs = read_jsonl(pairs_path)
    template = Path(prompt_path).read_text(encoding="utf-8")
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    clients = _judge_clients(
        judge_models or [],
        judge_configs or [],
        runtime_root=Path(output_path).parent / "judge-runtime",
        fake=fake,
    )
    usage: dict[str, dict[str, Any]] = {}
    # 同一专家串行（保护 client.last_usage 与 Codex runtime 目录），不同专家并行；
    # 评审是纯 I/O 等待（HTTP / 子进程），并行专家不改变单次判定的输入与提示词，结论不受影响。
    workers = _judge_worker_count(len(clients), max_workers, fake=fake)
    state_lock = Lock()
    total = len(clients) * len(pairs)
    completed = 0

    def _judge_lane(client: Any) -> None:
        nonlocal completed
        for pair in pairs:
            if cancel_requested is not None and cancel_requested():
                break
            try:
                prompt = render_judge_prompt(pair, template)
                judgment = client.judge(prompt, pair_id=str(pair["pair_id"])).to_dict()
                lane_usage = dict(client.last_usage)
                with state_lock:
                    rows.append(judgment)
                    usage[client.judge_id] = _merge_usage(usage.get(client.judge_id, {}), lane_usage)
            except Exception as exc:
                with state_lock:
                    errors.append(
                        {
                            "pair_id": str(pair.get("pair_id", "")),
                            "judge_id": client.judge_id,
                            "error": _redact_secret(str(exc), client.api_key),
                        }
                    )
            finally:
                with state_lock:
                    completed += 1
                    done = completed
                if progress_callback is not None:
                    progress_callback(done, total)

    if workers <= 1 or len(clients) <= 1:
        for client in clients:
            _judge_lane(client)
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="judge") as pool:
            for future in [pool.submit(_judge_lane, client) for client in clients]:
                future.result()
    rows.sort(key=lambda row: (str(row.get("judge_id", "")), str(row.get("pair_id", ""))))
    errors.sort(key=lambda row: (row["judge_id"], row["pair_id"]))
    write_jsonl(output_path, rows)
    errors_path = Path(output_path).with_suffix(".errors.jsonl")
    if errors:
        write_jsonl(errors_path, errors)
    elif errors_path.is_file():
        errors_path.unlink()
    return {
        "judgment_count": len(rows),
        "error_count": len(errors),
        "judge_count": len(clients),
        "parallel_workers": workers,
        "usage": usage,
        "cancelled": bool(cancel_requested is not None and cancel_requested()),
    }


def _judge_worker_count(client_count: int, max_workers: int | None, *, fake: bool) -> int:
    if fake or client_count <= 1:
        return 1
    env_value = os.environ.get("EQUIPMENT_EVAL_JUDGE_CONCURRENCY", "")
    configured = max_workers if max_workers is not None else (int(env_value) if env_value.isdigit() else 3)
    return max(1, min(int(configured), client_count))


def _judge_clients(
    judge_models: list[str],
    judge_configs: list[dict[str, Any]],
    *,
    runtime_root: Path,
    fake: bool,
) -> list[Any]:
    if judge_configs:
        clients: list[Any] = []
        for row in judge_configs:
            runtime = str(row.get("runtime") or "llm_api")
            common = {
                "model": str(row.get("model") or "judge"),
                "judge_id": str(row.get("judge_id") or row.get("model") or "judge"),
                "base_url": str(row.get("base_url") or "") or None,
                "api_key": str(row.get("api_key") or "") or None,
                "timeout_seconds": int(row.get("timeout_seconds", 600)),
                "fake": fake,
            }
            if runtime == "codex_cli":
                clients.append(
                    CodexJudgeClient(
                        **common,
                        runtime_root=runtime_root,
                        command=str(row.get("command") or "codex"),
                        auth_mode=str(row.get("auth_mode") or "codex_login"),
                        reasoning_effort=str(row.get("reasoning_effort") or "high"),
                    )
                )
            elif runtime == "llm_api":
                clients.append(
                    JudgeClient(
                        **common,
                        api_protocol=str(row.get("api_protocol") or "responses"),
                        temperature=float(row["temperature"]) if row.get("temperature") is not None else None,
                        max_output_tokens=int(row.get("max_output_tokens", 2500)),
                    )
                )
            else:
                raise ValueError(f"unsupported judge runtime: {runtime}")
        return clients
    return [JudgeClient(model, fake=fake) for model in judge_models]


def _response_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in payload.get("output", []) if isinstance(payload.get("output"), list) else []:
        if isinstance(item, dict) and item.get("type") == "message":
            for content in item.get("content", []) if isinstance(item.get("content"), list) else []:
                if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                    parts.append(str(content.get("text", "")))
    return "\n".join(parts)


def _chat_response_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ""
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return str(choices[0].get("text") or "")
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("text"):
                text = item["text"]
                parts.append(str(text.get("value") if isinstance(text, dict) else text))
        return "\n".join(parts)
    return ""


def _extract_json_object(value: str) -> str:
    text = str(value or "").strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    start = text.find("{")
    end = text.rfind("}")
    return text[start : end + 1] if start >= 0 and end > start else text


def _merge_usage(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    result = dict(left)
    for key, value in right.items():
        if isinstance(value, (int, float)) and isinstance(result.get(key, 0), (int, float)):
            result[key] = result.get(key, 0) + value
        else:
            result[key] = value
    return result


def _response_error_detail(response: requests.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                return str(error.get("message") or error.get("code") or "request failed")[:1000]
            if error:
                return str(error)[:1000]
            if payload.get("message"):
                return str(payload["message"])[:1000]
    except Exception:
        pass
    return str(getattr(response, "text", "") or "request failed")[:1000]


def _redact_secret(value: str, secret: str) -> str:
    return str(value or "").replace(secret, "[REDACTED]") if secret else str(value or "")


def _safe_runtime_name(value: str) -> str:
    return "".join(character if character.isalnum() or character in {"-", "_"} else "_" for character in value)[:96]


def _env_first(*names: str) -> str:
    return next((os.environ[name] for name in names if os.environ.get(name)), "")
