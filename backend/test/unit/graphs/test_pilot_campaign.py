from __future__ import annotations

import hashlib
import json
from collections import Counter

import pytest
from pydantic import ValidationError

from platform_core.knowledge.training.pilot_campaign import (
    AuthoritativeDocumentBinding,
    build_annotation_campaign_spec,
    load_pilot_selection_manifest,
    pilot_manifest_coverage_blockers,
    safe_manifest_summary,
)


def test_selection_manifest_is_strict_and_drops_source_paths(tmp_path):
    path = tmp_path / "gold-selection.jsonl"
    rows = _rows()
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")

    manifest = load_pilot_selection_manifest(path)
    summary = safe_manifest_summary(manifest)

    assert len(manifest.entries) == 300
    assert manifest.manifest_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    assert summary["split_counts"] == {"dev": 30, "test": 60, "train": 210}
    assert summary["source_type_counts"] == {"paper": 150, "patent": 150}
    assert "path" not in manifest.entries[0].model_dump()
    assert "title" not in manifest.entries[0].model_dump()
    assert "path" not in json.dumps(summary)
    assert pilot_manifest_coverage_blockers(manifest) == []


def test_campaign_coverage_allows_all_papers_but_requires_bilingual_and_six_domains(tmp_path):
    rows = _rows()
    for row in rows:
        row["source_type"] = "paper"
        row["language"] = "zh"
        row["domain"] = ""
    path = tmp_path / "single-source.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    manifest = load_pilot_selection_manifest(path)

    assert pilot_manifest_coverage_blockers(manifest) == [
        "missing_bilingual_coverage",
        "insufficient_domain_coverage",
    ]
    with pytest.raises(ValueError, match="覆盖不足"):
        build_annotation_campaign_spec(
            manifest=manifest,
            bindings=[],
            name="invalid-pilot",
            ontology_version="defense-kg-1.0",
            guideline_version="defense-kg-annotation-v1",
            annotator_ids=["ann-a", "ann-b"],
            arbitrator_id="expert",
        )


def test_campaign_accepts_explicit_chinese_only_profile(tmp_path):
    rows = _rows()
    for row in rows:
        row["source_type"] = "paper"
        row["language"] = "zh"
        row["acceptance_languages"] = ["zh"]
    path = tmp_path / "chinese-only.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    manifest = load_pilot_selection_manifest(path)

    assert manifest.acceptance_languages == ["zh"]
    assert pilot_manifest_coverage_blockers(manifest) == []


def test_selection_manifest_rejects_duplicate_content(tmp_path):
    rows = _rows()
    rows[1]["content_sha256"] = rows[0]["content_sha256"]
    path = tmp_path / "duplicate.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    with pytest.raises(ValidationError, match="重复内容"):
        load_pilot_selection_manifest(path)


def test_campaign_spec_uses_authoritative_ids_and_distinct_human_roles(tmp_path):
    path = tmp_path / "gold-selection.jsonl"
    rows = _rows()
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    manifest = load_pilot_selection_manifest(path)
    bindings = [
        AuthoritativeDocumentBinding(
            manifest_document_id=item.document_id,
            authoritative_document_id=f"file-{index:03d}",
            document_version=2,
        )
        for index, item in enumerate(manifest.entries)
    ]

    spec = build_annotation_campaign_spec(
        manifest=manifest,
        bindings=bindings,
        name="pilot",
        ontology_version="defense-kg-1.0",
        guideline_version="defense-kg-annotation-v1",
        annotator_ids=["ann-a", "ann-b"],
        arbitrator_id="expert",
    )

    assert len(spec.assignments) == 300
    assert spec.assignments[0].document_id == "file-000"
    assert spec.assignments[0].document_version == 2
    assert Counter(item.split for item in spec.assignments) == {"train": 210, "dev": 30, "test": 60}

    with pytest.raises(ValidationError, match="仲裁专家"):
        build_annotation_campaign_spec(
            manifest=manifest,
            bindings=bindings,
            name="pilot",
            ontology_version="defense-kg-1.0",
            guideline_version="defense-kg-annotation-v1",
            annotator_ids=["ann-a", "ann-b"],
            arbitrator_id="ann-a",
        )


def _rows() -> list[dict]:
    splits = ["train"] * 210 + ["dev"] * 30 + ["test"] * 60
    return [
        {
            "document_id": f"src_{index:064x}",
            "split": split,
            "source_type": "paper" if index % 2 == 0 else "patent",
            "language": "zh" if index % 3 else "en",
            "domain": f"domain-{index % 6}",
            "domain_annotation_kind": "human",
            "content_sha256": f"{index:064x}",
            "title": f"sensitive title {index}",
            "path": f"/private/corpus/{index}.pdf",
        }
        for index, split in enumerate(splits)
    ]
