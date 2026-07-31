from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DemandDiscoveryDemoTests(unittest.TestCase):
    def test_fake_demo_runs_offline_and_prints_summary(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "demand_discovery_demo.py"),
                "--mode",
                "fake",
            ],
            cwd=PROJECT_ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Candidate Demand: Low-altitude resilient sensing", result.stdout)
        self.assertIn("Evidence: ev-low-altitude-1", result.stdout)
        self.assertRegex(result.stdout, r"Trace events: \d+")
        self.assertNotIn("Authorization", result.stdout)
        self.assertNotIn("API key", result.stdout)

    def test_fake_watch_runs_workers_and_writes_progress_snapshot(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

        with tempfile.TemporaryDirectory() as temp_dir:
            inbox = Path(temp_dir) / "watch-test" / "inbox"
            inbox.mkdir(parents=True)
            (inbox / "next_turn.md").write_text("operator follow-up", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "demand_discovery_demo.py"),
                    "--mode",
                    "fake",
                    "--watch",
                    "--run-id",
                    "watch-test",
                    "--output-root",
                    temp_dir,
                ],
                cwd=PROJECT_ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            progress_path = Path(temp_dir) / "watch-test" / "progress.md"

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("worker_started", result.stdout)
            self.assertIn("worker_completed", result.stdout)
            self.assertIn(f"Progress path: {progress_path}", result.stdout)
            self.assertTrue(progress_path.exists())
            progress = progress_path.read_text(encoding="utf-8")
            self.assertIn("reader", progress)
            self.assertIn("completed", progress)
            self.assertIn("sources:", progress)
            self.assertEqual(len(list((inbox / "processed").glob("*_next_turn.md"))), 1)

    def test_real_mode_requires_configured_api_key(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
        env.pop("DEMAND_DISCOVERY_API_KEY", None)
        env["DEMAND_DISCOVERY_DOTENV"] = str(
            PROJECT_ROOT / "does-not-exist-demand-discovery.env"
        )

        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "demand_discovery_demo.py"),
                "--mode",
                "real",
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

    def test_real_mode_dry_run_prints_sanitized_request(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
        env["DEMAND_DISCOVERY_API_KEY"] = "secret-demo-key"

        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "demand_discovery_demo.py"),
                "--mode",
                "real",
                "--dry-run-provider-request",
                "--endpoint-mode",
                "responses_compatible",
                "--base-url",
                "https://api.example.test",
                "--model",
                "gpt-demo",
            ],
            cwd=PROJECT_ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("endpoint_mode: responses_compatible", result.stdout)
        self.assertIn("model: gpt-demo", result.stdout)
        self.assertIn("payload_keys:", result.stdout)
        self.assertNotIn("secret-demo-key", result.stdout)
        self.assertNotIn("Authorization", result.stdout)

    def test_real_mode_dry_run_reads_base_url_from_env(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
        env["DEMAND_DISCOVERY_API_KEY"] = "secret-demo-key"
        env["DEMAND_DISCOVERY_BASE_URL"] = "https://env-api.example.test"

        result = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "scripts" / "demand_discovery_demo.py"),
                "--mode",
                "real",
                "--dry-run-provider-request",
                "--model",
                "gpt-demo",
            ],
            cwd=PROJECT_ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("url: https://env-api.example.test/v1/responses", result.stdout)
        self.assertNotIn("secret-demo-key", result.stdout)
        self.assertNotIn("Authorization", result.stdout)

    def test_real_mode_dry_run_reads_power_shell_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dotenv_path = Path(temp_dir) / ".env"
            dotenv_path.write_text(
                "\n".join(
                    [
                        '$env:DEMAND_DISCOVERY_API_KEY="secret-dotenv-key"',
                        '$env:DEMAND_DISCOVERY_BASE_URL="https://dotenv-api.example.test"',
                        '$env:DEMAND_DISCOVERY_MODEL="gpt-dotenv"',
                    ]
                ),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
            env["DEMAND_DISCOVERY_DOTENV"] = str(dotenv_path)
            env.pop("DEMAND_DISCOVERY_API_KEY", None)
            env.pop("DEMAND_DISCOVERY_BASE_URL", None)
            env.pop("DEMAND_DISCOVERY_MODEL", None)

            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "demand_discovery_demo.py"),
                    "--mode",
                    "real",
                    "--dry-run-provider-request",
                ],
                cwd=PROJECT_ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "url: https://dotenv-api.example.test/v1/responses",
            result.stdout,
        )
        self.assertIn("model: gpt-dotenv", result.stdout)
        self.assertNotIn("secret-dotenv-key", result.stdout)
        self.assertNotIn("Authorization", result.stdout)

    def test_real_mode_runs_with_local_sse_provider_and_prints_summary(self) -> None:
        server = _ProviderStubServer(
            [
                _sse_tool(
                    "create_source_record",
                    "call-source",
                    {
                        "source_id": "src-real-1",
                        "title": "Real provider source",
                        "source_name": "Local SSE Provider",
                        "source_tier": "A",
                        "source_type": "demo",
                        "url_or_path": "demo://real-source",
                        "summary_text": "summary",
                        "summary_source": "model_generated",
                        "collection_decision": "use_as_evidence",
                    },
                ),
                _sse_tool(
                    "create_evidence_card",
                    "call-evidence",
                    {
                        "evidence_id": "ev-real-1",
                        "source_id": "src-real-1",
                        "claim": "Real provider evidence claim.",
                        "evidence_summary": "Real provider evidence summary.",
                        "excerpt": "Real provider excerpt.",
                        "source_location": "text:local-stub#para:0",
                        "evidence_assessment": "strong",
                    },
                ),
                _sse_tool(
                    "create_or_update_candidate",
                    "call-candidate",
                    {
                        "candidate_id": "cand-real",
                        "title": "Real provider demand",
                        "demand_statement": "Need a real provider-backed demo path.",
                        "evidence_ids": ["ev-real-1"],
                    },
                ),
                _sse_tool(
                    "run_audit",
                    "call-audit",
                    {
                        "audit_id": "audit-real",
                        "candidate_id": "cand-real",
                        "conclusion": "approved",
                        "scorecard": _passing_default_scorecard(),
                        "comments": "approved by local provider stub",
                    },
                ),
                _sse_tool(
                    "generate_demand_report",
                    "call-report",
                    {
                        "report_id": "report-real",
                        "candidate_id": "cand-real",
                        "title": "Real provider demand report",
                        "body": "Report body from local provider stub.",
                        "evidence_ids": ["ev-real-1"],
                        "audit_id": "audit-real",
                    },
                ),
                _sse_text("done"),
            ]
        )
        server.start()
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
        env["DEMAND_DISCOVERY_API_KEY"] = "secret-real-key"

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                result = subprocess.run(
                    [
                        sys.executable,
                        str(PROJECT_ROOT / "scripts" / "demand_discovery_demo.py"),
                        "--mode",
                        "real",
                        "--base-url",
                        server.base_url,
                        "--model",
                        "gpt-local",
                        "--output",
                        str(Path(temp_dir) / "real-demo.jsonl"),
                    ],
                    cwd=PROJECT_ROOT,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                )
        finally:
            server.stop()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Candidate Demand: Real provider demand", result.stdout)
        self.assertIn("Evidence: ev-real-1", result.stdout)
        self.assertIn("Report: Real provider demand report", result.stdout)
        self.assertRegex(result.stdout, r"Trace events: \d+")
        self.assertNotIn("secret-real-key", result.stdout)
        self.assertNotIn("Authorization", result.stdout)

    def test_real_mode_surfaces_provider_error_before_missing_report(self) -> None:
        server = _ProviderStubServer(
            [
                _sse_events(
                    [
                        {
                            "type": "response.failed",
                            "error": {"message": "invalid model slug"},
                        }
                    ]
                )
            ]
        )
        server.start()
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
        env["DEMAND_DISCOVERY_API_KEY"] = "secret-real-key"

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "scripts" / "demand_discovery_demo.py"),
                    "--mode",
                    "real",
                    "--base-url",
                    server.base_url,
                    "--model",
                    "bad model",
                ],
                cwd=PROJECT_ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
        finally:
            server.stop()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("provider error: invalid model slug", result.stderr)
        self.assertNotIn("provider did not produce a demand report", result.stderr)


class _ProviderStubServer:
    def __init__(self, responses: list[bytes]) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _ProviderStubHandler)
        self._server.responses = list(responses)  # type: ignore[attr-defined]
        self._server.request_count = 0  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


class _ProviderStubHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            self.rfile.read(length)
        index = self.server.request_count  # type: ignore[attr-defined]
        self.server.request_count += 1  # type: ignore[attr-defined]
        responses = self.server.responses  # type: ignore[attr-defined]
        body = responses[min(index, len(responses) - 1)]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def _sse_tool(name: str, call_id: str, arguments: dict[str, object]) -> bytes:
    item = {
        "type": "response.output_item.done",
        "item": {
            "type": "function_call",
            "call_id": call_id,
            "name": name,
            "arguments": json.dumps(arguments),
        },
    }
    return _sse_events([item, {"type": "response.completed"}])


def _sse_text(text: str) -> bytes:
    return _sse_events(
        [
            {"type": "response.output_text.delta", "delta": text},
            {"type": "response.completed"},
        ]
    )


def _sse_events(events: list[dict[str, object]]) -> bytes:
    return "".join(f"data: {json.dumps(event)}\n\n" for event in events).encode(
        "utf-8"
    )


def _passing_default_scorecard() -> dict[str, object]:
    rubric = json.loads(
        (PROJECT_ROOT / "configs" / "demand_discovery" / "audit_rubric.json").read_text(
            encoding="utf-8"
        )
    )
    item_ids = [
        item["id"]
        for item in [*rubric["veto_items"], *rubric["check_items"]]
    ]
    scorecard: dict[str, object] = {
        item_id: {"verdict": "pass", "reason": "local SSE fixture passes"}
        for item_id in item_ids
    }
    scorecard["evidence_support"] = {
        "verdict": "pass",
        "reason": "local SSE fixture evidence directly supports the core conclusion",
        "evidence_reviews": {
            "ev-real-1": {
                "evidence_id": "ev-real-1",
                "support_level": "direct",
                "support_type": "inferred_gap",
                "used_for_core": True,
                "reason": "fixture body evidence supports the candidate",
                "missing_link": "",
            }
        },
    }
    return scorecard


if __name__ == "__main__":
    unittest.main()
