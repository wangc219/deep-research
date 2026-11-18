#!/usr/bin/env python3
"""校验 Pilot 清单并幂等回填论文来源元数据与权威来源版本。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select


APP_ROOT = Path(__file__).resolve().parents[1]
for import_path in (APP_ROOT, APP_ROOT / "package"):
    value = str(import_path)
    if value not in sys.path:
        sys.path.insert(0, value)


class SourceMetadataError(RuntimeError):
    """Pilot 来源清单、导入映射或数据库状态不一致。"""


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    """读取非空 JSONL，并拒绝空清单。"""

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise SourceMetadataError(f"清单为空: {path}")
    return rows


def build_source_metadata(
    manifest_rows: list[dict[str, Any]],
    checkpoint_rows: list[dict[str, Any]],
    *,
    expected_count: int,
) -> dict[str, dict[str, Any]]:
    """以内容哈希闭合集合，将清单来源语义绑定到实际 file_id。"""

    manifest_by_hash = _unique_by(manifest_rows, "content_sha256", "来源清单")
    completed_rows = [
        row for row in checkpoint_rows if str(row.get("status") or "") in {"added", "already_present"}
    ]
    checkpoint_by_hash = _unique_by(completed_rows, "content_sha256", "导入检查点")
    if len(manifest_by_hash) != expected_count:
        raise SourceMetadataError(f"来源清单应为 {expected_count} 篇，实际 {len(manifest_by_hash)} 篇")
    if set(manifest_by_hash) != set(checkpoint_by_hash):
        missing = sorted(set(manifest_by_hash) - set(checkpoint_by_hash))
        unexpected = sorted(set(checkpoint_by_hash) - set(manifest_by_hash))
        raise SourceMetadataError(f"导入检查点与来源清单不闭合，缺失 {missing[:3]}，多出 {unexpected[:3]}")

    result: dict[str, dict[str, Any]] = {}
    for content_hash, manifest in manifest_by_hash.items():
        checkpoint = checkpoint_by_hash[content_hash]
        file_id = str(checkpoint.get("file_id") or "").strip()
        if not file_id:
            raise SourceMetadataError(f"导入检查点缺少 file_id: {content_hash}")
        if file_id in result:
            raise SourceMetadataError(f"导入检查点重复绑定 file_id: {file_id}")
        if str(checkpoint.get("document_id") or "") != str(manifest.get("document_id") or ""):
            raise SourceMetadataError(f"manifest document_id 与检查点不一致: {content_hash}")
        if str(checkpoint.get("filename") or "") != str(manifest.get("filename") or ""):
            raise SourceMetadataError(f"manifest filename 与检查点不一致: {content_hash}")

        source_type = str(manifest.get("source_type") or "paper").strip().lower()
        language = str(manifest.get("language") or "zh").strip().lower()
        acceptance_languages = [str(item).strip().lower() for item in manifest.get("acceptance_languages") or ["zh"]]
        if source_type != "paper":
            raise SourceMetadataError(f"当前中文论文 Pilot 禁止非论文来源: {content_hash}={source_type}")
        if language != "zh" or acceptance_languages != ["zh"]:
            raise SourceMetadataError(f"当前 Pilot 只验收中文: {content_hash}={language}/{acceptance_languages}")
        result[file_id] = {
            "source_type": source_type,
            "language": language,
            "domain": str(manifest.get("domain") or ""),
            "source_manifest_document_id": str(manifest["document_id"]),
            "source_manifest_version": str(manifest.get("manifest_version") or ""),
            "acceptance_languages": acceptance_languages,
            "source_content_sha256": content_hash,
        }
    return result


def _unique_by(rows: list[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    """建立唯一索引，缺失或重复键均显式失败。"""

    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = str(row.get(key) or "").strip()
        if not value:
            raise SourceMetadataError(f"{label}存在缺失 {key} 的记录")
        if value in indexed:
            raise SourceMetadataError(f"{label}存在重复 {key}: {value}")
        indexed[value] = row
    return indexed


async def backfill(args: argparse.Namespace) -> dict[str, Any]:
    """在一个 PostgreSQL 事务中合并元数据并登记不可变来源版本。"""

    from platform_core.repositories.knowledge_graph_source_repository import KnowledgeGraphSourceRepository
    from platform_core.storage.postgres.manager import pg_manager
    from platform_core.storage.postgres.models_knowledge import KnowledgeFile
    from platform_core.utils.datetime_utils import utc_now

    metadata_by_file_id = build_source_metadata(
        _load_jsonl(args.manifest.expanduser().resolve()),
        _load_jsonl(args.checkpoint.expanduser().resolve()),
        expected_count=args.expected_count,
    )
    file_ids = sorted(metadata_by_file_id)
    pg_manager.initialize()
    async with pg_manager.get_async_session_context() as session:
        records = list(
            (
                await session.scalars(
                    select(KnowledgeFile)
                    .where(KnowledgeFile.kb_id == args.kb_id, KnowledgeFile.file_id.in_(file_ids))
                    .order_by(KnowledgeFile.file_id)
                )
            ).all()
        )
        if len(records) != args.expected_count:
            raise SourceMetadataError(f"知识库应匹配 {args.expected_count} 篇，实际 {len(records)} 篇")
        for record in records:
            metadata = metadata_by_file_id[record.file_id]
            expected_hash = metadata["source_content_sha256"]
            if str(record.content_hash or "") != expected_hash:
                raise SourceMetadataError(f"数据库内容哈希不一致: {record.file_id}")
            if args.apply:
                record.processing_params = {**dict(record.processing_params or {}), **metadata}
                record.updated_at = utc_now()

        registered: list[dict[str, Any]] = []
        if args.apply:
            registered = await KnowledgeGraphSourceRepository().register_in_session(
                session,
                kb_id=args.kb_id,
                file_ids=file_ids,
                metadata_by_file_id=metadata_by_file_id,
            )
            if len(registered) != args.expected_count:
                raise SourceMetadataError(f"权威来源版本应登记 {args.expected_count} 篇，实际 {len(registered)} 篇")

    return {
        "contract_version": "defense-kg-pilot-source-metadata-backfill-v1",
        "mode": "apply" if args.apply else "dry_run",
        "kb_id": args.kb_id,
        "validated_files": len(file_ids),
        "registered_sources": len(registered),
        "source_type": "paper",
        "language": "zh",
        "cloud_authorized": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kb-id", required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--expected-count", type=int, default=999)
    parser.add_argument("--apply", action="store_true", help="通过全部闭集校验后写入；默认只读预检。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = asyncio.run(backfill(args))
    except Exception as exc:
        print(f"Pilot 来源元数据回填失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
