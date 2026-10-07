import sys


def test_import_platform_core_does_not_eagerly_import_knowledge(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delitem(sys.modules, "platform-core", raising=False)
    monkeypatch.delitem(sys.modules, "platform_core.knowledge", raising=False)

    import platform_core

    assert platform_core.get_version() == platform_core.__version__
    assert "platform_core.knowledge" not in sys.modules
