#!/usr/bin/env python3
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from equipment_deep_research.orchestration.capability_military_value import (  # noqa: E402
    rewrite_capability_for_military_value,
)
from equipment_deep_research.agents.provider import (  # noqa: E402
    _normalize_s6_deterministic_format,
)


REFERENCE_FILES = (
    "branch_deliverables.json",
    "demand_cards.json",
    "capability_panorama.json",
    "round_summary.json",
    "reasoning_traceability.json",
)


EQUIPMENT_ANCHOR_RULES = (
    {
        "direction_terms": ("巡飞弹", "游荡弹药", "精确制导弹药"),
        "anchors": (
            ("Switchblade 600 Block 2", ("switchblade 600",)),
            ("ALTIUS/Launched Effects", ("altius", "launched effects")),
        ),
    },
    {
        "direction_terms": ("无人节点", "无人机群", "无人艇", "小型无人机"),
        "anchors": (
            ("RQ-28A/SRR", ("rq-28a", "short range reconnaissance")),
            ("Ghost-X", ("ghost-x",)),
            ("PDW C-100", ("c-100",)),
            ("Replicator sUSV", ("susv", "small unmanned surface")),
        ),
    },
)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _replace_strings(value: Any, replacements: list[tuple[str, str]]) -> Any:
    if isinstance(value, str):
        for old, new in replacements:
            value = value.replace(old, new)
        return value
    if isinstance(value, list):
        return [_replace_strings(item, replacements) for item in value]
    if isinstance(value, dict):
        return {
            key: _replace_strings(item, replacements) for key, item in value.items()
        }
    return value


def _replace_capability_rows(
    value: Any, rewritten: dict[str, dict[str, Any]]
) -> Any:
    """Synchronize embedded capability cards, including evidence-id changes."""
    if isinstance(value, list):
        return [_replace_capability_rows(item, rewritten) for item in value]
    if isinstance(value, dict):
        capability_id = str(value.get("capability_id", ""))
        if capability_id in rewritten:
            return dict(rewritten[capability_id])
        return {
            key: _replace_capability_rows(item, rewritten)
            for key, item in value.items()
        }
    return value


def _evidence_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if record.get("type") == "EvidenceCard" and isinstance(
            record.get("payload"), dict
        ):
            rows.append(record["payload"])
    return rows


def _attach_public_equipment_anchors(
    capability: dict[str, Any], evidence_rows: list[dict[str, Any]]
) -> dict[str, Any]:
    text = " ".join(
        str(capability.get(key, ""))
        for key in ("name", "equipment_form", "baseline_system")
    ).lower()
    updated = dict(capability)
    matched_labels: list[str] = []
    matched_evidence_ids: list[str] = []
    for rule in EQUIPMENT_ANCHOR_RULES:
        if not any(term.lower() in text for term in rule["direction_terms"]):
            continue
        for label, signals in rule["anchors"]:
            matching = next(
                (
                    row
                    for row in evidence_rows
                    if any(
                        signal in " ".join(
                            str(row.get(key, ""))
                            for key in ("source_title", "claim", "excerpt")
                        ).lower()
                        for signal in signals
                    )
                ),
                None,
            )
            if matching is None:
                continue
            matched_labels.append(label)
            evidence_id = str(matching.get("evidence_id", "")).strip()
            if evidence_id:
                matched_evidence_ids.append(evidence_id)
    if not matched_labels:
        return updated
    anchor_clause = (
        "公开型号/装备族谱锚点包括"
        + "、".join(dict.fromkeys(matched_labels))
        + "；锚点用于公开基线类比，不代表其已满足本研究全部强对抗要求。"
    )
    baseline = str(updated.get("baseline_system", "")).strip().rstrip("。；")
    if anchor_clause not in baseline:
        updated["baseline_system"] = f"{baseline}。{anchor_clause}".lstrip("。")
    updated["evidence_ids"] = list(
        dict.fromkeys(
            [
                *list(updated.get("evidence_ids", [])),
                *matched_evidence_ids,
            ]
        )
    )
    return updated


def _replacement_pairs(before: dict[str, Any], after: dict[str, Any]) -> list[tuple[str, str]]:
    pairs: dict[str, str] = {}
    for key, old in before.items():
        new = after.get(key)
        if (
            isinstance(old, str)
            and isinstance(new, str)
            and old != new
            and len(old.strip()) >= 4
        ):
            pairs[old] = new
    return sorted(pairs.items(), key=lambda pair: len(pair[0]), reverse=True)


def _completed_runs(application_db: Path) -> list[tuple[str, str, str]]:
    connection = sqlite3.connect(application_db)
    try:
        rows = connection.execute(
            "SELECT run_id, payload FROM runs "
            "WHERE json_extract(payload, '$.status') = 'completed' ORDER BY run_id"
        ).fetchall()
    finally:
        connection.close()
    result: list[tuple[str, str, str]] = []
    for run_id, payload_json in rows:
        payload = json.loads(payload_json)
        result.append(
            (
                str(run_id),
                str(payload.get("topic", "")),
                str(payload.get("research_route", "") or payload.get("discovery_branch", "")),
            )
        )
    return result


def _update_domain_jsonl(
    path: Path,
    rewritten: dict[str, dict[str, Any]],
) -> bool:
    if not path.exists():
        return False
    changed = False
    output: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError:
            output.append(raw_line)
            continue
        payload = record.get("payload", {})
        capability_id = str(payload.get("capability_id", ""))
        if record.get("type") == "CapabilityImageItem" and capability_id in rewritten:
            record["payload"] = rewritten[capability_id]
            raw_line = json.dumps(record, ensure_ascii=False, sort_keys=True)
            changed = True
        output.append(raw_line)
    if changed:
        path.write_text("\n".join(output) + "\n", encoding="utf-8")
    return changed


def _update_run_db(path: Path, rewritten: dict[str, dict[str, Any]]) -> bool:
    if not path.exists() or not rewritten:
        return False
    connection = sqlite3.connect(path)
    changed = False
    try:
        for capability_id, payload in rewritten.items():
            cursor = connection.execute(
                "UPDATE domain_objects SET payload_json = ? "
                "WHERE object_type = 'CapabilityImageItem' AND object_id = ?",
                (json.dumps(payload, ensure_ascii=False, sort_keys=True), capability_id),
            )
            changed = changed or cursor.rowcount > 0
        connection.commit()
    finally:
        connection.close()
    return changed


def _update_manifest(run_dir: Path, changed_paths: set[Path]) -> bool:
    manifest_path = run_dir / "delivery-manifest.json"
    if not manifest_path.exists() or not changed_paths:
        return False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_path = {str(item.get("path", "")): item for item in manifest.get("files", [])}
    touched = False
    for path in changed_paths:
        relative = path.relative_to(run_dir).as_posix()
        entry = by_path.get(relative)
        if entry is None or not path.exists():
            continue
        data = path.read_bytes()
        entry["sha256"] = sha256(data).hexdigest()
        entry["size"] = len(data)
        touched = True
    if touched:
        manifest_path.write_bytes(_json_bytes(manifest))
    return touched


def upgrade_run(
    run_dir: Path,
    *,
    topic: str,
    route: str,
    apply: bool,
    evidence_anchors: bool = False,
) -> dict[str, Any]:
    capability_path = run_dir / "capability_images.json"
    if not capability_path.exists():
        return {"changed": False, "directions": []}
    original = json.loads(capability_path.read_text(encoding="utf-8"))
    rewritten: dict[str, dict[str, Any]] = {}
    replacements: list[tuple[str, str]] = []
    directions: list[dict[str, str]] = []
    output: list[dict[str, Any]] = []
    evidence_rows = _evidence_rows(run_dir / "domain.jsonl")
    for row in original:
        refresh_migrated = "不以一般体系补位、通信连续或保障可用作为最终目标" in str(
            row.get("deep_capability_portrait", "")
        )
        updated = rewrite_capability_for_military_value(
            row,
            topic=topic,
            route=route,
            force=refresh_migrated,
        )
        normalized = _normalize_s6_deterministic_format(
            {"concept_directions": [updated]},
            topic=topic,
        ).get("concept_directions", [])
        if normalized and isinstance(normalized[0], dict):
            updated = normalized[0]
        # ``capability_portrait`` is an S6 transport field. Completed-run
        # artifacts store the dataclass field ``deep_capability_portrait``;
        # retaining the transport alias would break strict deserialization.
        updated.pop("capability_portrait", None)
        if evidence_anchors:
            updated = _attach_public_equipment_anchors(updated, evidence_rows)
        output.append(updated)
        if updated == row:
            continue
        capability_id = str(updated.get("capability_id", ""))
        rewritten[capability_id] = updated
        replacements.extend(_replacement_pairs(row, updated))
        directions.append(
            {
                "capability_id": capability_id,
                "old_name": str(row.get("name", "")),
                "new_name": str(updated.get("name", "")),
            }
        )
    if not rewritten:
        return {"changed": False, "directions": []}
    replacements = sorted(dict(replacements).items(), key=lambda pair: len(pair[0]), reverse=True)
    if not apply:
        return {"changed": True, "directions": directions}

    changed_paths: set[Path] = set()
    capability_path.write_bytes(_json_bytes(output))
    changed_paths.add(capability_path)

    if _update_domain_jsonl(run_dir / "domain.jsonl", rewritten):
        changed_paths.add(run_dir / "domain.jsonl")
    if _update_run_db(run_dir / "run.db", rewritten):
        changed_paths.add(run_dir / "run.db")

    for name in REFERENCE_FILES:
        path = run_dir / name
        if not path.exists():
            continue
        before = json.loads(path.read_text(encoding="utf-8"))
        after = _replace_strings(before, replacements)
        after = _replace_capability_rows(after, rewritten)
        if after != before:
            path.write_bytes(_json_bytes(after))
            changed_paths.add(path)

    _update_manifest(run_dir, changed_paths)
    return {
        "changed": True,
        "directions": directions,
        "files": sorted(path.name for path in changed_paths),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="将已完成研究任务中的宽泛能力方向升级为 Query 领域化军事作战能力。"
    )
    parser.add_argument("--apply", action="store_true", help="实际写入；默认仅预览")
    parser.add_argument("--run-id", action="append", default=[], help="仅处理指定 run_id")
    parser.add_argument(
        "--evidence-anchors",
        action="store_true",
        help="用本运行已登记公开证据为能力画像补充型号/装备族谱锚点",
    )
    args = parser.parse_args()

    outputs = ROOT / "outputs"
    selected = set(args.run_id)
    scanned = changed_runs = changed_directions = 0
    for run_id, topic, route in _completed_runs(outputs / "application.db"):
        if selected and run_id not in selected:
            continue
        scanned += 1
        result = upgrade_run(
            outputs / "runs" / run_id,
            topic=topic,
            route=route,
            apply=args.apply,
            evidence_anchors=args.evidence_anchors,
        )
        if not result["changed"]:
            continue
        changed_runs += 1
        changed_directions += len(result["directions"])
        action = "UPDATED" if args.apply else "WOULD_UPDATE"
        print(f"{action} {run_id} {topic}")
        for item in result["directions"]:
            print(f"  {item['capability_id']}: {item['old_name']} -> {item['new_name']}")
    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry-run",
                "scanned_completed_runs": scanned,
                "changed_runs": changed_runs,
                "changed_directions": changed_directions,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
