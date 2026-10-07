"""Import-boundary checks for the package's layered architecture.

This is intentionally a small AST-based checker rather than a runtime import
hack.  It can run in a clean interpreter, does not execute application code,
and is therefore suitable for pre-commit and CI checks while modules are being
split by multiple developers.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import sys


PACKAGE = "equipment_deep_research"

# The left-hand side is the owning layer.  A rule is only concerned with
# direct imports; transitive dependencies are checked by the imported module's
# own rule.  Composition roots (API, interfaces and application.factory) may
# depend on lower layers by design.
FORBIDDEN_IMPORTS: dict[str, frozenset[str]] = {
    # Configuration is a process-boundary value object.  Keeping it free of
    # application/framework imports lets every composition root inject the
    # same settings without creating a dependency cycle.
    "config": frozenset(
        {
            "api", "interfaces", "application", "orchestration", "harness", "agents",
            "providers", "tools", "persistence", "queue", "deep_runtime", "delivery",
            "query_library",
        }
    ),
    "domain": frozenset(
        {
            "api", "interfaces", "application", "orchestration", "harness", "agents",
            "providers", "tools", "persistence", "queue", "deep_runtime", "delivery",
            "query_library",
        }
    ),
    "contracts": frozenset(
        {
            "api", "interfaces", "application", "orchestration", "harness", "agents",
            "providers", "tools", "persistence", "queue", "deep_runtime", "delivery",
            "query_library",
        }
    ),
    "providers": frozenset({"api", "interfaces", "orchestration", "harness", "agents", "persistence", "queue"}),
    "persistence": frozenset({"api", "interfaces", "orchestration", "harness", "deep_runtime", "providers", "agents", "tools", "queue"}),
    # Tool authorization consumes the stable AgentSpec protocol.  It must not
    # import the executable registry, which would pull prompts and providers
    # into the low-level tool layer.
    "tools": frozenset({"agents"}),
}


@dataclass(frozen=True)
class ArchitectureViolation:
    source: str
    target: str
    line: int

    def __str__(self) -> str:
        return f"{self.source}:{self.line}: {self.target} is outside its layer boundary"


@dataclass(frozen=True)
class ModuleMetric:
    """Small, static metric used to keep future module growth visible."""

    module: str
    lines: int
    direct_imports: int


def module_metrics(source_root: str | Path) -> list[ModuleMetric]:
    """Return line/import counts without importing application modules."""

    root = Path(source_root).resolve()
    metrics: list[ModuleMetric] = []
    for path in sorted(root.rglob("*.py")):
        module = module_name_for_path(path, root)
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
        except (OSError, SyntaxError):
            continue
        imports = sum(
            1
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
        )
        metrics.append(ModuleMetric(module, text.count("\n") + 1, imports))
    return metrics


def oversized_modules(
    source_root: str | Path,
    *,
    line_limit: int = 1000,
) -> list[ModuleMetric]:
    """Return large modules for refactoring dashboards (informational only)."""

    return [item for item in module_metrics(source_root) if item.lines > line_limit]


def _package_layer(module: str) -> str | None:
    parts = module.split(".")
    if len(parts) < 2 or parts[0] != PACKAGE:
        return None
    return parts[1]


def _resolve_from_import(module: str, node: ast.ImportFrom) -> list[str]:
    if node.level == 0:
        return [node.module or alias.name for alias in node.names]
    base = module.split(".")
    # A relative import at level one resolves from the current package.
    anchor = max(1, len(base) - node.level)
    prefix = base[:anchor]
    if node.module:
        prefix.extend(node.module.split("."))
    return [".".join([*prefix, alias.name]) for alias in node.names]


def _iter_imports(
    module: str,
    tree: ast.AST,
    *,
    include_nested: bool = True,
) -> list[tuple[str, int]]:
    imports: list[tuple[str, int]] = []
    nodes = ast.walk(tree) if include_nested else tree.body  # type: ignore[attr-defined]
    for node in nodes:
        if isinstance(node, ast.Import):
            imports.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.extend((target, node.lineno) for target in _resolve_from_import(module, node))
    return imports


def module_name_for_path(path: Path, source_root: Path) -> str:
    relative = path.relative_to(source_root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join([PACKAGE, *parts])


def find_violations(source_root: str | Path) -> list[ArchitectureViolation]:
    """Return direct imports that cross a forbidden package boundary."""

    root = Path(source_root).resolve()
    violations: list[ArchitectureViolation] = []
    for path in sorted(root.rglob("*.py")):
        module = module_name_for_path(path, root)
        layer = _package_layer(module)
        if layer not in FORBIDDEN_IMPORTS:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        for target, line in _iter_imports(module, tree):
            target_layer = _package_layer(target)
            if target_layer in FORBIDDEN_IMPORTS[layer]:
                violations.append(ArchitectureViolation(module, target, line))
    return violations


def import_graph(
    source_root: str | Path,
    *,
    include_nested: bool = False,
) -> dict[str, frozenset[str]]:
    """Build a graph of local package imports without executing modules.

    Nested imports are excluded by default because they are often deliberate
    late-bound adapters.  Callers can opt in when auditing runtime coupling.
    """

    root = Path(source_root).resolve()
    paths = sorted(root.rglob("*.py"))
    modules = {module_name_for_path(path, root): path for path in paths}
    graph: dict[str, set[str]] = {module: set() for module in modules}
    for module, path in modules.items():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        for target, _line in _iter_imports(module, tree, include_nested=include_nested):
            if not target.startswith(PACKAGE):
                continue
            candidates = [
                candidate
                for candidate in modules
                if target == candidate or target.startswith(candidate + ".")
            ]
            if candidates:
                graph[module].add(max(candidates, key=len))
    return {module: frozenset(targets) for module, targets in graph.items()}


def find_import_cycles(
    source_root: str | Path,
    *,
    include_nested: bool = False,
) -> list[tuple[str, ...]]:
    """Return strongly connected local import components with more than one node."""

    graph = import_graph(source_root, include_nested=include_nested)
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    active: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        active.add(node)
        for target in graph[node]:
            if target not in indices:
                visit(target)
                lowlinks[node] = min(lowlinks[node], lowlinks[target])
            elif target in active:
                lowlinks[node] = min(lowlinks[node], indices[target])
        if lowlinks[node] != indices[node]:
            return
        component: list[str] = []
        while True:
            target = stack.pop()
            active.remove(target)
            component.append(target)
            if target == node:
                break
        if len(component) > 1:
            components.append(tuple(sorted(component)))

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return sorted(components)


def assert_boundaries(source_root: str | Path) -> None:
    violations = find_violations(source_root)
    if violations:
        formatted = "\n".join(str(item) for item in violations)
        raise AssertionError(f"architecture boundary violations:\n{formatted}")


def main() -> int:
    root = Path(__file__).resolve().parent
    violations = find_violations(root)
    if violations:
        print("\n".join(str(item) for item in violations), file=sys.stderr)
        return 1
    print("architecture boundaries: OK")
    return 0


__all__ = [
    "ArchitectureViolation", "FORBIDDEN_IMPORTS", "ModuleMetric", "assert_boundaries",
    "find_import_cycles", "find_violations", "import_graph", "main",
    "module_metrics", "module_name_for_path", "oversized_modules",
]


if __name__ == "__main__":
    raise SystemExit(main())
