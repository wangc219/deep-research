"""On-demand, bounded subagents for deep equipment research.

Subagents here are deliberately lightweight: a task has one isolated prompt,
one structured return value and one merge contract.  They are not a second
orchestration graph and they never receive the parent transcript or provider
credentials.  The parent runtime decides whether the extra perspective is
worth its budget, then merges only the public result.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import re
from typing import Any

from equipment_deep_research.deep_runtime.provider_runtime import ProviderRuntime


def _text(value: Any, limit: int = 1200) -> str:
    return _sanitize_string(" ".join(str(value or "").split()).strip())[: max(0, int(limit))]


_SENSITIVE_KEY_MARKERS = (
    "authorization",
    "apikey",
    "accesstoken",
    "refreshtoken",
    "password",
    "secret",
    "cookie",
    "credential",
    "privatekey",
    "rawsession",
    "rawmessage",
    "rawresponse",
    "providerresponse",
    "providermetadata",
    "providerheaders",
    "hiddenreasoning",
    "reasoningtrace",
    "chainofthought",
    "internalprompt",
    "systemprompt",
    "rawoutput",
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret|authorization|cookie)\b"
    r"\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_HIDDEN_BLOCK_RE = re.compile(
    r"(?is)<(?:think|analysis|reasoning)>.*?</(?:think|analysis|reasoning)>"
)


def _normalized_key(key: Any) -> str:
    return "".join(character for character in str(key).lower() if character.isalnum())


def _is_sensitive_key(key: Any) -> bool:
    normalized = _normalized_key(key)
    return any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS) or normalized in {
        "token",
        "key",
        "auth",
    }


def _sanitize_string(value: str) -> str:
    value = _HIDDEN_BLOCK_RE.sub("<redacted>", value)
    value = _BEARER_RE.sub("Bearer <redacted>", value)
    return _SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(0).split('=', 1)[0].split(':', 1)[0]}=<redacted>",
        value,
    )


def _bounded(value: Any, *, depth: int = 0) -> Any:
    if depth >= 4:
        return "<truncated>" if isinstance(value, str) else None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _sanitize_string(value)[:1600]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in list(value.items())[:32]:
            name = str(key)[:120]
            result[name] = "<redacted>" if _is_sensitive_key(name) else _bounded(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_bounded(item, depth=depth + 1) for item in list(value)[:16]]
    return _sanitize_string(str(value))[:1600]


@dataclass(frozen=True, slots=True)
class SubagentTask:
    """A separable research probe with an explicit merge contract."""

    task_id: str
    role: str
    prompt: str
    merge_contract: str
    context: Mapping[str, Any] = field(default_factory=dict)
    output_schema: Mapping[str, Any] = field(
        default_factory=lambda: {
            "finding": "string",
            "assumptions": ["string"],
            "next_probe": "string",
        }
    )
    max_output_tokens: int = 1400

    def __post_init__(self) -> None:
        task_id = _text(self.task_id, 120)
        role = _text(self.role, 160)
        prompt = _text(self.prompt, 2400)
        contract = _text(self.merge_contract, 500)
        if not task_id or not role or not prompt or not contract:
            raise ValueError("subagent task requires id, role, prompt and merge_contract")
        if not isinstance(self.context, Mapping) or not isinstance(self.output_schema, Mapping):
            raise TypeError("subagent context and output_schema must be objects")
        object.__setattr__(self, "task_id", task_id)
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "prompt", prompt)
        object.__setattr__(self, "merge_contract", contract)
        object.__setattr__(self, "context", _bounded(dict(self.context)))
        object.__setattr__(self, "output_schema", _bounded(dict(self.output_schema)))
        object.__setattr__(self, "max_output_tokens", max(256, min(int(self.max_output_tokens), 4000)))

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "role": self.role,
            "prompt": self.prompt,
            "merge_contract": self.merge_contract,
            "context": dict(self.context),
        }


@dataclass(frozen=True, slots=True)
class SubagentResult:
    task_id: str
    role: str
    status: str
    finding: Any = None
    assumptions: tuple[str, ...] = ()
    next_probe: str = ""
    error: str = ""
    provider: Mapping[str, Any] = field(default_factory=dict)

    def to_public(self) -> dict[str, Any]:
        result = {
            "task_id": self.task_id,
            "role": self.role,
            "status": self.status,
            "finding": _bounded(self.finding),
            "assumptions": list(self.assumptions[:8]),
            "next_probe": _text(self.next_probe, 500),
        }
        if self.error:
            result["error"] = _text(self.error, 500)
        if self.provider:
            result["provider"] = _bounded(dict(self.provider))
        return result


class LightweightSubagentRunner:
    """Run at most a few isolated probes and return mergeable summaries."""

    def __init__(
        self,
        runtime: ProviderRuntime | None = None,
        *,
        max_concurrent: int = 2,
        max_tasks: int = 2,
    ) -> None:
        if max_concurrent < 1 or max_tasks < 1:
            raise ValueError("subagent limits must be positive")
        self.runtime = runtime
        self.max_concurrent = min(int(max_concurrent), 4)
        self.max_tasks = min(int(max_tasks), 4)
        self._semaphore = asyncio.Semaphore(self.max_concurrent)

    @classmethod
    def from_host(cls, host: Any, *, max_tasks: int = 2) -> "LightweightSubagentRunner | None":
        runtime = ProviderRuntime.from_host(host)
        if runtime is None:
            return None
        return cls(runtime, max_tasks=max_tasks)

    async def run(self, task: SubagentTask) -> SubagentResult:
        if self.runtime is None:
            return SubagentResult(task.task_id, task.role, "unavailable", error="no provider runtime")
        async with self._semaphore:
            try:
                raw = await self.runtime.complete_json(
                    agent_id=f"deep_subagent_{task.task_id}",
                    system=(
                        "你是深研系统的轻量独立子 Agent。只完成一个可合并的研究探针。"
                        "不要输出制造参数、具体操作步骤、秘密、完整会话或父任务证据。"
                        "canonical_equipment_identity 是不可变的单装备身份锁；"
                        "可以提出该装备的创新变体，但不得换成另一件源装备、虚构新的卡谱系或把"
                        "不同装备拼成一个对象。"
                        "严格遵守给定 merge_contract，只返回 JSON。\n"
                        f"角色：{task.role}\n任务：{task.prompt}\n"
                        f"合并契约：{task.merge_contract}"
                    ),
                    payload=task.to_prompt_payload(),
                    output_schema=task.output_schema,
                    max_output_tokens=task.max_output_tokens,
                    phase="deep_runtime_subagent",
                )
                if not isinstance(raw, Mapping):
                    return SubagentResult(task.task_id, task.role, "invalid", error="subagent output is not an object")
                if raw.get("_provider_error"):
                    return SubagentResult(
                        task.task_id,
                        task.role,
                        "invalid",
                        error="provider returned invalid structured output",
                        provider=self.runtime.snapshot(),
                    )
                finding = raw.get("finding", raw.get("summary"))
                if finding in (None, "", [], {}):
                    return SubagentResult(
                        task.task_id,
                        task.role,
                        "invalid",
                        error="subagent output has no mergeable finding",
                        provider=self.runtime.snapshot(),
                    )
                assumptions = raw.get("assumptions", [])
                if not isinstance(assumptions, Sequence) or isinstance(assumptions, (str, bytes)):
                    assumptions = []
                return SubagentResult(
                    task.task_id,
                    task.role,
                    "completed",
                    finding=finding,
                    assumptions=tuple(_text(item, 300) for item in assumptions if _text(item, 300))[:8],
                    next_probe=_text(raw.get("next_probe"), 500),
                    provider=self.runtime.snapshot(),
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return SubagentResult(task.task_id, task.role, "failed", error=f"{type(exc).__name__}: {exc}")

    async def run_many(self, tasks: Sequence[SubagentTask]) -> list[SubagentResult]:
        selected = [task for task in tasks[: self.max_tasks] if isinstance(task, SubagentTask)]
        if not selected:
            return []
        return list(await asyncio.gather(*(self.run(task) for task in selected)))


def default_divergence_subtasks(question: str, *, context: Mapping[str, Any] | None = None) -> list[SubagentTask]:
    """Build two orthogonal probes for an explicit open-divergence request."""

    safe_context = dict(context or {})
    return [
        SubagentTask(
            task_id="configuration_probe",
            role="装备构型探针",
            prompt=f"围绕专家问题「{_text(question, 700)}」寻找一种与当前主线正交的单装备构型假设。",
            merge_contract="返回一个构型假设、改变的作战假设和一条需要主 Agent 验证的因果链。",
            context=safe_context,
        ),
        SubagentTask(
            task_id="countermeasure_probe",
            role="反制边界探针",
            prompt=f"围绕专家问题「{_text(question, 700)}」寻找最低成本反制、失效边界和仍可成立的修订方向。",
            merge_contract="返回一个最强反例、失效条件和一条可继续研究的修订建议。",
            context=safe_context,
        ),
    ]


def tasks_from_payload(
    raw: Any,
    *,
    question: str,
    context: Mapping[str, Any] | None = None,
) -> list[SubagentTask]:
    """Normalize explicit task descriptors without accepting executable code."""

    if raw is None:
        return []
    if raw is True:
        return default_divergence_subtasks(question, context=context)
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    tasks: list[SubagentTask] = []
    for index, item in enumerate(raw[:4]):
        if isinstance(item, SubagentTask):
            tasks.append(item)
            continue
        if not isinstance(item, Mapping):
            continue
        try:
            tasks.append(
                SubagentTask(
                    task_id=str(item.get("task_id") or item.get("id") or f"probe_{index + 1}"),
                    role=str(item.get("role") or "独立研究探针"),
                    prompt=str(item.get("prompt") or item.get("task") or ""),
                    merge_contract=str(item.get("merge_contract") or item.get("merge") or "返回一条可合并的研究发现和下一探针"),
                    # The caller's bounded context carries the server-owned
                    # identity lock.  A client task descriptor may add hints,
                    # but cannot overwrite that protected projection.
                    context={**dict(item.get("context") or {}), **dict(context or {})},
                    output_schema=item.get("output_schema") or {
                        "finding": "string",
                        "assumptions": ["string"],
                        "next_probe": "string",
                    },
                    max_output_tokens=int(item.get("max_output_tokens", 1400)),
                )
            )
        except (TypeError, ValueError):
            continue
    return tasks


__all__ = [
    "LightweightSubagentRunner",
    "SubagentResult",
    "SubagentTask",
    "default_divergence_subtasks",
    "tasks_from_payload",
]
