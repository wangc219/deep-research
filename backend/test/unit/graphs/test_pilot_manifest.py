from __future__ import annotations

from collections import Counter

import pytest

from platform_core.knowledge.training.pilot_manifest import (
    GOLD_SPLIT_COUNTS,
    build_pilot_inventory_report,
    scan_pilot_corpus,
    select_gold_documents,
)


def test_scan_manifest_hashes_and_deduplicates_content(tmp_path):
    paper_root = tmp_path / "papers"
    patent_root = tmp_path / "patents"
    paper_root.mkdir()
    patent_root.mkdir()
    (paper_root / "中文论文.pdf").write_bytes(b"same-content")
    (patent_root / "duplicate.pdf").write_bytes(b"same-content")
    (patent_root / "english-patent.pdf").write_bytes(b"patent-content")

    manifest, report = scan_pilot_corpus(paper_roots=[paper_root], patent_roots=[patent_root])

    assert len(manifest) == 2
    assert all(len(item["content_sha256"]) == 64 for item in manifest)
    assert {item["language"] for item in manifest} == {"zh", "en"}
    assert len(report["duplicate_content_groups"]) == 1
    assert report["actual"]["source_documents"] == 2
    assert report["ready"] is False


def test_report_requires_real_paper_patent_bilingual_and_domain_coverage():
    manifest = []
    for index in range(1000):
        manifest.append(_item(index, "paper", "zh" if index else "en", f"domain-{index % 6}"))

    report = build_pilot_inventory_report(manifest)

    assert report["ready"] is True
    assert report["failed_criteria"] == []
    assert report["actual"]["source_documents"] == 1000
    assert report["actual"]["paper_documents"] == 1000
    assert report["actual"]["patent_documents"] == 0


def test_gold_selection_is_deterministic_document_level_and_uses_fixed_split_counts():
    manifest = [
        _item(
            index,
            "paper" if index % 3 else "patent",
            "zh" if index % 4 else "en",
            f"domain-{index % 6}",
        )
        for index in range(360)
    ]

    first = select_gold_documents(manifest)
    second = select_gold_documents(list(reversed(manifest)))

    assert first == second
    assert len(first) == 300
    assert len({item["document_id"] for item in first}) == 300
    assert Counter(item["split"] for item in first) == GOLD_SPLIT_COUNTS


def test_gold_selection_fails_closed_when_source_coverage_is_incomplete():
    manifest = [_item(index, "paper", "zh", "") for index in range(300)]

    with pytest.raises(ValueError, match="覆盖不足"):
        select_gold_documents(manifest)

    exploratory = select_gold_documents(manifest, allow_incomplete_coverage=True)
    assert len(exploratory) == 300


def test_gold_selection_rejects_ai_prelabel_domain_manifest():
    manifest = [_item(index, "paper", "zh", f"domain-{index % 6}") for index in range(300)]
    manifest[0]["domain_annotation"]["kind"] = "ai_prelabel"

    with pytest.raises(ValueError, match="只接受显式 human"):
        select_gold_documents(manifest, acceptance_languages=["zh"])


def test_chinese_only_acceptance_is_explicit_and_still_requires_six_domains():
    manifest = [_item(index, "paper", "zh", f"domain-{index % 6}") for index in range(1000)]

    report = build_pilot_inventory_report(manifest, acceptance_languages=["zh"])
    selected = select_gold_documents(manifest, acceptance_languages=["zh"])

    assert report["ready"] is True
    assert report["acceptance_languages"] == ["zh"]
    assert len(selected) == 300
    assert {tuple(item["acceptance_languages"]) for item in selected} == {("zh",)}


def _item(index: int, source_type: str, language: str, domain: str) -> dict:
    digest = f"{index:064x}"
    return {
        "document_id": f"src_{digest}",
        "source_type": source_type,
        "language": language,
        "domain": domain,
        "domain_annotation": {"kind": "human"},
        "title": f"document-{index}",
        "path": f"/corpus/{index}.pdf",
        "content_sha256": digest,
        "file_size": 100,
    }
