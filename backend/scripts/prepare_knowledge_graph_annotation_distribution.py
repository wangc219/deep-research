"""从 300 篇选择清单生成无预标注答案的双标分发包。"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from platform_core.knowledge.graphs.defense_ontology import ontology_payload
from platform_core.knowledge.training.pilot_campaign import load_pilot_selection_manifest

PACKAGE_VERSION = "defense-kg-annotation-distribution-v1"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--document-mode", choices=("hardlink", "copy", "reference"), default="hardlink")
    parser.add_argument("--annotator-a", default="ANNOTATOR_A_PENDING")
    parser.add_argument("--annotator-b", default="ANNOTATOR_B_PENDING")
    parser.add_argument("--arbitrator", default="ARBITRATOR_PENDING")
    args = parser.parse_args()
    build_distribution(
        manifest_path=Path(args.manifest),
        output_root=Path(args.output),
        document_mode=args.document_mode,
        roles={"annotator_a": args.annotator_a, "annotator_b": args.annotator_b, "arbitrator": args.arbitrator},
    )


def build_distribution(
    *,
    manifest_path: Path,
    output_root: Path,
    document_mode: str,
    roles: dict[str, str],
) -> dict[str, Any]:
    """生成共享论文、两份独立任务表、仲裁模板和校验清单。"""
    manifest_path = manifest_path.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError(f"输出目录必须为空: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    documents_dir = output_root / "shared_documents"
    private_dir = output_root / "private_tasks"
    templates_dir = output_root / "templates"
    reference_dir = output_root / "reference"
    for path in (documents_dir, private_dir, templates_dir, reference_dir):
        path.mkdir()

    manifest = load_pilot_selection_manifest(manifest_path)
    source_rows = _load_source_rows(manifest_path.parent / "gold-selection-manifest.jsonl")
    source_by_id = {str(item["document_id"]): item for item in source_rows}
    tasks_a = []
    tasks_b = []
    adjudication = []
    document_checksums = []
    for index, entry in enumerate(manifest.entries, start=1):
        source = source_by_id.get(entry.document_id)
        if source is None or not source.get("path"):
            raise ValueError(f"选择项缺少本地论文路径: {entry.document_id}")
        source_path = Path(str(source["path"])).expanduser().resolve()
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        safe_name = f"{index:03d}_{entry.document_id}.pdf"
        target_path = documents_dir / safe_name
        _materialize_document(source_path, target_path, document_mode)
        relative_document = target_path.relative_to(output_root).as_posix()
        document_checksums.append(
            {
                "document_id": entry.document_id,
                "relative_path": relative_document,
                "sha256": entry.content_sha256,
                "bytes": source_path.stat().st_size,
            }
        )
        common = {
            "sequence": index,
            "document_id": entry.document_id,
            "split": entry.split,
            "source_type": entry.source_type,
            "language": entry.language,
            "domain": entry.domain,
            "document_path": relative_document,
            "document_sha256": entry.content_sha256,
            "guideline_version": "defense-kg-annotation-v1",
            "ontology_version": "defense-kg-1.0",
            "status": "unassigned" if "PENDING" in roles["annotator_a"] else "pending",
        }
        task_a = {
            **common,
            "assignment_id": _stable_id(entry.document_id, "A"),
            "annotator_role": "A",
            "annotator_account": roles["annotator_a"],
        }
        task_b = {
            **common,
            "assignment_id": _stable_id(entry.document_id, "B"),
            "annotator_role": "B",
            "annotator_account": roles["annotator_b"],
        }
        tasks_a.append(task_a)
        tasks_b.append(task_b)
        adjudication.append(
            {
                "sequence": index,
                "document_id": entry.document_id,
                "split": entry.split,
                "annotator_a_assignment_id": task_a["assignment_id"],
                "annotator_b_assignment_id": task_b["assignment_id"],
                "arbitrator_account": roles["arbitrator"],
                "difference_report_path": "",
                "decision_status": "pending",
                "decision_summary": "",
                "adjudicated_gold_path": "",
            }
        )

    _write_csv(private_dir / "annotator_A_tasks.csv", tasks_a)
    _write_csv(private_dir / "annotator_B_tasks.csv", tasks_b)
    _write_csv(private_dir / "expert_adjudication_tasks.csv", adjudication)
    _write_jsonl(templates_dir / "annotator_A_empty_submissions.jsonl", [_empty_submission(item) for item in tasks_a])
    _write_jsonl(templates_dir / "annotator_B_empty_submissions.jsonl", [_empty_submission(item) for item in tasks_b])
    _write_jsonl(
        templates_dir / "expert_empty_adjudications.jsonl",
        [_empty_adjudication(item) for item in adjudication],
    )
    _write_json(reference_dir / "ontology-defense-kg-1.0.json", ontology_payload())
    _write_ontology_csv(reference_dir / "entity_types.csv", ontology_payload()["entity_types"])
    _write_ontology_csv(reference_dir / "relation_types.csv", ontology_payload()["relation_types"])
    (reference_dir / "annotation-guideline.md").write_text(_guideline(), encoding="utf-8")
    (output_root / "README.md").write_text(_readme(document_mode, roles), encoding="utf-8")
    _write_jsonl(output_root / "document-checksums.jsonl", document_checksums)

    report = {
        "package_version": PACKAGE_VERSION,
        "manifest_sha256": manifest.manifest_sha256,
        "document_count": len(manifest.entries),
        "split_counts": {"train": 210, "dev": 30, "test": 60},
        "source_type_counts": {"paper": 300, "patent": 0},
        "preannotations_included": False,
        "sealed_test_answers_included": False,
        "roles": roles,
        "document_mode": document_mode,
        "coverage_deviations": [
            "本次 Pilot 按用户批准仅验收中文，300 篇选择文档均为中文。",
            "本次 Pilot 按用户批准使用 999 篇全论文、0 件专利；不代表原始中英论文及专利覆盖要求已满足。",
        ],
    }
    _write_json(output_root / "package-report.json", report)
    package_files = _package_checksums(output_root)
    _write_jsonl(output_root / "package-checksums.jsonl", package_files)
    return report


def _load_source_rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _materialize_document(source: Path, target: Path, mode: str) -> None:
    if mode == "reference":
        return
    if mode == "copy":
        shutil.copy2(source, target)
        return
    try:
        os.link(source, target)
    except OSError:
        shutil.copy2(source, target)


def _empty_submission(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": "defense-kg-gold-v1",
        "assignment_id": task["assignment_id"],
        "document_id": task["document_id"],
        "split": task["split"],
        "language": task["language"],
        "source_type": task["source_type"],
        "domain": task["domain"],
        "source_version": task["document_sha256"],
        "annotation": {
            "annotator_ids": [task["annotator_account"]],
            "arbitrator_id": None,
            "adjudicated": False,
            "guideline_version": task["guideline_version"],
            "completed_at": None,
        },
        "blocks": [],
        "entities": [],
        "relations": [],
        "annotation_notes": "",
    }


def _empty_adjudication(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": "defense-kg-adjudication-template-v1",
        **task,
        "entity_decisions": [],
        "relation_decisions": [],
        "global_notes": "",
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_ontology_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    flattened = []
    for row in rows:
        flattened.append(
            {
                key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value
                for key, value in row.items()
            }
        )
    _write_csv(path, flattened)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _package_checksums(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name != "package-checksums.jsonl"):
        rows.append(
            {
                "relative_path": path.relative_to(root).as_posix(),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    return rows


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_id(document_id: str, role: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"defense-kg-annotation|{document_id}|{role}").hex


def _guideline() -> str:
    return """# 军事武器装备知识图谱双标规范 v1

## 独立性

- 标注员 A、B 独立作业，不查看对方任务表、提交结果或差异报告。
- 不使用模型预标答案；密封测试集不得用于提示词、规则、阈值或模型调参。
- 专家只在 A、B 均提交后查看差异并仲裁。

## 实体

- 按 `entity_types.csv` 选择类型，Span 必须逐字对应原文，采用 0-based、exclusive-end。
- 长实体取能唯一表达概念的最小完整短语；型号、版本、数值和单位不得随意截断。
- 同一处文本只在确有嵌套语义时标多个实体；不以关系需要为由虚构实体。
- `canonical_entity_id` 无法确认时留空，不猜测；别名、中英文映射交由对齐环节复核。

## 关系与证据

- 按 `relation_types.csv` 校验起止实体类型、方向和是否允许自环。
- Fact 必须有直接原文 Span；Inference 必须记录推导依据；Hypothesis 不计入正式事实规模。
- 证据 Span 应覆盖关系成立所需的最小完整语句，可跨 Block 保存多个 Span。
- 适用条件（环境、参数、材料、平台、试验条件）单独记录，不塞入关系类型。

## 提交与仲裁

- 每篇完成后校验所有实体及证据都能原文回切，关系端点均存在。
- A、B 差异包括 Span、类型、方向、claim level、证据和适用条件。
- 仲裁必须说明采用 A、采用 B 或重新裁定的理由，并形成最终 GoldDocument。
"""


def _readme(document_mode: str, roles: dict[str, str]) -> str:
    return f"""# 300 篇双人独立标注分发包

- 语料：300 篇论文，train/dev/test = 210/30/60。
- 文档交付方式：`{document_mode}`；`shared_documents/` 是唯一共享论文目录。
- A 任务：`private_tasks/annotator_A_tasks.csv`，账号 `{roles["annotator_a"]}`。
- B 任务：`private_tasks/annotator_B_tasks.csv`，账号 `{roles["annotator_b"]}`。
- 专家任务：`private_tasks/expert_adjudication_tasks.csv`，账号 `{roles["arbitrator"]}`。
- 空白提交模板位于 `templates/`；其中没有模型预标、标准答案或密封测试答案。
- 本体与标注规范位于 `reference/`；分发前请核对 `package-checksums.jsonl`。

当前账号均可为占位值。提供平台知识库 ID、标注员 A/B UID 和独立仲裁专家 UID 后，
再运行平台 campaign 预检、绑定权威文档版本并创建线上标注任务。
"""


if __name__ == "__main__":
    main()
