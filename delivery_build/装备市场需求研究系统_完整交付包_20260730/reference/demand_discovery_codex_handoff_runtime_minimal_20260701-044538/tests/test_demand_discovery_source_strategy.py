from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.source_registry import (  # noqa: E402
    SourceRegistry,
    default_source_whitelist_path,
)
from knowledgegraph.demand_discovery.domain.source_strategy import (  # noqa: E402
    SourceStrategyPlanner,
    source_strategy_from_dict,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402


class DemandDiscoverySourceStrategyTests(unittest.TestCase):
    def test_discoverable_entries_prefers_topic_matched_public_http_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source_whitelist.yaml"
            path.write_text(
                """
version: 1
sources:
  - source_name: Login Source
    source_tier: A
    source_type: official
    hosts: [login.example.test]
    fetch_transport: http
    entry_urls: ["https://login.example.test/"]
    topic_tags: [low_altitude, uav]
    default_queries: ["低空 无人机"]
    interaction_profile: static_listing
    requires_login: true
    max_discovery_depth: 1
  - source_name: Topic Source
    source_tier: B
    source_type: journal
    hosts: [topic.example.test]
    fetch_transport: http
    entry_urls: ["https://topic.example.test/news"]
    topic_tags: [低空, 无人机, air_defense]
    default_queries: ["低空 无人机 探测"]
    interaction_profile: static_listing
    requires_login: false
    max_discovery_depth: 2
  - source_name: Generic Source
    source_tier: A
    source_type: thinktank
    hosts: [generic.example.test]
    fetch_transport: http
    entry_urls: ["https://generic.example.test/reports"]
    interaction_profile: none
    requires_login: false
  - source_name: Browser Source
    source_tier: A
    source_type: media
    hosts: [browser.example.test]
    fetch_transport: browser_session
    entry_urls: ["https://browser.example.test/"]
    topic_tags: [低空]
    interaction_profile: browser_search
    requires_login: false
excluded: []
""",
                encoding="utf-8",
            )

            registry = SourceRegistry.load(path)
            entries = registry.discoverable_entries(
                topic="低空无人机探测预警",
                tiers={"A", "B"},
                transports={"http"},
            )

        self.assertEqual([entry.source_name for entry in entries], ["Topic Source", "Generic Source", "Login Source"])
        self.assertEqual(entries[0].default_queries, ["低空 无人机 探测"])
        self.assertEqual(entries[0].interaction_profile, "static_listing")
        self.assertEqual(entries[0].max_discovery_depth, 2)
        for entry in entries:
            for url in entry.entry_urls:
                self.assertIs(registry.match(url), entry)

    def test_default_whitelist_has_seedless_entry_urls_that_match_registry(self) -> None:
        registry = SourceRegistry.load(default_source_whitelist_path())
        entries = registry.discoverable_entries(
            topic="低空小型无人机探测预警防护",
            tiers={"A", "B"},
            transports={"http"},
        )

        self.assertGreaterEqual(len(entries), 3)
        china_military = next(
            entry for entry in entries if entry.source_name == "中国军网"
        )
        self.assertIn("http://www.81.cn/", china_military.entry_urls)
        self.assertEqual(china_military.interaction_profile, "site_search")
        self.assertEqual(china_military.search.type, "dynamic_api")
        self.assertIn("ssjgy", china_military.search.template)
        self.assertIn("searchfield=TITLE", china_military.search.template)
        self.assertIn("{query}", china_military.search.template)
        rand = next(entry for entry in entries if entry.source_name == "美国兰德公司")
        self.assertIn(
            "https://www.rand.org/topics/uncrewed-aerial-vehicles.html",
            rand.entry_urls,
        )
        modern_defense = next(entry for entry in entries if entry.source_name == "现代防御技术")
        self.assertIn(
            "https://www.xdfyjs.cn/CN/article/showBrowseTopList.do",
            modern_defense.entry_urls,
        )
        for entry in entries[:5]:
            self.assertTrue(entry.entry_urls, entry.source_name)
            self.assertNotEqual(entry.interaction_profile, "none")
            for url in entry.entry_urls:
                self.assertIsNotNone(registry.match(url), url)

    def test_default_whitelist_strategy_is_not_uav_biased_for_non_uav_topic(self) -> None:
        topic = "远程补给链受扰条件下的战术通信保障能力缺口"
        registry = SourceRegistry.load(default_source_whitelist_path())

        strategy = SourceStrategyPlanner(registry).plan(
            topic=topic,
            allow_browser=False,
            min_sources=4,
        )

        selected_names = {source.source_name for source in strategy.selected_sources}
        self.assertTrue(
            selected_names
            & {
                "英国国际战略研究所",
                "Defense One",
                "简氏防务周刊",
                "Parameters",
            },
            selected_names,
        )
        self.assertNotIn("中国军网", selected_names)
        for source in strategy.selected_sources:
            if source.content_languages == ["en"]:
                self.assertIn("tactical communications", source.planned_queries[0])
            else:
                self.assertEqual(source.planned_queries[0], topic)
        flattened_defaults = " ".join(
            " ".join(source.default_queries)
            for source in strategy.selected_sources
        ).lower()
        self.assertNotIn("counter-uas", flattened_defaults)

    def test_default_whitelist_does_not_encode_static_default_queries(self) -> None:
        registry = SourceRegistry.load(default_source_whitelist_path())

        configured_defaults = {
            entry.source_name: list(entry.default_queries)
            for entry in registry.sources
            if entry.default_queries
        }

        self.assertEqual(configured_defaults, {})

    def test_discoverable_entries_scores_topic_tags_not_default_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source_whitelist.yaml"
            path.write_text(
                """
version: 1
sources:
  - source_name: Irrelevant Defaults
    source_tier: A
    source_type: thinktank
    hosts: [irrelevant.example.test]
    fetch_transport: http
    entry_urls: ["https://irrelevant.example.test/"]
    topic_tags: [uav]
    default_queries: ["远程补给链受扰条件下的战术通信保障能力缺口"]
    interaction_profile: static_listing
  - source_name: Relevant Tags
    source_tier: B
    source_type: journal
    hosts: [relevant.example.test]
    fetch_transport: http
    entry_urls: ["https://relevant.example.test/"]
    topic_tags: [通信]
    default_queries: []
    interaction_profile: static_listing
excluded: []
""",
                encoding="utf-8",
            )

            registry = SourceRegistry.load(path)
            entries = registry.discoverable_entries(
                topic="远程补给链受扰条件下的战术通信保障能力缺口",
                tiers={"A", "B"},
                transports={"http"},
            )

        self.assertEqual(entries[0].source_name, "Relevant Tags")

    def test_source_strategy_planner_builds_http_seed_strategy_and_holds_browser(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source_whitelist.yaml"
            path.write_text(
                """
version: 1
sources:
  - source_name: Official Topic
    source_tier: A
    source_type: official
    hosts: [official.example.test]
    fetch_transport: http
    entry_urls: ["https://official.example.test/"]
    topic_tags: [低空, 无人机]
    default_queries: ["低空 无人机"]
    interaction_profile: static_listing
  - source_name: Journal Topic
    source_tier: B
    source_type: journal
    hosts: [journal.example.test]
    fetch_transport: http
    entry_urls: ["https://journal.example.test/CN/"]
    topic_tags: [探测, 防护]
    default_queries: ["无人机 探测"]
    interaction_profile: static_listing
  - source_name: Browser Topic
    source_tier: A
    source_type: wemedia
    hosts: [browser.example.test]
    fetch_transport: browser_session
    entry_urls: ["https://browser.example.test/"]
    topic_tags: [低空]
    default_queries: ["低空"]
    interaction_profile: browser_search
excluded: []
""",
                encoding="utf-8",
            )
            registry = SourceRegistry.load(path)

            strategy = SourceStrategyPlanner(registry).plan(
                topic="低空无人机探测防护",
                allow_browser=False,
            )

        self.assertGreaterEqual(len(strategy.selected_sources), 2)
        self.assertEqual(
            [source.fetch_transport for source in strategy.selected_sources],
            ["http", "http"],
        )
        self.assertEqual(
            strategy.seed_urls,
            ["https://official.example.test/", "https://journal.example.test/CN/"],
        )
        self.assertIn("Browser Topic", [source.source_name for source in strategy.held_sources])

    def test_source_strategy_planner_prefers_diverse_source_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source_whitelist.yaml"
            path.write_text(
                """
version: 1
sources:
  - source_name: Official Alpha
    source_tier: A
    source_type: official
    hosts: [alpha.example.test]
    fetch_transport: http
    entry_urls: ["https://alpha.example.test/"]
    topic_tags: [通信]
    interaction_profile: static_listing
  - source_name: Official Beta
    source_tier: A
    source_type: official
    hosts: [beta.example.test]
    fetch_transport: http
    entry_urls: ["https://beta.example.test/"]
    topic_tags: [通信]
    interaction_profile: static_listing
  - source_name: Think Tank Perspective
    source_tier: B
    source_type: thinktank
    hosts: [thinktank.example.test]
    fetch_transport: http
    entry_urls: ["https://thinktank.example.test/reports"]
    topic_tags: [通信]
    interaction_profile: static_listing
excluded: []
""",
                encoding="utf-8",
            )
            registry = SourceRegistry.load(path)

            strategy = SourceStrategyPlanner(registry).plan(
                topic="战术通信保障能力缺口",
                allow_browser=False,
                min_sources=2,
            )

        self.assertEqual(
            [source.source_name for source in strategy.selected_sources],
            ["Official Alpha", "Think Tank Perspective"],
        )
        self.assertEqual(
            {source.source_type for source in strategy.selected_sources},
            {"official", "thinktank"},
        )

    def test_source_strategy_planner_derives_queries_from_topic_before_source_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source_whitelist.yaml"
            path.write_text(
                """
version: 1
sources:
  - source_name: Official Portal
    source_tier: A
    source_type: official
    hosts: [official.example.test]
    fetch_transport: http
    entry_urls: ["https://official.example.test/"]
    topic_tags: [unmanned, air_defense]
    default_queries: ["反无人机"]
    interaction_profile: site_search
  - source_name: Defense Media
    source_tier: B
    source_type: defense_media
    hosts: [media.example.test]
    fetch_transport: http
    entry_urls: ["https://media.example.test/"]
    topic_tags: [uav]
    default_queries: ["counter drone defense"]
    interaction_profile: static_listing
excluded: []
""",
                encoding="utf-8",
            )
            registry = SourceRegistry.load(path)

            strategy = SourceStrategyPlanner(registry).plan(
                topic="远程补给链受扰条件下的战术通信保障能力缺口",
                allow_browser=False,
            )

        first = strategy.selected_sources[0].to_dict()
        self.assertIn("planned_queries", first)
        self.assertEqual(first["planned_queries"][0], "远程补给链受扰条件下的战术通信保障能力缺口")
        self.assertTrue(
            any("战术通信" in query or "补给链" in query for query in first["planned_queries"]),
            first["planned_queries"],
        )
        self.assertNotIn(
            "反无人机",
            first["planned_queries"],
        )

    def test_source_strategy_planner_uses_source_language_for_planned_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source_whitelist.yaml"
            path.write_text(
                """
version: 1
sources:
  - source_name: 中文期刊
    source_tier: A
    source_type: journal
    hosts: [cn.example.test]
    fetch_transport: http
    entry_urls: ["https://cn.example.test/"]
    topic_tags: [补给, 通信]
    content_languages: [zh]
    interaction_profile: static_listing
  - source_name: English Think Tank
    source_tier: A
    source_type: thinktank
    hosts: [en.example.test]
    fetch_transport: http
    entry_urls: ["https://en.example.test/"]
    topic_tags: [logistics, communications]
    content_languages: [en]
    interaction_profile: static_listing
excluded: []
""",
                encoding="utf-8",
            )
            registry = SourceRegistry.load(path)

            strategy = SourceStrategyPlanner(registry).plan(
                topic="远程补给链受扰条件下的战术通信保障能力缺口",
                allow_browser=False,
                min_sources=2,
            )

        by_name = {source.source_name: source for source in strategy.selected_sources}
        zh_source = by_name["中文期刊"]
        en_source = by_name["English Think Tank"]

        self.assertEqual(zh_source.content_languages, ["zh"])
        self.assertEqual(zh_source.planned_queries[0], "远程补给链受扰条件下的战术通信保障能力缺口")
        self.assertIn("补给链", zh_source.planned_queries[1])
        self.assertEqual(en_source.content_languages, ["en"])
        self.assertIn("contested logistics", en_source.planned_queries[0])
        self.assertIn("tactical communications", en_source.planned_queries[0])
        self.assertFalse(any("\u4e00" <= char <= "\u9fff" for char in en_source.planned_queries[0]))

    def test_english_source_queries_are_translated_for_non_uav_topics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "source_whitelist.yaml"
            path.write_text(
                """
version: 1
sources:
  - source_name: English Relief Source
    source_tier: A
    source_type: thinktank
    hosts: [relief.example.test]
    fetch_transport: http
    entry_urls: ["https://relief.example.test/"]
    topic_tags: [rescue, cold, support]
    content_languages: [en]
    interaction_profile: static_listing
excluded: []
""",
                encoding="utf-8",
            )
            registry = SourceRegistry.load(path)

            strategy = SourceStrategyPlanner(registry).plan(
                topic="高寒地区联合救援保障能力缺口",
                allow_browser=False,
                min_sources=1,
            )

        source = strategy.selected_sources[0]
        query = source.planned_queries[0]

        self.assertIn("cold regions", query)
        self.assertIn("joint rescue", query)
        self.assertIn("support", query)
        self.assertIn("capability gap", query)
        self.assertFalse(any("\u4e00" <= char <= "\u9fff" for char in query))

    def test_source_strategy_round_trips_through_domain_store_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            whitelist_path = Path(tmp) / "source_whitelist.yaml"
            export_path = Path(tmp) / "domain-export.jsonl"
            append_path = Path(tmp) / "domain-append.jsonl"
            whitelist_path.write_text(
                """
version: 1
sources:
  - source_name: Strategy Source
    source_tier: A
    source_type: official
    hosts: [strategy.example.test]
    fetch_transport: http
    entry_urls: ["https://strategy.example.test/"]
    topic_tags: [通信]
    content_languages: [zh]
    interaction_profile: static_listing
excluded: []
""",
                encoding="utf-8",
            )
            registry = SourceRegistry.load(whitelist_path)
            strategy = SourceStrategyPlanner(registry).plan(
                topic="战术通信保障能力缺口",
                allow_browser=False,
                min_sources=1,
            )

            store = DomainStore()
            store.upsert_source_strategy(strategy)
            store.export_jsonl(export_path)
            loaded_export = DomainStore.load_jsonl(export_path)
            store.export_append_only_snapshot(append_path)
            loaded_append = DomainStore.load_jsonl(append_path)

        self.assertEqual(
            source_strategy_from_dict(strategy.to_dict()).to_dict(),
            strategy.to_dict(),
        )
        self.assertEqual(
            loaded_export.source_strategies[strategy.strategy_id].to_dict(),
            strategy.to_dict(),
        )
        self.assertEqual(
            loaded_append.source_strategies[strategy.strategy_id].to_dict(),
            strategy.to_dict(),
        )


if __name__ == "__main__":
    unittest.main()
