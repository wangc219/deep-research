"""Run the first-round extraction experiment.

This runner verifies the unified extraction contract locally. It does not call
write facts into a graph database.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from adapters import (
    LLMSevenRelationSchemaGuidedAdapter,
    LLMSchemaGuidedAdapter,
    PrecomputedResultAdapter,
    SchemaGuidedOfflineAdapter,
)
from evaluator import evaluate_group, write_evaluation_summary
from llm_client import LLMConfig, OpenAICompatibleClient
from models import DocumentChunk, ExtractionResult, load_chunks, write_jsonl


GROUP_A = "group_a_schema_guided"
GROUP_B = "group_b_llamaindex_schema_path"
GROUP_C = "group_c_neo4j_kg_builder"


def main() -> None:
    args = _parse_args()
    chunks = _load_input_chunks(args)
    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    group_results: list[tuple[str, list[ExtractionResult]]] = []
    skipped_groups: list[str] = []

    group_a_adapter = _build_group_a_adapter(args)
    group_a_results = _run_adapter(group_a_adapter, chunks)
    group_a_name = group_a_adapter.adapter_name
    _write_group_results(output_dir, group_a_name, group_a_results)
    group_results.append((group_a_name, group_a_results))

    if args.group_b_results:
        adapter = PrecomputedResultAdapter(GROUP_B, Path(args.group_b_results))
        results = _run_adapter(adapter, chunks)
        _write_group_results(output_dir, GROUP_B, results)
        group_results.append((GROUP_B, results))
    else:
        skipped_groups.append(GROUP_B)

    if args.group_c_results:
        adapter = PrecomputedResultAdapter(GROUP_C, Path(args.group_c_results))
        results = _run_adapter(adapter, chunks)
        _write_group_results(output_dir, GROUP_C, results)
        group_results.append((GROUP_C, results))
    else:
        skipped_groups.append(GROUP_C)

    summaries = [
        evaluate_group(adapter_name, results, chunks_by_id)
        for adapter_name, results in group_results
    ]
    write_evaluation_summary(output_dir, summaries, skipped_groups)
    print(f"Wrote extraction experiment outputs to {output_dir}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run first-round extraction experiment evaluation."
    )
    parser.add_argument(
        "--chunks",
        help="Path to standardized chunks JSONL. Required unless --demo is set.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use built-in demo chunks for offline smoke verification.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/processed/extraction_experiments/demo",
        help="Directory for group outputs and evaluation summaries.",
    )
    parser.add_argument(
        "--group-a-mode",
        choices=["offline", "llm"],
        default="offline",
        help=(
            "A-group adapter mode. 'offline' uses deterministic local heuristics; "
            "'llm' calls an OpenAI-compatible Chat Completions endpoint."
        ),
    )
    parser.add_argument(
        "--group-a-prompt-version",
        choices=["v3", "v4"],
        default="v3",
        help=(
            "Prompt/schema variant for real LLM A-group extraction. "
            "v3 uses the historical 15-relation prompt; v4 asks the model "
            "to emit only the seven prediction-oriented relation types."
        ),
    )
    parser.add_argument(
        "--group-a-results",
        help=(
            "Precomputed A-group ExtractionResult JSONL. If provided, the runner "
            "uses it instead of calling the offline or LLM A-group adapter."
        ),
    )
    parser.add_argument(
        "--group-b-results",
        help="Precomputed B-group ExtractionResult JSONL.",
    )
    parser.add_argument(
        "--group-c-results",
        help="Precomputed C-group ExtractionResult JSONL.",
    )
    return parser.parse_args()


def _build_group_a_adapter(args: argparse.Namespace):
    if args.group_a_results:
        return PrecomputedResultAdapter(GROUP_A, Path(args.group_a_results))
    if args.group_a_mode == "llm":
        config = LLMConfig.from_env()
        client = OpenAICompatibleClient(config)
        if args.group_a_prompt_version == "v4":
            return LLMSevenRelationSchemaGuidedAdapter(client)
        return LLMSchemaGuidedAdapter(client)
    return SchemaGuidedOfflineAdapter()


def _load_input_chunks(args: argparse.Namespace) -> list[DocumentChunk]:
    if args.demo:
        return _demo_chunks()
    if not args.chunks:
        raise SystemExit("--chunks is required unless --demo is set")
    chunks = load_chunks(Path(args.chunks))
    if not chunks:
        raise SystemExit(f"No chunks found in {args.chunks}")
    return chunks


def _run_adapter(adapter, chunks: list[DocumentChunk]) -> list[ExtractionResult]:
    results: list[ExtractionResult] = []
    for chunk in chunks:
        result = adapter.extract(chunk)
        if result is not None:
            results.append(result)
    return results


def _write_group_results(
    output_dir: Path,
    group_name: str,
    results: list[ExtractionResult],
) -> None:
    group_dir = output_dir / group_name
    rows = [result.to_dict() for result in results]
    write_jsonl(group_dir / "extraction_results.jsonl", rows)


def _demo_chunks() -> list[DocumentChunk]:
    return [
        DocumentChunk(
            document_id="demo-doc-001",
            chunk_id="demo-doc-001-chunk-001",
            text=(
                "某公开综述指出，测控通信技术可用于提升复杂环境下的平台协同能力。"
                "但该技术在跨域应用中仍存在链路稳定性不足和成本约束。"
            ),
            source_path="demo",
            page=1,
            section_title="公开综述片段",
            metadata={"title": "demo chunk 1", "source_type": "paper"},
        ),
        DocumentChunk(
            document_id="demo-doc-002",
            chunk_id="demo-doc-002-chunk-001",
            text=(
                "研究提出，智能识别算法有望支撑目标感知和态势分析。"
                "相关模型可能适用于无人机平台的任务规划研究。"
            ),
            source_path="demo",
            page=2,
            section_title="技术趋势片段",
            metadata={"title": "demo chunk 2", "source_type": "paper"},
        ),
    ]


if __name__ == "__main__":
    main()
