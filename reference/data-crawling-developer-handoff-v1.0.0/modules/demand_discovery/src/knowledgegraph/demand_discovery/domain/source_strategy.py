"""Programmatic source strategy planning for topic-only research."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from typing import Any

from knowledgegraph.demand_discovery.domain.query_planner import (
    QueryBundle,
    QueryVariant,
    ResearchDirection,
    ResearchPlan,
    WorkerAssignment,
)
from knowledgegraph.demand_discovery.domain.source_registry import (
    SourceRegistry,
    WhitelistEntry,
)


@dataclass(frozen=True)
class SelectedSource:
    source_name: str
    source_tier: str
    source_type: str
    fetch_transport: str
    entry_urls: list[str]
    content_languages: list[str]
    planned_queries: list[str]
    default_queries: list[str]
    interaction_profile: str
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "source_tier": self.source_tier,
            "source_type": self.source_type,
            "fetch_transport": self.fetch_transport,
            "entry_urls": list(self.entry_urls),
            "content_languages": list(self.content_languages),
            "planned_queries": list(self.planned_queries),
            "default_queries": list(self.default_queries),
            "interaction_profile": self.interaction_profile,
            "rationale": self.rationale,
        }


@dataclass(frozen=True)
class HeldSource:
    source_name: str
    source_tier: str
    source_type: str
    fetch_transport: str
    entry_urls: list[str]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "source_tier": self.source_tier,
            "source_type": self.source_type,
            "fetch_transport": self.fetch_transport,
            "entry_urls": list(self.entry_urls),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SourceStrategy:
    strategy_id: str
    topic: str
    selected_sources: list[SelectedSource]
    held_sources: list[HeldSource] = field(default_factory=list)
    seed_urls: list[str] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "topic": self.topic,
            "selected_sources": [source.to_dict() for source in self.selected_sources],
            "held_sources": [source.to_dict() for source in self.held_sources],
            "seed_urls": list(self.seed_urls),
            "rationale": self.rationale,
        }


def selected_source_from_dict(data: dict[str, Any]) -> SelectedSource:
    return SelectedSource(
        source_name=str(data.get("source_name", "")),
        source_tier=str(data.get("source_tier", "")),
        source_type=str(data.get("source_type", "")),
        fetch_transport=str(data.get("fetch_transport", "")),
        entry_urls=list(data.get("entry_urls", [])),
        content_languages=list(data.get("content_languages", [])),
        planned_queries=list(data.get("planned_queries", [])),
        default_queries=list(data.get("default_queries", [])),
        interaction_profile=str(data.get("interaction_profile", "")),
        rationale=str(data.get("rationale", "")),
    )


def held_source_from_dict(data: dict[str, Any]) -> HeldSource:
    return HeldSource(
        source_name=str(data.get("source_name", "")),
        source_tier=str(data.get("source_tier", "")),
        source_type=str(data.get("source_type", "")),
        fetch_transport=str(data.get("fetch_transport", "")),
        entry_urls=list(data.get("entry_urls", [])),
        reason=str(data.get("reason", "")),
    )


def source_strategy_from_dict(data: dict[str, Any]) -> SourceStrategy:
    return SourceStrategy(
        strategy_id=str(data["strategy_id"]),
        topic=str(data.get("topic", "")),
        selected_sources=[
            selected_source_from_dict(dict(item))
            for item in data.get("selected_sources", [])
        ],
        held_sources=[
            held_source_from_dict(dict(item))
            for item in data.get("held_sources", [])
        ],
        seed_urls=list(data.get("seed_urls", [])),
        rationale=str(data.get("rationale", "")),
    )


def source_strategy_to_research_plan_fixture(
    strategy: SourceStrategy,
    *,
    round_id: str = "",
    allowed_scope: str = "whitelist",
) -> ResearchPlan:
    """Project a legacy SourceStrategy into the new ResearchPlan contract.

    This is a compatibility fixture for fake/offline runs. It deliberately does
    not decompose topics or invent new queries; real query planning remains a
    model-agent responsibility.
    """

    directions: list[ResearchDirection] = []
    assignments: list[WorkerAssignment] = []
    for index, source in enumerate(strategy.selected_sources, start=1):
        direction_id = f"dir-{index}"
        query_bundle = _query_bundle_from_source(source, fallback_topic=strategy.topic)
        directions.append(
            ResearchDirection(
                direction_id=direction_id,
                goal=(
                    "Investigate the assigned whitelist source for evidence "
                    f"related to: {strategy.topic}"
                ),
                query_bundle=query_bundle,
            )
        )
        assignments.append(
            WorkerAssignment(
                assignment_id=f"wa-{index}",
                round_id=round_id,
                direction_id=direction_id,
                source_names=[source.source_name],
                query_bundle=query_bundle,
                brief=(
                    "Use the assigned whitelist source and query bundle to "
                    "find traceable body evidence before escalating scope."
                ),
                allowed_scope=allowed_scope,
            )
        )
    return ResearchPlan(
        plan_id=f"rp-{strategy.strategy_id}",
        topic=strategy.topic,
        round_id=round_id,
        research_directions=directions,
        worker_assignments=assignments,
        planner_rationale=(
            "Compatibility fixture projected from SourceStrategy; semantic "
            "planning is owned by the QueryPlanner agent."
        ),
    )


class SourceStrategyPlanner:
    """Select seedless discovery sources from the whitelist."""

    def __init__(self, registry: SourceRegistry) -> None:
        self.registry = registry

    def plan(
        self,
        *,
        topic: str,
        seed_urls: list[str] | None = None,
        allow_browser: bool = False,
        min_sources: int = 2,
    ) -> SourceStrategy:
        manual_seed_urls = list(seed_urls or [])
        selected_entries: list[WhitelistEntry] = []
        held_entries: list[HeldSource] = []

        http_entries = self.registry.discoverable_entries(
            topic=topic,
            tiers={"A", "B"},
            transports={"http"},
        )
        browser_entries = self.registry.discoverable_entries(
            topic=topic,
            tiers={"A", "B"},
            transports={"browser_session"},
        )
        selected_entries.extend(
            _diverse_first(http_entries, min_sources, topic=topic)
        )
        if allow_browser:
            browser_slots = max(0, min(1, min_sources - len(selected_entries)))
            selected_entries.extend(browser_entries[:browser_slots])
        else:
            held_entries.extend(
                _held(entry, "browser source held because allow_browser=false")
                for entry in browser_entries
            )

        selected_sources = [
            _selected(
                entry,
                topic=topic,
                rationale="topic-derived query plan and public whitelisted entry",
            )
            for entry in selected_entries
        ]
        seed_url_rows = [
            url
            for entry in selected_entries
            for url in entry.entry_urls[:1]
        ]
        seed_url_rows = [*manual_seed_urls, *seed_url_rows]
        strategy_id = f"strategy-{_hash(topic + '|' + '|'.join(seed_url_rows))}"
        return SourceStrategy(
            strategy_id=strategy_id,
            topic=topic,
            selected_sources=selected_sources,
            held_sources=held_entries,
            seed_urls=seed_url_rows,
            rationale=(
                "Selected A/B tier HTTP sources with whitelist entry URLs; "
                "browser sources are held unless explicitly allowed."
            ),
        )


def _diverse_first(
    entries: list[WhitelistEntry],
    min_sources: int,
    *,
    topic: str,
) -> list[WhitelistEntry]:
    selected = list(entries[:min_sources])
    if len({entry.source_type for entry in selected}) != 1:
        return selected
    selected_names = {entry.source_name for entry in selected}
    selected_type = selected[0].source_type if selected else ""
    for entry in entries[min_sources:]:
        if entry.source_name in selected_names:
            continue
        if entry.source_type == selected_type:
            continue
        if not _entry_has_topic_signal(topic, entry):
            continue
        return [*selected[:-1], entry]
    return selected


def _selected(entry: WhitelistEntry, *, topic: str, rationale: str) -> SelectedSource:
    return SelectedSource(
        source_name=entry.source_name,
        source_tier=entry.source_tier,
        source_type=entry.source_type,
        fetch_transport=entry.fetch_transport,
        entry_urls=list(entry.entry_urls),
        content_languages=_content_languages(entry),
        planned_queries=_planned_queries(topic, _content_languages(entry)),
        default_queries=list(entry.default_queries),
        interaction_profile=entry.interaction_profile,
        rationale=rationale,
    )


def _held(entry: WhitelistEntry, reason: str) -> HeldSource:
    return HeldSource(
        source_name=entry.source_name,
        source_tier=entry.source_tier,
        source_type=entry.source_type,
        fetch_transport=entry.fetch_transport,
        entry_urls=list(entry.entry_urls),
        reason=reason,
    )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _content_languages(entry: WhitelistEntry) -> list[str]:
    return list(entry.content_languages or ["zh", "en"])


def _entry_has_topic_signal(topic: str, entry: WhitelistEntry) -> bool:
    normalized_topic = " ".join(topic.lower().replace("_", " ").split())
    compact_topic = _compact_topic_terms(normalized_topic)
    topic_terms = set(compact_topic.split())
    for tag in entry.topic_tags:
        normalized_tag = " ".join(str(tag).lower().replace("_", " ").split())
        if not normalized_tag:
            continue
        if normalized_tag in normalized_topic:
            return True
        tag_terms = set(normalized_tag.split())
        if topic_terms & tag_terms:
            return True
    return False


def _planned_queries(topic: str, content_languages: list[str]) -> list[str]:
    topic_query = " ".join(str(topic).split())
    languages = content_languages or ["zh", "en"]
    rows: list[str] = []
    if "zh" in languages:
        rows.append(topic_query)
        compact = _compact_topic_terms(topic_query)
        if compact and compact != topic_query:
            rows.append(compact)
    if "en" in languages:
        english = _english_topic_query(topic_query)
        if english:
            rows.append(english)
    if not rows:
        rows.append(topic_query)
    return _dedupe_strings(rows)


def _query_bundle_from_source(
    source: SelectedSource,
    *,
    fallback_topic: str,
) -> QueryBundle:
    languages = source.content_languages or ["auto"]
    language = languages[0] if len(languages) == 1 else "auto"
    queries = source.planned_queries or [fallback_topic]
    return QueryBundle(
        queries=[
            QueryVariant(
                text=query,
                language=language,
                intent="evidence_discovery",
            )
            for query in queries
            if str(query).strip()
        ]
    )


def _compact_topic_terms(topic: str) -> str:
    normalized = (
        topic.replace("条件下", " ")
        .replace("能力缺口", " 能力 缺口")
        .replace("受扰", " 受扰 ")
        .replace("的", " ")
        .replace("、", " ")
        .replace("，", " ")
        .replace(",", " ")
    )
    return " ".join(part for part in normalized.split() if part)


def _english_topic_query(topic: str) -> str:
    if not _has_cjk(topic):
        return topic
    terms: list[str] = []
    if "补给链" in topic or "后勤" in topic or "补给" in topic:
        terms.append("contested logistics" if "受扰" in topic else "military logistics")
    for phrase, translations in _ZH_TO_EN_QUERY_TERMS:
        if phrase in topic:
            terms.extend(translations)
    if not terms and ("能力" in topic or "缺口" in topic):
        terms.append("defense capability gap")
    return " ".join(_dedupe_strings(terms))


_ZH_TO_EN_QUERY_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("远程", ("remote",)),
    ("补给链", ("supply chain",)),
    ("后勤", ("logistics",)),
    ("补给", ("supply",)),
    ("受扰", ("disrupted", "contested")),
    ("战术通信", ("tactical communications",)),
    ("通信", ("communications",)),
    ("指挥控制", ("command and control",)),
    ("态势感知", ("situational awareness",)),
    ("保障", ("support", "sustainment")),
    ("高寒", ("cold regions",)),
    ("寒区", ("cold regions",)),
    ("高原", ("plateau",)),
    ("山地", ("mountain",)),
    ("极地", ("polar",)),
    ("联合救援", ("joint rescue",)),
    ("联合", ("joint",)),
    ("救援", ("rescue",)),
    ("应急", ("emergency",)),
    ("医疗", ("medical",)),
    ("运输", ("transport",)),
    ("机动", ("mobility",)),
    ("低空", ("low altitude",)),
    ("小型无人机", ("small drones", "small UAS")),
    ("无人机", ("drones", "unmanned systems")),
    ("蜂群", ("swarming",)),
    ("探测", ("detection",)),
    ("预警", ("early warning",)),
    ("防护", ("protection",)),
    ("防御", ("defense",)),
    ("反制", ("countermeasure",)),
    ("电子战", ("electronic warfare",)),
    ("干扰", ("jamming", "interference")),
    ("侦察", ("reconnaissance",)),
    ("情报", ("intelligence",)),
    ("监视", ("surveillance",)),
    ("威胁", ("threat",)),
    ("韧性", ("resilience",)),
    ("能力缺口", ("capability gap",)),
    ("缺口", ("gap",)),
    ("能力", ("capability",)),
)


def _has_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _dedupe_strings(values: list[str]) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            rows.append(value)
    return rows
