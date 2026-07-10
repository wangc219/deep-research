from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.autonomous_research import (  # noqa: E402
    _append_trace_event,
    _fixture_judge_provider_factory,
    run_autonomous_research_sync,
)
from knowledgegraph.demand_discovery.domain.models import (  # noqa: E402
    AuditReport,
    EvidenceCard,
    SourceRecord,
)
from knowledgegraph.demand_discovery.domain.open_search import (  # noqa: E402
    OpenSourceBodyArtifact,
    OpenSourceLead,
    SourceQualityAssessment,
    open_search_plan_from_dict,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import AssistantContentBlock  # noqa: E402
from knowledgegraph.demand_discovery.llm.fake_provider import FakeProvider, FakeResponse  # noqa: E402
from knowledgegraph.demand_discovery.llm.types import AssistantMessage  # noqa: E402


class DemandDiscoveryAutonomousResearchRunnerTests(unittest.TestCase):
    def test_cli_real_defaults_read_provider_config_from_dotenv(self) -> None:
        from scripts import demand_discovery_autonomous_research as autonomous_cli

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dotenv = root / ".env"
            dotenv.write_text(
                '\n'.join(
                    [
                        '$env:DEMAND_DISCOVERY_ENDPOINT_MODE="codex_backend"',
                        '$env:DEMAND_DISCOVERY_BASE_URL="https://codex.example.test"',
                        '$env:DEMAND_DISCOVERY_ENDPOINT_PATH="/codex/responses"',
                        '$env:DEMAND_DISCOVERY_MODEL="gpt-5.5"',
                        '$env:DEMAND_DISCOVERY_API_KEY_ENV="CUSTOM_DD_KEY"',
                        '$env:CUSTOM_DD_KEY="sk-test"',
                    ]
                ),
                encoding="utf-8",
            )
            captured: dict[str, object] = {}

            def fake_run_autonomous_research_sync(**kwargs):
                captured.update(kwargs)
                run_dir = Path(kwargs["output_root"]) / str(kwargs["run_id"])
                return SimpleNamespace(
                    run_id=str(kwargs["run_id"]),
                    run_dir=run_dir,
                    source_strategy_id="strategy-test",
                    round_summary_path=run_dir / "round_summary.json",
                    domain_path=run_dir / "domain.jsonl",
                    trace_path=run_dir / "trace.jsonl",
                )

            with patch.dict(os.environ, {"DEMAND_DISCOVERY_DOTENV": str(dotenv)}, clear=True):
                with patch.object(
                    autonomous_cli,
                    "run_autonomous_research_sync",
                    side_effect=fake_run_autonomous_research_sync,
                ):
                    exit_code = autonomous_cli.main(
                        [
                            "--mode",
                            "real",
                            "--topic",
                            "高寒地区联合救援保障能力缺口",
                            "--output-root",
                            str(root / "runs"),
                            "--run-id",
                            "cli-real-env-defaults",
                        ]
                    )

        self.assertEqual(exit_code, 0)
        self.assertEqual(captured["endpoint_mode"], "codex_backend")
        self.assertEqual(captured["base_url"], "https://codex.example.test")
        self.assertEqual(captured["endpoint_path"], "/codex/responses")
        self.assertEqual(captured["model"], "gpt-5.5")
        self.assertEqual(captured["api_key_env"], "CUSTOM_DD_KEY")

    def test_cli_codex_mode_routes_to_independent_workflow(self) -> None:
        from scripts import demand_discovery_autonomous_research as autonomous_cli

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codex_home = root / "codex-home"
            codex_home.mkdir()
            captured: dict[str, object] = {}

            def fake_run_codex_workflow_sync(config):
                captured["topic"] = config.topic
                captured["output_root"] = config.output_root
                captured["run_id"] = config.run_id
                captured["source_whitelist_path"] = config.source_whitelist_path
                captured["codex_home"] = config.codex_home
                captured["codex_model"] = config.codex_model
                captured["reasoning_effort"] = config.reasoning_effort
                captured["timeout_seconds"] = config.timeout_seconds
                captured["enable_web_search"] = config.enable_web_search
                captured["max_worker_tasks_per_round"] = config.max_worker_tasks_per_round
                captured["max_report_rewrites"] = config.max_report_rewrites
                run_dir = Path(config.output_root) / str(config.run_id)
                return SimpleNamespace(
                    run_id=str(config.run_id),
                    run_dir=run_dir,
                    source_strategy_id="strategy-codex",
                    round_summary_path=run_dir / "round_summary.json",
                    domain_path=run_dir / "domain.jsonl",
                    trace_path=run_dir / "trace.jsonl",
                    report_path=run_dir / "report.md",
                )

            with patch.object(
                autonomous_cli,
                "run_codex_workflow_sync",
                side_effect=fake_run_codex_workflow_sync,
                create=True,
            ), patch.object(
                autonomous_cli,
                "run_autonomous_research_sync",
                side_effect=AssertionError("main chain should not run for codex mode"),
            ):
                exit_code = autonomous_cli.main(
                    [
                        "--mode",
                        "codex",
                        "--topic",
                        "低空无人机探测预警能力缺口",
                        "--output-root",
                        str(root / "runs"),
                        "--run-id",
                        "cli-codex",
                        "--source-whitelist",
                        str(root / "source_whitelist.yaml"),
                        "--codex-home",
                        str(codex_home),
                        "--codex-model",
                        "gpt-5.5",
                        "--codex-reasoning-effort",
                        "medium",
                        "--codex-timeout",
                        "123",
                        "--codex-max-worker-tasks-per-round",
                        "2",
                        "--codex-max-report-rewrites",
                        "3",
                        "--codex-no-search",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(captured["topic"], "低空无人机探测预警能力缺口")
        self.assertEqual(captured["run_id"], "cli-codex")
        self.assertEqual(captured["codex_home"], codex_home)
        self.assertEqual(captured["codex_model"], "gpt-5.5")
        self.assertEqual(captured["reasoning_effort"], "medium")
        self.assertEqual(captured["timeout_seconds"], 123)
        self.assertIs(captured["enable_web_search"], False)
        self.assertEqual(captured["max_worker_tasks_per_round"], 2)
        self.assertEqual(captured["max_report_rewrites"], 3)

    def test_fake_topic_only_run_writes_source_strategy_and_first_worker_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whitelist = root / "source_whitelist.yaml"
            whitelist.write_text(
                """
version: 1
sources:
  - source_name: Official Source
    source_tier: A
    source_type: official
    hosts: [official.example.test]
    fetch_transport: http
    entry_urls: ["https://official.example.test/"]
    topic_tags: [低空, 无人机]
    default_queries: ["低空 无人机"]
    interaction_profile: static_listing
  - source_name: Journal Source
    source_tier: B
    source_type: journal
    hosts: [journal.example.test]
    fetch_transport: http
    entry_urls: ["https://journal.example.test/CN/"]
    topic_tags: [探测, 防护]
    default_queries: ["无人机 探测 防护"]
    interaction_profile: static_listing
excluded: []
""",
                encoding="utf-8",
            )

            result = run_autonomous_research_sync(
                mode="fake",
                topic="低空小型无人机威胁下的探测、预警与防护能力缺口",
                output_root=root / "runs",
                run_id="topic-only-fake",
                max_rounds=1,
                source_whitelist_path=whitelist,
            )
            summary = json.loads(result.round_summary_path.read_text(encoding="utf-8"))
            domain_rows = [
                json.loads(line)
                for line in result.domain_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(result.run_id, "topic-only-fake")
        self.assertEqual(summary["source_strategy"]["topic"], "低空小型无人机威胁下的探测、预警与防护能力缺口")
        self.assertGreaterEqual(len(summary["source_strategy"]["selected_sources"]), 2)
        self.assertEqual(len(summary["rounds"]), 1)
        self.assertEqual(summary["rounds"][0]["status"], "planned")
        self.assertGreaterEqual(len(summary["worker_tasks"]), 1)
        self.assertIn("discover_articles", summary["worker_tasks"][0]["tools"])
        self.assertIn("SourceStrategy", {row["type"] for row in domain_rows})

    def test_real_mode_requires_api_configuration_and_does_not_emit_fake_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whitelist = root / "source_whitelist.yaml"
            whitelist.write_text(
                """
version: 1
sources:
  - source_name: Official Source
    source_tier: A
    source_type: official
    hosts: [official.example.test]
    fetch_transport: http
    entry_urls: ["https://official.example.test/"]
    topic_tags: [低空, 无人机]
    default_queries: ["低空 无人机"]
    interaction_profile: static_listing
  - source_name: Journal Source
    source_tier: B
    source_type: journal
    hosts: [journal.example.test]
    fetch_transport: http
    entry_urls: ["https://journal.example.test/CN/"]
    topic_tags: [探测, 防护]
    default_queries: ["无人机 探测 防护"]
    interaction_profile: static_listing
excluded: []
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "missing API key env DD_TEST_MISSING_KEY"):
                run_autonomous_research_sync(
                    mode="real",
                    topic="低空小型无人机威胁下的探测、预警与防护能力缺口",
                    output_root=root / "runs",
                    run_id="real-without-api",
                    max_rounds=2,
                    source_whitelist_path=whitelist,
                    api_key_env="DD_TEST_MISSING_KEY",
                )

            run_dir = root / "runs" / "real-without-api"
            if run_dir.exists():
                produced_text = "\n".join(
                    path.read_text(encoding="utf-8")
                    for path in run_dir.glob("*")
                    if path.is_file()
                )
                self.assertNotIn("Fake autonomous audit", produced_text)

    def test_real_mode_enters_phase5_controller_and_passes_browser_to_network_worker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whitelist = root / "source_whitelist.yaml"
            whitelist.write_text(
                """
version: 1
sources:
  - source_name: Official Source
    source_tier: A
    source_type: official
    hosts: [official.example.test]
    fetch_transport: http
    entry_urls: ["https://official.example.test/"]
    topic_tags: [低空, 无人机]
    default_queries: ["低空 无人机"]
    interaction_profile: static_listing
  - source_name: Journal Source
    source_tier: B
    source_type: journal
    hosts: [journal.example.test]
    fetch_transport: http
    entry_urls: ["https://journal.example.test/CN/"]
    topic_tags: [探测, 防护]
    default_queries: ["无人机 探测 防护"]
    interaction_profile: static_listing
excluded: []
""",
                encoding="utf-8",
            )
            captured: dict[str, object] = {}

            async def fake_run_network_worker_round(**kwargs):
                captured.update(kwargs)
                run_dir = Path(kwargs["output_root"]) / str(kwargs["run_id"])
                run_dir.mkdir(parents=True, exist_ok=True)
                domain_path = run_dir / "domain.jsonl"
                trace_path = run_dir / "trace.jsonl"
                _write_network_worker_domain_fixture(
                    domain_path,
                    round_id=str(kwargs["run_id"]),
                    seed_url=str(kwargs["seed_urls"][0]),
                )
                trace_path.write_text("", encoding="utf-8")
                return SimpleNamespace(
                    candidate_id="cand-real",
                    report_id="report-real",
                    evidence_ids=[],
                    trace_event_count=0,
                    report_trace_event_count=0,
                    run_dir=run_dir,
                    domain_path=domain_path,
                    trace_path=trace_path,
                )

            with patch(
                "knowledgegraph.demand_discovery.network_research.run_network_worker_round",
                side_effect=fake_run_network_worker_round,
            ), patch(
                "knowledgegraph.demand_discovery.autonomous_research._real_judge_provider_factory",
                return_value=_fixture_judge_provider_factory(
                    topic="低空小型无人机威胁下的探测、预警与防护能力缺口"
                ),
            ), patch(
                "knowledgegraph.demand_discovery.autonomous_research._real_reporter_provider_factory",
                return_value=_fixture_reporter_provider_factory(),
            ), patch(
                "knowledgegraph.demand_discovery.autonomous_research._real_context_curator_provider_factory",
                return_value=_fixture_reporter_provider_factory(),
            ), patch(
                "knowledgegraph.demand_discovery.autonomous_research._run_real_audit_worker",
                side_effect=_fake_real_audit_worker,
            ):
                run_autonomous_research_sync(
                    mode="real",
                    topic="低空小型无人机威胁下的探测、预警与防护能力缺口",
                    output_root=root / "runs",
                    run_id="real-browser",
                    max_rounds=2,
                    source_whitelist_path=whitelist,
                    api_key="test-api-key",
                    allow_browser=True,
                )

            self.assertIs(captured.get("allow_browser"), True)
            source_guidance = captured.get("source_guidance")
            self.assertIsInstance(source_guidance, list)
            self.assertEqual(len(source_guidance), 2)
            self.assertIn("planned_queries", source_guidance[0])
            self.assertIn("content_languages", source_guidance[0])
            summary = json.loads(
                (root / "runs" / "real-browser" / "round_summary.json").read_text(
                    encoding="utf-8"
                )
            )
            rows = [
                json.loads(line)
                for line in (root / "runs" / "real-browser" / "domain.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            ]
            trace_events = [
                json.loads(line)["event_type"]
                for line in (root / "runs" / "real-browser" / "trace.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            ]

            self.assertEqual(summary["real_execution"], "phase5_research_loop_with_network_workers")
            self.assertEqual(len(summary["rounds"]), 1)
            self.assertEqual(summary["rounds"][-1]["status"], "stopped")
            self.assertEqual(summary["candidate_synthesis"]["status"], "synthesized")
            self.assertIn("audit", summary)
            self.assertIn("report", summary)
            self.assertIn("ResearchRound", {row["type"] for row in rows})
            self.assertIn("ReadingQueue", {row["type"] for row in rows})
            self.assertIn("JudgementReport", {row["type"] for row in rows})
            self.assertIn("candidate_synthesized", trace_events)
            self.assertLess(
                trace_events.index("judgement_recorded"),
                trace_events.index("candidate_synthesized"),
            )

    def test_real_mode_writes_demand_report_with_b_tier_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whitelist = root / "source_whitelist.yaml"
            whitelist.write_text(
                """
version: 1
sources:
  - source_name: Defense Media Source
    source_tier: B
    source_type: defense_media
    hosts: [media.example.test]
    fetch_transport: http
    entry_urls: ["https://media.example.test/"]
    topic_tags: [低空, 无人机]
    default_queries: ["低空 无人机"]
    interaction_profile: static_listing
excluded: []
""",
                encoding="utf-8",
            )

            async def fake_run_network_worker_round(**kwargs):
                run_dir = Path(kwargs["output_root"]) / str(kwargs["run_id"])
                run_dir.mkdir(parents=True, exist_ok=True)
                domain_path = run_dir / "domain.jsonl"
                trace_path = run_dir / "trace.jsonl"
                _write_network_worker_domain_fixture(
                    domain_path,
                    round_id=str(kwargs["run_id"]),
                    seed_url=str(kwargs["seed_urls"][0]),
                    source_name="Defense Media Source",
                    source_tier="B",
                    source_type="defense_media",
                )
                trace_path.write_text("", encoding="utf-8")
                return SimpleNamespace(
                    evidence_ids=[],
                    trace_event_count=0,
                    report_trace_event_count=0,
                    run_id=str(kwargs["run_id"]),
                    run_dir=run_dir,
                    domain_path=domain_path,
                    trace_path=trace_path,
                )

            with patch(
                "knowledgegraph.demand_discovery.network_research.run_network_worker_round",
                side_effect=fake_run_network_worker_round,
            ), patch(
                "knowledgegraph.demand_discovery.autonomous_research._real_judge_provider_factory",
                return_value=_fixture_judge_provider_factory(
                    topic="低空小型无人机威胁下的探测、预警与防护能力缺口"
                ),
            ), patch(
                "knowledgegraph.demand_discovery.autonomous_research._real_reporter_provider_factory",
                return_value=_fixture_reporter_provider_factory(),
            ), patch(
                "knowledgegraph.demand_discovery.autonomous_research._real_context_curator_provider_factory",
                return_value=_fixture_reporter_provider_factory(),
            ), patch(
                "knowledgegraph.demand_discovery.autonomous_research._run_real_audit_worker",
                side_effect=_fake_real_audit_worker,
            ), patch(
                "knowledgegraph.demand_discovery.autonomous_research._render_autonomous_report_body",
                side_effect=AssertionError("template body used"),
            ):
                result = run_autonomous_research_sync(
                    mode="real",
                    topic="低空小型无人机威胁下的探测、预警与防护能力缺口",
                    output_root=root / "runs",
                    run_id="real-b-tier-report",
                    max_rounds=1,
                    source_whitelist_path=whitelist,
                    api_key="test-api-key",
                )

            summary = json.loads(result.round_summary_path.read_text(encoding="utf-8"))
            rows = [
                json.loads(line)
                for line in result.domain_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            trace_events = [
                json.loads(line)
                for line in result.trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            candidates = [
                row["payload"]
                for row in rows
                if row["type"] == "CandidateDemand"
            ]

            self.assertEqual(summary["candidate_synthesis"]["status"], "synthesized")
            self.assertEqual(summary["report"]["report_mode"], "real")
            self.assertEqual(summary["report"]["review_status"], "needs_revision")
            self.assertIn("## 证据", summary["report"]["body"])
            self.assertIn("## 待解决问题", summary["report"]["body"])
            self.assertNotIn("## Evidence", summary["report"]["body"])
            self.assertNotIn("## Open Questions", summary["report"]["body"])
            self.assertNotIn("storage_status", summary["report"])
            self.assertEqual(candidates[0]["status"], "demand_report")
            self.assertIn("DemandReport", {row["type"] for row in rows})
            self.assertTrue((result.run_dir / "report.md").exists())
            self.assertIn(
                "## 证据",
                (result.run_dir / "report.md").read_text(encoding="utf-8"),
            )
            self.assertIn("report_generated", [item["event_type"] for item in trace_events])
            self.assertIn(
                "audit_worker_completed",
                [item["event_type"] for item in trace_events],
            )
            self.assertLess(
                [item["event_type"] for item in trace_events].index("candidate_synthesized"),
                [item["event_type"] for item in trace_events].index("audit_worker_completed"),
            )
            self.assertLess(
                [item["event_type"] for item in trace_events].index("audit_worker_completed"),
                [item["event_type"] for item in trace_events].index("report_generated"),
            )

    def test_real_mode_report_trace_refs_open_search_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whitelist = root / "source_whitelist.yaml"
            whitelist.write_text(
                """
version: 1
sources:
  - source_name: Official Source
    source_tier: A
    source_type: official
    hosts: [official.example.test]
    fetch_transport: http
    entry_urls: ["https://official.example.test/"]
    topic_tags: [保障]
    default_queries: ["远海保障"]
    interaction_profile: static_listing
excluded: []
""",
                encoding="utf-8",
            )
            captured: list[dict[str, object]] = []

            async def fake_run_network_worker_round(**kwargs):
                captured.append(dict(kwargs))
                run_dir = Path(kwargs["output_root"]) / str(kwargs["run_id"])
                run_dir.mkdir(parents=True, exist_ok=True)
                domain_path = run_dir / "domain.jsonl"
                trace_path = run_dir / "trace.jsonl"
                if kwargs.get("allow_open_search"):
                    _write_open_network_worker_domain_fixture(
                        domain_path,
                        open_search_plan_payload=dict(kwargs["open_search_plan_payload"]),
                    )
                else:
                    domain_path.write_text("", encoding="utf-8")
                trace_path.write_text("", encoding="utf-8")
                return SimpleNamespace(
                    evidence_ids=[],
                    trace_event_count=0,
                    report_trace_event_count=0,
                    run_id=str(kwargs["run_id"]),
                    run_dir=run_dir,
                    domain_path=domain_path,
                    trace_path=trace_path,
                )

            with patch(
                "knowledgegraph.demand_discovery.network_research.run_network_worker_round",
                side_effect=fake_run_network_worker_round,
            ), patch(
                "knowledgegraph.demand_discovery.autonomous_research._real_judge_provider_factory",
                return_value=_fixture_judge_provider_factory(topic="远海保障能力缺口"),
            ), patch(
                "knowledgegraph.demand_discovery.autonomous_research._real_reporter_provider_factory",
                return_value=_fixture_reporter_provider_factory(),
            ), patch(
                "knowledgegraph.demand_discovery.autonomous_research._real_context_curator_provider_factory",
                return_value=_fixture_reporter_provider_factory(),
            ), patch(
                "knowledgegraph.demand_discovery.autonomous_research._run_real_audit_worker",
                side_effect=_fake_real_audit_worker,
            ):
                result = run_autonomous_research_sync(
                    mode="real",
                    topic="远海保障能力缺口",
                    output_root=root / "runs",
                    run_id="real-open-search-lineage",
                    max_rounds=2,
                    source_whitelist_path=whitelist,
                    api_key="test-api-key",
                )

            trace_events = [
                json.loads(line)
                for line in result.trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            report_event = next(
                item for item in trace_events if item["event_type"] == "report_generated"
            )
            refs = set(report_event["input_refs"])
            summary = json.loads(result.round_summary_path.read_text(encoding="utf-8"))

        self.assertIs(captured[0]["allow_open_search"], False)
        self.assertIs(captured[1]["allow_open_search"], True)
        self.assertIn("osp-", str(captured[1]["open_search_plan_id"]))
        self.assertIn(str(captured[1]["open_search_plan_id"]), refs)
        self.assertIn("osl-open", refs)
        self.assertIn("qa-open", refs)
        self.assertEqual(summary["open_search_plans"][0]["status"], "completed")

    def test_real_mode_audit_needs_revision_triggers_open_search_repair_round(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whitelist = root / "source_whitelist.yaml"
            whitelist.write_text(
                """
version: 1
sources:
  - source_name: Official Source
    source_tier: A
    source_type: official
    hosts: [official.example.test]
    fetch_transport: http
    entry_urls: ["https://official.example.test/"]
    topic_tags: [保障]
    default_queries: ["远海保障"]
    interaction_profile: static_listing
excluded: []
""",
                encoding="utf-8",
            )
            captured: list[dict[str, object]] = []
            audit_calls: list[dict[str, object]] = []

            async def fake_run_network_worker_round(**kwargs):
                captured.append(dict(kwargs))
                run_dir = Path(kwargs["output_root"]) / str(kwargs["run_id"])
                run_dir.mkdir(parents=True, exist_ok=True)
                domain_path = run_dir / "domain.jsonl"
                trace_path = run_dir / "trace.jsonl"
                if kwargs.get("allow_open_search"):
                    suffix = "-repair" if len(captured) >= 3 else ""
                    _write_open_network_worker_domain_fixture(
                        domain_path,
                        open_search_plan_payload=dict(kwargs["open_search_plan_payload"]),
                        suffix=suffix,
                    )
                else:
                    domain_path.write_text("", encoding="utf-8")
                trace_path.write_text("", encoding="utf-8")
                return SimpleNamespace(
                    evidence_ids=[],
                    trace_event_count=0,
                    report_trace_event_count=0,
                    run_id=str(kwargs["run_id"]),
                    run_dir=run_dir,
                    domain_path=domain_path,
                    trace_path=trace_path,
                )

            async def fake_audit_worker(**kwargs):
                audit_calls.append(dict(kwargs))
                if len(audit_calls) == 1:
                    return await _fake_needs_revision_audit_worker(**kwargs)
                return await _fake_real_audit_worker(**kwargs)

            with patch(
                "knowledgegraph.demand_discovery.network_research.run_network_worker_round",
                side_effect=fake_run_network_worker_round,
            ), patch(
                "knowledgegraph.demand_discovery.autonomous_research._real_judge_provider_factory",
                return_value=_fixture_judge_provider_factory(topic="远海保障能力缺口"),
            ), patch(
                "knowledgegraph.demand_discovery.autonomous_research._real_reporter_provider_factory",
                return_value=_fixture_reporter_provider_factory(),
            ), patch(
                "knowledgegraph.demand_discovery.autonomous_research._real_context_curator_provider_factory",
                return_value=_fixture_reporter_provider_factory(),
            ), patch(
                "knowledgegraph.demand_discovery.autonomous_research._run_real_audit_worker",
                side_effect=fake_audit_worker,
            ):
                result = run_autonomous_research_sync(
                    mode="real",
                    topic="远海保障能力缺口",
                    output_root=root / "runs",
                    run_id="real-audit-repair",
                    max_rounds=3,
                    source_whitelist_path=whitelist,
                    api_key="test-api-key",
                )

            summary = json.loads(result.round_summary_path.read_text(encoding="utf-8"))
            trace_events = [
                json.loads(line)["event_type"]
                for line in result.trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(len(captured), 3)
        self.assertIs(captured[2]["allow_open_search"], True)
        repair_payload = dict(captured[2]["open_search_plan_payload"])
        self.assertIn("补充独立来源交叉验证", " ".join(repair_payload["queries"]))
        self.assertEqual(len(audit_calls), 2)
        self.assertEqual(len(summary["rounds"]), 3)
        self.assertIn("audit_repair_plan", summary["trace"])
        self.assertEqual(trace_events.count("audit_worker_completed"), 2)


def _write_network_worker_domain_fixture(
    path: Path,
    *,
    round_id: str,
    seed_url: str,
    source_name: str = "Official Source",
    source_tier: str = "A",
    source_type: str = "official",
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    source_id = f"src-{abs(hash(round_id))}"
    evidence_id = f"ev-{abs(hash(round_id))}"
    rows = [
        {
            "type": "SourceRecord",
            "payload": {
                "source_id": source_id,
                "title": "Network worker article",
                "source_name": source_name,
                "source_tier": source_tier,
                "source_type": source_type,
                "publish_time": now,
                "url_or_path": seed_url,
                "summary_text": "network worker fixture source",
                "summary_source": "fixture",
                "collection_decision": "use_as_evidence",
                "author_or_org": None,
                "is_repost": False,
                "original_source": None,
                "institutional_stance": None,
                "created_at": now,
                "updated_at": now,
            },
        },
        {
            "type": "EvidenceCard",
            "payload": {
                "evidence_id": evidence_id,
                "source_id": source_id,
                "claim": "需要低空小型无人机探测预警与防护能力闭环",
                "evidence_summary": "worker evidence supports the autonomous research topic",
                "excerpt": "低空小型无人机威胁要求探测、预警与防护闭环。",
                "source_location": "text:fixture#para:0",
                "evidence_assessment": "strong",
                "created_by": "fixture-network-worker",
                "created_at": now,
            },
        },
    ]
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
        + "\n",
        encoding="utf-8",
    )


def _fixture_reporter_provider_factory():
    def factory() -> FakeProvider:
        provider = FakeProvider()
        provider.set_responses(
            [FakeResponse(factory=_fixture_reporter_response), FakeResponse(text="done")]
        )
        return provider

    return factory


def _fixture_reporter_response(context, state) -> AssistantMessage:
    del state
    prompt_text = "\n\n".join(str(message.content) for message in context.messages)
    working_memory = _json_section(prompt_text, "Working Memory")
    if "report_context_candidate_pool" in working_memory:
        pool = dict(working_memory["report_context_candidate_pool"])
        materials = [item for item in pool.get("materials", []) if isinstance(item, dict)]
        curated_items = []
        for index, material in enumerate(materials, start=1):
            allowed = list(material.get("allowed_report_uses", []) or [])
            if not allowed:
                continue
            curated_items.append(
                {
                    "item_id": f"cur-{index}",
                    "material_ids": [str(material["material_id"])],
                    "report_use": "core" if "core" in allowed else str(allowed[0]),
                    "claim_summary": str(material.get("summary") or material.get("title") or ""),
                    "curation_reason": "fixture curator selected permitted material",
                }
            )
        return AssistantMessage(
            content=[
                AssistantContentBlock(
                    type="tool_call",
                    id="call-curate",
                    name="record_report_context_curation",
                    arguments={
                        "bundle_id": str(pool["bundle_id"]),
                        "curated_items": curated_items,
                    },
                )
            ]
        )
    bundle = dict(working_memory["report_context_bundle"])
    candidate_id = str(bundle["candidate_id"])
    audit_id = str(bundle["audit_id"])
    evidence_ids = [str(item) for item in bundle.get("allowed_evidence_ids", [])]
    if not evidence_ids:
        for material in list(bundle.get("materials", [])):
            if isinstance(material, dict):
                evidence_ids.extend(
                    str(item) for item in material.get("refs", {}).get("evidence_ids", [])
                )
    evidence_ids = list(dict.fromkeys(evidence_ids))
    lineage = [item for item in bundle.get("lineage_trace", []) if isinstance(item, dict)]
    domain_trace_ids = [
        str(item["domain_trace_id"])
        for item in lineage
        if item.get("event_type") in {"candidate_synthesized", "audit_completed"}
        and item.get("domain_trace_id")
    ]
    caveats = [str(item) for item in bundle.get("required_caveats", []) if str(item)]
    caveat_text = "\n".join(f"- {item}" for item in caveats) or "- 当前报告按审计状态降级表达。"
    body = (
        "## 阶段性结论\n"
        f"围绕“{bundle.get('topic', '')}”，当前只能形成可追溯的阶段性判断。\n\n"
        "## 证据\n"
        + "\n".join(f"- {evidence_id}" for evidence_id in evidence_ids)
        + "\n\n## 矛盾与限制\n"
        + caveat_text
        + "\n\n## 待解决问题\n"
        "- 继续补充独立来源交叉验证。"
    )
    return AssistantMessage(
        content=[
            AssistantContentBlock(
                type="tool_call",
                id="call-report",
                name="generate_demand_report",
                arguments={
                    "report_id": f"report-{candidate_id}",
                    "candidate_id": candidate_id,
                    "title": "需求挖掘阶段性报告",
                    "body": body,
                    "evidence_ids": evidence_ids,
                    "audit_id": audit_id,
                    "domain_trace_ids": domain_trace_ids,
                    "report_context_bundle_id": str(bundle["bundle_id"]),
                },
            )
        ]
    )


def _json_section(text: str, section: str) -> dict[str, object]:
    marker = f"# {section}\n"
    start = text.index(marker) + len(marker)
    end = text.find("\n\n# ", start)
    raw = text[start:] if end < 0 else text[start:end]
    return json.loads(raw)


async def _fake_real_audit_worker(**kwargs) -> AuditReport:
    store = kwargs["store"]
    candidate_id = str(kwargs["candidate_id"])
    judgement_id = str(kwargs["judgement_id"])
    candidate = store.candidates[candidate_id]
    evidence_reviews = {
        evidence_id: {
            "evidence_id": evidence_id,
            "support_level": "direct",
            "support_type": "inferred_gap",
            "used_for_core": True,
            "reason": "test fixture treats imported worker evidence as direct",
            "missing_link": "",
        }
        for evidence_id in candidate.evidence_ids
    }
    evidence_support = {
        "verdict": "pass",
        "reason": "test fixture real audit worker",
        "evidence_reviews": evidence_reviews,
    }
    audit = AuditReport(
        audit_id=f"audit-{candidate_id}",
        candidate_id=candidate_id,
        conclusion="approved",
        scorecard={
            "evidence_support": evidence_support,
            "fixture_audit": {
                "verdict": "pass",
                "reason": "test fixture real audit worker",
            }
        },
        comments="test fixture real audit worker approved",
        required_rework=[],
        created_by="fixture-real-audit-worker",
        created_at=datetime.now(timezone.utc),
    )
    store.append_audit(audit)
    _append_trace_event(
        store,
        event_type="audit_completed",
        actor="fixture-real-audit-worker",
        target_type="AuditReport",
        target_id=audit.audit_id,
        input_refs=[candidate_id, judgement_id, *list(candidate.evidence_ids)],
        output_refs=[audit.audit_id],
        summary=f"audit completed {audit.audit_id}",
        decision=audit.conclusion,
        rationale=audit.comments,
        payload={
            "audit_mode": "real",
            "evidence_support": evidence_support,
            "required_rework": [],
        },
    )
    _append_trace_event(
        store,
        event_type="audit_worker_completed",
        actor="fixture-real-audit-worker",
        target_type="AuditReport",
        target_id=audit.audit_id,
        input_refs=[candidate_id, judgement_id],
        output_refs=[audit.audit_id],
        summary=f"fixture real audit worker completed {audit.audit_id}",
        decision=audit.conclusion,
        rationale=audit.comments,
        payload={
            "audit_mode": "real",
            "audit_completed_event_source": "run_audit_tool",
            "audit_id": audit.audit_id,
            "worker_status": "completed",
        },
    )
    return audit


def _write_open_network_worker_domain_fixture(
    path: Path,
    *,
    open_search_plan_payload: dict[str, object],
    suffix: str = "",
) -> None:
    now = datetime.now(timezone.utc)
    store = DomainStore()
    plan = open_search_plan_from_dict(open_search_plan_payload)
    store.upsert_open_search_plan(plan)
    lead_id = f"osl-open{suffix}"
    body_id = f"osb-open{suffix}"
    assessment_id = f"qa-open{suffix}"
    source_id = f"src-open{suffix}"
    evidence_id = f"ev-open{suffix}"
    url = f"https://open.example.test/report{suffix}"
    simplified_ref = f"text:open{suffix}"
    store.upsert_open_source_lead(
        OpenSourceLead(
            lead_id=lead_id,
            plan_id=plan.plan_id,
            run_id=plan.run_id,
            round_id=plan.round_id,
            topic=plan.topic,
            url=url,
            domain="open.example.test",
            title="Open report",
            snippet="远海保障公开正文",
            source_name_guess="Open Example",
            search_query=plan.queries[0],
            source_scope="open_web",
            quality_status="pending",
            created_at=now,
            updated_at=now,
        )
    )
    store.upsert_open_source_body_artifact(
        OpenSourceBodyArtifact(
            body_id=body_id,
            lead_id=lead_id,
            plan_id=plan.plan_id,
            url=url,
            final_url=url,
            content_type="text/html",
            artifact_ref=f"html:open{suffix}",
            simplified_ref=simplified_ref,
            body_location_prefix=f"{simplified_ref}#para:",
            fetched_by="network-worker",
            created_at=now,
        )
    )
    store.upsert_source_quality_assessment(
        SourceQualityAssessment(
            assessment_id=assessment_id,
            lead_id=lead_id,
            url=url,
            domain="open.example.test",
            basis_artifact_refs=[simplified_ref],
            body_location_refs=[f"{simplified_ref}#para:0"],
            read_document_ref=simplified_ref,
            source_identity="Open Example",
            publisher_or_org="Open Example",
            author="",
            publish_time="2026-06-20",
            is_original_source=True,
            citation_or_reference_signal="public report",
            content_type="article",
            quality_level="usable",
            risk_flags=[],
            reason="正文和发布主体可核验",
            created_by="network-worker",
            created_at=now,
        )
    )
    store.upsert_source(
        SourceRecord(
            source_id=source_id,
            title="Open report",
            source_name="Open Example",
            source_tier="B",
            source_type="open_web",
            publish_time=now,
            url_or_path=url,
            summary_text="公开正文",
            summary_source="network-worker",
            collection_decision="use_as_evidence",
            author_or_org=None,
            is_repost=False,
            original_source=None,
            institutional_stance=None,
            created_at=now,
            updated_at=now,
            open_source_lead_id=lead_id,
        )
    )
    store.upsert_evidence(
        EvidenceCard(
            evidence_id=evidence_id,
            source_id=source_id,
            claim="远海保障存在持续维护能力缺口",
            evidence_summary="公开正文支持远海保障缺口判断",
            excerpt="远海保障需要持续维护能力。",
            source_location=f"{simplified_ref}#para:0",
            evidence_assessment="strong",
            created_by="network-worker",
            created_at=now,
            source_quality_assessment_id=assessment_id,
        )
    )
    store.export_jsonl(path)


async def _fake_needs_revision_audit_worker(**kwargs) -> AuditReport:
    store = kwargs["store"]
    candidate_id = str(kwargs["candidate_id"])
    judgement_id = str(kwargs["judgement_id"])
    candidate = store.candidates[candidate_id]
    evidence_reviews = {
        evidence_id: {
            "evidence_id": evidence_id,
            "support_level": "partial",
            "support_type": "inferred_gap",
            "used_for_core": True,
            "reason": "needs independent cross-source validation",
            "missing_link": "缺少第二个独立开放来源",
        }
        for evidence_id in candidate.evidence_ids
    }
    evidence_support = {
        "verdict": "doubt",
        "reason": "证据仍不足，需要开放补证",
        "evidence_reviews": evidence_reviews,
        "recommended_report_status": "needs_revision",
        "status_reason": "缺少独立来源交叉验证",
        "recheck_conditions": ["补充独立来源交叉验证"],
    }
    audit = AuditReport(
        audit_id=f"audit-{candidate_id}-needs-revision",
        candidate_id=candidate_id,
        conclusion="needs_revision",
        scorecard={"evidence_support": evidence_support},
        comments="证据仍不足，需要补充独立来源交叉验证",
        required_rework=["补充独立来源交叉验证"],
        created_by="fixture-real-audit-worker",
        created_at=datetime.now(timezone.utc),
    )
    store.append_audit(audit)
    _append_trace_event(
        store,
        event_type="audit_completed",
        actor="fixture-real-audit-worker",
        target_type="AuditReport",
        target_id=audit.audit_id,
        input_refs=[candidate_id, judgement_id, *list(candidate.evidence_ids)],
        output_refs=[audit.audit_id],
        summary=f"audit completed {audit.audit_id}",
        decision=audit.conclusion,
        rationale=audit.comments,
        payload={
            "audit_mode": "real",
            "evidence_support": evidence_support,
            "required_rework": list(audit.required_rework),
        },
    )
    _append_trace_event(
        store,
        event_type="audit_worker_completed",
        actor="fixture-real-audit-worker",
        target_type="AuditReport",
        target_id=audit.audit_id,
        input_refs=[candidate_id, judgement_id],
        output_refs=[audit.audit_id],
        summary=f"fixture real audit worker completed {audit.audit_id}",
        decision=audit.conclusion,
        rationale=audit.comments,
        payload={
            "audit_mode": "real",
            "audit_completed_event_source": "run_audit_tool",
            "audit_id": audit.audit_id,
            "worker_status": "completed",
        },
    )
    return audit


if __name__ == "__main__":
    unittest.main()
