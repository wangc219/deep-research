"""生成可复现的 Pilot 来源清单和金标文档抽样清单。"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict, deque
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .pilot_coverage import (
    DEFAULT_ACCEPTANCE_LANGUAGES,
    normalize_acceptance_languages,
    pilot_coverage_blockers,
)
from .pilot_requirements import PILOT_QUOTAS

PILOT_SOURCE_MANIFEST_VERSION = "defense-kg-pilot-source-v3"
GOLD_SPLIT_COUNTS = {"train": 210, "dev": 30, "test": 60}
_SUPPORTED_SUFFIXES = {".pdf"}


def scan_pilot_corpus(
    *,
    paper_roots: Iterable[str | Path] = (),
    patent_roots: Iterable[str | Path] = (),
    acceptance_languages: Iterable[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """扫描论文和专利目录，按内容 SHA-256 去重并输出权威缺口统计。"""
    required_languages = normalize_acceptance_languages(acceptance_languages)
    roots = [
        *((Path(root), "paper") for root in paper_roots),
        *((Path(root), "patent") for root in patent_roots),
    ]
    if not roots:
        raise ValueError("至少提供一个 paper_root 或 patent_root")

    candidates: list[tuple[Path, Path, str]] = []
    missing_roots = []
    for root, source_type in roots:
        resolved_root = root.expanduser().resolve()
        if not resolved_root.is_dir():
            missing_roots.append(str(resolved_root))
            continue
        candidates.extend(
            (path, resolved_root, source_type)
            for path in sorted(resolved_root.rglob("*"))
            if path.is_file() and path.suffix.lower() in _SUPPORTED_SUFFIXES
        )
    if missing_roots:
        raise ValueError(f"语料目录不存在: {missing_roots}")

    manifest = []
    duplicate_paths: dict[str, list[str]] = defaultdict(list)
    seen_hashes: dict[str, dict[str, Any]] = {}
    for path, root, source_type in sorted(candidates, key=lambda item: str(item[0])):
        content_sha256 = _sha256_file(path)
        duplicate_paths[content_sha256].append(str(path))
        if content_sha256 in seen_hashes:
            continue
        relative_path = path.relative_to(root)
        item = {
            "manifest_version": PILOT_SOURCE_MANIFEST_VERSION,
            "document_id": f"src_{content_sha256}",
            "source_type": source_type,
            "language": _detect_language(path.name),
            "acceptance_languages": sorted(required_languages),
            "domain": _domain_from_relative_path(relative_path),
            "title": path.stem,
            "filename": path.name,
            "path": str(path.resolve()),
            "relative_path": str(relative_path),
            "content_sha256": content_sha256,
            "file_size": path.stat().st_size,
        }
        manifest.append(item)
        seen_hashes[content_sha256] = item

    manifest.sort(key=lambda item: (item["source_type"], item["content_sha256"], item["path"]))
    duplicates = [
        {"content_sha256": digest, "paths": paths}
        for digest, paths in sorted(duplicate_paths.items())
        if len(paths) > 1
    ]
    return manifest, build_pilot_inventory_report(
        manifest,
        duplicates=duplicates,
        acceptance_languages=required_languages,
    )


def build_pilot_inventory_report(
    manifest: list[dict[str, Any]],
    *,
    duplicates: list[dict[str, Any]] | None = None,
    acceptance_languages: Iterable[str] | None = None,
) -> dict[str, Any]:
    """按照 DOCX/Pilot 口径判定来源覆盖，不用文件总数冒充有效来源数。"""
    required_languages = _manifest_acceptance_languages(manifest, acceptance_languages)
    source_counts = Counter(str(item.get("source_type") or "unknown") for item in manifest)
    language_counts = Counter(str(item.get("language") or "unknown") for item in manifest)
    domains = sorted({str(item.get("domain") or "") for item in manifest if str(item.get("domain") or "")})
    actual = {
        "source_documents": len(manifest),
        "paper_documents": source_counts.get("paper", 0),
        "patent_documents": source_counts.get("patent", 0),
        "gold_documents_available": min(len(manifest), PILOT_QUOTAS["gold_documents"]),
    }
    criteria = [
        _criterion("source_documents", actual["source_documents"], PILOT_QUOTAS["source_documents"]),
        _criterion("paper_documents", actual["paper_documents"], PILOT_QUOTAS["paper_documents"]),
        _criterion("patent_documents", actual["patent_documents"], PILOT_QUOTAS["patent_documents"]),
        _criterion("gold_documents_available", actual["gold_documents_available"], PILOT_QUOTAS["gold_documents"]),
        {
            "id": (
                "bilingual_coverage"
                if required_languages == DEFAULT_ACCEPTANCE_LANGUAGES
                else "acceptance_language_coverage"
            ),
            "actual": {language: language_counts.get(language, 0) for language in sorted(required_languages)},
            "required": sorted(required_languages),
            "passed": all(language_counts.get(language, 0) > 0 for language in required_languages),
        },
        {
            "id": "domain_coverage",
            "actual": len(domains),
            "required": 6,
            "passed": len(domains) >= 6,
        },
    ]
    failed_criteria = [item["id"] for item in criteria if not item["passed"]]
    return {
        "manifest_version": PILOT_SOURCE_MANIFEST_VERSION,
        "ready": not failed_criteria,
        "failed_criteria": failed_criteria,
        "criteria": criteria,
        "actual": actual,
        "source_type_counts": dict(sorted(source_counts.items())),
        "language_counts": dict(sorted(language_counts.items())),
        "acceptance_languages": sorted(required_languages),
        "domains": domains,
        "total_bytes": sum(int(item.get("file_size") or 0) for item in manifest),
        "duplicate_content_groups": duplicates or [],
    }


def select_gold_documents(
    manifest: list[dict[str, Any]],
    *,
    count: int = PILOT_QUOTAS["gold_documents"],
    allow_incomplete_coverage: bool = False,
    acceptance_languages: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """按来源、语言和领域分层轮询，确定性选择文档并做 210/30/60 切分。"""
    if count != sum(GOLD_SPLIT_COUNTS.values()):
        raise ValueError(f"当前金标契约固定要求 {sum(GOLD_SPLIT_COUNTS.values())} 篇")
    unique_by_document_id = {str(item["document_id"]): item for item in manifest}
    if len(unique_by_document_id) < count:
        raise ValueError(f"唯一来源不足 {count} 篇，当前仅 {len(unique_by_document_id)} 篇")
    non_human = [
        str(item["document_id"])
        for item in unique_by_document_id.values()
        if str((item.get("domain_annotation") or {}).get("kind") or "") != "human"
    ]
    if non_human:
        raise ValueError(f"正式 Gold 选择只接受显式 human 领域标注，当前有 {len(non_human)} 篇不合格: {non_human[:5]}")
    required_languages = _manifest_acceptance_languages(manifest, acceptance_languages)
    coverage_blockers = pilot_coverage_blockers(
        source_types={str(item.get("source_type") or "unknown") for item in unique_by_document_id.values()},
        languages={str(item.get("language") or "unknown") for item in unique_by_document_id.values()},
        domains={str(item.get("domain") or "") for item in unique_by_document_id.values() if item.get("domain")},
        acceptance_languages=required_languages,
    )
    if coverage_blockers and not allow_incomplete_coverage:
        raise ValueError(f"来源语料覆盖不足，不能生成正式金标选择清单: {coverage_blockers}")

    strata: dict[tuple[str, str, str], deque[dict[str, Any]]] = defaultdict(deque)
    for item in sorted(unique_by_document_id.values(), key=lambda value: str(value["content_sha256"])):
        key = (
            str(item.get("source_type") or "unknown"),
            str(item.get("language") or "unknown"),
            str(item.get("domain") or "unknown"),
        )
        strata[key].append(item)

    selected = []
    active_keys = sorted(strata)
    while len(selected) < count and active_keys:
        next_keys = []
        for key in active_keys:
            if len(selected) >= count:
                break
            bucket = strata[key]
            if bucket:
                selected.append(bucket.popleft())
            if bucket:
                next_keys.append(key)
        active_keys = next_keys

    split_remaining = dict(GOLD_SPLIT_COUNTS)
    split_capacity = dict(GOLD_SPLIT_COUNTS)
    result = []
    for item in selected:
        split = max(
            (name for name, remaining in split_remaining.items() if remaining > 0),
            key=lambda name: (split_remaining[name] / split_capacity[name], split_capacity[name]),
        )
        split_remaining[split] -= 1
        result.append(
            {
                "document_id": item["document_id"],
                "split": split,
                "source_type": item["source_type"],
                "language": item["language"],
                "acceptance_languages": sorted(required_languages),
                "domain": item["domain"],
                "domain_annotation_kind": "human",
                "title": item["title"],
                "path": item["path"],
                "content_sha256": item["content_sha256"],
            }
        )
    return result


def _manifest_acceptance_languages(
    manifest: list[dict[str, Any]],
    acceptance_languages: Iterable[str] | None,
) -> frozenset[str]:
    """读取显式参数或清单内一致的验收语种声明。"""
    if acceptance_languages is not None:
        return normalize_acceptance_languages(acceptance_languages)
    profiles = {
        tuple(sorted(normalize_acceptance_languages(item.get("acceptance_languages"))))
        for item in manifest
        if item.get("acceptance_languages")
    }
    if len(profiles) > 1:
        raise ValueError("Pilot 来源清单包含不一致的验收语种声明")
    if profiles:
        return frozenset(next(iter(profiles)))
    return DEFAULT_ACCEPTANCE_LANGUAGES


def _criterion(identifier: str, actual: int, required: int) -> dict[str, Any]:
    return {"id": identifier, "actual": actual, "required": required, "passed": actual >= required}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _detect_language(filename: str) -> str:
    has_zh = bool(any("\u4e00" <= char <= "\u9fff" for char in filename))
    has_latin = bool(any("a" <= char.lower() <= "z" for char in filename))
    if has_zh:
        return "zh"
    if has_latin:
        return "en"
    return "unknown"


def _domain_from_relative_path(relative_path: Path) -> str:
    return relative_path.parts[0][:256] if len(relative_path.parts) > 1 else ""
