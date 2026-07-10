"""Run the real Neo4j GraphRAG KG Builder pipeline and adapt results.

This script uses neo4j-graphrag's experimental SimpleKGPipeline. By default it
captures the generated graph through a custom KGWriter instead of writing to a
Neo4j database, so extraction quality can be evaluated even when a local Neo4j
server is not running.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from evaluator import evaluate_group, write_evaluation_summary
from llm_client import LLMConfig, OpenAICompatibleClient
from models import (
    DocumentChunk,
    EvidenceSpan,
    ExtractedEntity,
    ExtractedRelation,
    ExtractionResult,
    ExtractionTrace,
    SourceClaim,
    load_chunks,
    write_jsonl,
)
from run_experiment import GROUP_C, _demo_chunks
from schema import (
    ASSERTION_STRENGTHS,
    CLAIM_TYPES,
    ENTITY_TYPES,
    MODALITIES,
    RELATION_TYPES,
    SCHEMA_VERSION,
)


LEXICAL_NODE_LABELS = {"Document", "Chunk"}
LEXICAL_RELATION_TYPES = {"FROM_CHUNK", "NEXT_CHUNK", "PART_OF_DOCUMENT"}

KG_BUILDER_PROMPT_TEMPLATE = """
You are an information extraction component for a governed knowledge graph.
Extract only information explicitly stated in the input text. Do not use outside knowledge.

Return result as a single valid JSON object using exactly this shape:
{{"nodes": [
  {{"id": "0", "label": "Technology", "properties": {{"name": "entity name"}}}}
],
"relationships": [
  {{
    "type": "supports",
    "start_node_id": "0",
    "end_node_id": "1",
    "properties": {{
      "claim_text": "short source claim expressed by the text",
      "claim_type": "fact_statement",
      "modality": "asserted",
      "evidence_quote": "exact continuous quote from input text",
      "assertion_strength": "weak"
    }}
  }}
]}}

Use only the following nodes and relationships:
{schema}

Relationship type guidance:
- supports: source provides support, basis, or condition for target.
- implements: source implements a concrete object, architecture, or function.
- enables: source makes a capability or effect possible or improves it.
- constrains: source limits or weakens target.
- applies_to: source is applied to a task, scenario, domain, or object.
- measured_by: source is measured by target.
- indicates: source is a signal or clue pointing to target; do not use as a generic fallback.
- addresses: source solves, breaks through, mitigates, or responds to a gap, constraint, bottleneck, or problem.
- evolves_to: source evolves from one technical/system/capability state toward another.
- impacts: source affects a capability, system, scenario, competition landscape, or situation.
- similar_to: source is similar to target.
- contrasts_with: source contrasts with target.

Relationship property rules:
- claim_text should summarize the source claim without adding new facts.
- claim_type must be one of: fact_statement, proposal, prediction, opinion, weak_signal, contradiction.
- modality must be one of: asserted, proposed, possible, expected, uncertain, negated.
- evidence_quote must be an exact continuous substring of the input text and should be as short as possible.
- assertion_strength must be one of: strong, weak, speculative, negated.
- If the text uses words like may, possible, expected, proposed, 有望, 可能, 预期, 提出, set modality away from asserted.
- If the text says a technology breaks through a bottleneck, prefer addresses over enables.
- If the text says something evolves from one state toward another, prefer evolves_to.
- If the text says something affects a landscape or situation, prefer impacts.

Assign unique string IDs to nodes and reuse them in relationships.
Respect source and target node types, relationship direction, and the allowed schema.
Return JSON only. No Markdown, no explanation, no extra wrapper list.
Examples:
{examples}

Input text:
{text}
""".strip()


def main() -> None:
    args = _parse_args()
    chunks = _load_input_chunks(args)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results, raw_graphs = asyncio.run(_run_real_kg_builder(args, chunks))
    write_jsonl(output_dir / GROUP_C / "extraction_results.jsonl", [r.to_dict() for r in results])
    write_jsonl(output_dir / GROUP_C / "raw_graphs.jsonl", raw_graphs)

    chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    write_evaluation_summary(
        output_dir,
        [evaluate_group(GROUP_C, results, chunks_by_id)],
        skipped_groups=[],
    )
    print(f"Wrote real Neo4j KG Builder outputs to {output_dir}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run real Neo4j GraphRAG KG Builder on standardized chunks."
    )
    parser.add_argument(
        "--chunks",
        help="Path to standardized chunks JSONL. Required unless --demo is set.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use built-in demo chunks.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Maximum chunks to process. Keep small for first real LLM validation.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for Neo4j KG Builder outputs and evaluation summary.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=360,
        help="LLM request timeout in seconds.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=8000,
        help="Neo4j KG Builder text splitter chunk size.",
    )
    return parser.parse_args()


def _load_input_chunks(args: argparse.Namespace) -> list[DocumentChunk]:
    if args.demo:
        chunks = _demo_chunks()
    else:
        if not args.chunks:
            raise SystemExit("--chunks is required unless --demo is set")
        chunks = load_chunks(Path(args.chunks))
    if args.limit > 0:
        chunks = chunks[: args.limit]
    if not chunks:
        raise SystemExit("No chunks to process")
    return chunks


async def _run_real_kg_builder(
    args: argparse.Namespace,
    chunks: list[DocumentChunk],
) -> tuple[list[ExtractionResult], list[dict[str, Any]]]:
    from neo4j import GraphDatabase
    from neo4j_graphrag.experimental.components.kg_writer import (
        KGWriter,
        KGWriterModel,
    )
    from neo4j_graphrag.experimental.components.text_splitters.fixed_size_splitter import (
        FixedSizeSplitter,
    )
    from neo4j_graphrag.experimental.pipeline.kg_builder import SimpleKGPipeline
    from neo4j_graphrag.llm.base import LLMInterface
    from neo4j_graphrag.llm.types import LLMResponse
    from neo4j_graphrag.embeddings.base import Embedder

    globals()["KGWriterModel"] = KGWriterModel

    class CaptureKGWriter(KGWriter):
        def __init__(self) -> None:
            self.graph = None

        async def run(self, graph, lexical_graph_config=None) -> KGWriterModel:
            self.graph = graph
            return KGWriterModel(status="SUCCESS", metadata={"captured": True})

    class ConstantEmbedder(Embedder):
        def embed_query(self, text: str) -> list[float]:
            return [0.0, 0.0, 0.0]

    class ProjectLLM(LLMInterface):
        def __init__(self, config: LLMConfig) -> None:
            super().__init__(model_name=config.model)
            self.client = OpenAICompatibleClient(config)

        def invoke(
            self,
            input: str,
            message_history: Any | None = None,
            system_instruction: str | None = None,
        ) -> LLMResponse:
            messages = []
            if system_instruction:
                messages.append({"role": "system", "content": system_instruction})
            messages.append({"role": "user", "content": input})
            payload = self.client.complete_json(messages)
            return LLMResponse(content=json.dumps(payload, ensure_ascii=False))

        async def ainvoke(
            self,
            input: str,
            message_history: Any | None = None,
            system_instruction: str | None = None,
        ) -> LLMResponse:
            return await asyncio.to_thread(
                self.invoke,
                input,
                message_history,
                system_instruction,
            )

    config = LLMConfig.from_env()
    config.timeout_seconds = args.timeout_seconds

    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
    try:
        results: list[ExtractionResult] = []
        raw_graphs: list[dict[str, Any]] = []
        for chunk in chunks:
            writer = CaptureKGWriter()
            pipeline = SimpleKGPipeline(
                llm=ProjectLLM(config),
                driver=driver,
                embedder=ConstantEmbedder(),
                entities=sorted(ENTITY_TYPES),
                relations=sorted(RELATION_TYPES),
                potential_schema=_potential_schema(),
                from_pdf=False,
                text_splitter=FixedSizeSplitter(
                    chunk_size=args.chunk_size,
                    chunk_overlap=0,
                    approximate=False,
                ),
                kg_writer=writer,
                on_error="RAISE",
                prompt_template=KG_BUILDER_PROMPT_TEMPLATE,
                perform_entity_resolution=False,
            )
            started = time.perf_counter()
            await pipeline.run_async(text=chunk.text)
            latency_ms = int((time.perf_counter() - started) * 1000)
            graph_payload = serialize_neo4j_graph(writer.graph)
            graph_payload.update(
                {
                    "document_id": chunk.document_id,
                    "chunk_id": chunk.chunk_id,
                    "adapter_name": GROUP_C,
                    "model": config.model,
                    "latency_ms": latency_ms,
                }
            )
            raw_graphs.append(graph_payload)
            results.append(
                raw_graph_to_extraction_result(
                    graph_payload=graph_payload,
                    chunk=chunk,
                    model=config.model,
                    latency_ms=latency_ms,
                )
            )
        return results, raw_graphs
    finally:
        driver.close()


def _potential_schema() -> list[tuple[str, str, str]]:
    return [
        ("Technology", "supports", "Capability"),
        ("Technology", "enables", "Capability"),
        ("Technology", "implements", "EngineeringObject"),
        ("Technology", "applies_to", "Scenario"),
        ("Technology", "constrains", "Constraint"),
        ("Technology", "addresses", "RequirementGap"),
        ("Technology", "addresses", "Constraint"),
        ("Technology", "evolves_to", "Technology"),
        ("Technology", "evolves_to", "Capability"),
        ("Technology", "impacts", "Scenario"),
        ("Technology", "impacts", "Capability"),
        ("Constraint", "constrains", "Technology"),
        ("Metric", "measured_by", "Technology"),
        ("RequirementGap", "indicates", "Technology"),
        ("EngineeringObject", "addresses", "RequirementGap"),
        ("EngineeringObject", "impacts", "Scenario"),
        ("EngineeringObject", "applies_to", "Scenario"),
        ("Principle", "supports", "Technology"),
    ]


def serialize_neo4j_graph(graph: Any) -> dict[str, Any]:
    if graph is None:
        return {"nodes": [], "relationships": [], "writer_status": "NO_GRAPH"}
    if isinstance(graph, dict):
        return {
            "nodes": [_normalize_node_dict(node) for node in graph.get("nodes", [])],
            "relationships": [
                _normalize_relationship_dict(rel)
                for rel in graph.get("relationships", [])
            ],
            "writer_status": "CAPTURED",
        }
    return {
        "nodes": [
            {
                "id": node.id,
                "label": node.label,
                "properties": dict(node.properties or {}),
            }
            for node in graph.nodes
        ],
        "relationships": [
            {
                "start_node_id": rel.start_node_id,
                "end_node_id": rel.end_node_id,
                "type": rel.type,
                "properties": dict(rel.properties or {}),
            }
            for rel in graph.relationships
        ],
        "writer_status": "CAPTURED",
    }


def _normalize_node_dict(node: Any) -> dict[str, Any]:
    if not isinstance(node, dict):
        return {"id": str(node), "label": "", "properties": {}}
    return {
        "id": str(node.get("id", "")),
        "label": str(node.get("label", "")),
        "properties": dict(node.get("properties") or {}),
    }


def _normalize_relationship_dict(rel: Any) -> dict[str, Any]:
    if not isinstance(rel, dict):
        return {
            "start_node_id": "",
            "end_node_id": "",
            "type": "",
            "properties": {},
        }
    return {
        "start_node_id": str(rel.get("start_node_id", "")),
        "end_node_id": str(rel.get("end_node_id", "")),
        "type": str(rel.get("type", "")),
        "properties": dict(rel.get("properties") or {}),
    }


def raw_graph_to_extraction_result(
    graph_payload: dict[str, Any],
    chunk: DocumentChunk,
    model: str,
    latency_ms: int,
) -> ExtractionResult:
    full_chunk_evidence_id = f"{chunk.chunk_id}-neo4j-kg-builder-full-chunk"
    full_chunk_evidence = EvidenceSpan(
        evidence_id=full_chunk_evidence_id,
        chunk_id=chunk.chunk_id,
        quote=chunk.text,
        start_char=0,
        end_char=len(chunk.text),
        page=chunk.page,
    )
    semantic_nodes = [
        node
        for node in graph_payload.get("nodes", [])
        if node.get("label") not in LEXICAL_NODE_LABELS
    ]
    node_ids = {str(node.get("id", "")) for node in semantic_nodes}
    entities = [
        ExtractedEntity(
            entity_id=str(node.get("id", "")),
            name=str((node.get("properties") or {}).get("name") or node.get("id", "")),
            entity_type=str(node.get("label", "")),
            evidence_span_ids=[full_chunk_evidence_id],
            confidence=0.0,
        )
        for node in semantic_nodes
    ]
    evidence_spans = [full_chunk_evidence]
    evidence_by_quote: dict[str, str] = {}
    relations: list[ExtractedRelation] = []
    claims: list[SourceClaim] = []
    warnings: list[str] = []
    for index, rel in enumerate(graph_payload.get("relationships", []), start=1):
        rel_type = str(rel.get("type", ""))
        source = str(rel.get("start_node_id", ""))
        target = str(rel.get("end_node_id", ""))
        if rel_type in LEXICAL_RELATION_TYPES:
            continue
        if source not in node_ids or target not in node_ids:
            continue
        properties = dict(rel.get("properties") or {})
        evidence_ids = _evidence_ids_from_relationship_properties(
            properties=properties,
            chunk=chunk,
            evidence_spans=evidence_spans,
            evidence_by_quote=evidence_by_quote,
            fallback_evidence_id=full_chunk_evidence_id,
            warnings=warnings,
        )
        assertion_strength = _allowed_value(
            str(properties.get("assertion_strength", "")),
            ASSERTION_STRENGTHS,
            "weak",
        )
        relation_id = f"{chunk.chunk_id}-neo4j-kg-builder-rel-{index:03d}"
        relations.append(
            ExtractedRelation(
                relation_id=relation_id,
                source_entity_id=source,
                target_entity_id=target,
                relation_type=rel_type,
                evidence_span_ids=evidence_ids,
                assertion_strength=assertion_strength,
                confidence=0.0,
            )
        )
        claim_text = str(properties.get("claim_text") or "").strip()
        if claim_text:
            claims.append(
                SourceClaim(
                    claim_id=f"{chunk.chunk_id}-neo4j-kg-builder-claim-{index:03d}",
                    claim_type=_allowed_value(
                        str(properties.get("claim_type", "")),
                        CLAIM_TYPES,
                        "fact_statement",
                    ),
                    text=claim_text,
                    modality=_allowed_value(
                        str(properties.get("modality", "")),
                        MODALITIES,
                        "asserted",
                    ),
                    evidence_span_ids=evidence_ids,
                    subject_entity_id=source,
                    object_entity_id=target,
                    predicate=rel_type,
                    confidence=0.0,
                )
            )
        else:
            warnings.append(f"neo4j_relationship_missing_claim_text:{relation_id}")
    if len(evidence_spans) == 1:
        warnings.append(
            "Neo4j KG Builder emitted no usable exact evidence_quote; full chunk used as evidence."
        )
    result = ExtractionResult(
        task_id=f"{chunk.chunk_id}-neo4j-kg-builder-real",
        adapter_name=GROUP_C,
        document_id=chunk.document_id,
        chunk_id=chunk.chunk_id,
        entities=entities,
        relations=relations,
        claims=claims,
        evidence_spans=evidence_spans,
        warnings=warnings,
        trace=ExtractionTrace(
            schema_version=SCHEMA_VERSION,
            prompt_version="neo4j-graphrag-simple-kg-pipeline-enhanced-schema-v2",
            model=model,
            latency_ms=latency_ms,
            cost=0.0,
            retry_count=0,
        ),
    )
    structural_warnings = result.validate(chunk.text)
    if structural_warnings:
        result.warnings = list(dict.fromkeys([*result.warnings, *structural_warnings]))
    return result


def _evidence_ids_from_relationship_properties(
    properties: dict[str, Any],
    chunk: DocumentChunk,
    evidence_spans: list[EvidenceSpan],
    evidence_by_quote: dict[str, str],
    fallback_evidence_id: str,
    warnings: list[str],
) -> list[str]:
    quote = str(properties.get("evidence_quote") or "").strip()
    if not quote:
        return [fallback_evidence_id]
    start_char, end_char, exact_quote = _locate_quote(quote, chunk.text)
    if start_char is None or end_char is None:
        warnings.append(f"neo4j_evidence_quote_not_found:{quote[:60]}")
        return [fallback_evidence_id]
    evidence_key = exact_quote or quote
    if evidence_key in evidence_by_quote:
        return [evidence_by_quote[evidence_key]]
    evidence_id = f"{chunk.chunk_id}-neo4j-kg-builder-ev-{len(evidence_by_quote) + 1:03d}"
    evidence_by_quote[evidence_key] = evidence_id
    evidence_spans.append(
        EvidenceSpan(
            evidence_id=evidence_id,
            chunk_id=chunk.chunk_id,
            quote=evidence_key,
            start_char=start_char,
            end_char=end_char,
            page=chunk.page,
        )
    )
    return [evidence_id]


def _locate_quote(quote: str, text: str) -> tuple[int | None, int | None, str]:
    if not quote:
        return None, None, ""
    start_char = text.find(quote)
    if start_char >= 0:
        return start_char, start_char + len(quote), quote

    compact_quote = "".join(quote.split())
    if not compact_quote:
        return None, None, ""
    compact_chars: list[str] = []
    original_positions: list[int] = []
    for index, char in enumerate(text):
        if char.isspace():
            continue
        compact_chars.append(char)
        original_positions.append(index)
    compact_text = "".join(compact_chars)
    compact_start = compact_text.find(compact_quote)
    if compact_start < 0:
        return None, None, ""
    compact_end = compact_start + len(compact_quote) - 1
    original_start = original_positions[compact_start]
    original_end = original_positions[compact_end] + 1
    return original_start, original_end, text[original_start:original_end]


def _allowed_value(value: str, allowed_values: set[str], fallback: str) -> str:
    normalized = value.strip()
    if normalized in allowed_values:
        return normalized
    lowered = normalized.lower()
    if lowered in allowed_values:
        return lowered
    return fallback


if __name__ == "__main__":
    main()
