import sys
from pathlib import Path


def test_import_platform_core_does_not_eagerly_import_knowledge(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delitem(sys.modules, "platform-core", raising=False)
    monkeypatch.delitem(sys.modules, "platform_core.knowledge", raising=False)

    import platform_core

    assert platform_core.get_version() == platform_core.__version__
    assert "platform_core.knowledge" not in sys.modules


def test_sdist_manifest_covers_all_python_modules() -> None:
    """防止 editable 环境掩盖源码包遗漏新增模块。"""
    backend_root = Path(__file__).resolve().parents[2]
    package_root = backend_root / "package"
    declared = set((package_root / "platform_core.egg-info" / "SOURCES.txt").read_text().splitlines())
    actual = set()
    for path in package_root.rglob("*.py"):
        relative = path.relative_to(package_root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        actual.add(relative.as_posix())

    assert actual <= declared
