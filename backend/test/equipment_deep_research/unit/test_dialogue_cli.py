from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from urllib.error import HTTPError

import pytest

from equipment_deep_research.interfaces import dialogue_cli as cli
from equipment_deep_research.interfaces import cli as research_cli
from equipment_deep_research.providers.registry import ProviderConfigurationError


def test_research_cli_module_invocation_reaches_argparse() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "equipment_deep_research.interfaces.cli", "--help"],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                filter(None, ["src", os.environ.get("PYTHONPATH", "")])
            ),
        },
    )
    assert result.returncode == 0
    assert "Run equipment capability image Deep Research." in result.stdout


def test_research_cli_reports_provider_configuration_errors(monkeypatch, capsys) -> None:
    class FailingRunner:
        def __init__(self, **_kwargs):
            raise ProviderConfigurationError("missing required Codex credential: TEST_KEY")

    monkeypatch.setattr(research_cli, "DeepResearchRunner", FailingRunner)
    with pytest.raises(SystemExit) as error:
        research_cli.main(["--mode", "real", "--provider", "codex", "--topic", "probe"])
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert "missing required Codex credential: TEST_KEY" in captured.err
    assert "Traceback" not in captured.err


def test_cli_reads_session_without_sending_a_message(monkeypatch, capsys):
    calls = []

    def request(base, path, headers, body=None):
        calls.append((base, path, headers, body))
        return {"session": {"session_id": "existing"}}

    monkeypatch.setattr(cli, "_request", request)
    assert cli.main(["--run-id", "run/one", "--session-id", "existing"]) == 0
    assert calls[0][1] == "/runs/run%2Fone/deep-thinking/sessions/existing"
    assert calls[0][3] is None
    assert json.loads(capsys.readouterr().out)["session"]["session_id"] == "existing"


def test_cli_sends_multiline_message_with_scope_and_retry_key(monkeypatch, capsys):
    calls = []

    def request(base, path, headers, body=None):
        calls.append((path, headers, body))
        return {"job": {"job_id": "job-one"}}

    monkeypatch.setattr(cli, "_request", request)
    monkeypatch.setattr(cli.sys, "stdin", io.StringIO("Paragraph\n\n- An alternative\n"))
    monkeypatch.setenv("CLI_TEST_TOKEN", "private-token")
    assert cli.main(["--run-id", "run-one", "--session-id", "existing", "--message", "-",
        "--branch-id", "side", "--skill", "workspace:frontier", "--tenant-id", "tenant-one",
        "--token-env", "CLI_TEST_TOKEN", "--idempotency-key", "retry-key"]) == 0
    assert calls[0][2] == {"content": "Paragraph\n\n- An alternative\n", "branch_id": "side",
                           "channel": "cli", "active_skill_ids": ["workspace:frontier"]}
    assert calls[0][1]["Idempotency-Key"] == "retry-key"
    assert calls[0][1]["Authorization"] == "Bearer private-token"
    assert calls[0][1]["X-Tenant-ID"] == "tenant-one"
    assert "private-token" not in capsys.readouterr().out


def test_cli_waits_for_server_job_then_reads_the_shared_session(monkeypatch, capsys):
    calls = []
    responses = iter([
        {"job": {"job_id": "job-one"}},
        {"job": {"job_id": "job-one", "status": "running"}},
        {"job": {"job_id": "job-one", "status": "completed"}},
        {"session": {"messages": [{"role": "assistant", "content": "result"}]}},
    ])

    def request(base, path, headers, body=None):
        calls.append(path)
        return next(responses)

    monkeypatch.setattr(cli, "_request", request)
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: None)
    assert cli.main(["--run-id", "run-one", "--session-id", "existing", "--message", "question", "--wait"]) == 0
    assert calls[1:3] == ["/runs/run-one/deep-thinking/jobs/job-one"] * 2
    assert calls[-1] == "/runs/run-one/deep-thinking/sessions/existing"
    assert json.loads(capsys.readouterr().out)["session"]["messages"][0]["content"] == "result"


def test_cli_http_failure_does_not_print_sensitive_response(monkeypatch, capsys):
    def unavailable(*_args, **_kwargs):
        raise HTTPError("private-url", 503, "private-reason", {}, io.BytesIO(b"api_key=private"))

    monkeypatch.setattr(cli, "urlopen", unavailable)
    assert cli.main(["--run-id", "run-one", "--session-id", "existing"]) == 1
    assert capsys.readouterr().err == "Dialogue API returned HTTP 503\n"


def test_cli_rejects_empty_messages_before_network(monkeypatch):
    monkeypatch.setattr(cli, "_request", lambda *_args: pytest.fail("must not send an empty message"))
    with pytest.raises(SystemExit) as error:
        cli.main(["--run-id", "run-one", "--session-id", "existing", "--message", "  "])
    assert error.value.code == 2


def test_cli_failed_job_retains_shared_session_and_returns_failure(monkeypatch, capsys):
    responses = iter([
        {"job": {"job_id": "job-one"}},
        {"job": {"job_id": "job-one", "status": "failed"}},
        {"session": {"session_id": "existing"}},
    ])
    monkeypatch.setattr(cli, "_request", lambda *_args: next(responses))
    assert cli.main(["--run-id", "run-one", "--session-id", "existing", "--message", "question", "--wait"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["job"]["status"] == "failed"
    assert output["session"]["session_id"] == "existing"


def test_cli_does_not_forward_authentication_to_a_redirect():
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from threading import Thread

    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/redirect-destination")
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(cli.DialogueAPIError, match="HTTP 302"):
            cli._request(f"http://127.0.0.1:{server.server_port}", "/session",
                         {"Authorization": "Bearer private-token"})
        assert seen == ["/session"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
