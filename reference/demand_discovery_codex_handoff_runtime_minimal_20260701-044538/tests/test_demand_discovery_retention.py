from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.domain.models import EvidenceCard  # noqa: E402
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.retention import (  # noqa: E402
    RetentionConfig,
    cleanup_outputs,
)
from scripts.demand_discovery_cleanup import main as cleanup_main  # noqa: E402


NOW = datetime(2026, 6, 15, tzinfo=timezone.utc)


class DemandDiscoveryRetentionTests(unittest.TestCase):
    def test_cleanup_respects_layers_and_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_runtime = _touch(root / "scheduled" / "runner.log", days_old=10)
            old_processed = _touch(root / "runs" / "run-1" / "inbox" / "processed" / "old_steer.md", days_old=10)
            old_html = _touch(root / "runs" / "run-1" / "artifacts" / "html-old.html", days_old=20)
            fresh_html = _touch(root / "runs" / "run-1" / "artifacts" / "html-fresh.html", days_old=1)
            long_term = _touch(root / "runs" / "run-1" / "domain.jsonl", days_old=500)

            result = cleanup_outputs(
                root,
                RetentionConfig(
                    mid_term_keep_days=90,
                    short_term_keep_days=14,
                    runtime_log_keep_days=7,
                ),
                now=NOW,
                apply=False,
            )

            self.assertEqual(
                {item.path for item in result.to_delete},
                {old_runtime, old_processed, old_html},
            )
            self.assertTrue(old_runtime.exists())
            self.assertTrue(old_html.exists())
            self.assertTrue(fresh_html.exists())
            self.assertTrue(long_term.exists())

    def test_cleanup_apply_deletes_unreferenced_old_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old_html = _touch(root / "runs" / "run-1" / "artifacts" / "html-old.html", days_old=20)

            cleanup_outputs(
                root,
                RetentionConfig(short_term_keep_days=14),
                now=NOW,
                apply=True,
            )

            self.assertFalse(old_html.exists())

    def test_referenced_artifact_is_protected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = _touch(root / "runs" / "run-1" / "artifacts" / "text-abc123.txt", days_old=90)
            store = DomainStore()
            store.upsert_evidence(
                EvidenceCard(
                    evidence_id="ev-1",
                    source_id="",
                    claim="claim",
                    evidence_summary="summary",
                    excerpt="excerpt",
                    source_location="text:abc123#para:1",
                    evidence_assessment="strong",
                    created_by="tester",
                    created_at=NOW,
                )
            )

            result = cleanup_outputs(
                root,
                RetentionConfig(short_term_keep_days=14),
                now=NOW,
                apply=True,
                domain_store=store,
            )

            self.assertTrue(artifact.exists())
            self.assertEqual(result.protected_refs, {"text:abc123"})

    def test_cleanup_cli_auto_loads_domain_jsonl_before_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = _touch(root / "runs" / "run-1" / "artifacts" / "text-abc123.txt", days_old=90)
            store = DomainStore()
            store.upsert_evidence(
                EvidenceCard(
                    evidence_id="ev-1",
                    source_id="",
                    claim="claim",
                    evidence_summary="summary",
                    excerpt="excerpt",
                    source_location="text:abc123#para:1",
                    evidence_assessment="strong",
                    created_by="tester",
                    created_at=NOW,
                )
            )
            store.export_jsonl(root / "runs" / "run-1" / "domain.jsonl")
            config = root / "retention.yaml"
            config.write_text(
                "\n".join(
                    [
                        "mid_term:",
                        "  keep_days: 90",
                        "short_term:",
                        "  keep_days: 14",
                        "runtime_log:",
                        "  keep_days: 7",
                    ]
                ),
                encoding="utf-8",
            )

            exit_code = cleanup_main(
                [
                    "--root",
                    str(root),
                    "--config",
                    str(config),
                    "--apply",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(artifact.exists())


def _touch(path: Path, *, days_old: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    timestamp = (NOW - timedelta(days=days_old)).timestamp()
    path.touch()
    import os

    os.utime(path, (timestamp, timestamp))
    return path


if __name__ == "__main__":
    unittest.main()
