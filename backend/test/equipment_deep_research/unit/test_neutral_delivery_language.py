from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).parents[3]
FORBIDDEN_TERM = "\u7532\u65b9"
TEXT_SUFFIXES = {".html", ".jsx", ".md", ".py", ".yaml", ".yml"}


def test_product_sources_use_neutral_delivery_language() -> None:
    checked_roots = (
        ROOT / "apps" / "web" / "src",
        ROOT / "configs" / "equipment_deep_research",
        ROOT / "docs",
        ROOT / "output" / "html",
        ROOT / "src" / "equipment_deep_research",
    )
    violations: list[str] = []

    for checked_root in checked_roots:
        for path in checked_root.rglob("*"):
            if path.is_file() and path.suffix in TEXT_SUFFIXES:
                if FORBIDDEN_TERM in path.read_text(encoding="utf-8"):
                    violations.append(str(path.relative_to(ROOT)))

    assert not violations, f"found non-neutral delivery wording in: {violations}"


def test_product_filenames_use_neutral_delivery_language() -> None:
    checked_roots = (ROOT / "docs", ROOT / "output" / "html")
    violations = [
        str(path.relative_to(ROOT))
        for checked_root in checked_roots
        for path in checked_root.rglob("*")
        if FORBIDDEN_TERM in path.name
    ]

    assert not violations, f"found non-neutral delivery wording in filenames: {violations}"
