from platform_core.config.environment import deep_research_env, env_value


def test_canonical_environment_name_wins_over_legacy(monkeypatch):
    monkeypatch.setenv("DEEP_RESEARCH_SAMPLE", "canonical")
    monkeypatch.setenv("YUXI_SAMPLE", "legacy")

    assert deep_research_env("SAMPLE") == "canonical"


def test_legacy_environment_name_remains_readable_during_migration(monkeypatch):
    monkeypatch.delenv("DEEP_RESEARCH_SAMPLE", raising=False)
    monkeypatch.setenv("YUXI_SAMPLE", "legacy")

    assert deep_research_env("SAMPLE") == "legacy"


def test_intentionally_empty_canonical_value_is_not_replaced(monkeypatch):
    monkeypatch.setenv("DEEP_RESEARCH_SAMPLE", "")
    monkeypatch.setenv("YUXI_SAMPLE", "legacy")

    assert deep_research_env("SAMPLE", "default") == ""


def test_explicit_aliases_are_supported(monkeypatch):
    monkeypatch.setenv("OLD_SAMPLE", "legacy")

    assert env_value("NEW_SAMPLE", legacy_names=("OLD_SAMPLE",)) == "legacy"
