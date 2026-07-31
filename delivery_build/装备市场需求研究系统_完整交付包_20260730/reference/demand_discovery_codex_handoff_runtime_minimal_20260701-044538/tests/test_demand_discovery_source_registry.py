from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.models import (  # noqa: E402
    CandidateDemand,
    EvidenceCard,
    SourceRecord,
)
from knowledgegraph.demand_discovery.domain.source_registry import (  # noqa: E402
    SourceRegistry,
    default_source_whitelist_path,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402


NOW = datetime(2026, 6, 11, tzinfo=timezone.utc)


class DemandDiscoverySourceRegistryTests(unittest.TestCase):
    def test_load_validates_required_fields_and_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing_tier = Path(tmp) / "missing-tier.yaml"
            missing_tier.write_text(
                """
version: 1
sources:
  - source_name: Broken
    source_type: official
    hosts: [example.test]
    fetch_transport: http
""",
                encoding="utf-8",
            )
            bad_transport = Path(tmp) / "bad-transport.yaml"
            bad_transport.write_text(
                """
version: 1
sources:
  - source_name: Broken
    source_tier: A
    source_type: official
    hosts: [example.test]
    fetch_transport: ftp
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "source_tier"):
                SourceRegistry.load(missing_tier)
            with self.assertRaisesRegex(ValueError, "fetch_transport"):
                SourceRegistry.load(bad_transport)

    def test_match_uses_subdomain_path_and_most_specific_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "whitelist.yaml"
            path.write_text(
                """
version: 1
sources:
  - source_name: General
    source_tier: B
    source_type: defense_media
    hosts: [example.test]
    path_prefixes: []
    fetch_transport: http
    search: {type: none}
  - source_name: Specific
    source_tier: A
    source_type: official
    hosts: [example.test]
    path_prefixes: [/reports]
    fetch_transport: http
    search: {type: listing}
excluded:
  - source_name: Excluded
    hosts: [excluded.example.test]
    reason: no source chain
""",
                encoding="utf-8",
            )

            registry = SourceRegistry.load(path)

            self.assertEqual(
                registry.match("https://sub.example.test/reports/2026/a.html").source_name,
                "Specific",
            )
            self.assertEqual(
                registry.match("https://example.test/news/a.html").source_name,
                "General",
            )
            self.assertIsNone(registry.match("https://outside.example/a.html"))
            self.assertIsNone(registry.match("https://excluded.example.test/a.html"))
            self.assertEqual(
                [entry.source_name for entry in registry.search_entries()],
                ["Specific"],
            )

    def test_default_whitelist_covers_design_source_table(self) -> None:
        registry = SourceRegistry.load(default_source_whitelist_path())
        names = {entry.source_name for entry in registry.sources}

        for name in [
            "中国军网",
            "军事科学院期刊集群",
            "中国兵工学会",
            "英国国际战略研究所",
            "美国兰德公司",
            "美国战略与国际研究中心",
            "解放军报 / 中国军号",
            "简氏防务周刊",
            "Defense One",
            "中国军事期刊",
            "联合部队季刊（JFQ）",
            "International Security",
        ]:
            self.assertIn(name, names)

        china_military = next(
            entry for entry in registry.sources if entry.source_name == "中国军网"
        )
        self.assertIn("www.81.cn", china_military.hosts)
        self.assertEqual(
            registry.match("http://www.81.cn/").source_name,
            "中国军网",
        )
        self.assertEqual(
            registry.match("https://www.rand.org/pubs/research_reports.html").source_name,
            "美国兰德公司",
        )
        self.assertEqual(
            registry.match("https://www.defenseone.com/ideas/").source_tier,
            "B",
        )
        self.assertEqual(
            registry.match("https://direct.mit.edu/isec/article").source_name,
            "International Security",
        )
        self.assertEqual(
            registry.match("https://www.techxcope.com/about").source_name,
            "远望智库",
        )
        self.assertEqual(
            registry.match("https://warontherocks.com/2026/01/example/").source_name,
            "战争困境",
        )
        self.assertEqual(
            registry.match("https://www.xdfyjs.cn/CN/article/showArticle.do").source_name,
            "现代防御技术",
        )
        self.assertEqual(
            registry.match("https://www.bj.xinhuanet.com/xhsbk/sjjs.htm").source_name,
            "世界军事",
        )
        self.assertEqual(
            registry.match("https://zsyyb.cn/journal/browseissue.htm?journalid=10383").source_name,
            "中国军事期刊",
        )
        self.assertIsNone(registry.match("https://mp.weixin.qq.com/s/unsafe-broad-host"))
        self.assertIsNone(registry.match("https://www.sohu.com/a/123456_358040"))
        self.assertIsNone(registry.match("https://www.secrss.com/articles/12345"))

    def test_tier_status_cap_can_guard_domain_store(self) -> None:
        registry = SourceRegistry.load(default_source_whitelist_path())
        self.assertEqual(registry.tier_status_cap("A"), "demand_report")
        self.assertEqual(registry.tier_status_cap("B"), "demand_report")
        self.assertEqual(registry.tier_status_cap("C"), "researchable_signal")

        b_store = _seed_store("B", registry)
        accepted_b = b_store.upsert_candidate(_candidate("demand_report"))
        self.assertEqual(accepted_b.status, "demand_report")

        store = _seed_store("C", registry)

        with self.assertRaisesRegex(ValueError, "exceeds source tier cap"):
            store.upsert_candidate(_candidate("candidate_demand"))

        accepted = store.upsert_candidate(_candidate("researchable_signal"))
        self.assertEqual(accepted.status, "researchable_signal")


def _seed_store(source_tier: str, registry: SourceRegistry) -> DomainStore:
    store = DomainStore(tier_status_cap=registry.tier_status_cap)
    store.upsert_source(
        SourceRecord(
            source_id="src-1",
            title="Source",
            source_name="Fixture",
            source_tier=source_tier,
            source_type="journal",
            publish_time=NOW,
            url_or_path="https://example.test/source",
            summary_text="summary",
            summary_source="manual",
            collection_decision="use_as_evidence",
            author_or_org=None,
            is_repost=False,
            original_source=None,
            institutional_stance=None,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    store.upsert_evidence(
        EvidenceCard(
            evidence_id="ev-1",
            source_id="src-1",
            claim="claim",
            evidence_summary="summary",
            excerpt="excerpt",
            source_location="p1",
            evidence_assessment="strong",
            created_by="tester",
            created_at=NOW,
        )
    )
    return store


def _candidate(status: str) -> CandidateDemand:
    return CandidateDemand(
        candidate_id="cand-1",
        title="Candidate",
        demand_statement="Need capability.",
        status=status,
        evidence_ids=["ev-1"],
        open_questions=[],
        solution_signals=[],
        created_by="tester",
        created_at=NOW,
        updated_at=NOW,
    )


if __name__ == "__main__":
    unittest.main()
