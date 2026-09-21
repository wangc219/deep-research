"""Shared provider runtime: routing, budgets, streaming, retries and metrics."""
# ruff: noqa: F821

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from equipment_deep_research.agents.workflows import coordinator as _legacy
from equipment_deep_research.execution_model import (
    configured_model,
    resolve_swarm_model,
)
from equipment_deep_research.model_profiles import swarm_profile_id
from equipment_deep_research.agents.dynamic_prompt_resources import (
    load_dynamic_winning_prompt,
)
from equipment_deep_research.harness.evolution_trace import (
    begin_retrieval,
    finish_retrieval,
)

globals().update(
    {name: value for name, value in vars(_legacy).items() if not name.startswith("__")}
)


def _s6_hard_timeout_enabled() -> bool:
    """Keep S6 timeout thresholds observational unless explicitly enforced."""

    configured = str(
        os.environ.get("EQUIPMENT_DR_S6_HARD_TIMEOUTS", "0")
    ).strip().lower()
    return configured in {
        "1",
        "true",
        "yes",
        "on",
    }


def _s6_timeout_threshold(name: str, default: int, minimum: int) -> int:
    """Read a soft/hard threshold without letting bad config fail S6."""

    try:
        configured = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        configured = default
    return max(minimum, configured)


def close(host) -> None:
    """Release all provider state owned by this research run."""

    with host._isolated_agent_providers_lock:
        if host._closed:
            return
        host._closed = True
        isolated_providers = list(host._isolated_agent_providers.values())
        host._isolated_agent_providers.clear()
    with host._discovery_lock:
        inflight = list(host._discovery_inflight.values())
        host._discovery_inflight.clear()
        host._discovery_cache.clear()
        host._shared_discovery_sources.clear()
    with host._run_call_gates_lock:
        host._run_call_gates.clear()
    for future in inflight:
        future.cancel()
    host._winning_progress_callback = None
    host._reporter_progress_callback = None
    host._baseline_progress_callback = None
    host._deep_dialogue_progress_callback = None
    host._deep_dialogue_steer_callback = None
    host._evolution_trace_sink = None
    host._evolution_context = {}
    host._s6_card_result_cache.clear()

    providers = [
        *isolated_providers,
        *host.agent_providers.values(),
        host.discovery_provider,
        host.provider,
    ]
    closed_ids: set[int] = set()
    first_error: BaseException | None = None
    for provider in providers:
        if provider is None or id(provider) in closed_ids:
            continue
        closed_ids.add(id(provider))
        close = getattr(provider, "close", None)
        if not callable(close):
            continue
        try:
            close()
        except BaseException as exc:
            if first_error is None:
                first_error = exc
    if first_error is not None:
        raise first_error


def configure_run_budget(host, budgets: Mapping[str, Any] | None) -> None:
    with host._budget_lock:
        host._runtime_budgets = {
            str(key): value for key, value in dict(budgets or {}).items()
        }
        host._run_started_at = monotonic()
        host._budget_started_calls = 0
        host._budget_started_delivery_calls = 0
        host._budget_started_reporter_calls = 0
        host._budget_started_swarm_calls = 0
        host._budget_started_s6_calls = 0
        # Token usage is advisory (providers may omit usage metadata), but a
        # run-scoped counter lets adaptive controllers make an honest
        # remaining-token decision when a profile declares one.
        host._budget_consumed_swarm_tokens = 0
        host._budget_started_quality_judge_calls = 0
        host._search_batches_started = 0
    if budgets:
        configured_concurrency = int(dict(budgets).get("codex_concurrency", 4))
        host._call_gate.configure_concurrency(configured_concurrency)
        # A provider instance can serve more than one run over its lifetime
        # (notably in tests and embedded workers).  Keep already-materialized
        # run gates aligned with the current execution profile; newly-created
        # gates inherit the same value in ``call_gate_for_run``.
        with host._run_call_gates_lock:
            run_gates = list(host._run_call_gates.values())
        for gate in run_gates:
            gate.configure_concurrency(configured_concurrency)


def deadline_state(host, *, priority: str) -> dict[str, Any]:
    """Return the current deadline pressure without consuming call budget."""

    with host._budget_lock:
        if not host._runtime_budgets:
            return {
                "enabled": False,
                "mode": "normal",
                "elapsed_seconds": 0.0,
                "remaining_seconds": None,
            }
        if not bool(
            host._runtime_budgets.get("wall_clock_deadlines_enabled", True)
        ):
            return {
                "enabled": False,
                "mode": "normal",
                "elapsed_seconds": monotonic() - host._run_started_at,
                "remaining_seconds": None,
            }
        elapsed = monotonic() - host._run_started_at
        configured_absolute = float(host._runtime_budgets.get("absolute_deadline_seconds", 0))
        absolute_deadline = min(2400.0, configured_absolute) if configured_absolute > 0 else 0.0
        configured_hard = float(host._runtime_budgets.get("hard_deadline_seconds", 0))
        hard_deadline = min(configured_hard, absolute_deadline) if absolute_deadline > 0 else configured_hard
        delivery_deadline = min(
            absolute_deadline,
            hard_deadline
            + max(
                0.0,
                float(host._runtime_budgets.get("delivery_grace_seconds", 300)),
            ),
        )
        critical_fast_deadline = min(
            delivery_deadline,
            hard_deadline
            + max(
                0.0,
                float(
                    host._runtime_budgets.get(
                        "critical_fast_finalize_seconds",
                        120,
                    )
                ),
            ),
        )
        active_deadline = (
            delivery_deadline if priority == "delivery" else hard_deadline
        )
        if priority == "critical" and elapsed >= hard_deadline:
            active_deadline = critical_fast_deadline
        downshift_window = max(
            30.0,
            float(
                host._runtime_budgets.get(
                    "deadline_downshift_window_seconds",
                    240,
                )
            ),
        )
        after_hard = elapsed >= hard_deadline
        approaching_hard = elapsed >= max(0.0, hard_deadline - downshift_window)
        mode = (
            "fast_finalize"
            if after_hard and priority in {"critical", "delivery"}
            else "deadline_approach"
            if approaching_hard
            else "normal"
        )
        return {
            "enabled": True,
            "mode": mode,
            "elapsed_seconds": elapsed,
            "hard_deadline_seconds": hard_deadline,
            "active_deadline_seconds": active_deadline,
            "remaining_seconds": max(0.0, active_deadline - elapsed),
            "after_hard_deadline": after_hard,
            "approaching_hard_deadline": approaching_hard,
        }


def deadline_adjusted_options(
    host,
    options: Mapping[str, Any],
    *,
    priority: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Downshift reasoning and output size as the run approaches finalization."""

    result = dict(options)
    no_deadline_degrade = bool(result.pop("_no_deadline_degrade", False))
    ignore_runtime_deadline = bool(
        result.pop("_ignore_runtime_deadline", False)
    )
    # This is an explicit escape hatch for maintenance callers only.  It is
    # deliberately separate from ``_ignore_runtime_deadline``: a long-running
    # quality turn may ignore the wall-clock cutoff while still consuming its
    # declared model-call allowance.
    result.pop("_exclude_from_model_budget", False)
    if ignore_runtime_deadline:
        return result, {
            "enabled": False,
            "mode": "unbounded_quality_stage",
            "remaining_seconds": 0.0,
        }
    state = host._deadline_state(priority=priority)
    if no_deadline_degrade:
        return result, state
    mode = str(state.get("mode", "normal"))
    if mode == "normal":
        return result, state

    configured_cap = int(
        host._runtime_budgets.get("fast_finalize_output_token_cap", 4200)
    )
    remaining = float(state.get("remaining_seconds") or 0.0)
    if mode == "fast_finalize":
        result["reasoning_effort"] = "low"
        token_cap = (
            configured_cap if priority == "delivery" else min(configured_cap, 1800)
        )
        result["max_output_tokens"] = min(
            int(result.get("max_output_tokens", token_cap)),
            token_cap,
        )
    else:
        current_effort = str(result.get("reasoning_effort", "high")).lower()
        if remaining <= 90:
            result["reasoning_effort"] = "low"
        elif current_effort in {"high", "xhigh"}:
            result["reasoning_effort"] = "medium"
        approach_cap = (
            min(configured_cap + 800, 5200)
            if priority == "delivery"
            else 2600
        )
        result["max_output_tokens"] = min(
            int(result.get("max_output_tokens", approach_cap)),
            approach_cap,
        )
    result["model_verbosity"] = "low"
    search = result.get("web_search")
    if isinstance(search, Mapping):
        compact_search = dict(search)
        compact_search["search_context_size"] = "low"
        result["web_search"] = compact_search
    return result, state


def optional_work_allowed(
    host,
    *,
    priority: str = "normal",
    minimum_remaining_seconds: float = 120.0,
) -> bool:
    """Return whether a non-essential model loop may still be started.

    Token/effort downshifting happens inside ``_collect_stream``.  This
    guard sits one level higher and prevents a critic, rereview, dynamic
    specialist or full retry from being started when the remaining wall
    clock can no longer amortize that extra call.
    """

    state = host._deadline_state(priority=priority)
    if not state.get("enabled"):
        return True
    return (
        state.get("mode") == "normal"
        and float(state.get("remaining_seconds") or 0.0)
        >= max(0.0, minimum_remaining_seconds)
    )


def reserve_model_call(
    host,
    *,
    priority: str,
    count_toward_model_budget: bool = True,
    ignore_runtime_deadline: bool = False,
    reporter_lane: bool = False,
) -> float | None:
    with host._budget_lock:
        if not host._runtime_budgets:
            return None
        elapsed = monotonic() - host._run_started_at
        wall_clock_deadlines_enabled = bool(
            host._runtime_budgets.get("wall_clock_deadlines_enabled", True)
        ) and not ignore_runtime_deadline
        hard_deadline = float(host._runtime_budgets.get("hard_deadline_seconds", 0))
        configured_absolute = float(host._runtime_budgets.get("absolute_deadline_seconds", 0))
        absolute_deadline = min(2400.0, configured_absolute) if configured_absolute > 0 else 0.0
        if wall_clock_deadlines_enabled and absolute_deadline > 0:
            hard_deadline = min(hard_deadline, absolute_deadline)
        soft_deadline = float(host._runtime_budgets.get("soft_deadline_seconds", 0))
        hard_calls = int(
            host._runtime_budgets.get("maximum_model_calls_with_residuals", 10)
        )
        soft_calls = int(
            host._runtime_budgets.get("maximum_model_calls", 7)
        )
        if priority == "s6":
            s6_calls = int(
                host._runtime_budgets.get(
                    "maximum_s6_model_calls",
                    max(
                        int(host._runtime_budgets.get("maximum_swarm_model_calls", 16)),
                        64,
                    ),
                )
            )
            if wall_clock_deadlines_enabled and elapsed >= hard_deadline:
                raise RuntimeError("Harness v2 S6 deadline reached")
            if count_toward_model_budget and host._budget_started_s6_calls >= s6_calls:
                raise RuntimeError("Harness v2 S6 model-call budget exhausted")
            if count_toward_model_budget:
                host._budget_started_s6_calls += 1
            return (
                max(0.1, hard_deadline - elapsed)
                if wall_clock_deadlines_enabled
                else None
            )
        if priority == "swarm":
            swarm_calls = int(
                host._runtime_budgets.get("maximum_swarm_model_calls", 16)
            )
            if wall_clock_deadlines_enabled and elapsed >= hard_deadline:
                raise RuntimeError("Harness v2 swarm deadline reached")
            if (
                count_toward_model_budget
                and host._budget_started_swarm_calls >= swarm_calls
            ):
                raise RuntimeError(
                    "Harness v2 swarm model-call budget exhausted"
                )
            if count_toward_model_budget:
                host._budget_started_swarm_calls += 1
            return (
                max(0.1, hard_deadline - elapsed)
                if wall_clock_deadlines_enabled
                else None
            )
        if priority == "quality_gate":
            quality_calls = int(
                host._runtime_budgets.get(
                    "maximum_quality_judge_model_calls", 1
                )
            )
            if wall_clock_deadlines_enabled and elapsed >= hard_deadline:
                raise RuntimeError(
                    "Harness v2 quality-judge deadline reached"
                )
            if (
                count_toward_model_budget
                and host._budget_started_quality_judge_calls >= quality_calls
            ):
                raise RuntimeError(
                    "Harness v2 quality-judge model-call budget exhausted"
                )
            if count_toward_model_budget:
                host._budget_started_quality_judge_calls += 1
            return (
                max(0.1, hard_deadline - elapsed)
                if wall_clock_deadlines_enabled
                else None
            )
        if priority == "delivery":
            delivery_grace = float(
                host._runtime_budgets.get("delivery_grace_seconds", 300)
            )
            delivery_deadline = min(
                absolute_deadline,
                hard_deadline + max(0.0, delivery_grace),
            )
            # Reporter delivery is intentionally exempt from wall-clock
            # cancellation, but it still needs a finite call budget.  Keep a
            # separate lane budget because a column-parallel report may require
            # targeted retries while ordinary delivery calls (for
            # example a legacy serial repair) should retain their smaller
            # historical allowance.
            delivery_budget_key = (
                "maximum_reporter_model_calls"
                if reporter_lane
                else "maximum_delivery_model_calls"
            )
            delivery_calls = int(
                host._runtime_budgets.get(
                    delivery_budget_key,
                    host._runtime_budgets.get("maximum_delivery_model_calls", 8),
                )
            )
            if wall_clock_deadlines_enabled and elapsed >= delivery_deadline:
                raise RuntimeError(
                    "Harness v2 delivery deadline reached; report model call may not start"
                )
            budget_attr = (
                "_budget_started_reporter_calls"
                if reporter_lane
                else "_budget_started_delivery_calls"
            )
            budget_used = int(getattr(host, budget_attr, 0))
            if count_toward_model_budget and budget_used >= delivery_calls:
                raise RuntimeError(
                    "Harness v2 reporter model-call budget exhausted"
                    if reporter_lane
                    else "Harness v2 delivery model-call budget exhausted"
                )
            if count_toward_model_budget:
                setattr(host, budget_attr, budget_used + 1)
            if not wall_clock_deadlines_enabled:
                return None
            remaining = max(0.1, delivery_deadline - elapsed)
            retry_reserve = max(
                0.0,
                float(
                    host._runtime_budgets.get(
                        "delivery_retry_reserve_seconds",
                        45,
                    )
                ),
            )
            calls_remain = int(getattr(host, budget_attr, 0)) < delivery_calls
            if (
                elapsed >= hard_deadline
                and calls_remain
                and remaining > retry_reserve + 30.0
            ):
                remaining -= retry_reserve
            return max(0.1, remaining)
        if wall_clock_deadlines_enabled and elapsed >= hard_deadline:
            if priority != "critical":
                raise RuntimeError(
                    "Harness v2 hard deadline reached; no new model call may start"
                )
            critical_fast_deadline = min(
                absolute_deadline,
                hard_deadline
                + max(
                    0.0,
                    float(
                        host._runtime_budgets.get(
                            "critical_fast_finalize_seconds",
                            120,
                        )
                    ),
                ),
            )
            if elapsed >= critical_fast_deadline:
                raise RuntimeError(
                    "Harness v2 critical fast-finalize deadline reached; "
                    "use the latest complete checkpoint"
                )
        if count_toward_model_budget and host._budget_started_calls >= hard_calls:
            raise RuntimeError("Harness v2 model-call hard budget exhausted")
        if count_toward_model_budget and priority != "critical" and (
            (
                wall_clock_deadlines_enabled
                and elapsed >= soft_deadline
            )
            or host._budget_started_calls >= soft_calls
        ):
            raise RuntimeError("Harness v2 soft budget reached; optional model call skipped")
        if count_toward_model_budget:
            host._budget_started_calls += 1
        if not wall_clock_deadlines_enabled:
            return None
        active_deadline = (
            critical_fast_deadline
            if priority == "critical" and elapsed >= hard_deadline
            else hard_deadline
        )
        return max(0.1, active_deadline - elapsed)


def reserve_search_batches(host, requested: int) -> int:
    with host._budget_lock:
        if not host._runtime_budgets:
            return requested
        # Deep-divergence profiles use the concise ``max_searches`` key while
        # legacy execution contracts expose ``maximum_searches``.  Honour
        # either spelling so child retrieval cannot silently exceed its
        # six-search profile budget.
        maximum = int(
            host._runtime_budgets.get(
                "maximum_searches",
                host._runtime_budgets.get("max_searches", 12),
            )
        )
        granted = max(0, min(requested, maximum - host._search_batches_started))
        host._search_batches_started += granted
        return granted


def set_winning_progress_callback(
    host,
    callback: Callable[[dict[str, Any]], None] | None,
) -> None:
    host._winning_progress_callback = callback


def set_baseline_progress_callback(
    host,
    callback: Callable[[dict[str, Any]], None] | None,
) -> None:
    host._baseline_progress_callback = callback


def set_reporter_progress_callback(
    host,
    callback: Callable[[dict[str, Any]], None] | None,
) -> None:
    host._reporter_progress_callback = callback


def set_deep_dialogue_progress_callback(
    host,
    callback: Callable[[dict[str, Any]], None] | None,
) -> None:
    """Install a live progress sink for single-equipment deep dialogue."""

    host._deep_dialogue_progress_callback = callback


def emit_deep_dialogue_progress(host, row: dict[str, Any]) -> None:
    """Forward mid-council deep-dialogue progress without failing the turn."""

    callback = getattr(host, "_deep_dialogue_progress_callback", None)
    if callback is None:
        return
    try:
        callback(dict(row))
    except Exception:
        # Live UX telemetry must never invalidate the dialogue result.
        return


def set_deep_dialogue_steer_callback(
    host,
    callback: Callable[[str], list[dict[str, Any]]] | None,
) -> None:
    """Install the durable steering source used at council checkpoints."""

    host._deep_dialogue_steer_callback = callback


def claim_deep_dialogue_steers(host, stage: str) -> list[dict[str, Any]]:
    callback = getattr(host, "_deep_dialogue_steer_callback", None)
    if callback is None:
        return []
    rows = callback(str(stage or "context"))
    return [dict(item) for item in rows if isinstance(item, Mapping)]


def set_evolution_trace_sink(
    host,
    callback: Callable[..., Any] | None,
) -> None:
    """Install a run-scoped sink for prompt/memory attribution records."""

    # Delegate to the standalone helper under an alias to avoid shadowing the
    # runtime method name exposed by ``ResponsesAgentProvider``.
    from equipment_deep_research.harness.evolution_trace import (
        set_evolution_trace_sink as _set_sink,
    )

    _set_sink(host, callback)


def set_evolution_context(host, context: Mapping[str, Any] | None) -> None:
    """Attach immutable run-level snapshot metadata to a provider host."""

    from equipment_deep_research.harness.evolution_trace import (
        set_evolution_context as _set_context,
    )

    _set_context(host, context)


def evolution_trace_events(host) -> list[dict[str, Any]]:
    from equipment_deep_research.harness.evolution_trace import (
        evolution_trace_events as _events,
    )

    return _events(host)


def emit_baseline_progress(host, row: dict[str, Any]) -> None:
    if host._baseline_progress_callback is None:
        return
    try:
        host._baseline_progress_callback(dict(row))
    except Exception:
        return


def emit_winning_progress(host, row: dict[str, Any]) -> None:
    if host._winning_progress_callback is None:
        return
    try:
        host._winning_progress_callback(dict(row))
    except Exception:
        # Progress reporting must never invalidate the research result.
        return


def emit_reporter_progress(host, row: dict[str, Any]) -> None:
    if host._reporter_progress_callback is None:
        return
    try:
        host._reporter_progress_callback(dict(row))
    except Exception:
        # Delivery telemetry is diagnostic and must not break the report.
        return


def emit_model_progress(
    host,
    family: str,
    row: dict[str, Any],
) -> None:
    if family == "winning":
        host._emit_winning_progress(row)
    elif family == "report":
        host._emit_reporter_progress(row)
    else:
        host._emit_baseline_progress(row)


def record_call_metric(host, metric: Mapping[str, Any]) -> None:
    with host._call_metrics_lock:
        host._call_metrics.append(dict(metric))


def call_metric_count(host) -> int:
    with host._call_metrics_lock:
        return len(host._call_metrics)


def call_metrics_since(host, offset: int) -> list[dict[str, Any]]:
    with host._call_metrics_lock:
        return [dict(item) for item in host._call_metrics[offset:]]


_RUNTIME_METADATA_KEYS = frozenset({"run_id", "_run_id", "_audit_run_id"})


def _model_visible_payload(value: Any) -> Any:
    """Copy business input while removing execution-only run metadata.

    Run identifiers are needed by the provider runtime for concurrency gates,
    progress and checkpoint attribution, but they are not part of the model's
    business task.  Keep the original payload available to the runtime and
    provider selectors while giving the model a detached, metadata-free copy.
    """

    if isinstance(value, Mapping):
        return {
            key: _model_visible_payload(item)
            for key, item in value.items()
            if str(key) not in _RUNTIME_METADATA_KEYS
        }
    if isinstance(value, list):
        return [_model_visible_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_model_visible_payload(item) for item in value)
    return value


async def collect_stream(
    host,
    provider: ModelProvider,
    messages: Sequence[ModelMessage],
    options: Mapping[str, Any],
    *,
    priority: str = "normal",
    progress: Mapping[str, Any] | None = None,
    progress_family: str = "baseline",
) -> tuple[str, dict[str, Any]]:
    fragments: list[str] = []
    metadata: dict[str, Any] = {}
    no_deadline_degrade = bool(options.get("_no_deadline_degrade", False))
    ignore_runtime_deadline = bool(
        options.get("_ignore_runtime_deadline", False)
    )
    exclude_from_model_budget = bool(
        options.get("_exclude_from_model_budget", False)
    )
    # Only body/repair generation consumes the dedicated Reporter allowance.
    # The small title editor also uses agent_id=reporter, but belongs to the
    # ordinary delivery budget and must not take a column recovery slot.
    reporter_lane = priority == "delivery" and str(
        (progress or {}).get("phase", "")
    ).startswith("report_generation")
    # Reporter fan-out has its own per-run ceiling.  Resolve the run-scoped
    # gate before leasing so concurrent users cannot race on the shared gate.
    run_key = options.get("_run_id") or (progress or {}).get("run_id")
    run_gate = host.call_gate_for_run(run_key) if hasattr(host, "call_gate_for_run") else host._call_gate
    if reporter_lane:
        budgets = getattr(host, "_runtime_budgets", {})
        configured_reporter_concurrency = (
            budgets.get("reporter_codex_concurrency", 12)
            if isinstance(budgets, Mapping)
            else 12
        )
        try:
            run_gate.configure_concurrency(max(1, int(configured_reporter_concurrency)))
        except (TypeError, ValueError):
            run_gate.configure_concurrency(12)
    lease = run_gate.try_acquire(priority=priority)
    if lease is None:
        if progress:
            host._emit_model_progress(
                progress_family,
                {
                    "event_type": f"{progress_family}_model_queue_started",
                    **dict(progress),
                    "priority": priority,
                    **run_gate.snapshot(),
                }
            )
        lease = await asyncio.to_thread(
            run_gate.acquire,
            priority=priority,
        )
    try:
        remaining_seconds = host._reserve_model_call(
            priority=priority,
            # Search-backed discovery stays on the search budget.  Swarm
            # first drafts (including S6 cards that enable live search)
            # still consume the unified swarm call ceiling.
            count_toward_model_budget=(
                (
                    not isinstance(options.get("web_search"), Mapping)
                or priority in {"swarm", "s6"}
                )
                # ``_ignore_runtime_deadline`` only disables the wall-clock
                # cancellation path.  It must not turn dynamic specialist or
                # S6 repair attempts into unmetered model calls.  Callers that
                # truly perform an internal, non-model maintenance pass must
                # opt into the narrower escape hatch explicitly.
                and not exclude_from_model_budget
            ),
            ignore_runtime_deadline=ignore_runtime_deadline,
            reporter_lane=reporter_lane,
        )
        stream_options, deadline_state = host._deadline_adjusted_options(
            options,
            priority=priority,
        )
        # The run-local gate protects one research run; the Codex provider has
        # a second deployment-wide gate shared by all users and provider
        # instances. Preserve the orchestration priority across that boundary
        # so quality-gate and delivery turns are not buried behind background
        # exploration from another run.
        stream_options["_codex_call_priority"] = priority
        # Baseline packets are contract-bearing and must contain visible
        # findings.  DeepSeek/OpenLux may spend the whole budget in hidden
        # reasoning for long evidence prompts, so use its supported
        # provider-neutral switch only for baseline discovery/analysis.  The
        # S3-S6 creative and synthesis phases keep their normal reasoning.
        is_chat_completions = (
            getattr(provider, "provider_type", "") == "chat_completions"
        )
        current_phase = str(progress.get("phase", "")) if progress else ""
        if is_chat_completions and (
            current_phase
            in {
                "web_discovery_open",
                "web_discovery_fast",
                "evidence_analysis",
                # S5 is a compact, contract-bearing JSON judgement.  DeepSeek
                # reasoning models can otherwise spend the entire max-token
                # allowance on hidden reasoning and return a truncated
                # decisions array, which incorrectly activates transport
                # fallback instead of performing the requested five-axis
                # innovation review.
                "winning_swarm_dynamic_portfolio_review_fast",
            }
            # Dynamic swarm creative/reasoning nodes are also strict-JSON
            # contract turns. DeepSeek/OpenLux can burn the entire output
            # allowance on hidden reasoning and leave an empty visible body,
            # which currently surfaces as ``returned invalid JSON``.
            or current_phase.startswith("winning_swarm_dynamic")
            # S6 card authoring is the same strict-JSON contract, but its
            # five-column cards are much larger than the compact swarm JSON.
            # DeepSeek must not spend that budget on hidden reasoning.
            or current_phase.startswith("winning_s6")
        ):
            stream_options["_disable_hidden_reasoning"] = True
        if progress:
            audit_progress = dict(progress)
            run_id = str(audit_progress.get("run_id", "")).strip()
            if run_id:
                # Keep fairness explicit for provider adapters that do not
                # infer it from the run gate's private option map.
                stream_options["_run_id"] = run_id
                stream_options["_fairness_key"] = run_id
                stream_options["_audit_run_id"] = run_id
                stream_options["_audit_agent_id"] = str(
                    audit_progress.get("agent_instance_id")
                    or audit_progress.get("agent_id")
                    or "unattributed-agent"
                )
                stream_options["_audit_phase"] = str(
                    audit_progress.get("phase") or "model-turn"
                )
                stream_options["_audit_call_purpose"] = str(
                    audit_progress.get("current_step")
                    or audit_progress.get("lane")
                    or ""
                )
    except BaseException:
        run_gate.release(0.0, success=False)
        raise
    if isinstance(options, dict):
        options.clear()
        options.update(stream_options)
    if progress:
        host._emit_model_progress(
            progress_family,
            {
                "event_type": f"{progress_family}_model_call_started",
                **dict(progress),
                "priority": lease.priority,
                "queue_wait_seconds": lease.queue_wait_seconds,
                "concurrency_limit": lease.concurrency_limit,
                "active_calls": lease.active_calls,
            }
        )
    started_at = monotonic()
    success = False
    heartbeat_task: asyncio.Task[None] | None = None
    heartbeat_stop = asyncio.Event()
    if progress:
        heartbeat_interval = max(
            5.0,
            float(
                os.environ.get(
                    "EQUIPMENT_DR_MODEL_PROGRESS_INTERVAL_SECONDS",
                    "15",
                )
            ),
        )

        async def emit_heartbeat() -> None:
            while not heartbeat_stop.is_set():
                try:
                    await asyncio.wait_for(
                        heartbeat_stop.wait(),
                        timeout=heartbeat_interval,
                    )
                except TimeoutError:
                    host._emit_model_progress(
                        progress_family,
                        {
                            "event_type": f"{progress_family}_model_call_progress",
                            **dict(progress),
                            "priority": lease.priority,
                            "queue_wait_seconds": lease.queue_wait_seconds,
                            "elapsed_seconds": round(monotonic() - started_at, 1),
                            "concurrency_limit": lease.concurrency_limit,
                            "active_calls": run_gate.snapshot()["active"],
                        }
                    )

        heartbeat_task = asyncio.create_task(emit_heartbeat())
    try:
        try:
            async with asyncio.timeout(remaining_seconds):
                async for event in provider.stream(messages, [], stream_options):
                    if event.event_type == "text_delta":
                        fragments.append(event.delta)
                    elif (
                        event.event_type == "final"
                        and event.final_turn
                        and event.final_turn.text
                    ):
                        metadata = dict(event.final_turn.metadata)
                        metadata["usage"] = dict(event.final_turn.usage)
                        metadata["finish_reason"] = event.final_turn.finish_reason
                        if not fragments:
                            fragments.append(event.final_turn.text)
                    elif event.event_type == "final" and event.final_turn:
                        metadata = dict(event.final_turn.metadata)
                        metadata["usage"] = dict(event.final_turn.usage)
                        metadata["finish_reason"] = event.final_turn.finish_reason
        except TimeoutError:
            partial = _trim_deadline_partial_text("".join(fragments))
            if (
                no_deadline_degrade
                or priority != "delivery"
                or len(partial) < 1200
            ):
                raise
            fragments = [partial]
            metadata["finish_reason"] = "deadline_partial"
            metadata["deadline_partial"] = True
        metadata.setdefault("queue_wait_seconds", lease.queue_wait_seconds)
        metadata.setdefault("concurrency_limit", lease.concurrency_limit)
        metadata.setdefault("active_calls_at_start", lease.active_calls)
        metadata.setdefault("priority", lease.priority)
        metadata.setdefault("deadline_mode", deadline_state.get("mode", "normal"))
        metadata.setdefault(
            "deadline_remaining_seconds",
            round(float(deadline_state.get("remaining_seconds") or 0.0), 3),
        )
        if priority in {"swarm", "s6"}:
            usage = metadata.get("usage")
            if isinstance(usage, Mapping):
                raw_total = usage.get("total_tokens")
                if raw_total is None:
                    raw_total = (
                        usage.get("input_tokens", usage.get("prompt_tokens", 0))
                        or 0
                    ) + (
                        usage.get(
                            "output_tokens", usage.get("completion_tokens", 0)
                        )
                        or 0
                    )
                try:
                    consumed_tokens = max(0, int(raw_total or 0))
                except (TypeError, ValueError):
                    consumed_tokens = 0
                if consumed_tokens:
                    with host._budget_lock:
                        token_counter = (
                            "_budget_consumed_s6_tokens"
                            if priority == "s6"
                            else "_budget_consumed_swarm_tokens"
                        )
                        setattr(
                            host,
                            token_counter,
                            int(getattr(host, token_counter, 0)) + consumed_tokens,
                        )
        success = True
    finally:
        elapsed = monotonic() - started_at
        heartbeat_stop.set()
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
        run_gate.release(elapsed, success=success)
        if progress:
            host._emit_model_progress(
                progress_family,
                {
                    "event_type": f"{progress_family}_model_call_completed",
                    **dict(progress),
                    "priority": lease.priority,
                    "queue_wait_seconds": lease.queue_wait_seconds,
                    "elapsed_seconds": round(elapsed, 3),
                    "success": success,
                }
            )
    if not isinstance(metadata.get("elapsed_seconds"), (int, float)):
        metadata["elapsed_seconds"] = round(elapsed, 3)
    return "".join(fragments).strip(), metadata


def provider_for(
    host,
    agent_id: str,
    *,
    isolation_id: str = "",
    payload: Mapping[str, Any] | None = None,
    provider_profile: str = "",
) -> ModelProvider:
    base_provider = host.agent_providers.get(agent_id, host.provider)
    scoped_id = str(isolation_id or "").strip()
    profile_factory = getattr(host, "model_profile_factory", None)
    # A caller may request a one-turn provider profile for a targeted
    # delivery retry (for example a failed Reporter chapter).  This is kept
    # separate from the normal swarm override lookup so ordinary calls retain
    # their configured routing and legacy monkeypatches remain compatible.
    profile_id = str(provider_profile or "").strip() or swarm_profile_id(agent_id, payload)
    capabilities = getattr(base_provider, "capabilities", lambda: None)()
    supports_isolation = bool(
        getattr(capabilities, "isolated_sessions", False)
        or getattr(host, "supports_isolated_sessions", False)
    )
    if profile_id and callable(profile_factory) and scoped_id:
        cache_key = f"profile:{profile_id}:{agent_id}:{scoped_id}"
        with host._isolated_agent_providers_lock:
            existing = host._isolated_agent_providers.get(cache_key)
            if existing is not None:
                return existing
            try:
                scoped_provider = profile_factory(profile_id, scoped_id)
            except (KeyError, OSError, ValueError):
                # Profile overrides are optional. If a role-specific profile
                # has no credential yet, retain the deployment provider so
                # legacy real/fake runs continue to work; doctor/use exposes
                # the missing configuration to the operator.
                scoped_provider = base_provider
            host._isolated_agent_providers[cache_key] = scoped_provider
            return scoped_provider
    if not scoped_id or not supports_isolation:
        return base_provider
    cache_key = f"{agent_id}:{scoped_id}"
    with host._isolated_agent_providers_lock:
        existing = host._isolated_agent_providers.get(cache_key)
        if existing is not None:
            return existing
        factory = getattr(base_provider, "isolated_copy", None)
        if not callable(factory):
            return base_provider
        scoped_model = resolve_swarm_model(
            agent_id,
            payload,
            fallback=str(getattr(base_provider, "model", "")),
        )
        base_model = str(getattr(base_provider, "model", "")).strip()
        if scoped_model and scoped_model != base_model:
            try:
                scoped_provider = factory(scoped_id, model=scoped_model)
            except TypeError:
                # Preserve compatibility with embedders that provide the old
                # one-argument isolated_copy seam.
                scoped_provider = factory(scoped_id)
        else:
            scoped_provider = factory(scoped_id)
        host._isolated_agent_providers[cache_key] = scoped_provider
        return scoped_provider


def _normalize_discovery_responses_url(value: str) -> str:
    """Normalize a configured API URL to the Responses endpoint.

    Provider profiles commonly store either an API root (``.../v1``), a
    complete Chat Completions URL (``.../v1/chat/completions``), or an
    already-normalized Responses URL.  Appending ``/responses`` blindly to
    the second form produces the invalid
    ``.../chat/completions/responses`` route and makes discovery look like a
    provider outage.  Keep query/fragment components intact for gateways
    that use them for routing or tenancy.
    """
    raw = str(value or "").strip()
    if not raw:
        return raw
    parsed = urlsplit(raw)
    path = parsed.path.rstrip("/")
    if path.endswith("/responses"):
        normalized_path = path or "/responses"
    elif path.endswith("/chat/completions"):
        normalized_path = f"{path[:-len('/chat/completions')]}/responses"
        if not normalized_path.startswith("/"):
            normalized_path = f"/{normalized_path}"
    else:
        normalized_path = f"{path}/responses" if path else "/responses"
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            normalized_path,
            parsed.query,
            parsed.fragment,
        )
    )


def build_discovery_provider(host) -> ModelProvider | None:
    """为 web discovery 构建直连 Responses provider。

    Codex CLI 0.144+ 的自定义 model_provider 会禁用 hosted web_search 工具，
    导致真实检索退化为沙箱内 curl（无网络）而返回 0 来源。网关本身支持
    Responses `web_search` 工具（含 search_queries 导出），因此发现阶段
    直接走 HTTPS Responses 端点，分析阶段仍由 Codex CLI 隔离会话执行。
    设 EQUIPMENT_DR_DISCOVERY_VIA_RESPONSES=0 可禁用此路径。
    """
    if os.environ.get("EQUIPMENT_DR_DISCOVERY_VIA_RESPONSES", "1") != "1":
        return None
    if str(getattr(host, "provider_kind", "")) != "codex_cli":
        return None
    # Discovery must use the same deployment profile as the task's primary
    # provider.  The old implementation always used the process-wide GPT
    # ``EQUIPMENT_DR_CODEX_*`` variables, which meant a task pinned to
    # ``codex_queen`` still performed its hosted search with GPT.  Resolve a
    # profile-specific endpoint from the selected provider model first, while
    # retaining the legacy GPT variables as the final fallback.
    # Prefer the already-instantiated primary adapter.  Embedded callers may
    # construct a provider with explicit credentials instead of exporting the
    # profile environment variables; falling back to the deployment-wide GPT
    # endpoint in that case silently sends discovery through the wrong model.
    selected_provider = getattr(host, "provider", None)
    provider_chain = getattr(selected_provider, "providers", None)
    if isinstance(provider_chain, (list, tuple)) and provider_chain:
        selected_provider = provider_chain[0]
    selected_model = str(getattr(selected_provider, "model", "") or "").strip()
    base_url = ""
    key_env = ""
    direct_api_key = str(getattr(selected_provider, "api_key", "") or "").strip()
    direct_base_url = str(getattr(selected_provider, "base_url", "") or "").strip()
    if direct_base_url and direct_api_key:
        base_url = direct_base_url
    matched_profiles: list[tuple[str, str, str]] = []
    for env_name, env_value in os.environ.items():
        if not env_name.startswith("EQUIPMENT_DR_") or not env_name.endswith("_MODEL"):
            continue
        if env_name == "EQUIPMENT_DR_MODEL":
            continue
        if not selected_model or str(env_value).strip() != selected_model:
            continue
        token = env_name[len("EQUIPMENT_DR_") : -len("_MODEL")]
        candidate_base_url = os.environ.get(
            f"EQUIPMENT_DR_{token}_BASE_URL", ""
        ).strip()
        candidate_key_env = os.environ.get(
            f"EQUIPMENT_DR_{token}_API_KEY_ENV", f"{token}_API_KEY"
        ).strip()
        if candidate_base_url and candidate_key_env:
            matched_profiles.append((token, candidate_base_url, candidate_key_env))
    if matched_profiles:
        # The routing helper materializes CODEX_* variables for DeepSeek
        # (including the local Chat-Completions bridge). Prefer that resolved
        # route over the original profile URL, regardless of environment
        # insertion order; otherwise discovery can accidentally target the
        # upstream relay and claim hosted search while the task runs through
        # a bridge that cannot provide Responses web search.
        matched_profiles.sort(
            key=lambda item: (
                0 if item[0].startswith("CODEX_") else 1,
                item[0],
            )
        )
        _token, matched_base_url, matched_key_env = matched_profiles[0]
        if not base_url:
            base_url = matched_base_url
        if not key_env and not direct_api_key:
            key_env = matched_key_env
    if not base_url:
        base_url = os.environ.get("EQUIPMENT_DR_CODEX_BASE_URL", "").strip()
    if not key_env and not direct_api_key:
        key_env = os.environ.get("EQUIPMENT_DR_CODEX_API_KEY_ENV", "").strip()
    api_key = direct_api_key or (os.environ.get(key_env, "").strip() if key_env else "")
    if not base_url or not api_key:
        return None
    from equipment_deep_research.providers.responses import ResponsesProvider

    endpoint = _normalize_discovery_responses_url(base_url)
    model = selected_model or configured_model()
    if not model:
        return None
    try:
        return ResponsesProvider(
            model=model,
            base_url=endpoint,
            api_key=api_key,
            timeout_seconds=int(
                os.environ.get("EQUIPMENT_DR_DISCOVERY_TIMEOUT_SECONDS", "300")
            ),
        )
    except Exception:
        return None


def discovery_provider_for(host, agent_id: str) -> ModelProvider:
    if host.discovery_provider is not None:
        return host.discovery_provider
    return host._provider_for(agent_id)


def model_call_metric(
    host,
    agent_id: str,
    phase: str,
    options: Mapping[str, Any],
    metadata: Mapping[str, Any],
    *,
    provider: ModelProvider | None = None,
) -> dict[str, Any]:
    snapshot = getattr(
        provider or host._provider_for(agent_id),
        "snapshot",
        lambda: {},
    )()
    usage = dict(metadata.get("usage", {}) or {})
    return {
        "agent_id": agent_id,
        "phase": phase,
        "provider": str(snapshot.get("type", host.provider_kind)),
        "context_isolation": str(snapshot.get("context_isolation", "")),
        "execution_backend": str(snapshot.get("execution_backend", "")),
        "process_isolation": str(snapshot.get("process_isolation", "")),
        "model": str(snapshot.get("model", "")),
        "reasoning_effort": str(options.get("reasoning_effort", "")),
        "max_output_tokens": int(options.get("max_output_tokens", 0) or 0),
        "elapsed_seconds": metadata.get("elapsed_seconds"),
        "latency_ms": metadata.get("latency_ms")
        if metadata.get("latency_ms") is not None
        else (
            round(float(metadata.get("elapsed_seconds")) * 1000, 3)
            if isinstance(metadata.get("elapsed_seconds"), (int, float))
            else None
        ),
        "prompt_chars": metadata.get("prompt_chars"),
        "output_chars": metadata.get("output_chars"),
        "queue_wait_seconds": metadata.get("queue_wait_seconds"),
        "concurrency_limit": metadata.get("concurrency_limit"),
        "active_calls_at_start": metadata.get("active_calls_at_start"),
        "usage": usage,
        "input_tokens": usage.get("input_tokens", usage.get("prompt_tokens")),
        "output_tokens": usage.get("output_tokens", usage.get("completion_tokens")),
        "total_tokens": usage.get("total_tokens"),
        "token_cost": usage.get("total_tokens")
        if usage.get("total_tokens") is not None
        else (
            (usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
            + (usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
        ),
        "cost_usd": metadata.get(
            "cost_usd", metadata.get("estimated_cost_usd")
        ),
        "finish_reason": metadata.get("finish_reason"),
        "fallback_activated": bool(metadata.get("fallback_activated")),
        "fallback_reason": str(metadata.get("fallback_reason", "")),
        "fallback_provider": dict(metadata.get("fallback_provider", {}) or {})
        if isinstance(metadata.get("fallback_provider"), Mapping)
        else {},
        "codex_transcript_paths": list(
            metadata.get("codex_transcript_paths", []) or []
        ),
        "deadline_mode": metadata.get("deadline_mode", "normal"),
        "deadline_remaining_seconds": metadata.get(
            "deadline_remaining_seconds"
        ),
        "deadline_partial": bool(metadata.get("deadline_partial")),
    }


async def run_core_json(
    host,
    agent_id: str,
    system: str,
    payload: dict[str, Any],
    output_schema: dict[str, Any],
    max_output_tokens: int,
    *,
    phase: str = "structured_analysis",
) -> str:
    # Blueprint routing is a small JSON decision, not a large artifact that
    # benefits from provider-side schema enforcement. Passing the full nested
    # schema to Codex CLI makes the first turn spend time on contract planning
    # before it reasons about the Query. Keep the strict JSON instruction in
    # the prompt and let the normal parser validate/fallback the result.
    provider_schema = None if phase == "blueprint_design" else output_schema
    return await host._run_core_text(
        agent_id,
        system
        + " "
        + load_dynamic_winning_prompt(
            "common", section="runtime.output_schema_suffix"
        ),
        {"input": payload},
        max_output_tokens,
        phase=phase,
        output_schema=provider_schema,
    )


async def run_core_text(
    host,
    agent_id: str,
    system: str,
    payload: dict[str, Any],
    max_output_tokens: int,
    *,
    phase: str = "analysis",
    output_schema: dict[str, Any] | None = None,
) -> str:
    agent = host.agent_definitions.get(agent_id)
    configured_max_tokens = (
        int(agent.model_profile.get("max_output_tokens", max_output_tokens))
        if agent is not None
        else max_output_tokens
    )
    configured_effort = (
        str(agent.model_profile.get("reasoning_effort", "high"))
        if agent is not None
        else "high"
    )
    options = {
        # Keep the phase in the internal provider envelope.  Prompt adapters
        # use it to apply column-specific retrieval guidance, while the
        # runtime strips this metadata from model payloads and public output.
        "phase": phase,
        "reasoning_effort": _phase_reasoning_effort(
            agent_id,
            phase,
            configured_effort,
        ),
        "model_verbosity": _phase_model_verbosity(agent_id, phase),
        "max_output_tokens": min(max_output_tokens, configured_max_tokens),
    }
    if phase == "blueprint_design":
        # Blueprint design is a bounded routing decision. It must not inherit
        # the Codex CLI's 900s provider ceiling and become the first task
        # long-tail before any swarm work has started.
        options.update(
            {
                "reasoning_effort": "medium",
                "model_verbosity": "low",
                "max_output_tokens": min(options["max_output_tokens"], 2200),
                "_provider_timeout_seconds": max(
                    30,
                    min(
                        180,
                        int(
                            os.environ.get(
                                "EQUIPMENT_DR_BLUEPRINT_TIMEOUT_SECONDS",
                                "150",
                            )
                        ),
                    ),
                ),
                "_provider_retry_attempts": 1,
                # Blueprint judgment is a single Codex CLI turn. The timeout
                # is scoped to this routing call; a timeout is recorded as a
                # local advisory fallback and never consumes the whole run.
                "_allow_extended_provider_timeout": True,
            }
        )
    if phase.startswith("deep_contextual_dialogue"):
        # A deep follow-up is a bounded three-round council over one existing
        # equipment result.  Every council role needs the same latency,
        # retry and privacy envelope; proposal/critique calls pass a smaller
        # max_output_tokens value while the final synthesizer can use the full
        # five-column allowance.
        try:
            deep_timeout = int(
                os.environ.get("EQUIPMENT_DR_DEEP_TIMEOUT_SECONDS", "300")
            )
        except ValueError:
            deep_timeout = 300
        deep_reasoning_effort = os.environ.get(
            "EQUIPMENT_DR_DEEP_REASONING_EFFORT", "medium"
        ).strip().lower()
        if deep_reasoning_effort not in {"low", "medium", "high", "xhigh"}:
            deep_reasoning_effort = "medium"
        options.update(
            {
                "reasoning_effort": deep_reasoning_effort,
                "model_verbosity": "low",
                # A governed deep result contains up to three compared
                # directions plus the complete S6 five-column portrait.  The
                # The original 2400/5600-token caps routinely truncated the
                # fourth/fifth column or forced overly terse cross-agent
                # synthesis. Keep proposal/critique calls bounded by their
                # own requested budgets while allowing the final S6 response
                # to use the full 12000-token envelope.
                "max_output_tokens": min(options["max_output_tokens"], 12000),
                "_provider_timeout_seconds": max(30, min(900, deep_timeout)),
                # Deep dialogue is an interactive, progress-streaming graph.
                # Do not turn the old 180-second (or any replacement) wall
                # into a hard process kill for proposal/critique either;
                # individual role failures are isolated by the council and
                # the UI continues to show durable stage progress.
                "_disable_provider_timeout": True,
                "_provider_retry_attempts": 1,
                "_no_deadline_degrade": True,
                "_ignore_runtime_deadline": True,
            }
        )
        if phase.startswith("deep_contextual_dialogue_synthesis"):
            # Final authoring receives the compared council packets plus the
            # complete S6 five-column contract.  It needs a wider quality
            # window than proposal/critique turns and explicit permission to
            # exceed the provider's ordinary timeout ceiling.
            timeout_env = (
                "EQUIPMENT_DR_DEEP_SYNTHESIS_RETRY_TIMEOUT_SECONDS"
                if phase.endswith("_retry")
                else "EQUIPMENT_DR_DEEP_SYNTHESIS_TIMEOUT_SECONDS"
            )
            timeout_default = 600 if phase.endswith("_retry") else 900
            try:
                synthesis_timeout = int(
                    os.environ.get(timeout_env, str(timeout_default))
                )
            except ValueError:
                synthesis_timeout = timeout_default
            options.update(
                {
                    "_provider_timeout_seconds": max(
                        120, min(3600, synthesis_timeout)
                    ),
                    "_allow_extended_provider_timeout": True,
                    # S6 quality work must not be killed at the former
                    # council-wide 180-second wall.  The application streams
                    # progress and persists each completed column instead.
                    "_disable_provider_timeout": True,
                    # The workflow owns one compact retry so provider replay
                    # cannot multiply the critical path invisibly.
                    "_provider_retry_attempts": 1,
                }
            )
        elif phase.startswith("deep_contextual_dialogue_s6_column_"):
            options.update(
                {
                    "reasoning_effort": "high",
                    "model_verbosity": "medium",
                    "_provider_timeout_seconds": 900,
                    "_allow_extended_provider_timeout": True,
                    "_disable_provider_timeout": True,
                    "_provider_retry_attempts": 1,
                }
            )
            # The technology-implementation column is the only deep-dialogue
            # S6 column that benefits from current, externally verifiable
            # technology findings. Keep live search scoped to its first turn;
            # recovery turns use the model directly so a search outage cannot
            # strand the card or make the other columns wait.
            if phase.startswith("deep_contextual_dialogue_s6_column_2"):
                # Technology retrieval is the only S6 lane that can touch a
                # remote search service. Give it a bounded wall and let the
                # workflow's explicit retry/fallback handle outages; the old
                # 900-second no-timeout profile left the whole card looking
                # permanently stuck on column 2.
                try:
                    technology_timeout = int(
                        os.environ.get(
                            "EQUIPMENT_DR_DEEP_TECHNOLOGY_TIMEOUT_SECONDS",
                            "180",
                        )
                    )
                except ValueError:
                    technology_timeout = 180
                options.update(
                    {
                        "_provider_timeout_seconds": max(
                            45, min(300, technology_timeout)
                        ),
                        "_disable_provider_timeout": False,
                    }
                )
                # The first pass attempts live search. Recovery turns remain
                # useful when the source endpoint is transiently unavailable,
                # but they must not turn search availability into a hard
                # publication gate or ask the model to expose a failure notice
                # in prose.
                if not any(
                    phase.endswith(suffix)
                    for suffix in ("_retry", "_model_recovery", "_offline_recovery")
                ):
                    options.update(
                        {
                            "web_search": {
                                "search_context_size": "medium",
                                "external_web_access": True,
                            },
                            "include_web_sources": True,
                            "require_web_search": False,
                        }
                    )
    # ``run_core_json`` wraps business payloads under ``input``.  Preserve the
    # durable run identity in internal runtime options so collect_stream can
    # select the correct run-scoped concurrency gate.  Direct text callers are
    # supported as well; walk a small number of wrappers for compatibility
    # with older adapters without serializing run metadata into model prompts.
    embedded_payload: Any = payload
    for _ in range(3):
        if not isinstance(embedded_payload, Mapping):
            break
        embedded_run_id = str(embedded_payload.get("run_id", "")).strip()
        if embedded_run_id:
            options["_run_id"] = embedded_run_id
            break
        nested_payload = embedded_payload.get("input")
        if not isinstance(nested_payload, Mapping) or nested_payload is embedded_payload:
            break
        embedded_payload = nested_payload
    if phase.startswith("winning_s6_parallel_card") and phase.endswith("_one_shot"):
        options.update(
            {
                "reasoning_effort": "high",
                "model_verbosity": "medium",
                "_provider_timeout_seconds": _s6_timeout_threshold(
                    "EQUIPMENT_DR_S6_CARD_RESUME_TIMEOUT_SECONDS"
                    if "resume" in phase
                    else "EQUIPMENT_DR_S6_CARD_TIMEOUT_SECONDS",
                    480 if "resume" in phase else 420,
                    180,
                ),
                "_disable_provider_timeout": not _s6_hard_timeout_enabled(),
                "_provider_retry_attempts": 1,
                "_no_deadline_degrade": True,
                "_ignore_runtime_deadline": True,
                "web_search": {
                    "search_context_size": "medium",
                    "external_web_access": True,
                },
                "include_web_sources": True,
                "require_web_search": False,
            }
        )
    elif phase.startswith("winning_s6_parallel_card") and "_module_" in phase:
        # One column is a bounded prose task. Keep high reasoning for the
        # military judgement, but use a tighter wall than whole-card turns.
        module_timeout_name = (
            "EQUIPMENT_DR_S6_CARD_REPAIR_TIMEOUT_SECONDS"
            if "repair" in phase
            else (
                "EQUIPMENT_DR_S6_CARD_RESUME_TIMEOUT_SECONDS"
                if "resume" in phase
                else "EQUIPMENT_DR_S6_CARD_TIMEOUT_SECONDS"
            )
        )
        module_default = 240 if "repair" in phase else (300 if "resume" in phase else 240)
        options.update(
            {
                # Independent portrait columns have a narrow, explicit prose
                # contract. Medium reasoning is sufficient after S5 has
                # frozen the equipment identity and mechanism, and avoids
                # xhigh/high tails on short cards. Repair keeps the existing
                # low-verbosity profile.
                "reasoning_effort": "medium",
                "model_verbosity": "low" if "repair" in phase else "medium",
                "_provider_timeout_seconds": _s6_timeout_threshold(
                    module_timeout_name,
                    module_default,
                    120,
                ),
                "_disable_provider_timeout": not _s6_hard_timeout_enabled(),
                "_provider_retry_attempts": 1,
                "_no_deadline_degrade": True,
                "_ignore_runtime_deadline": True,
            }
        )
        # A technology column gets one live-search opportunity on its first
        # authored attempt.  Module retries and quality-repair calls reuse the
        # compact handoff instead of issuing another remote search: this keeps
        # the five-column wave bounded when a gateway is slow or unavailable.
        portrait_module_attempt_value: Any = None
        attempt_payload: Any = payload
        for _ in range(3):
            if not isinstance(attempt_payload, Mapping):
                break
            if "portrait_module_attempt" in attempt_payload:
                portrait_module_attempt_value = attempt_payload.get(
                    "portrait_module_attempt"
                )
                break
            nested_attempt_payload = attempt_payload.get("input")
            if not isinstance(nested_attempt_payload, Mapping):
                break
            attempt_payload = nested_attempt_payload
        try:
            portrait_module_attempt = int(portrait_module_attempt_value or 1)
        except (TypeError, ValueError):
            portrait_module_attempt = 1
        technology_module = "_module_technology_implementation" in phase
        if technology_module:
            # Unlike the four local-reasoning columns, this lane can block on
            # an external search/tool request.  Keep every technology attempt
            # bounded, including no-search retries and offline recovery, so a
            # stalled provider cannot hold the five-column gather forever.
            try:
                technology_timeout = int(
                    os.environ.get(
                        "EQUIPMENT_DR_DEEP_TECHNOLOGY_TIMEOUT_SECONDS",
                        "180",
                    )
                )
            except (TypeError, ValueError):
                technology_timeout = 180
            options.update(
                {
                    "_provider_timeout_seconds": max(
                        45, min(300, technology_timeout)
                    ),
                    "_disable_provider_timeout": False,
                }
            )
        technology_search_allowed = (
            portrait_module_attempt <= 1
            and "repair" not in phase
            and not phase.endswith("_offline_recovery")
            and not phase.endswith("_retry")
            and not phase.endswith("_model_recovery")
        )
        if technology_module and technology_search_allowed:
            # S6.md requires the technology-realization column to compare
            # genuinely available routes and identify recent enabling
            # technologies.  Enable the provider's governed live-search path
            # only for this column so the requirement is executed rather than
            # answered from model memory, without multiplying search latency
            # across the other four concurrently authored columns.
            options.update(
                {
                    "web_search": {
                        "search_context_size": "medium",
                        "external_web_access": True,
                    },
                    "include_web_sources": True,
                    "require_web_search": False,
                }
            )
    elif phase.startswith("winning_s6_parallel_card") and phase.endswith("_spine"):
        options.update(
            {
                # The spine is compact structured routing context. The
                # substantive reasoning is completed in the five parallel
                # columns, so keep this short turn on the medium profile.
                "reasoning_effort": os.environ.get(
                    "EQUIPMENT_DR_S6_SPINE_REASONING_EFFORT",
                    "medium",
                ).strip().lower()
                if os.environ.get(
                    "EQUIPMENT_DR_S6_SPINE_REASONING_EFFORT",
                    "medium",
                ).strip().lower() in {"low", "medium", "high", "xhigh"}
                else "medium",
                "model_verbosity": "low",
                "_provider_timeout_seconds": _s6_timeout_threshold(
                    (
                        "EQUIPMENT_DR_S6_CARD_RESUME_TIMEOUT_SECONDS"
                        if "resume" in phase
                        else "EQUIPMENT_DR_S6_CARD_TIMEOUT_SECONDS"
                    ),
                    300 if "resume" in phase else 240,
                    120,
                ),
                "_disable_provider_timeout": not _s6_hard_timeout_enabled(),
                "_provider_retry_attempts": 1,
                "_no_deadline_degrade": True,
                "_ignore_runtime_deadline": True,
            }
        )
    elif phase.startswith("winning_s6_parallel_card_resume"):
        # Only an actually missing/failed card reaches this branch; cards
        # completed in the persisted checkpoint are rehydrated above.
        options.update(
            {
                "reasoning_effort": "high",
                "model_verbosity": "medium",
                "_provider_timeout_seconds": _s6_timeout_threshold(
                    "EQUIPMENT_DR_S6_CARD_RESUME_TIMEOUT_SECONDS",
                    480,
                    180,
                ),
                "_disable_provider_timeout": not _s6_hard_timeout_enabled(),
                # Workflow-level retry owns the second attempt so a congested
                # provider cannot multiply hidden retries across every card.
                "_provider_retry_attempts": 1,
                "_no_deadline_degrade": True,
                "_ignore_runtime_deadline": True,
            }
        )
    elif phase.startswith("winning_s6_parallel_card_repair"):
        # A single isolated card already has a locked weapon identity and
        # a precise defect list. The timeout is observational by default and
        # becomes a hard process boundary only when explicitly enabled.
        options.update(
            {
                "reasoning_effort": "medium",
                "model_verbosity": "low",
                "_provider_timeout_seconds": _s6_timeout_threshold(
                    "EQUIPMENT_DR_S6_CARD_REPAIR_TIMEOUT_SECONDS",
                    240,
                    120,
                ),
                "_disable_provider_timeout": not _s6_hard_timeout_enabled(),
                "_provider_retry_attempts": 1,
                "_no_deadline_degrade": True,
                "_ignore_runtime_deadline": True,
            }
        )
    elif phase.startswith("winning_s6_parallel_card"):
        # S3-S5 freeze identity, but S6 still owns scenario reconstruction,
        # the engineering-realization argument, decisive combat nodes and the
        # cross-module edit.  Those are substantive military judgments rather
        # than a bounded copy-edit, so preserve high reasoning while giving
        # each dynamic card a wide generation budget.  Length is evaluated
        # per module after the call: every column below the 380-character
        # enhancement trigger is repaired independently, so long sibling
        # columns can never hide a thin one.
        options.update(
            {
                "reasoning_effort": "high",
                "model_verbosity": "medium",
                # Keep a slow-call threshold for audit and optional hard
                # enforcement. The portfolio layer retries only actual failed
                # cards and preserves completed siblings for resume.
                "_provider_timeout_seconds": _s6_timeout_threshold(
                    "EQUIPMENT_DR_S6_CARD_TIMEOUT_SECONDS",
                    420,
                    180,
                ),
                "_disable_provider_timeout": not _s6_hard_timeout_enabled(),
                "_provider_retry_attempts": 1,
                "_no_deadline_degrade": True,
                # Regular first drafts share the swarm wall-clock and call
                # budget.  Only repair/resume/image recovery may ignore it.
                # Live search stays on the technology-column / repair path;
                # requiring it on every whole-card draft serialized the S6
                # wave behind seven search round-trips.
                "_ignore_runtime_deadline": False,
            }
        )
    elif phase.startswith("winning_s6_portrait_module_repair"):
        options.update(
            {
                "reasoning_effort": "medium",
                "model_verbosity": "low",
                "_provider_timeout_seconds": _s6_timeout_threshold(
                    "EQUIPMENT_DR_S6_MODULE_REPAIR_TIMEOUT_SECONDS",
                    240,
                    120,
                ),
                "_disable_provider_timeout": not _s6_hard_timeout_enabled(),
                "_provider_retry_attempts": 1,
                "_no_deadline_degrade": True,
                "_ignore_runtime_deadline": True,
            }
        )
    elif phase.startswith("winning_s6_card_repair"):
        # Card repair receives the complete, already quality-gated portfolio
        # plus a bounded set of card-local issues.  Running this narrow edit
        # with the full S6 xhigh profile turned a small deterministic repair
        # into another multi-minute critical-path call.  Keep the same
        # no-deadline delivery protection, but use the phase-specific low
        # reasoning/verbosity contract and a single transport attempt.
        options.update(
            {
                "reasoning_effort": "low",
                "model_verbosity": "low",
                "_provider_timeout_seconds": max(120, int(os.environ.get("EQUIPMENT_DR_S6_BATCH_REPAIR_TIMEOUT_SECONDS", "240"))),
                "_disable_provider_timeout": False,
                "_provider_retry_attempts": 1,
                "_no_deadline_degrade": True,
                "_ignore_runtime_deadline": True,
            }
        )
    elif agent_id == "winning_s6_image" or phase.startswith("winning_s6"):
        # Regular S6 first drafts share the swarm call budget.  Only
        # repair/resume/image recovery may ignore the wall-clock deadline.
        ignore_deadline = (
            agent_id == "winning_s6_image"
            or "repair" in phase
            or "resume" in phase
        )
        options.update(
            {
                "reasoning_effort": "xhigh",
                "model_verbosity": "medium",
                "_provider_retry_attempts": 2,
                "_no_deadline_degrade": True,
                "_ignore_runtime_deadline": ignore_deadline,
            }
        )
        if agent_id == "winning_s6_image" and phase.startswith(
            "winning_s6_image"
        ):
            # Standard/non-parallel S6 writes all five card columns in one
            # turn, including the Markdown-owned technology-realization
            # column, so it needs the same governed frontier-tech retrieval.
            options.update(
                {
                    "web_search": {
                        "search_context_size": "medium",
                        "external_web_access": True,
                    },
                    "include_web_sources": True,
                    "require_web_search": False,
                }
            )
    elif phase in {"evidence_analysis", "evidence_analysis_repair"}:
        # These calls receive already materialized, compact source rows
        # and only extract evidence-bearing judgments. Deep/xhigh turns
        # repeatedly became the longest baseline tail without increasing
        # the accepted-source target. Keep the structured analysis bounded
        # and let later domain/S1-S5 reasoning own synthesis depth.
        options.update(
            {
                "reasoning_effort": "medium",
                "model_verbosity": "low",
                "_provider_timeout_seconds": max(
                    120,
                    int(
                        os.environ.get(
                            "EQUIPMENT_DR_EVIDENCE_ANALYSIS_TIMEOUT_SECONDS",
                            "210",
                        )
                    ),
                ),
                "_disable_provider_timeout": False,
                "_provider_retry_attempts": 1,
            }
        )
    elif phase.startswith("winning_s5_handoff_contract_"):
        # S5 already has a frozen candidate and only closes two short,
        # falsifiable handoff fields. Run finalists concurrently with a
        # bounded low-latency profile; S6 remains the deep prose stage.
        options.update(
            {
                "reasoning_effort": "medium",
                "model_verbosity": "low",
                "_provider_timeout_seconds": max(
                    90,
                    int(
                        os.environ.get(
                            "EQUIPMENT_DR_S5_HANDOFF_TIMEOUT_SECONDS",
                            "180",
                        )
                    ),
                ),
                "_disable_provider_timeout": False,
                "_provider_retry_attempts": 1,
                "_no_deadline_degrade": True,
            }
        )
    elif phase == "winning_pre_generation_active_angle_selection":
        # This is an optional creativity hint, not an admission gate. Do not
        # terminate a healthy Codex CLI turn at an arbitrary wall-clock limit;
        # the workflow still fails open from S1/S2 seeds or the Query when the
        # provider actively reports an error or returns no usable hint.
        options.update(
            {
                "reasoning_effort": "low",
                "model_verbosity": "low",
                "_disable_provider_timeout": True,
                "_provider_retry_attempts": 1,
            }
        )
    elif phase in {
        "winning_semantic_pair_clustering",
        "winning_pre_generation_angle_selection",
    }:
        # This call only compares compact decision spines pairwise.  It is
        # an admission-control step, not another candidate authoring pass.
        # Keep it short so semantic convergence cannot dominate S3 time.
        options.update(
            {
                "reasoning_effort": "low",
                "model_verbosity": "low",
                "_provider_timeout_seconds": max(
                    60,
                    int(
                        os.environ.get(
                            "EQUIPMENT_DR_SEMANTIC_CLUSTER_TIMEOUT_SECONDS",
                            "120",
                        )
                    ),
                ),
                "_disable_provider_timeout": False,
                "_provider_retry_attempts": 1,
            }
        )
    elif phase.startswith("winning_swarm_dynamic_"):
        # Dynamic specialists are redundant and quality-gated. Allow one
        # provider-level retry so a transient relay/CLI failure does not
        # invalidate an otherwise healthy swarm instance.
        options.update(
            {
                "_provider_timeout_seconds": max(120, int(os.environ.get("EQUIPMENT_DR_SWARM_CALL_TIMEOUT_SECONDS", "480"))),
                "_disable_provider_timeout": True,
                # A dynamic specialist is a resumable, isolated branch.
                # The run-level wall-clock budget is an observability
                # signal for this branch, never a reason to kill a live
                # Codex turn or fail the whole mission graph.
                "_ignore_runtime_deadline": True,
                "_provider_retry_attempts": 2,
            }
        )
    elif re.match(r"^winning_(?:s[3-5]|cohort)", phase):
        # Core S3-S5 calls are checkpointed at the orchestration layer.
        # Replaying one long CLI response inside the provider can double a
        # ten-minute tail and still lose the response at the same relay
        # boundary. Use one bounded attempt for these upstream steps.
        options.update(
            {
                "_provider_timeout_seconds": max(
                    120,
                    int(
                        os.environ.get(
                            "EQUIPMENT_DR_WINNING_CORE_TIMEOUT_SECONDS",
                            "600",
                        )
                    ),
                ),
                "_provider_retry_attempts": 1,
            }
        )
    if agent_id == "reporter" or phase.startswith("report_generation"):
        options.update(
            {
                "reasoning_effort": "xhigh",
                "model_verbosity": "medium",
                "max_output_tokens": 12000,
                "_no_deadline_degrade": True,
            }
        )
    extended_quality_call = (
        agent_id == "reporter"
        or phase.startswith("report_generation")
        or phase.startswith("winning_quality_expert")
        or (
            (agent_id == "winning_s6_image" or phase.startswith("winning_s6"))
            and not phase.startswith("winning_s6_card_repair")
        )
    )
    if extended_quality_call:
        try:
            quality_timeout_seconds = int(
                os.environ.get(
                    "EQUIPMENT_DR_CODEX_QUALITY_TIMEOUT_SECONDS",
                    "3600",
                )
            )
        except (TypeError, ValueError):
            quality_timeout_seconds = 3600
        options.setdefault(
            "_provider_timeout_seconds",
            max(30, quality_timeout_seconds),
        )
        options["_allow_extended_provider_timeout"] = True
        options.setdefault("_provider_retry_attempts", 1)
    options = _apply_codex_performance_options(
        options,
        host.provider_kind,
        quality_critical=(
            agent_id == "reporter"
            or agent_id == "winning_s6_image"
            or phase.startswith("report_generation")
            or phase.startswith("winning_s6")
            or phase.startswith("winning_quality_expert")
        ),
    )
    if output_schema is not None:
        options["output_schema"] = output_schema
    progress: dict[str, Any] | None = None
    progress_family = "baseline"
    progress_subject = f"{agent_id} {phase}".lower()
    winning_steps = sorted(
        {
            int(item)
            for item in re.findall(
                r"(?:^|[_-])s([3-6])(?:[_-]|$)",
                progress_subject,
            )
        }
    )
    if not winning_steps and phase.startswith("winning_swarm_dynamic"):
        embedded_input = payload.get("input", payload)
        embedded_input = (
            embedded_input if isinstance(embedded_input, Mapping) else {}
        )
        mission_node = str(embedded_input.get("mission_node", "")).upper()
        match = re.fullmatch(r"S([3-6])", mission_node)
        if match:
            winning_steps = [int(match.group(1))]
    if winning_steps:
        embedded = payload.get("input", payload)
        embedded = embedded if isinstance(embedded, Mapping) else {}
        step_names = {
            3: "突破口与效果推演",
            4: "装备能力映射",
            5: "装备现状与差距",
            6: "能力画像综合",
        }
        step_label = "/".join(f"S{step}" for step in winning_steps)
        current_step = (
            f"{step_label} 联合推理"
            if len(winning_steps) > 1
            else f"{step_label} {step_names[winning_steps[0]]}"
        )
        if "repair" in phase:
            current_step += "修复"
        progress = {
            "run_id": str(embedded.get("run_id", "")),
            "agent_id": agent_id,
            "agent_instance_id": str(
                embedded.get("agent_instance_id", "")
            ),
            "mission_node": str(embedded.get("mission_node", "")),
            "batch": embedded.get("batch"),
            "phase": phase,
            "step": winning_steps[0],
            "steps": winning_steps,
            "current_step": current_step,
        }
        progress_family = "winning"
    provider_isolation_id = _swarm_provider_isolation_id(agent_id, payload)
    selected_provider = host._provider_for(
        agent_id,
        isolation_id=provider_isolation_id,
        payload=payload,
    )
    if progress and provider_isolation_id:
        provider_snapshot = getattr(selected_provider, "snapshot", lambda: {})()
        progress["context_isolation"] = str(
            provider_snapshot.get("context_isolation") or provider_isolation_id
        )
        progress["execution_backend"] = str(
            provider_snapshot.get("execution_backend") or "independent_codex_cli"
        )
        progress["process_isolation"] = str(
            provider_snapshot.get("process_isolation") or "new_process_per_turn"
        )
    # The model prompt is the point at which a selected lesson can actually
    # influence S1--S6.  Emit a bounded retrieval lifecycle around this single
    # provider call so replay can distinguish selected/applied from adopted or
    # contradicted outcomes.  ``begin_retrieval`` is a no-op for non-winning
    # phases and for standalone hosts that do not expose an evolution sink.
    retrieval_handle = begin_retrieval(
        host,
        agent_id=agent_id,
        phase=phase,
        payload=payload,
        system=system,
    )
    try:
        text, final_metadata = await host._collect_stream(
            selected_provider,
            host._runtime_messages(
                agent_id,
                system,
                payload,
                phase=phase,
                agent=agent,
                harness_profile=host._harness_for(agent),
            ),
            options,
            priority=(
                "delivery"
                if agent_id == "reporter" or phase.startswith("report_generation")
                else "quality_gate"
                if phase.startswith("winning_quality_expert")
                else "s6"
                if phase.startswith("winning_s6_parallel_card")
                else "swarm"
                if phase.startswith("winning_swarm_")
                else "normal"
                if any(marker in phase for marker in ("critic", "review", "convergence", "audit"))
                else "critical"
            ),
            progress=progress,
            progress_family=progress_family,
        )
    except BaseException as exc:
        finish_retrieval(
            retrieval_handle,
            output="",
            metadata={"finish_reason": "error"},
            success=False,
            error=exc,
        )
        raise
    finish_retrieval(
        retrieval_handle,
        output=text,
        metadata=final_metadata,
        success=True,
    )
    host._record_call_metric(
        host._model_call_metric(
            agent_id,
            phase,
            options,
            final_metadata,
            provider=selected_provider,
        )
    )
    return text


def runtime_messages(
    host,
    agent_id: str,
    system: str,
    payload: dict[str, Any],
    *,
    phase: str,
    agent: AgentDef | None = None,
    harness_profile: HarnessProfile | None = None,
) -> list[ModelMessage]:
    runtime = build_codex_runtime_profile(
        agent_id,
        payload=payload,
        agent=agent,
        harness_profile=harness_profile,
        phase=phase,
        compact=True,
    )
    quality_profile = is_optimized_v2_payload(payload)
    aggressive_compaction = is_aggressive_optimized_v2_payload(payload)
    dynamic_winning = is_dynamic_winning_payload(payload)
    codex_skill_rule = ""
    if host.provider_kind == "codex_cli":
        codex_skill_rule = load_dynamic_winning_prompt(
            "common", section="runtime.codex_skill_rule"
        )
        if agent_id.startswith("winning") or phase.startswith("winning"):
            codex_skill_rule += " " + load_dynamic_winning_prompt(
                "common", section="runtime.codex_winning_skill_suffix"
            )
    isolated_preamble = load_dynamic_winning_prompt(
        "common", section="runtime.isolated_preamble"
    )
    # Blueprint design is a model routing decision, not a workspace task.
    # Codex skill instructions and process-isolation prose add tokens and can
    # trigger unnecessary tool/runtime planning before the model reads the
    # Query.  Keep those contracts for execution phases only.
    if phase == "blueprint_design":
        codex_skill_rule = ""
        isolated_preamble = ""
    if dynamic_winning:
        system_message = (
            codex_skill_rule
            + isolated_preamble
            + system
            + " "
            + load_dynamic_winning_prompt(
                "common", section="runtime.dynamic_suffix"
            )
        )
    elif aggressive_compaction:
        system_message = (
            codex_skill_rule
            + isolated_preamble
            + system
            + " "
            + load_dynamic_winning_prompt(
                "common", section="runtime.aggressive_suffix"
            )
        )
    else:
        system_message = (
            codex_skill_rule
            + isolated_preamble
            + system
            + " "
            + load_dynamic_winning_prompt(
                "common", section="runtime.standard_suffix"
            )
        )
        if quality_profile:
            system_message += " " + load_dynamic_winning_prompt(
                "common", section="runtime.quality_suffix"
            )
    model_payload = _model_visible_payload(payload)
    return [
        ModelMessage(
            "system",
            system_message,
        ),
        ModelMessage(
            "user",
            {
                "agent_runtime": runtime,
                "task_input": model_payload,
            },
        ),
    ]


def harness_for(host, agent: AgentDef | None) -> HarnessProfile | None:
    if agent is None or not agent.harness_profile:
        return None
    return host.harness_profiles.get(agent.harness_profile)
