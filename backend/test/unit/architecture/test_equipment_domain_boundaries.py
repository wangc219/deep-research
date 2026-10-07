"""架构边界：装备研究领域不得反向依赖平台 HTTP、PostgreSQL 或 Vue。"""

from __future__ import annotations

import ast
from pathlib import Path

DOMAIN_ROOT = Path(__file__).resolve().parents[3] / "package" / "equipment_deep_research"
FORBIDDEN_PREFIXES = (
    "platform_core",
    "server",
    "asyncpg",
    "psycopg",
    "psycopg2",
    "vue",
)
LEGACY_HTTP_ALLOWLIST = {
    "equipment_deep_research/api/app.py",
    "equipment_deep_research/api/auth.py",
    "equipment_deep_research/api/schemas.py",
    "equipment_deep_research/query_library/api.py",
}


def _iter_python_files() -> list[Path]:
    return sorted(path for path in DOMAIN_ROOT.rglob("*.py") if path.is_file())


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_equipment_domain_does_not_import_platform_http_postgres_or_vue() -> None:
    violations: list[str] = []
    for path in _iter_python_files():
        relative = path.relative_to(DOMAIN_ROOT.parent).as_posix()
        for module in _imported_modules(path):
            if any(module == prefix or module.startswith(f"{prefix}.") for prefix in FORBIDDEN_PREFIXES):
                violations.append(f"{relative}:{module}")
            if module in {"fastapi", "starlette"} or module.startswith("fastapi.") or module.startswith("starlette."):
                if relative not in LEGACY_HTTP_ALLOWLIST:
                    violations.append(f"{relative}:{module}")
    assert violations == []


def test_shared_model_telemetry_does_not_depend_on_equipment_adapters() -> None:
    """通用模型计量只依赖平台账本，不能反向绑定装备研究适配层。"""
    root = DOMAIN_ROOT.parent / "platform_core"
    paths = [
        root / "models" / "usage_observer.py",
        root / "agents" / "middlewares" / "token_usage.py",
        root / "repositories" / "model_call_repository.py",
    ]
    for path in paths:
        for module in _imported_modules(path):
            assert not module.startswith(("equipment_deep_research", "platform_core.services.equipment_")), (
                str(path), module
            )
