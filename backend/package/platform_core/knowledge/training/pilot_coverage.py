"""Pilot 来源类型、语言和领域覆盖的统一领域规则。"""

from __future__ import annotations

from collections.abc import Iterable


DEFAULT_ACCEPTANCE_LANGUAGES = frozenset({"zh", "en"})


def normalize_acceptance_languages(languages: Iterable[str] | None) -> frozenset[str]:
    """规范化一次 Pilot 验收明确声明的语种范围。"""
    values = frozenset(str(item).strip().lower() for item in (languages or ()) if str(item).strip())
    if not values:
        return DEFAULT_ACCEPTANCE_LANGUAGES
    if "unknown" in values or any(len(item) > 32 for item in values):
        raise ValueError("Pilot 验收语种编码无效")
    return values


def pilot_coverage_blockers(
    *,
    source_types: set[str],
    languages: set[str],
    domains: set[str],
    acceptance_languages: Iterable[str] | None = None,
) -> list[str]:
    """按 1000 篇全论文及显式语种口径判断来源和六领域覆盖。"""
    required_languages = normalize_acceptance_languages(acceptance_languages)
    blockers = []
    if "paper" not in source_types:
        blockers.append("missing_paper_coverage")
    if not required_languages.issubset(languages):
        blocker = (
            "missing_bilingual_coverage"
            if required_languages == DEFAULT_ACCEPTANCE_LANGUAGES
            else "missing_acceptance_language_coverage"
        )
        blockers.append(blocker)
    if len(domains) < 6:
        blockers.append("insufficient_domain_coverage")
    return blockers
