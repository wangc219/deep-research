"""Browser research domain state for reusable audited browsing recipes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from knowledgegraph.demand_discovery.domain.models import SerializableDataclass


BROWSER_RECIPE_REVIEW_STATUSES = {"draft", "approved", "rejected", "needs_revision"}
BROWSER_RECIPE_OUTPUT_TYPES = {"api_candidate", "document_candidate", "interaction_path"}
BROWSER_API_METHODS = {"GET", "HEAD"}


@dataclass
class BrowserApiCandidate(SerializableDataclass):
    method: str
    url: str
    host: str
    path: str
    query_keys: list[str]
    body_keys: list[str]
    content_type: str
    purpose_guess: str
    same_origin: bool

    def __post_init__(self) -> None:
        if self.method not in BROWSER_API_METHODS:
            raise ValueError(f"unsupported BrowserApiCandidate method: {self.method}")
        if not self.same_origin:
            raise ValueError("BrowserApiCandidate must be same-origin")


@dataclass
class BrowserRecipeDraft(SerializableDataclass):
    recipe_id: str
    run_id: str
    source_name: str
    domain: str
    intent: str
    trigger_condition: str
    script_hash: str
    script_ref: str
    return_artifact_ref: str
    input_names: list[str]
    output_type: str
    api_candidate: BrowserApiCandidate | None
    observed_success_signal: str
    safety_notes: list[str]
    review_status: str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if self.review_status not in BROWSER_RECIPE_REVIEW_STATUSES:
            raise ValueError(
                f"unknown BrowserRecipeDraft review_status: {self.review_status}"
            )
        if self.output_type not in BROWSER_RECIPE_OUTPUT_TYPES:
            raise ValueError(
                f"unknown BrowserRecipeDraft output_type: {self.output_type}"
            )
        if self.output_type == "api_candidate" and self.api_candidate is None:
            raise ValueError("BrowserRecipeDraft api_candidate is required")


def browser_api_candidate_from_dict(
    data: dict[str, Any] | None,
) -> BrowserApiCandidate | None:
    if data is None:
        return None
    return BrowserApiCandidate(
        method=str(data.get("method", "GET")).upper(),
        url=str(data.get("url", "")),
        host=str(data.get("host", "")),
        path=str(data.get("path", "")),
        query_keys=[str(item) for item in data.get("query_keys", [])],
        body_keys=[str(item) for item in data.get("body_keys", [])],
        content_type=str(data.get("content_type", "")),
        purpose_guess=str(data.get("purpose_guess", "")),
        same_origin=bool(data.get("same_origin", False)),
    )


def browser_recipe_draft_from_dict(data: dict[str, Any]) -> BrowserRecipeDraft:
    return BrowserRecipeDraft(
        recipe_id=str(data["recipe_id"]),
        run_id=str(data.get("run_id", "")),
        source_name=str(data.get("source_name", "")),
        domain=str(data.get("domain", "")),
        intent=str(data.get("intent", "")),
        trigger_condition=str(data.get("trigger_condition", "")),
        script_hash=str(data.get("script_hash", "")),
        script_ref=str(data.get("script_ref", "")),
        return_artifact_ref=str(data.get("return_artifact_ref", "")),
        input_names=[str(item) for item in data.get("input_names", [])],
        output_type=str(data.get("output_type", "")),
        api_candidate=browser_api_candidate_from_dict(data.get("api_candidate")),
        observed_success_signal=str(data.get("observed_success_signal", "")),
        safety_notes=[str(item) for item in data.get("safety_notes", [])],
        review_status=str(data.get("review_status", "draft")),
        created_at=_parse_datetime(data.get("created_at")),
        updated_at=_parse_datetime(data.get("updated_at")),
    )


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    return datetime.now(timezone.utc)
