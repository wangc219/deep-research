import json
from pathlib import Path

from equipment_deep_research.model_profiles import (
    activate_profile,
    activate_swarm_overrides,
    doctor_profile,
    get_profile,
    normalize_profile_id,
    public_profiles,
)


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "model-profiles.yaml"
    path.write_text(
        """version: 1
default_profile: test-gpt
profiles:
  test-gpt:
    label: Test GPT
    provider: codex
    protocol: codex_cli
    model_env: TEST_MODEL
    api_key_env: TEST_KEY
    base_url_env: TEST_URL
    fallback:
      policy: capacity_only
      profiles: [test-ds]
  test-ds:
    provider: deepseek
    protocol: chat_completions
    model_env: DS_MODEL
    api_key_env: DS_KEY
    base_url_env: DS_URL
""",
        encoding="utf-8",
    )
    return path


def test_profiles_are_secret_safe_and_activation_writes_no_key(tmp_path, monkeypatch):
    path = _config(tmp_path)
    monkeypatch.setenv("TEST_KEY", "secret-value")
    monkeypatch.setenv("TEST_URL", "https://example.test/v1")
    monkeypatch.setenv("TEST_MODEL", "test-model")
    monkeypatch.setenv("DS_MODEL", "ds-model")
    payload = public_profiles(path)
    assert payload["active_profile"] == "test-gpt"
    assert payload["profiles"][0]["credential_configured"] is True
    assert "secret-value" not in json.dumps(payload)
    env_file = tmp_path / ".env.local"
    activate_profile("test-ds", path=path, env_file=env_file)
    activate_swarm_overrides({"S3": "test-gpt", "S4": "test-ds"}, path=path, env_file=env_file)
    text = env_file.read_text(encoding="utf-8")
    assert "secret-value" not in text
    assert "EQUIPMENT_DR_PROFILE=test-ds" in text
    assert json.loads(text.split("EQUIPMENT_DR_SWARM_PROFILE_OVERRIDES_JSON=", 1)[1].strip().strip('"').replace('\\"', '"')) == {"S3": "test-gpt", "S4": "test-ds"}


def test_doctor_reports_missing_credentials_without_network_call(tmp_path, monkeypatch):
    path = _config(tmp_path)
    monkeypatch.delenv("DS_KEY", raising=False)
    result = doctor_profile("test-ds", path)
    assert result["credential_configured"] is False
    assert result["reachable"] is False


def test_doctor_reports_missing_model_before_network(tmp_path, monkeypatch):
    path = _config(tmp_path)
    monkeypatch.setenv("DS_KEY", "secret")
    monkeypatch.setenv("DS_URL", "https://example.test/v1")
    monkeypatch.delenv("DS_MODEL", raising=False)
    result = doctor_profile("test-ds", path)
    assert result["model"] == ""
    assert result["reachable"] is False
    assert any("model id is not configured" in item for item in result["errors"])


def test_doctor_matches_relay_prefixed_model_ids(tmp_path, monkeypatch):
    path = _config(tmp_path)
    monkeypatch.setenv("TEST_KEY", "secret")
    monkeypatch.setenv("TEST_URL", "https://relay.example.test/v1")
    monkeypatch.setenv("TEST_MODEL", "gpt-5.5")

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"data":[{"id":"openai/gpt-5.5"},{"id":"deepseek-chat"}]}'

    monkeypatch.setattr(
        "equipment_deep_research.model_profiles.urllib.request.urlopen",
        lambda *args, **kwargs: Response(),
    )
    result = doctor_profile("test-gpt", path)
    assert result["reachable"] is True
    assert result["model_available"] is True
    assert result["models_listed"] == 2


def test_profile_model_is_read_from_environment_not_profile_metadata(tmp_path, monkeypatch):
    path = _config(tmp_path)
    monkeypatch.setenv("EQUIPMENT_DR_MODEL", "env-model")
    monkeypatch.setenv("EQUIPMENT_DR_DEEPSEEK_MODEL", "env-ds-model")
    monkeypatch.setenv("TEST_MODEL", "env-model")
    monkeypatch.setenv("DS_MODEL", "env-ds-model")
    payload = public_profiles(path)
    assert payload["profiles"][0]["model"] == "env-model"
    assert payload["profiles"][1]["model"] == "env-ds-model"

    env_file = tmp_path / ".env.local"
    activate_profile("test-ds", path=path, env_file=env_file)
    text = env_file.read_text(encoding="utf-8")
    assert "EQUIPMENT_DR_PROFILE=test-ds" in text
    assert "EQUIPMENT_DR_MODEL" not in text


def test_legacy_profile_alias_resolves_to_canonical_id(tmp_path, monkeypatch):
    path = tmp_path / "model-profiles.yaml"
    path.write_text(
        """version: 1
default_profile: codex-deepseek
profiles:
  codex-deepseek:
    label: DeepSeek
    provider: codex_deepseek
    model_env: TEST_MODEL
    api_key_env: TEST_KEY
    base_url_env: TEST_URL
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_MODEL", "deepseek-v4-flash")
    monkeypatch.setenv("TEST_KEY", "configured")
    monkeypatch.setenv("TEST_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("EQUIPMENT_DR_PROFILE", "deepseek-openlux")

    assert normalize_profile_id("deepseek-openlux") == "codex-deepseek"
    assert get_profile("deepseek-openlux", path)[0] == "codex-deepseek"
    assert public_profiles(path)["active_profile"] == "codex-deepseek"

    env_file = tmp_path / ".env.local"
    activation = activate_profile("deepseek-openlux", path=path, env_file=env_file)
    swarm = activate_swarm_overrides(
        {"S4": "deepseek-openlux"}, path=path, env_file=env_file
    )

    assert activation["profile_id"] == "codex-deepseek"
    assert swarm["swarm_overrides"] == {"S4": "codex-deepseek"}
    assert "deepseek-openlux" not in env_file.read_text(encoding="utf-8")
