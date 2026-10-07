import json
import multiprocessing
from types import SimpleNamespace

from equipment_deep_research.domain.models import EvidenceCard
from equipment_deep_research.tools.source_index import SourcePriorityIndex


def _evidence(url: str) -> EvidenceCard:
    return EvidenceCard(
        evidence_id="ev-source-index",
        source_title="Verified equipment program page",
        source_url=url,
        source_tier="A",
        claim="A current program milestone is documented.",
        excerpt="Program milestone text.",
        source_location="artifact:test#p1",
        quality_assessment="accepted",
        created_by="weapon_equipment",
    )


def _record_source_in_process(path: str, index: int) -> None:
    SourcePriorityIndex(path).record(
        agent_id="weapon_equipment",
        topic=f"并发主题 {index}",
        evidence=_evidence(f"https://example.org/program-{index}"),
        material={"status": "fetched", "formal_evidence_allowed": True},
        assessment=SimpleNamespace(decision="accepted"),
    )


def test_curated_equipment_sources_are_available_without_history(tmp_path) -> None:
    index = SourcePriorityIndex(tmp_path / "source-index.json")

    rows = index.recommend("weapon_equipment", "装备能力缺口", limit=20)

    assert any(row["url"].startswith("https://www.gao.gov/") for row in rows)
    assert any(row["url"].endswith(".cn/") for row in rows)
    assert any(
        row.get("source_region") == "domestic"
        for row in rows
        if row["url"].endswith(".cn/")
    )
    assert all(row["learned"] is False for row in rows)


def test_accepted_materialized_source_is_learned_across_runs(tmp_path) -> None:
    path = tmp_path / "source-index.json"
    url = "https://www.gao.gov/products/example-program"
    index = SourcePriorityIndex(path)
    index.record(
        agent_id="weapon_equipment",
        topic="西太装备能力缺口",
        evidence=_evidence(url),
        material={"status": "fetched", "formal_evidence_allowed": True},
        assessment=SimpleNamespace(decision="accepted"),
    )

    rows = SourcePriorityIndex(path).recommend(
        "weapon_equipment",
        "西太装备能力缺口",
        limit=5,
    )

    assert rows[0]["url"] == url
    assert rows[0]["learned"] is True


def test_failed_source_is_not_recommended_as_learned(tmp_path) -> None:
    path = tmp_path / "source-index.json"
    url = "https://blocked.example/report"
    index = SourcePriorityIndex(path)
    index.record(
        agent_id="combat_scenario",
        topic="场景研究",
        evidence=_evidence(url),
        material={"status": "fetch_failed", "formal_evidence_allowed": False},
        assessment=SimpleNamespace(decision="accepted"),
    )

    rows = SourcePriorityIndex(path).recommend(
        "combat_scenario",
        "场景研究",
        limit=20,
    )

    assert all(row["url"] != url for row in rows)


def test_source_index_supports_parallel_process_writers(tmp_path) -> None:
    path = tmp_path / "source-index.json"
    context = multiprocessing.get_context("fork")
    processes = [
        context.Process(
            target=_record_source_in_process,
            args=(str(path), index),
        )
        for index in range(4)
    ]

    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=5)
        assert process.exitcode == 0

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["sources"]) == 4
