"""只读审计 Pilot 全量解析文本，输出不含正文的质量报告。"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

from platform_core.knowledge.training.parsed_text_quality import analyze_parsed_text
from platform_core.knowledge.utils.kb_utils import parse_minio_url
from platform_core.repositories.knowledge_file_repository import KnowledgeFileRepository
from platform_core.storage.minio import get_minio_client


async def audit(kb_id: str, *, expected_file_count: int) -> dict:
    """下载权威 Markdown 并生成不含原文的逐篇审计结果。"""
    records = [
        record for record in await KnowledgeFileRepository().list_by_kb_id(kb_id) if record.is_folder is not True
    ]
    if len(records) != expected_file_count:
        raise ValueError(f"知识库文件数不符: expected={expected_file_count}, actual={len(records)}")

    storage = get_minio_client()
    documents = []
    for record in sorted(records, key=lambda item: item.file_id):
        if not record.markdown_file:
            metrics = {
                "contract_version": "parsed-text-quality-v1",
                "issues": ["markdown_missing"],
                "ready_for_extraction": False,
                "recommended_route": "reparse",
            }
        else:
            bucket_name, object_name = parse_minio_url(record.markdown_file)
            source_text = (await storage.adownload_file(bucket_name, object_name)).decode("utf-8")
            metrics = analyze_parsed_text(source_text)
        documents.append(
            {
                "file_id": record.file_id,
                "filename": record.filename,
                "status": record.status,
                "parser_name": (record.processing_params or {}).get("parser_name"),
                **metrics,
            }
        )

    issue_counts = Counter(issue for document in documents for issue in document["issues"])
    ready_count = sum(document["ready_for_extraction"] for document in documents)
    return {
        "contract_version": "defense-kg-pilot-parsed-text-audit-v1",
        "kb_id": kb_id,
        "expected_file_count": expected_file_count,
        "document_count": len(documents),
        "ready_count": ready_count,
        "hold_count": len(documents) - ready_count,
        "issue_counts": dict(sorted(issue_counts.items())),
        "ready": ready_count == expected_file_count,
        "documents": documents,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kb-id", required=True)
    parser.add_argument("--expected-file-count", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args()

    report = asyncio.run(audit(args.kb_id, expected_file_count=args.expected_file_count))
    output_path = args.output.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "documents"}, ensure_ascii=False, indent=2))
    if args.require_clean and not report["ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
