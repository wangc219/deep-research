"""Reporter workflow service using the provider host as its runtime port."""
# ruff: noqa: F821

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from collections.abc import Mapping, Sequence

from equipment_deep_research.agents.workflows import coordinator as _legacy
from equipment_deep_research.agents.workflows.reporting_support import (
    _limit_report_capability_cues,
    _report_capability_image_table_directions,
    _report_chapter_mechanical_issues,
    _report_equipment_attribution_issues,
    _report_table_issues,
)
from equipment_deep_research.providers.responses import ProviderRequestError


_REPORT_PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"


def _read_parallel_fragment_prompt(filename: str, **values: str) -> str:
    prompt = (_REPORT_PROMPT_DIR / "parallel" / filename).read_text(
        encoding="utf-8"
    )
    for key, value in values.items():
        prompt = prompt.replace("{{" + key + "}}", value)
    return prompt


def _report_substantive_char_count(text: str) -> int:
    """Count alnum/CJK characters that carry report substance."""

    return len(re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", str(text or "")))


def _parallel_column_repair_floor(target_chars: int) -> int:
    """Return the thin-column trigger line for one parallel Reporter section."""

    try:
        target = int(target_chars)
    except (TypeError, ValueError):
        target = 900
    return max(120, int(target * 0.55))


def _parallel_report_output_cap(
    requested_tokens: int,
    payload: Mapping[str, Any] | object,
) -> int:
    """Bound an isolated column turn to the amount of prose it can publish.

    The old 4k-8k allowance let a short column spend most of its turn in
    hidden planning and then become the wall-clock tail of an otherwise fully
    parallel wave. The cap is derived from the section target, with enough
    headroom for headings, tables and normal reasoning. It is an output
    budget, not a content truncation rule: a provider that finishes earlier is
    accepted as-is and the structural/semantic gates still decide quality.
    """

    try:
        requested = max(1200, int(requested_tokens))
    except (TypeError, ValueError):
        requested = 4000
    contract = payload.get("parallel_section_contract", {}) if isinstance(payload, Mapping) else {}
    # Compatibility callers that do not provide the isolated-column contract
    # are full Reporter turns; keep their historical allowance unchanged.
    if not isinstance(contract, Mapping) or not contract:
        return min(requested, 8000)
    try:
        target = max(300, int(contract.get("target_chars", 0))) if isinstance(contract, Mapping) else 900
    except (TypeError, ValueError):
        target = 900
    target_cap = max(1800, int(target * 2.15) + 420)
    return min(requested, target_cap, 5600)


def _repair_reason_fingerprint(reasons: Sequence[str]) -> tuple[str, ...]:
    """Normalize review reasons so one root cause cannot loop indefinitely."""

    roots: set[str] = set()
    for reason in reasons:
        text = " ".join(str(reason or "").split()).strip().lower()
        if not text:
            continue
        text = re.sub(r"第?\d+(?:\.\d+)?(?:字|次|个|组)", "#", text)
        text = re.sub(r"仅#字|目标约#字|低于约#字", "长度偏短", text)
        if "未返回" in text or "调用异常" in text:
            root = "transport_or_empty"
        elif "标题" in text or "级标题" in text:
            root = "heading_contract"
        elif "偏短" in text or "过短" in text or "正文为空" in text:
            root = "substance_floor"
        elif "四级" in text or "表格" in text or "markdown" in text:
            root = "markup_contract"
        elif "归属" in text or "装备" in text and "对应" in text:
            root = "equipment_attribution"
        elif "重复" in text or "套话" in text or "占位" in text:
            root = "mechanical_repetition"
        else:
            root = text[:180]
        roots.add(root)
    return tuple(sorted(roots))


def _parallel_column_navigation_preamble(*, project_mode: bool) -> str:
    """Keep parallel authors on a single-column contract, not a full-report brief."""

    if project_mode:
        return (
            "你是项目论证研究报告的并行单栏作者。整份报告由其他隔离会话分别撰写其余栏目；"
            "你只完成本栏合同内的标题与正文，不得代写完整五章或其他栏目。"
            "research_handoff.capability_cues中的capability_portrait是已通过质量门的装备能力画像原料；"
            "须重新综合为本栏论证，不得逐字照录，也不得因篇幅删减关键因果。"
        )
    return (
        "你是三层九项研究报告的并行单栏作者。整份报告由其他隔离会话分别撰写其余栏目；"
        "你只完成本栏合同内的标题与正文，不得代写完整九项或其他栏目。"
        "research_handoff中的装备事实须重新综合为本栏判断，不得照录长句。"
    )


globals().update(
    {name: value for name, value in vars(_legacy).items() if not name.startswith("__")}
)


def _provider_snapshot(provider: object) -> dict[str, object]:
    """Return a secret-safe provider snapshot for routing diagnostics."""

    snapshot = getattr(provider, "snapshot", lambda: {})()
    return dict(snapshot) if isinstance(snapshot, Mapping) else {}


def _provider_has_backup(provider: object) -> bool:
    """Whether ``provider`` exposes an explicitly selectable backup lane."""

    checker = getattr(provider, "has_backup_provider", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:
            return False
    providers = getattr(provider, "providers", ())
    return bool(
        str(getattr(provider, "provider_type", "")) == "fallback_chain"
        and isinstance(providers, (tuple, list))
        and len(providers) > 1
    )


_REPORTER_CHAPTER_FALLBACK_PROVIDER = "deepseek"


def _is_unified_model_profile(profile_id: str) -> bool:
    """Return whether ``profile_id`` is a model-profiles.yaml archive id."""

    if not profile_id:
        return False
    try:
        from equipment_deep_research.model_profiles import get_profile

        get_profile(profile_id)
    except (KeyError, OSError, ValueError):
        return False
    return True


def _deepseek_provider_env_ready() -> bool:
    """True when the DeepSeek provider can read API key and URL from env."""

    key_env = (
        os.environ.get("EQUIPMENT_DR_DEEPSEEK_API_KEY_ENV", "").strip()
        or "DEEPSEEK_API_KEY"
    )
    return bool(
        os.environ.get(key_env, "").strip()
        and os.environ.get("EQUIPMENT_DR_DEEPSEEK_BASE_URL", "").strip()
    )


def _resolve_reporter_provider(
    host,
    *,
    isolation_id: str,
    force_fallback: bool,
    provider_profile: str = "",
) -> tuple[object, bool]:
    """Resolve the Reporter provider, optionally selecting DeepSeek.

    Normal Reporter calls retain the host's configured provider chain.  The
    explicit recovery path first uses the ``deepseek`` provider (URL and API
    from env), then the already isolated backup in a Codex chain. A missing
    credential is surfaced as a real provider error so the caller can preserve
    completed chapters and publish an honest limited artifact.
    """

    provider = host._provider_for("reporter", isolation_id=isolation_id)
    if not force_fallback:
        return provider, False
    requested = str(provider_profile or "").strip()
    model_factory = getattr(host, "model_profile_factory", None)
    provider_factory = getattr(host, "provider_factory", None)

    def create_model_profile(profile_id: str):
        if not profile_id or not callable(model_factory):
            return None
        profile_isolation = (
            f"{isolation_id}:{profile_id}" if isolation_id else f"reporter:{profile_id}"
        )
        try:
            return model_factory(profile_id, profile_isolation)
        except Exception:
            return None

    def create_provider(name: str):
        if not name or not callable(provider_factory):
            return None
        provider_isolation = (
            f"{isolation_id}:{name}" if isolation_id else f"reporter:{name}"
        )
        try:
            return provider_factory(name, provider_isolation)
        except Exception as exc:
            raise ProviderRequestError(
                f"DeepSeek fallback unavailable: {name} provider could not be created"
            ) from exc

    if requested:
        if _is_unified_model_profile(requested):
            candidate = create_model_profile(requested)
            if candidate is not None:
                return candidate, False
        else:
            candidate = create_provider(requested)
            if candidate is not None:
                return candidate, False
    if _provider_has_backup(provider):
        # FallbackProvider understands these private, reporter-only options
        # and skips the primary provider without changing ordinary capacity
        # fallback behavior for any other lane.
        return provider, True

    candidate = create_provider(_REPORTER_CHAPTER_FALLBACK_PROVIDER)
    if candidate is not None:
        return candidate, False

    snapshot = _provider_snapshot(provider)
    provider_name = str(
        snapshot.get("provider_id")
        or snapshot.get("model")
        or snapshot.get("type")
        or "primary"
    )
    raise ProviderRequestError(
        f"DeepSeek fallback unavailable after Reporter retries (primary={provider_name})"
    )


_TITLE_REWRITE_MARKERS = (
    "只提出",
    "按创新性",
    "按需求性",
    "评分",
    "综合评分",
    "只选前",
    "生成入选",
    "验收",
    "档案",
    "对应分析阶段",
    "请研究",
    "请分析",
)


def _needs_title_rewrite(topic: str) -> bool:
    """Detect task-like user queries that are unsuitable as report titles."""

    value = " ".join(str(topic or "").split()).strip()
    return bool(
        len(value) > 42
        or any(marker in value for marker in _TITLE_REWRITE_MARKERS)
        or "：" in value
        or ":" in value
        or "（" in value
        or "(" in value
    )


def _fallback_academic_title(topic: str) -> str:
    """Conservatively remove execution instructions when the model is unavailable."""

    value = " ".join(str(topic or "").split()).strip()
    if not value:
        return "军事武器装备需求研究"
    value = re.split(r"[：:]", value, maxsplit=1)[0].strip()
    value = re.sub(r"[（(].*?[）)]", "", value).strip(" ，,；;。．")
    value = re.sub(
        r"(?:只提出|按创新性|按需求性|按科学可行性|按效能性|按发展性|综合评分|只选前\d+|生成入选.*)$",
        "",
        value,
    ).strip(" ，,；;。．")
    if not value.endswith(("研究", "分析", "论证")):
        value += "研究"
    return value[:80]


def _clean_rewritten_title(value: object) -> str:
    title = " ".join(str(value or "").split()).strip()
    title = re.sub(r"^#{1,6}\s*", "", title)
    title = re.sub(r"^(?:题目|标题)\s*[：:]\s*", "", title, flags=re.I)
    title = title.strip(" \"'“”‘’《》【】：:。．")
    if "\n" in title:
        title = title.splitlines()[0].strip()
    if not title or len(title) > 80 or any(marker in title for marker in _TITLE_REWRITE_MARKERS):
        return ""
    if not re.search(r"[\u4e00-\u9fff]", title):
        return ""
    return title


def _reporter_chapter_fallback_profile(host, payload: Mapping[str, Any]) -> str:
    """Resolve the DeepSeek provider for failed chapter retries.

    Chapter fallback is opt-in by deployment capability. An explicit payload or
    environment id still wins; otherwise the ``deepseek`` provider is used so
    URL and API come from the unified env, not the ``codex-deepseek``
    model-profile archive. An unconfigured backup must not duplicate the
    primary call or change legacy/fake test behavior.
    """

    explicit = str(
        payload.get("reporter_chapter_fallback_profile")
        or os.environ.get("EQUIPMENT_DR_REPORTER_CHAPTER_FALLBACK_PROFILE", "")
    ).strip()
    if explicit:
        return explicit
    if os.environ.get("EQUIPMENT_DR_REPORTER_CHAPTER_FALLBACK", "1").strip() == "0":
        return ""
    provider_id = _REPORTER_CHAPTER_FALLBACK_PROVIDER
    # An embedding application may expose only a configured fallback chain,
    # without a provider factory. That chain is still sufficient for the
    # explicit Reporter recovery wave.
    try:
        configured = getattr(host, "agent_providers", {}).get(
            "reporter",
            getattr(host, "provider", None),
        )
        if _provider_has_backup(configured):
            return provider_id
    except Exception:
        pass
    if not callable(getattr(host, "provider_factory", None)) and not callable(
        getattr(host, "model_profile_factory", None)
    ):
        return ""
    if not _deepseek_provider_env_ready():
        return ""
    return provider_id


def _reporter_handoff_is_substantive(handoff: object) -> bool:
    """Check for actual evidence/weapon material before spending a fallback wave."""

    if not isinstance(handoff, Mapping):
        return []
    cues = handoff.get("capability_cues", [])
    if isinstance(cues, Sequence) and not isinstance(cues, (str, bytes)):
        if any(
            isinstance(item, Mapping) and _report_capability_cue_is_substantive(item)
            for item in cues
        ):
            return True
    for key in (
        "decisive_anchors",
        "mission_chain_breaks",
        "counterevidence_and_limits",
        "priority_signals",
    ):
        value = handoff.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            if any(str(item).strip() for item in value):
                return True
        elif str(value or "").strip():
            return True
    comparative = handoff.get("comparative_status")
    if isinstance(comparative, Mapping):
        return any(
            value not in (None, "", [], {}) for value in comparative.values()
        )
    return bool(comparative)


def _portfolio_explicit_safety_blockers(portfolio_gate: object) -> list[str]:
    """Return only blockers that explicitly describe a publication/safety risk."""

    if not isinstance(portfolio_gate, Mapping):
        return []
    raw = portfolio_gate.get("hard_blockers", [])
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    markers = ("unsafe", "safety", "安全", "致命", "危险", "不可交战")
    return [
        str(item)
        for item in raw
        if any(marker in str(item).lower() for marker in markers)
    ]


def _reporter_calls_remaining(host) -> int | None:
    """Read the finite Reporter lane budget without imposing a wall timeout."""

    budgets = getattr(host, "_runtime_budgets", None)
    if not isinstance(budgets, Mapping) or not budgets:
        return None
    try:
        limit = int(
            budgets.get(
                "maximum_reporter_model_calls",
                budgets.get("maximum_delivery_model_calls", 8),
            )
        )
        # Older embedders do not expose the dedicated counter; retain their
        # delivery counter as a compatibility fallback without coupling new
        # Reporter runs to unrelated delivery calls.
        used = int(
            getattr(
                host,
                "_budget_started_reporter_calls",
                getattr(host, "_budget_started_delivery_calls", 0),
            )
        )
    except (TypeError, ValueError):
        return None
    return max(0, limit - used)


def _reporter_column_timeout_seconds(wave: str, *, target_chars: int = 0) -> float:
    """Return a bounded column attempt timeout so a hung model can fail over."""

    settings = {
        "initial": ("EQUIPMENT_DR_REPORT_COLUMN_TIMEOUT_SECONDS", 1200.0),
        "retry": ("EQUIPMENT_DR_REPORT_RETRY_TIMEOUT_SECONDS", 600.0),
        "fallback": ("EQUIPMENT_DR_REPORT_FALLBACK_TIMEOUT_SECONDS", 900.0),
    }
    key, default = settings.get(wave, settings["retry"])
    try:
        target = int(target_chars)
    except (TypeError, ValueError):
        target = 0
    if 0 < target <= 700:
        default = {"initial": 300.0, "retry": 180.0, "fallback": 240.0}.get(
            wave, 180.0
        )
    elif 0 < target <= 1000:
        default = {"initial": 480.0, "retry": 300.0, "fallback": 360.0}.get(
            wave, 300.0
        )
    try:
        configured = max(0.0, float(os.environ.get(key, str(default))))
    except (TypeError, ValueError):
        configured = default
    # Deployment settings remain an upper bound.  A short section must not
    # inherit a 20-minute global tail merely because the environment carries
    # the historical long-form timeout.
    return min(configured, default) if target > 0 else configured


async def _await_reporter_column(
    awaitable, *, wave: str, target_chars: int = 0
) -> str:
    """Await one isolated column without allowing a stalled stream to block all peers."""

    timeout = _reporter_column_timeout_seconds(wave, target_chars=target_chars)
    if timeout <= 0:
        return await awaitable
    return await asyncio.wait_for(awaitable, timeout=timeout)


def _start_reporter_request(
    host,
    system: str,
    payload: dict[str, Any],
    max_output_tokens: int,
    *,
    phase: str,
    run_id: str = "",
    isolation_id: str = "",
    force_fallback: bool = False,
    fallback_reason: str = "",
    provider_profile: str = "",
):
    """Start a Reporter coroutine while preserving old embedding seams."""

    base_kwargs = {
        "phase": phase,
        "run_id": run_id,
        "isolation_id": isolation_id,
    }
    extended_kwargs = dict(base_kwargs)
    if force_fallback:
        extended_kwargs.update(
            {
                "force_fallback": True,
                "fallback_reason": fallback_reason,
            }
        )
    if provider_profile:
        extended_kwargs["provider_profile"] = provider_profile
    try:
        return host._run_reporter_text(
            system,
            payload,
            max_output_tokens,
            **extended_kwargs,
        )
    except TypeError as exc:
        # A few embedders/tests replace the host seam with the pre-fallback
        # five-argument coroutine. Only retry when the error is caused by the
        # newly added routing keywords; never mask a TypeError from a real
        # Reporter implementation.
        message = str(exc)
        if extended_kwargs != base_kwargs and "unexpected keyword" in message:
            return host._run_reporter_text(
                system,
                payload,
                max_output_tokens,
                **base_kwargs,
            )
        raise


def _rewrite_report_title(host, topic: str, *, run_id: str = "") -> str:
    """Use the Reporter model to turn a task-like query into an academic title."""

    fallback = _fallback_academic_title(topic)
    remaining = _reporter_calls_remaining(host)
    if (
        not _needs_title_rewrite(topic)
        or not callable(getattr(host, "_run_reporter_text", None))
        or (remaining is not None and remaining <= 0)
    ):
        return fallback
    system = (
        "你是军事武器装备研究报告的学术化题目编辑。只输出一个中文题目，不加引号、编号或解释。"
        "将用户任务型Query压缩为‘作战场景/约束 + 研究对象 + 核心能力 + 研究’的规范题目；"
        "删除候选数量、评分权重、阶段流程、验收说明、GPT或档案标记。题目应具体、通用、可用于正式研究报告，"
        "长度控制在20至50字以内，优先以‘研究’或‘需求研究’结尾。"
    )
    try:
        # Title normalization is part of deferred report delivery. Keep it on
        # the same unbounded Reporter path as the body; a short auxiliary
        # timeout could otherwise abort an otherwise healthy report before the
        # user-facing report artifact is written.
        text = asyncio.run(
            host._run_reporter_text(
                system,
                {"query": str(topic).strip()[:1200]},
                120,
                phase="report_title_rewrite",
                run_id=run_id,
            )
        )
        return _clean_rewritten_title(text) or fallback
    except Exception:
        return fallback

def draft_report(host, payload: dict[str, Any]) -> str:
    host._latest_report_title = _rewrite_report_title(
        host,
        str(payload.get("topic", "")),
        run_id=str(payload.get("run_id", "")),
    )
    host._last_report_quality_issues = []
    host._latest_report_draft = ""
    portfolio_gate = payload.get("portfolio_quality_gate", {})
    # Dynamic swarm portfolio checks are an internal innovation/novelty
    # review, not a publication prerequisite.  A sparse or empty finalist
    # set must be carried into the Reporter as an explicit limitation so the
    # report can still explain the evidence boundary and baseline findings.
    # Only explicit safety/publication blockers are allowed to stop delivery;
    # the mechanical portfolio cardinality/diversity score is advisory.
    # Portfolio cardinality/diversity findings are advisory.  Keep them in
    # the handoff for explanation, while reserving hard stops for explicit
    # publication-safety failures discovered after Reporter output exists.
    explicit_safety_blockers = _portfolio_explicit_safety_blockers(portfolio_gate)
    if explicit_safety_blockers:
        raise ValueError(
            "winning swarm safety gate blocked Reporter: "
            + "; ".join(explicit_safety_blockers[:4])
        )
    # Reporter normal mode is deliberately quality-first: xhigh, a real
    # 12k output ceiling, and a bounded but long-form main attempt. Reporter
    # is explicitly exempt from runtime reasoning/token downshift; upstream
    # stages absorb deadline pressure instead.
    # Report generation is a deferred delivery stage.  It has no wall-clock
    # hard timeout: the run exposes S6 capability images as soon as they are
    # durable, while the Reporter continues independently until a complete
    # report is available or the provider returns a real failure.  Provider
    # transport cancellation remains the only timeout boundary.
    try:
        timeout_seconds = max(
            0.0,
            float(os.environ.get("EQUIPMENT_DR_REPORT_TIMEOUT_SECONDS", "3600")),
        )
    except (TypeError, ValueError):
        timeout_seconds = 3600.0
    try:
        retry_timeout_seconds = max(
            0.0,
            float(os.environ.get("EQUIPMENT_DR_REPORT_RETRY_TIMEOUT_SECONDS", "180")),
        )
    except (TypeError, ValueError):
        retry_timeout_seconds = 180.0
    reporter_agent = host.agent_definitions.get("reporter")
    reporter_input = _reporter_generation_payload(payload, reporter_agent)
    output_token_budget = _reporter_output_token_budget(payload, default=12000)
    strict_model_delivery = bool(
        str(payload.get("execution_profile_id", ""))
        in {"swarm_quality_v1", "winning_swarm_dynamic_v2"}
        and _reporter_handoff_is_substantive(
            reporter_input.get("research_handoff")
        )
    )
    # Reporter chapter fan-out is a delivery invariant whenever the handoff is
    # substantive, independent of which approved/challenger profile produced
    # it.  The explicit environment switch remains an operator escape hatch
    # for legacy deployments that must keep the old monolithic call.
    profile_requests_parallel = str(payload.get("execution_profile_id", "")) in {
        "swarm_quality_v1",
        "winning_swarm_dynamic_v2",
    }
    # Only a native, explicitly persisted research_handoff is strong enough to
    # opt a non-profile caller into chapter fan-out.  ``synthesis_seed`` is a
    # legacy compatibility input and may contain a few capability cues without
    # the complete evidence/identity contract required by parallel writers.
    # Treating that sparse seed as substantive used to bypass the normal
    # full-report retry path and return a limited artifact after a transient
    # failure. Dynamic swarm profiles remain explicitly parallel by contract.
    native_research_handoff = isinstance(payload.get("research_handoff"), Mapping)
    parallel_reporter_enabled = (
        os.environ.get("EQUIPMENT_DR_PARALLEL_REPORTER", "1") != "0"
        and callable(getattr(host, "_draft_parallel_report", None))
        and (
            profile_requests_parallel
            or (
                native_research_handoff
                and _reporter_handoff_is_substantive(
                    reporter_input.get("research_handoff")
                )
            )
        )
    )
    if parallel_reporter_enabled:
        try:
            return host._draft_parallel_report(
                payload,
                reporter_input=reporter_input,
                output_token_budget=output_token_budget,
            )
        except (TimeoutError, ProviderRequestError, ValueError, RuntimeError) as exc:
            # Parallel authoring has already retried only failed chapters and
            # sent only those chapters through the configured DeepSeek lane.
            # Keep every completed chapter in ``_latest_report_draft`` and do
            # not launch a second full-report author: doing so can overwrite
            # good, equipment-specific prose with a fresh generic report.
            if strict_model_delivery:
                # A completed model draft is still deliverable when the
                # residual gate findings are advisory (for example URL
                # punctuation, heading drift, or other non-structural
                # quality diagnostics).  Chapter omissions have already
                # consumed the chapter-local repair waves above; preserve
                # those successful rewrites and let the limited-delivery
                # path record any remaining issues instead of hard-failing
                # the whole report.
                return host._limited_report_delivery(payload, failure=exc)
            return host._limited_report_delivery(payload, failure=exc)
    try:
        return host._draft_report_attempt(
            payload,
            reporter_agent=reporter_agent,
            reporter_input=reporter_input,
            output_token_budget=output_token_budget,
            timeout_seconds=timeout_seconds,
            phase="report_generation",
            allow_repair=False,
            allow_limited=False,
        )
    except (TimeoutError, ProviderRequestError, ValueError, RuntimeError) as exc:
        # A quality/structure rejection is deterministic and is already
        # recoverable by the limited-delivery builder.  Retrying the whole
        # report for these failures wastes a model call and can overwrite a
        # useful handoff with another generic draft.  Reserve the single
        # full-quality retry for transport/runtime timeouts only.
        if not isinstance(exc, (TimeoutError, ProviderRequestError)):
            return host._limited_report_delivery(payload, failure=exc)
        # Always spend one targeted retry before limited delivery, including
        # sparse legacy callers. This keeps transient ValueError/RuntimeError
        # failures from bypassing the recovery path entirely.
        retry_input = dict(reporter_input)
        retry_input["retry_instruction"] = (
            "上一完整质量调用因传输、运行时异常或内容质量缺陷未完成。仍按本任务约定的报告结构、"
            "完整逐装备事实和证据边界独立重写完整报告，不得压缩为限时版或降低研究深度。"
        )
        try:
            return host._draft_report_attempt(
                payload,
                reporter_agent=reporter_agent,
                reporter_input=retry_input,
                output_token_budget=output_token_budget,
                timeout_seconds=retry_timeout_seconds,
                phase="report_generation_full_quality_retry",
                allow_repair=False,
                allow_limited=False,
            )
        except (TimeoutError, ProviderRequestError, ValueError, RuntimeError) as retry_exc:
            # The serial path has no chapter fan-out to recover. Give the
            # configured DeepSeek backup one independent full-report attempt
            # after the primary retry, then fall back to the existing honest
            # limited-delivery path if the backup is absent or also fails.
            fallback_profile = _reporter_chapter_fallback_profile(host, payload)
            if not fallback_profile or not _reporter_handoff_is_substantive(
                reporter_input.get("research_handoff")
            ):
                if strict_model_delivery:
                    raise ProviderRequestError(
                        "Reporter primary retry failed and DeepSeek fallback is unavailable"
                    ) from retry_exc
                return host._limited_report_delivery(
                    payload,
                    failure=retry_exc,
                )
            try:
                return host._draft_report_attempt(
                    payload,
                    reporter_agent=reporter_agent,
                    reporter_input={
                        **retry_input,
                        "retry_instruction": (
                            "主模型重试仍未完成。由DeepSeek备用模型独立完成整份报告；"
                            "保留Query分析、具体装备事实、证据边界和中国现状，不输出降级模板。"
                        ),
                    },
                    output_token_budget=output_token_budget,
                    timeout_seconds=retry_timeout_seconds,
                    phase="report_generation_deepseek_fallback",
                    allow_repair=False,
                    allow_limited=False,
                    force_fallback=True,
                    provider_profile=fallback_profile,
                )
            except (TimeoutError, ProviderRequestError, ValueError, RuntimeError) as fallback_exc:
                if strict_model_delivery:
                    raise ProviderRequestError(
                        "Reporter primary and DeepSeek fallback attempts failed"
                    ) from fallback_exc
                return host._limited_report_delivery(
                    payload,
                    failure=fallback_exc,
                )


def draft_parallel_report(
    host,
    payload: Mapping[str, Any],
    *,
    reporter_input: dict[str, Any],
    output_token_budget: int,
) -> str:
    """Generate every top-level section concurrently without a hard cutoff."""

    # Keep a machine-readable failure map for the orchestrator.  It is used by
    # delivery-only resume to target only failed columns and is intentionally
    # cleared on a fully successful assembly.
    host._last_report_failed_columns = []

    # Author one decision-bearing H3 per isolated Reporter call.  The former
    # three-layer/three-column split forced one model context to solve several
    # different editorial problems and encouraged a shared paragraph skeleton.
    # Ordered assembly below restores the three-layer navigation contract.
    legacy_sections = (
        (
            "item_1_scenario",
            "第一层：需求挖掘层——场景·战法/技术·装备能力特征",
            ["① 典型作战场景"],
            1600,
            4200,
            [],
        ),
        (
            "item_2_winning_mechanism",
            "第一层：需求挖掘层——场景·战法/技术·装备能力特征",
            ["② 新战法或新概念技术及制胜机理"],
            1500,
            4000,
            [],
        ),
        (
            "item_3_capability_features",
            "第一层：需求挖掘层——场景·战法/技术·装备能力特征",
            ["③ 装备能力特征清单"],
            1400,
            3800,
            [],
        ),
        (
            "item_4_realization_path",
            "第二层：技术攻关层——能力实现途径与核心技术",
            ["④ 能力实现途径"],
            1300,
            3600,
            [],
        ),
        (
            "item_5_core_technologies",
            "第二层：技术攻关层——能力实现途径与核心技术",
            ["⑤ 核心技术清单与攻关优先级"],
            1700,
            4600,
            [],
        ),
        (
            "item_6_coupling_risks",
            "第二层：技术攻关层——能力实现途径与核心技术",
            ["⑥ 技术耦合与短板风险"],
            1400,
            4000,
            [],
        ),
        (
            "item_7_capability_image",
            "第三层：能力图像与效能贡献层",
            ["⑦ 装备能力图像"],
            1900,
            5200,
            [],
        ),
        (
            "item_8_effectiveness",
            "第三层：能力图像与效能贡献层",
            ["⑧ 效能贡献评估"],
            1900,
            5200,
            [],
        ),
        (
            "item_9_priority",
            "第三层：能力图像与效能贡献层",
            ["⑨ 发展优先级与近期抓手"],
            1600,
            4400,
            [],
        ),
    )
    project_sections = (
        (
            "chapter_1_demand_overview",
            "一、需求分析",
            ["（一）需求概述"],
            1100,
            4000,
            [],
        ),
        (
            "chapter_1_status",
            "一、需求分析",
            ["（二）国内外现状"],
            1100,
            4200,
            [],
        ),
        (
            "chapter_1_necessity",
            "一、需求分析",
            ["（三）建设必要性分析"],
            1100,
            4200,
            [],
        ),
        (
            "chapter_2_equipment_image",
            "二、项目画像",
            ["（一）装备图像概述"],
            1400,
            5200,
            [],
        ),
        (
            "chapter_2_operations",
            "二、项目画像",
            ["（二）作战运用模式"],
            1700,
            6000,
            [],
        ),
        (
            "chapter_2_contribution",
            "二、项目画像",
            ["（三）体系贡献率分析"],
            1100,
            4000,
            [],
        ),
        (
            "chapter_2_indicators",
            "二、项目画像",
            ["（四）主要战技指标"],
            1100,
            4000,
            [],
        ),
        (
            "chapter_3_architecture",
            "三、总体方案",
            ["（一）总体架构"],
            550,
            2400,
            [],
        ),
        (
            "chapter_3_subsystems",
            "三、总体方案",
            ["（二）子系统方案"],
            1100,
            4400,
            [],
        ),
        (
            "chapter_4_technology",
            "四、关键技术",
            ["（一）关键技术清单与攻关途径"],
            1400,
            5600,
            [],
        ),
        (
            "chapter_5_units",
            "五、研制基础",
            ["（一）参与单位"],
            650,
            2800,
            [],
        ),
        (
            "chapter_5_technical_foundation",
            "五、研制基础",
            ["（二）技术基础"],
            850,
            3600,
            [],
        ),
    )
    project_mode = _report_template_mode(payload) == "project_argument_v1"
    sections = project_sections if project_mode else legacy_sections
    skip_mechanical_retries = bool(
        payload.get("parallel_report_skip_mechanical_retries")
    )
    # A delivery-only resume may provide the last assembled draft and a list
    # of failed columns.  Reuse every healthy column byte-for-byte and fan out
    # model calls only for the failed columns.  This is deliberately local to
    # the parallel author so the ordinary first run remains unchanged.
    delivery_resume = payload.get("delivery_resume", {})
    existing_resume_report = ""
    resume_failed_layers: set[str] = set()
    if isinstance(delivery_resume, Mapping):
        existing_resume_report = str(
            delivery_resume.get("existing_report", "") or ""
        ).strip()
        raw_failed_layers = delivery_resume.get("failed_columns", [])
        if isinstance(raw_failed_layers, Sequence) and not isinstance(
            raw_failed_layers, (str, bytes)
        ):
            resume_failed_layers = {
                str(item).strip() for item in raw_failed_layers if str(item).strip()
            }

    def extract_resume_fragment(
        report: str,
        h2: str,
        h3s: Sequence[str],
        additional_h2s: Sequence[str] = (),
    ) -> str:
        """Extract one owned H3 (and its H4 children) from a prior draft."""

        if not report:
            return ""
        headings = [h2, *additional_h2s]
        fragments: list[str] = []
        for section_h3 in h3s:
            match = re.search(
                rf"^###\s*{re.escape(section_h3)}\s*$\n(?P<body>.*?)(?=^###\s|^##\s|\Z)",
                report,
                flags=re.MULTILINE | re.DOTALL,
            )
            if not match:
                return ""
            fragments.append(f"### {section_h3}\n{match.group('body').strip()}".strip())
        if not fragments:
            return ""
        # Include the parent H2 exactly once.  A project section can own an
        # additional H2 in older drafts, so preserve it when present.
        parent = next((f"## {title}" for title in headings if f"## {title}" in report), f"## {h2}")
        return parent + "\n\n" + "\n\n".join(fragments)
    # Keep the chapter contract focused while exposing the complete compact
    # equipment handoff to every writer.  The model decides relevance; the
    # runtime must not turn relevance into a fixed field whitelist.
    # H4 headings are part of the project report's navigation contract, but
    # they are not content fields.  Give each parallel chapter only the H4s it
    # owns so the model can preserve the agreed outline without turning the
    # body into a fixed verification form.
    project_h4_by_h3 = {
        "（一）需求概述": ("1. 背景分析", "2. 需求阐述", "3. 项目画像"),
        "（二）国内外现状": ("1. 国外情况", "2. 国内现状（中国）", "3. 对比小结"),
        "（三）建设必要性分析": (
            "1. 作战使用角度",
            "2. 装备能力提升角度",
            "3. 领域占位角度",
            "4. 综合效益",
        ),
        "（二）作战运用模式": ("1. 作战运用流程", "2. 链路闭环分析"),
    }
    # Keep the handoff compact, but do not use a chapter-specific field
    # whitelist.  The whitelist made the later chapters look like forms and
    # hid exactly the cross-field relationships needed for concrete weapon
    # architecture, technology maturity and Chinese industrial ownership.
    def compact_parallel_handoff(
        value: Mapping[str, Any], *, include_portrait: bool = True
    ) -> dict[str, Any]:
        """Compact list/table cues while preserving full S6 portrait substance."""

        preserve_cue_keys = {
            "capability_portrait",
            "capability_portrait_modules",
            "system_contribution_thesis",
            "indicator_portrait",
            "operational_concept",
            "concise_winning_summary",
            "winning_mechanism",
            "adversary_adaptation",
            "failure_boundary",
            "portrait_module_character_counts",
        }
        compact: dict[str, Any] = {}
        for key, item in value.items():
            if key != "capability_cues":
                compact[key] = item
                continue
            if not isinstance(item, Sequence) or isinstance(item, (str, bytes)):
                compact[key] = item
                continue
            cues: list[dict[str, Any]] = []
            for cue in _limit_report_capability_cues(item):
                if not isinstance(cue, Mapping):
                    continue
                row: dict[str, Any] = {}
                for cue_key, cue_value in cue.items():
                    key_text = str(cue_key)
                    if not include_portrait and key_text in {
                        "capability_portrait",
                        "capability_portrait_modules",
                    }:
                        continue
                    if key_text in preserve_cue_keys:
                        if isinstance(cue_value, Mapping):
                            row[key_text] = dict(cue_value)
                        elif isinstance(cue_value, Sequence) and not isinstance(
                            cue_value, (str, bytes)
                        ):
                            row[key_text] = list(cue_value)
                        elif cue_value not in (None, ""):
                            row[key_text] = str(cue_value)
                        continue
                    if isinstance(cue_value, Sequence) and not isinstance(
                        cue_value, (str, bytes)
                    ):
                        row[key_text] = [str(part)[:180] for part in cue_value[:8]]
                    elif cue_value not in (None, ""):
                        row[key_text] = str(cue_value)[:420]
                if row:
                    cues.append(row)
            compact[key] = cues
        return compact

    def assigned_output_review_issues(
        text: str,
        h2: str,
        h3s: Sequence[str],
        required_h4: Sequence[str] = (),
        layer_id: str = "",
        mechanical_checks: bool | None = None,
        target_chars: int = 0,
    ) -> list[str]:
        if mechanical_checks is None:
            mechanical_checks = not skip_mechanical_retries
        issues: list[str] = []
        raw_value = str(text or "").strip()
        if not raw_value:
            return ["栏目调用未返回正文"]
        # Accept harmless heading variants before applying the single-column
        # contract.  Prose remains byte-for-byte model-authored.
        value = _normalize_report_structure_deterministically(raw_value, payload)
        repair_floor = _parallel_column_repair_floor(target_chars or 900)
        if f"## {h2}" not in value:
            issues.append(f"缺少指定二级标题：{h2}")
        canonical_h2, canonical_h3, canonical_h4 = _report_canonical_headings(payload)
        template_mode = _report_template_mode(payload)
        raw_headings = re.findall(
            r"^(#{1,6})\s+(.+?)\s*$",
            raw_value,
            flags=re.MULTILINE,
        )
        raw_h2 = [
            canonical
            for marks, title in raw_headings
            if len(marks) == 2
            for canonical in [_canonical_report_h2(title, template_mode)]
            if canonical
        ]
        raw_h3 = [
            canonical
            for marks, title in raw_headings
            if len(marks) == 3
            for canonical in [_canonical_report_h3(title, template_mode)]
            if canonical
        ]
        raw_h4 = [
            canonical
            for marks, title in raw_headings
            if len(marks) == 4
            for canonical in [_canonical_report_h4(title)]
            if canonical
        ]
        if raw_h2 != [h2]:
            issues.append("二级标题不止或不是本栏目指定标题")
        if raw_h3 != list(h3s):
            issues.append("三级标题不止、缺失或顺序不符合本栏目合同")
        if raw_h4 != list(required_h4):
            issues.append("四级标题缺失、多余或顺序不符合本栏目合同")
        if any(len(marks) not in {2, 3, 4} for marks, _ in raw_headings):
            issues.append("栏目输出含一级、五级或六级标题")
        # The canonical lists above intentionally omit unknown headings.  A
        # fragment must not exploit that by adding an arbitrary neighboring or
        # explanatory heading which the normalizer would later discard.
        if len(raw_h2) != sum(1 for marks, _ in raw_headings if len(marks) == 2):
            issues.append("栏目输出含非模板二级标题")
        if len(raw_h3) != sum(1 for marks, _ in raw_headings if len(marks) == 3):
            issues.append("栏目输出含非模板三级标题")
        if len(raw_h4) != sum(1 for marks, _ in raw_headings if len(marks) == 4):
            issues.append("栏目输出含非模板四级标题")
        actual_h2 = [
            title
            for title in re.findall(r"^##\s+(.+?)\s*$", value, flags=re.MULTILINE)
            if title in canonical_h2
        ]
        actual_h3 = [
            title
            for title in re.findall(r"^###\s+(.+?)\s*$", value, flags=re.MULTILINE)
            if title in canonical_h3
        ]
        actual_h4 = [
            title
            for title in re.findall(r"^####\s+(.+?)\s*$", value, flags=re.MULTILINE)
            if title in canonical_h4
        ]
        if actual_h2 != [h2] or actual_h3 != list(h3s):
            issues.append("规范化后仍未形成唯一指定二级/三级标题")
        if actual_h4 != list(required_h4):
            issues.append("规范化后四级标题仍不完整或含越界标题")
        leaked_or_placeholder = (
            "按任务准备与装订、平台部署与进入、目标发现确认、火力分配",
            "围绕时间链、信息与精度链、火力链、毁伤评估链分析",
            "本节暂缺足够的装备专属事实",
            "核心技术待核验",
            "形成能力待核验",
            "作战动作与直接效果待核验",
            "指标画像尚未由",
            "须回到前置质量门",
            "回到前置质量门",
            "通过分布式感知、弹性协同和多样化任务效应",
        )
        if mechanical_checks:
            if any(marker in value for marker in leaked_or_placeholder):
                issues.append("正文含流程性占位句或统一作战能力套话")
        if not all(f"### {heading}" in value for heading in h3s):
            issues.append("缺少指定三级标题正文")
        if project_mode:
            for heading in h3s:
                match = re.search(
                    rf"^###\s*{re.escape(heading)}\s*$\n(?P<body>.*?)(?=^###\s|^##\s|\Z)",
                    value,
                    flags=re.MULTILINE | re.DOTALL,
                )
                if not match:
                    issues.append(f"无法定位三级栏目正文：{heading}")
                    continue
                prose = re.sub(r"(?m)^#{4,}\s+.*$", "", match.group("body"))
                prose = re.sub(r"(?m)^\|?\s*:?-{3,}.*$", "", prose)
                body_chars = _report_substantive_char_count(prose)
                if body_chars < 8:
                    issues.append(f"三级栏目正文为空或过短：{heading}")
                elif body_chars < repair_floor and not skip_mechanical_retries:
                    issues.append(
                        f"三级栏目正文偏短：{heading}仅{body_chars}字，"
                        f"目标约{int(target_chars or 900)}字，"
                        f"验收不得低于{repair_floor}字"
                    )
            # A column writer owns no neighboring H3 anymore, so it must also
            # finish every navigational H4 inside its assigned column.  This
            # closes a former gap where an incomplete multi-column chapter
            # could pass the fragment gate and be padded later.
            if required_h4 and not all(
                f"#### {heading}" in value for heading in required_h4
            ):
                issues.append("指定四级标题未全部完成")
            h4_floor = max(40, repair_floor // max(2, len(required_h4) or 1))
            for heading in required_h4:
                h4_match = re.search(
                    rf"^####\s*{re.escape(heading)}\s*$\n(?P<body>.*?)(?=^####\s|^###\s|^##\s|\Z)",
                    value,
                    flags=re.MULTILINE | re.DOTALL,
                )
                if not h4_match:
                    issues.append(f"四级栏目正文为空或过短：{heading}")
                    continue
                h4_chars = _report_substantive_char_count(h4_match.group("body"))
                if h4_chars < 8:
                    issues.append(f"四级栏目正文为空或过短：{heading}")
                elif h4_chars < h4_floor and not skip_mechanical_retries:
                    issues.append(
                        f"四级栏目正文偏短：{heading}仅{h4_chars}字，"
                        f"验收不得低于{h4_floor}字"
                    )
        else:
            # Legacy three-layer/nine-item columns also need a substance floor.
            for heading in h3s:
                match = re.search(
                    rf"^###\s*{re.escape(heading)}\s*$\n(?P<body>.*?)(?=^###\s|^##\s|\Z)",
                    value,
                    flags=re.MULTILINE | re.DOTALL,
                )
                if not match:
                    continue
                body_chars = _report_substantive_char_count(match.group("body"))
                if 0 < body_chars < repair_floor and not skip_mechanical_retries:
                    issues.append(
                        f"三级栏目正文偏短：{heading}仅{body_chars}字，"
                        f"目标约{int(target_chars or 900)}字，"
                        f"验收不得低于{repair_floor}字"
                    )
        fragment_issues = _report_fragment_quality_issues(value)
        if fragment_issues:
            issues.extend(fragment_issues)
        mechanical_chapters = {
            "chapter_1_demand_overview": ("chapter_1_demand",),
            "chapter_1_status": ("chapter_1_demand",),
            "chapter_1_necessity": ("chapter_1_demand",),
            "chapter_2_equipment_image": ("chapter_2_equipment_image",),
            "chapter_2_operations": ("chapter_2_operations",),
            "chapter_2_contribution": ("chapter_2_contribution",),
            "chapter_2_indicators": ("chapter_2_indicators",),
            "chapter_3_architecture": ("chapter_3_solution",),
            "chapter_3_subsystems": ("chapter_3_solution",),
            "chapter_4_technology": ("chapter_4_technology",),
            "chapter_5_units": ("chapter_5_foundation",),
            "chapter_5_technical_foundation": ("chapter_5_foundation",),
        }
        if mechanical_checks and layer_id in mechanical_chapters:
            # A syntactically complete chapter that rotates the same
            # contribution, metric or validation sentence between weapons is
            # not reviewable. Returning False here sends only that chapter
            # through the existing targeted retry path; the stabilizer is
            # deliberately prohibited from manufacturing replacement prose.
            for chapter in mechanical_chapters[layer_id]:
                issues.extend(_report_chapter_mechanical_issues(value, chapter))
        if project_mode and mechanical_checks:
            issues.extend(_report_equipment_attribution_issues(value, payload))
        if layer_id == "chapter_2_equipment_image":
            # The image table is part of the chapter writer's answer.  Empty
            # concept/effect cells or the historical five-column split must be
            # retried here, before assembly; the delivery stabilizer must not
            # disguise them by projecting a common sentence into every row.
            header = re.search(
                r"\|\s*武器装备\s*\|\s*核心技术\s*\|\s*形成能力\s*\|\s*作战概念与主要效果\s*\|",
                value,
            )
            if not header:
                issues.append("装备图像概述缺少规定的四列表头")
            image_table_issues = [
                issue
                for issue in _report_table_issues(value, project_mode=True)
                if issue.startswith("装备图像概述")
            ]
            if image_table_issues:
                issues.extend(image_table_issues)
            handoff = reporter_input.get("research_handoff", {})
            cues = handoff.get("capability_cues", []) if isinstance(handoff, Mapping) else []
            expected_names = [
                str(item.get("direction", "")).strip()
                for item in cues
                if isinstance(item, Mapping) and str(item.get("direction", "")).strip()
            ]
            image_section = re.search(
                r"^###\s*（一）装备图像概述\s*$\n(?P<body>.*?)(?=^###\s|^##\s|\Z)",
                value,
                flags=re.MULTILINE | re.DOTALL,
            )
            image_body = image_section.group("body") if image_section else ""
            table_directions = set(
                _report_capability_image_table_directions(image_body)
            )
            if any(name not in table_directions for name in expected_names):
                issues.append("装备图像四列表未逐件覆盖交接中的装备方向")
        return list(dict.fromkeys(str(issue).strip() for issue in issues if str(issue).strip()))

    def assigned_output_is_reviewable(
        text: str,
        h2: str,
        h3s: Sequence[str],
        required_h4: Sequence[str] = (),
        layer_id: str = "",
        mechanical_checks: bool | None = None,
        target_chars: int = 0,
    ) -> bool:
        return not assigned_output_review_issues(
            text,
            h2,
            h3s,
            required_h4,
            layer_id,
            mechanical_checks,
            target_chars=target_chars,
        )

    def section_required_h4(section: tuple) -> tuple[str, ...]:
        if not project_mode:
            return ()
        return tuple(
            heading
            for heading in section[2]
            for heading in project_h4_by_h3.get(heading, ())
        )

    section_semantic_guidance = {
        "item_1_scenario": (
            "只解决场景问题：交代对手、地域与环境、任务窗口、行动主体、约束和失败后果；"
            "不同装备若进入不同场景，不得用同一背景轮换名称。"
        ),
        "item_2_winning_mechanism": (
            "只解释旧范式为何失效、装备动作改变了哪项制胜关系，以及对手反适应和成立边界；"
            "不得复述场景或能力清单。"
        ),
        "item_3_capability_features": (
            "只从任务断点反推具体装备能力与有判别力的指标方向；不同装备不共用指标组，"
            "没有校准数据时保留变量和工况，不生成点值。"
        ),
        "item_4_realization_path": (
            "只判断沿用改进、集成创新或原理突破如何落到装备本体，并说明选择依据和工程边界。"
        ),
        "item_5_core_technologies": (
            "只选择决定成败的技术断点，逐项说明作用环节、物理或工程约束、成熟基础、瓶颈与优先级；"
            "不得按热门技术类别凑表。"
        ),
        "item_6_coupling_risks": (
            "只分析接口依赖、物理耦合、级联失效和单点短板如何改变任务结果，并给出装备专属压力工况。"
        ),
        "item_7_capability_image": (
            "只形成可比较的装备能力图像；每行必须对应具体装备、能力增量、谱系基线、边界和证据状态，"
            "不得增加抽象公共节点或统一占位列。"
        ),
        "item_8_effectiveness": (
            "只评估每件装备对实际任务结果的贡献；比较轴随装备机理变化，不强制补链、强链或开链句式，"
            "不得复制统一贡献句。"
        ),
        "item_9_priority": (
            "重点说明各装备在解决态势威胁、改变交战关系和形成制胜效果中的优先级与近期抓手；"
            "验证判据和建设取舍只作必要收束，不展开成工程管理清单。"
        ),
        "chapter_1_demand_overview": (
            "需求概述下三级分工必须清楚："
            "1. 背景分析交代威胁态势与任务链压力；"
            "2. 需求阐述严格从 Query 角度分析相关装备需求（需要什么、为何需要、缺什么），不提前写型号方案或工程验证；"
            "3. 项目画像聚焦该装备研发的作用、应对态势威胁、作战前景与制胜增量，不提前展开第二章作战流程或指标表。"
        ),
        "chapter_1_status": (
            "只比较与本项目任务、装备机理和工程基础直接相关的国外与中国公开事实；"
            "两侧不必对称，必须区分类别事实、具体案例、参数证据和推断边界。"
        ),
        "chapter_1_necessity": (
            "重点回答装备如何缓解现实威胁、改变作战使用和提升制胜能力；"
            "领域占位、综合效益与建设取舍只作简短收束，同一理由只出现一次。"
        ),
        "chapter_2_equipment_image": (
            "只完成四列表格。逐件把核心技术、形成能力、部署或进入方式、关键动作、作用对象和直接效果"
            "闭合成装备专属因果链，不得使用统一抽象作战概念。"
        ),
        "chapter_2_operations": (
            "重点写真实威胁态势下的进入条件、决定性作战动作、对手状态变化、我方制胜链条和直接战果；"
            "退出或中止条件只需点到为止，流程长短随装备机理变化，不套统一骨架。"
        ),
        "chapter_2_contribution": (
            "只从实际体系基线判断每件装备如何解决威胁、改写敌我交换关系、放大直接战果并形成制胜增量；"
            "衰减或失效条件简要交代，比较口径随装备变化，禁止复用统一贡献句。"
        ),
        "chapter_2_indicators": (
            "只从每件武器的制胜机理、作战动作和最可能失效环节反推少量判别性指标；"
            "先说明指标对应的作战效果，验证设计简要点明，不得共用指标组或判退句。"
        ),
        "chapter_3_architecture": (
            "只上提多件装备真正共享且会改变任务结果的状态、权限、资源和接口，说明分工、衔接和失败耦合；"
            "单件装备专属机理不得抽象成公共层。"
        ),
        "chapter_3_subsystems": (
            "只从各装备作用链反推产品形态、控制机理、必要输入输出、关键接口和工程验证；"
            "不同装备的构型、控制、接口和集成验证不能共用一套展开顺序。"
        ),
        "chapter_4_technology": (
            "只选择决定各装备能否成立的技术断点，按其物理约束、当前基础、瓶颈和验证证据形成判断；"
            "不得为每件装备机械补齐相同技术栏目。"
        ),
        "chapter_5_units": (
            "聚焦与本项目装备研发大致相关的承研/配套单位类型："
            "从产品责任、关键接口、试验责任和证据交付反推；"
            "公开依据不足时只写机构类型与缺失证据，不得虚构具体单位或复制通用承研分工。"
        ),
        "chapter_5_technical_foundation": (
            "聚焦已经比较成熟、可支撑新质装备研发的技术与工程基础："
            "按装备写清可继承成熟基础、新增工作、可研缺口及试验/供应链条件，"
            "重点体现具备研发新质装备的基础；没有证据时指出缺哪项，不用统一‘待核验’句填表。"
        ),
    }

    # A real run carries a compact S6/query handoff. Only then can a malformed
    # chapter be meaningfully repaired from the same evidence. Minimal fake or
    # legacy callers may intentionally return a short sentinel (for budget and
    # transport tests); do not spend extra model calls trying to infer prose
    # from an empty handoff.
    handoff_value = reporter_input.get("research_handoff")
    strict_section_repair = bool(
        isinstance(handoff_value, Mapping)
        and any(
            value not in (None, "", [], {})
            for value in handoff_value.values()
        )
    )

    def bounded_repair_reasons(reasons: Sequence[str]) -> list[str]:
        """Keep model-facing repair guidance specific, bounded and single-line."""

        bounded: list[str] = []
        for reason in reasons:
            value = " ".join(str(reason or "").split()).strip()
            if not value:
                continue
            bounded.append(value[:180])
            if len(bounded) >= 6:
                break
        return list(dict.fromkeys(bounded)) or ["栏目正文未通过完整性门禁"]

    def column_system_prompt(
        *,
        layer_id: str,
        h2: str,
        h3s: Sequence[str],
        target_chars: int,
        additional_h2s: Sequence[str] = (),
        required_h4: Sequence[str] = (),
        source_index: str = "omit",
        repair_note: str = "",
    ) -> str:
        """Build the same one-shot quality contract for first pass and repairs."""

        h2_h3_map = {h2: list(h3s)}
        if additional_h2s:
            h2_h3_map[h2] = list(h3s[:1])
            h2_h3_map[additional_h2s[0]] = list(h3s[1:])
        h2_contract = "、".join([h2, *additional_h2s])
        heading_contract = "；".join(
            f"{section_h2}下依次写{','.join(section_h3s)}"
            for section_h2, section_h3s in h2_h3_map.items()
        )
        if required_h4:
            heading_contract += (
                "；本分片四级标题仅按父级顺序使用："
                + "、".join(required_h4)
                + "；不新增其他四级标题"
            )
        source_instruction = (
            "本分片末尾附加精简的核心公开来源索引。"
            if source_index == "append_after_layer"
            else "本分片不输出公开来源索引。"
        )
        grounding_instruction = (
            "S6已提供通过硬门的装备画像和事实底稿。先理解本项目的真实任务矛盾以及每件装备改变结果的原因，"
            "再自主完成本栏目；栏目结构应服务于装备之间有意义的比较，不能把输入字段依次改写成段落。"
            "保持装备身份、证据边界和已知限制一致，不另造装备或补写无依据参数。体系贡献应说明装备相对实际"
            "基线产生了什么不可替代的变化以及判断何时失效；战技指标应由装备自身的制胜机理和失败原因生成，"
            "其数量、表达和验证设计由实际分析决定。各装备不得共用同一论证骨架或指标组合。"
            "若删除装备名称后某项判断仍可原样套给其他装备，说明分析尚未落到本体，应在当前调用中重写。"
            if project_mode
            else ""
        )
        grounding_instruction += section_semantic_guidance.get(layer_id, "")
        repair_floor = _parallel_column_repair_floor(target_chars)
        common_contract = (
            f"本分片编号为 {layer_id}。只输出以下标题：{h2_contract}；{heading_contract}。"
            "report_spine是报告级只读事实脊柱，包含Query边界、装备身份、任务断点、动作—机理—战果、"
            "基线、证据与失效边界以及章节交接关系；优先用它保持跨栏事实一致。不得修改、扩展或重新发明"
            "spine中的装备主体、事实和证据边界；本栏只从spine选择与本栏职责直接相关的判断。"
            "不得输出其他层、总标题、前言或过程说明。每个判断必须完整、可独立拼接，避免复述其他层。"
            "动笔前先为每个direction建立独立的威胁态势、作战矛盾、作用对象、关键动作、效应机理、"
            "直接战果、相对基线和制胜机理因果链；验证边界与建设取舍只用于最后收束，不得变成八项固定输出格式。"
            "正文优先解释装备怎样解决态势威胁、改变交战关系和形成制胜效果，结构、比较轴和信息顺序应随装备机理变化。"
            f"本分片目标篇幅约{target_chars}字；{repair_floor}字仅是异常偏短触发线，不是写作目标。"
            "除非事实确实不足，正文不得明显短于目标；因果未闭合时可自然略多。"
            "应优先补充具体装备差异、作战动作、因果链、验证判据、反适应和建设取舍，"
            "不得用空泛套话凑字，也不得因过早收束而留下过短、信息密度不足的段落。"
            "每段至少承担战场矛盾、具体装备事实、作战动作、制胜因果、直接战果、对手反适应中的一项；"
            "验证边界和建设取舍仅在确有必要时简短补充。"
            "相邻栏目不得使用相同的开头句、段落骨架或结尾句；输入字段只是事实线索，必须重新组织，不得连续照录长句。"
            "禁止连续照录其中的长句。"
            "不得通过删除事实、来源、反证或验证要求来制造篇幅合规。"
            "表格每行必须对应不同对象，每列必须承担不同判断功能；证据不足时减少行数并明确说明，不得用模板内容填充。"
            "逐装备落笔前按direction核对其场景、动作、目标、效果、技术和边界的归属；除明确论证装备间接口外，"
            "不得把一件装备的事实、验证口径或战果写入另一件装备。"
            "每个段落和表格单元格必须自然收束为完整判断；写完后从总编辑视角检查是否存在半句、悬空连接词、"
            "被截断的词语或未闭合的 Markdown 标记，并在当前调用内直接改写。不要用‘当前结论’等表头词代替正文判断。"
            "完成后检查标题、独立结论、具体对象、因果机制、证据边界和句式去重，发现不满足时在当前调用内重写。"
        )
        if repair_note:
            common_contract += " " + repair_note
        return (
            _parallel_column_navigation_preamble(project_mode=project_mode)
            + "\n"
            + _read_parallel_fragment_prompt(
                "report_column.md",
                parent_heading=h2,
                column_heading="、".join(h3s),
                column_focus=section_semantic_guidance.get(layer_id, ""),
                common_contract=common_contract,
                grounding_instruction=grounding_instruction,
                source_instruction=source_instruction,
                target_chars=str(target_chars),
                repair_floor_chars=str(repair_floor),
            )
        )

    def issues_are_thin_only(reasons: Sequence[str]) -> bool:
        cleaned = [str(item) for item in reasons if str(item).strip()]
        return bool(cleaned) and all(
            ("偏短" in item or "过短" in item) and "为空" not in item
            for item in cleaned
        )

    async def generate_layers() -> list[str]:
        calls = []
        call_indexes: list[int] = []
        reused_results: list[str] = [""] * len(sections)
        for index, (layer_id, h2, h3s, target_chars, token_cap, additional_h2s) in enumerate(sections):
            if existing_resume_report and layer_id not in resume_failed_layers:
                reused = extract_resume_fragment(
                    existing_resume_report, h2, h3s, additional_h2s
                )
                if reused:
                    reused_results[index] = reused
                    continue
            layer_input = dict(reporter_input)
            if project_mode:
                handoff = layer_input.get("research_handoff", {})
                if isinstance(handoff, Mapping):
                    # Keep each chapter's context focused while preserving the
                    # complete equipment-specific semantic spine in chapter 2,
                    # where contribution and indicator judgments are authored.
                    # Keep the complete compact handoff in every chapter. A
                    # chapter may choose what matters, but the runtime must not
                    # remove the anchors, comparison facts or boundary evidence
                    # before the model can connect them to a weapon's argument.
                    scoped = dict(handoff)
                    # Every chapter receives the complete compact semantic
                    # spine for each weapon.  Earlier per-chapter field filters
                    # removed the cross-field relations needed to distinguish
                    # architecture, technology and industrial basis, which led
                    # writers to fall back to a shared prose skeleton.
                    layer_input["research_handoff"] = compact_parallel_handoff(
                        scoped,
                        include_portrait=layer_id
                        in {
                            "item_7_capability_image",
                            "chapter_2_equipment_image",
                            "chapter_2_contribution",
                            "chapter_2_indicators",
                        },
                    )
            h2_h3_map = {h2: list(h3s)}
            if additional_h2s:
                h2_h3_map[h2] = list(h3s[:1])
                h2_h3_map[additional_h2s[0]] = list(h3s[1:])
            required_h4 = (
                [
                    heading
                    for h3 in h3s
                    for heading in project_h4_by_h3.get(h3, ())
                ]
                if project_mode
                else []
            )
            layer_input["parallel_section_contract"] = {
                "layer_id": layer_id,
                "required_h2": h2,
                "additional_required_h2": list(additional_h2s),
                "required_h3": h3s,
                "required_h4": required_h4,
                "h2_h3_map": h2_h3_map,
                "output_scope": "only_assigned_layer",
                "no_h1": True,
                "standalone_complete_prose": True,
                "cross_layer_repetition_forbidden": True,
                "spine_read_only": True,
                "spine_schema": (
                    "query_boundary,directions,mission_chain_breaks,decisive_anchors,"
                    "counterevidence_and_limits,evidence_policy,chapter_handoffs"
                ),
                "target_chars": target_chars,
                "repair_floor_chars": _parallel_column_repair_floor(target_chars),
                "target_is_minimum": False,
                "quality_unit": "decision_relevant_military_information",
                "hard_max_chars": 0,
                "output_token_budget_is_soft": True,
                "source_index": (
                    "append_after_layer"
                    if layer_id
                    in {"item_9_priority", "chapter_5_technical_foundation"}
                    else "omit"
                ),
            }
            system = column_system_prompt(
                layer_id=layer_id,
                h2=h2,
                h3s=h3s,
                target_chars=target_chars,
                additional_h2s=additional_h2s,
                required_h4=required_h4,
                source_index=str(
                    layer_input["parallel_section_contract"]["source_index"]
                ),
            )
            calls.append(
                _await_reporter_column(
                    host._run_reporter_text(
                        system,
                        layer_input,
                        min(output_token_budget, token_cap),
                        phase=f"report_generation_{layer_id}",
                        run_id=str(payload.get("run_id", "")),
                        isolation_id=f"{payload.get('run_id', 'run')}:{layer_id}",
                    ),
                    wave="initial",
                    target_chars=target_chars,
                )
            )
            call_indexes.append(index)
        first_results = await asyncio.gather(*calls, return_exceptions=True)
        results: list[str] = list(reused_results)
        failure_reasons: list[list[str]] = [[] for _ in sections]
        # A repair wave is useful only when it changes the diagnosed root
        # cause. Track normalized fingerprints per column so a provider that
        # returns the same structurally bad answer cannot consume a second
        # retry (and then a third fallback) for the same defect.
        # Keep the last diagnosed root set for each column.  A new repair wave
        # is allowed only when the root set strictly shrinks; changing wording
        # while leaving the same short/repetition/heading defect is not progress.
        last_repair_roots: list[tuple[str, ...]] = [() for _ in sections]
        transport_retry_counts: list[int] = [0 for _ in sections]
        stalled_repair_columns: set[int] = set()
        for index, item in zip(call_indexes, first_results):
            results[index] = item if isinstance(item, str) else ""
            if isinstance(item, BaseException):
                failure_reasons[index] = [f"模型调用异常：{type(item).__name__}"]
            elif not str(item or "").strip():
                failure_reasons[index] = ["模型未返回栏目正文"]

        # A transient CLI capacity refusal or an incomplete stream should only
        # replay that chapter.  Replaying the whole report was the main cause
        # of deterministic limited/fallback reports after otherwise successful
        # parallel work.  Two small repair waves keep the calls parallel and
        # preserve the no-hard-timeout policy.
        fallback_profile = _reporter_chapter_fallback_profile(host, payload)
        handoff_material = reporter_input.get("research_handoff")
        fallback_recovery_enabled = bool(
            fallback_profile
            and _reporter_handoff_is_substantive(handoff_material)
        )
        for retry_round in range(2):
            retry_calls = []
            retry_indexes: list[int] = []
            failed_indexes: list[int] = []
            if not strict_section_repair:
                # Lightweight/fake callers do not carry the S6/query handoff
                # needed to repair a chapter meaningfully. Preserve their
                # sentinel behavior and avoid spending three waves on empty
                # prose that cannot be grounded in equipment facts.
                break
            for index, (section, result) in enumerate(zip(sections, results)):
                layer_id, h2, h3s, target_chars, token_cap, additional_h2s = section
                required_h4 = section_required_h4(section)
                # Empty/exceptional calls are always retried. Structural
                # repair is enabled only when the Reporter has real handoff
                # material; otherwise preserving the sentinel is preferable
                # to an unbounded retry storm in lightweight callers.
                if str(result or "").strip() and (
                    not strict_section_repair
                    or assigned_output_is_reviewable(
                        result,
                        h2,
                        h3s,
                        required_h4,
                        layer_id,
                        target_chars=target_chars,
                    )
                ):
                    continue
                failure_reasons[index] = bounded_repair_reasons(
                    assigned_output_review_issues(
                        result,
                        h2,
                        h3s,
                        required_h4,
                        layer_id,
                        target_chars=target_chars,
                    )
                    or failure_reasons[index]
                )
                current_roots = _repair_reason_fingerprint(failure_reasons[index])
                if not str(result or "").strip():
                    # Empty/transport failures get one primary retry, then
                    # may use the independent fallback provider.  Repeating
                    # an empty call in a second primary wave only adds tail
                    # latency and cannot improve the evidence.
                    if transport_retry_counts[index] >= 1:
                        continue
                    transport_retry_counts[index] += 1
                elif current_roots:
                    previous_roots = last_repair_roots[index]
                    if previous_roots and not set(current_roots) < set(previous_roots):
                        stalled_repair_columns.add(index)
                        continue
                    last_repair_roots[index] = current_roots
                failed_indexes.append(index)
            if not failed_indexes:
                break
            remaining_budget = _reporter_calls_remaining(host)
            retry_capacity = len(failed_indexes)
            if remaining_budget is not None:
                if fallback_recovery_enabled:
                    # Reserve one final DeepSeek slot per still-failed
                    # chapter before spending another primary retry. This
                    # keeps the fallback wave viable even when every chapter
                    # fails together under the finite Reporter budget.
                    reserve_for_fallback = min(
                        len(failed_indexes),
                        max(0, remaining_budget),
                    )
                    retry_capacity = max(
                        0,
                        min(
                            len(failed_indexes),
                            remaining_budget - reserve_for_fallback,
                        ),
                    )
                else:
                    retry_capacity = min(len(failed_indexes), max(0, remaining_budget))
            for index in failed_indexes[:retry_capacity]:
                section = sections[index]
                layer_id, h2, h3s, target_chars, token_cap, additional_h2s = section
                retry_indexes.append(index)
                # Rebuild the input from the same bounded source so retries do
                # not depend on a partially consumed coroutine or a clipped
                # first response.
                retry_input = dict(reporter_input)
                if project_mode:
                    handoff = retry_input.get("research_handoff", {})
                    if isinstance(handoff, Mapping):
                        retry_input["research_handoff"] = compact_parallel_handoff(
                            handoff,
                            include_portrait=layer_id
                            in {
                                "item_7_capability_image",
                                "chapter_2_equipment_image",
                                "chapter_2_contribution",
                                "chapter_2_indicators",
                            },
                        )
                retry_input["parallel_section_contract"] = {
                    "layer_id": layer_id,
                    "required_h2": h2,
                    "additional_required_h2": list(additional_h2s),
                    "required_h3": h3s,
                    "required_h4": list(section_required_h4(section)),
                    "h2_h3_map": ({h2: list(h3s)}),
                    "output_scope": "only_assigned_layer",
                    "no_h1": True,
                    "standalone_complete_prose": True,
                    "cross_layer_repetition_forbidden": True,
                    "spine_read_only": True,
                    "spine_schema": (
                        "query_boundary,directions,mission_chain_breaks,decisive_anchors,"
                        "counterevidence_and_limits,evidence_policy,chapter_handoffs"
                    ),
                    "target_chars": target_chars,
                    "repair_floor_chars": _parallel_column_repair_floor(target_chars),
                    "target_is_minimum": False,
                    "quality_unit": "decision_relevant_military_information",
                    "hard_max_chars": 0,
                    "output_token_budget_is_soft": True,
                    "retry_round": retry_round + 1,
                    "repair_reasons": list(failure_reasons[index]),
                }
                reason_text = "；".join(failure_reasons[index])
                thin_expansion = issues_are_thin_only(failure_reasons[index]) and bool(
                    str(results[index] or "").strip()
                )
                if thin_expansion:
                    retry_input["current_column_draft"] = results[index]
                    repair_note = (
                        f"这是第{retry_round + 1}次偏短补写。"
                        f"上一稿结构可用但正文偏短：{reason_text}。"
                        "保留已成立的装备专属判断，只补缺失的态势、动作、因果、战果或边界；"
                        "不得整栏换成模板句，不输出解释或降级模板。"
                    )
                else:
                    repair_note = (
                        f"这是第{retry_round + 1}次定向重试。"
                        f"上一响应未通过栏目门禁：{reason_text}。"
                        "保留Query分析和装备事实，只修复上述问题并直接完成本栏，不输出解释、草稿或降级模板。"
                    )
                retry_system = column_system_prompt(
                    layer_id=layer_id,
                    h2=h2,
                    h3s=h3s,
                    target_chars=target_chars,
                    additional_h2s=additional_h2s,
                    required_h4=section_required_h4(section),
                    repair_note=repair_note,
                )
                retry_calls.append(
                    _await_reporter_column(
                        _start_reporter_request(
                            host,
                            retry_system,
                            retry_input,
                            min(output_token_budget, token_cap),
                            phase=f"report_generation_{layer_id}_retry{retry_round + 1}",
                            run_id=str(payload.get("run_id", "")),
                            isolation_id=f"{payload.get('run_id', 'run')}:{layer_id}:retry{retry_round + 1}",
                        ),
                        wave="retry",
                        target_chars=target_chars,
                    )
                )
            if not retry_calls:
                break
            retry_results = await asyncio.gather(*retry_calls, return_exceptions=True)
            for index, item in zip(retry_indexes, retry_results):
                if isinstance(item, str) and item.strip():
                    results[index] = item
                    section = sections[index]
                    failure_reasons[index] = assigned_output_review_issues(
                        item,
                        section[1],
                        section[2],
                        section_required_h4(section),
                        section[0],
                        target_chars=section[3],
                    )
                elif isinstance(item, BaseException):
                    failure_reasons[index] = [
                        f"定向重试调用异常：{type(item).__name__}"
                    ]
                else:
                    failure_reasons[index] = ["定向重试未返回栏目正文"]

        # If the primary Reporter and its two column-local repair waves still
        # leave holes, spend one final wave on only those indexes using the
        # configured DeepSeek/OpenLux profile.  Completed columns are never
        # replayed or replaced.  The wave is gated by substantive handoff
        # material so sparse/legacy callers keep their existing behavior.
        fallback_indexes = [
            index
            for index, (section, result) in enumerate(zip(sections, results))
            if (
                not str(result or "").strip()
                or (
                    strict_section_repair
                    and not assigned_output_is_reviewable(
                        result,
                        section[1],
                        section[2],
                        section_required_h4(section),
                        section[0],
                        target_chars=section[3],
                    )
                )
            )
        ]
        # A non-empty quality defect whose root did not change has already had
        # its useful repair opportunity.  Empty responses are different: one
        # fallback provider attempt is still worthwhile after the single
        # primary transport retry.
        fallback_indexes = [
            index
            for index in fallback_indexes
            if index not in stalled_repair_columns
        ]
        remaining_budget = _reporter_calls_remaining(host)
        if remaining_budget is not None:
            # A custom deployment may retain a smaller legacy lane budget.
            # Never enqueue more fallback chapters than the finite budget can
            # reserve; the remaining chapters stay in the honest limited
            # delivery path instead of causing a burst of guaranteed budget
            # errors.
            fallback_indexes = fallback_indexes[:remaining_budget]
        if fallback_recovery_enabled and fallback_indexes:
            fallback_calls = []
            for index in fallback_indexes:
                current_section = sections[index]
                layer_id, h2, h3s, target_chars, token_cap, additional_h2s = current_section
                fallback_input = dict(reporter_input)
                if project_mode:
                    handoff = fallback_input.get("research_handoff", {})
                    if isinstance(handoff, Mapping):
                        fallback_input["research_handoff"] = compact_parallel_handoff(
                            handoff,
                            include_portrait=layer_id
                            in {
                                "item_7_capability_image",
                                "chapter_2_equipment_image",
                                "chapter_2_contribution",
                                "chapter_2_indicators",
                            },
                        )
                fallback_input["parallel_section_contract"] = {
                    "layer_id": layer_id,
                    "required_h2": h2,
                    "additional_required_h2": list(additional_h2s),
                    "required_h3": h3s,
                    "required_h4": list(section_required_h4(current_section)),
                    "h2_h3_map": {h2: list(h3s)},
                    "output_scope": "only_assigned_layer",
                    "no_h1": True,
                    "standalone_complete_prose": True,
                    "cross_layer_repetition_forbidden": True,
                    "spine_read_only": True,
                    "spine_schema": (
                        "query_boundary,directions,mission_chain_breaks,decisive_anchors,"
                        "counterevidence_and_limits,evidence_policy,chapter_handoffs"
                    ),
                    "target_chars": target_chars,
                    "repair_floor_chars": _parallel_column_repair_floor(target_chars),
                    "target_is_minimum": False,
                    "quality_unit": "decision_relevant_military_information",
                    "hard_max_chars": 0,
                    "output_token_budget_is_soft": True,
                    "fallback_wave": "deepseek",
                    "repair_reasons": list(
                        bounded_repair_reasons(
                            assigned_output_review_issues(
                                results[index],
                                h2,
                                h3s,
                                section_required_h4(current_section),
                                layer_id,
                                target_chars=target_chars,
                            )
                            or failure_reasons[index]
                        )
                    ),
                }
                fallback_reason_text = "；".join(
                    fallback_input["parallel_section_contract"]["repair_reasons"]
                )
                thin_expansion = issues_are_thin_only(
                    fallback_input["parallel_section_contract"]["repair_reasons"]
                ) and bool(str(results[index] or "").strip())
                if thin_expansion:
                    fallback_input["current_column_draft"] = results[index]
                    repair_note = (
                        "这是DeepSeek备用偏短补写波次。"
                        f"主模型稿结构可用但正文偏短：{fallback_reason_text}。"
                        "保留已成立判断，只补缺失的装备专属因果，不得输出解释或降级模板。"
                    )
                else:
                    repair_note = (
                        "这是DeepSeek备用波次，仅修复该栏目。"
                        f"主模型未通过栏目门禁：{fallback_reason_text}。"
                        "保留Query与交接中的具体装备事实，只修复上述问题并补齐完整因果判断；"
                        "不得输出解释、降级模板或其他章节。"
                    )
                fallback_system = column_system_prompt(
                    layer_id=layer_id,
                    h2=h2,
                    h3s=h3s,
                    target_chars=target_chars,
                    additional_h2s=additional_h2s,
                    required_h4=section_required_h4(current_section),
                    repair_note=repair_note,
                )
                fallback_calls.append(
                    _await_reporter_column(
                        _start_reporter_request(
                            host,
                            fallback_system,
                            fallback_input,
                            min(output_token_budget, token_cap),
                            phase=f"report_generation_{layer_id}_deepseek_fallback",
                            run_id=str(payload.get("run_id", "")),
                            isolation_id=(
                                f"{payload.get('run_id', 'run')}:{layer_id}:deepseek-fallback"
                            ),
                            force_fallback=True,
                            fallback_reason="report_chapter_retry_exhausted",
                            provider_profile=fallback_profile,
                        ),
                        wave="fallback",
                        target_chars=target_chars,
                    )
                )
            fallback_results = await asyncio.gather(*fallback_calls, return_exceptions=True)
            for index, item in zip(fallback_indexes, fallback_results):
                section = sections[index]
                if isinstance(item, str) and item.strip() and assigned_output_is_reviewable(
                        item,
                        section[1],
                        section[2],
                        section_required_h4(section),
                        section[0],
                        target_chars=section[3],
                    ):
                        results[index] = item
        if strict_section_repair:
            # Never assemble a known structurally bad response after all local
            # model waves are exhausted. Thin-only drafts that still miss the
            # substance floor are kept so limited delivery retains usable prose
            # instead of collapsing into empty template holes.
            for index, (section, result) in enumerate(zip(sections, results)):
                if not str(result or "").strip():
                    continue
                reasons = assigned_output_review_issues(
                    result,
                    section[1],
                    section[2],
                    section_required_h4(section),
                    section[0],
                    target_chars=section[3],
                )
                if reasons and not issues_are_thin_only(reasons):
                    results[index] = ""
        host._last_report_failed_columns = [
            sections[index][0]
            for index, (section, result) in enumerate(zip(sections, results))
            if not str(result or "").strip()
            or not assigned_output_is_reviewable(
                result,
                section[1],
                section[2],
                section_required_h4(section),
                section[0],
                target_chars=section[3],
            )
        ]
        host._last_report_repair_stalled_columns = [
            sections[index][0]
            for index in sorted(stalled_repair_columns)
            if index < len(sections)
        ]
        return results

    # Research stages keep their existing bounded concurrency, while the
    # column-authoring wave may use the larger Reporter-only ceiling.  Restore
    # the shared gate even when one coroutine raises so later runs do not
    # inherit delivery-specific capacity.
    call_gate = getattr(host, "_call_gate", None)
    previous_concurrency: int | None = None
    configure_concurrency = getattr(call_gate, "configure_concurrency", None)
    if callable(configure_concurrency):
        snapshot = call_gate.snapshot()
        previous_concurrency = int(snapshot.get("limit", snapshot.get("maximum", 1)))
        budgets = getattr(host, "_runtime_budgets", {})
        configured_reporter_concurrency = (
            budgets.get("reporter_codex_concurrency", 12)
            if isinstance(budgets, Mapping)
            else 12
        )
        try:
            requested_concurrency = max(1, int(configured_reporter_concurrency))
        except (TypeError, ValueError):
            requested_concurrency = 12
        configure_concurrency(min(len(sections), requested_concurrency))
    try:
        layer_texts = asyncio.run(generate_layers())
    finally:
        if callable(configure_concurrency) and previous_concurrency is not None:
            configure_concurrency(previous_concurrency)
    if existing_resume_report:
        # Replace only explicitly failed H3 blocks in the prior draft.  This
        # avoids re-serializing healthy chapters (and preserves their evidence
        # citations, tables and wording) while still allowing the final
        # normalizer to reconcile the global heading contract.
        merged = existing_resume_report
        for index, result in enumerate(layer_texts):
            if not str(result or "").strip():
                continue
            section = sections[index]
            layer_id, h2, h3s, _target_chars, _token_cap, _additional_h2s = section
            if layer_id not in resume_failed_layers:
                continue
            for heading in h3s:
                replacement = re.search(
                    rf"^###\s*{re.escape(heading)}\s*$\n(?P<body>.*?)(?=^###\s|^##\s|\Z)",
                    _normalize_report_summary(result),
                    flags=re.MULTILINE | re.DOTALL,
                )
                if not replacement:
                    continue
                new_block = f"### {heading}\n{replacement.group('body').strip()}"
                merged = re.sub(
                    rf"^###\s*{re.escape(heading)}\s*$\n.*?(?=^###\s|^##\s|\Z)",
                    new_block + "\n\n",
                    merged,
                    count=1,
                    flags=re.MULTILINE | re.DOTALL,
                )
    else:
        assembled: list[str] = []
        for section, item in zip(sections, layer_texts):
            text = str(item or "").strip()
            if text:
                assembled.append(
                    _sanitize_reporter_output(_normalize_report_summary(item))
                )
                continue
            _layer_id, h2, h3s, _target_chars, _token_cap, _additional_h2s = section
            skeleton = [f"## {h2}"]
            for heading in h3s:
                skeleton.append(f"### {heading}")
                for h4 in project_h4_by_h3.get(heading, ()):
                    skeleton.append(f"#### {h4}")
            assembled.append("\n".join(skeleton))
        merged = "\n\n".join(assembled)
    model_normalized = _normalize_report_structure_deterministically(
        _normalize_branch_report_labels(merged, payload),
        payload,
    )
    normalized = _stabilize_report_delivery_contract(
        model_normalized,
        payload,
    )
    normalized = _enforce_report_hard_max(normalized, payload)
    host._latest_report_draft = normalized
    quality_issues = [
        item
        for item in _report_draft_quality_issues(normalized, payload)
        if not _is_report_seed_copy_issue(item)
    ]
    for layer_id in getattr(host, "_last_report_repair_stalled_columns", []):
        quality_issues.append(
            f"栏目{layer_id}同一质量根因重试后未改善，已停止重复修复并保留审计记录"
        )
    quality_issues.extend(_report_seed_copy_issues(model_normalized, payload))
    failed_columns = [
        sections[index][0]
        for index, (section, result) in enumerate(zip(sections, layer_texts))
        if not str(result or "").strip()
        or (
            strict_section_repair
            and not assigned_output_is_reviewable(
                result,
                section[1],
                section[2],
                section_required_h4(section),
                section[0],
                target_chars=section[3],
            )
        )
    ]
    if skip_mechanical_retries:
        host._last_report_quality_issues = list(quality_issues)
        host._last_report_failed_columns = list(failed_columns)
        return normalized
    blocking = _report_delivery_blocking_issues(quality_issues)
    if blocking or failed_columns or not _minimum_viable_model_report(normalized, payload):
        host._last_report_failed_columns = list(failed_columns)
        host._last_report_quality_issues = list(quality_issues)
        raise ValueError(
            "parallel Reporter assembly is not reviewable: "
            + "；".join((blocking or quality_issues or ["栏目调用未返回正文"])[:8])
        )
    host._last_report_quality_issues = list(quality_issues)
    host._last_report_failed_columns = []
    return normalized


def limited_report_delivery(
    host,
    payload: Mapping[str, Any],
    *,
    failure: BaseException,
) -> str:
    """Return the best reviewable report instead of failing the whole run."""

    failure_note = f"{type(failure).__name__}: {failure}"
    issues = list(host._last_report_quality_issues)
    # Preserve the historical audit marker for downstream dashboards, while
    # making clear that this is a failure/quality convergence path rather than
    # a wall-clock cutoff in deferred Reporter delivery.
    issues.append(f"Reporter限时收敛（非墙钟）：{failure_note}"[:260])
    host._last_report_quality_issues = list(dict.fromkeys(issues))[:16]
    candidate = _stabilize_report_delivery_contract(
        _normalize_report_structure_deterministically(
            _normalize_branch_report_labels(
                _sanitize_reporter_output(
                    _normalize_report_summary(host._latest_report_draft)
                ),
                payload,
            ),
            payload,
        ),
        payload,
    )
    candidate = _enforce_report_hard_max(candidate, payload)
    candidate_issues = _report_draft_quality_issues(candidate, payload)
    candidate_blocking = _report_delivery_blocking_issues(candidate_issues)
    if (
        _minimum_viable_model_report(candidate, payload)
        and _report_has_complete_canonical_structure(candidate, payload)
        and not candidate_blocking
    ):
        return candidate
    # The deterministic limited builder is still a publication path.  It
    # must consume the exact same Reporter-ready indicator and coupling
    # fields as the normal model draft; otherwise a transport/quality
    # fallback can reintroduce generic placeholders and dangling clipped
    # sentences after the normal stabilizer has already run.
    fallback = _build_limited_report(payload, draft=candidate)
    hybrid = _merge_partial_report_with_limited_completion(
        candidate,
        fallback,
        payload,
    )
    completed = hybrid or fallback
    completed = _enforce_report_hard_max(
        _stabilize_report_delivery_contract(
            completed,
            payload,
        ),
        payload,
    )
    completed_issues = _report_draft_quality_issues(completed, payload)
    completed_blocking = _report_delivery_blocking_issues(completed_issues)
    if (
        not _minimum_viable_model_report(completed, payload)
        or not _report_has_complete_canonical_structure(completed, payload)
        or completed_blocking
    ):
        # Limited delivery is an evidence-preserving recovery artifact.
        # Record defects for the resumable publication gate, but do not
        # turn mechanical structure drift into a provider exception.
        host._last_report_quality_issues = list(
            dict.fromkeys([*host._last_report_quality_issues, *completed_issues])
        )[:16]
    return completed


def draft_report_attempt(
    host,
    payload: Mapping[str, Any],
    *,
    reporter_agent: AgentDef | None,
    reporter_input: dict[str, Any],
    output_token_budget: int,
    timeout_seconds: float,
    phase: str,
    allow_repair: bool = True,
    allow_limited: bool = False,
    force_fallback: bool = False,
    provider_profile: str = "",
) -> str:
    async def _generate() -> str:
        request = _start_reporter_request(
            host,
            _report_writer_system_prompt(payload),
            reporter_input,
            output_token_budget,
            phase=phase,
            run_id=str(payload.get("run_id", "")),
            force_fallback=force_fallback,
            fallback_reason="report_retry_exhausted" if force_fallback else "",
            provider_profile=provider_profile,
        )
        # A non-positive timeout explicitly means deferred/unbounded report
        # delivery. Tests and legacy callers may still pass a positive value.
        return await asyncio.wait_for(request, timeout=timeout_seconds) if timeout_seconds > 0 else await request

    text = asyncio.run(_generate())
    model_normalized = _normalize_report_structure_deterministically(
        _normalize_branch_report_labels(
            _sanitize_reporter_output(_normalize_report_summary(text)),
            payload,
        ),
        payload,
    )
    normalized = _stabilize_report_delivery_contract(
        model_normalized,
        payload,
    )
    normalized = _enforce_report_hard_max(normalized, payload)
    host._latest_report_draft = normalized
    quality_issues = [
        item
        for item in _report_draft_quality_issues(normalized, payload)
        if not _is_report_seed_copy_issue(item)
    ]
    quality_issues.extend(_report_seed_copy_issues(model_normalized, payload))
    if not quality_issues:
        return normalized
    if (
        _report_issues_are_deterministic_format_only(quality_issues)
        and _minimum_viable_model_report(normalized, payload)
    ):
        # Heading labels, depth and duplicate source-index headings are
        # deterministic presentation defects.  Never pay for another
        # full Reporter pass to repair them; preserve the report and make
        # the residual visible to the quality artifact.
        host._last_report_quality_issues = list(quality_issues)
        return normalized
    blocking_issues = _report_delivery_blocking_issues(quality_issues)
    if not blocking_issues and _minimum_viable_model_report(normalized, payload):
        # Preserve the independent model report when only cosmetic heading
        # conventions remain. The downstream quality artifact may record
        # them, but they must not fail an otherwise reviewable delivery.
        host._last_report_quality_issues = list(quality_issues)
        return normalized
    if allow_limited and _minimum_viable_model_report(normalized, payload):
        host._last_report_quality_issues = list(quality_issues)
        return normalized
    if not allow_repair:
        host._last_report_quality_issues = list(quality_issues)
        raise ValueError(
            "fast finalize report is not reviewable: "
            + "；".join(quality_issues[:8])
        )
    repair_payload = _reporter_repair_payload(
        payload,
        draft=normalized,
        quality_issues=quality_issues,
        reporter_agent=reporter_agent,
        generation_payload=reporter_input,
    )
    repair_timeout_seconds = (
        min(
            timeout_seconds,
            max(
                30.0,
                min(
                    90.0,
                    float(
                        os.environ.get(
                            "EQUIPMENT_DR_REPORT_REPAIR_TIMEOUT_SECONDS",
                            "90",
                        )
                    ),
                ),
            ),
        )
        if timeout_seconds > 0
        else 0.0
    )
    async def _repair() -> str:
        request = host._run_reporter_text(
            _report_repair_system_prompt(payload),
            repair_payload,
            min(output_token_budget, 2000),
            phase=f"{phase}_repair",
            run_id=str(payload.get("run_id", "")),
        )
        return await asyncio.wait_for(request, timeout=repair_timeout_seconds) if repair_timeout_seconds > 0 else await request

    repaired = asyncio.run(_repair())
    repaired_normalized = _stabilize_report_delivery_contract(
        _normalize_report_structure_deterministically(
            _normalize_branch_report_labels(
                _sanitize_reporter_output(_normalize_report_summary(repaired)),
                payload,
            ),
            payload,
        ),
        payload,
    )
    repaired_normalized = _enforce_report_hard_max(
        repaired_normalized,
        payload,
    )
    host._latest_report_draft = repaired_normalized
    remaining_issues = _report_draft_quality_issues(
        repaired_normalized,
        payload,
    )
    if remaining_issues:
        host._last_report_quality_issues = list(remaining_issues)
        if (
            is_quality_execution_profile_id(
                payload.get("execution_profile_id", "")
            )
            and _branch_delivery_is_complete(payload)
            and _minimum_viable_model_report(repaired_normalized, payload)
            and not _report_delivery_blocking_issues(remaining_issues)
        ):
            # optimized_v2 treats Reporter checks as delivery diagnostics,
            # not a reason to discard a complete independent model report.
            # Formal quality/claim gates still persist their findings for
            # audit and residual evolution after delivery.
            return repaired_normalized
        blocking_issues = _report_delivery_blocking_issues(remaining_issues)
        if not blocking_issues and _minimum_viable_model_report(
            repaired_normalized,
            payload,
        ):
            return repaired_normalized
        nonnegotiable = _report_nonnegotiable_delivery_issues(
            remaining_issues
        )
        if not nonnegotiable and _minimum_viable_model_report(
            repaired_normalized,
            payload,
        ) and not _report_delivery_blocking_issues(remaining_issues):
            # After the one allowed targeted repair, benchmark-detail
            # shortcomings become residuals. They must not trigger another
            # full Reporter call or fail a substantively complete report.
            return repaired_normalized
        if allow_limited and _minimum_viable_model_report(
            repaired_normalized,
            payload,
        ):
            return repaired_normalized
        raise ValueError(
            "report delivery gate failed after repair: "
            + "；".join(remaining_issues[:8])
        )
    return repaired_normalized


async def run_reporter_text(
    host,
    system: str,
    payload: dict[str, Any],
    max_output_tokens: int,
    *,
    phase: str,
    run_id: str = "",
    isolation_id: str = "",
    force_fallback: bool = False,
    fallback_reason: str = "",
    provider_profile: str = "",
) -> str:
    """Run Reporter in a fresh minimal Codex context without agent runtime."""

    # Reporter is a delivery-quality boundary, not a deadline relief valve.
    # Keep this invariant local to the actual provider call so a future
    # caller, legacy phase name (including fast_finalize/timeout_retry),
    # registry override, or global Codex performance profile cannot silently
    # lower report reasoning depth or truncate the output allowance.
    # Serial delivery retains xhigh/12k. Parallel template sections use
    # high reasoning with an 8k maximum planning budget, then stop against
    # their own section contract once complete.
    configured_effort = "xhigh"
    short_parallel_section = False
    if isolation_id and str(phase).startswith("report_generation_"):
        # Parallel report sections are bounded synthesis jobs.  ``high``
        # preserves Codex CLI's reasoning quality while avoiding the
        # xhigh latency multiplier across the template's actual sections.
        configured_effort = "high"
        contract = payload.get("parallel_section_contract", {})
        if isinstance(contract, Mapping):
            try:
                target_chars = int(contract.get("target_chars", 0))
            except (TypeError, ValueError):
                target_chars = 0
            # Architecture/unit columns are bounded synthesis jobs.  Keeping
            # xhigh out of these short turns removes the hidden-reasoning tail
            # while their shared spine and strict contract preserve factual
            # quality.  Longer chapters retain high reasoning.
            short_parallel_section = 0 < target_chars <= 700
            if short_parallel_section:
                configured_effort = os.environ.get(
                    "EQUIPMENT_DR_REPORT_SHORT_SECTION_REASONING_EFFORT",
                    "medium",
                ).strip() or "medium"
    # Parallel callers provide a section-specific soft planning budget
    # (4k for short sections, 8k for the equipment portrait). Honor it at
    # the provider boundary without treating it as a truncation condition.
    if isolation_id and str(phase).startswith("report_generation_"):
        try:
            configured_max_tokens = _parallel_report_output_cap(
                max_output_tokens,
                payload,
            )
        except (TypeError, ValueError):
            configured_max_tokens = 4000
    elif str(phase) == "report_title_rewrite":
        configured_max_tokens = max(64, min(256, int(max_output_tokens or 120)))
    else:
        configured_max_tokens = 12000
    options = _apply_codex_performance_options(
        {
            "reasoning_effort": _phase_reasoning_effort(
                "reporter", phase, configured_effort
            ),
            "model_verbosity": "medium",
            "prompt_mode": "standalone",
            "max_output_tokens": configured_max_tokens,
            "_soft_output_token_budget": bool(isolation_id),
            # Keep Reporter quality independent of the global deadline while
            # retaining deadline telemetry for audit and scheduling metrics.
            "_no_deadline_degrade": True,
            "_disable_provider_timeout": True,
            "_run_id": str(run_id or ""),
        },
        host.provider_kind,
        quality_critical=True,
    )
    primary_provider = host._provider_for("reporter", isolation_id=isolation_id)
    primary_snapshot = _provider_snapshot(primary_provider)
    selected_provider, chain_fallback = _resolve_reporter_provider(
        host,
        isolation_id=isolation_id,
        force_fallback=force_fallback,
        provider_profile=provider_profile,
    )
    if force_fallback:
        # DeepSeek-compatible chat gateways can spend the whole visible-token
        # budget in hidden reasoning. Recovery chapters need a usable body,
        # so prefer visible output over another empty/truncated response.
        options["_disable_hidden_reasoning"] = True
        options["_fallback_reason"] = (
            str(fallback_reason).strip() or "report_chapter_retry_exhausted"
        )
        if chain_fallback:
            options["_force_fallback_provider"] = True
    if short_parallel_section and os.environ.get(
        "EQUIPMENT_DR_REPORT_SHORT_SECTION_DISABLE_HIDDEN_REASONING", "1"
    ).strip().lower() in {"1", "true", "yes"}:
        options["_disable_hidden_reasoning"] = True
    text, metadata = await host._collect_stream(
        selected_provider,
        [
            ModelMessage("system", system),
            ModelMessage("user", payload),
        ],
        options,
        priority="delivery",
        progress={
            "run_id": run_id,
            "agent_id": "reporter",
            "phase": phase,
            "current_step": (
                "报告定向修复"
                if phase.endswith("_repair")
                else (
                    "项目论证报告撰写"
                    if _report_template_mode(payload)
                    == "project_argument_v1"
                    else "三层九项报告撰写"
                )
            ),
        },
        progress_family="report",
    )
    if force_fallback:
        # Direct profile fallback does not pass through FallbackProvider's
        # metadata decorator. Preserve equivalent audit fields for metrics and
        # progress consumers without changing the public text contract.
        metadata.setdefault("fallback_activated", True)
        metadata.setdefault(
            "fallback_reason",
            str(fallback_reason).strip() or "report_chapter_retry_exhausted",
        )
        metadata.setdefault("fallback_provider", _provider_snapshot(selected_provider))
        metadata.setdefault(
            "fallback_from",
            str(
                primary_snapshot.get("type")
                or primary_snapshot.get("provider_id")
                or getattr(primary_provider, "provider_type", "primary")
            ),
        )
        if chain_fallback:
            providers = getattr(selected_provider, "providers", ())
            if isinstance(providers, (tuple, list)) and len(providers) > 1:
                metadata["fallback_provider"] = _provider_snapshot(providers[1])
    host._record_call_metric(
        host._model_call_metric(
            "reporter",
            phase,
            options,
            metadata,
            provider=selected_provider,
        )
    )
    return text


def consume_report_quality_issues(host) -> list[str]:
    issues, host._last_report_quality_issues = host._last_report_quality_issues, []
    return list(issues)
