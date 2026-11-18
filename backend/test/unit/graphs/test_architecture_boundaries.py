from __future__ import annotations

import ast
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[3]
REPOSITORY_ROOT = BACKEND_ROOT.parent
GRAPH_ROOT = BACKEND_ROOT / "package" / "platform_core" / "knowledge" / "graphs"

PURE_GRAPH_MODULES = (
    "acceptance_policy.py",
    "defense_ontology.py",
    "entity_alignment.py",
    "entity_identity.py",
    "evolution_analysis.py",
    "extraction_cache.py",
    "innovation_discovery.py",
    "ontology_versioning.py",
    "path_discovery.py",
    "pipeline_config.py",
    "projection_contract.py",
    "requirement_analysis.py",
    "solution_assessment.py",
)
DOMAIN_FORBIDDEN_PREFIXES = (
    "fastapi",
    "neo4j",
    "pymilvus",
    "server",
    "sqlalchemy",
    "platform_core.repositories",
    "platform_core.services",
    "platform_core.storage",
)
SIDECAR_FORBIDDEN_PREFIXES = (
    "neo4j",
    "pymilvus",
    "server",
    "sqlalchemy",
    "platform_core",
)


def _imported_modules(path: Path) -> set[str]:
    """解析一个 Python 文件的显式 import，不执行被检查模块。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _forbidden_imports(paths: list[Path], prefixes: tuple[str, ...]) -> list[str]:
    """返回触碰禁用依赖前缀的稳定、可读违规列表。"""
    violations: list[str] = []
    for path in sorted(paths):
        for module in sorted(_imported_modules(path)):
            if any(module == prefix or module.startswith(f"{prefix}.") for prefix in prefixes):
                violations.append(f"{path.relative_to(REPOSITORY_ROOT)} -> {module}")
    return violations


def test_graph_domain_modules_do_not_depend_on_runtime_adapters() -> None:
    """本体、对齐和推理算法保持为无数据库与无 HTTP 的领域模块。"""
    paths = [GRAPH_ROOT / name for name in PURE_GRAPH_MODULES]

    assert all(path.is_file() for path in paths)
    assert _forbidden_imports(paths, DOMAIN_FORBIDDEN_PREFIXES) == []


def test_shared_ie_contracts_are_independent_from_all_runtimes() -> None:
    """兼容 DTO 不得把旧抽取器依赖带入 LightRAG 主运行时。"""
    paths = [
        BACKEND_ROOT / "package" / "defense_document_re_contract.py",
    ]

    assert all(path.is_file() for path in paths)
    assert _forbidden_imports(paths, SIDECAR_FORBIDDEN_PREFIXES) == []


def test_graph_router_does_not_bypass_service_boundaries() -> None:
    """HTTP Router 不直接依赖 Repository 或具体图数据库驱动。"""
    router = BACKEND_ROOT / "server" / "routers" / "graph_router.py"

    assert (
        _forbidden_imports(
            [router],
            ("neo4j", "pymilvus", "platform_core.repositories"),
        )
        == []
    )
