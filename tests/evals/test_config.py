from pathlib import Path

import yaml

from evals.config import config_status, load_eval_config, resolved_system_config, validate_eval_config


ROOT = Path(__file__).parents[2]


def test_real_baseline_config_is_valid_and_keeps_secrets_hidden(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_EVAL_OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("EQUIPMENT_EVAL_OPENAI_API_KEY", "openai-secret")
    monkeypatch.setenv(
        "EQUIPMENT_EVAL_DASHSCOPE_BASE_URL",
        "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1",
    )
    monkeypatch.setenv("EQUIPMENT_EVAL_DASHSCOPE_API_KEY", "dashscope-secret")
    monkeypatch.setenv(
        "EQUIPMENT_EVAL_ZHIPU_BASE_URL",
        "https://open.bigmodel.cn/api/paas/v4",
    )
    monkeypatch.setenv("EQUIPMENT_EVAL_ZHIPU_API_KEY", "zhipu-secret")
    config = load_eval_config(ROOT / "evals" / "config.yaml", project_root=ROOT)
    status = config_status(config)
    assert status["ready"] is True
    assert status["providers"]["openai"]["base_url_host"] == "api.openai.com"
    assert status["providers"]["dashscope"]["ready"] is True
    assert status["providers"]["zhipu"]["base_url_host"] == "open.bigmodel.cn"
    assert "openai-secret" not in str(status)
    assert "dashscope-secret" not in str(status)
    assert "zhipu-secret" not in str(status)
    deep = resolved_system_config(config, "generic_deep_research")
    assert deep["api_key"] == "dashscope-secret"
    assert deep["model"] == "qwen-deep-research"
    assert deep["output_format"] == "model_detailed_report"
    zhipu = resolved_system_config(config, "zhipu_llm")
    assert zhipu["api_key"] == "zhipu-secret"
    assert zhipu["api_protocol"] == "chat_completions"
    assert zhipu["model"] == "glm-5.2"


def test_config_keeps_baseline_mechanisms_distinct(monkeypatch) -> None:
    monkeypatch.setenv("EQUIPMENT_EVAL_OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("EQUIPMENT_EVAL_OPENAI_API_KEY", "secret")
    monkeypatch.setenv(
        "EQUIPMENT_EVAL_DASHSCOPE_BASE_URL",
        "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1",
    )
    monkeypatch.setenv("EQUIPMENT_EVAL_DASHSCOPE_API_KEY", "secret")
    monkeypatch.setenv(
        "EQUIPMENT_EVAL_ZHIPU_BASE_URL",
        "https://yunwu.ai/v1",
    )
    monkeypatch.setenv("EQUIPMENT_EVAL_ZHIPU_API_KEY", "secret")
    config = load_eval_config(ROOT / "evals" / "config.yaml", project_root=ROOT)
    systems = config["systems"]
    assert systems["generic_deep_research"]["adapter"] == "dashscope_deep_research"
    assert systems["generic_deep_research"]["provider"] == "dashscope"
    assert systems["generic_agent"]["adapter"] == "codex_cli"
    assert systems["generic_agent"]["sandbox"] == "read-only"
    assert systems["generic_agent"]["web_search"]["enabled"] is True
    assert systems["bare_llm"]["adapter"] == "compatible_llm"
    assert systems["bare_llm"]["api_protocol"] == "responses"
    assert systems["bare_llm"]["web_search"]["enabled"] is False
    assert systems["zhipu_llm"]["adapter"] == "compatible_llm"
    assert systems["zhipu_llm"]["provider"] == "zhipu"
    assert systems["zhipu_llm"]["api_protocol"] == "chat_completions"
    assert systems["zhipu_llm"]["web_search"]["enabled"] is False


def test_config_rejects_responses_adapter_for_generic_agent() -> None:
    payload = yaml.safe_load((ROOT / "evals" / "config.yaml").read_text())
    payload["systems"]["generic_agent"]["adapter"] = "responses"
    try:
        validate_eval_config(payload)
    except ValueError as exc:
        assert "codex_cli" in str(exc)
    else:
        raise AssertionError("invalid generic-agent adapter was accepted")


def test_selected_config_check_does_not_require_dashscope(tmp_path: Path, monkeypatch) -> None:
    auth_dir = tmp_path / ".codex"
    auth_dir.mkdir()
    (auth_dir / "auth.json").write_text("{}")
    monkeypatch.setattr("evals.config.Path.home", lambda: tmp_path)
    monkeypatch.setattr(
        "evals.config._codex_status",
        lambda command: {"command": command, "present": True, "path": "/bin/codex", "version": "test"},
    )
    monkeypatch.setenv("EQUIPMENT_EVAL_OPENAI_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setenv("EQUIPMENT_EVAL_OPENAI_API_KEY", "benchmark-key")
    monkeypatch.setenv("EQUIPMENT_EVAL_DASHSCOPE_BASE_URL", "")
    monkeypatch.setenv("EQUIPMENT_EVAL_DASHSCOPE_API_KEY", "")
    config = load_eval_config(ROOT / "evals" / "config.yaml", project_root=ROOT)
    status = config_status(
        config,
        selected_systems=["full_method", "generic_agent"],
    )
    assert status["ready"] is True
    assert status["system_readiness"] == {
        "full_method": True,
        "generic_agent": True,
    }
