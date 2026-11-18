"""生成并回收 Pilot 语料领域标注任务。"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .pilot_manifest import build_pilot_inventory_report

DOMAIN_ANNOTATION_VERSION = "defense-kg-pilot-domain-v2"
PILOT_DOMAIN_CATALOG = (
    {
        "code": "radar_sensing_electronic_warfare",
        "name_zh": "雷达、感知与电子对抗",
        "description": "雷达、光电/声学感知、目标识别、电子侦察、干扰与抗干扰。",
    },
    {
        "code": "communications_networks_command_information",
        "name_zh": "通信、网络与指挥信息",
        "description": "通信链路、网络体系、信息安全、指挥控制与任务信息系统。",
    },
    {
        "code": "autonomous_systems_ai_control",
        "name_zh": "自主系统、人工智能与控制",
        "description": "无人/自主系统、智能决策、机器学习、制导导航与控制。",
    },
    {
        "code": "materials_devices_advanced_manufacturing",
        "name_zh": "材料、器件与先进制造",
        "description": "功能/结构材料、电子器件、传感器、制造工艺与增材制造。",
    },
    {
        "code": "energy_power_propulsion",
        "name_zh": "能源、动力与推进",
        "description": "能源供给、动力系统、发动机、推进剂与推进技术。",
    },
    {
        "code": "protection_survivability_support_reliability",
        "name_zh": "防护、生存性、保障与可靠性",
        "description": "防护隐身、生存性、维修保障、可靠性、安全与工程约束。",
    },
)
_DOMAIN_CODES = {item["code"] for item in PILOT_DOMAIN_CATALOG}
_CONFIDENCE_LEVELS = {"low", "medium", "high"}
_PREFLIGHT_SUCCESS_STATUSES = {"success", "succeeded"}
_ANNOTATION_KINDS = {"human", "ai_prelabel"}
_AI_PROVENANCE_MARKERS = ("AI领域初筛", "AI 领域初筛", "seed=")


def build_domain_annotation_package(
    *,
    manifest_path: Path,
    output_root: Path,
    batch_count: int = 6,
    annotator_accounts: Iterable[str] = (),
    parser_preflight_path: Path | None = None,
    prior_task_paths: Iterable[Path] = (),
) -> dict[str, Any]:
    """把来源清单确定性拆成可直接分发的领域标注任务。"""
    if batch_count < 1 or batch_count > 100:
        raise ValueError("batch_count 必须在 1 到 100 之间")
    manifest_path = manifest_path.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError(f"输出目录必须为空: {output_root}")

    rows = _load_jsonl(manifest_path)
    _validate_source_manifest(rows)
    preflight_by_id = _load_parser_preflight(parser_preflight_path, rows)
    inherited_by_hash, stale_completed_count = _load_completed_annotations_by_hash(prior_task_paths, rows)
    accounts = [str(item).strip() for item in annotator_accounts if str(item).strip()]
    output_root.mkdir(parents=True, exist_ok=True)
    batches_root = output_root / "batches"
    reference_root = output_root / "reference"
    batches_root.mkdir()
    reference_root.mkdir()

    tasks = []
    batch_rows: list[list[dict[str, Any]]] = [[] for _ in range(batch_count)]
    for sequence, source in enumerate(rows, start=1):
        batch_index = (sequence - 1) % batch_count
        account = (
            accounts[batch_index % len(accounts)] if accounts else f"DOMAIN_ANNOTATOR_{batch_index + 1:02d}_PENDING"
        )
        preflight = preflight_by_id.get(str(source["document_id"]))
        source_held = bool(preflight and str(preflight.get("status") or "").lower() not in _PREFLIGHT_SUCCESS_STATUSES)
        hold_reason = str((preflight or {}).get("error_code") or "parser_preflight_failed")
        inherited = inherited_by_hash.get(str(source["content_sha256"])) if not source_held else None
        task = {
            "sequence": sequence,
            "batch_id": f"domain-{batch_index + 1:02d}",
            "document_id": source["document_id"],
            "content_sha256": source["content_sha256"],
            "title": source["title"],
            "filename": source["filename"],
            "document_path": (Path("papers") / str(source.get("relative_path") or source["filename"])).as_posix(),
            "source_type": source["source_type"],
            "language": source["language"],
            "primary_domain_code": inherited["primary_domain_code"] if inherited else "",
            "secondary_domain_codes": ";".join(inherited["secondary_domain_codes"]) if inherited else "",
            "confidence": inherited["confidence"] if inherited else "",
            "annotator_account": inherited["annotator_account"] if inherited else account,
            "status": (
                "source_hold"
                if source_held
                else "completed"
                if inherited
                else ("unassigned" if "PENDING" in account else "pending")
            ),
            "notes": (
                f"来源解析预检未通过（{hold_reason}），不得分发；待内容完整替换件重建清单后再标注。"
                if source_held
                else inherited["notes"]
                if inherited
                else ""
            ),
        }
        tasks.append(task)
        batch_rows[batch_index].append(task)

    _write_csv(output_root / "all-domain-tasks.csv", tasks)
    for index, items in enumerate(batch_rows, start=1):
        _write_csv(batches_root / f"domain-batch-{index:02d}.csv", items)
    _write_csv(reference_root / "domain-catalog.csv", list(PILOT_DOMAIN_CATALOG))
    _write_json(reference_root / "domain-catalog.json", list(PILOT_DOMAIN_CATALOG))
    (output_root / "README.md").write_text(
        _annotation_readme(
            manifest_name=manifest_path.name,
            document_count=len(rows),
            batch_count=batch_count,
            accounts=accounts,
            parser_preflight_name=parser_preflight_path.name if parser_preflight_path else None,
            source_hold_count=sum(item["status"] == "source_hold" for item in tasks),
            package_directory=output_root.name,
            inherited_completed_count=sum(item["status"] == "completed" for item in tasks),
        ),
        encoding="utf-8",
    )
    report = {
        "package_version": DOMAIN_ANNOTATION_VERSION,
        "source_manifest": manifest_path.name,
        "source_manifest_sha256": _sha256_file(manifest_path),
        "document_count": len(rows),
        "batch_count": batch_count,
        "batch_sizes": {f"domain-{index + 1:02d}": len(items) for index, items in enumerate(batch_rows)},
        "annotator_accounts": accounts or [f"DOMAIN_ANNOTATOR_{index + 1:02d}_PENDING" for index in range(batch_count)],
        "preannotations_included": False,
        "required_completion_status": "completed",
        "parser_preflight_verified": parser_preflight_path is not None,
        "source_hold_count": sum(item["status"] == "source_hold" for item in tasks),
        "source_hold_document_ids": [item["document_id"] for item in tasks if item["status"] == "source_hold"],
        "source_distribution_ready": all(item["status"] != "source_hold" for item in tasks),
        "inherited_completed_count": sum(item["status"] == "completed" for item in tasks),
        "stale_completed_count": stale_completed_count,
    }
    _write_json(output_root / "package-report.json", report)
    _write_jsonl(output_root / "package-checksums.jsonl", _package_checksums(output_root))
    return report


def apply_domain_annotations(
    *,
    manifest_path: Path,
    task_paths: Iterable[Path],
    output_manifest_path: Path,
    output_report_path: Path,
    require_complete: bool = True,
    annotation_kind: str = "human",
) -> dict[str, Any]:
    """校验回收结果并生成带来源类型的领域清单，绝不覆盖原清单。"""
    annotation_kind = str(annotation_kind).strip().lower()
    if annotation_kind not in _ANNOTATION_KINDS:
        raise ValueError(f"领域标注来源类型非法: {annotation_kind!r}")
    manifest_path = manifest_path.expanduser().resolve()
    sources = _load_jsonl(manifest_path)
    _validate_source_manifest(sources)
    source_by_id = {str(item["document_id"]): item for item in sources}

    annotations: dict[str, dict[str, Any]] = {}
    for task_path in task_paths:
        with task_path.expanduser().resolve().open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                document_id = str(row.get("document_id") or "").strip()
                if not document_id:
                    raise ValueError(f"任务行缺少 document_id: {task_path}")
                if document_id in annotations:
                    raise ValueError(f"同一文档存在重复领域标注: {document_id}")
                annotation = _validate_annotation(row, source_by_id.get(document_id))
                if annotation_kind == "human" and _looks_like_ai_prelabel(annotation["notes"]):
                    raise ValueError(f"AI 预标不得作为真人领域标注回收: {document_id}")
                annotations[document_id] = annotation

    unknown = sorted(set(annotations) - set(source_by_id))
    if unknown:
        raise ValueError(f"标注结果包含未知文档: {unknown[:5]}")
    missing = sorted(set(source_by_id) - set(annotations))
    if require_complete and missing:
        raise ValueError(f"仍有 {len(missing)} 篇文档未完成领域标注: {missing[:5]}")

    annotated_manifest = []
    for source in sources:
        annotation = annotations.get(str(source["document_id"]))
        item = dict(source)
        if annotation:
            item["domain"] = annotation["primary_domain_code"]
            item["domain_labels"] = [
                annotation["primary_domain_code"],
                *annotation["secondary_domain_codes"],
            ]
            item["domain_annotation"] = {
                "version": DOMAIN_ANNOTATION_VERSION,
                "kind": annotation_kind,
                "annotator_account": annotation["annotator_account"],
                "confidence": annotation["confidence"],
                "notes": annotation["notes"],
            }
        annotated_manifest.append(item)

    inventory = build_pilot_inventory_report(annotated_manifest)
    report = {
        "annotation_version": DOMAIN_ANNOTATION_VERSION,
        "annotation_kind": annotation_kind,
        "formal_gold_eligible": annotation_kind == "human",
        "source_manifest_sha256": _sha256_file(manifest_path),
        "source_documents": len(sources),
        "completed_documents": len(annotations),
        "missing_documents": len(missing),
        "primary_domain_counts": dict(
            sorted(Counter(item["primary_domain_code"] for item in annotations.values()).items())
        ),
        "inventory": inventory,
    }
    output_manifest_path = output_manifest_path.expanduser().resolve()
    output_report_path = output_report_path.expanduser().resolve()
    output_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    output_report_path.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(output_manifest_path, annotated_manifest)
    _write_json(output_report_path, report)
    return report


def _looks_like_ai_prelabel(notes: str) -> bool:
    """识别当前平台生成的显式 AI 预标谱系标记。"""
    normalized = str(notes or "")
    return any(marker in normalized for marker in _AI_PROVENANCE_MARKERS)


def _validate_annotation(row: dict[str, Any], source: dict[str, Any] | None) -> dict[str, Any]:
    document_id = str(row.get("document_id") or "").strip()
    if source is None:
        return {
            "primary_domain_code": "",
            "secondary_domain_codes": [],
            "confidence": "",
            "annotator_account": "",
            "notes": "",
        }
    if str(row.get("content_sha256") or "").strip() != source["content_sha256"]:
        raise ValueError(f"文档内容 SHA-256 不匹配: {document_id}")
    if str(row.get("status") or "").strip().lower() != "completed":
        raise ValueError(f"文档领域标注尚未完成: {document_id}")
    primary = str(row.get("primary_domain_code") or "").strip()
    if primary not in _DOMAIN_CODES:
        raise ValueError(f"文档主领域不在六领域目录中: {document_id}={primary!r}")
    secondary = [item.strip() for item in str(row.get("secondary_domain_codes") or "").split(";") if item.strip()]
    invalid_secondary = sorted(set(secondary) - _DOMAIN_CODES)
    if invalid_secondary:
        raise ValueError(f"文档次领域编码非法: {document_id}={invalid_secondary}")
    if primary in secondary:
        raise ValueError(f"主领域不得重复出现在次领域: {document_id}")
    confidence = str(row.get("confidence") or "").strip().lower()
    if confidence not in _CONFIDENCE_LEVELS:
        raise ValueError(f"文档领域置信度必须是 low/medium/high: {document_id}")
    annotator = str(row.get("annotator_account") or "").strip()
    if not annotator or "PENDING" in annotator:
        raise ValueError(f"文档领域标注缺少真实人员账号: {document_id}")
    return {
        "primary_domain_code": primary,
        "secondary_domain_codes": list(dict.fromkeys(secondary)),
        "confidence": confidence,
        "annotator_account": annotator,
        "notes": str(row.get("notes") or "").strip(),
    }


def _validate_source_manifest(rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError("Pilot 来源清单为空")
    required = {"document_id", "content_sha256", "title", "filename", "path", "source_type", "language"}
    seen_ids = set()
    seen_hashes = set()
    for index, row in enumerate(rows, start=1):
        missing = sorted(key for key in required if not row.get(key))
        if missing:
            raise ValueError(f"来源清单第 {index} 行缺少字段: {missing}")
        if row["document_id"] in seen_ids or row["content_sha256"] in seen_hashes:
            raise ValueError(f"来源清单存在重复文档或内容: {row['document_id']}")
        seen_ids.add(row["document_id"])
        seen_hashes.add(row["content_sha256"])


def _load_completed_annotations_by_hash(
    task_paths: Iterable[Path],
    sources: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], int]:
    """按不变内容哈希迁移已完成人工结果，避免来源替换造成重复标注。"""
    source_by_hash = {str(item["content_sha256"]): item for item in sources}
    inherited: dict[str, dict[str, Any]] = {}
    stale_completed_count = 0
    seen_hashes = set()
    for task_path in task_paths:
        resolved = task_path.expanduser().resolve()
        with resolved.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                content_hash = str(row.get("content_sha256") or "").strip()
                if not content_hash:
                    raise ValueError(f"复用任务行缺少 content_sha256: {resolved}")
                if content_hash in seen_hashes:
                    raise ValueError(f"复用任务存在重复内容 SHA-256: {content_hash}")
                seen_hashes.add(content_hash)
                if str(row.get("status") or "").strip().lower() != "completed":
                    continue
                source = source_by_hash.get(content_hash)
                if source is None:
                    stale_completed_count += 1
                    continue
                inherited[content_hash] = _validate_annotation(row, source)
    return inherited, stale_completed_count


def _annotation_readme(
    *,
    manifest_name: str,
    document_count: int,
    batch_count: int,
    accounts: list[str],
    parser_preflight_name: str | None,
    source_hold_count: int,
    package_directory: str,
    inherited_completed_count: int,
) -> str:
    account_note = (
        "、".join(dict.fromkeys(accounts)) if accounts else "尚未提供，任务表中保留 DOMAIN_ANNOTATOR_*_PENDING"
    )
    if parser_preflight_name:
        preflight_note = f"`{parser_preflight_name}`，待替换来源 {source_hold_count} 篇"
    else:
        preflight_note = "未提供；本包不能单独证明每篇来源均可解析"
    return f"""# 999 篇 Pilot 论文六领域人工标注包

本包只要求标注文档所属领域，不包含实体/关系预标答案，也不改变原始论文和来源清单。

- 来源清单：`{manifest_name}`（仅记录文件名，不在分发包中暴露本机绝对路径）
- 文档数：{document_count}
- 分发批次：{batch_count}
- 当前账号：{account_note}
- 解析预检：{preflight_note}
- 按内容 SHA-256 继承的已完成标注：{inherited_completed_count} 篇

## 标注字段

1. `primary_domain_code`：必须从 `reference/domain-catalog.csv` 的六个编码中选择一个。
2. `secondary_domain_codes`：可空；多项用英文分号 `;` 分隔，不得重复主领域。
3. `confidence`：填写 `high`、`medium` 或 `low`。
4. `annotator_account`：填写平台真实账号或 UID，不能保留 `PENDING`。
5. `status`：完成后填写 `completed`。
6. `notes`：低置信度、跨领域或争议文档必须说明原因。

## 分发与回收

- `batches/` 下每份 CSV 是一个独立批次；按 `filename` 从项目 `papers/` 目录分发对应 PDF。
- `status=source_hold` 的任务禁止分发或标注；必须取得内容完整替换件并重建来源清单和任务包。
- 不要改动 `document_id`、`content_sha256`、`filename` 等身份字段。
- 回收后用 `prepare_knowledge_graph_pilot_domain_annotation.py apply` 校验并生成新 manifest。
- 工具会拒绝缺失、重复、SHA-256 不匹配、非法领域、未完成状态和占位账号。
- 替换损坏来源后，可在 `prepare` 时重复传入 `--reuse-tasks`，仅继承内容 SHA-256 未变化且状态为
  `completed` 的人工结果；新文件和内容变化文件保持待标注，避免 998 篇重复劳动。
- 本包按来源清单内的显式验收语种执行；当前 Pilot 为中文验收，不能外推为英文能力已验证。

在 `backend/` 目录回收六批 CSV 的示例：

```bash
uv run python scripts/prepare_knowledge_graph_pilot_domain_annotation.py apply \\
  --manifest <Pilot来源清单路径> \\
  --tasks ../artifacts/{package_directory}/batches/domain-batch-01.csv \\
  --tasks ../artifacts/{package_directory}/batches/domain-batch-02.csv \\
  --tasks ../artifacts/{package_directory}/batches/domain-batch-03.csv \\
  --tasks ../artifacts/{package_directory}/batches/domain-batch-04.csv \\
  --tasks ../artifacts/{package_directory}/batches/domain-batch-05.csv \\
  --tasks ../artifacts/{package_directory}/batches/domain-batch-06.csv \\
  --output-manifest <回收输出目录>/pilot-source-manifest-domain-reviewed.jsonl \\
  --output-report <回收输出目录>/domain-annotation-report.json
```

领域回填通过后，应基于新 manifest 重新执行分层抽样并重建正式 300 篇双标包；当前 domain 为空的
300 篇包只能作为分发结构演练，不能直接创建正式 campaign。
"""


def _load_parser_preflight(
    parser_preflight_path: Path | None,
    sources: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if parser_preflight_path is None:
        return {}
    rows = _load_jsonl(parser_preflight_path.expanduser().resolve())
    source_by_id = {str(item["document_id"]): item for item in sources}
    preflight_by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        document_id = str(row.get("document_id") or "").strip()
        if not document_id or document_id in preflight_by_id:
            raise ValueError(f"解析预检存在空或重复 document_id: {document_id!r}")
        source = source_by_id.get(document_id)
        if source is None:
            raise ValueError(f"解析预检包含来源清单外文档: {document_id}")
        if str(row.get("content_sha256") or "").strip() != str(source["content_sha256"]):
            raise ValueError(f"解析预检与来源清单 SHA-256 不匹配: {document_id}")
        if str(row.get("status") or "").lower() not in {*_PREFLIGHT_SUCCESS_STATUSES, "failed"}:
            raise ValueError(f"解析预检状态非法: {document_id}")
        preflight_by_id[document_id] = row
    missing = sorted(set(source_by_id) - set(preflight_by_id))
    if missing:
        raise ValueError(f"解析预检缺少 {len(missing)} 篇来源: {missing[:5]}")
    return preflight_by_id


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"不能写入空 CSV: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _package_checksums(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "relative_path": path.relative_to(root).as_posix(),
            "sha256": _sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "package-checksums.jsonl"
    ]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
