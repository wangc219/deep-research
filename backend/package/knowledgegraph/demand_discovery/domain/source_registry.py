"""Demand-discovery source whitelist registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


VALID_TIERS = {"A", "B", "C", "D"}
VALID_TRANSPORTS = {"http", "browser_session"}
VALID_SEARCH_TYPES = {"url_template", "dynamic_api", "listing", "local_only", "none"}
VALID_INTERACTION_PROFILES = {
    "static_listing",
    "site_search",
    "browser_listing",
    "browser_search",
    "none",
}
VALID_CONTENT_LANGUAGES = {"zh", "en"}


@dataclass(frozen=True)
class SearchConfig:
    type: str = "none"
    template: str = ""


@dataclass(frozen=True)
class WhitelistEntry:
    source_name: str
    source_tier: str
    source_type: str
    hosts: list[str] = field(default_factory=list)
    path_prefixes: list[str] = field(default_factory=list)
    fetch_transport: str = "http"
    search: SearchConfig = field(default_factory=SearchConfig)
    rate_limit_ms: int = 3000
    notes: str = ""
    entry_urls: list[str] = field(default_factory=list)
    topic_tags: list[str] = field(default_factory=list)
    default_queries: list[str] = field(default_factory=list)
    content_languages: list[str] = field(default_factory=list)
    interaction_profile: str = "none"
    requires_login: bool = False
    max_discovery_depth: int = 1


@dataclass(frozen=True)
class ExcludedSource:
    source_name: str
    reason: str
    hosts: list[str] = field(default_factory=list)


class SourceRegistry:
    """Whitelist lookup for source-aware network tools."""

    def __init__(
        self,
        sources: list[WhitelistEntry],
        excluded: list[ExcludedSource] | None = None,
        version: int = 1,
    ) -> None:
        self.sources = list(sources)
        self.excluded = list(excluded or [])
        self.version = version

    @classmethod
    def load(cls, path: str | Path) -> "SourceRegistry":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        version = int(data.get("version", 1))
        if version != 1:
            raise ValueError(f"unsupported source whitelist version: {version}")
        sources = [
            _entry_from_dict(item, index)
            for index, item in enumerate(data.get("sources", []))
        ]
        excluded = [
            _excluded_from_dict(item, index)
            for index, item in enumerate(data.get("excluded", []))
        ]
        return cls(sources=sources, excluded=excluded, version=version)

    def match(self, url: str) -> WhitelistEntry | None:
        host, path = _host_path(url)
        if not host:
            return None
        if any(_entry_matches(host, path, item.hosts, []) for item in self.excluded):
            return None
        matches = [
            (self._specificity(entry, host, path), entry)
            for entry in self.sources
            if _entry_matches(host, path, entry.hosts, entry.path_prefixes)
        ]
        if not matches:
            return None
        return max(matches, key=lambda item: item[0])[1]

    def tier_status_cap(self, tier: str) -> str:
        normalized = str(tier).strip().upper()
        if normalized == "A":
            return "demand_report"
        if normalized == "B":
            return "demand_report"
        if normalized == "C":
            return "researchable_signal"
        if normalized == "D":
            return "discarded_signal"
        raise ValueError(f"unknown source tier: {tier}")

    def max_status_for_tier(self, tier: str) -> str:
        return self.tier_status_cap(tier)

    def search_entries(self) -> list[WhitelistEntry]:
        return [entry for entry in self.sources if entry.search.type != "none"]

    def discoverable_entries(
        self,
        *,
        topic: str = "",
        tiers: set[str] | None = None,
        transports: set[str] | None = None,
    ) -> list[WhitelistEntry]:
        """Return whitelist entries usable as seedless discovery starts."""

        normalized_tiers = {item.upper() for item in tiers} if tiers else None
        normalized_transports = {item.strip() for item in transports} if transports else None
        entries = [
            entry
            for entry in self.sources
            if entry.entry_urls
            and (normalized_tiers is None or entry.source_tier in normalized_tiers)
            and (
                normalized_transports is None
                or entry.fetch_transport in normalized_transports
            )
        ]
        return sorted(
            entries,
            key=lambda entry: self._discoverable_sort_key(entry, topic),
        )

    def _discoverable_sort_key(
        self,
        entry: WhitelistEntry,
        topic: str,
    ) -> tuple[int, int, int, int, int, str]:
        topic_score = _topic_score(topic, entry.topic_tags)
        tier_rank = {"A": 0, "B": 1, "C": 2, "D": 3}.get(entry.source_tier, 9)
        has_profile = 0 if entry.interaction_profile != "none" else 1
        login_rank = 1 if entry.requires_login else 0
        has_queries = 0 if entry.default_queries else 1
        return (login_rank, -topic_score, tier_rank, has_profile, has_queries, entry.source_name)

    @staticmethod
    def _specificity(
        entry: WhitelistEntry,
        host: str,
        path: str,
    ) -> tuple[int, int, str]:
        matched_prefix_lengths = [
            len(prefix)
            for prefix in entry.path_prefixes
            if _path_matches(path, prefix)
        ]
        path_len = max(matched_prefix_lengths) if matched_prefix_lengths else 0
        host_len = max(
            (len(item) for item in entry.hosts if _host_matches(host, item)),
            default=0,
        )
        return (path_len, host_len, entry.source_name)


def default_source_whitelist_path() -> Path:
    return (
        Path(__file__).resolve().parents[4]
        / "configs"
        / "demand_discovery"
        / "source_whitelist.yaml"
    )


def _entry_from_dict(data: dict[str, Any], index: int) -> WhitelistEntry:
    source_name = _required_str(data, "source_name", index)
    source_tier = _required_str(data, "source_tier", index).upper()
    if source_tier not in VALID_TIERS:
        raise ValueError(f"sources[{index}].source_tier must be one of A/B/C/D")
    source_type = _required_str(data, "source_type", index)
    fetch_transport = str(data.get("fetch_transport", "http")).strip()
    if fetch_transport not in VALID_TRANSPORTS:
        raise ValueError(f"sources[{index}].fetch_transport is invalid")
    search = _search_from_dict(data.get("search", {"type": "none"}), index)
    interaction_profile = str(data.get("interaction_profile", "none")).strip() or "none"
    if interaction_profile not in VALID_INTERACTION_PROFILES:
        raise ValueError(f"sources[{index}].interaction_profile is invalid")
    content_languages = _content_languages_from_dict(data, index)
    return WhitelistEntry(
        source_name=source_name,
        source_tier=source_tier,
        source_type=source_type,
        hosts=_host_list(data.get("hosts", []), f"sources[{index}].hosts"),
        path_prefixes=[
            _normalize_prefix(item)
            for item in _string_list(
                data.get("path_prefixes", []),
                f"sources[{index}].path_prefixes",
            )
        ],
        fetch_transport=fetch_transport,
        search=search,
        rate_limit_ms=_non_negative_int(data.get("rate_limit_ms", 3000), index),
        notes=str(data.get("notes", "")),
        entry_urls=_string_list(data.get("entry_urls", []), f"sources[{index}].entry_urls"),
        topic_tags=_string_list(data.get("topic_tags", []), f"sources[{index}].topic_tags"),
        default_queries=_string_list(
            data.get("default_queries", []),
            f"sources[{index}].default_queries",
        ),
        content_languages=content_languages,
        interaction_profile=interaction_profile,
        requires_login=bool(data.get("requires_login", False)),
        max_discovery_depth=max(
            0,
            _non_negative_int(data.get("max_discovery_depth", 1), index),
        ),
    )


def _excluded_from_dict(data: dict[str, Any], index: int) -> ExcludedSource:
    return ExcludedSource(
        source_name=_required_str(data, "source_name", index),
        reason=_required_str(data, "reason", index),
        hosts=_host_list(data.get("hosts", []), f"excluded[{index}].hosts"),
    )


def _search_from_dict(value: Any, index: int) -> SearchConfig:
    data = value if isinstance(value, dict) else {"type": "none"}
    search_type = str(data.get("type", "none")).strip()
    if search_type not in VALID_SEARCH_TYPES:
        raise ValueError(f"sources[{index}].search.type is invalid")
    return SearchConfig(
        type=search_type,
        template=str(data.get("template", "")),
    )


def _content_languages_from_dict(data: dict[str, Any], index: int) -> list[str]:
    raw = _string_list(
        data.get("content_languages", []),
        f"sources[{index}].content_languages",
    )
    languages = [item.lower() for item in raw]
    invalid = [item for item in languages if item not in VALID_CONTENT_LANGUAGES]
    if invalid:
        raise ValueError(
            f"sources[{index}].content_languages must contain zh/en values"
        )
    return _dedupe_strings(languages)


def _required_str(data: dict[str, Any], key: str, index: int) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"sources[{index}].{key} is required")
    return value.strip()


def _string_list(value: Any, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return [str(item).strip() for item in value if str(item).strip()]


def _host_list(value: Any, label: str) -> list[str]:
    return [item.lower() for item in _string_list(value, label)]


def _non_negative_int(value: Any, index: int) -> int:
    number = int(value)
    if number < 0:
        raise ValueError(f"sources[{index}].rate_limit_ms must be non-negative")
    return number


def _normalize_prefix(prefix: str) -> str:
    if not prefix:
        return ""
    return prefix if prefix.startswith("/") else f"/{prefix}"


def _dedupe_strings(values: list[str]) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            rows.append(value)
    return rows


def _host_path(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    host = (parsed.hostname or "").strip().lower()
    path = parsed.path or "/"
    return host, path


def _entry_matches(
    host: str,
    path: str,
    hosts: list[str],
    path_prefixes: list[str],
) -> bool:
    if not hosts:
        return False
    if not any(_host_matches(host, item) for item in hosts):
        return False
    if not path_prefixes:
        return True
    return any(_path_matches(path, prefix) for prefix in path_prefixes)


def _host_matches(host: str, allowed_host: str) -> bool:
    normalized = allowed_host.strip().lower()
    return host == normalized or host.endswith(f".{normalized}")


def _path_matches(path: str, prefix: str) -> bool:
    if not prefix:
        return True
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def _topic_score(topic: str, tags: list[str]) -> int:
    normalized_topic = topic.lower().replace(" ", "")
    if not normalized_topic:
        return 0
    score = 0
    for value in tags:
        normalized = value.lower().replace(" ", "")
        if normalized and normalized in normalized_topic:
            score += 2
            continue
        for token in _split_topic_tokens(value):
            if token and token in normalized_topic:
                score += 1
    return score


def _split_topic_tokens(value: str) -> list[str]:
    return [
        token.strip().lower()
        for token in value.replace(",", " ").replace("，", " ").split()
        if token.strip()
    ]
