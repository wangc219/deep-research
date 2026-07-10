"""Controlled browser observe/action tools for whitelisted sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Protocol
from urllib.parse import parse_qs, urljoin, urlparse

from knowledgegraph.demand_discovery.domain.browser_research import (
    BrowserApiCandidate,
    BrowserRecipeDraft,
)
from bs4 import BeautifulSoup
from bs4.element import Tag

from knowledgegraph.demand_discovery.domain.source_registry import SourceRegistry
from knowledgegraph.demand_discovery.domain.store import DomainStore
from knowledgegraph.demand_discovery.harness.tools import (
    ToolDefinition,
    ToolExecutionContext,
)
from knowledgegraph.demand_discovery.harness.types import (
    DomainTraceProposal,
    DomainWriteProposal,
    ToolCall,
    ToolResult,
)
from knowledgegraph.demand_discovery.tools.artifacts import ArtifactStore
from knowledgegraph.demand_discovery.tools.network import (
    UNTRUSTED_NOTICE,
    WHITELIST_BLOCK_MESSAGE,
)


ALLOWED_BROWSER_ACTIONS = {
    "click_link",
    "fill_input",
    "submit_form",
    "next_page",
    "download_link",
    "activate_button",
    "capture_current_document",
}
MAX_BROWSER_JS_CHARS = 4000
SENSITIVE_INPUT_TYPES = {"hidden", "password"}
SENSITIVE_PAGE_RISK_FLAGS = {
    "sensitive_form_fields",
    "login_required_signal",
    "captcha_signal",
    "paywall_signal",
}
PREFLIGHT_BLOCKED_JS_PATTERNS = [
    r"\bdocument\.cookie\b",
    r"\bdocument\s*\[\s*['\"]cookie['\"]\s*\]",
    r"\blocalStorage\b",
    r"\bwindow\s*\[\s*['\"]localStorage['\"]\s*\]",
    r"\bsessionStorage\b",
    r"\bwindow\s*\[\s*['\"]sessionStorage['\"]\s*\]",
    r"\bindexedDB\b",
    r"\bXMLHttpRequest\b",
    r"\bWebSocket\b",
    r"\bAuthorization\b",
    r"\bcredentials\s*:\s*['\"](?:include|same-origin)['\"]",
    r"\bmethod\s*:\s*['\"](?:POST|DELETE|PUT|PATCH)['\"]",
]


@dataclass(frozen=True)
class BrowserUrlScope:
    scope_type: str
    source_name: str
    plan_id: str = ""
    lead_id: str = ""
    url_prefixes: list[str] = field(default_factory=list)
    hosts: list[str] = field(default_factory=list)
    scope_granularity: str = "url_prefix"


@dataclass(frozen=True)
class BrowserPageSnapshot:
    url: str
    html: str
    download_url: str = ""


class BrowserSession(Protocol):
    async def observe(self, url: str, timeout_ms: int) -> BrowserPageSnapshot:
        ...

    async def action(
        self,
        *,
        action: str,
        target: dict[str, object],
        value: str,
        timeout_ms: int,
    ) -> BrowserPageSnapshot:
        ...

    async def execute_javascript(
        self,
        *,
        script: str,
        timeout_ms: int,
        max_return_chars: int,
        allow_network_probe: bool,
        safety_policy: dict[str, object],
    ) -> dict[str, object]:
        ...


@dataclass
class BrowserObservation:
    observation_id: str
    page_url: str
    title: str
    artifact_ref: str
    targets: dict[str, dict[str, object]]
    visible_text_digest: str = ""
    source_scope: dict[str, object] = field(default_factory=dict)
    page_risk_flags: list[str] = field(default_factory=list)
    filled_values: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BrowserPageScan:
    title: str
    visible_text: str
    targets: list[dict[str, object]]
    article_candidates: list[dict[str, object]]
    listing_candidates: list[dict[str, object]]
    forms: list[dict[str, object]]
    buttons: list[dict[str, object]]
    download_targets: list[dict[str, object]]
    pagination_targets: list[dict[str, object]]
    network_api_candidates: list[dict[str, object]]
    access_status: str
    page_risk_flags: list[str]
    suggested_interaction_modes: list[str]


class BrowserActionState:
    def __init__(self) -> None:
        self._observations: dict[str, BrowserObservation] = {}

    def remember(
        self,
        *,
        page_url: str,
        title: str,
        artifact_ref: str,
        targets: list[dict[str, object]],
        visible_text_digest: str = "",
        source_scope: dict[str, object] | None = None,
        page_risk_flags: list[str] | None = None,
    ) -> BrowserObservation:
        observation_id = f"obs-{_hash(f'{page_url}|{artifact_ref}|{len(targets)}')}"
        observation = BrowserObservation(
            observation_id=observation_id,
            page_url=page_url,
            title=title,
            artifact_ref=artifact_ref,
            targets={str(target["target_id"]): dict(target) for target in targets},
            visible_text_digest=visible_text_digest,
            source_scope=dict(source_scope or {}),
            page_risk_flags=[str(item) for item in page_risk_flags or []],
        )
        self._observations[observation_id] = observation
        return observation

    def get(self, observation_id: str) -> BrowserObservation | None:
        return self._observations.get(observation_id)

    def fill_value(
        self,
        observation_id: str,
        target: dict[str, object],
        value: str,
    ) -> None:
        observation = self._observations[observation_id]
        name = str(target.get("name", ""))
        if name:
            observation.filled_values[name] = value


def create_browser_observe_tool(
    registry: SourceRegistry,
    artifacts: ArtifactStore,
    *,
    state: BrowserActionState | None = None,
    browser_session: BrowserSession | None = None,
    allowed_scopes: list[BrowserUrlScope] | None = None,
    timeout_ms: int = 30_000,
) -> ToolDefinition:
    action_state = state or BrowserActionState()
    session = browser_session or DefaultBrowserSession()
    resolved_allowed_scopes = list(allowed_scopes or [])

    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        url = str(call.arguments["url"]).strip()
        topic = str(call.arguments.get("topic", ""))
        initial_scope = _browser_scope_for_url(
            registry=registry,
            url=url,
            allowed_scopes=resolved_allowed_scopes,
        )
        if initial_scope is None:
            return ToolResult(
                call.id,
                call.name,
                f"outside browser URL scope: {url}",
                {"url": url, "blocked_by": "browser_url_scope"},
                is_error=True,
            )
        try:
            snapshot = await session.observe(url, timeout_ms)
        except Exception as exc:
            return ToolResult(
                call.id,
                call.name,
                f"browser observe failed: {exc}",
                {"url": url},
                is_error=True,
            )
        source_scope = _browser_scope_for_url(
            registry=registry,
            url=snapshot.url,
            allowed_scopes=resolved_allowed_scopes,
        )
        if source_scope is None:
            return ToolResult(
                call.id,
                call.name,
                f"outside browser URL scope: {snapshot.url}",
                {"url": snapshot.url, "blocked_by": "browser_url_scope"},
                is_error=True,
            )
        scan = _scan_page(snapshot.html, snapshot.url)
        artifact_html, artifact_sanitized = _sanitize_browser_html_for_artifact(
            snapshot.html
        )
        artifact_ref = artifacts.put(
            artifact_html,
            kind="html",
            meta={
                "url": url,
                "final_url": snapshot.url,
                "tool": "browser_observe",
                "topic": topic,
                "sanitized_sensitive_fields": artifact_sanitized,
                "content_type": "text/html; charset=utf-8",
            },
        )
        observation = action_state.remember(
            page_url=snapshot.url,
            title=scan.title,
            artifact_ref=artifact_ref,
            targets=scan.targets,
            visible_text_digest=_excerpt(scan.visible_text, 1200),
            source_scope=_scope_details(source_scope),
            page_risk_flags=scan.page_risk_flags,
        )
        details = {
            "observation_ref": observation.observation_id,
            "observation_id": observation.observation_id,
            "url": snapshot.url,
            "final_url": snapshot.url,
            "title": scan.title,
            "artifact_ref": artifact_ref,
            "targets": scan.targets,
            "top_targets": scan.targets[:12],
            "visible_text": _excerpt(scan.visible_text, 1200),
            "visible_text_digest": _excerpt(scan.visible_text, 1200),
            "article_candidates": scan.article_candidates,
            "listing_candidates": scan.listing_candidates,
            "forms": scan.forms,
            "buttons": scan.buttons,
            "download_targets": scan.download_targets,
            "pagination_targets": scan.pagination_targets,
            "network_api_candidates": scan.network_api_candidates,
            "access_status": scan.access_status,
            "page_risk_flags": scan.page_risk_flags,
            "suggested_interaction_modes": scan.suggested_interaction_modes,
            "source_scope": _scope_details(source_scope),
            "open_source_lead_ids": [],
        }
        return ToolResult(
            call.id,
            call.name,
            (
                f"{UNTRUSTED_NOTICE}\n"
                f"browser observe captured {len(scan.targets)} controlled targets"
            ),
            details,
            domain_proposals=[],
            trace_proposals=[
                DomainTraceProposal(
                    event_type="browser_observed",
                    target_type="BrowserObservation",
                    target_id=observation.observation_id,
                    payload_summary=f"browser observed {snapshot.url}",
                    input_refs=[url],
                    output_refs=[observation.observation_id, artifact_ref],
                    payload={
                        "target_count": len(scan.targets),
                        "title": scan.title,
                        "source_scope": _scope_details(source_scope),
                        "open_source_lead_ids": [],
                    },
                ),
            ],
        )

    return ToolDefinition(
        name="browser_observe",
        description=(
            "Observe a whitelisted page through a controlled browser session and "
            "return only safe link/form/download targets."
        ),
        parameters_schema={
            "type": "object",
            "required": ["url", "topic"],
            "properties": {
                "url": {"type": "string"},
                "topic": {"type": "string"},
            },
            "additionalProperties": False,
        },
        execute=execute,
        execution_mode="sequential",
        timeout_ms=timeout_ms + 5_000,
        prompt_guidelines=UNTRUSTED_NOTICE,
    )


def create_browser_action_tool(
    registry: SourceRegistry,
    artifacts: ArtifactStore,
    *,
    state: BrowserActionState | None = None,
    browser_session: BrowserSession | None = None,
    timeout_ms: int = 30_000,
) -> ToolDefinition:
    action_state = state or BrowserActionState()
    session = browser_session or DefaultBrowserSession()

    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        observation_id = str(call.arguments["observation_id"])
        target_id = str(call.arguments["target_id"])
        action = str(call.arguments["action"])
        value = str(call.arguments.get("value", ""))
        if action not in ALLOWED_BROWSER_ACTIONS:
            return ToolResult(
                call.id,
                call.name,
                f"unsupported browser action: {action}",
                {"action": action, "allowed_actions": sorted(ALLOWED_BROWSER_ACTIONS)},
                is_error=True,
            )
        observation = action_state.get(observation_id)
        if observation is None:
            return ToolResult(
                call.id,
                call.name,
                f"unknown browser observation_id: {observation_id}",
                {"observation_id": observation_id},
                is_error=True,
            )
        target = observation.targets.get(target_id)
        if target is None:
            return ToolResult(
                call.id,
                call.name,
                f"unknown browser target_id: {target_id}",
                {"observation_id": observation_id, "target_id": target_id},
                is_error=True,
            )
        allowed = set(target.get("allowed_actions", []) or [])
        if action not in allowed:
            return ToolResult(
                call.id,
                call.name,
                f"browser action {action} is not allowed for target {target_id}",
                {
                    "target_id": target_id,
                    "action": action,
                    "allowed_actions": sorted(allowed),
                },
                is_error=True,
            )
        if action == "fill_input":
            action_state.fill_value(observation_id, target, value)
        session_target = {
            **target,
            "page_url": observation.page_url,
            "filled_values": dict(observation.filled_values),
        }
        try:
            snapshot = await session.action(
                action=action,
                target=session_target,
                value=value,
                timeout_ms=timeout_ms,
            )
        except Exception as exc:
            return ToolResult(
                call.id,
                call.name,
                f"browser action failed: {exc}",
                {"observation_id": observation_id, "target_id": target_id},
                is_error=True,
            )
        blocked_url = _first_outside_whitelist(registry, snapshot.url, snapshot.download_url)
        if blocked_url:
            return ToolResult(
                call.id,
                call.name,
                WHITELIST_BLOCK_MESSAGE,
                {"url": blocked_url, "blocked_by": "source_whitelist"},
                is_error=True,
            )
        title_after, targets_after, visible_after = _extract_targets(
            snapshot.html,
            snapshot.url,
        )
        artifact_html, artifact_sanitized = _sanitize_browser_html_for_artifact(
            snapshot.html
        )
        artifact_ref = artifacts.put(
            artifact_html,
            kind="html",
            meta={
                "url": observation.page_url,
                "final_url": snapshot.url,
                "tool": "browser_action",
                "action": action,
                "target_id": target_id,
                "sanitized_sensitive_fields": artifact_sanitized,
                "content_type": "text/html; charset=utf-8",
            },
        )
        new_observation = action_state.remember(
            page_url=snapshot.url,
            title=title_after,
            artifact_ref=artifact_ref,
            targets=targets_after,
            page_risk_flags=[],
        )
        details = {
            "observation_id": observation_id,
            "new_observation_id": new_observation.observation_id,
            "target_id": target_id,
            "action": action,
            "url_before": observation.page_url,
            "final_url": snapshot.url,
            "url_changed": snapshot.url != observation.page_url,
            "title_before": observation.title,
            "title_after": title_after,
            "title_changed": title_after != observation.title,
            "artifact_ref": artifact_ref,
            "new_text": _excerpt(_new_text(observation.page_url, visible_after), 1200),
            "download_url": snapshot.download_url,
            "targets": targets_after,
        }
        return ToolResult(
            call.id,
            call.name,
            f"{UNTRUSTED_NOTICE}\nbrowser action {action} completed",
            details,
            trace_proposals=[
                DomainTraceProposal(
                    event_type="browser_action_completed",
                    target_type="BrowserObservation",
                    target_id=new_observation.observation_id,
                    payload_summary=f"browser action {action} on {target_id}",
                    input_refs=[observation_id, target_id],
                    output_refs=[new_observation.observation_id, artifact_ref],
                    payload={
                        "action": action,
                        "url_changed": details["url_changed"],
                        "download_url": snapshot.download_url,
                    },
                )
            ],
        )

    return ToolDefinition(
        name="browser_action",
        description=(
            "Run a controlled browser action against a target_id returned by "
            "browser_observe. Does not accept JS, CSS selectors, or arbitrary URLs."
        ),
        parameters_schema={
            "type": "object",
            "required": ["observation_id", "target_id", "action"],
            "properties": {
                "observation_id": {"type": "string"},
                "target_id": {"type": "string"},
                "action": {
                    "type": "string",
                    "enum": sorted(ALLOWED_BROWSER_ACTIONS),
                },
                "value": {"type": "string"},
            },
            "additionalProperties": False,
        },
        execute=execute,
        execution_mode="sequential",
        timeout_ms=timeout_ms + 5_000,
        prompt_guidelines=UNTRUSTED_NOTICE,
    )


def create_browser_execute_tool(
    registry: SourceRegistry,
    artifacts: ArtifactStore,
    *,
    state: BrowserActionState | None = None,
    browser_session: BrowserSession | None = None,
    allowed_scopes: list[BrowserUrlScope] | None = None,
    domain_store: DomainStore | None = None,
    run_id: str = "",
    timeout_ms: int = 30_000,
) -> ToolDefinition:
    action_state = state or BrowserActionState()
    session = browser_session or DefaultBrowserSession()
    resolved_allowed_scopes = list(allowed_scopes or [])

    async def execute(call: ToolCall, ctx: ToolExecutionContext) -> ToolResult:
        observation_id = str(call.arguments["observation_ref"])
        intent = str(call.arguments.get("intent", "")).strip()
        mode = str(call.arguments.get("mode", "target_action"))
        if not intent:
            return ToolResult(
                call.id,
                call.name,
                "browser_execute intent is required",
                {},
                is_error=True,
            )
        if mode == "javascript":
            javascript = dict(call.arguments.get("javascript", {}) or {})
            script = str(javascript.get("script", ""))
            expected_result = str(javascript.get("expected_result", ""))
            why_standard_actions_are_insufficient = str(
                javascript.get("why_standard_actions_are_insufficient", "")
            ).strip()
            result_sink = str(javascript.get("result_sink", "")).strip()
            fallback = str(javascript.get("fallback", "")).strip()
            allow_network_probe = bool(javascript.get("allow_network_probe", False))
            max_return_chars = int(call.arguments.get("max_return_chars", 4000))
            policy_error = _validate_javascript_policy(
                script=script,
                expected_result=expected_result,
                why_standard_actions_are_insufficient=(
                    why_standard_actions_are_insufficient
                ),
                result_sink=result_sink,
                fallback=fallback,
            )
            if policy_error:
                return ToolResult(
                    call.id,
                    call.name,
                    policy_error,
                    {"status": "blocked", "blocked_by": "browser_javascript_safety_policy"},
                    is_error=True,
                )
            observation = action_state.get(observation_id)
            if observation is None:
                return ToolResult(
                    call.id,
                    call.name,
                    f"unknown browser observation_ref: {observation_id}",
                    {"observation_ref": observation_id},
                    is_error=True,
                )
            if _blocks_javascript(observation.page_risk_flags):
                return ToolResult(
                    call.id,
                    call.name,
                    "browser javascript blocked on page with sensitive fields or access-control signals",
                    {
                        "status": "blocked",
                        "blocked_by": "sensitive_page",
                        "page_risk_flags": list(observation.page_risk_flags),
                    },
                    is_error=True,
                )
            return await _execute_javascript(
                call=call,
                artifacts=artifacts,
                action_state=action_state,
                session=session,
                registry=registry,
                observation=observation,
                observation_ref=observation_id,
                intent=intent,
                script=script,
                expected_result=expected_result,
                why_standard_actions_are_insufficient=(
                    why_standard_actions_are_insufficient
                ),
                result_sink=result_sink,
                fallback=fallback,
                allow_network_probe=allow_network_probe,
                safety_policy=_javascript_safety_policy(
                    page_url=observation.page_url,
                    allow_network_probe=allow_network_probe,
                    max_return_chars=max_return_chars,
                ),
                allowed_scopes=resolved_allowed_scopes,
                domain_store=domain_store,
                run_id=run_id or ctx.run_id,
                timeout_ms=int(call.arguments.get("max_wait_ms", timeout_ms)),
                max_return_chars=max_return_chars,
            )
        if mode != "target_action":
            return ToolResult(
                call.id,
                call.name,
                f"unsupported browser_execute mode: {mode}",
                {"mode": mode},
                is_error=True,
            )
        observation = action_state.get(observation_id)
        if observation is None:
            return ToolResult(
                call.id,
                call.name,
                f"unknown browser observation_ref: {observation_id}",
                {"observation_ref": observation_id},
                is_error=True,
            )
        target_action = dict(call.arguments.get("target_action", {}) or {})
        action = str(target_action.get("action", ""))
        target_id = str(target_action.get("target_id", ""))
        value = str(target_action.get("value", ""))
        if action not in ALLOWED_BROWSER_ACTIONS:
            return ToolResult(
                call.id,
                call.name,
                f"unsupported browser action: {action}",
                {"action": action, "allowed_actions": sorted(ALLOWED_BROWSER_ACTIONS)},
                is_error=True,
            )
        target = observation.targets.get(target_id)
        if target is None:
            return ToolResult(
                call.id,
                call.name,
                f"unknown browser target_id: {target_id}",
                {"observation_ref": observation_id, "target_id": target_id},
                is_error=True,
            )
        allowed = set(target.get("allowed_actions", []) or [])
        if action not in allowed:
            return ToolResult(
                call.id,
                call.name,
                f"browser action {action} is not allowed for target {target_id}",
                {
                    "target_id": target_id,
                    "action": action,
                    "allowed_actions": sorted(allowed),
                },
                is_error=True,
            )
        if action == "capture_current_document":
            return _capture_current_document(
                call=call,
                observation=observation,
                target_id=target_id,
                intent=intent,
            )
        blocked_target_url = _first_outside_browser_scope(
            registry,
            resolved_allowed_scopes,
            *_target_action_scope_urls(
                action=action,
                target=target,
                observation=observation,
            ),
        )
        if blocked_target_url:
            return ToolResult(
                call.id,
                call.name,
                f"outside browser URL scope: {blocked_target_url}",
                {"url": blocked_target_url, "blocked_by": "browser_url_scope"},
                is_error=True,
            )
        if action == "fill_input":
            action_state.fill_value(observation_id, target, value)
        session_target = {
            **target,
            "page_url": observation.page_url,
            "filled_values": dict(observation.filled_values),
        }
        try:
            snapshot = await session.action(
                action=action,
                target=session_target,
                value=value,
                timeout_ms=timeout_ms,
            )
        except Exception as exc:
            return ToolResult(
                call.id,
                call.name,
                f"browser_execute target_action failed: {exc}",
                {"observation_ref": observation_id, "target_id": target_id},
                is_error=True,
            )
        blocked_url = _first_outside_browser_scope(
            registry,
            resolved_allowed_scopes,
            snapshot.url,
            snapshot.download_url,
        )
        if blocked_url:
            return ToolResult(
                call.id,
                call.name,
                f"outside browser URL scope: {blocked_url}",
                {"url": blocked_url, "blocked_by": "browser_url_scope"},
                is_error=True,
            )
        source_scope = _browser_scope_for_url(
            registry=registry,
            url=snapshot.url,
            allowed_scopes=resolved_allowed_scopes,
        )
        scan = _scan_page(snapshot.html, snapshot.url)
        artifact_html, artifact_sanitized = _sanitize_browser_html_for_artifact(
            snapshot.html
        )
        artifact_ref = artifacts.put(
            artifact_html,
            kind="html",
            meta={
                "url": observation.page_url,
                "final_url": snapshot.url,
                "tool": "browser_execute",
                "mode": "target_action",
                "action": action,
                "target_id": target_id,
                "intent": intent,
                "sanitized_sensitive_fields": artifact_sanitized,
                "content_type": "text/html; charset=utf-8",
            },
        )
        new_observation = action_state.remember(
            page_url=snapshot.url,
            title=scan.title,
            artifact_ref=artifact_ref,
            targets=scan.targets,
            visible_text_digest=_excerpt(scan.visible_text, 1200),
            source_scope=_scope_details(source_scope) if source_scope else observation.source_scope,
            page_risk_flags=scan.page_risk_flags,
        )
        details = {
            "status": "success",
            "execution_mode": "target_action",
            "observation_ref": observation_id,
            "next_observation_ref": new_observation.observation_id,
            "target_id": target_id,
            "action": action,
            "intent": intent,
            "url_before": observation.page_url,
            "url_after": snapshot.url,
            "final_url": snapshot.url,
            "url_changed": snapshot.url != observation.page_url,
            "title_before": observation.title,
            "title_after": scan.title,
            "title_changed": scan.title != observation.title,
            "artifact_ref": artifact_ref,
            "delta_summary": _excerpt(scan.visible_text, 1200),
            "top_changed_region": _excerpt(scan.visible_text, 600),
            "document_candidate_refs": [],
            "download_targets": scan.download_targets,
            "download_url": snapshot.download_url,
            "targets": scan.targets,
            "suggested_next_actions": _suggested_next_actions(scan),
            "return_artifact_ref": "",
            "source_scope": _scope_details(source_scope) if source_scope else observation.source_scope,
        }
        return ToolResult(
            call.id,
            call.name,
            f"{UNTRUSTED_NOTICE}\nbrowser_execute {action} completed",
            details,
            trace_proposals=[
                DomainTraceProposal(
                    event_type="browser_execute_completed",
                    target_type="BrowserObservation",
                    target_id=new_observation.observation_id,
                    payload_summary=f"browser_execute {action} on {target_id}",
                    input_refs=[observation_id, target_id],
                    output_refs=[new_observation.observation_id, artifact_ref],
                    payload={
                        "mode": "target_action",
                        "action": action,
                        "intent": intent,
                        "url_changed": details["url_changed"],
                        "download_url": snapshot.download_url,
                        "source_scope": details["source_scope"],
                    },
                )
            ],
        )

    return ToolDefinition(
        name="browser_execute",
        description=(
            "Execute a controlled browser target action returned by browser_observe "
            "or auditable JavaScript tied to an observation_ref. JavaScript output "
            "is candidate/diagnosis/recipe material only, not EvidenceCard input."
        ),
        parameters_schema={
            "type": "object",
            "required": ["observation_ref", "intent", "mode"],
            "properties": {
                "observation_ref": {"type": "string"},
                "intent": {"type": "string"},
                "mode": {"type": "string", "enum": ["target_action", "javascript"]},
                "target_action": {
                    "type": "object",
                    "required": ["action", "target_id"],
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": sorted(ALLOWED_BROWSER_ACTIONS),
                        },
                        "target_id": {"type": "string"},
                        "value": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
                "javascript": {
                    "type": "object",
                    "required": [
                        "script",
                        "expected_result",
                        "why_standard_actions_are_insufficient",
                        "result_sink",
                        "fallback",
                    ],
                    "properties": {
                        "script": {"type": "string"},
                        "expected_result": {"type": "string"},
                        "why_standard_actions_are_insufficient": {"type": "string"},
                        "result_sink": {"type": "string"},
                        "fallback": {"type": "string"},
                        "allow_network_probe": {"type": "boolean"},
                    },
                    "additionalProperties": False,
                },
                "max_wait_ms": {"type": "integer"},
                "max_return_chars": {"type": "integer"},
            },
            "additionalProperties": False,
        },
        execute=execute,
        execution_mode="sequential",
        timeout_ms=timeout_ms + 5_000,
        prompt_guidelines=UNTRUSTED_NOTICE,
    )


class DefaultBrowserSession:
    async def observe(self, url: str, timeout_ms: int) -> BrowserPageSnapshot:
        from knowledgegraph.demand_discovery.tools.browser_bridge import (
            observe_with_browser_session,
        )

        snapshot = await observe_with_browser_session(url, timeout_ms=timeout_ms)
        return BrowserPageSnapshot(
            url=str(snapshot["url"]),
            html=str(snapshot["html"]),
            download_url=str(snapshot.get("download_url", "")),
        )

    async def execute_javascript(
        self,
        *,
        script: str,
        timeout_ms: int,
        max_return_chars: int,
        allow_network_probe: bool,
        safety_policy: dict[str, object],
    ) -> dict[str, object]:
        from knowledgegraph.demand_discovery.tools.browser_bridge import (
            execute_javascript_with_browser_session,
        )

        return await execute_javascript_with_browser_session(
            script=script,
            timeout_ms=timeout_ms,
            max_return_chars=max_return_chars,
            allow_network_probe=allow_network_probe,
            safety_policy=safety_policy,
        )

    async def action(
        self,
        *,
        action: str,
        target: dict[str, object],
        value: str,
        timeout_ms: int,
    ) -> BrowserPageSnapshot:
        from knowledgegraph.demand_discovery.tools.browser_bridge import (
            action_with_browser_session,
        )

        snapshot = await action_with_browser_session(
            action=action,
            target=target,
            value=value,
            timeout_ms=timeout_ms,
        )
        return BrowserPageSnapshot(
            url=str(snapshot["url"]),
            html=str(snapshot["html"]),
            download_url=str(snapshot.get("download_url", "")),
        )


def _extract_targets(
    html: str,
    page_url: str,
) -> tuple[str, list[dict[str, object]], str]:
    soup = BeautifulSoup(html or "", "html.parser")
    title = _title(soup)
    visible_text = _clean_text(soup.get_text(" ", strip=True))
    targets: list[dict[str, object]] = []
    targets.extend(_form_targets(soup, page_url))
    targets.extend(_link_targets(soup, page_url))
    return title, targets, visible_text


def _scan_page(html: str, page_url: str) -> BrowserPageScan:
    soup = BeautifulSoup(html or "", "html.parser")
    title = _title(soup)
    visible_text = _clean_text(soup.get_text(" ", strip=True))
    form_targets = _form_targets(soup, page_url)
    link_targets = _link_targets(soup, page_url)
    risk_flags = _page_risk_flags(visible_text, [*form_targets, *link_targets], soup)
    current_document_target = _current_document_target(
        page_url,
        title,
        allow_capture=not _blocks_document_capture(risk_flags),
    )
    targets = [current_document_target, *form_targets, *link_targets]
    article_candidates = [
        _candidate_from_target(target, "article")
        for target in link_targets
        if _looks_like_article(str(target.get("url", "")), str(target.get("text", "")))
    ][:10]
    listing_candidates = _listing_candidates(soup, page_url, link_targets)[:10]
    download_targets = [
        target for target in link_targets if target.get("kind") == "download_link"
    ][:10]
    pagination_targets = [
        target for target in link_targets if target.get("kind") == "next_page"
    ][:10]
    forms = [target for target in form_targets if target.get("kind") == "form"][:10]
    buttons = _button_targets(soup, page_url)[:10]
    api_candidates = _network_api_candidates_from_html(soup, page_url)[:10]
    modes = ["target_action"]
    if (api_candidates or _has_dynamic_script(soup)) and not _blocks_javascript(
        risk_flags
    ):
        modes.append("javascript")
    return BrowserPageScan(
        title=title,
        visible_text=visible_text,
        targets=targets[:30],
        article_candidates=article_candidates,
        listing_candidates=listing_candidates,
        forms=forms,
        buttons=buttons,
        download_targets=download_targets,
        pagination_targets=pagination_targets,
        network_api_candidates=api_candidates,
        access_status=_access_status(visible_text),
        page_risk_flags=risk_flags,
        suggested_interaction_modes=modes,
    )


def _browser_scope_for_url(
    *,
    registry: SourceRegistry,
    url: str,
    allowed_scopes: list[BrowserUrlScope],
) -> BrowserUrlScope | None:
    entry = registry.match(url)
    if entry is not None:
        return BrowserUrlScope(
            scope_type="whitelist",
            source_name=entry.source_name,
            url_prefixes=list(entry.entry_urls),
            hosts=list(entry.hosts),
            scope_granularity="host",
        )
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None
    for scope in allowed_scopes:
        if any(url.startswith(prefix) for prefix in scope.url_prefixes):
            return scope
        if scope.scope_granularity == "host" and parsed.hostname in set(scope.hosts):
            return scope
    return None


def _scope_details(scope: BrowserUrlScope) -> dict[str, object]:
    return {
        "scope_type": scope.scope_type,
        "source_name": scope.source_name,
        "plan_id": scope.plan_id,
        "lead_id": scope.lead_id,
        "scope_granularity": scope.scope_granularity,
    }


def _javascript_safety_policy(
    *,
    page_url: str,
    allow_network_probe: bool,
    max_return_chars: int,
) -> dict[str, object]:
    parsed = urlparse(page_url)
    return {
        "allowed_origin": f"{parsed.scheme}://{parsed.netloc}",
        "allowed_host": parsed.hostname or "",
        "allow_network_probe": allow_network_probe,
        "allowed_methods": ["GET", "HEAD"],
        "force_credentials": "omit",
        "max_requests": 5 if allow_network_probe else 0,
        "max_return_chars": max_return_chars,
        "block_storage": True,
        "block_cookie": True,
        "block_xhr": True,
    }


def _validate_javascript_policy(
    *,
    script: str,
    expected_result: str,
    why_standard_actions_are_insufficient: str,
    result_sink: str,
    fallback: str,
) -> str:
    if not expected_result.strip():
        return "expected_result is required"
    if not why_standard_actions_are_insufficient.strip():
        return "why_standard_actions_are_insufficient is required"
    if not result_sink.strip():
        return "result_sink is required"
    if not fallback.strip():
        return "fallback is required"
    if len(script) > MAX_BROWSER_JS_CHARS:
        return f"script exceeds max length: {MAX_BROWSER_JS_CHARS}"
    for pattern in PREFLIGHT_BLOCKED_JS_PATTERNS:
        if re.search(pattern, script, flags=re.IGNORECASE):
            return "blocked by browser javascript safety policy"
    return ""


async def _execute_javascript(
    *,
    call: ToolCall,
    artifacts: ArtifactStore,
    action_state: BrowserActionState,
    session: BrowserSession,
    registry: SourceRegistry,
    observation: BrowserObservation,
    observation_ref: str,
    intent: str,
    script: str,
    expected_result: str,
    why_standard_actions_are_insufficient: str,
    result_sink: str,
    fallback: str,
    allow_network_probe: bool,
    safety_policy: dict[str, object],
    allowed_scopes: list[BrowserUrlScope],
    domain_store: DomainStore | None,
    run_id: str,
    timeout_ms: int,
    max_return_chars: int,
) -> ToolResult:
    script_hash = f"sha256:{hashlib.sha256(script.encode('utf-8')).hexdigest()}"
    script_ref = artifacts.put(
        script,
        kind="js",
        meta={
            "tool": "browser_execute",
            "mode": "javascript",
            "script_hash": script_hash,
            "intent": intent,
            "expected_result": expected_result,
            "why_standard_actions_are_insufficient": why_standard_actions_are_insufficient,
            "result_sink": result_sink,
            "fallback": fallback,
            "content_type": "application/javascript; charset=utf-8",
        },
    )
    try:
        raw = await session.execute_javascript(
            script=script,
            timeout_ms=timeout_ms,
            max_return_chars=max_return_chars,
            allow_network_probe=allow_network_probe,
            safety_policy=safety_policy,
        )
    except Exception as exc:
        return ToolResult(
            call.id,
            call.name,
            f"browser javascript failed: {exc}",
            {
                "status": "failed",
                "execution_mode": "javascript",
                "script_hash": script_hash,
                "script_ref": script_ref,
                "intent": intent,
                "expected_result": expected_result,
                "why_standard_actions_are_insufficient": why_standard_actions_are_insufficient,
                "result_sink": result_sink,
                "fallback": fallback,
                "error": {"name": exc.__class__.__name__, "message": str(exc)},
                "delta_summary": "页面无明显文本变化",
            },
            is_error=True,
        )

    network_delta = list(raw.get("network_delta", []) or [])
    outside_url = _outside_browser_scope_from_js_delta(
        registry=registry,
        allowed_scopes=allowed_scopes,
        network_delta=network_delta,
    )
    if outside_url:
        return ToolResult(
            call.id,
            call.name,
            f"outside browser URL scope: {outside_url}",
            {"url": outside_url, "blocked_by": "browser_url_scope"},
            is_error=True,
        )

    status = str(raw.get("status", "success"))
    url_after = str(raw.get("url_after", observation.page_url) or observation.page_url)
    if _browser_scope_for_url(
        registry=registry,
        url=url_after,
        allowed_scopes=allowed_scopes,
    ) is None:
        return ToolResult(
            call.id,
            call.name,
            f"outside browser URL scope: {url_after}",
            {"url": url_after, "blocked_by": "browser_url_scope"},
            is_error=True,
        )
    result_payload = raw.get("result")
    result_text = _json_preview(result_payload)
    return_artifact_ref = artifacts.put(
        result_text,
        kind="json",
        meta={
            "tool": "browser_execute",
            "mode": "javascript",
            "script_hash": script_hash,
            "intent": intent,
            "expected_result": expected_result,
            "why_standard_actions_are_insufficient": why_standard_actions_are_insufficient,
            "result_sink": result_sink,
            "fallback": fallback,
            "content_type": "application/json; charset=utf-8",
        },
    )
    title_after = str(raw.get("title_after", observation.title) or observation.title)
    html_after = str(raw.get("html_after", "") or "")
    if html_after:
        scan = _scan_page(html_after, url_after)
    else:
        scan = BrowserPageScan(
            title=title_after,
            visible_text=observation.visible_text_digest,
            targets=[],
            article_candidates=[],
            listing_candidates=[],
            forms=[],
            buttons=[],
            download_targets=[],
            pagination_targets=[],
            network_api_candidates=[],
            access_status="unknown",
            page_risk_flags=[],
            suggested_interaction_modes=["target_action"],
        )
    document_candidate_refs = _document_candidates_from_js_result(result_payload)
    details = {
        "status": status,
        "execution_mode": "javascript",
        "observation_ref": observation_ref,
        "next_observation_ref": observation_ref,
        "intent": intent,
        "expected_result": expected_result,
        "why_standard_actions_are_insufficient": why_standard_actions_are_insufficient,
        "result_sink": result_sink,
        "fallback": fallback,
        "script_hash": script_hash,
        "script_ref": script_ref,
        "return_preview": _excerpt(result_text, max_return_chars),
        "return_artifact_ref": return_artifact_ref,
        "url_before": observation.page_url,
        "url_after": url_after,
        "final_url": url_after,
        "url_changed": url_after != observation.page_url,
        "title_before": observation.title,
        "title_after": title_after or scan.title,
        "title_changed": (title_after or scan.title) != observation.title,
        "new_tabs": [],
        "reload": False,
        "delta_summary": _delta_summary(observation.visible_text_digest, scan.visible_text),
        "top_changed_region": _excerpt(scan.visible_text, 600),
        "transient_text": [],
        "network_delta": network_delta,
        "document_candidate_refs": document_candidate_refs,
        "download_targets": scan.download_targets,
        "suggested_next_actions": ["browser_observe"],
        "html_after_saved": False,
        "source_scope": dict(observation.source_scope),
    }
    recipe = (
        _recipe_from_js_success(
            run_id=run_id,
            observation=observation,
            intent=intent,
            script_hash=script_hash,
            script_ref=script_ref,
            return_artifact_ref=return_artifact_ref,
            network_delta=network_delta,
        )
        if status == "success"
        else None
    )
    trace_output_refs = [script_ref, return_artifact_ref]
    if recipe is not None:
        details["browser_recipe_draft_id"] = recipe.recipe_id
        trace_output_refs.append(recipe.recipe_id)
        if domain_store is not None:
            domain_store.upsert_browser_recipe_draft(recipe)
    if status != "success":
        details["error"] = dict(raw.get("error", {}) or {})
        return ToolResult(
            call.id,
            call.name,
            "browser javascript failed",
            details,
            is_error=True,
            trace_proposals=[
                DomainTraceProposal(
                    event_type="browser_javascript_failed",
                    target_type="BrowserObservation",
                    target_id=observation_ref,
                    payload_summary=f"browser javascript failed {script_hash}",
                    input_refs=[observation_ref],
                    output_refs=[script_ref, return_artifact_ref],
                    payload={
                        "script_hash": script_hash,
                        "script_ref": script_ref,
                        "intent": intent,
                        "expected_result": expected_result,
                        "why_standard_actions_are_insufficient": (
                            why_standard_actions_are_insufficient
                        ),
                        "result_sink": result_sink,
                        "fallback": fallback,
                        "error": details["error"],
                    },
                )
            ],
        )
    return ToolResult(
        call.id,
        call.name,
        f"{UNTRUSTED_NOTICE}\nbrowser javascript completed",
        details,
        trace_proposals=[
            DomainTraceProposal(
                event_type="browser_javascript_completed",
                target_type="BrowserObservation",
                target_id=observation_ref,
                payload_summary=f"browser javascript completed {script_hash}",
                input_refs=[observation_ref],
                output_refs=trace_output_refs,
                payload={
                    "script_hash": script_hash,
                    "script_ref": script_ref,
                    "intent": intent,
                    "expected_result": expected_result,
                    "why_standard_actions_are_insufficient": (
                        why_standard_actions_are_insufficient
                    ),
                    "result_sink": result_sink,
                    "fallback": fallback,
                    "network_delta": network_delta,
                    "document_candidate_refs": details["document_candidate_refs"],
                    "browser_recipe_draft_id": details.get("browser_recipe_draft_id", ""),
                },
            )
        ],
    )


def _capture_current_document(
    *,
    call: ToolCall,
    observation: BrowserObservation,
    target_id: str,
    intent: str,
) -> ToolResult:
    if _blocks_document_capture(observation.page_risk_flags):
        return ToolResult(
            call.id,
            call.name,
            "browser capture_current_document blocked on page with sensitive fields or access-control signals",
            {
                "status": "blocked",
                "blocked_by": "sensitive_page",
                "page_risk_flags": list(observation.page_risk_flags),
            },
            is_error=True,
        )
    details = {
        "status": "success",
        "execution_mode": "target_action",
        "observation_ref": observation.observation_id,
        "next_observation_ref": observation.observation_id,
        "target_id": target_id,
        "action": "capture_current_document",
        "intent": intent,
        "url_before": observation.page_url,
        "url_after": observation.page_url,
        "final_url": observation.page_url,
        "url_changed": False,
        "title_before": observation.title,
        "title_after": observation.title,
        "title_changed": False,
        "artifact_ref": observation.artifact_ref,
        "delta_summary": observation.visible_text_digest,
        "top_changed_region": observation.visible_text_digest,
        "document_candidate_refs": [observation.artifact_ref],
        "download_targets": [],
        "download_url": "",
        "targets": list(observation.targets.values()),
        "suggested_next_actions": ["read_document"],
        "return_artifact_ref": "",
        "source_scope": dict(observation.source_scope),
    }
    return ToolResult(
        call.id,
        call.name,
        f"{UNTRUSTED_NOTICE}\nbrowser_execute capture_current_document completed",
        details,
        trace_proposals=[
            DomainTraceProposal(
                event_type="browser_current_document_captured",
                target_type="BrowserObservation",
                target_id=observation.observation_id,
                payload_summary=f"browser captured current document {observation.page_url}",
                input_refs=[observation.observation_id, target_id],
                output_refs=[observation.artifact_ref],
                payload={
                    "intent": intent,
                    "source_scope": dict(observation.source_scope),
                },
            )
        ],
    )


def _current_document_target(
    page_url: str,
    title: str,
    *,
    allow_capture: bool = True,
) -> dict[str, object]:
    return {
        "target_id": _target_id(page_url, "current_document", 0, 0, "当前页面"),
        "kind": "current_document",
        "label": "当前页面",
        "text": "当前页面",
        "title": title,
        "page_url": page_url,
        "allowed_actions": ["capture_current_document"] if allow_capture else [],
    }


def _candidate_from_target(
    target: dict[str, object],
    candidate_type: str,
) -> dict[str, object]:
    return {
        "candidate_type": candidate_type,
        "target_id": str(target.get("target_id", "")),
        "title": str(target.get("text", "") or target.get("label", "")),
        "url": str(target.get("url", "")),
    }


def _listing_candidates(
    soup: BeautifulSoup,
    page_url: str,
    link_targets: list[dict[str, object]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, tag in enumerate(soup.find_all(["section", "div", "main"]), start=1):
        if not isinstance(tag, Tag):
            continue
        marker = " ".join(
            [
                str(tag.get("id", "") or ""),
                " ".join(str(item) for item in tag.get("class", []) or []),
            ]
        ).lower()
        links = tag.find_all("a")
        if len(links) >= 2 and (
            "list" in marker
            or "result" in marker
            or "search" in marker
            or tag.name == "main"
        ):
            rows.append(
                {
                    "candidate_type": "listing",
                    "target_id": _target_id(page_url, "listing", index, 0, marker),
                    "title": _excerpt(_clean_text(tag.get_text(" ", strip=True)), 120),
                    "url": page_url,
                    "link_count": len(links),
                }
            )
    if not rows and len(link_targets) >= 2:
        rows.append(
            {
                "candidate_type": "listing",
                "target_id": _target_id(page_url, "listing", 0, 0, "links"),
                "title": "链接列表",
                "url": page_url,
                "link_count": len(link_targets),
            }
        )
    return rows


def _button_targets(soup: BeautifulSoup, page_url: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, tag in enumerate(soup.find_all("button"), start=1):
        if not isinstance(tag, Tag):
            continue
        text = _clean_text(tag.get_text(" ", strip=True)) or f"button-{index}"
        rows.append(
            {
                "target_id": _target_id(page_url, "button", index, 0, text),
                "kind": "button",
                "label": text,
                "page_url": page_url,
                "allowed_actions": ["activate_button"],
            }
        )
    return rows


def _network_api_candidates_from_html(
    soup: BeautifulSoup,
    page_url: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    page_host = urlparse(page_url).hostname or ""
    script_text = "\n".join(script.get_text(" ") for script in soup.find_all("script"))
    for match in re.finditer(r"fetch\(\s*['\"]([^'\"]+)['\"]", script_text):
        raw_url = match.group(1)
        absolute = urljoin(page_url, raw_url)
        parsed = urlparse(absolute)
        if parsed.hostname != page_host:
            continue
        context = script_text[match.start() : match.start() + 300]
        query_keys = sorted(
            set(_query_keys_from_url(parsed.query)) | set(_query_keys_from_url(context))
        )
        rows.append(
            {
                "method": "GET",
                "url": f"{parsed.scheme}://{parsed.netloc}{parsed.path}",
                "host": parsed.hostname or "",
                "path": parsed.path,
                "query_keys": query_keys,
                "body_keys": [],
                "content_type": "application/json",
                "sample_result_count": 0,
                "purpose_guess": _purpose_guess(parsed.path, query_keys),
            }
        )
    return _dedupe_api_candidates(rows)


def _query_keys_from_url(query: str) -> list[str]:
    keys: set[str] = set()
    if re.fullmatch(r"[A-Za-z0-9_=&%+\-\.]*", query):
        keys.update(parse_qs(query, keep_blank_values=True).keys())
    keys.update(re.findall(r"[?&]([A-Za-z_][\w-]*)=", query))
    for item in query.split("&"):
        if "=" in item:
            key = item.split("=", 1)[0]
            if re.fullmatch(r"[A-Za-z_][\w-]*", key):
                keys.add(key)
    return sorted(keys)


def _purpose_guess(path: str, query_keys: list[str]) -> str:
    lowered = " ".join([path, *query_keys]).lower()
    if "search" in lowered or "query" in lowered or "keyword" in lowered:
        return "search_results"
    if "download" in lowered or "file" in lowered:
        return "download_lookup"
    return "unknown"


def _dedupe_api_candidates(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        key = (
            str(row["method"]),
            str(row["url"]),
            "|".join(str(item) for item in row.get("query_keys", [])),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _looks_like_article(url: str, text: str) -> bool:
    lowered = f"{url} {text}".lower()
    if re.search(r"\.(?:s?html?|pdf|txt)(?:[?#].*)?$", lowered):
        return True
    return any(marker in lowered for marker in ["/article", "/news", "/report"])


def _looks_like_listing(url: str, text: str) -> bool:
    lowered = f"{url} {text}".lower()
    return any(marker in lowered for marker in ["list", "search", "topic", "page="])


def _page_risk_flags(
    visible_text: str,
    targets: list[dict[str, object]],
    soup: BeautifulSoup | None = None,
) -> list[str]:
    flags: list[str] = []
    lowered = visible_text.lower()
    if "login" in lowered or "登录" in visible_text:
        flags.append("login_required_signal")
    if "captcha" in lowered or "验证码" in visible_text:
        flags.append("captcha_signal")
    if "paywall" in lowered or "付费" in visible_text:
        flags.append("paywall_signal")
    if soup is not None and _has_sensitive_form_fields(soup):
        flags.append("sensitive_form_fields")
    if not targets:
        flags.append("no_interactive_targets")
    return _dedupe_strings(flags)


def _blocks_javascript(flags: list[str]) -> bool:
    return bool(set(flags) & SENSITIVE_PAGE_RISK_FLAGS)


def _blocks_document_capture(flags: list[str]) -> bool:
    return bool(set(flags) & SENSITIVE_PAGE_RISK_FLAGS)


def _has_sensitive_form_fields(soup: BeautifulSoup) -> bool:
    for tag in soup.find_all("input"):
        if not isinstance(tag, Tag):
            continue
        if _input_type(tag) in SENSITIVE_INPUT_TYPES:
            return True
    return False


def _sanitize_browser_html_for_artifact(html: str) -> tuple[str, bool]:
    soup = BeautifulSoup(html or "", "html.parser")
    sanitized = False
    for tag in list(soup.find_all("input")):
        if not isinstance(tag, Tag):
            continue
        input_type = _input_type(tag)
        field_name = str(tag.get("name", "") or "").lower()
        field_id = str(tag.get("id", "") or "").lower()
        if input_type in SENSITIVE_INPUT_TYPES:
            tag.decompose()
            sanitized = True
            continue
        if "value" in tag.attrs and _looks_sensitive_field_name(field_name, field_id):
            tag["value"] = "[REDACTED]"
            sanitized = True
    return str(soup), sanitized


def _looks_sensitive_field_name(*names: str) -> bool:
    markers = ["token", "csrf", "auth", "credential", "password", "passwd", "secret"]
    joined = " ".join(names).lower()
    return any(marker in joined for marker in markers)


def _access_status(visible_text: str) -> str:
    lowered = visible_text.lower()
    if "403" in lowered or "forbidden" in lowered:
        return "forbidden"
    if "404" in lowered or "not found" in lowered:
        return "not_found"
    if "login" in lowered or "登录" in visible_text:
        return "login_required_signal"
    return "ok"


def _has_dynamic_script(soup: BeautifulSoup) -> bool:
    script_text = "\n".join(script.get_text(" ") for script in soup.find_all("script"))
    return bool(re.search(r"\b(fetch|XMLHttpRequest|axios|__NEXT_DATA__)\b", script_text))


def _form_targets(soup: BeautifulSoup, page_url: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for form_index, form in enumerate(soup.find_all("form"), start=1):
        if not isinstance(form, Tag):
            continue
        action_url = urljoin(page_url, str(form.get("action", "") or page_url))
        method = str(form.get("method", "get")).lower() or "get"
        inputs: list[dict[str, str]] = []
        form_risk_flags: list[str] = []
        if any(
            isinstance(tag, Tag) and _input_type(tag) in SENSITIVE_INPUT_TYPES
            for tag in form.find_all("input")
        ):
            form_risk_flags.append("sensitive_form_fields")
        if method != "get":
            form_risk_flags.append("non_get_form")
        for input_index, tag in enumerate(form.find_all("input"), start=1):
            if not isinstance(tag, Tag):
                continue
            input_type = _input_type(tag)
            if input_type in SENSITIVE_INPUT_TYPES:
                continue
            if input_type in {"submit", "button", "reset", "image"}:
                continue
            name = str(tag.get("name", "") or "")
            label = name or str(tag.get("placeholder", "") or f"input-{input_index}")
            input_target = {
                "target_id": _target_id(page_url, "input", form_index, input_index, label),
                "kind": "input",
                "name": name,
                "input_type": input_type,
                "label": label,
                "form_index": form_index,
                "page_url": page_url,
                "allowed_actions": ["fill_input"],
            }
            rows.append(input_target)
            inputs.append({"name": name, "type": input_type, "label": label})
        button_text = _button_text(form) or "submit"
        allowed_actions = (
            ["submit_form"]
            if method == "get" and "sensitive_form_fields" not in form_risk_flags
            else []
        )
        rows.append(
            {
                "target_id": _target_id(page_url, "form", form_index, 0, button_text),
                "kind": "form",
                "label": button_text,
                "action_url": action_url,
                "method": method,
                "inputs": inputs,
                "page_url": page_url,
                "allowed_actions": allowed_actions,
                "risk_flags": _dedupe_strings(form_risk_flags),
            }
        )
    return rows


def _link_targets(soup: BeautifulSoup, page_url: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, tag in enumerate(soup.find_all("a"), start=1):
        if not isinstance(tag, Tag):
            continue
        href = str(tag.get("href", "") or "").strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        url = urljoin(page_url, href)
        text = _clean_text(tag.get_text(" ", strip=True)) or url
        kind = _link_kind(tag, url, text)
        action = {
            "download_link": "download_link",
            "next_page": "next_page",
        }.get(kind, "click_link")
        rows.append(
            {
                "target_id": _target_id(page_url, kind, index, 0, text),
                "kind": kind,
                "text": text,
                "url": url,
                "page_url": page_url,
                "allowed_actions": [action],
            }
        )
    return rows


def _link_kind(tag: Tag, url: str, text: str) -> str:
    lower = f"{url} {text} {' '.join(str(item) for item in tag.get('rel', []) or [])}".lower()
    if re.search(r"\.(pdf|doc|docx|txt)(?:[?#].*)?$", url.lower()) or "download" in lower or "下载" in text:
        return "download_link"
    if "next" in lower or "下一页" in text or text.strip() in {">", ">>"}:
        return "next_page"
    return "link"


def _title(soup: BeautifulSoup) -> str:
    for tag in [soup.find("h1"), soup.find("title")]:
        if isinstance(tag, Tag):
            text = _clean_text(tag.get_text(" ", strip=True))
            if text:
                return text
    return ""


def _button_text(form: Tag) -> str:
    for tag in form.find_all(["button", "input"]):
        if not isinstance(tag, Tag):
            continue
        if tag.name == "button":
            text = _clean_text(tag.get_text(" ", strip=True))
        else:
            if _input_type(tag) not in {"submit", "button", "reset", "image"}:
                continue
            text = _clean_text(str(tag.get("value", "") or ""))
        if text:
            return text
    return ""


def _input_type(tag: Tag) -> str:
    return str(tag.get("type", "text") or "text").lower()


def _dedupe_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _first_outside_whitelist(
    registry: SourceRegistry,
    *urls: str,
) -> str:
    for url in urls:
        if url and registry.match(url) is None:
            return url
    return ""


def _first_outside_browser_scope(
    registry: SourceRegistry,
    allowed_scopes: list[BrowserUrlScope],
    *urls: str,
) -> str:
    for url in urls:
        if url and _browser_scope_for_url(
            registry=registry,
            url=url,
            allowed_scopes=allowed_scopes,
        ) is None:
            return url
    return ""


def _target_action_scope_urls(
    *,
    action: str,
    target: dict[str, object],
    observation: BrowserObservation,
) -> list[str]:
    if action in {"click_link", "next_page", "download_link"}:
        return [str(target.get("url", "")).strip()]
    if action == "submit_form":
        return [str(target.get("action_url", "") or observation.page_url).strip()]
    if action in {"fill_input", "activate_button"}:
        return [
            str(
                target.get("url", "")
                or target.get("action_url", "")
                or observation.page_url
            ).strip()
        ]
    return [observation.page_url]


def _outside_browser_scope_from_js_delta(
    *,
    registry: SourceRegistry,
    allowed_scopes: list[BrowserUrlScope],
    network_delta: list[object],
) -> str:
    for row in network_delta:
        if not isinstance(row, dict):
            continue
        host = str(row.get("host", "") or "")
        path = str(row.get("path", "/") or "/")
        scheme = str(row.get("scheme", "https") or "https")
        if not host:
            continue
        url = f"{scheme}://{host}{path}"
        if _browser_scope_for_url(
            registry=registry,
            url=url,
            allowed_scopes=allowed_scopes,
        ) is None:
            return url
    return ""


def _suggested_next_actions(scan: BrowserPageScan) -> list[str]:
    if scan.article_candidates or scan.visible_text:
        return ["capture_current_document"]
    if scan.download_targets:
        return ["download_link"]
    if scan.pagination_targets:
        return ["next_page"]
    return ["browser_observe"]


def _json_preview(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _document_candidates_from_js_result(value: object) -> list[str]:
    items = value if isinstance(value, list) else [value]
    rows: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "") or item.get("href", "")).strip()
        if url.startswith("http") and url not in rows:
            rows.append(url)
    return rows[:10]


def _recipe_from_js_success(
    *,
    run_id: str,
    observation: BrowserObservation,
    intent: str,
    script_hash: str,
    script_ref: str,
    return_artifact_ref: str,
    network_delta: list[object],
) -> BrowserRecipeDraft | None:
    api = _first_api_candidate_from_network_delta(observation.page_url, network_delta)
    if api is None:
        return None
    now = _now()
    recipe_id = f"browser-recipe-{_hash(observation.page_url + script_hash)}"
    return BrowserRecipeDraft(
        recipe_id=recipe_id,
        run_id=run_id,
        source_name=str(observation.source_scope.get("source_name", "")),
        domain=api.host,
        intent=intent,
        trigger_condition="browser javascript discovered public same-origin API candidate",
        script_hash=script_hash,
        script_ref=script_ref,
        return_artifact_ref=return_artifact_ref,
        input_names=[*api.query_keys, *api.body_keys],
        output_type="api_candidate",
        api_candidate=api,
        observed_success_signal="javascript returned candidate result and network delta",
        safety_notes=["same-origin", "read-only", "no-credentials"],
        review_status="draft",
        created_at=now,
        updated_at=now,
    )


def _first_api_candidate_from_network_delta(
    page_url: str,
    network_delta: list[object],
) -> BrowserApiCandidate | None:
    page_host = urlparse(page_url).hostname or ""
    page_scheme = urlparse(page_url).scheme or "https"
    for row in network_delta:
        if not isinstance(row, dict):
            continue
        method = str(row.get("method", "GET")).upper()
        host = str(row.get("host", "") or "")
        if host != page_host or method not in {"GET", "HEAD"}:
            continue
        path = str(row.get("path", "") or "")
        return BrowserApiCandidate(
            method=method,
            url=f"{page_scheme}://{host}{path}",
            host=host,
            path=path,
            query_keys=[str(item) for item in row.get("query_keys", [])],
            body_keys=[],
            content_type=str(row.get("content_type", "")),
            purpose_guess=str(row.get("purpose_guess", "")),
            same_origin=True,
        )
    return None


def _delta_summary(before: str, after: str) -> str:
    cleaned_before = _clean_text(before)
    cleaned_after = _clean_text(after)
    if not cleaned_after or cleaned_after == cleaned_before:
        return "页面无明显文本变化"
    return _excerpt(cleaned_after, 1200)


def _target_id(
    page_url: str,
    kind: str,
    index: int,
    child_index: int,
    label: str,
) -> str:
    return f"bt-{_hash(f'{page_url}|{kind}|{index}|{child_index}|{label}')}"


def _new_text(previous_url: str, visible_text: str) -> str:
    if not visible_text:
        return ""
    return visible_text if previous_url else visible_text


def _clean_text(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _excerpt(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _now() -> datetime:
    return datetime.now(timezone.utc)
