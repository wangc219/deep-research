from pathlib import Path
import json
import subprocess

from evals.judging import CodexJudgeClient, JudgeClient, judge_pair_file
from evals.models import read_jsonl, write_jsonl


def _judgment_payload() -> dict:
    return {
        "winner": "A",
        "confidence": 0.8,
        "dimensions": {
            "task_fulfillment": "A",
            "facts_and_citations": "A",
            "analysis_depth": "B",
            "equipment_demand_value": "A",
            "uncertainty": "tie",
        },
        "reason": "A 更完整。",
        "citation_issues": [],
        "hard_failures": [],
    }


def test_direct_judge_supports_chat_completions(tmp_path: Path, monkeypatch) -> None:
    captured = {}

    class Response:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {
                "model": "deepseek-chat",
                "choices": [{"message": {"content": json.dumps(_judgment_payload(), ensure_ascii=False)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            }

    def fake_post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr("evals.judging.requests.post", fake_post)
    client = JudgeClient(
        "deepseek-chat",
        judge_id="expert-1",
        api_protocol="chat_completions",
        base_url="https://api.deepseek.com/chat/completions",
        api_key="temporary-secret",
        temperature=0,
    )
    judgment = client.judge("比较回答", pair_id="P-1")
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["json"]["response_format"] == {"type": "json_object"}
    assert captured["json"]["messages"][0]["content"] == "比较回答"
    assert judgment.judge_id == "expert-1"
    assert judgment.winner == "A"
    assert client.last_usage["completion_tokens"] == 20


def test_direct_judge_retries_one_transient_ssl_disconnect(monkeypatch) -> None:
    calls = []

    class Response:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {
                "model": "judge",
                "output_text": json.dumps(_judgment_payload(), ensure_ascii=False),
                "usage": {"input_tokens": 10, "output_tokens": 20},
            }

    def flaky_post(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            raise __import__("requests").exceptions.SSLError(
                "UNEXPECTED_EOF_WHILE_READING"
            )
        return Response()

    monkeypatch.setattr("evals.judging.requests.post", flaky_post)
    client = JudgeClient(
        "judge",
        base_url="https://api.example.com/v1",
        api_key="temporary-secret",
        connection_retries=1,
        retry_backoff_seconds=0,
    )

    judgment = client.judge("比较回答", pair_id="P-1")

    assert judgment.winner == "A"
    assert len(calls) == 2


def test_direct_judge_does_not_retry_non_connection_failure(monkeypatch) -> None:
    calls = []

    class Response:
        ok = False
        status_code = 500
        text = "provider failure"

        @staticmethod
        def json():
            return {"error": {"message": "provider failure"}}

    def failed_post(url, **kwargs):
        calls.append(url)
        return Response()

    monkeypatch.setattr("evals.judging.requests.post", failed_post)
    client = JudgeClient(
        "judge",
        base_url="https://api.example.com/v1",
        api_key="temporary-secret",
        connection_retries=1,
        retry_backoff_seconds=0,
    )

    try:
        client.judge("比较回答", pair_id="P-1")
    except RuntimeError:
        pass
    else:
        raise AssertionError("judge error was not raised")

    assert len(calls) == 1


def test_codex_judge_supports_custom_responses_url_and_api_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("evals.judging.shutil.which", lambda command: "/usr/local/bin/codex")
    monkeypatch.setenv("OPENAI_API_KEY", "stale-openai-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://wrong-provider.example/v1")
    payload = json.dumps(_judgment_payload(), ensure_ascii=False)

    def fake_run(command, **kwargs):
        assert kwargs["env"]["EQUIPMENT_EVAL_JUDGE_CODEX_RUNTIME_API_KEY"] == "temporary-secret"
        assert kwargs["env"]["CODEX_API_KEY"] == "temporary-secret"
        assert "OPENAI_API_KEY" not in kwargs["env"]
        assert "OPENAI_BASE_URL" not in kwargs["env"]
        assert any("equipment_eval_judge_openai" in item for item in command)
        stdout = "\n".join(
            [
                json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": payload}}),
                json.dumps({"type": "turn.completed", "usage": {"input_tokens": 11, "output_tokens": 22}}),
            ]
        )
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr("evals.judging.subprocess.run", fake_run)
    client = CodexJudgeClient(
        "gpt-test",
        judge_id="codex-expert-1",
        runtime_root=tmp_path,
        auth_mode="eval_api_key",
        base_url="https://gateway.example/v1/responses",
        api_key="temporary-secret",
    )
    judgment = client.judge("比较回答", pair_id="P-1")
    assert judgment.judge_id == "codex-expert-1"
    assert judgment.winner == "A"
    assert client.last_usage["output_tokens"] == 22


def test_judge_pair_file_accepts_configured_expert_replicas(tmp_path: Path) -> None:
    pairs_path = tmp_path / "pairs.jsonl"
    prompt_path = tmp_path / "prompt.md"
    output_path = tmp_path / "judgments.jsonl"
    write_jsonl(
        pairs_path,
        [{"pair_id": "P-1", "query": "问题", "answer_a": "A", "answer_b": "B"}],
    )
    prompt_path.write_text("{{QUERY}}\n{{ANSWER_A}}\n{{ANSWER_B}}\n{{PAIR_ID}}", encoding="utf-8")
    result = judge_pair_file(
        pairs_path,
        prompt_path,
        output_path,
        judge_configs=[
            {"runtime": "llm_api", "model": "judge", "judge_id": "expert-1"},
            {"runtime": "codex_cli", "model": "judge", "judge_id": "expert-2"},
        ],
        fake=True,
    )
    rows = read_jsonl(output_path)
    assert result["judge_count"] == 2
    assert result["judgment_count"] == 2
    assert result["parallel_workers"] == 1
    assert {row["judge_id"] for row in rows} == {"expert-1", "expert-2"}


def test_real_judges_run_in_parallel_lanes_with_deterministic_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import threading
    import time as time_module

    pairs_path = tmp_path / "pairs.jsonl"
    prompt_path = tmp_path / "prompt.md"
    output_path = tmp_path / "judgments.jsonl"
    write_jsonl(
        pairs_path,
        [
            {"pair_id": "P-1", "query": "问题一", "answer_a": "A", "answer_b": "B"},
            {"pair_id": "P-2", "query": "问题二", "answer_a": "A", "answer_b": "B"},
        ],
    )
    prompt_path.write_text("{{QUERY}}\n{{ANSWER_A}}\n{{ANSWER_B}}\n{{PAIR_ID}}", encoding="utf-8")

    active = {"now": 0, "peak": 0}
    gate = threading.Lock()

    class Response:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {
                "model": "judge",
                "choices": [
                    {"message": {"content": json.dumps(_judgment_payload(), ensure_ascii=False)}}
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 7},
            }

    def fake_post(url, **kwargs):
        with gate:
            active["now"] += 1
            active["peak"] = max(active["peak"], active["now"])
        time_module.sleep(0.05)
        with gate:
            active["now"] -= 1
        return Response()

    monkeypatch.setattr("evals.judging.requests.post", fake_post)
    result = judge_pair_file(
        pairs_path,
        prompt_path,
        output_path,
        judge_configs=[
            {
                "runtime": "llm_api",
                "api_protocol": "chat_completions",
                "base_url": "https://api.example.com/v1",
                "api_key": "k",
                "model": "judge",
                "judge_id": f"expert-{index}",
            }
            for index in (1, 2, 3)
        ],
        fake=False,
        max_workers=3,
    )
    rows = read_jsonl(output_path)
    assert result["judgment_count"] == 6
    assert result["error_count"] == 0
    assert result["parallel_workers"] == 3
    assert active["peak"] >= 2, "judge lanes did not overlap"
    assert [(row["judge_id"], row["pair_id"]) for row in rows] == [
        (f"expert-{index}", pair) for index in (1, 2, 3) for pair in ("P-1", "P-2")
    ]
    assert all(result["usage"][f"expert-{index}"]["completion_tokens"] == 14 for index in (1, 2, 3))


def test_direct_judge_redacts_api_key_from_errors(monkeypatch) -> None:
    secret = "temporary-secret"

    class Response:
        ok = False
        status_code = 401
        text = ""

        @staticmethod
        def json():
            return {"error": {"message": f"invalid {secret}"}}

    monkeypatch.setattr("evals.judging.requests.post", lambda *args, **kwargs: Response())
    client = JudgeClient(
        "judge",
        base_url="https://api.openai.com/v1",
        api_key=secret,
    )
    try:
        client.judge("prompt", pair_id="P-1")
    except RuntimeError as exc:
        assert secret not in str(exc)
        assert "[REDACTED]" in str(exc)
    else:
        raise AssertionError("judge error was not raised")
