from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Mapping
import json
import os
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import urlsplit, urlunsplit

import requests

from .models import EvalQuery, EvalRunResult


URL_PATTERN = re.compile(r"https?://[^\s<>)\]}]+")
DEFAULT_GENERIC_AGENT_OUTPUT_TOKENS = 7000
DEFAULT_BARE_LLM_OUTPUT_TOKENS = 8000
DEFAULT_ZHIPU_LLM_OUTPUT_TOKENS = 8000
_CODEX_PARENT_ENV_VARS = {
    "CODEX_INTERNAL_ORIGINATOR_OVERRIDE",
    "CODEX_SANDBOX_NETWORK_DISABLED",
    "CODEX_THREAD_ID",
    "CODEX_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "CODEX_BASE_URL",
    "EQUIPMENT_EVAL_CODEX_RUNTIME_API_KEY",
}
_CODEX_RUNTIME_API_KEY_ENV = "EQUIPMENT_EVAL_CODEX_RUNTIME_API_KEY"
_CODEX_RUNTIME_PROVIDER_ID = "equipment_eval_openai"


class SystemAdapter(ABC):
    system_id: str

    @abstractmethod
    def run(self, query: EvalQuery, *, eval_id: str, output_dir: Path) -> EvalRunResult:
        raise NotImplementedError


class FullMethodAdapter(SystemAdapter):
    system_id = "full_method"

    def __init__(
        self,
        project_root: str | Path,
        *,
        mode: str = "fake",
        provider: str | None = None,
        timeout_seconds: int = 21600,
        agent_config: str | Path | None = None,
        agent_ids: list[str] | None = None,
        max_rounds: int | None = None,
        stage_policy_id: str = "full_method",
        system_id: str | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.mode = mode
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        self.agent_config = Path(agent_config).resolve() if agent_config else None
        self.agent_ids = list(agent_ids or [])
        self.max_rounds = max_rounds
        self.stage_policy_id = stage_policy_id
        if system_id:
            self.system_id = system_id

    def run(self, query: EvalQuery, *, eval_id: str, output_dir: Path) -> EvalRunResult:
        started = time.monotonic()
        run_id = f"{self.system_id}-{query.query_id.lower()}"
        run_root = output_dir / "runtime"
        run_dir = run_root / run_id
        command = [
            sys.executable,
            str(self.project_root / "scripts" / "run_deep_research.py"),
            "--mode", self.mode,
            "--topic", query.query,
            "--research-route", "auto",
            "--run-id", run_id,
            "--output-root", str(run_root),
            "--interaction-mode", "expert",
            "--discovery-branch", "auto",
            "--analyst-confirmed",
            "--stage-policy-id", self.stage_policy_id,
        ]
        if run_dir.is_dir():
            command.append("--resume")
        if self.provider:
            command.extend(["--provider", self.provider])
        if self.agent_config:
            command.extend(["--agent-config", str(self.agent_config)])
        if self.agent_ids:
            command.extend(["--agents", ",".join(self.agent_ids)])
        if self.max_rounds:
            command.extend(["--max-rounds", str(self.max_rounds)])
        try:
            process = subprocess.run(
                command,
                cwd=self.project_root,
                env=os.environ.copy(),
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
            if process.returncode != 0:
                return _failed_result(
                    eval_id, query.query_id, self.system_id, started,
                    f"{self.system_id} exited {process.returncode}: {process.stderr[-3000:]}",
                )
            report_path = run_dir / "report.md"
            summary_path = run_dir / "round_summary.json"
            if not report_path.is_file() or not summary_path.is_file():
                return _failed_result(eval_id, query.query_id, self.system_id, started, "required run artifacts are missing")
            answer = report_path.read_text(encoding="utf-8")
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            sources = _summary_sources(summary)
            citations = sorted(set(URL_PATTERN.findall(answer)))
            artifacts = [
                str(path.relative_to(output_dir))
                for path in sorted(run_dir.rglob("*"))
                if path.is_file()
            ]
            return EvalRunResult(
                eval_id=eval_id,
                query_id=query.query_id,
                system_id=self.system_id,
                status="completed",
                answer=answer,
                citations=citations,
                sources=sorted(set([*sources, *citations])),
                duration_seconds=round(time.monotonic() - started, 3),
                usage=_collect_run_usage(run_dir, summary),
                model_snapshot={
                    "provider": summary.get("provider", {}),
                    "agent_models": summary.get("agent_models", {}),
                    "mode": self.mode,
                },
                artifact_refs=artifacts,
            )
        except subprocess.TimeoutExpired:
            return _failed_result(
                eval_id,
                query.query_id,
                self.system_id,
                started,
                f"{self.system_id} timed out",
            )
        except Exception as exc:  # benchmark failures must not escape into production
            return _failed_result(eval_id, query.query_id, self.system_id, started, str(exc))


class ResponsesAdapter(SystemAdapter):
    def __init__(
        self,
        system_id: str,
        *,
        model: str = "gpt-5.5",
        reasoning_effort: str = "high",
        web_search: bool = False,
        background: bool = False,
        timeout_seconds: int = 3600,
        fake: bool = False,
        base_url: str | None = None,
        api_key: str | None = None,
        max_tool_calls: int | None = None,
        max_output_tokens: int | None = None,
        poll_interval_seconds: float = 2.0,
        web_search_options: dict[str, Any] | None = None,
    ) -> None:
        self.system_id = system_id
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.web_search = web_search
        self.background = background
        self.timeout_seconds = timeout_seconds
        self.fake = fake
        self.base_url = (
            base_url
            or _env_first("EQUIPMENT_EVAL_OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        ).rstrip("/")
        self.api_key = api_key or _env_first("EQUIPMENT_EVAL_OPENAI_API_KEY")
        self.max_tool_calls = max_tool_calls
        self.max_output_tokens = max_output_tokens
        self.poll_interval_seconds = max(0.25, float(poll_interval_seconds))
        self.web_search_options = dict(web_search_options or {})

    def run(self, query: EvalQuery, *, eval_id: str, output_dir: Path) -> EvalRunResult:
        started = time.monotonic()
        if self.fake:
            answer = f"# {query.query}\n\n这是{self.system_id}的离线评测回答。\n\n来源：https://fixture.local/{self.system_id}"
            return EvalRunResult(
                eval_id=eval_id,
                query_id=query.query_id,
                system_id=self.system_id,
                status="completed",
                answer=answer,
                citations=[f"https://fixture.local/{self.system_id}"],
                sources=[f"https://fixture.local/{self.system_id}"],
                duration_seconds=round(time.monotonic() - started, 3),
                usage={"input_tokens": 20, "output_tokens": 30},
                model_snapshot={"model": self.model, "fake": True},
            )
        if not self.api_key:
            return _failed_result(eval_id, query.query_id, self.system_id, started, "Responses API key is not configured")
        try:
            response = self._create_response(query)
            if self.background and response.get("id") and response.get("status") not in {"completed", "failed", "cancelled"}:
                response = self._poll_response(str(response["id"]))
            answer, citations, sources = parse_responses_output(response)
            if response.get("status") not in {None, "completed"}:
                raise RuntimeError(f"response status is {response.get('status')}")
            if not answer:
                raise RuntimeError("Responses API returned no answer text")
            return EvalRunResult(
                eval_id=eval_id,
                query_id=query.query_id,
                system_id=self.system_id,
                status="completed",
                answer=answer,
                citations=citations,
                sources=sources,
                duration_seconds=round(time.monotonic() - started, 3),
                usage={
                    **dict(response.get("usage") or {}),
                    "web_search_calls": sum(
                        isinstance(item, dict) and item.get("type") == "web_search_call"
                        for item in response.get("output", []) if isinstance(response.get("output"), list)
                    ),
                },
                model_snapshot={"model": response.get("model", self.model), "background": self.background, "web_search": self.web_search},
            )
        except Exception as exc:
            return _failed_result(eval_id, query.query_id, self.system_id, started, str(exc))

    def build_request_payload(self, query: EvalQuery) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": _neutral_research_prompt(query.query, allow_search=self.web_search),
            "reasoning": {"effort": self.reasoning_effort},
            "background": self.background,
        }
        if self.max_output_tokens:
            payload["max_output_tokens"] = int(self.max_output_tokens)
        if self.max_tool_calls:
            payload["max_tool_calls"] = int(self.max_tool_calls)
        if self.web_search:
            tool: dict[str, Any] = {"type": "web_search"}
            for key in ("search_context_size", "return_token_budget", "external_web_access"):
                if key in self.web_search_options:
                    tool[key] = self.web_search_options[key]
            payload["tools"] = [tool]
            payload["include"] = ["web_search_call.action.sources"]
            if self.web_search_options.get("required"):
                payload["tool_choice"] = "required"
        return payload

    def _create_response(self, query: EvalQuery) -> dict[str, Any]:
        payload = self.build_request_payload(query)
        response = requests.post(
            f"{self.base_url}/responses",
            headers=self._headers(),
            json=payload,
            timeout=min(self.timeout_seconds, 300),
        )
        response.raise_for_status()
        return dict(response.json())

    def _poll_response(self, response_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            response = requests.get(
                f"{self.base_url}/responses/{response_id}",
                headers=self._headers(),
                timeout=60,
            )
            response.raise_for_status()
            payload = dict(response.json())
            if payload.get("status") in {"completed", "failed", "cancelled", "incomplete"}:
                return payload
            time.sleep(self.poll_interval_seconds)
        raise TimeoutError("background response timed out")

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}


class CompatibleLLMAdapter(SystemAdapter):
    """Run a tool-free LLM through Responses or OpenAI-compatible Chat Completions."""

    system_id = "bare_llm"
    ALLOWED_PROTOCOLS = {"responses", "chat_completions"}

    def __init__(
        self,
        *,
        system_id: str = "bare_llm",
        api_protocol: str = "responses",
        model: str = "gpt-5.5",
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float | None = 0.2,
        max_output_tokens: int = DEFAULT_BARE_LLM_OUTPUT_TOKENS,
        reasoning_effort: str | None = None,
        timeout_seconds: int = 900,
        fake: bool = False,
    ) -> None:
        protocol = str(api_protocol or "responses").strip().lower()
        if protocol not in self.ALLOWED_PROTOCOLS:
            raise ValueError(f"unsupported LLM API protocol: {protocol}")
        self.system_id = str(system_id or "bare_llm").strip()
        self.api_protocol = protocol
        self.model = str(model or "").strip()
        self.base_url = normalize_llm_base_url(str(base_url or "")) if base_url else ""
        self.api_key = str(api_key or "")
        self.temperature = None if temperature is None else float(temperature)
        self.max_output_tokens = int(max_output_tokens)
        self.reasoning_effort = str(reasoning_effort or "").strip()
        self.timeout_seconds = int(timeout_seconds)
        self.fake = fake

    @property
    def endpoint(self) -> str:
        suffix = "/responses" if self.api_protocol == "responses" else "/chat/completions"
        base_url = self.base_url
        parsed = urlsplit(base_url)
        # Yunwu exposes its OpenAI-compatible API below /v1 while the user-facing
        # provider URL remains the requested https://yunwu.ai root.
        if parsed.hostname == "yunwu.ai" and not parsed.path.rstrip("/"):
            base_url = f"{base_url}/v1"
        return f"{base_url}{suffix}"

    def run(self, query: EvalQuery, *, eval_id: str, output_dir: Path) -> EvalRunResult:
        started = time.monotonic()
        snapshot = {
            "protocol": self.api_protocol,
            "model": self.model,
            "base_url_host": urlsplit(self.base_url).hostname or "",
        }
        if self.fake:
            label = "智谱 GLM" if self.system_id == "zhipu_llm" else "纯 LLM"
            return EvalRunResult(
                eval_id=eval_id,
                query_id=query.query_id,
                system_id=self.system_id,
                status="completed",
                answer=f"# {query.query}\n\n这是{label}的离线评测回答；未使用联网搜索或工具。",
                citations=[],
                sources=[],
                duration_seconds=round(time.monotonic() - started, 3),
                usage={"input_tokens": 20, "output_tokens": 30},
                model_snapshot=snapshot,
            )
        if not self.base_url:
            return _failed_result(eval_id, query.query_id, self.system_id, started, "LLM API URL is not configured")
        if not self.api_key:
            return _failed_result(eval_id, query.query_id, self.system_id, started, "LLM API key is not configured")
        if not self.model:
            return _failed_result(eval_id, query.query_id, self.system_id, started, "LLM model is not configured")
        try:
            response = None
            for attempt in range(2):
                try:
                    response = requests.post(
                        self.endpoint,
                        headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                        json=self.build_request_payload(query),
                        timeout=(30, min(self.timeout_seconds, 900)),
                    )
                    break
                except (requests.ConnectionError, requests.Timeout):
                    if attempt:
                        raise
                    # The gateway occasionally closes an otherwise valid
                    # connection while several baselines start together. Retry
                    # that transport fault once; semantic/API failures are not
                    # retried and remain visible to the benchmark.
                    time.sleep(0.5)
            assert response is not None
            if not response.ok:
                detail = _redact_secret(_response_error_detail(response), self.api_key)
                raise RuntimeError(f"LLM API returned HTTP {response.status_code}: {detail}")
            payload = dict(response.json())
            if self.api_protocol == "responses":
                answer, citations, sources = parse_responses_output(payload)
            else:
                answer, citations, sources = parse_chat_completions_output(payload)
            if not answer:
                raise RuntimeError("LLM API returned no answer text")
            usage = dict(payload.get("usage") or {})
            snapshot["model"] = str(payload.get("model") or self.model)
            return EvalRunResult(
                eval_id=eval_id,
                query_id=query.query_id,
                system_id=self.system_id,
                status="completed",
                answer=answer,
                citations=citations,
                sources=sources,
                duration_seconds=round(time.monotonic() - started, 3),
                usage=usage,
                model_snapshot=snapshot,
            )
        except Exception as exc:
            return _failed_result(
                eval_id,
                query.query_id,
                self.system_id,
                started,
                _redact_secret(str(exc), self.api_key),
            )

    def build_request_payload(self, query: EvalQuery) -> dict[str, Any]:
        prompt = _neutral_research_prompt(
            query.query,
            allow_search=False,
            max_output_tokens=self.max_output_tokens,
        )
        if self.api_protocol == "responses":
            payload: dict[str, Any] = {"model": self.model, "input": prompt}
            if self.max_output_tokens > 0:
                payload["max_output_tokens"] = self.max_output_tokens
            if self.temperature is not None:
                payload["temperature"] = self.temperature
            if self.reasoning_effort and self.reasoning_effort != "none":
                payload["reasoning"] = {"effort": self.reasoning_effort}
            return payload
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self.max_output_tokens > 0:
            payload["max_tokens"] = self.max_output_tokens
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        return payload


class TongyiDeepResearchAdapter(SystemAdapter):
    """Run Qwen-Deep-Research through its two-stage DashScope SSE API."""

    system_id = "generic_deep_research"

    def __init__(
        self,
        *,
        model: str = "qwen-deep-research",
        base_url: str | None = None,
        api_key: str | None = None,
        output_format: str = "model_detailed_report",
        timeout_seconds: int = 7200,
        fake: bool = False,
        clarification_answer: str | None = None,
    ) -> None:
        self.model = model
        self.base_url = str(base_url or "").rstrip("/")
        self.api_key = str(api_key or "")
        self.output_format = output_format
        self.timeout_seconds = timeout_seconds
        self.fake = fake
        self.clarification_answer = clarification_answer or (
            "无需进一步澄清。请严格按照原始问题覆盖全部范围，优先使用公开、可核验、"
            "时效明确的资料，区分事实与推断，直接开展深入研究并输出详细中文报告。"
        )

    def run(self, query: EvalQuery, *, eval_id: str, output_dir: Path) -> EvalRunResult:
        started = time.monotonic()
        if self.fake:
            source = "https://fixture.local/generic_deep_research"
            return EvalRunResult(
                eval_id=eval_id,
                query_id=query.query_id,
                system_id=self.system_id,
                status="completed",
                answer=f"# {query.query}\n\n这是通义 DeepResearch 的离线评测回答。\n\n来源：{source}",
                citations=[source],
                sources=[source],
                duration_seconds=round(time.monotonic() - started, 3),
                usage={"input_tokens": 20, "output_tokens": 30, "api_calls": 2},
                model_snapshot={"provider": "dashscope", "model": self.model, "fake": True},
            )
        if not self.base_url:
            return _failed_result(eval_id, query.query_id, self.system_id, started, "DashScope base URL is not configured")
        if not self.api_key:
            return _failed_result(eval_id, query.query_id, self.system_id, started, "DashScope API key is not configured")
        try:
            initial_messages = [
                {"role": "user", "content": f"{query.query}\n\n{REPORT_TASK_BRIEF}"}
            ]
            first_events = self._stream_generation(initial_messages)
            clarification = _dashscope_content(first_events).strip()
            if not clarification:
                clarification = "请确认研究范围和重点。"
            research_messages = [
                *initial_messages,
                {"role": "assistant", "content": clarification},
                {"role": "user", "content": self.clarification_answer},
            ]
            research_events = self._stream_generation(research_messages)
            answer = _dashscope_content(research_events).strip()
            if not answer:
                raise RuntimeError("Qwen-Deep-Research returned no report text")
            references = _dashscope_references(research_events)
            citations = sorted({str(row["url"]) for row in references if row.get("url")})
            answer = _append_reference_list(answer, references)
            metadata = {
                "request_ids": _dashscope_request_ids([*first_events, *research_events]),
                "phases": _dashscope_phases([*first_events, *research_events]),
                "search_queries": _dashscope_search_queries(research_events),
                "references": references,
                "usage": _merge_usage(
                    _dashscope_usage(first_events),
                    _dashscope_usage(research_events),
                ),
            }
            output_dir.mkdir(parents=True, exist_ok=True)
            metadata_path = output_dir / "tongyi-run-metadata.json"
            metadata_path.write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            return EvalRunResult(
                eval_id=eval_id,
                query_id=query.query_id,
                system_id=self.system_id,
                status="completed",
                answer=answer,
                citations=citations,
                sources=citations,
                duration_seconds=round(time.monotonic() - started, 3),
                usage={
                    **metadata["usage"],
                    "api_calls": 2,
                    "search_query_count": len(metadata["search_queries"]),
                    "reference_count": len(references),
                },
                model_snapshot={
                    "provider": "dashscope",
                    "model": self.model,
                    "output_format": self.output_format,
                    "region": "cn-beijing",
                    "base_url_host": urlsplit(self.base_url).hostname or "",
                },
                artifact_refs=[str(metadata_path.relative_to(output_dir))],
            )
        except Exception as exc:
            return _failed_result(eval_id, query.query_id, self.system_id, started, str(exc))

    def build_request_payload(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        return {
            "model": self.model,
            "input": {"messages": messages},
            "parameters": {"output_format": self.output_format},
        }

    def _stream_generation(self, messages: list[dict[str, str]]) -> list[dict[str, Any]]:
        endpoint = f"{self.base_url}/services/aigc/text-generation/generation"
        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "X-DashScope-SSE": "enable",
            },
            json=self.build_request_payload(messages),
            stream=True,
            timeout=(30, min(self.timeout_seconds, 900)),
        )
        response.raise_for_status()
        events: list[dict[str, Any]] = []
        for raw_line in response.iter_lines(decode_unicode=True):
            line = str(raw_line or "").strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            if not line or line == "[DONE]":
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            status_code = event.get("status_code")
            if status_code not in {None, 200, "200"}:
                raise RuntimeError(
                    f"DashScope request failed ({status_code}): {event.get('message') or event.get('code') or 'unknown error'}"
                )
            events.append(event)
        if not events:
            raise RuntimeError("DashScope returned no SSE events")
        return events


class CodexGenericAgentAdapter(SystemAdapter):
    """Run a neutral generic web-research agent through an isolated Codex CLI."""

    system_id = "generic_agent"

    def __init__(
        self,
        *,
        command: str = "codex",
        model: str = "gpt-5.5",
        reasoning_effort: str = "high",
        base_url: str | None = None,
        api_key: str | None = None,
        auth_mode: str = "eval_api_key",
        source_codex_home: str | Path | None = None,
        timeout_seconds: int = 1800,
        sandbox: str = "read-only",
        max_tool_calls: int = 12,
        max_output_tokens: int = 7000,
        search_context_size: str = "medium",
        fake: bool = False,
    ) -> None:
        self.command = command
        self.model = model
        self.reasoning_effort = reasoning_effort
        self.base_url = str(base_url or "").rstrip("/")
        self.api_key = str(api_key or "")
        self.auth_mode = auth_mode
        self.source_codex_home = Path(
            source_codex_home or Path.home() / ".codex"
        ).expanduser().resolve()
        self.timeout_seconds = timeout_seconds
        self.sandbox = sandbox
        self.max_tool_calls = max_tool_calls
        self.max_output_tokens = max_output_tokens
        self.search_context_size = search_context_size
        self.fake = fake

    def run(self, query: EvalQuery, *, eval_id: str, output_dir: Path) -> EvalRunResult:
        started = time.monotonic()
        if self.fake:
            source = "https://fixture.local/generic_agent"
            return EvalRunResult(
                eval_id=eval_id,
                query_id=query.query_id,
                system_id=self.system_id,
                status="completed",
                answer=f"# {query.query}\n\n这是 Codex 通用 Agent 的离线评测回答。\n\n来源：{source}",
                citations=[source],
                sources=[source],
                duration_seconds=round(time.monotonic() - started, 3),
                usage={"input_tokens": 20, "output_tokens": 30, "web_search_calls": 1},
                model_snapshot={"adapter": "codex_cli", "model": self.model, "fake": True},
            )
        executable = shutil.which(self.command)
        if not executable:
            return _failed_result(eval_id, query.query_id, self.system_id, started, f"Codex CLI not found: {self.command}")
        if self.auth_mode == "eval_api_key" and not self.api_key:
            return _failed_result(eval_id, query.query_id, self.system_id, started, "OpenAI API key for Codex is not configured")
        if self.auth_mode == "codex_login" and not (self.source_codex_home / "auth.json").is_file():
            return _failed_result(eval_id, query.query_id, self.system_id, started, "Codex login auth is not available")
        runtime_root = output_dir / "runtime"
        codex_home = runtime_root / "codex-home"
        workspace = runtime_root / "workspace"
        codex_home.mkdir(parents=True, exist_ok=True)
        workspace.mkdir(parents=True, exist_ok=True)
        try:
            codex_home.chmod(0o700)
        except OSError:
            pass
        auth_link: Path | None = None
        if self.auth_mode == "codex_login":
            auth_link = codex_home / "auth.json"
            if auth_link.exists() or auth_link.is_symlink():
                auth_link.unlink()
            auth_link.symlink_to(self.source_codex_home / "auth.json")
        command = self.build_command(executable, workspace)
        prompt = _codex_agent_prompt(
            query.query,
            max_tool_calls=self.max_tool_calls,
            max_output_tokens=self.max_output_tokens,
        )
        env = {
            str(key): str(value)
            for key, value in os.environ.items()
            if str(key).upper() not in _CODEX_PARENT_ENV_VARS
        }
        env["CODEX_HOME"] = str(codex_home)
        if self.auth_mode == "eval_api_key":
            env[_CODEX_RUNTIME_API_KEY_ENV] = self.api_key
            env["CODEX_API_KEY"] = self.api_key
        try:
            process = subprocess.run(
                command,
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
            events_path = runtime_root / "codex-events.jsonl"
            events_path.write_text(stdout, encoding="utf-8")
            artifact_refs = [str(events_path.relative_to(output_dir))]
            if stderr.strip():
                stderr_path = runtime_root / "codex-stderr.log"
                stderr_path.write_text(stderr, encoding="utf-8")
                artifact_refs.append(str(stderr_path.relative_to(output_dir)))
            answer, citations, sources, usage, metadata = parse_codex_jsonl(stdout)
            if process.returncode != 0:
                detail = stderr.strip() or metadata.get("error") or stdout[-3000:]
                raise RuntimeError(f"Codex CLI exited {process.returncode}: {detail}")
            if not answer:
                raise RuntimeError("Codex CLI returned no final agent message")
            return EvalRunResult(
                eval_id=eval_id,
                query_id=query.query_id,
                system_id=self.system_id,
                status="completed",
                answer=answer,
                citations=citations,
                sources=sources,
                duration_seconds=round(time.monotonic() - started, 3),
                usage=usage,
                model_snapshot={
                    "adapter": "codex_cli",
                    "model": self.model,
                    "reasoning_effort": self.reasoning_effort,
                    "sandbox": self.sandbox,
                    "web_search": "live",
                    "search_context_size": self.search_context_size,
                    "base_url_host": urlsplit(self.base_url).hostname or "",
                    "auth_mode": self.auth_mode,
                    "codex_version": _codex_version(executable),
                },
                artifact_refs=artifact_refs,
            )
        except subprocess.TimeoutExpired:
            return _failed_result(eval_id, query.query_id, self.system_id, started, "Codex CLI timed out")
        except Exception as exc:
            return _failed_result(eval_id, query.query_id, self.system_id, started, str(exc))
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
            self.sandbox,
            "--ignore-user-config",
            "--ignore-rules",
            "--model",
            self.model,
            "--config",
            'approval_policy="never"',
            "--config",
            f"model_reasoning_effort={json.dumps(self.reasoning_effort)}",
            "--config",
            'web_search="live"',
            "--config",
            f'tools.web_search={{context_size={json.dumps(self.search_context_size)}}}',
        ]
        if self.auth_mode == "eval_api_key" and self.base_url:
            command.extend(
                [
                    "--config",
                    f"model_provider={json.dumps(_CODEX_RUNTIME_PROVIDER_ID)}",
                    "--config",
                    (
                        f"model_providers.{_CODEX_RUNTIME_PROVIDER_ID}="
                        '{name="Benchmark OpenAI Provider",'
                        f"base_url={json.dumps(self.base_url)},"
                        f"env_key={json.dumps(_CODEX_RUNTIME_API_KEY_ENV)},"
                        'wire_api="responses",supports_websockets=false}'
                    ),
                ]
            )
        command.append("-")
        return command


def make_adapter(
    system_id: str,
    project_root: str | Path,
    *,
    fake: bool = False,
    system_config: dict[str, Any] | None = None,
) -> SystemAdapter:
    if system_id == "full_method":
        return FullMethodAdapter(project_root, mode="fake" if fake else "real")
    config = dict(system_config or {})
    if system_id == "generic_deep_research":
        return TongyiDeepResearchAdapter(
            model=str(config.get("model", "qwen-deep-research")),
            base_url=str(config.get("base_url") or "") or None,
            api_key=str(config.get("api_key") or "") or None,
            output_format=str(config.get("output_format", "model_detailed_report")),
            timeout_seconds=int(config.get("timeout_seconds", 7200)),
            fake=fake,
            clarification_answer=str(config.get("clarification_answer") or "") or None,
        )
    if system_id == "generic_agent":
        web_config = dict(config.get("web_search") or {})
        return CodexGenericAgentAdapter(
            command=str(config.get("command", "codex")),
            model=str(config.get("model", "gpt-5.5")),
            reasoning_effort=str(config.get("reasoning_effort", "high")),
            base_url=str(config.get("base_url") or "") or None,
            api_key=str(config.get("api_key") or "") or None,
            auth_mode=str(config.get("auth_mode", "eval_api_key")),
            timeout_seconds=int(config.get("timeout_seconds", 1800)),
            sandbox=str(config.get("sandbox", "read-only")),
            max_tool_calls=int(config.get("max_tool_calls", 12)),
            max_output_tokens=int(
                config.get(
                    "max_output_tokens",
                    DEFAULT_GENERIC_AGENT_OUTPUT_TOKENS,
                )
            ),
            search_context_size=str(web_config.get("search_context_size", "medium")),
            fake=fake,
        )
    if system_id in {"bare_llm", "zhipu_llm"}:
        default_model = "glm-5.2" if system_id == "zhipu_llm" else "gpt-5.5"
        default_protocol = "chat_completions" if system_id == "zhipu_llm" else "responses"
        default_tokens = (
            DEFAULT_ZHIPU_LLM_OUTPUT_TOKENS
            if system_id == "zhipu_llm"
            else DEFAULT_BARE_LLM_OUTPUT_TOKENS
        )
        return CompatibleLLMAdapter(
            system_id=system_id,
            api_protocol=str(config.get("api_protocol", default_protocol)),
            model=str(config.get("model", default_model)),
            reasoning_effort=str(config.get("reasoning_effort", "none")),
            timeout_seconds=int(config.get("timeout_seconds", 3600)),
            fake=fake,
            base_url=str(config.get("base_url") or "") or None,
            api_key=str(config.get("api_key") or "") or None,
            temperature=float(config["temperature"]) if config.get("temperature") is not None else None,
            max_output_tokens=int(config.get("max_output_tokens", default_tokens)),
        )
    raise ValueError(f"unknown benchmark system: {system_id}")


def parse_codex_jsonl(output: str) -> tuple[str, list[str], list[str], dict[str, Any], dict[str, Any]]:
    final_message = ""
    last_message = ""
    sources: set[str] = set()
    search_queries: list[str] = []
    usage: dict[str, Any] = {}
    thread_id = ""
    error = ""
    web_search_calls = 0
    tool_call_count = 0
    for raw_line in output.splitlines():
        try:
            envelope = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(envelope, Mapping):
            continue
        event = envelope.get("msg") if isinstance(envelope.get("msg"), Mapping) else envelope
        if not isinstance(event, Mapping):
            continue
        event_type = str(event.get("type", ""))
        if event_type == "thread.started":
            thread_id = str(event.get("thread_id", ""))
        if event_type in {"error", "turn.failed", "response.failed"}:
            error = str(event.get("message") or event.get("error") or event)
        if event_type in {"item.started", "item.completed"}:
            item = event.get("item")
            if not isinstance(item, Mapping):
                continue
            item_type = str(item.get("type", ""))
            if item_type == "agent_message":
                text = str(item.get("text", "")).strip()
                if text:
                    last_message = text
                    if event_type == "item.completed":
                        final_message = text
            elif event_type == "item.completed":
                tool_call_count += 1
                if "search" in item_type.lower():
                    web_search_calls += 1
                _collect_url_and_query_values(item, sources, search_queries)
        if event_type in {"turn.completed", "response.completed"}:
            raw_usage = event.get("usage")
            if isinstance(raw_usage, Mapping):
                usage = {str(key): value for key, value in raw_usage.items()}
        _collect_url_and_query_values(event, sources, search_queries)
    answer = final_message or last_message
    citations = sorted(set(URL_PATTERN.findall(answer)))
    sources.update(citations)
    usage.update(
        {
            "web_search_calls": web_search_calls,
            "tool_call_count": tool_call_count,
            "search_query_count": len(set(search_queries)),
        }
    )
    metadata = {
        "thread_id": thread_id,
        "search_queries": list(dict.fromkeys(search_queries)),
        "error": error,
    }
    return answer, citations, sorted(sources), usage, metadata


def _dashscope_content(events: list[dict[str, Any]]) -> str:
    result = ""
    for event in events:
        output = event.get("output")
        if not isinstance(output, Mapping):
            continue
        message = output.get("message")
        if not isinstance(message, Mapping):
            continue
        chunk = str(message.get("content") or "")
        if not chunk:
            continue
        # DashScope normally emits deltas, but accepting cumulative chunks makes
        # the adapter robust to SDK/gateway variations without duplicating text.
        if chunk.startswith(result) and len(chunk) > len(result):
            result = chunk
        elif not result.endswith(chunk):
            result += chunk
    return result


def _dashscope_references(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    for event in events:
        output = event.get("output")
        message = output.get("message") if isinstance(output, Mapping) else None
        extra = message.get("extra") if isinstance(message, Mapping) else None
        deep = extra.get("deep_research") if isinstance(extra, Mapping) else None
        references = deep.get("references") if isinstance(deep, Mapping) else None
        if not isinstance(references, list):
            continue
        for row in references:
            if not isinstance(row, Mapping) or not row.get("url"):
                continue
            url = str(row["url"])
            by_url[url] = {
                "index_number": row.get("index_number"),
                "title": str(row.get("title") or ""),
                "description": str(row.get("description") or ""),
                "url": url,
            }
    return sorted(
        by_url.values(),
        key=lambda row: (
            row.get("index_number") if isinstance(row.get("index_number"), int) else 10**9,
            row["url"],
        ),
    )


def _dashscope_search_queries(events: list[dict[str, Any]]) -> list[str]:
    queries: list[str] = []
    for event in events:
        output = event.get("output")
        message = output.get("message") if isinstance(output, Mapping) else None
        extra = message.get("extra") if isinstance(message, Mapping) else None
        deep = extra.get("deep_research") if isinstance(extra, Mapping) else None
        query = deep.get("query") if isinstance(deep, Mapping) else None
        if isinstance(query, Mapping) and query.get("query"):
            queries.append(str(query["query"]))
        elif isinstance(query, str) and query.strip():
            queries.append(query.strip())
    return list(dict.fromkeys(queries))


def _dashscope_usage(events: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for event in events:
        usage = event.get("usage")
        if isinstance(usage, Mapping):
            result = {str(key): value for key, value in usage.items()}
    return result


def _dashscope_request_ids(events: list[dict[str, Any]]) -> list[str]:
    return list(
        dict.fromkeys(
            str(event.get("request_id"))
            for event in events
            if event.get("request_id")
        )
    )


def _dashscope_phases(events: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for event in events:
        output = event.get("output")
        message = output.get("message") if isinstance(output, Mapping) else None
        if isinstance(message, Mapping) and message.get("phase"):
            result.append(str(message["phase"]))
    return list(dict.fromkeys(result))


def _merge_usage(*rows: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for row in rows:
        for key, value in row.items():
            if isinstance(value, (int, float)) and isinstance(result.get(str(key), 0), (int, float)):
                result[str(key)] = result.get(str(key), 0) + value
            else:
                result[str(key)] = value
    return result


def _append_reference_list(answer: str, references: list[dict[str, Any]]) -> str:
    missing = [row for row in references if row.get("url") and str(row["url"]) not in answer]
    if not missing:
        return answer
    lines = [answer.rstrip(), "", "## 参考来源"]
    for position, row in enumerate(missing, start=1):
        index = row.get("index_number") or position
        title = str(row.get("title") or "来源")
        lines.append(f"[{index}] [{title}]({row['url']})")
    return "\n".join(lines).strip()


def _collect_url_and_query_values(
    value: Any,
    sources: set[str],
    search_queries: list[str],
    *,
    parent_key: str = "",
) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in {"query", "search_query"} and isinstance(child, str) and child.strip():
                search_queries.append(child.strip())
            _collect_url_and_query_values(child, sources, search_queries, parent_key=normalized)
    elif isinstance(value, list):
        for child in value:
            _collect_url_and_query_values(child, sources, search_queries, parent_key=parent_key)
    elif isinstance(value, str):
        if parent_key in {"url", "uri", "href"} and value.startswith(("http://", "https://")):
            sources.add(value)
        else:
            sources.update(URL_PATTERN.findall(value))


# 所有 benchmark baseline 共用的交付物任务书，统一采用三层九项报告格式。
REPORT_TASK_BRIEF = (
    "市场需求挖掘报告：\n"
    "**【第一层：需求挖掘层——场景·战法/技术·装备能力特征】**\n"
    "① 构造并论证该概念适用的典型作战场景\n"
    "② 阐明牵引该需求的新战法或新概念技术及其制胜机理\n"
    "③ 凝练所需装备的能力特征清单（关键能力域+定性特征+定量指标方向）\n"
    "**【第二层：技术攻关层——能力实现途径与核心技术】**\n"
    "④ 针对每项能力特征，给出能力实现途径的总体判断（沿用改进/集成创新/原理突破）；\n"
    "⑤ 分解出需重点攻关的核心技术清单（精确到技术点）\n"
    "⑥ 指出关键技术之间的耦合关系与短板风险（哪项技术卡脖子会拖垮整个能力）。\n"
    "**【第三层：能力图像与效能贡献层】**\n"
    "⑦ 绘制该装备的能力图像（能力域构成、指标画像、与现有装备体系的谱系位置）；\n"
    "⑧ 评估效能贡献：在所述场景下对杀伤链/作战体系的贡献方式与可量化方向\n"
    "⑨ 给出发展优先级建议与近期可启动的抓手（演示验证项目构想）。"
)

_ANTI_LEAK_RULE = "不要在报告中自述身份、工具或工作流程，不要描述评测过程，不要猜测或比较其他系统。"


def _codex_agent_prompt(query: str, *, max_tool_calls: int, max_output_tokens: int) -> str:
    return (
        "你是一个通用联网研究 Agent。不要读取或分析本地工作区文件，不要修改任何文件或系统状态，"
        "不要使用任何军事垂类技能、项目配置或预置路线。只使用通用推理与实时公开网络搜索完成任务。\n\n"
        f"研究问题：\n{query}\n\n"
        f"{REPORT_TASK_BRIEF}\n"
        "引用你实际查看过的公开 HTTPS 来源，并让引用可点击。"
        f"最多进行约 {max_tool_calls} 次搜索或工具操作，最终报告控制在 {max_output_tokens} token 以内。"
        f"{_ANTI_LEAK_RULE}"
    )


def _codex_version(executable: str) -> str:
    try:
        process = subprocess.run(
            [executable, "--version"],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        return (process.stdout or process.stderr).strip().splitlines()[-1]
    except Exception:
        return ""


def _redact_secret(value: str, secret: str) -> str:
    return str(value or "").replace(secret, "[REDACTED]") if secret else str(value or "")


def parse_responses_output(payload: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    text_parts: list[str] = []
    citations: list[str] = []
    sources: list[str] = []
    for item in payload.get("output", []) if isinstance(payload.get("output"), list) else []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message":
            for content in item.get("content", []) if isinstance(item.get("content"), list) else []:
                if not isinstance(content, dict):
                    continue
                if content.get("type") in {"output_text", "text"}:
                    text_parts.append(str(content.get("text", "")))
                for annotation in content.get("annotations", []) if isinstance(content.get("annotations"), list) else []:
                    if isinstance(annotation, dict) and annotation.get("url"):
                        citations.append(str(annotation["url"]))
        if item.get("type") == "web_search_call":
            action = item.get("action", {})
            if isinstance(action, dict):
                for source in action.get("sources", []) if isinstance(action.get("sources"), list) else []:
                    if isinstance(source, dict) and source.get("url"):
                        sources.append(str(source["url"]))
    answer = "\n".join(part for part in text_parts if part).strip()
    if not answer and payload.get("output_text"):
        answer = str(payload["output_text"])
    citations.extend(URL_PATTERN.findall(answer))
    return answer, sorted(set(citations)), sorted(set([*citations, *sources]))


def parse_chat_completions_output(payload: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    choices = payload.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], Mapping) else {}
    message = choice.get("message") if isinstance(choice.get("message"), Mapping) else {}
    content = message.get("content")
    text_parts: list[str] = []
    if isinstance(content, str):
        text_parts.append(content)
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, Mapping):
                text = item.get("text")
                if isinstance(text, Mapping):
                    text = text.get("value")
                if text:
                    text_parts.append(str(text))
    if not text_parts and choice.get("text"):
        text_parts.append(str(choice["text"]))
    answer = "\n".join(part for part in text_parts if part).strip()
    citations = sorted(set(URL_PATTERN.findall(answer)))
    return answer, citations, citations


def normalize_llm_base_url(value: str) -> str:
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("LLM API URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("LLM API URL must not contain credentials, query parameters, or fragments")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("LLM API URL must use HTTPS; HTTP is allowed only for localhost")
    path = parsed.path.rstrip("/")
    for suffix in ("/chat/completions", "/responses"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return urlunsplit((parsed.scheme, parsed.netloc, path.rstrip("/"), "", "")).rstrip("/")


def _response_error_detail(response: requests.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, Mapping):
            error = payload.get("error")
            if isinstance(error, Mapping):
                return str(error.get("message") or error.get("code") or "request failed")[:1000]
            if error:
                return str(error)[:1000]
            if payload.get("message"):
                return str(payload["message"])[:1000]
    except Exception:
        pass
    return str(getattr(response, "text", "") or "request failed")[:1000]


def _neutral_research_prompt(
    query: str,
    *,
    allow_search: bool,
    max_output_tokens: int | None = None,
) -> str:
    source_rule = (
        "引用你实际查看过的公开网络资料，并让引用可点击"
        if allow_search
        else "你无法联网检索：不得假装已联网或编造来源，引用仅限确有把握的公开资料，不确定的事实必须明确说明"
    )
    length_rule = (
        f"采用简洁、低推理开销的写法，不展示思维过程；最终报告不得超过 {max_output_tokens} token。"
        if max_output_tokens and max_output_tokens > 0
        else "采用简洁写法，不展示思维过程。"
    )
    return (
        f"研究问题：\n{query}\n\n"
        f"{REPORT_TASK_BRIEF}\n"
        f"{source_rule}。{length_rule}{_ANTI_LEAK_RULE}"
    )


def _summary_sources(summary: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for row in summary.get("source_materials", []) if isinstance(summary, dict) else []:
        if isinstance(row, dict):
            url = row.get("source_url") or row.get("url")
            if url:
                result.append(str(url))
    return result


def _collect_usage(payload: Any) -> dict[str, Any]:
    totals: dict[str, float] = {}

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            usage = value.get("usage")
            if isinstance(usage, dict):
                for key, number in usage.items():
                    if isinstance(number, (int, float)):
                        totals[str(key)] = totals.get(str(key), 0.0) + float(number)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    return {key: int(value) if value.is_integer() else value for key, value in totals.items()}


def _collect_run_usage(run_dir: Path, summary: dict[str, Any]) -> dict[str, Any]:
    totals: dict[str, float] = {
        key: float(value)
        for key, value in _collect_usage(summary).items()
        if isinstance(value, (int, float))
    }
    trace_event_count = 0
    tool_call_count = 0
    search_event_count = 0
    for path in [run_dir / "trace.jsonl", *(run_dir / "agent_sessions").glob("*.jsonl")]:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            for key, value in _collect_usage(row).items():
                if isinstance(value, (int, float)):
                    totals[key] = totals.get(key, 0.0) + float(value)
            if path.name == "trace.jsonl":
                trace_event_count += 1
                event_name = str(row.get("event_type") or row.get("type") or "").lower()
                tool_call_count += int("tool" in event_name)
                search_event_count += int("search" in event_name or "fetch" in event_name)
    totals.update(
        {
            "trace_event_count": float(trace_event_count),
            "tool_call_count": float(tool_call_count),
            "search_event_count": float(search_event_count),
        }
    )
    return {key: int(value) if value.is_integer() else round(value, 6) for key, value in totals.items()}


def _failed_result(eval_id: str, query_id: str, system_id: str, started: float, error: str) -> EvalRunResult:
    return EvalRunResult(
        eval_id=eval_id,
        query_id=query_id,
        system_id=system_id,
        status="failed",
        duration_seconds=round(time.monotonic() - started, 3),
        error=error[:5000],
    )


def _env_first(*names: str) -> str:
    return next((os.environ[name] for name in names if os.environ.get(name)), "")
