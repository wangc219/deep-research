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
    _capability_direction_quality_issues,
    _normalize_s6_deterministic_format,
    _s6_delivery_blocking_issues,
)
from equipment_deep_research.domain.models import to_plain  # noqa: E402
from equipment_deep_research.domain.store import SqliteRunStore  # noqa: E402
from equipment_deep_research.harness.recovery import (  # noqa: E402
    _restore_domain_store,
)
from equipment_deep_research.orchestration.winning import (  # noqa: E402
    WinningMechanismEngine,
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


def _run_context(run_dir: Path) -> tuple[str, str]:
    sqlite_store = SqliteRunStore(run_dir / "run.db", run_id=run_dir.name)
    try:
        store = _restore_domain_store(sqlite_store.domain_objects())
    finally:
        sqlite_store.close()
    problem = next(iter(store.problems.values()))
    route = str(problem.research_route or "")
    if route in {"", "auto"}:
        summary_path = run_dir / "round_summary.json"
        summary = (
            json.loads(summary_path.read_text(encoding="utf-8"))
            if summary_path.exists()
            else {}
        )
        discovery = summary.get("discovery_branch", {})
        if isinstance(discovery, dict):
            route = str(discovery.get("primary", ""))
        elif isinstance(discovery, str):
            route = discovery
    return str(problem.topic), route or "G"


def _latest_s6_checkpoint(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "agent_sessions" / "winning_mechanism.jsonl"
    if not path.exists():
        raise RuntimeError(f"missing winning-mechanism checkpoint: {path}")
    for raw_line in reversed(path.read_text(encoding="utf-8").splitlines()):
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        result = row.get("result")
        if (
            row.get("event_type") in {"model_checkpoint", "model_result"}
            and isinstance(result, dict)
            and isinstance(result.get("concept_directions"), list)
            and result["concept_directions"]
        ):
            return dict(result)
    raise RuntimeError(f"no S6 model checkpoint with concept directions in {path}")


def _direction_family(value: dict[str, Any]) -> str:
    text = " ".join(
        str(value.get(key, ""))
        for key in (
            "name",
            "title",
            "equipment_form",
            "equipment_forms",
            "project_function",
            "function",
        )
    ).lower()
    if any(marker in text for marker in ("高功率微波", "hpm", "微波巡飞")):
        return "high_power_microwave"
    if any(marker in text for marker in ("反辐射", "辐射源", "射频复核")):
        return "anti_radiation_loitering"
    if any(marker in text for marker in ("无人水面", "无人艇", "半潜")):
        return "unmanned_surface_launcher"
    if any(marker in text for marker in ("发射车", "岛岸", "陆基无人巡飞火力舱")):
        return "land_loitering_launcher"
    if "低成本" in text and any(marker in text for marker in ("弹药", "效应器")):
        return "low_cost_munition_family"
    return ""


def _concrete_direction_name(direction: dict[str, Any]) -> str:
    family = _direction_family(direction)
    return {
        "unmanned_surface_launcher": "机动式无人水面巡航弹释放艇",
        "anti_radiation_loitering": "多模复核反辐射巡飞弹",
        "land_loitering_launcher": "无人值守岛岸巡飞弹发射车",
        "low_cost_munition_family": "模块化低成本巡航打击弹药族",
        "high_power_microwave": "高功率微波巡飞压制弹",
    }.get(family, str(direction.get("name", "")).strip())


def _hypothesis_to_direction(
    hypothesis: dict[str, Any],
    *,
    topic: str,
    priority: str,
) -> dict[str, Any]:
    equipment_forms = [
        str(item).strip()
        for item in hypothesis.get("equipment_forms", [])
        if str(item).strip()
    ]
    mechanism_chain = [
        str(item).strip()
        for item in hypothesis.get("mechanism_chain", [])[:4]
        if str(item).strip()
    ]
    direct_effects = [
        str(item).strip()
        for item in hypothesis.get("direct_military_effects", [])[:3]
        if str(item).strip()
    ]
    adaptations = [
        str(item).strip()
        for item in hypothesis.get("adversary_adaptations", [])[:4]
        if str(item).strip()
    ]
    boundaries = [
        str(item).strip()
        for item in hypothesis.get("failure_boundaries", [])[:4]
        if str(item).strip()
    ]
    validation = [
        str(item).strip()
        for item in hypothesis.get("validation_plan", [])[:4]
        if str(item).strip()
    ]
    project_function = str(hypothesis.get("project_function", "")).strip()
    equipment_form = equipment_forms[0] if equipment_forms else str(
        hypothesis.get("title", "")
    ).strip()
    problem_statement = str(
        hypothesis.get("changed_confrontation_variable", "")
    ).strip()
    if _direction_family(hypothesis) == "high_power_microwave":
        problem_statement = (
            "敌电子压制、低空防空和反无人传感节点在末段持续干扰与拦截无人远程弹药，"
            "现有动能压制手段难以同时制造可确认、可被后续火力利用的短时功能失效窗口"
        )
    direction = {
        "name": str(hypothesis.get("title", "")).strip(),
        "type": "new_capability",
        "priority": priority,
        "horizon": "mid",
        "feasibility": 2,
        "confidence": 0.68,
        "hypothesis_id": str(hypothesis.get("hypothesis_id", "")).strip(),
        "source_hypothesis_title": str(hypothesis.get("title", "")).strip(),
        "function": project_function,
        "project_function": project_function,
        "equipment_form": equipment_form,
        "equipment_forms": equipment_forms,
        "operational_mechanism": "→".join(mechanism_chain),
        "operational_process": mechanism_chain,
        "military_value": "；".join(direct_effects),
        "combat_effect_uplift": "；".join(direct_effects),
        "strike_chain_contribution": "→".join(mechanism_chain),
        "strike_countermeasure_value": "；".join(direct_effects),
        "capability_outcome": "；".join(direct_effects),
        "adversary_adaptation": "；".join(adaptations),
        "failure_boundary": "；".join(boundaries),
        "development_path": "；".join(validation),
        "validation_plan": validation,
        "verification": "；".join(validation),
        "baseline_system": str(hypothesis.get("nearest_public_baseline", "")).strip(),
        "capability_gap": problem_statement,
        "problem_statement": problem_statement,
        "query_relevance": (
            f"面向{topic}，{project_function}"
        ).strip("，"),
        "target_scenario": topic,
        "scientific_principle": str(
            hypothesis.get("changed_confrontation_variable", "")
        ).strip(),
        "winning_mechanism": str(hypothesis.get("novelty_delta", "")).strip(),
        "novelty": str(hypothesis.get("novelty_delta", "")).strip(),
        "foresight": "；".join(
            str(item).strip()
            for item in hypothesis.get("cross_scenario_results", [])[:3]
            if str(item).strip()
        ),
        "uncertainty_boundary": str(
            hypothesis.get("evidence_boundary", "")
        ).strip(),
        "direct_evidence_refs": [
            str(item).strip()
            for item in hypothesis.get("evidence_ids", [])
            if str(item).strip()
        ],
        "enabling_technologies": [
            *equipment_forms[:2],
            *[
                str(item).strip()
                for item in hypothesis.get("system_interfaces", [])[:3]
                if str(item).strip()
            ],
        ],
        "capability_portrait": "",
    }
    direction["name"] = _concrete_direction_name(direction)
    return direction


def _repair_dynamic_s6_portfolio(
    checkpoint: dict[str, Any],
    *,
    topic: str,
) -> dict[str, Any]:
    """Repair vague titles and replace repeated weapon families from the ledger."""

    repaired = dict(checkpoint)
    directions = [
        dict(item)
        for item in checkpoint.get("concept_directions", [])
        if isinstance(item, dict)
    ]
    used_families: set[str] = set()
    duplicate_positions: list[int] = []
    for position, direction in enumerate(directions):
        direction["name"] = _concrete_direction_name(direction)
        direction["capability_portrait"] = ""
        family = _direction_family(direction)
        if family and family in used_families:
            duplicate_positions.append(position)
        elif family:
            used_families.add(family)

    hypotheses = checkpoint.get("winning_swarm", {}).get("hypotheses", [])
    candidates = sorted(
        (item for item in hypotheses if isinstance(item, dict)),
        key=lambda item: float(item.get("score", 0.0) or 0.0),
        reverse=True,
    )
    for position in duplicate_positions:
        replacement = next(
            (
                item
                for item in candidates
                if _direction_family(item)
                and _direction_family(item) not in used_families
                and str(item.get("project_function", "")).strip()
                and item.get("equipment_forms")
            ),
            None,
        )
        if replacement is None:
            continue
        priority = str(directions[position].get("priority", f"P{position + 1}"))
        directions[position] = _hypothesis_to_direction(
            replacement,
            topic=topic,
            priority=priority,
        )
        used_families.add(_direction_family(replacement))
    repaired["concept_directions"] = directions
    return repaired


def _rebuild_from_s6_checkpoint(
    run_dir: Path,
    *,
    topic: str,
    route: str,
    repair_dynamic_portfolio: bool = False,
) -> list[dict[str, Any]]:
    """Reproject accepted S6 directions through the current portrait contracts."""

    sqlite_store = SqliteRunStore(run_dir / "run.db", run_id=run_dir.name)
    try:
        store = _restore_domain_store(sqlite_store.domain_objects())
    finally:
        sqlite_store.close()
    checkpoint = _latest_s6_checkpoint(run_dir)
    normalized = _normalize_s6_deterministic_format(checkpoint, topic=topic)
    warnings = _capability_direction_quality_issues(normalized)
    blocking = _s6_delivery_blocking_issues(warnings)
    if blocking and repair_dynamic_portfolio:
        checkpoint = _repair_dynamic_s6_portfolio(checkpoint, topic=topic)
        normalized = _normalize_s6_deterministic_format(checkpoint, topic=topic)
        warnings = _capability_direction_quality_issues(normalized)
        blocking = _s6_delivery_blocking_issues(warnings)
    if blocking:
        raise RuntimeError(
            "S6 checkpoint still has delivery-blocking issues: "
            + "；".join(blocking[:8])
        )
    normalized["s6_quality_gate_passed"] = True
    normalized["s6_quality_gate_failed"] = False
    normalized["s6_quality_warnings"] = warnings
    for direction in normalized.get("concept_directions", []):
        if isinstance(direction, dict):
            # The checkpoint may carry a portrait produced by an older family
            # classifier. Keep every accepted weapon field, but force the
            # current governed portrait contract to rebuild the prose.
            direction["capability_portrait"] = ""
    l3 = next(
        (stage for stage in store.stage_outputs.values() if stage.layer == "L3"),
        None,
    )
    if l3 is None:
        raise RuntimeError("completed run has no L3 capability-image stage")
    packets = store.baseline_packet_snapshot()
    evidence_ids = sorted(
        {evidence_id for packet in packets for evidence_id in packet.evidence_ids}
    )
    images = WinningMechanismEngine(risk_based_gates=True)._capability_images(
        topic=topic,
        route=route,
        l3=l3,
        evidence_ids=evidence_ids,
        coverage={},
        packets=packets,
        model_analysis=normalized,
    )
    if not 5 <= len(images) <= 7:
        raise RuntimeError(
            f"S6 checkpoint rebuilt {len(images)} capability images; expected 5 to 7"
        )
    return [to_plain(image) for image in images]


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
    from_s6_checkpoint: bool = False,
    repair_dynamic_portfolio: bool = False,
) -> dict[str, Any]:
    capability_path = run_dir / "capability_images.json"
    if not capability_path.exists():
        return {"changed": False, "directions": []}
    original = json.loads(capability_path.read_text(encoding="utf-8"))
    checkpoint_rows = (
        _rebuild_from_s6_checkpoint(
            run_dir,
            topic=topic,
            route=route,
            repair_dynamic_portfolio=repair_dynamic_portfolio,
        )
        if from_s6_checkpoint
        else []
    )
    original_by_id = {
        str(row.get("capability_id", "")): row
        for row in original
        if isinstance(row, dict)
    }
    rewritten: dict[str, dict[str, Any]] = {}
    replacements: list[tuple[str, str]] = []
    directions: list[dict[str, str]] = []
    output: list[dict[str, Any]] = []
    evidence_rows = _evidence_rows(run_dir / "domain.jsonl")
    source_rows = checkpoint_rows or original
    for source_row in source_rows:
        row = original_by_id.get(
            str(source_row.get("capability_id", "")),
            source_row,
        )
        if checkpoint_rows:
            updated = dict(source_row)
            if row.get("created_at"):
                updated["created_at"] = row["created_at"]
            if row.get("schema_version"):
                updated["schema_version"] = row["schema_version"]
        else:
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
    parser.add_argument(
        "--from-s6-checkpoint",
        action="store_true",
        help="从已通过组合门控的S6检查点重建能力卡，避免继承旧成品中的画像串线",
    )
    parser.add_argument(
        "--repair-dynamic-portfolio",
        action="store_true",
        help="修复S6中的枚举式标题和重复装备族，并从候选账本补入互异装备",
    )
    args = parser.parse_args()

    outputs = ROOT / "outputs"
    selected = set(args.run_id)
    scanned = changed_runs = changed_directions = 0
    completed = _completed_runs(outputs / "application.db")
    completed_ids = {run_id for run_id, _, _ in completed}
    if selected:
        for run_id in sorted(selected - completed_ids):
            run_dir = outputs / "runs" / run_id
            if not run_dir.exists():
                continue
            topic, route = _run_context(run_dir)
            completed.append((run_id, topic, route))
    for run_id, topic, route in completed:
        if selected and run_id not in selected:
            continue
        scanned += 1
        result = upgrade_run(
            outputs / "runs" / run_id,
            topic=topic,
            route=route,
            apply=args.apply,
            evidence_anchors=args.evidence_anchors,
            from_s6_checkpoint=args.from_s6_checkpoint,
            repair_dynamic_portfolio=args.repair_dynamic_portfolio,
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
