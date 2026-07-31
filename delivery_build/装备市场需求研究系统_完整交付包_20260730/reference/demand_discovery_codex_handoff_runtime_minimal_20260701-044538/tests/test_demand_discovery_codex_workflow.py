from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.codex_workflow import (  # noqa: E402
    CodexWorkflowConfig,
    DefaultSourceMaterializer,
    _assess_report_quality,
    _role_prompt,
    run_codex_workflow_sync,
)
from knowledgegraph.demand_discovery.domain.store import DomainStore  # noqa: E402
from knowledgegraph.demand_discovery.tools.network import HttpFetchResponse  # noqa: E402


class RecordingRoleRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run_role(
        self,
        role: str,
        payload: dict[str, object],
        *,
        run_dir: Path,
    ) -> dict[str, object]:
        self.calls.append({"role": role, "payload": payload, "run_dir": str(run_dir)})
        if role == "planner":
            return {
                "research_directions": ["白名单内公开资料检索"],
                "reader_tasks": [
                    {
                        "task_id": "reader-task-1",
                        "objective": "查找正文证据",
                        "queries": ["低空无人机 探测 预警 能力缺口"],
                    }
                ],
            }
        if role == "reader":
            return {
                "source_records": [
                    {
                        "source_id": "src-official",
                        "title": "Official body article",
                        "source_name": "Official Source",
                        "source_tier": "A",
                        "source_type": "official",
                        "publish_time": "2026-06-01",
                        "url_or_path": "https://official.example.test/article/1",
                        "summary_text": "正文讨论低空无人机探测预警需求。",
                        "summary_source": "codex_websearch",
                        "collection_decision": "use_as_evidence",
                    },
                    {
                        "source_id": "src-outside",
                        "title": "Outside article",
                        "source_name": "Outside Source",
                        "source_tier": "B",
                        "source_type": "open_web",
                        "publish_time": "2026-06-01",
                        "url_or_path": "https://outside.example.test/article/9",
                        "summary_text": "白名单外来源。",
                        "summary_source": "codex_websearch",
                        "collection_decision": "use_as_evidence",
                    },
                ],
                "evidence_cards": [
                    {
                        "evidence_id": "ev-official",
                        "source_id": "src-official",
                        "claim": "低空小型无人机威胁要求形成探测、预警、防护闭环。",
                        "evidence_summary": "白名单正文直接支持能力缺口判断。",
                        "excerpt": "低空小型无人机威胁要求探测、预警与防护闭环。",
                        "source_location": "text:codex#para:1",
                        "evidence_assessment": "strong",
                    },
                    {
                        "evidence_id": "ev-outside",
                        "source_id": "src-outside",
                        "claim": "白名单外来源不应直接进入正式证据链。",
                        "evidence_summary": "应被拒绝或降级。",
                        "excerpt": "outside body",
                        "source_location": "text:outside#para:1",
                        "evidence_assessment": "strong",
                    },
                ],
                "findings": ["白名单正文支持低空无人机探测预警能力缺口。"],
                "open_questions": ["需要继续补充反制效果数据。"],
            }
        if role == "judge":
            return {
                "judgement_id": "judge-codex-1",
                "round_id": "round-1",
                "consensus_points": [
                    {
                        "text": "低空小型无人机威胁要求形成探测、预警、防护闭环。",
                        "worker_report_ids": ["reader-task-1"],
                        "evidence_ids": ["ev-official"],
                        "lead_ids": [],
                    }
                ],
                "contradictions": [],
                "partial_coverage": [],
                "unique_insights": [],
                "blind_spots": [
                    {
                        "text": "反制效果数据仍需补充。",
                        "worker_report_ids": ["reader-task-1"],
                        "evidence_ids": ["ev-official"],
                        "lead_ids": [],
                    }
                ],
                "evidence_strength_map": {"ev-official": "strong"},
                "next_round_plan": {
                    "plan_version": 1,
                    "summary": "进入候选合成",
                    "controller_tasks": [],
                    "worker_briefs": {},
                    "remaining_open_questions": ["反制效果数据仍需补充。"],
                    "stop_candidate_reason": "evidence sufficient for first report",
                },
                "stop_or_continue": "stop",
                "rationale": "Codex judge sees enough body evidence for first candidate.",
            }
        if role == "synthesizer":
            return {
                "candidate_id": "cand-codex-1",
                "title": "低空无人机探测预警防护闭环需求",
                "demand_statement": (
                    "在低空小型无人机威胁场景下，现有探测、预警和防护链路需要形成"
                    "更稳定的闭环能力。"
                ),
                "evidence_ids": ["ev-official", "ev-outside"],
                "open_questions": ["需要继续补充反制效果数据。"],
                "solution_signals": ["多源探测融合"],
                "rationale": "Codex synthesizer used accepted evidence and retained caveats.",
            }
        if role == "auditor":
            return {
                "audit_id": "audit-codex-1",
                "candidate_id": "cand-codex-1",
                "conclusion": "approved",
                "comments": "核心判断由白名单 A 级正文支撑，白名单外来源未纳入核心证据。",
                "required_rework": [],
                "scorecard": {
                    "evidence_support": {
                        "verdict": "pass",
                        "reason": "accepted evidence directly supports the candidate.",
                        "recommended_report_status": "review_ready",
                        "recheck_conditions": [],
                        "evidence_reviews": {
                            "ev-official": {
                                "evidence_id": "ev-official",
                                "support_level": "direct",
                                "support_type": "inferred_gap",
                                "used_for_core": True,
                                "reason": "body evidence supports the core gap claim.",
                                "missing_link": "",
                            }
                        },
                    },
                    "evidence_supports_candidate": {
                        "verdict": "pass",
                        "reason": "direct support exists.",
                    },
                    "core_conclusion_supported": {
                        "verdict": "pass",
                        "reason": "core conclusion is supported.",
                    },
                },
            }
        if role == "reporter":
            return {
                "report_id": "report-codex-1",
                "candidate_id": "cand-codex-1",
                "title": "低空无人机探测预警防护闭环需求报告",
                "body": (
                    "## 阶段性结论\n"
                    "低空小型无人机威胁下，探测、预警与防护链路存在闭环能力缺口。\n\n"
                    "## 待解决问题\n"
                    "- 继续补充反制效果数据。"
                ),
                "evidence_ids": ["ev-official", "ev-outside"],
            }
        raise AssertionError(f"unexpected role: {role}")


class CodexDemandWorkflowTests(unittest.TestCase):
    def test_role_prompts_reuse_markdown_agents_and_codex_complements(self) -> None:
        payload = {
            "topic": "低空无人机探测预警能力缺口",
            "rules": [],
            "source_strategy": {},
            "whitelist_sources": [],
        }

        reader_prompt = _role_prompt("reader", payload)
        judge_prompt = _role_prompt("judge", payload)
        planner_prompt = _role_prompt("planner", payload)
        synthesizer_prompt = _role_prompt("synthesizer", payload)

        self.assertIn("Reader / Network Research Worker", reader_prompt)
        self.assertIn("Judge / Research Planning Agent", judge_prompt)
        self.assertIn("Planner / Codex Research Controller", planner_prompt)
        self.assertIn("Synthesizer / Candidate Demand Agent", synthesizer_prompt)
        self.assertIn("Return JSON only", reader_prompt)

    def test_report_quality_accepts_markdown_heading_levels(self) -> None:
        report = {
            "body": (
                "# 结论摘要\n正文足够长，说明低空无人机探测预警能力缺口。\n\n"
                "# 场景与压力\n正文。\n\n"
                "# 能力缺口拆解\n正文。\n\n"
                "# 证据矩阵\n正文。\n\n"
                "# 审计结论与限制\n正文。\n\n"
                "# 后续验证计划\n正文。"
            ),
            "evidence_ids": ["ev-1"],
        }

        quality = _assess_report_quality(report)

        self.assertEqual(quality["status"], "passed")

    def test_codex_workflow_runs_all_roles_and_writes_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whitelist = _write_whitelist(root)
            runner = RecordingRoleRunner()

            result = run_codex_workflow_sync(
                CodexWorkflowConfig(
                    topic="低空小型无人机威胁下的探测、预警与防护能力缺口",
                    output_root=root / "runs",
                    run_id="codex-independent",
                    source_whitelist_path=whitelist,
                ),
                role_runner=runner,
            )

            summary = json.loads(result.round_summary_path.read_text(encoding="utf-8"))
            store = DomainStore.load_jsonl(result.domain_path)
            report_text = result.report_path.read_text(encoding="utf-8")
            trace_events = [
                json.loads(line)["event_type"]
                for line in result.trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            artifact_exists = {
                "summary": result.round_summary_path.exists(),
                "domain": result.domain_path.exists(),
                "trace": result.trace_path.exists(),
                "report": result.report_path.exists(),
            }

        self.assertEqual(
            [call["role"] for call in runner.calls],
            ["planner", "reader", "judge", "synthesizer", "auditor", "reporter"],
        )
        self.assertEqual(summary["execution"], "independent_codex_workflow")
        self.assertEqual(summary["accepted_evidence_ids"], ["ev-official"])
        self.assertEqual(summary["rejected_evidence_ids"], ["ev-outside"])
        self.assertIn("src-official", store.sources)
        self.assertNotIn("src-outside", store.sources)
        self.assertIn("ev-official", store.evidence)
        self.assertNotIn("ev-outside", store.evidence)
        self.assertIn("judge-codex-1", store.judgement_reports)
        self.assertIn("cand-codex-1", store.candidates)
        self.assertEqual(store.candidates["cand-codex-1"].evidence_ids, ["ev-official"])
        self.assertIn("audit-codex-1", store.audit_reports)
        self.assertIn("report-codex-1", store.demand_reports)
        self.assertEqual(store.demand_reports["report-codex-1"].evidence_ids, ["ev-official"])
        self.assertIn("## 阶段性结论", report_text)
        self.assertIn("ev-official", report_text)
        self.assertNotIn("ev-outside", report_text)
        self.assertIn("codex_role_completed", trace_events)
        self.assertIn("report_published", trace_events)
        self.assertTrue(artifact_exists["summary"])
        self.assertTrue(artifact_exists["domain"])
        self.assertTrue(artifact_exists["trace"])
        self.assertTrue(artifact_exists["report"])

    def test_codex_workflow_materializes_reader_evidence_before_judge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whitelist = _write_whitelist(root)
            runner = RecordingRoleRunner()
            materializer = RecordingSourceMaterializer()

            result = run_codex_workflow_sync(
                CodexWorkflowConfig(
                    topic="低空小型无人机威胁下的探测、预警与防护能力缺口",
                    output_root=root / "runs",
                    run_id="codex-materialized",
                    source_whitelist_path=whitelist,
                ),
                role_runner=runner,
                source_materializer=materializer,
            )

            summary = json.loads(result.round_summary_path.read_text(encoding="utf-8"))
            store = DomainStore.load_jsonl(result.domain_path)
            trace_events = [
                json.loads(line)
                for line in result.trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(len(materializer.calls), 1)
        self.assertEqual(materializer.calls[0]["accepted_evidence_ids"], ["ev-official"])
        self.assertEqual(summary["source_materials"][0]["evidence_id"], "ev-official")
        self.assertEqual(
            summary["worker_reports"][0]["source_materials"][0]["matched_source_location"],
            "text:materialized#para:2",
        )
        judge_payload = runner.calls[2]["payload"]
        synthesizer_payload = runner.calls[3]["payload"]
        auditor_payload = runner.calls[4]["payload"]
        reporter_payload = runner.calls[5]["payload"]
        for payload in [judge_payload, synthesizer_payload, auditor_payload, reporter_payload]:
            self.assertEqual(payload["source_materials"][0]["evidence_id"], "ev-official")
        self.assertEqual(
            store.evidence["ev-official"].source_location,
            "text:materialized#para:2",
        )
        self.assertEqual(store.evidence["ev-official"].excerpt, "材料化后的正文证据摘录。")
        self.assertIn(
            "reader_source_materialized",
            [event["event_type"] for event in trace_events],
        )

    def test_default_source_materializer_fetches_and_reads_body_artifacts(self) -> None:
        fetched_urls: list[str] = []

        async def transport(url: str, timeout_ms: int, max_bytes: int) -> HttpFetchResponse:
            fetched_urls.append(url)
            html = (
                "<html><body><article>"
                "<h1>Official body article</h1>"
                "<p>背景段落说明低空无人机活动频率提升。</p>"
                "<p>低空小型无人机威胁要求探测、预警与防护闭环。</p>"
                "</article></body></html>"
            )
            return HttpFetchResponse(
                url=url,
                status_code=200,
                headers={"content-type": "text/html; charset=utf-8"},
                content=html.encode("utf-8"),
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whitelist = _write_whitelist(root)
            runner = RecordingRoleRunner()

            result = run_codex_workflow_sync(
                CodexWorkflowConfig(
                    topic="低空小型无人机威胁下的探测、预警与防护能力缺口",
                    output_root=root / "runs",
                    run_id="codex-default-materializer",
                    source_whitelist_path=whitelist,
                ),
                role_runner=runner,
                source_materializer=DefaultSourceMaterializer(http_transport=transport),
            )

            summary = json.loads(result.round_summary_path.read_text(encoding="utf-8"))
            store = DomainStore.load_jsonl(result.domain_path)

        self.assertEqual(fetched_urls, ["https://official.example.test/article/1"])
        self.assertEqual(summary["source_materials"][0]["status"], "matched")
        self.assertTrue(summary["source_materials"][0]["artifact_ref"].startswith("html:"))
        self.assertTrue(summary["source_materials"][0]["simplified_ref"].startswith("text:"))
        self.assertEqual(
            store.evidence["ev-official"].excerpt,
            "低空小型无人机威胁要求探测、预警与防护闭环。",
        )
        self.assertRegex(
            store.evidence["ev-official"].source_location,
            r"^text:[0-9a-f]{16}#para:1$",
        )
        self.assertEqual(runner.calls[2]["payload"]["source_materials"][0]["status"], "matched")

    def test_codex_workflow_routes_judge_worker_brief_to_next_reader_round(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whitelist = _write_whitelist(root)
            runner = MultiRoundRoleRunner()

            result = run_codex_workflow_sync(
                CodexWorkflowConfig(
                    topic="低空无人机探测预警能力缺口",
                    output_root=root / "runs",
                    run_id="codex-multiround",
                    source_whitelist_path=whitelist,
                    max_rounds=2,
                ),
                role_runner=runner,
            )

            summary = json.loads(result.round_summary_path.read_text(encoding="utf-8"))
            store = DomainStore.load_jsonl(result.domain_path)
            trace_events = [
                json.loads(line)["event_type"]
                for line in result.trace_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

        self.assertEqual(
            [call["role"] for call in runner.calls],
            [
                "planner",
                "reader",
                "judge",
                "reader",
                "judge",
                "synthesizer",
                "auditor",
                "reporter",
            ],
        )
        second_reader_payload = runner.calls[3]["payload"]
        self.assertEqual(second_reader_payload["round_id"], "round-2")
        self.assertIn("worker_assignment", second_reader_payload)
        self.assertIn("补充跨来源正文证据", second_reader_payload["worker_assignment"]["worker_brief"])
        self.assertIn("previous_judgement", second_reader_payload)
        self.assertEqual(summary["round_count"], 2)
        self.assertEqual([row["status"] for row in summary["rounds"]], ["judged", "stopped"])
        self.assertEqual(summary["accepted_evidence_ids"], ["ev-r1", "ev-r2"])
        self.assertIn("ev-r1", store.evidence)
        self.assertIn("ev-r2", store.evidence)
        self.assertIn("judge_worker_assignment_created", trace_events)

    def test_codex_workflow_rewrites_thin_report_before_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whitelist = _write_whitelist(root)
            runner = ThinReportRoleRunner()

            result = run_codex_workflow_sync(
                CodexWorkflowConfig(
                    topic="低空无人机探测预警能力缺口",
                    output_root=root / "runs",
                    run_id="codex-report-quality",
                    source_whitelist_path=whitelist,
                    max_rounds=1,
                ),
                role_runner=runner,
            )

            summary = json.loads(result.round_summary_path.read_text(encoding="utf-8"))
            report_text = result.report_path.read_text(encoding="utf-8")

        reporter_calls = [call for call in runner.calls if call["role"] == "reporter"]
        self.assertEqual(len(reporter_calls), 2)
        self.assertIn("report_quality_feedback", reporter_calls[1]["payload"])
        self.assertEqual(summary["report_quality"]["status"], "passed")
        self.assertEqual(summary["report_quality"]["attempts"], 2)
        self.assertIn("## 证据矩阵", report_text)
        self.assertIn("## 后续验证计划", report_text)

    def test_codex_workflow_downgrades_report_status_when_audit_needs_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            whitelist = _write_whitelist(root)
            runner = NeedsRevisionAuditRoleRunner()

            result = run_codex_workflow_sync(
                CodexWorkflowConfig(
                    topic="低空无人机探测预警能力缺口",
                    output_root=root / "runs",
                    run_id="codex-audit-downgrade",
                    source_whitelist_path=whitelist,
                    max_rounds=1,
                ),
                role_runner=runner,
            )

            summary = json.loads(result.round_summary_path.read_text(encoding="utf-8"))
            store = DomainStore.load_jsonl(result.domain_path)

        self.assertEqual(summary["audit"]["conclusion"], "needs_revision")
        self.assertEqual(summary["report"]["review_status"], "needs_revision")
        self.assertEqual(store.demand_reports["report-codex-1"].review_status, "needs_revision")


def _write_whitelist(root: Path) -> Path:
    path = root / "source_whitelist.yaml"
    path.write_text(
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
    interaction_profile: static_listing
    content_languages: [zh]
excluded: []
""",
        encoding="utf-8",
    )
    return path


class RecordingSourceMaterializer:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def materialize_reader_output(
        self,
        *,
        store: DomainStore,
        import_result: dict[str, list[str]],
        **_: object,
    ) -> list[dict[str, object]]:
        self.calls.append(
            {
                "accepted_evidence_ids": list(import_result["accepted_evidence_ids"]),
                "accepted_source_ids": list(import_result["accepted_source_ids"]),
            }
        )
        card = store.evidence["ev-official"]
        store.upsert_evidence(
            replace(
                card,
                excerpt="材料化后的正文证据摘录。",
                source_location="text:materialized#para:2",
            )
        )
        return [
            {
                "evidence_id": "ev-official",
                "source_id": "src-official",
                "url": "https://official.example.test/article/1",
                "artifact_ref": "html:materialized",
                "simplified_ref": "text:materialized",
                "matched_source_location": "text:materialized#para:2",
                "read_excerpt": "材料化后的正文证据摘录。",
                "status": "matched",
            }
        ]


class MultiRoundRoleRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run_role(
        self,
        role: str,
        payload: dict[str, object],
        *,
        run_dir: Path,
    ) -> dict[str, object]:
        self.calls.append({"role": role, "payload": payload, "run_dir": str(run_dir)})
        round_id = str(payload.get("round_id", "round-1"))
        if role == "planner":
            return {
                "research_directions": ["先查白名单正文证据"],
                "reader_tasks": [
                    {
                        "task_id": "reader-task-1",
                        "objective": "查找初始正文证据",
                        "queries": ["低空无人机 探测预警 能力缺口"],
                    }
                ],
            }
        if role == "reader" and round_id == "round-1":
            return _reader_output(
                source_id="src-r1",
                evidence_id="ev-r1",
                url="https://official.example.test/article/1",
                claim="初始正文证据显示低空无人机压缩探测预警时间。",
                stop_reason="needs_open_search",
            )
        if role == "reader" and round_id == "round-2":
            return _reader_output(
                source_id="src-r2",
                evidence_id="ev-r2",
                url="https://official.example.test/article/2",
                claim="补充正文证据显示需要跨来源态势共享和连续跟踪。",
                stop_reason="evidence_sufficient",
            )
        if role == "judge" and round_id == "round-1":
            worker_reports = list(payload.get("worker_reports") or [])
            worker_report_id = str(worker_reports[0]["worker_report_id"])
            return {
                "judgement_id": "judge-round-1",
                "round_id": "round-1",
                "consensus_points": [
                    {
                        "text": "已有初始正文证据，但缺少跨来源正文支撑。",
                        "worker_report_ids": [worker_report_id],
                        "evidence_ids": ["ev-r1"],
                        "lead_ids": [],
                    }
                ],
                "contradictions": [],
                "partial_coverage": [],
                "unique_insights": [],
                "blind_spots": [
                    {
                        "text": "需要补充跨来源正文证据。",
                        "worker_report_ids": [worker_report_id],
                        "evidence_ids": ["ev-r1"],
                        "lead_ids": [],
                    }
                ],
                "evidence_strength_map": {"ev-r1": "partial"},
                "next_round_plan": {
                    "plan_version": 1,
                    "summary": "继续一轮补证",
                    "controller_tasks": [
                        {
                            "task_id": "followup-1",
                            "objective": "补充跨来源正文证据",
                            "gap_type": "missing_direct_evidence",
                            "routing_hint": "different_whitelist_source",
                            "source_scope": "whitelist_first",
                            "input_refs": {
                                "worker_report_ids": [worker_report_id],
                                "evidence_ids": ["ev-r1"],
                                "lead_ids": [],
                            },
                            "query_revisions": [
                                {
                                    "query": "低空无人机 探测预警 态势共享 连续跟踪",
                                    "rationale": "围绕 judge blind spot 补证",
                                }
                            ],
                            "completion_check": "新增跨来源正文 EvidenceCard 或说明白名单耗尽",
                        }
                    ],
                    "worker_briefs": {
                        "followup-1": "补充跨来源正文证据，限定白名单优先，完成后停止。"
                    },
                    "remaining_open_questions": [],
                    "stop_candidate_reason": "",
                },
                "stop_or_continue": "continue",
                "rationale": "需要第二轮 worker 补证。",
            }
        if role == "judge" and round_id == "round-2":
            worker_reports = list(payload.get("worker_reports") or [])
            worker_report_id = str(worker_reports[0]["worker_report_id"])
            return {
                "judgement_id": "judge-round-2",
                "round_id": "round-2",
                "consensus_points": [
                    {
                        "text": "两轮正文证据共同支持低空无人机探测预警与态势共享缺口。",
                        "worker_report_ids": [worker_report_id],
                        "evidence_ids": ["ev-r1", "ev-r2"],
                        "lead_ids": [],
                    }
                ],
                "contradictions": [],
                "partial_coverage": [],
                "unique_insights": [],
                "blind_spots": [],
                "evidence_strength_map": {"ev-r1": "partial", "ev-r2": "strong"},
                "next_round_plan": {
                    "plan_version": 1,
                    "summary": "停止进入报告",
                    "controller_tasks": [],
                    "worker_briefs": {},
                    "remaining_open_questions": [],
                    "stop_candidate_reason": "核心缺口已有两轮正文证据支撑",
                },
                "stop_or_continue": "stop",
                "rationale": "可以进入候选和报告。",
            }
        if role == "synthesizer":
            return _synthesizer_output(["ev-r1", "ev-r2"])
        if role == "auditor":
            return _audit_output()
        if role == "reporter":
            return _full_report_output(["ev-r1", "ev-r2"])
        raise AssertionError(f"unexpected role/round: {role}/{round_id}")


class ThinReportRoleRunner(MultiRoundRoleRunner):
    def __init__(self) -> None:
        super().__init__()
        self.reporter_call_count = 0

    def run_role(
        self,
        role: str,
        payload: dict[str, object],
        *,
        run_dir: Path,
    ) -> dict[str, object]:
        if role != "reporter":
            if role == "judge":
                self.calls.append({"role": role, "payload": payload, "run_dir": str(run_dir)})
                worker_report_id = str(list(payload.get("worker_reports") or [])[0]["worker_report_id"])
                return {
                    "judgement_id": "judge-round-1",
                    "round_id": "round-1",
                    "consensus_points": [
                        {
                            "text": "白名单正文证据支持低空无人机探测预警能力缺口。",
                            "worker_report_ids": [worker_report_id],
                            "evidence_ids": ["ev-r1"],
                            "lead_ids": [],
                        }
                    ],
                    "contradictions": [],
                    "partial_coverage": [],
                    "unique_insights": [],
                    "blind_spots": [],
                    "evidence_strength_map": {"ev-r1": "strong"},
                    "next_round_plan": {
                        "plan_version": 1,
                        "summary": "停止进入报告",
                        "controller_tasks": [],
                        "worker_briefs": {},
                        "remaining_open_questions": [],
                        "stop_candidate_reason": "证据足以形成第一版报告",
                    },
                    "stop_or_continue": "stop",
                    "rationale": "可以进入报告。",
                }
            if role == "synthesizer":
                self.calls.append({"role": role, "payload": payload, "run_dir": str(run_dir)})
                return _synthesizer_output(["ev-r1"])
            return super().run_role(role, payload, run_dir=run_dir)
        self.calls.append({"role": role, "payload": payload, "run_dir": str(run_dir)})
        self.reporter_call_count += 1
        if self.reporter_call_count == 1:
            return {
                "report_id": "report-codex-1",
                "candidate_id": "cand-codex-1",
                "title": "低空无人机探测预警能力缺口",
                "body": "结论：存在能力缺口。",
                "evidence_ids": ["ev-r1"],
            }
        return _full_report_output(["ev-r1"])


class NeedsRevisionAuditRoleRunner(ThinReportRoleRunner):
    def run_role(
        self,
        role: str,
        payload: dict[str, object],
        *,
        run_dir: Path,
    ) -> dict[str, object]:
        if role == "auditor":
            self.calls.append({"role": role, "payload": payload, "run_dir": str(run_dir)})
            audit = _audit_output()
            audit["conclusion"] = "needs_revision"
            audit["comments"] = "证据可形成降级报告，但不能进入 review_ready。"
            audit["required_rework"] = ["补充跨来源验证"]
            audit["scorecard"]["evidence_support"]["verdict"] = "doubt"
            audit["scorecard"]["evidence_support"]["recommended_report_status"] = "needs_revision"
            audit["scorecard"]["evidence_support"]["status_reason"] = "needs cross-source validation"
            audit["scorecard"]["evidence_supports_candidate"]["verdict"] = "doubt"
            return audit
        return super().run_role(role, payload, run_dir=run_dir)


def _reader_output(
    *,
    source_id: str,
    evidence_id: str,
    url: str,
    claim: str,
    stop_reason: str,
) -> dict[str, object]:
    return {
        "source_records": [
            {
                "source_id": source_id,
                "title": f"Official body article {source_id}",
                "source_name": "Official Source",
                "source_tier": "A",
                "source_type": "official",
                "publish_time": "2026-06-01",
                "url_or_path": url,
                "summary_text": claim,
                "summary_source": "codex_websearch",
                "collection_decision": "use_as_evidence",
            }
        ],
        "evidence_cards": [
            {
                "evidence_id": evidence_id,
                "source_id": source_id,
                "claim": claim,
                "evidence_summary": "白名单正文支撑需求判断。",
                "excerpt": claim,
                "source_location": f"text:{url}#para:1",
                "evidence_assessment": "strong",
            }
        ],
        "findings": [claim],
        "open_questions": [],
        "stop_reason": stop_reason,
        "remaining_gaps": [],
        "suggested_next_routes": [],
        "need_more_sources": stop_reason != "evidence_sufficient",
        "risks": [],
    }


def _synthesizer_output(evidence_ids: list[str]) -> dict[str, object]:
    return {
        "candidate_id": "cand-codex-1",
        "title": "低空无人机探测预警与态势共享能力缺口",
        "demand_statement": (
            "低空无人机威胁压缩传统探测预警时间，现有体系需要补强"
            "多源探测、连续跟踪和跨机构态势共享能力。"
        ),
        "evidence_ids": evidence_ids,
        "open_questions": ["需要继续验证采购部署成熟度。"],
        "solution_signals": ["多源传感器融合", "跨机构态势共享"],
        "rationale": "多条白名单正文证据共同支撑候选需求。",
    }


def _audit_output() -> dict[str, object]:
    return {
        "audit_id": "audit-codex-1",
        "candidate_id": "cand-codex-1",
        "conclusion": "approved",
        "comments": "核心判断有白名单正文证据支撑。",
        "required_rework": [],
        "scorecard": {
            "evidence_support": {
                "verdict": "pass",
                "reason": "accepted evidence supports the candidate.",
                "recommended_report_status": "review_ready",
                "status_reason": "evidence-backed first report",
                "recheck_conditions": ["继续验证部署成熟度"],
                "evidence_reviews": {
                    "ev-r1": {
                        "evidence_id": "ev-r1",
                        "support_level": "direct",
                        "support_type": "inferred_gap",
                        "used_for_core": True,
                        "reason": "body evidence supports the core gap claim.",
                        "missing_link": "",
                    },
                    "ev-r2": {
                        "evidence_id": "ev-r2",
                        "support_level": "direct",
                        "support_type": "inferred_gap",
                        "used_for_core": True,
                        "reason": "body evidence supports the follow-up gap claim.",
                        "missing_link": "",
                    },
                },
            },
            "evidence_supports_candidate": {
                "verdict": "pass",
                "reason": "direct support exists.",
            },
            "core_conclusion_supported": {
                "verdict": "pass",
                "reason": "core conclusion is supported.",
            },
        },
    }


def _full_report_output(evidence_ids: list[str]) -> dict[str, object]:
    return {
        "report_id": "report-codex-1",
        "candidate_id": "cand-codex-1",
        "title": "低空无人机探测预警与态势共享能力缺口报告",
        "body": (
            "## 结论摘要\n"
            "白名单正文证据支持将低空无人机探测预警与态势共享不足视为需求缺口。\n\n"
            "## 场景与压力\n"
            "低空无人机威胁压缩传统探测预警时间，并提高连续跟踪难度。\n\n"
            "## 能力缺口拆解\n"
            "- 多源探测不足。\n- 连续跟踪不足。\n- 跨机构态势共享不足。\n\n"
            "## 证据矩阵\n"
            "- ev-r1：支撑探测预警时间被压缩。\n"
            "- ev-r2：支撑态势共享和连续跟踪缺口。\n\n"
            "## 审计结论与限制\n"
            "当前结论可作为阶段性需求发现，采购部署成熟度仍需验证。\n\n"
            "## 后续验证计划\n"
            "继续补充部署成熟度、反制效果和不同场景的正文证据。"
        ),
        "evidence_ids": evidence_ids,
    }


if __name__ == "__main__":
    unittest.main()
