from __future__ import annotations

import csv
import json

import pytest

from platform_core.knowledge.training.pilot_domain_annotation import (
    PILOT_DOMAIN_CATALOG,
    apply_domain_annotations,
    build_domain_annotation_package,
)


def test_build_domain_annotation_package_has_no_preannotations_and_balances_batches(tmp_path):
    manifest = tmp_path / "source.jsonl"
    _write_manifest(manifest, 12)

    report = build_domain_annotation_package(
        manifest_path=manifest,
        output_root=tmp_path / "distribution",
        batch_count=5,
    )

    assert report["document_count"] == 12
    assert sorted(report["batch_sizes"].values()) == [2, 2, 2, 3, 3]
    tasks = _read_csv(tmp_path / "distribution" / "all-domain-tasks.csv")
    assert len(tasks) == 12
    assert all(not item["primary_domain_code"] for item in tasks)
    assert all("PENDING" in item["annotator_account"] for item in tasks)
    assert all(item["document_path"].startswith("papers/") for item in tasks)
    assert all(not item["document_path"].startswith("/") for item in tasks)
    assert len(_read_csv(tmp_path / "distribution" / "reference" / "domain-catalog.csv")) == 6
    readme = (tmp_path / "distribution" / "README.md").read_text(encoding="utf-8")
    assert "apply \\\n  --manifest" in readme
    assert "../artifacts/distribution/batches/domain-batch-01.csv" in readme
    assert "knowledge-graph-domain-annotation-999-20261030/batches" not in readme


def test_apply_domain_annotations_requires_complete_valid_human_results(tmp_path):
    manifest = tmp_path / "source.jsonl"
    _write_manifest(manifest, 6)
    distribution = tmp_path / "distribution"
    build_domain_annotation_package(
        manifest_path=manifest,
        output_root=distribution,
        batch_count=1,
        annotator_accounts=["reviewer-uid"],
    )
    tasks_path = distribution / "all-domain-tasks.csv"
    tasks = _read_csv(tasks_path)
    domain_codes = [item["code"] for item in PILOT_DOMAIN_CATALOG]
    for index, task in enumerate(tasks):
        task["primary_domain_code"] = domain_codes[index]
        task["confidence"] = "high"
        task["status"] = "completed"
    _write_csv(tasks_path, tasks)

    report = apply_domain_annotations(
        manifest_path=manifest,
        task_paths=[tasks_path],
        output_manifest_path=tmp_path / "annotated.jsonl",
        output_report_path=tmp_path / "report.json",
    )

    annotated = [json.loads(line) for line in (tmp_path / "annotated.jsonl").read_text().splitlines()]
    assert report["completed_documents"] == 6
    assert report["inventory"]["criteria"][-1]["passed"] is True
    assert {item["domain"] for item in annotated} == set(domain_codes)
    assert all(item["domain_annotation"]["annotator_account"] == "reviewer-uid" for item in annotated)
    assert all(item["domain_annotation"]["kind"] == "human" for item in annotated)
    assert report["formal_gold_eligible"] is True


def test_apply_domain_annotations_separates_ai_prelabels_from_human_results(tmp_path):
    manifest = tmp_path / "source.jsonl"
    _write_manifest(manifest, 1)
    distribution = tmp_path / "distribution"
    build_domain_annotation_package(
        manifest_path=manifest,
        output_root=distribution,
        batch_count=1,
        annotator_accounts=["reviewer-uid"],
    )
    tasks_path = distribution / "all-domain-tasks.csv"
    tasks = _read_csv(tasks_path)
    tasks[0].update(
        {
            "primary_domain_code": PILOT_DOMAIN_CATALOG[0]["code"],
            "confidence": "medium",
            "status": "completed",
            "notes": "AI领域初筛（seed=104729），待真人确认。",
        }
    )
    _write_csv(tasks_path, tasks)

    with pytest.raises(ValueError, match="AI 预标不得作为真人"):
        apply_domain_annotations(
            manifest_path=manifest,
            task_paths=[tasks_path],
            output_manifest_path=tmp_path / "invalid-human.jsonl",
            output_report_path=tmp_path / "invalid-human.json",
        )

    report = apply_domain_annotations(
        manifest_path=manifest,
        task_paths=[tasks_path],
        output_manifest_path=tmp_path / "ai-prelabels.jsonl",
        output_report_path=tmp_path / "ai-prelabels.json",
        annotation_kind="ai_prelabel",
    )
    annotated = [json.loads(line) for line in (tmp_path / "ai-prelabels.jsonl").read_text().splitlines()]

    assert report["annotation_kind"] == "ai_prelabel"
    assert report["formal_gold_eligible"] is False
    assert annotated[0]["domain_annotation"]["kind"] == "ai_prelabel"


def test_build_domain_annotation_package_holds_failed_parser_source(tmp_path):
    manifest = tmp_path / "source.jsonl"
    _write_manifest(manifest, 3)
    sources = [json.loads(line) for line in manifest.read_text().splitlines()]
    preflight = tmp_path / "parser-routing-preflight.jsonl"
    preflight.write_text(
        "".join(
            json.dumps(
                {
                    "document_id": source["document_id"],
                    "content_sha256": source["content_sha256"],
                    "status": "failed" if index == 1 else "success",
                    "route": "failed" if index == 1 else "complex_layout",
                    "error_code": "invalid_pdf_structure" if index == 1 else None,
                }
            )
            + "\n"
            for index, source in enumerate(sources)
        )
    )

    report = build_domain_annotation_package(
        manifest_path=manifest,
        output_root=tmp_path / "distribution",
        batch_count=2,
        parser_preflight_path=preflight,
    )

    tasks = _read_csv(tmp_path / "distribution" / "all-domain-tasks.csv")
    held = [item for item in tasks if item["status"] == "source_hold"]
    assert report["parser_preflight_verified"] is True
    assert report["source_hold_count"] == 1
    assert report["source_distribution_ready"] is False
    assert held[0]["document_id"] == "doc-1"
    assert "invalid_pdf_structure" in held[0]["notes"]
    readme = (tmp_path / "distribution" / "README.md").read_text(encoding="utf-8")
    assert "status=source_hold" in readme
    assert "待替换来源 1 篇" in readme


def test_build_domain_annotation_package_rejects_preflight_hash_mismatch(tmp_path):
    manifest = tmp_path / "source.jsonl"
    _write_manifest(manifest, 1)
    preflight = tmp_path / "parser-routing-preflight.jsonl"
    preflight.write_text(
        json.dumps(
            {
                "document_id": "doc-0",
                "content_sha256": "f" * 64,
                "status": "success",
                "route": "complex_layout",
            }
        )
        + "\n"
    )

    with pytest.raises(ValueError, match="SHA-256"):
        build_domain_annotation_package(
            manifest_path=manifest,
            output_root=tmp_path / "distribution",
            parser_preflight_path=preflight,
        )


def test_build_domain_annotation_package_reuses_completed_annotations_by_unchanged_hash(tmp_path):
    manifest = tmp_path / "source.jsonl"
    _write_manifest(manifest, 3)
    previous = tmp_path / "previous"
    build_domain_annotation_package(
        manifest_path=manifest,
        output_root=previous,
        batch_count=1,
        annotator_accounts=["domain-reviewer"],
    )
    previous_tasks_path = previous / "all-domain-tasks.csv"
    previous_tasks = _read_csv(previous_tasks_path)
    for index, task in enumerate(previous_tasks):
        task.update(
            {
                "primary_domain_code": PILOT_DOMAIN_CATALOG[index]["code"],
                "confidence": "high",
                "status": "completed",
                "notes": f"人工结论 {index}",
            }
        )
    _write_csv(previous_tasks_path, previous_tasks)

    sources = [json.loads(line) for line in manifest.read_text().splitlines()]
    sources[-1].update(
        {
            "document_id": "replacement-doc",
            "content_sha256": "f" * 64,
            "title": "替换论文",
            "filename": "replacement.pdf",
            "path": "/papers/replacement.pdf",
            "relative_path": "replacement.pdf",
        }
    )
    replacement_manifest = tmp_path / "replacement-source.jsonl"
    replacement_manifest.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in sources))

    report = build_domain_annotation_package(
        manifest_path=replacement_manifest,
        output_root=tmp_path / "rebased",
        batch_count=1,
        prior_task_paths=[previous_tasks_path],
    )

    rebased = _read_csv(tmp_path / "rebased" / "all-domain-tasks.csv")
    assert report["inherited_completed_count"] == 2
    assert report["stale_completed_count"] == 1
    assert [item["status"] for item in rebased] == ["completed", "completed", "unassigned"]
    assert rebased[0]["annotator_account"] == "domain-reviewer"
    assert rebased[0]["notes"] == "人工结论 0"
    assert not rebased[-1]["primary_domain_code"]
    readme = (tmp_path / "rebased" / "README.md").read_text(encoding="utf-8")
    assert "--reuse-tasks" in readme
    assert "继承的已完成标注：2 篇" in readme


def test_apply_domain_annotations_rejects_tampered_hash_and_pending_account(tmp_path):
    manifest = tmp_path / "source.jsonl"
    _write_manifest(manifest, 1)
    distribution = tmp_path / "distribution"
    build_domain_annotation_package(manifest_path=manifest, output_root=distribution, batch_count=1)
    tasks_path = distribution / "all-domain-tasks.csv"
    tasks = _read_csv(tasks_path)
    tasks[0].update(
        {
            "content_sha256": "0" * 64,
            "primary_domain_code": PILOT_DOMAIN_CATALOG[0]["code"],
            "confidence": "high",
            "status": "completed",
        }
    )
    _write_csv(tasks_path, tasks)

    with pytest.raises(ValueError, match="SHA-256"):
        apply_domain_annotations(
            manifest_path=manifest,
            task_paths=[tasks_path],
            output_manifest_path=tmp_path / "annotated.jsonl",
            output_report_path=tmp_path / "report.json",
        )


def _write_manifest(path, count):
    rows = [
        {
            "document_id": f"doc-{index}",
            "content_sha256": f"{index + 1:064x}",
            "title": f"论文 {index}",
            "filename": f"paper-{index}.pdf",
            "path": f"/papers/paper-{index}.pdf",
            "relative_path": f"paper-{index}.pdf",
            "source_type": "paper",
            "language": "zh",
            "domain": "",
            "file_size": 1,
        }
        for index in range(count)
    ]
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))


def _read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
