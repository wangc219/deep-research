"""Audit route discovery gold slot evidence records.

This is a gate for benchmark quality, not a discovery step. It verifies that
each gold slot has a manual evidence audit record and that visible extraction
slots are backed by visible evidence. It never feeds gold labels into extraction
or candidate generation.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any


DEFAULT_GOLD_ROUTES = Path("data/benchmarks/route_discovery/gold_routes_v0.jsonl")
DEFAULT_AUDIT = Path("data/benchmarks/route_discovery/gold_slot_evidence_audit_v0.jsonl")
DEFAULT_OUTPUT_JSON = Path("data/benchmarks/route_discovery/gold_slot_evidence_audit_gate_summary.json")
DEFAULT_REPORT = Path("docs/manual-review/route_discovery_gold_slot_evidence_audit_gate.md")

SLOT_KEYS = ("principles", "technologies", "capabilities", "applications")
VERIFIED_VERDICTS = {
    "verified_literal",
    "verified_alias",
    "verified_semantic",
    "inferred_supported",
}
TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".html", ".htm", ".json", ".jsonl"}


def main() -> int:
    args = _parse_args()
    cases = read_jsonl(Path(args.gold_routes))
    audit_rows = read_jsonl(Path(args.audit))
    summary = audit_gold_evidence(
        cases,
        audit_rows,
        project_root=Path(args.project_root).resolve(),
        require_source_files=not args.allow_missing_source_files,
        check_verbatim_excerpts=args.check_verbatim_excerpts,
    )

    output_json = Path(args.output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(summary, Path(args.gold_routes), Path(args.audit)), encoding="utf-8")

    print("gold_slot_evidence_audit_gate=" + json.dumps(_compact_summary(summary), ensure_ascii=False))
    return 0 if summary["ready"] else 1


def audit_gold_evidence(
    cases: list[dict[str, Any]],
    audit_rows: list[dict[str, Any]],
    project_root: Path,
    require_source_files: bool = True,
    check_verbatim_excerpts: bool = False,
) -> dict[str, Any]:
    gold_slots = _gold_slot_index(cases)
    audit_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    duplicate_keys: list[str] = []
    errors: list[str] = []
    warnings: list[str] = []
    verdict_counts: Counter[str] = Counter()
    support_counts: Counter[str] = Counter()
    stage_counts: Counter[str] = Counter()
    visibility_counts: Counter[str] = Counter()
    text_evidence_checked_count = 0
    text_evidence_found_count = 0

    for row in audit_rows:
        key = (
            str(row.get("case_id", "")),
            str(row.get("slot_group", "")),
            str(row.get("slot_name", "")),
        )
        if key in audit_by_key:
            duplicate_keys.append(_format_key(key))
        audit_by_key[key] = row

    for duplicate in duplicate_keys:
        errors.append(f"{duplicate}: duplicate audit record")

    for key, slot in gold_slots.items():
        audit = audit_by_key.get(key)
        formatted = _format_key(key)
        if audit is None:
            errors.append(f"{formatted}: missing audit record")
            continue

        verdict = str(audit.get("verdict", "")).strip()
        support_level = str(audit.get("support_level", "")).strip()
        stage = str(audit.get("evaluation_stage", "")).strip()
        visibility = str(audit.get("gold_visibility", "")).strip()
        verdict_counts.update([verdict])
        support_counts.update([support_level])
        stage_counts.update([stage])
        visibility_counts.update([visibility])

        if verdict not in VERIFIED_VERDICTS:
            errors.append(f"{formatted}: unverified verdict {verdict!r}")
        if not support_level:
            errors.append(f"{formatted}: missing support_level")
        if not str(audit.get("manual_conclusion", "")).strip():
            errors.append(f"{formatted}: missing manual_conclusion")
        if slot.get("evaluation_stage") and stage != slot.get("evaluation_stage"):
            errors.append(
                f"{formatted}: audit evaluation_stage {stage!r} does not match gold {slot.get('evaluation_stage')!r}"
            )
        if slot.get("visibility") and visibility != slot.get("visibility"):
            errors.append(
                f"{formatted}: audit visibility {visibility!r} does not match gold {slot.get('visibility')!r}"
            )

        evidence_rows = [item for item in audit.get("source_evidence", []) if isinstance(item, dict)]
        if not evidence_rows:
            errors.append(f"{formatted}: missing source_evidence")
            continue

        gold_source_ids = {str(source_id) for source_id in slot.get("evidence_source_ids", [])}
        visible_evidence_count = 0
        for evidence in evidence_rows:
            source_id = str(evidence.get("source_id", "")).strip()
            split = str(evidence.get("split", "")).strip()
            source_path = str(evidence.get("source_path", "")).strip()
            excerpt = str(evidence.get("evidence_excerpt", "")).strip()
            if not source_id:
                errors.append(f"{formatted}: evidence missing source_id")
            elif gold_source_ids and source_id not in gold_source_ids:
                errors.append(f"{formatted}: evidence source_id {source_id!r} not listed in gold slot")
            if split == "visible":
                visible_evidence_count += 1
            if not source_path:
                errors.append(f"{formatted}: evidence {source_id or '<missing-source>'} missing source_path")
            else:
                path = _resolve_path(project_root, source_path)
                if require_source_files and not path.exists():
                    errors.append(f"{formatted}: evidence source file missing: {source_path}")
                elif check_verbatim_excerpts and path.exists() and path.suffix.lower() in TEXT_SUFFIXES and excerpt:
                    text_evidence_checked_count += 1
                    if _excerpt_found(path, excerpt):
                        text_evidence_found_count += 1
                    else:
                        warnings.append(f"{formatted}: excerpt not found verbatim in {source_path}")
            if not str(evidence.get("location", "")).strip():
                warnings.append(f"{formatted}: evidence {source_id or '<missing-source>'} missing location")
            if not excerpt:
                errors.append(f"{formatted}: evidence {source_id or '<missing-source>'} missing evidence_excerpt")

        if slot.get("visibility") in {"visible_chunk", "visible_source"} and not visible_evidence_count:
            errors.append(f"{formatted}: {slot.get('visibility')} slot must have at least one visible source evidence")

    extra_audits = sorted(set(audit_by_key) - set(gold_slots))
    for key in extra_audits:
        warnings.append(f"{_format_key(key)}: audit record does not map to current gold slot")

    return {
        "ready": not errors,
        "gold_slot_count": len(gold_slots),
        "audit_record_count": len(audit_rows),
        "verified_audit_count": sum(verdict_counts[verdict] for verdict in VERIFIED_VERDICTS),
        "verdict_counts": dict(verdict_counts),
        "support_counts": dict(support_counts),
        "stage_counts": dict(stage_counts),
        "visibility_counts": dict(visibility_counts),
        "text_evidence_checked_count": text_evidence_checked_count,
        "text_evidence_found_count": text_evidence_found_count,
        "errors": errors,
        "warnings": warnings,
    }


def render_report(summary: dict[str, Any], gold_path: Path, audit_path: Path) -> str:
    lines = [
        "# Route Discovery Gold Evidence Audit Gate",
        "",
        "本报告是 benchmark gold case 的质量门禁：只验证 gold slot 是否有可追溯人工证据，不参与抽取、归一或候选生成。",
        "",
        "## Inputs",
        "",
        f"- gold routes: `{gold_path}`",
        f"- audit records: `{audit_path}`",
        "",
        "## Summary",
        "",
        f"- ready: `{summary['ready']}`",
        f"- gold slots: {summary['gold_slot_count']}",
        f"- audit records: {summary['audit_record_count']}",
        f"- verified audits: {summary['verified_audit_count']}",
        f"- verdict counts: `{summary['verdict_counts']}`",
        f"- support counts: `{summary['support_counts']}`",
        f"- stage counts: `{summary['stage_counts']}`",
        f"- visibility counts: `{summary['visibility_counts']}`",
        f"- text evidence checked/found: {summary['text_evidence_found_count']}/{summary['text_evidence_checked_count']}",
        "",
        "## Interpretation",
        "",
        "- `ready=true` 只表示 gold slot 有人工证据记录，不能说明系统已经命中这些 gold。",
        "- visible extraction slot 必须至少有一条 visible source evidence；holdout-only evidence 不能支撑 visible-only 抽取门槛。",
        "- 默认不逐字校验 `evidence_excerpt`，因为该字段允许人工压缩归纳；需要逐字核查时使用 `--check-verbatim-excerpts`。",
        "",
    ]
    if summary["errors"]:
        lines.extend(["## Errors", ""])
        lines.extend(f"- {error}" for error in summary["errors"])
        lines.append("")
    if summary["warnings"]:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {warning}" for warning in summary["warnings"])
        lines.append("")
    return "\n".join(lines)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rows.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc}") from exc
    return rows


def _gold_slot_index(cases: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    slots: dict[tuple[str, str, str], dict[str, Any]] = {}
    for case in cases:
        case_id = str(case.get("case_id", ""))
        groups = case.get("gold_slots", {})
        for slot_group in SLOT_KEYS:
            for slot in groups.get(slot_group, []):
                if isinstance(slot, dict):
                    slots[(case_id, slot_group, str(slot.get("name", "")))] = slot
    return slots


def _resolve_path(project_root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else project_root / path


def _excerpt_found(path: Path, excerpt: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return _normalize_text(excerpt) in _normalize_text(text)


def _normalize_text(value: str) -> str:
    ignored = set(" \t\r\n-_/\\|()（）[]【】{}<>《》:：;；,，.。'\"“”‘’")
    return "".join(ch for ch in str(value).lower() if ch not in ignored)


def _format_key(key: tuple[str, str, str]) -> str:
    return f"{key[0]}/{key[1]}/{key[2]}"


def _compact_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "ready": summary["ready"],
        "gold_slots": summary["gold_slot_count"],
        "audit_records": summary["audit_record_count"],
        "error_count": len(summary["errors"]),
        "warning_count": len(summary["warnings"]),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-routes", default=str(DEFAULT_GOLD_ROUTES))
    parser.add_argument("--audit", default=str(DEFAULT_AUDIT))
    parser.add_argument("--output-json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--project-root", default=".")
    parser.add_argument(
        "--allow-missing-source-files",
        action="store_true",
        help="Do not fail when audit source_path files are unavailable.",
    )
    parser.add_argument(
        "--check-verbatim-excerpts",
        action="store_true",
        help="Warn when text evidence excerpts are not found verbatim in local text/html/markdown files.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
