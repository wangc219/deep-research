"""对现有知识库做小样本性能测试，不修改文件、分块或图谱结果。"""

import argparse
import asyncio
import json
import tempfile
import time
from pathlib import Path

import pypdfium2 as pdfium
from sqlalchemy import func, select

from platform_core.knowledge.graphs.extractors.base import normalize_extraction_result, verify_extraction_evidence
from platform_core.knowledge.graphs.extractors.llm import LLMGraphExtractor
from platform_core.knowledge.graphs.milvus_graph_service import MilvusGraphService
from platform_core.knowledge.parser.local_ocr_pool import process_local_document
from platform_core.knowledge.parser.rapid_ocr import RapidOCRParser
from platform_core.knowledge.utils.kb_utils import parse_minio_url
from platform_core.storage.minio import get_minio_client
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_knowledge import KnowledgeBase, KnowledgeChunk, KnowledgeFile


async def benchmark(args):
    """在真实模型和已上传文件上采样，输出耗时与结果数量。"""
    pg_manager.initialize()
    report = {}
    try:
        async with pg_manager.get_async_session_context() as session:
            kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.kb_id == args.kb_id))
            if kb is None:
                raise ValueError("知识库不存在")
            options = dict(kb.additional_params["graph_build_config"]["extractor_options"])
            if args.enable_thinking is not None:
                options["enable_thinking"] = args.enable_thinking
                params = dict(options.get("model_params") or {})
                params["extra_body"] = {**dict(params.get("extra_body") or {}), "thinking_budget": args.thinking_budget}
                options["model_params"] = params
            chunks = (
                list(
                    await session.scalars(
                        select(KnowledgeChunk)
                        .where(
                            KnowledgeChunk.kb_id == args.kb_id,
                            func.length(KnowledgeChunk.content) >= 500,
                        )
                        .order_by(KnowledgeChunk.id)
                        .offset(args.sample_offset)
                        .limit(args.model_samples)
                    )
                )
                if args.model_samples
                else []
            )
            files = (
                list(
                    await session.scalars(
                        select(KnowledgeFile)
                        .where(
                            KnowledgeFile.kb_id == args.kb_id,
                            KnowledgeFile.filename.ilike("%.pdf"),
                        )
                        .order_by(KnowledgeFile.id)
                        .limit(args.ocr_files)
                    )
                )
                if args.ocr_files
                else []
            )

        if chunks:
            extractor = LLMGraphExtractor(options)
            service_start = time.monotonic()

            async def extract(chunk):
                started = time.monotonic()
                context = await MilvusGraphService()._load_preceding_context(chunk, extractor)
                result = await extractor.extract(
                    chunk.content, chunk_metadata={"chunk_id": chunk.chunk_id, "context_chunks": context}
                )
                normalized = normalize_extraction_result(result, "llm", options)
                normalized = verify_extraction_evidence(normalized, chunk.content)
                return {
                    "chunk_id": chunk.chunk_id,
                    "input_chars": len(chunk.content),
                    "seconds": round(time.monotonic() - started, 2),
                    "entities": len(normalized["entities"]),
                    "relations": len(normalized["relations"]),
                    "original_relations": len((chunk.extraction_result or {}).get("relations") or []),
                    "original_result": chunk.extraction_result,
                    "optimized_result": normalized,
                }

            try:
                outcomes = await asyncio.gather(*(extract(chunk) for chunk in chunks), return_exceptions=True)
                results = [
                    {"chunk_id": chunk.chunk_id, "error": str(outcome)} if isinstance(outcome, Exception) else outcome
                    for chunk, outcome in zip(chunks, outcomes, strict=True)
                ]
                report["graph"] = results
                report["graph_wall_seconds"] = round(time.monotonic() - service_start, 2)
                print(
                    json.dumps(
                        {
                            "graph": [
                                {key: value for key, value in result.items() if not key.endswith("_result")}
                                for result in results
                            ],
                            "wall_seconds": report["graph_wall_seconds"],
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            finally:
                await extractor.aclose()

        if files:
            with tempfile.TemporaryDirectory(prefix="knowledge-benchmark-") as directory:
                sources = []
                for index, file in enumerate(files):
                    bucket, name = parse_minio_url(file.minio_url or file.path)
                    content = await get_minio_client().adownload_file(bucket, name)
                    original = Path(directory) / f"original-{index}.pdf"
                    original.write_bytes(content)
                    sample = Path(directory) / f"sample-{index}.pdf"
                    with pdfium.PdfDocument(original) as source_pdf, pdfium.PdfDocument.new() as sample_pdf:
                        sample_pdf.import_pages(source_pdf, pages=list(range(min(len(source_pdf), args.ocr_pages))))
                        sample_pdf.save(sample)
                    sources.append(str(sample))
                parser = RapidOCRParser()
                started = time.monotonic()
                baseline = [
                    await asyncio.to_thread(parser.process_pdf, path, {"prefer_text_layer": False}) for path in sources
                ]
                serial = time.monotonic() - started
                started = time.monotonic()
                optimized = await asyncio.gather(
                    *(process_local_document(path, {"prefer_text_layer": True}) for path in sources)
                )
                parallel = time.monotonic() - started
                report["ocr"] = {
                    "ocr_files": len(files),
                    "pages_per_file": args.ocr_pages,
                    "serial_ocr_seconds": round(serial, 2),
                    "optimized_seconds": round(parallel, 2),
                    "baseline_chars": list(map(len, baseline)),
                    "optimized_chars": list(map(len, optimized)),
                }
                print(json.dumps(report["ocr"], ensure_ascii=False), flush=True)
        if args.output:
            Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        await pg_manager.close()


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--kb-id", required=True)
    cli.add_argument("--model-samples", type=int, choices=range(0, 9), default=3)
    cli.add_argument("--ocr-files", type=int, choices=range(0, 5), default=2)
    cli.add_argument("--ocr-pages", type=int, choices=range(1, 6), default=2)
    cli.add_argument("--output", help="可选，保存包含对比抽取结果的本地 JSON 报告")
    cli.add_argument("--enable-thinking", action=argparse.BooleanOptionalAction, default=None)
    cli.add_argument("--thinking-budget", type=int, default=2048)
    cli.add_argument("--sample-offset", type=int, choices=range(21), default=0)
    asyncio.run(benchmark(cli.parse_args()))
