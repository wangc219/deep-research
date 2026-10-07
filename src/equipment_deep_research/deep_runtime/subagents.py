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
    slug: str = ""
    kind: str = "research"
    system_prompt: str = ""

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
        object.__setattr__(self, "slug", _text(self.slug, 80))
        object.__setattr__(self, "kind", _text(self.kind, 40) or "research")
        object.__setattr__(self, "system_prompt", _text(self.system_prompt, 4000))

    def to_prompt_payload(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "role": self.role,
            "slug": self.slug,
            "kind": self.kind,
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
    slug: str = ""
    kind: str = "research"
    run_id: str = ""

    def to_public(self) -> dict[str, Any]:
        result = {
            "task_id": self.task_id,
            "role": self.role,
            "status": self.status,
            "finding": _bounded(self.finding),
            "assumptions": list(self.assumptions[:8]),
            "next_probe": _text(self.next_probe, 500),
        }
        if self.slug:
            result["slug"] = _text(self.slug, 80)
        if self.kind:
            result["kind"] = _text(self.kind, 40)
        if self.run_id:
            result["run_id"] = _text(self.run_id, 80)
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
                role_prompt = task.system_prompt or (
                    f"角色：{task.role}\n任务：{task.prompt}\n"
                    f"合并契约：{task.merge_contract}"
                )
                raw = await self.runtime.complete_json(
                    agent_id=f"deep_subagent_{task.slug or task.task_id}",
                    system=(
                        "你是深研系统的独立子 Agent，只完成调用方给出的单个子任务。"
                        "不要输出制造参数、具体操作步骤、秘密、完整会话或父任务证据。"
                        "canonical_equipment_identity 是不可变的单装备身份锁；"
                        "可以提出该装备的创新变体，但不得换成另一件源装备、虚构新的卡谱系或把"
                        "不同装备拼成一个对象。"
                        "不能继续调用其他子智能体。"
                        "严格遵守给定 merge_contract，只返回 JSON。\n"
                        f"{role_prompt}\n"
                        f"角色：{task.role}\n任务：{task.prompt}\n"
                        f"合并契约：{task.merge_contract}"
                    ),
                    payload=task.to_prompt_payload(),
                    output_schema=task.output_schema,
                    max_output_tokens=task.max_output_tokens,
                    phase="deep_runtime_subagent",
                )
                if not isinstance(raw, Mapping):
                    return SubagentResult(
                        task.task_id,
                        task.role,
                        "invalid",
                        error="subagent output is not an object",
                        slug=task.slug,
                        kind=task.kind,
                    )
                if raw.get("_provider_error"):
                    return SubagentResult(
                        task.task_id,
                        task.role,
                        "invalid",
                        error="provider returned invalid structured output",
                        provider=self.runtime.snapshot(),
                        slug=task.slug,
                        kind=task.kind,
                    )
                finding = raw.get("finding", raw.get("summary"))
                if finding in (None, "", [], {}):
                    return SubagentResult(
                        task.task_id,
                        task.role,
                        "invalid",
                        error="subagent output has no mergeable finding",
                        provider=self.runtime.snapshot(),
                        slug=task.slug,
                        kind=task.kind,
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
                    slug=task.slug,
                    kind=task.kind,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return SubagentResult(
                    task.task_id,
                    task.role,
                    "failed",
                    error=f"{type(exc).__name__}: {exc}",
                    slug=task.slug,
                    kind=task.kind,
                )

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
                    slug=str(item.get("slug") or ""),
                    kind=str(item.get("kind") or "research"),
                    system_prompt=str(item.get("system_prompt") or ""),
                )
            )
        except (TypeError, ValueError):
            continue
    return tasks


@dataclass(frozen=True, slots=True)
class SubagentPreset:
    """A first-class specialized SubAgent the main Agent may dispatch."""

    slug: str
    name: str
    description: str
    role: str
    kind: str
    system_prompt: str
    merge_contract: str
    default_prompt: str

    def public_payload(self) -> dict[str, str]:
        return {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "role": self.role,
            "kind": self.kind,
            "backend": "SubAgentBackend",
        }

    def to_task(
        self,
        question: str,
        *,
        context: Mapping[str, Any] | None = None,
        prompt: str = "",
        task_id: str = "",
    ) -> SubagentTask:
        focused = _text(
            prompt or self.default_prompt.replace("{question}", _text(question, 700)),
            2400,
        )
        return SubagentTask(
            task_id=_text(task_id, 80) or self.slug.replace("-", "_"),
            role=self.role,
            prompt=focused,
            merge_contract=self.merge_contract,
            context=dict(context or {}),
            slug=self.slug,
            kind=self.kind,
            system_prompt=self.system_prompt,
        )


BUILTIN_SUBAGENT_PRESETS: tuple[SubagentPreset, ...] = (
    SubagentPreset(
        slug="research-explorer",
        name="调研探索员",
        description="围绕单个子问题检索公开线索与工作记忆，交叉验证后返回带缺口的结构化发现。",
        role="深度调研",
        kind="research",
        system_prompt=(
            "你是调研探索员子智能体。只围绕调用方给定的单个子问题收集可追溯发现。"
            "优先使用调用方给出的工作记忆与已有证据，再提出需要主 Agent 验证的公开检索方向。"
            "不要写成完整报告，不要调用其他子智能体。"
        ),
        merge_contract="返回该子问题的结构化发现、关键假设和一条主 Agent 应验证的下一探针。",
        default_prompt="围绕专家问题「{question}」收集足以推进单装备创新判断的证据线索与缺口。",
    ),
    SubagentPreset(
        slug="fact-verifier",
        name="事实核查员",
        description="对给定论断做对抗式核验，给出支持/存疑/反驳、依据与置信度。",
        role="对抗核验",
        kind="verification",
        system_prompt=(
            "你是事实核查员子智能体。默认持怀疑态度：证据不足时判定存疑，而不是相信。"
            "寻找能反驳论断的最低成本反制和失效边界。不要调用其他子智能体。"
        ),
        merge_contract="返回最强反例或存疑点、失效条件和一条仍可成立的修订建议。",
        default_prompt="围绕专家问题「{question}」核验当前方向中最容易被推翻的论断。",
    ),
    SubagentPreset(
        slug="data-analyst",
        name="数据分析员",
        description="整理工作记忆与已有证据中的结构化线索，比较冲突并量化缺口。",
        role="数据分析",
        kind="analysis",
        system_prompt=(
            "你是数据分析员子智能体。只分析调用方给出的已有证据和工作记忆摘要。"
            "比较冲突、标出覆盖缺口，不编造未提供的数据，不调用其他子智能体。"
        ),
        merge_contract="返回可比较的数据要点、冲突项和需要补证的量化缺口。",
        default_prompt="围绕专家问题「{question}」分析已有资料中的冲突、覆盖缺口和可比较指标。",
    ),
    SubagentPreset(
        slug="content-generator",
        name="内容生成员",
        description="把已收敛发现组织成可合并的研究叙述，不扩展新的源装备身份。",
        role="内容生成",
        kind="generation",
        system_prompt=(
            "你是内容生成员子智能体。只根据已有发现组织结构化叙述，供主 Agent 综合。"
            "不发明新的源装备，不写成能力卡五栏，不调用其他子智能体。"
        ),
        merge_contract="返回一段可合并的研究叙述、保留的冲突和待验证假设。",
        default_prompt="围绕专家问题「{question}」把当前发现整理成可直接并入主答复的结构化叙述。",
    ),
)


def builtin_subagent_catalog() -> tuple[dict[str, str], ...]:
    return tuple(item.public_payload() for item in BUILTIN_SUBAGENT_PRESETS)


def preset_by_slug(slug: str) -> SubagentPreset | None:
    wanted = _text(slug, 80)
    return next((item for item in BUILTIN_SUBAGENT_PRESETS if item.slug == wanted), None)


_ORTHOGONAL_LENSES: tuple[tuple[str, str, str], ...] = (
    (
        "configuration",
        "装备构型",
        "围绕专家问题「{question}」寻找一种与当前主线正交的单装备构型或进入窗口假设，说明改写了哪条作战假设，并标出证据缺口。",
    ),
    (
        "mechanism",
        "作用机理",
        "围绕专家问题「{question}」闭合从进入、作用到直接毁伤或任务失能的因果链，标出断点和需要主 Agent 验证的下一探针。",
    ),
    (
        "countermeasure",
        "反制边界",
        "围绕专家问题「{question}」寻找最低成本反制、失效边界和仍可成立的修订方向。",
    ),
)


def decompose_research_lenses(
    plan: Sequence[str],
    *,
    max_items: int = 2,
) -> tuple[tuple[str, str, str], ...]:
    """Split a complex turn into orthogonal, independently researchable lenses."""

    tools = {str(item) for item in plan}
    limit = max(1, min(int(max_items), 3))
    if "challenge" in tools:
        selected = (_ORTHOGONAL_LENSES[2],)
    elif "synthesize" in tools:
        selected = ()
    elif "deepen" in tools:
        selected = (_ORTHOGONAL_LENSES[1], _ORTHOGONAL_LENSES[0])
    else:
        selected = (_ORTHOGONAL_LENSES[0], _ORTHOGONAL_LENSES[2])
    return tuple(selected[:limit])


def public_subagent_findings(
    results: Sequence[SubagentResult | Mapping[str, Any]],
    *,
    limit: int = 4,
) -> list[dict[str, Any]]:
    """Project completed SubAgent results into a bounded merge packet."""

    findings: list[dict[str, Any]] = []
    for item in list(results)[: max(1, min(int(limit), 4))]:
        payload = item.to_public() if isinstance(item, SubagentResult) else dict(item)
        if str(payload.get("status", "")).lower() not in {"completed", ""}:
            continue
        finding = payload.get("finding")
        if isinstance(finding, Mapping):
            finding = finding.get("summary") or finding.get("finding") or finding
        text = _text(finding, 400)
        if not text:
            continue
        assumptions = payload.get("assumptions", [])
        if not isinstance(assumptions, Sequence) or isinstance(assumptions, (str, bytes)):
            assumptions = []
        findings.append(
            {
                "role": _text(payload.get("role"), 80),
                "slug": _text(payload.get("slug"), 80),
                "task_id": _text(payload.get("task_id"), 80),
                "finding": text,
                "assumptions": [
                    _text(value, 160) for value in list(assumptions)[:3] if _text(value, 160)
                ],
                "next_probe": _text(payload.get("next_probe"), 240),
            }
        )
    return findings


def attach_prior_findings(
    task: SubagentTask,
    results: Sequence[SubagentResult | Mapping[str, Any]],
) -> SubagentTask:
    """Give a verifier/generator the previous wave's mergeable findings only."""

    prior = public_subagent_findings(results)
    extra = (
        "先核验下列并行调研发现中影响结论的论断；证据不足则判定存疑，不要写入确信结论。"
        if prior and task.kind == "verification"
        else "基于下列并行调研发现组织可合并叙述，不要原文拼接。"
        if prior
        else ""
    )
    return SubagentTask(
        task_id=task.task_id,
        role=task.role,
        prompt=_text(f"{task.prompt} {extra}".strip(), 2400),
        merge_contract=task.merge_contract,
        context={**dict(task.context), "prior_subagent_findings": prior},
        output_schema=dict(task.output_schema),
        max_output_tokens=task.max_output_tokens,
        slug=task.slug,
        kind=task.kind,
        system_prompt=task.system_prompt,
    )


def plan_subagent_tasks(
    plan: Sequence[str],
    question: str,
    *,
    context: Mapping[str, Any] | None = None,
    allowed_slugs: Sequence[str] | None = None,
    max_tasks: int = 3,
) -> list[SubagentTask]:
    """Decompose a complex turn, then return tasks the caller starts together.

    Research-explorer is the main force: orthogonal sub-questions are dispatched
    as separate explorer runs.  A verifier or generator, if selected, is meant
    to run in a second wave after those findings exist.
    """

    allowed = {
        _text(item, 80)
        for item in (
            allowed_slugs
            if allowed_slugs is not None
            else [preset.slug for preset in BUILTIN_SUBAGENT_PRESETS]
        )
        if _text(item, 80)
    }
    tools = {str(item) for item in plan}
    budget = max(1, min(int(max_tasks), 4))
    tasks: list[SubagentTask] = []
    explorer = preset_by_slug("research-explorer")
    verifier = preset_by_slug("fact-verifier")
    generator = preset_by_slug("content-generator")
    reserve_follow = 0
    if "synthesize" in tools and generator is not None and generator.slug in allowed:
        reserve_follow = 1
    elif "challenge" in tools and verifier is not None and verifier.slug in allowed:
        reserve_follow = 1
    elif ("research_council" in tools or "diverge" in tools) and verifier is not None and verifier.slug in allowed:
        reserve_follow = 1
    explorer_slots = max(0, budget - reserve_follow)
    if explorer is not None and explorer.slug in allowed and explorer_slots and "synthesize" not in tools:
        if "challenge" in tools:
            lenses = ()
        else:
            lenses = decompose_research_lenses(plan, max_items=explorer_slots)
        for lens_id, _label, template in lenses:
            tasks.append(
                explorer.to_task(
                    question,
                    context=context,
                    prompt=template.replace("{question}", _text(question, 700)),
                    task_id=f"research_explorer_{lens_id}",
                )
            )
            if len(tasks) >= explorer_slots:
                break
    if len(tasks) < budget:
        if "synthesize" in tools and generator is not None and generator.slug in allowed:
            tasks.append(generator.to_task(question, context=context))
        elif verifier is not None and verifier.slug in allowed and (
            "challenge" in tools or "research_council" in tools or "diverge" in tools
        ):
            tasks.append(verifier.to_task(question, context=context))
    return tasks[:budget]


@dataclass
class SubagentHandle:
    """Immediate receipt from ``subagent_start``; await to read the mergeable result."""

    run_id: str
    thread_id: str
    slug: str
    task_id: str
    role: str
    status: str = "running"


class SubagentPool:
    """Yuxi-style start-then-await pool with bounded parallel execution.

    Independent tasks are started first so they overlap, then awaited.
    Child runs cannot spawn another SubAgent layer.
    """

    def __init__(
        self,
        runner: LightweightSubagentRunner | None = None,
        *,
        max_concurrent: int = 3,
        max_tasks: int = 3,
        nested: bool = False,
    ) -> None:
        self.runner = runner
        self.max_concurrent = max(1, min(int(max_concurrent), 4))
        self.max_tasks = max(1, min(int(max_tasks), 4))
        self.nested = bool(nested)
        self._active: dict[str, asyncio.Task[SubagentResult]] = {}
        self._results: dict[str, SubagentResult] = {}
        self._handles: dict[str, SubagentHandle] = {}
        self._started = 0

    @classmethod
    def from_host(cls, host: Any, **kwargs: Any) -> "SubagentPool | None":
        runner = LightweightSubagentRunner.from_host(host, max_tasks=kwargs.get("max_tasks", 3))
        if runner is None:
            return None
        return cls(runner, **kwargs)

    def _reject_nested(self, task: SubagentTask) -> SubagentResult | None:
        if not self.nested:
            return None
        return SubagentResult(
            task.task_id,
            task.role,
            "failed",
            error="subagents cannot spawn further subagents",
            slug=task.slug,
            kind=task.kind,
        )

    async def start(self, task: SubagentTask) -> SubagentHandle:
        """Dispatch one SubAgent and return immediately with a run id."""

        nested = self._reject_nested(task)
        run_id = f"sub-{task.task_id}-{self._started + 1}"
        handle = SubagentHandle(
            run_id=run_id,
            thread_id=f"thread-{task.slug or task.task_id}",
            slug=task.slug,
            task_id=task.task_id,
            role=task.role,
            status="queued" if nested is None else "failed",
        )
        if nested is not None:
            self._results[run_id] = nested
            handle.status = "failed"
            self._handles[run_id] = handle
            return handle
        if self.runner is None:
            self._results[run_id] = SubagentResult(
                task.task_id, task.role, "unavailable", error="no provider runtime",
                slug=task.slug, kind=task.kind, run_id=run_id,
            )
            handle.status = "unavailable"
            self._handles[run_id] = handle
            return handle
        if self._started >= self.max_tasks:
            self._results[run_id] = SubagentResult(
                task.task_id, task.role, "failed", error="subagent task budget exceeded",
                slug=task.slug, kind=task.kind, run_id=run_id,
            )
            handle.status = "failed"
            self._handles[run_id] = handle
            return handle
        self._started += 1
        handle.status = "running"
        self._handles[run_id] = handle
        self._active[run_id] = asyncio.create_task(self.runner.run(task), name=run_id)
        return handle

    def status(self, run_id: str) -> dict[str, Any]:
        handle = self._handles.get(run_id)
        if handle is None:
            return {"run_id": run_id, "status": "unknown"}
        if run_id in self._results:
            return {**handle.__dict__, **self._results[run_id].to_public(), "status": self._results[run_id].status}
        task = self._active.get(run_id)
        status = "completed" if task is not None and task.done() else handle.status
        return {**handle.__dict__, "status": status}

    async def await_run(self, run_id: str) -> SubagentResult:
        if run_id in self._results:
            return self._results[run_id]
        task = self._active.get(run_id)
        handle = self._handles.get(run_id)
        if task is None:
            return SubagentResult(
                handle.task_id if handle else run_id,
                handle.role if handle else "",
                "unknown",
                error="subagent run not found",
                run_id=run_id,
            )
        result = await task
        if result.run_id:
            stored = result
        else:
            stored = SubagentResult(
                result.task_id,
                result.role,
                result.status,
                finding=result.finding,
                assumptions=result.assumptions,
                next_probe=result.next_probe,
                error=result.error,
                provider=result.provider,
                slug=result.slug,
                kind=result.kind,
                run_id=run_id,
            )
        self._results[run_id] = stored
        self._active.pop(run_id, None)
        if handle is not None:
            handle.status = stored.status
        return stored

    async def cancel(self, run_id: str) -> dict[str, Any]:
        task = self._active.get(run_id)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        handle = self._handles.get(run_id)
        cancelled = SubagentResult(
            handle.task_id if handle else run_id,
            handle.role if handle else "",
            "cancelled",
            error="cancelled by parent",
            slug=handle.slug if handle else "",
            run_id=run_id,
        )
        self._results[run_id] = cancelled
        self._active.pop(run_id, None)
        if handle is not None:
            handle.status = "cancelled"
        return cancelled.to_public()

    async def dispatch_parallel(self, tasks: Sequence[SubagentTask]) -> list[SubagentResult]:
        """Start independent SubAgents first, then await all of them."""

        selected = [task for task in list(tasks)[: self.max_tasks] if isinstance(task, SubagentTask)]
        handles = [await self.start(task) for task in selected]
        return [await self.await_run(handle.run_id) for handle in handles]

    async def dispatch_research_waves(self, tasks: Sequence[SubagentTask]) -> list[SubagentResult]:
        """Explore independent sub-questions first, then verify or generate from those findings."""

        selected = [task for task in list(tasks) if isinstance(task, SubagentTask)]
        explore = [task for task in selected if task.kind in {"research", "analysis"}]
        follow = [task for task in selected if task.kind in {"verification", "generation"}]
        leftover = [
            task for task in selected if task not in explore and task not in follow
        ]
        if leftover:
            explore.extend(leftover)
        if not explore or not follow:
            return await self.dispatch_parallel(selected)
        first = await self.dispatch_parallel(explore)
        second = await self.dispatch_parallel(
            [attach_prior_findings(task, first) for task in follow]
        )
        return [*first, *second]


__all__ = [
    "BUILTIN_SUBAGENT_PRESETS",
    "LightweightSubagentRunner",
    "SubagentHandle",
    "SubagentPool",
    "SubagentPreset",
    "SubagentResult",
    "SubagentTask",
    "attach_prior_findings",
    "builtin_subagent_catalog",
    "decompose_research_lenses",
    "default_divergence_subtasks",
    "plan_subagent_tasks",
    "preset_by_slug",
    "public_subagent_findings",
    "tasks_from_payload",
]
