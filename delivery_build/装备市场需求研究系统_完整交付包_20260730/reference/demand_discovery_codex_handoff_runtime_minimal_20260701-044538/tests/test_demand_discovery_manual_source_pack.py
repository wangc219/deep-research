from __future__ import annotations

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.manual_source_pack import (  # noqa: E402
    build_fake_source_pack_provider,
    build_manual_source_pack_prompt,
    load_manual_source_pack,
    run_manual_source_pack_sync,
)


PACK_PATH = (
    PROJECT_ROOT
    / "configs"
    / "demand_discovery"
    / "source_packs"
    / "manual_cuas_low_altitude_v0.json"
)
WEAK_PACK_PATH = (
    PROJECT_ROOT
    / "configs"
    / "demand_discovery"
    / "source_packs"
    / "manual_weak_trend_hotspot_v0.json"
)


class DemandDiscoveryManualSourcePackTests(unittest.TestCase):
    def test_load_manual_source_pack_validates_controlled_inputs(self) -> None:
        pack = load_manual_source_pack(PACK_PATH)

        self.assertEqual(pack.pack_id, "manual-cuas-low-altitude-v0")
        self.assertIn("create_source_record", pack.allowed_tools)
        self.assertNotIn("fetch_page", pack.allowed_tools)
        self.assertEqual(len(pack.sources), 5)
        self.assertEqual(
            pack.suggested_ids["candidate_id"],
            "cand-low-altitude-cuas-sensing-gap",
        )

    def test_prompt_includes_demand_type_decision_rule(self) -> None:
        prompt = build_manual_source_pack_prompt(load_manual_source_pack(PACK_PATH))

        self.assertIn("Demand type rule", prompt)
        self.assertIn("default to demand_type inferred", prompt)
        self.assertIn("only use explicit", prompt)

    def test_fake_pack_run_writes_reviewable_outputs_and_lineage(self) -> None:
        pack = load_manual_source_pack(PACK_PATH)
        provider = build_fake_source_pack_provider(pack)

        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir) / "manual-pack-test-run"
            inbox = run_dir / "inbox"
            inbox.mkdir(parents=True)
            (inbox / "next_turn.md").write_text("operator follow-up", encoding="utf-8")

            result = run_manual_source_pack_sync(
                provider=provider,
                source_pack_path=PACK_PATH,
                output_root=Path(temp_dir),
                run_id="manual-pack-test-run",
                endpoint_mode="fake",
                base_url="fake://provider",
                model="fake-pack-model",
            )

            for file_name in [
                "run_config.json",
                "domain.jsonl",
                "trace.jsonl",
                "session.jsonl",
                "report.md",
                "manual_review_checklist.md",
            ]:
                self.assertTrue((run_dir / file_name).exists(), file_name)
            self.assertEqual(len(list((inbox / "processed").glob("*_next_turn.md"))), 1)

            self.assertEqual(result.run_id, "manual-pack-test-run")
            self.assertEqual(result.source_count, 5)
            self.assertEqual(result.evidence_count, 5)
            self.assertEqual(
                result.candidate_id,
                "cand-low-altitude-cuas-sensing-gap",
            )
            self.assertEqual(result.audit_conclusion, "approved")
            self.assertGreaterEqual(result.trace_event_count, 8)
            self.assertEqual(
                result.lineage_event_types,
                [
                    "source_seen",
                    "source_seen",
                    "source_seen",
                    "source_seen",
                    "source_seen",
                    "evidence_created",
                    "evidence_created",
                    "evidence_created",
                    "evidence_created",
                    "evidence_created",
                    "candidate_created",
                    "audit_completed",
                    "evidence_updated",
                    "evidence_updated",
                    "evidence_updated",
                    "evidence_updated",
                    "evidence_updated",
                    "candidate_updated",
                    "report_consistency_checked",
                    "report_generated",
                ],
            )

            report_text = (run_dir / "report.md").read_text(encoding="utf-8")
            self.assertTrue(report_text.startswith("# "))
            self.assertIn("低空小型无人机", report_text)
            self.assertIn("Demand type: inferred", report_text)
            self.assertIn("## Run Metadata", report_text)
            self.assertIn("## Trace Lineage", report_text)
            self.assertIn("source_seen", report_text)
            self.assertNotIn("## Candidate Demand", report_text)
            self.assertNotIn("## Demand Report Body", report_text)

    def test_weak_fake_pack_records_audit_rework_without_report(self) -> None:
        pack = load_manual_source_pack(WEAK_PACK_PATH)
        provider = build_fake_source_pack_provider(pack)

        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_manual_source_pack_sync(
                provider=provider,
                source_pack_path=WEAK_PACK_PATH,
                output_root=Path(temp_dir),
                run_id="manual-weak-pack-test-run",
                endpoint_mode="fake",
                base_url="fake://provider",
                model="fake-pack-model",
                require_report=False,
            )
            run_dir = Path(temp_dir) / "manual-weak-pack-test-run"

            self.assertEqual(result.pack_id, "manual-weak-trend-hotspot-v0")
            self.assertEqual(result.audit_conclusion, "needs_revision")
            self.assertEqual(result.report_id, "")
            self.assertTrue((run_dir / "report.md").exists())
            report_text = (run_dir / "report.md").read_text(encoding="utf-8")
            self.assertIn("No DemandReport generated.", report_text)
            domain_text = (run_dir / "domain.jsonl").read_text(encoding="utf-8")
            self.assertIn('"conclusion": "needs_revision"', domain_text)
            self.assertIn('"verdict": "fail"', domain_text)
            self.assertIn("补充至少一条非 C/D 级证据", domain_text)

    def test_cli_fake_mode_runs_pack_and_writes_outputs(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "demand_discovery_manual_source_pack.py"),
                    "--mode",
                    "fake",
                    "--source-pack",
                    str(PACK_PATH),
                    "--output-root",
                    temp_dir,
                    "--run-id",
                    "manual-pack-cli-test",
                ],
                cwd=PROJECT_ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            run_dir = Path(temp_dir) / "manual-pack-cli-test"

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Run ID: manual-pack-cli-test", result.stdout)
            self.assertIn("Trace events:", result.stdout)
            self.assertTrue((run_dir / "domain.jsonl").exists())
            self.assertTrue((run_dir / "report.md").exists())
            self.assertNotIn("Authorization", result.stdout)

    def test_cli_real_mode_requires_configured_api_key(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
        env.pop("DEMAND_DISCOVERY_API_KEY", None)
        env["DEMAND_DISCOVERY_DOTENV"] = str(
            PROJECT_ROOT / "does-not-exist-demand-discovery.env"
        )

        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "demand_discovery_manual_source_pack.py"),
                "--mode",
                "real",
                "--source-pack",
                str(PACK_PATH),
                "--dry-run-provider-request",
            ],
            cwd=PROJECT_ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing API key env DEMAND_DISCOVERY_API_KEY", result.stderr)

    def test_cli_real_dry_run_prints_sanitized_request(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
        env["DEMAND_DISCOVERY_API_KEY"] = "secret-pack-key"

        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "demand_discovery_manual_source_pack.py"),
                "--mode",
                "real",
                "--source-pack",
                str(PACK_PATH),
                "--dry-run-provider-request",
                "--endpoint-mode",
                "responses_compatible",
                "--base-url",
                "https://api.example.test",
                "--model",
                "gpt-pack",
                "--run-id",
                "dry-run-id",
            ],
            cwd=PROJECT_ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("mode: real", result.stdout)
        self.assertIn("run_id: dry-run-id", result.stdout)
        self.assertIn("pack: manual-cuas-low-altitude-v0", result.stdout)
        self.assertIn("url: https://api.example.test/v1/responses", result.stdout)
        self.assertNotIn("secret-pack-key", result.stdout)
        self.assertNotIn("Authorization", result.stdout)


if __name__ == "__main__":
    unittest.main()
