#!/usr/bin/env python3
"""导出 1000 篇军事语料中 train/dev 的无 PDF 外部 GPU 预标视图。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from platform_core.knowledge.training.military_corpus_prelabel import (
    export_external_prelabel_view,
    load_authoritative_blocks,
    load_training_manifest,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--domain-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--kb-id", required=True)
    parser.add_argument("--database-url", default="postgresql://postgres:postgres@127.0.0.1:15432/yuxi")
    parser.add_argument("--new-document-domain", action="append", default=[])
    args = parser.parse_args()

    new_domains = dict(item.split("=", 1) for item in args.new_document_domain)
    manifest = load_training_manifest(
        args.source_manifest.expanduser().resolve(),
        args.domain_manifest.expanduser().resolve(),
        new_document_domains=new_domains,
    )
    manifest = [item for item in manifest if item["split"] in {"train", "dev"}]
    documents = load_authoritative_blocks(args.database_url, args.kb_id, manifest)
    report = export_external_prelabel_view(documents, args.output.expanduser().resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
