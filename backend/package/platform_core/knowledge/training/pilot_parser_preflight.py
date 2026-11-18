"""对 Pilot 来源清单执行只读 PDF 解析路由预检。"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from platform_core.knowledge.parser.base import DocumentParserException
from platform_core.knowledge.parser.intelligent_router import PDFRoutingDecision, inspect_pdf_routing

PARSER_PREFLIGHT_VERSION = "defense-kg-parser-preflight-v1"
_SUCCESS_STATUS = "succeeded"
_SUPPORTED_ROUTES = {"native_text", "complex_layout", "scanned_or_mixed"}


def load_source_manifest(path: str | Path) -> list[dict[str, Any]]:
    """读取并校验 Pilot JSONL 来源清单的最小稳定字段。"""
    manifest_path = Path(path).expanduser().resolve()
    if not manifest_path.is_file():
        raise ValueError(f"来源清单不存在: {manifest_path}")

    rows: list[dict[str, Any]] = []
    seen_document_ids: set[str] = set()
    with manifest_path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"来源清单第 {line_number} 行不是有效 JSON") from exc
            if not isinstance(row, dict):
                raise ValueError(f"来源清单第 {line_number} 行必须是对象")
            missing = [key for key in ("document_id", "path", "content_sha256", "file_size") if key not in row]
            if missing:
                raise ValueError(f"来源清单第 {line_number} 行缺少字段: {missing}")
            document_id = str(row["document_id"])
            if document_id in seen_document_ids:
                raise ValueError(f"来源清单包含重复 document_id: {document_id}")
            content_sha256 = str(row["content_sha256"]).lower()
            if len(content_sha256) != 64 or any(char not in "0123456789abcdef" for char in content_sha256):
                raise ValueError(f"来源清单第 {line_number} 行 content_sha256 无效")
            seen_document_ids.add(document_id)
            rows.append(dict(row))
    return sorted(rows, key=lambda row: str(row["document_id"]))


def run_parser_preflight(
    manifest: Iterable[dict[str, Any]],
    *,
    sample_limit: int = 12,
    batch_size: int = 25,
    verify_content_sha256: bool = True,
    resume_rows: Iterable[dict[str, Any]] = (),
    inspector: Callable[..., PDFRoutingDecision] = inspect_pdf_routing,
    on_result: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """检查文件指纹和采样页特征，返回逐篇结果、摘要与批次计划。"""
    if sample_limit < 1:
        raise ValueError("sample_limit 必须大于 0")
    if batch_size < 1:
        raise ValueError("batch_size 必须大于 0")

    source_rows = sorted((dict(row) for row in manifest), key=lambda row: str(row["document_id"]))
    resumable = _index_resumable_rows(
        resume_rows,
        sample_limit=sample_limit,
        verify_content_sha256=verify_content_sha256,
    )
    results: list[dict[str, Any]] = []
    reused_count = 0

    for source in source_rows:
        cache_key = _resume_key_for_source(source)
        resumed = resumable.get(cache_key)
        if resumed is not None:
            results.append(resumed)
            reused_count += 1
            continue
        result = _inspect_source(
            source,
            sample_limit=sample_limit,
            verify_content_sha256=verify_content_sha256,
            inspector=inspector,
        )
        results.append(result)
        if on_result is not None:
            on_result(dict(result))

    report = build_parser_preflight_report(
        results,
        sample_limit=sample_limit,
        verify_content_sha256=verify_content_sha256,
        reused_count=reused_count,
    )
    return results, report, build_parser_batch_plan(results, batch_size=batch_size)


def build_parser_preflight_report(
    rows: Iterable[dict[str, Any]],
    *,
    sample_limit: int,
    verify_content_sha256: bool,
    reused_count: int = 0,
) -> dict[str, Any]:
    """汇总路由、失败、页数和预估工作量，不包含原文。"""
    results = list(rows)
    status_counts = Counter(str(row.get("status") or "unknown") for row in results)
    route_counts = Counter(
        str(row.get("route") or "unknown") for row in results if row.get("status") == _SUCCESS_STATUS
    )
    failure_counts = Counter(
        str(row.get("error_code") or "unknown") for row in results if row.get("status") != _SUCCESS_STATUS
    )
    total_pages = sum(int(row.get("total_pages") or 0) for row in results if row.get("status") == _SUCCESS_STATUS)
    sampled_pages = sum(int(row.get("sampled_pages") or 0) for row in results if row.get("status") == _SUCCESS_STATUS)
    total_bytes = sum(int(row.get("file_size") or 0) for row in results)
    elapsed_ms = sum(int(row.get("elapsed_ms") or 0) for row in results)
    trailing_data_recovered = sum(
        1 for row in results if row.get("status") == _SUCCESS_STATUS and row.get("trailing_data_recovered") is True
    )
    documents_with_failed_sample_pages = sum(
        1 for row in results if row.get("status") == _SUCCESS_STATUS and int(row.get("failed_sample_pages") or 0) > 0
    )
    failed_sample_pages = sum(
        int(row.get("failed_sample_pages") or 0) for row in results if row.get("status") == _SUCCESS_STATUS
    )
    documents_with_cid_glyph_pages = sum(
        1 for row in results if row.get("status") == _SUCCESS_STATUS and int(row.get("cid_glyph_pages") or 0) > 0
    )
    cid_glyph_pages = sum(
        int(row.get("cid_glyph_pages") or 0) for row in results if row.get("status") == _SUCCESS_STATUS
    )
    native_pages = sum(
        int(row.get("total_pages") or 0)
        for row in results
        if row.get("status") == _SUCCESS_STATUS and row.get("route") == "native_text"
    )
    structure_pages = sum(
        int(row.get("total_pages") or 0)
        for row in results
        if row.get("status") == _SUCCESS_STATUS and row.get("route") == "complex_layout"
    )
    ocr_pages = sum(
        int(row.get("total_pages") or 0)
        for row in results
        if row.get("status") == _SUCCESS_STATUS and row.get("route") == "scanned_or_mixed"
    )
    return {
        "preflight_version": PARSER_PREFLIGHT_VERSION,
        "sample_limit": sample_limit,
        "verify_content_sha256": verify_content_sha256,
        "ready": status_counts.get(_SUCCESS_STATUS, 0) == len(results) and bool(results),
        "documents": len(results),
        "succeeded": status_counts.get(_SUCCESS_STATUS, 0),
        "failed": len(results) - status_counts.get(_SUCCESS_STATUS, 0),
        "reused_from_resume": reused_count,
        "route_counts": dict(sorted(route_counts.items())),
        "failure_counts": dict(sorted(failure_counts.items())),
        "total_bytes": total_bytes,
        "total_pages": total_pages,
        "sampled_pages": sampled_pages,
        "inspection_elapsed_ms": elapsed_ms,
        "quality_signals": {
            "trailing_data_recovered_documents": trailing_data_recovered,
            "documents_with_failed_sample_pages": documents_with_failed_sample_pages,
            "failed_sample_pages": failed_sample_pages,
            "documents_with_cid_glyph_pages": documents_with_cid_glyph_pages,
            "cid_glyph_pages": cid_glyph_pages,
        },
        "workload_estimate": {
            "native_text_pages": native_pages,
            "structure_layout_pages": structure_pages,
            "ocr_pages": ocr_pages,
            "cpu_weighted_page_units": native_pages + structure_pages * 4 + ocr_pages * 8,
        },
    }


def build_parser_batch_plan(rows: Iterable[dict[str, Any]], *, batch_size: int = 25) -> list[dict[str, Any]]:
    """按路由与文件体积稳定分批，便于后续控制 CPU/OCR 资源。"""
    if batch_size < 1:
        raise ValueError("batch_size 必须大于 0")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("status") == _SUCCESS_STATUS:
            grouped.setdefault(str(row.get("route") or "unknown"), []).append(dict(row))

    batches = []
    for route in sorted(grouped):
        route_rows = sorted(
            grouped[route],
            key=lambda row: (-int(row.get("file_size") or 0), str(row.get("document_id") or "")),
        )
        for offset in range(0, len(route_rows), batch_size):
            members = route_rows[offset : offset + batch_size]
            batches.append(
                {
                    "batch_id": f"{route}-{offset // batch_size + 1:04d}",
                    "route": route,
                    "document_count": len(members),
                    "total_bytes": sum(int(member.get("file_size") or 0) for member in members),
                    "total_pages": sum(int(member.get("total_pages") or 0) for member in members),
                    "document_ids": [str(member["document_id"]) for member in members],
                }
            )
    return batches


def write_parser_preflight_outputs(
    output_dir: str | Path,
    *,
    rows: Iterable[dict[str, Any]],
    report: dict[str, Any],
    batches: Iterable[dict[str, Any]],
) -> dict[str, Path]:
    """以稳定键序写入预检结果、报告和批次计划。"""
    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    paths = {
        "rows": destination / "parser-routing-preflight.jsonl",
        "report": destination / "parser-routing-report.json",
        "batches": destination / "parser-routing-batches.jsonl",
    }
    _write_jsonl(paths["rows"], sorted(rows, key=lambda row: str(row["document_id"])))
    paths["report"].write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_jsonl(paths["batches"], batches)
    return paths


def _inspect_source(
    source: dict[str, Any],
    *,
    sample_limit: int,
    verify_content_sha256: bool,
    inspector: Callable[..., PDFRoutingDecision],
) -> dict[str, Any]:
    path = Path(str(source["path"])).expanduser().resolve()
    started = time.perf_counter()
    base = {
        "preflight_version": PARSER_PREFLIGHT_VERSION,
        "document_id": str(source["document_id"]),
        "content_sha256": str(source["content_sha256"]).lower(),
        "path": str(path),
        "file_size": int(source.get("file_size") or 0),
        "sample_limit": sample_limit,
        "sha256_verified": False,
    }
    if not path.is_file():
        return _failed_row(base, "source_missing", started)
    stat = path.stat()
    actual_size = stat.st_size
    base["source_mtime_ns"] = stat.st_mtime_ns
    if actual_size != base["file_size"]:
        return _failed_row(base, "file_size_mismatch", started, actual_file_size=actual_size)
    if path.suffix.lower() != ".pdf":
        return _failed_row(base, "unsupported_file_type", started)
    if verify_content_sha256:
        actual_sha256 = _sha256_file(path)
        if actual_sha256 != base["content_sha256"]:
            return _failed_row(base, "content_sha256_mismatch", started, actual_sha256=actual_sha256)
        base["sha256_verified"] = True

    try:
        decision = inspector(path, sample_limit=sample_limit)
    except DocumentParserException as exc:
        return _failed_row(base, str(exc.status_code or "routing_inspection_failed"), started)
    except Exception as exc:  # noqa: BLE001
        return _failed_row(base, f"unexpected_{type(exc).__name__}", started)
    if decision.route not in _SUPPORTED_ROUTES:
        return _failed_row(base, "unsupported_route", started)
    return {
        **base,
        "status": _SUCCESS_STATUS,
        **decision.as_metadata(),
        "elapsed_ms": _elapsed_ms(started),
    }


def _index_resumable_rows(
    rows: Iterable[dict[str, Any]],
    *,
    sample_limit: int,
    verify_content_sha256: bool,
) -> dict[tuple[str, str, int], dict[str, Any]]:
    reusable = {}
    for row in rows:
        candidate = dict(row)
        if candidate.get("preflight_version") != PARSER_PREFLIGHT_VERSION:
            continue
        if candidate.get("status") != _SUCCESS_STATUS or int(candidate.get("sample_limit") or 0) != sample_limit:
            continue
        if verify_content_sha256 and candidate.get("sha256_verified") is not True:
            continue
        candidate.setdefault("failed_sample_pages", 0)
        candidate.setdefault("trailing_data_recovered", False)
        reusable[_resume_key(candidate)] = candidate
    return reusable


def _resume_key(row: dict[str, Any]) -> tuple[str, str, int, str, int]:
    return (
        str(row.get("document_id") or ""),
        str(row.get("content_sha256") or "").lower(),
        int(row.get("file_size") or 0),
        str(Path(str(row.get("path") or "")).expanduser().resolve()),
        int(row.get("source_mtime_ns") or 0),
    )


def _resume_key_for_source(row: dict[str, Any]) -> tuple[str, str, int, str, int]:
    path = Path(str(row.get("path") or "")).expanduser().resolve()
    source_mtime_ns = path.stat().st_mtime_ns if path.is_file() else 0
    return _resume_key({**row, "path": str(path), "source_mtime_ns": source_mtime_ns})


def _failed_row(
    base: dict[str, Any],
    error_code: str,
    started: float,
    **metadata: Any,
) -> dict[str, Any]:
    return {
        **base,
        "status": "failed",
        "route": "failed",
        "error_code": error_code,
        **metadata,
        "elapsed_ms": _elapsed_ms(started),
    }


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
