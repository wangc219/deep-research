"""Batch PDF-to-Markdown preparation for journal issue directories.

This is a thin orchestration layer over prepare_chunks.py. It keeps the
existing MinerU/chunking pipeline unchanged while writing outputs to the
normalized data/processed/<journal>/<issue>/ layout.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JOURNALS = ("zsdd", "ktfy", "xxdkjs", "dzdkjs", "hkxb")
DEFAULT_RAW_ROOT = PROJECT_ROOT / "data" / "raw"
DEFAULT_PROCESSED_ROOT = PROJECT_ROOT / "data" / "processed"
DEFAULT_MANIFEST = DEFAULT_PROCESSED_ROOT / "journal_prepare_batch_manifest.jsonl"
LEGACY_ZSDD_2026_02 = (
    DEFAULT_PROCESSED_ROOT
    / "extraction_experiments"
    / "zsdd_2026_02_full_ocr"
)


@dataclass(frozen=True)
class IssueJob:
    journal: str
    issue: str
    source_root: Path
    dataset_root: Path
    pdf_count: int
    markdown_count: int
    chunks_exists: bool
    pdf_limit: int = 0


def main() -> int:
    args = parse_args()
    raw_root = resolve_path(args.raw_root)
    processed_root = resolve_path(args.processed_root)
    manifest_path = resolve_path(args.manifest)
    jobs = discover_issue_jobs(
        raw_root=raw_root,
        processed_root=processed_root,
        journals=args.journal,
        issues=args.issue,
    )
    jobs = order_jobs_by_issue(jobs, issue_order=args.issue_order)
    if args.target_pdfs_per_journal:
        jobs = select_jobs_for_target_per_journal(
            jobs,
            target=args.target_pdfs_per_journal,
        )
    if args.limit_issues and args.limit_issues > 0:
        jobs = jobs[: args.limit_issues]

    if args.migrate_legacy_zsdd:
        migrate_legacy_zsdd_2026_02(processed_root=processed_root, dry_run=args.dry_run)
        jobs = discover_issue_jobs(
            raw_root=raw_root,
            processed_root=processed_root,
            journals=args.journal,
            issues=args.issue,
        )
        jobs = order_jobs_by_issue(jobs, issue_order=args.issue_order)
        if args.target_pdfs_per_journal:
            jobs = select_jobs_for_target_per_journal(
                jobs,
                target=args.target_pdfs_per_journal,
            )
        if args.limit_issues and args.limit_issues > 0:
            jobs = jobs[: args.limit_issues]

    print(
        json.dumps(
            {
                "job_count": len(jobs),
                "pdf_count": sum(job.pdf_count for job in jobs),
                "manifest": str(manifest_path),
            },
            ensure_ascii=False,
        )
    )

    failures = 0
    for index, job in enumerate(jobs, start=1):
        print(f"[{index}/{len(jobs)}] {job.journal}/{job.issue} pdfs={job.pdf_count}")
        status = run_issue_job(job, args=args, manifest_path=manifest_path)
        if status["status"] not in {"success", "skipped_existing_complete", "dry_run"}:
            failures += 1
            if args.stop_on_error:
                break
    return 1 if failures else 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch convert journal PDFs to Markdown using prepare_chunks.py.",
    )
    parser.add_argument(
        "--journal",
        action="append",
        choices=DEFAULT_JOURNALS,
        default=[],
        help="Journal key to process. Repeatable. Defaults to zsdd, ktfy, xxdkjs.",
    )
    parser.add_argument(
        "--issue",
        action="append",
        default=[],
        help="Issue directory to process, for example 2026-02. Repeatable.",
    )
    parser.add_argument("--raw-root", default=str(DEFAULT_RAW_ROOT))
    parser.add_argument("--processed-root", default=str(DEFAULT_PROCESSED_ROOT))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0, help="PDF limit passed to prepare_chunks.py; 0 means all.")
    parser.add_argument(
        "--target-pdfs-per-journal",
        type=int,
        default=0,
        help=(
            "Select enough issue jobs so each journal reaches this many Markdown files. "
            "The final selected issue receives a per-job PDF limit when needed."
        ),
    )
    parser.add_argument(
        "--issue-order",
        choices=["oldest", "newest"],
        default="oldest",
        help="Issue processing order within each journal.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument(
        "--subprocess-timeout-seconds",
        type=int,
        default=2400,
        help="Maximum wall-clock seconds for one issue subprocess; 0 disables this guard.",
    )
    parser.add_argument("--poll-interval-seconds", type=int, default=10)
    parser.add_argument("--max-chars", type=int, default=1600)
    parser.add_argument("--token-env-var", default="MINERU_TOKEN")
    parser.add_argument("--model-version", default="vlm")
    parser.add_argument("--language", default="ch")
    parser.add_argument("--skip-existing-complete", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--migrate-legacy-zsdd", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--force-mineru", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit-issues", type=int, default=0)
    return parser.parse_args(argv)


def discover_issue_jobs(
    *,
    raw_root: Path,
    processed_root: Path,
    journals: list[str],
    issues: list[str],
) -> list[IssueJob]:
    selected_journals = journals or list(DEFAULT_JOURNALS)
    selected_issues = set(issues)
    jobs: list[IssueJob] = []
    for journal in selected_journals:
        journal_root = raw_root / journal
        for papers_dir in sorted(journal_root.glob("*/papers")):
            issue = papers_dir.parent.name
            if selected_issues and issue not in selected_issues:
                continue
            pdf_count = len(list(papers_dir.glob("*.pdf")))
            if pdf_count == 0:
                continue
            dataset_root = processed_root / journal / issue
            markdown_count = len(list((dataset_root / "mineru_raw").rglob("*.md")))
            jobs.append(
                IssueJob(
                    journal=journal,
                    issue=issue,
                    source_root=papers_dir,
                    dataset_root=dataset_root,
                    pdf_count=pdf_count,
                    markdown_count=markdown_count,
                    chunks_exists=(dataset_root / "chunks.jsonl").exists(),
                )
            )
    return jobs


def order_jobs_by_issue(jobs: list[IssueJob], *, issue_order: str) -> list[IssueJob]:
    if issue_order == "oldest":
        return jobs
    grouped: dict[str, list[IssueJob]] = {}
    for job in jobs:
        grouped.setdefault(job.journal, []).append(job)
    ordered: list[IssueJob] = []
    for journal_jobs in grouped.values():
        ordered.extend(reversed(journal_jobs))
    return ordered


def select_jobs_for_target_per_journal(
    jobs: list[IssueJob],
    *,
    target: int,
) -> list[IssueJob]:
    if target <= 0:
        return jobs

    existing_by_journal: dict[str, int] = {}
    for job in jobs:
        existing_by_journal[job.journal] = existing_by_journal.get(job.journal, 0) + min(
            job.markdown_count,
            job.pdf_count,
        )

    selected: list[IssueJob] = []
    planned_by_journal = dict(existing_by_journal)
    for job in jobs:
        current = planned_by_journal.get(job.journal, 0)
        if current >= target:
            continue
        pending_pdf_count = max(job.pdf_count - min(job.markdown_count, job.pdf_count), 0)
        if pending_pdf_count <= 0:
            continue
        remaining = target - current
        if pending_pdf_count > remaining:
            selected.append(replace(job, pdf_limit=remaining))
            planned_by_journal[job.journal] = current + remaining
        else:
            selected.append(replace(job, pdf_limit=0))
            planned_by_journal[job.journal] = current + pending_pdf_count
    return selected


def run_issue_job(job: IssueJob, *, args: argparse.Namespace, manifest_path: Path) -> dict[str, Any]:
    if args.skip_existing_complete and is_complete(job) and not args.force_mineru:
        status = build_status(job, status="skipped_existing_complete", returncode=0, elapsed_seconds=0.0)
        append_manifest(manifest_path, status)
        print(json.dumps(status, ensure_ascii=False))
        return status

    command = build_prepare_command(job, args=args)
    if args.dry_run:
        status = build_status(job, status="dry_run", returncode=0, elapsed_seconds=0.0, command=command)
        print(json.dumps(status, ensure_ascii=False))
        return status

    start = time.time()
    timeout = args.subprocess_timeout_seconds or None
    try:
        completed = subprocess.run(command, cwd=PROJECT_ROOT, timeout=timeout)
        returncode = completed.returncode
        status_name = "success" if returncode == 0 else "failed"
    except subprocess.TimeoutExpired:
        returncode = 124
        status_name = "timeout"
    elapsed = round(time.time() - start, 3)
    refreshed = refresh_job(job)
    status = build_status(
        refreshed,
        status=status_name,
        returncode=returncode,
        elapsed_seconds=elapsed,
        command=command,
    )
    append_manifest(manifest_path, status)
    print(json.dumps(status, ensure_ascii=False))
    return status


def build_prepare_command(job: IssueJob, *, args: argparse.Namespace) -> list[str]:
    limit = job.pdf_limit if job.pdf_limit > 0 else args.limit
    command = [
        sys.executable,
        "scripts/extraction_experiment/prepare_chunks.py",
        "--source-root",
        str(job.source_root),
        "--work-root",
        str(job.dataset_root.parent),
        "--dataset-name",
        job.issue,
        "--limit",
        str(limit),
        "--batch-size",
        str(args.batch_size),
        "--timeout-seconds",
        str(args.timeout_seconds),
        "--poll-interval-seconds",
        str(args.poll_interval_seconds),
        "--max-chars",
        str(args.max_chars),
        "--token-env-var",
        args.token_env_var,
        "--model-version",
        args.model_version,
        "--language",
        args.language,
    ]
    if args.force_mineru:
        command.append("--force-mineru")
    if should_skip_mineru_for_existing_markdown(job, args=args):
        command.append("--skip-mineru")
    return command


def should_skip_mineru_for_existing_markdown(job: IssueJob, *, args: argparse.Namespace) -> bool:
    if args.force_mineru:
        return False
    return job.markdown_count >= job.pdf_count


def is_complete(job: IssueJob) -> bool:
    return job.markdown_count >= job.pdf_count and job.chunks_exists


def refresh_job(job: IssueJob) -> IssueJob:
    markdown_count = len(list((job.dataset_root / "mineru_raw").rglob("*.md")))
    return IssueJob(
        journal=job.journal,
        issue=job.issue,
        source_root=job.source_root,
        dataset_root=job.dataset_root,
        pdf_count=job.pdf_count,
        markdown_count=markdown_count,
        chunks_exists=(job.dataset_root / "chunks.jsonl").exists(),
    )


def build_status(
    job: IssueJob,
    *,
    status: str,
    returncode: int,
    elapsed_seconds: float,
    command: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "journal": job.journal,
        "issue": job.issue,
        "status": status,
        "returncode": returncode,
        "pdf_count": job.pdf_count,
        "markdown_count": job.markdown_count,
        "chunks_exists": job.chunks_exists,
        "pdf_limit": job.pdf_limit,
        "source_root": str(job.source_root),
        "dataset_root": str(job.dataset_root),
        "elapsed_seconds": elapsed_seconds,
        "command": command or [],
        "created_at": int(time.time()),
    }


def append_manifest(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(row, ensure_ascii=False) + "\n")


def migrate_legacy_zsdd_2026_02(*, processed_root: Path, dry_run: bool) -> None:
    source = LEGACY_ZSDD_2026_02
    target = processed_root / "zsdd" / "2026-02"
    if not source.exists():
        return
    if dry_run:
        print(json.dumps({"migrate_legacy_zsdd": str(source), "target": str(target)}, ensure_ascii=False))
        return
    for name in ["mineru_raw", "mineru_artifacts"]:
        source_path = source / name
        target_path = target / name
        if source_path.exists():
            shutil.copytree(source_path, target_path, dirs_exist_ok=True)
    for name in ["chunks.jsonl", "prepare_chunks_report.json"]:
        source_path = source / name
        if source_path.exists():
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target / name)


def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (PROJECT_ROOT / path).resolve()


if __name__ == "__main__":
    raise SystemExit(main())
