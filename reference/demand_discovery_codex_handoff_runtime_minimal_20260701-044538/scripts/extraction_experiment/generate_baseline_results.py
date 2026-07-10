"""Generate deterministic B/C baseline outputs for extraction comparison.

The baselines are framework-shape proxies. They do not call LlamaIndex or Neo4j;
they produce precomputed ExtractionResult JSONL files that exercise the same
adapter contract used by those paths.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from adapters import (
    LlamaIndexSchemaPathBaselineAdapter,
    Neo4jKGBuilderBaselineAdapter,
)
from models import DocumentChunk, ExtractionResult, load_chunks, write_jsonl
from run_experiment import GROUP_B, GROUP_C, _demo_chunks


def main() -> None:
    args = _parse_args()
    chunks = _load_input_chunks(args)
    output_dir = Path(args.output_dir)

    adapters = [
        (GROUP_B, LlamaIndexSchemaPathBaselineAdapter()),
        (GROUP_C, Neo4jKGBuilderBaselineAdapter()),
    ]
    for group_name, adapter in adapters:
        results = _run_adapter(adapter, chunks)
        _write_group_results(output_dir, group_name, results)

    print(f"Wrote B/C baseline precomputed outputs to {output_dir}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate deterministic B/C baseline ExtractionResult JSONL files."
    )
    parser.add_argument(
        "--chunks",
        help="Path to standardized chunks JSONL. Required unless --demo is set.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use the same built-in demo chunks as run_experiment.py.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for generated group_b/group_c precomputed outputs.",
    )
    return parser.parse_args()


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
    write_jsonl(
        output_dir / group_name / "extraction_results.jsonl",
        [result.to_dict() for result in results],
    )


if __name__ == "__main__":
    main()
