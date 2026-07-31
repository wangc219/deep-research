from pathlib import Path
import json
import subprocess

from evals.adapters import (
    CodexGenericAgentAdapter,
    CompatibleLLMAdapter,
    FullMethodAdapter,
    ResponsesAdapter,
    TongyiDeepResearchAdapter,
    make_adapter,
    parse_codex_jsonl,
    parse_chat_completions_output,
    parse_responses_output,
    normalize_llm_base_url,
)
from evals.models import EvalQuery


ROOT = Path(__file__).parents[2]


def _query() -> EvalQuery:
    return EvalQuery("Q-0001", "低空公开资料研究", "台海", "低空", "easy", "pilot")


def test_fake_responses_adapter_is_offline_and_structured(tmp_path: Path) -> None:
    result = ResponsesAdapter("generic_deep_research", fake=True, web_search=True).run(
        _query(), eval_id="eval-1", output_dir=tmp_path
    )
    assert result.status == "completed"
    assert result.system_id == "generic_deep_research"
    assert result.sources == ["https://fixture.local/generic_deep_research"]


def test_fake_tongyi_and_codex_adapters_are_distinct(tmp_path: Path) -> None:
    tongyi = TongyiDeepResearchAdapter(fake=True).run(
        _query(), eval_id="eval-1", output_dir=tmp_path / "tongyi"
    )
    codex = CodexGenericAgentAdapter(fake=True).run(
        _query(), eval_id="eval-1", output_dir=tmp_path / "codex"
    )
    assert tongyi.status == codex.status == "completed"
    assert tongyi.model_snapshot["provider"] == "dashscope"
    assert codex.model_snapshot["adapter"] == "codex_cli"


def test_tongyi_payload_uses_two_stage_compatible_dashscope_shape() -> None:
    adapter = TongyiDeepResearchAdapter(output_format="model_detailed_report")
    payload = adapter.build_request_payload([{"role": "user", "content": "研究主题"}])
    assert payload == {
        "model": "qwen-deep-research",
        "input": {"messages": [{"role": "user", "content": "研究主题"}]},
        "parameters": {"output_format": "model_detailed_report"},
    }


def test_tongyi_adapter_automates_clarification_and_extracts_references(
    tmp_path: Path, monkeypatch
) -> None:
    adapter = TongyiDeepResearchAdapter(
        base_url="https://workspace.cn-beijing.maas.aliyuncs.com/api/v1",
        api_key="dashscope-secret",
    )
    calls = []

    def fake_stream(messages):
        calls.append(messages)
        if len(calls) == 1:
            return [
                {
                    "request_id": "first",
                    "output": {
                        "message": {
                            "phase": "answer",
                            "content": "请确认重点范围？",
                        }
                    },
                    "usage": {"input_tokens": 2, "output_tokens": 3},
                }
            ]
        return [
            {
                "request_id": "second",
                "output": {
                    "message": {
                        "phase": "WebResearch",
                        "content": "",
                        "extra": {
                            "deep_research": {"query": {"query": "公开资料检索"}}
                        },
                    }
                },
            },
            {
                "request_id": "second",
                "output": {
                    "message": {
                        "phase": "answer",
                        "content": "研究结论。",
                        "extra": {
                            "deep_research": {
                                "references": [
                                    {
                                        "index_number": 1,
                                        "title": "公开来源",
                                        "url": "https://source.example/a",
                                    }
                                ]
                            }
                        },
                    }
                },
                "usage": {"input_tokens": 5, "output_tokens": 8},
            },
        ]

    monkeypatch.setattr(adapter, "_stream_generation", fake_stream)
    result = adapter.run(_query(), eval_id="eval-1", output_dir=tmp_path)
    assert result.status == "completed", result.error
    assert len(calls) == 2
    assert calls[1][1] == {"role": "assistant", "content": "请确认重点范围？"}
    assert result.citations == ["https://source.example/a"]
    assert "[公开来源](https://source.example/a)" in result.answer
    assert result.usage["input_tokens"] == 7
    assert result.usage["api_calls"] == 2
    assert (tmp_path / "tongyi-run-metadata.json").is_file()


def test_parse_responses_output_collects_text_and_sources() -> None:
    answer, citations, sources = parse_responses_output(
        {
            "output": [
                {
                    "type": "web_search_call",
                    "action": {"sources": [{"url": "https://source.example/a"}]},
                },
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "answer",
                            "annotations": [{"url": "https://source.example/b"}],
                        }
                    ],
                },
            ]
        }
    )
    assert answer == "answer"
    assert citations == ["https://source.example/b"]
    assert sources == ["https://source.example/a", "https://source.example/b"]


def test_compatible_llm_builds_tool_free_payloads() -> None:
    responses = CompatibleLLMAdapter(
        api_protocol="responses",
        model="gpt-test",
        max_output_tokens=1200,
        temperature=0.3,
        reasoning_effort="none",
    ).build_request_payload(_query())
    chat = CompatibleLLMAdapter(
        api_protocol="chat_completions",
        model="deepseek-test",
        max_output_tokens=900,
        temperature=0.1,
    ).build_request_payload(_query())
    assert responses["input"]
    assert responses["max_output_tokens"] == 1200
    assert "tools" not in responses and "reasoning" not in responses
    assert chat["messages"][0]["role"] == "user"
    assert chat["max_tokens"] == 900
    assert "tools" not in chat


def test_zhipu_baseline_uses_chat_completions_and_shared_report_brief(tmp_path: Path) -> None:
    adapter = make_adapter(
        "zhipu_llm",
        ROOT,
        fake=True,
        system_config={
            "api_protocol": "chat_completions",
            "base_url": "https://yunwu.ai/v1",
            "model": "glm-5.2",
            "max_output_tokens": 6000,
        },
    )
    payload = adapter.build_request_payload(_query())
    result = adapter.run(_query(), eval_id="eval-zhipu", output_dir=tmp_path)
    assert adapter.endpoint == "https://yunwu.ai/v1/chat/completions"
    assert payload["model"] == "glm-5.2"
    assert payload["max_tokens"] == 6000
    assert "第一层：需求挖掘层——场景·战法/技术·装备能力特征" in payload["messages"][0]["content"]
    assert "⑨ 给出发展优先级建议与近期可启动的抓手" in payload["messages"][0]["content"]
    assert "tools" not in payload
    assert result.status == "completed"
    assert result.system_id == "zhipu_llm"
    assert "智谱 GLM" in result.answer


def test_baseline_default_output_budgets_are_backend_managed() -> None:
    generic = make_adapter("generic_agent", ROOT, fake=True)
    bare = make_adapter("bare_llm", ROOT, fake=True)
    zhipu = make_adapter("zhipu_llm", ROOT, fake=True)

    assert generic.max_output_tokens == 7000
    assert bare.max_output_tokens == 8000
    assert zhipu.max_output_tokens == 8000


def test_parse_chat_completions_output_collects_answer_urls() -> None:
    answer, citations, sources = parse_chat_completions_output(
        {
            "choices": [
                {"message": {"content": "结论见 https://source.example/a"}}
            ]
        }
    )
    assert answer == "结论见 https://source.example/a"
    assert citations == sources == ["https://source.example/a"]


def test_compatible_llm_normalizes_endpoints_and_rejects_unsafe_urls() -> None:
    assert normalize_llm_base_url("https://api.openai.com/v1/responses") == "https://api.openai.com/v1"
    assert normalize_llm_base_url("http://127.0.0.1:11434/v1/chat/completions") == "http://127.0.0.1:11434/v1"
    for value in (
        "http://gateway.example/v1",
        "https://user:pass@gateway.example/v1",
        "https://gateway.example/v1?key=secret",
    ):
        try:
            normalize_llm_base_url(value)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe URL was accepted: {value}")


def test_compatible_llm_calls_chat_completions_without_persisting_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured = {}

    class Response:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {
                "model": "deepseek-chat",
                "choices": [{"message": {"content": "回答"}}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 4},
            }

    def fake_post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr("evals.adapters.requests.post", fake_post)
    result = CompatibleLLMAdapter(
        api_protocol="chat_completions",
        base_url="https://api.deepseek.com/chat/completions",
        api_key="temporary-secret",
        model="deepseek-chat",
    ).run(_query(), eval_id="eval-1", output_dir=tmp_path)
    assert result.status == "completed", result.error
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer temporary-secret"
    assert "temporary-secret" not in json.dumps(result.to_dict())
    assert result.model_snapshot == {
        "protocol": "chat_completions",
        "model": "deepseek-chat",
        "base_url_host": "api.deepseek.com",
    }


def test_compatible_llm_redacts_key_from_provider_errors(tmp_path: Path, monkeypatch) -> None:
    secret = "temporary-secret"

    class Response:
        ok = False
        status_code = 401
        text = ""

        @staticmethod
        def json():
            return {"error": {"message": f"invalid credential {secret}"}}

    monkeypatch.setattr("evals.adapters.requests.post", lambda *args, **kwargs: Response())
    result = CompatibleLLMAdapter(
        api_protocol="responses",
        base_url="https://api.openai.com/v1",
        api_key=secret,
        model="gpt-test",
    ).run(_query(), eval_id="eval-1", output_dir=tmp_path)
    assert result.status == "failed"
    assert secret not in result.error
    assert "[REDACTED]" in result.error


def test_compatible_llm_retries_one_connection_close(tmp_path: Path, monkeypatch) -> None:
    calls = 0

    class Response:
        ok = True
        status_code = 200

        @staticmethod
        def json():
            return {
                "model": "gpt-test",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": "重试后完成"}],
                    }
                ],
            }

    def flaky_post(*args, **kwargs):
        del args, kwargs
        nonlocal calls
        calls += 1
        if calls == 1:
            raise __import__("requests").ConnectionError("remote closed")
        return Response()

    monkeypatch.setattr("evals.adapters.requests.post", flaky_post)
    monkeypatch.setattr("evals.adapters.time.sleep", lambda _seconds: None)
    result = CompatibleLLMAdapter(
        api_protocol="responses",
        base_url="https://api.openai.com/v1",
        api_key="temporary-secret",
        model="gpt-test",
    ).run(_query(), eval_id="eval-1", output_dir=tmp_path)

    assert calls == 2
    assert result.status == "completed"
    assert result.answer == "重试后完成"


def test_deep_research_payload_applies_real_benchmark_controls() -> None:
    adapter = ResponsesAdapter(
        "generic_deep_research",
        model="gpt-5.5",
        reasoning_effort="xhigh",
        web_search=True,
        background=True,
        max_tool_calls=40,
        max_output_tokens=12000,
        web_search_options={
            "required": True,
            "search_context_size": "high",
            "return_token_budget": "unlimited",
            "external_web_access": True,
        },
    )
    payload = adapter.build_request_payload(_query())
    assert payload["background"] is True
    assert payload["reasoning"] == {"effort": "xhigh"}
    assert payload["max_tool_calls"] == 40
    assert payload["max_output_tokens"] == 12000
    assert payload["tool_choice"] == "required"
    assert payload["tools"] == [
        {
            "type": "web_search",
            "search_context_size": "high",
            "return_token_budget": "unlimited",
            "external_web_access": True,
        }
    ]


def test_parse_codex_jsonl_collects_final_message_search_and_usage() -> None:
    rows = [
        {"type": "thread.started", "thread_id": "thread-1"},
        {
            "type": "item.completed",
            "item": {
                "type": "web_search",
                "query": "公开资料",
                "sources": [{"url": "https://source.example/a"}],
            },
        },
        {
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "text": "结论 https://source.example/b",
            },
        },
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 20}},
    ]
    answer, citations, sources, usage, metadata = parse_codex_jsonl(
        "\n".join(json.dumps(row) for row in rows)
    )
    assert answer == "结论 https://source.example/b"
    assert citations == ["https://source.example/b"]
    assert sources == ["https://source.example/a", "https://source.example/b"]
    assert usage["web_search_calls"] == 1
    assert metadata["thread_id"] == "thread-1"


def test_codex_adapter_uses_isolated_home_and_read_only_workspace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("evals.adapters.shutil.which", lambda command: "/usr/local/bin/codex")

    def fake_run(command, **kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, "codex-cli test\n", "")
        assert kwargs["env"]["CODEX_HOME"].startswith(str(tmp_path))
        assert kwargs["env"]["EQUIPMENT_EVAL_CODEX_RUNTIME_API_KEY"] == "secret-key"
        assert "--ignore-user-config" in command
        assert "--ignore-rules" in command
        assert command[command.index("--sandbox") + 1] == "read-only"
        stdout = "\n".join(
            [
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": "回答 https://source.example"},
                    }
                ),
                json.dumps({"type": "turn.completed", "usage": {"input_tokens": 5}}),
            ]
        )
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr("evals.adapters.subprocess.run", fake_run)
    output = tmp_path / "outputs" / "evals" / "run" / "generic_agent" / "Q-0001"
    result = CodexGenericAgentAdapter(
        api_key="secret-key",
        base_url="https://api.openai.com/v1",
    ).run(_query(), eval_id="run", output_dir=output)
    assert result.status == "completed", result.error
    assert (output / "runtime" / "codex-home").is_dir()
    assert (output / "runtime" / "workspace").is_dir()
    assert "secret-key" not in (output / "runtime" / "codex-events.jsonl").read_text()


def test_codex_login_auth_is_symlinked_only_during_run(tmp_path: Path, monkeypatch) -> None:
    source_home = tmp_path / "source-codex"
    source_home.mkdir()
    (source_home / "auth.json").write_text('{"auth_mode":"apikey"}')
    monkeypatch.setattr("evals.adapters.shutil.which", lambda command: "/usr/local/bin/codex")
    monkeypatch.setenv("CODEX_API_KEY", "stale-codex-key")
    monkeypatch.setenv("OPENAI_API_KEY", "stale-openai-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://wrong-provider.example/v1")
    monkeypatch.setenv("CODEX_BASE_URL", "https://wrong-codex.example/v1")

    def fake_run(command, **kwargs):
        if command[-1] == "--version":
            return subprocess.CompletedProcess(command, 0, "codex-cli test\n", "")
        auth_path = Path(kwargs["env"]["CODEX_HOME"]) / "auth.json"
        assert auth_path.is_symlink()
        for name in ("CODEX_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "CODEX_BASE_URL"):
            assert name not in kwargs["env"]
        assert not any("model_provider=" in item for item in command)
        stdout = json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "登录态回答"},
            }
        )
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr("evals.adapters.subprocess.run", fake_run)
    output = tmp_path / "output"
    result = CodexGenericAgentAdapter(
        auth_mode="codex_login",
        source_codex_home=source_home,
        base_url="https://untrusted.example/v1",
        api_key="must-not-be-used",
    ).run(_query(), eval_id="run", output_dir=output)
    assert result.status == "completed", result.error
    assert result.model_snapshot["auth_mode"] == "codex_login"
    assert not (output / "runtime" / "codex-home" / "auth.json").exists()


def test_full_method_fake_adapter_writes_only_to_supplied_eval_dir(tmp_path: Path) -> None:
    output = tmp_path / "outputs" / "evals" / "smoke" / "systems" / "full_method" / "Q-0001"
    result = FullMethodAdapter(ROOT, mode="fake").run(_query(), eval_id="smoke", output_dir=output)
    assert result.status == "completed", result.error
    assert result.answer
    assert (output / "runtime" / "full_method-q-0001" / "report.md").is_file()
    assert not (ROOT / "outputs" / "runs" / "full_method-q-0001").exists()
    resumed = FullMethodAdapter(ROOT, mode="fake").run(_query(), eval_id="smoke", output_dir=output)
    assert resumed.status == "completed", resumed.error


def test_baseline_prompts_share_three_layer_nine_item_task_brief() -> None:
    from evals.adapters import REPORT_TASK_BRIEF, _codex_agent_prompt, _neutral_research_prompt

    codex = _codex_agent_prompt("测试研究问题", max_tool_calls=40, max_output_tokens=7000)
    llm_online = _neutral_research_prompt("测试研究问题", allow_search=True)
    llm_offline = _neutral_research_prompt(
        "测试研究问题", allow_search=False, max_output_tokens=4000
    )
    for prompt in (codex, llm_online, llm_offline):
        assert REPORT_TASK_BRIEF in prompt
        assert "测试研究问题" in prompt
        for leaked_term in ("S1", "S6", "A–H", "equipment_deep_research", "完整方法"):
            assert leaked_term not in prompt
        assert "评测过程" in prompt
    assert "无法联网" in llm_offline
    assert "不展示思维过程" in llm_offline
    assert "不得超过 4000 token" in llm_offline
    assert "可点击" in llm_online
    assert REPORT_TASK_BRIEF.startswith("市场需求挖掘报告：")
    assert REPORT_TASK_BRIEF.count("**【") == 3
    for marker in "①②③④⑤⑥⑦⑧⑨":
        assert marker in REPORT_TASK_BRIEF
    for structure_cue in (
        "典型作战场景",
        "新战法或新概念技术",
        "制胜机理",
        "能力域",
        "定量指标方向",
        "沿用改进/集成创新/原理突破",
        "核心技术清单",
        "耦合关系与短板风险",
        "指标画像",
        "谱系位置",
        "杀伤链/作战体系",
        "可量化方向",
        "优先级",
        "演示验证项目构想",
    ):
        assert structure_cue in REPORT_TASK_BRIEF
