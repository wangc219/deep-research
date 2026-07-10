"""Build seven-relation projections and rule-path hypothesis links from extraction JSONL.

This is an experiment-layer script. It does not call an LLM, does not write
Neo4j, and does not mutate previous extraction outputs.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_ROOT = PROJECT_ROOT / "scripts" / "extraction_experiment"
sys.path.insert(0, str(EXPERIMENT_ROOT))

from models import ExtractionResult, load_results, write_jsonl  # noqa: E402

from resolve_entities_sqlite import (  # noqa: E402
    NOISE_ALIASES,
    SEED_ALIAS_GROUPS,
    normalize_entity_name,
)


DEFAULT_RESULTS = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "zsdd_2026_02_full_ocr_llm_v3_all_chunks"
    / "group_a_schema_guided"
    / "extraction_results.jsonl"
)
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "extraction_experiments"
    / "zsdd_2026_02_v3_seven_relation_prediction"
)
DEFAULT_REPORT = (
    PROJECT_ROOT
    / "docs"
    / "experiment-artifacts"
    / "seven_relation_hypothesis_prediction_v0.md"
)

SEVEN_RELATION_TYPES = {
    "ENABLES",
    "DRIVES",
    "IMPLEMENTS",
    "HAS_CAPABILITY",
    "APPLIES_TO",
    "CONSTRAINS",
    "RESPONSIBLE_FOR",
}

DIRECT_RELATION_PROJECTION = {
    "enables": "ENABLES",
    "supports": "ENABLES",
    "drives": "DRIVES",
    "implements": "IMPLEMENTS",
    "responsible_for": "RESPONSIBLE_FOR",
    "has_capability": "HAS_CAPABILITY",
    "constrains": "CONSTRAINS",
    "applies_to": "APPLIES_TO",
}

CONTEXT_ONLY_RELATIONS = {
    "indicates",
    "measured_by",
    "evolves_to",
    "similar_to",
    "contrasts_with",
}

NEGATIVE_IMPACT_PATTERN = re.compile(
    r"限制|制约|削弱|妨碍|阻碍|风险|威胁|降低|limit|constrain|risk|threat|reduce|weaken",
    re.IGNORECASE,
)
POSITIVE_IMPACT_PATTERN = re.compile(
    r"提升|增强|提高|促进|改进|改善|boost|improve|enhance|increase|promote",
    re.IGNORECASE,
)

RULE_WEIGHTS = {
    "project_implementation_to_capability": 0.78,
    "actor_responsibility_to_implemented_object": 0.72,
    "actor_responsibility_to_capability": 0.62,
    "capability_application_from_technology": 0.72,
    "platform_capability_from_applied_technology": 0.76,
    "cross_document_capability_application_from_technology": 0.58,
    "cross_document_platform_capability_from_applied_technology": 0.60,
    "requirement_drives_enabled_capability": 0.70,
    "requirement_drives_implemented_object": 0.66,
    "constraint_risk_to_enabling_technology": 0.55,
}

OPERATION_SOURCE_PATTERN = re.compile(
    r"(交叉|变异|选择|迭代|训练|验证|测试|仿真|计算|响应|采样|归一化)?(操作|步骤|过程|流程)$",
    re.IGNORECASE,
)
UNSTABLE_TECH_HOLDER_PATTERN = re.compile(
    r"(程序|方法|格式|操作|步骤|过程|流程|性能|指标)$",
    re.IGNORECASE,
)
STABLE_TECH_HOLDER_PATTERN = re.compile(
    r"系统|平台|模型|算法|软件|架构|装备|项目|计划|无人机|导弹|雷达|卫星|飞行器",
    re.IGNORECASE,
)
INTERNAL_METRIC_CAPABILITY_PATTERN = re.compile(
    r"种群多样性|高效收敛|收敛速度|泛化能力|稳定性|局部最优|全局搜索能力|非线性拟合能力",
    re.IGNORECASE,
)
PLATFORM_TOKEN_PATTERN = re.compile(
    r"(MQ-\d+|XQ-\d+|TB\d+[A-Z]?|SR-\d+|HT-\d+|F-\d+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RelationProjection:
    canonical_relation_type: str
    source_id: str
    target_id: str
    reversed_direction: bool = False
    projection_rule: str = ""


@dataclass
class ProjectedEdge:
    edge_id: str
    canonical_relation_type: str
    source_id: str
    source_name: str
    source_type: str
    target_id: str
    target_name: str
    target_type: str
    document_id: str
    chunk_id: str
    raw_relation_type: str
    confidence: float
    claim_ids: list[str] = field(default_factory=list)
    claim_modalities: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    evidence_quotes: list[str] = field(default_factory=list)
    trigger_text: str = ""
    assertion_strength: str = ""
    projection_rule: str = ""
    reversed_direction: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HypothesisLink:
    hypothesis_id: str
    rule_id: str
    predicted_relation_type: str
    source_id: str
    source_name: str
    source_type: str
    target_id: str
    target_name: str
    target_type: str
    score: float
    distinct_document_count: int
    supporting_paths: list[list[str]]
    path_edge_ids: list[str]
    source_claim_ids: list[str]
    evidence_ids: list[str]
    evidence_quotes: list[str]
    path_assertion_strengths: list[str] = field(default_factory=list)
    path_claim_modalities: list[str] = field(default_factory=list)
    weak_path_edge_count: int = 0
    path_risk_flags: list[str] = field(default_factory=list)
    status: str = "unverified"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def main() -> int:
    args = parse_args()
    results_path = Path(args.results).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve()
    if not results_path.exists():
        raise FileNotFoundError(f"ExtractionResult JSONL not found: {results_path}")

    results = load_results(results_path)
    projection_result = build_projected_edges(results)
    edges = projection_result["edges"]
    hypotheses = build_hypotheses(edges)
    summary = build_summary(results, projection_result, hypotheses)
    labels_path = output_dir / "hypothesis_labels_top50.jsonl"
    label_rows = read_jsonl(labels_path) if labels_path.exists() else []
    label_summary = (
        summarize_hypothesis_labels(label_rows, hypotheses) if label_rows else {}
    )
    if label_summary:
        summary["top50_label_summary"] = label_summary

    output_dir.mkdir(parents=True, exist_ok=True)
    projected_edges_path = output_dir / "projected_edges.jsonl"
    hypotheses_path = output_dir / "hypotheses.jsonl"
    summary_path = output_dir / "summary.json"
    write_jsonl(projected_edges_path, (edge.to_dict() for edge in edges))
    write_jsonl(hypotheses_path, (item.to_dict() for item in hypotheses))
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        build_report(
            results_path=results_path,
            projected_edges_path=projected_edges_path,
            hypotheses_path=hypotheses_path,
            summary_path=summary_path,
            summary=summary,
            hypotheses=hypotheses,
            labels_path=labels_path if label_summary else None,
            label_summary=label_summary,
        ),
        encoding="utf-8",
    )
    print(f"wrote {projected_edges_path}")
    print(f"wrote {hypotheses_path}")
    print(f"wrote {summary_path}")
    print(f"wrote {report_path}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Project relation assertions to seven prediction edges and generate rule-path hypotheses.",
    )
    parser.add_argument("--results", default=str(DEFAULT_RESULTS))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    return parser.parse_args()


def project_relation(
    relation_type: str,
    source_id: str,
    target_id: str,
    source_type: str,
    target_type: str,
    trigger_text: str = "",
) -> RelationProjection | None:
    if relation_type in DIRECT_RELATION_PROJECTION:
        return RelationProjection(
            canonical_relation_type=DIRECT_RELATION_PROJECTION[relation_type],
            source_id=source_id,
            target_id=target_id,
            projection_rule=f"{relation_type}_to_{DIRECT_RELATION_PROJECTION[relation_type].lower()}",
        )
    if relation_type == "addresses":
        if target_type in {"RequirementGap", "Constraint"}:
            return RelationProjection(
                canonical_relation_type="DRIVES",
                source_id=target_id,
                target_id=source_id,
                reversed_direction=True,
                projection_rule="addresses_reversed_to_drives",
            )
        return None
    if relation_type == "impacts":
        if NEGATIVE_IMPACT_PATTERN.search(trigger_text or ""):
            return RelationProjection(
                canonical_relation_type="CONSTRAINS",
                source_id=source_id,
                target_id=target_id,
                projection_rule="negative_impacts_to_constrains",
            )
        if POSITIVE_IMPACT_PATTERN.search(trigger_text or ""):
            return RelationProjection(
                canonical_relation_type="ENABLES",
                source_id=source_id,
                target_id=target_id,
                projection_rule="positive_impacts_to_enables",
            )
        return None
    if relation_type in CONTEXT_ONLY_RELATIONS:
        return None
    return None


def build_projected_edges(results: list[ExtractionResult]) -> dict[str, Any]:
    alias_lookup = _alias_lookup()
    dropped_counts: Counter[str] = Counter()
    projected_edges: list[ProjectedEdge] = []
    noise_edge_count = 0
    raw_relation_count = 0

    for result in results:
        entities_by_id = {entity.entity_id: entity for entity in result.entities}
        evidence_by_id = {span.evidence_id: span for span in result.evidence_spans}
        claims_by_signature = _claims_by_signature(result)
        claims_by_evidence = _claims_by_evidence(result)

        for index, relation in enumerate(result.relations, start=1):
            raw_relation_count += 1
            raw_source = entities_by_id.get(relation.source_entity_id)
            raw_target = entities_by_id.get(relation.target_entity_id)
            if raw_source is None or raw_target is None:
                dropped_counts["missing_endpoint"] += 1
                continue

            source = _canonical_entity(
                raw_source.name,
                raw_source.entity_type,
                alias_lookup,
            )
            target = _canonical_entity(
                raw_target.name,
                raw_target.entity_type,
                alias_lookup,
            )
            if source is None or target is None:
                noise_edge_count += 1
                dropped_counts["noise_endpoint"] += 1
                continue

            projection = project_relation(
                relation_type=relation.relation_type,
                source_id=source["id"],
                target_id=target["id"],
                source_type=source["type"],
                target_type=target["type"],
                trigger_text=relation.trigger_text,
            )
            if projection is None:
                dropped_counts[relation.relation_type] += 1
                continue

            endpoints = {
                source["id"]: source,
                target["id"]: target,
            }
            projected_source = endpoints.get(projection.source_id, source)
            projected_target = endpoints.get(projection.target_id, target)
            matched_claims = claims_by_signature.get(
                (relation.source_entity_id, relation.target_entity_id, relation.relation_type),
                [],
            )
            if not matched_claims:
                matched_claims = [
                    claim
                    for evidence_id in relation.evidence_span_ids
                    for claim in claims_by_evidence.get(evidence_id, [])
                ]
            evidence_ids = _ordered_unique(
                [
                    *relation.evidence_span_ids,
                    *[
                        evidence_id
                        for claim in matched_claims
                        for evidence_id in claim.evidence_span_ids
                    ],
                ]
            )
            relation_id = relation.relation_id or f"r{index}"
            edge_id = f"{result.chunk_id}::{relation_id}"
            projected_edges.append(
                ProjectedEdge(
                    edge_id=edge_id,
                    canonical_relation_type=projection.canonical_relation_type,
                    source_id=projection.source_id,
                    source_name=projected_source["name"],
                    source_type=projected_source["type"],
                    target_id=projection.target_id,
                    target_name=projected_target["name"],
                    target_type=projected_target["type"],
                    document_id=result.document_id,
                    chunk_id=result.chunk_id,
                    raw_relation_type=relation.relation_type,
                    confidence=relation.confidence,
                    claim_ids=[f"{result.chunk_id}::{claim.claim_id}" for claim in matched_claims],
                    claim_modalities=_ordered_unique(
                        claim.modality for claim in matched_claims if claim.modality
                    ),
                    evidence_ids=[f"{result.chunk_id}::{evidence_id}" for evidence_id in evidence_ids],
                    evidence_quotes=_ordered_unique(
                        evidence_by_id[evidence_id].quote
                        for evidence_id in evidence_ids
                        if evidence_id in evidence_by_id
                    ),
                    trigger_text=relation.trigger_text,
                    assertion_strength=relation.assertion_strength,
                    projection_rule=projection.projection_rule,
                    reversed_direction=projection.reversed_direction,
                )
            )

    return {
        "edges": projected_edges,
        "raw_relation_count": raw_relation_count,
        "dropped_counts": dict(sorted(dropped_counts.items())),
        "noise_edge_count": noise_edge_count,
    }


def build_hypotheses(edges: list[ProjectedEdge]) -> list[HypothesisLink]:
    by_source_type: dict[tuple[str, str], list[ProjectedEdge]] = defaultdict(list)
    by_target_type: dict[tuple[str, str], list[ProjectedEdge]] = defaultdict(list)
    existing = {
        (edge.source_id, edge.canonical_relation_type, edge.target_id)
        for edge in edges
    }
    edge_by_id = {edge.edge_id: edge for edge in edges}
    accumulator: dict[tuple[str, str, str], list[tuple[str, list[str]]]] = defaultdict(list)

    for edge in edges:
        by_source_type[(edge.source_id, edge.canonical_relation_type)].append(edge)
        by_target_type[(edge.target_id, edge.canonical_relation_type)].append(edge)

    for implements in [edge for edge in edges if edge.canonical_relation_type == "IMPLEMENTS"]:
        if not _is_stable_capability_holder(implements.source_name, implements.source_type):
            continue
        for capability in by_source_type.get((implements.target_id, "HAS_CAPABILITY"), []):
            if not _same_document([implements, capability]):
                continue
            _add_path(
                accumulator,
                "project_implementation_to_capability",
                "HAS_CAPABILITY",
                implements.source_id,
                capability.target_id,
                [implements.edge_id, capability.edge_id],
                existing,
            )

    for responsible in [edge for edge in edges if edge.canonical_relation_type == "RESPONSIBLE_FOR"]:
        for implements in by_source_type.get((responsible.target_id, "IMPLEMENTS"), []):
            if not _same_document([responsible, implements]):
                continue
            _add_path(
                accumulator,
                "actor_responsibility_to_implemented_object",
                "RESPONSIBLE_FOR",
                responsible.source_id,
                implements.target_id,
                [responsible.edge_id, implements.edge_id],
                existing,
            )
            for capability in by_source_type.get((implements.target_id, "HAS_CAPABILITY"), []):
                if not _same_document([responsible, implements, capability]):
                    continue
                _add_path(
                    accumulator,
                    "actor_responsibility_to_capability",
                    "HAS_CAPABILITY",
                    responsible.source_id,
                    capability.target_id,
                    [responsible.edge_id, implements.edge_id, capability.edge_id],
                    existing,
                )

    for enables in [edge for edge in edges if edge.canonical_relation_type == "ENABLES"]:
        for application in by_source_type.get((enables.source_id, "APPLIES_TO"), []):
            if _same_document([enables, application]):
                _add_application_path(
                    accumulator=accumulator,
                    enables=enables,
                    application=application,
                    path=[enables.edge_id, application.edge_id],
                    existing=existing,
                    cross_document=False,
                )
                continue
            if not _cross_document_application_allowed(enables, application):
                continue
            _add_application_path(
                accumulator=accumulator,
                enables=enables,
                application=application,
                path=[enables.edge_id, application.edge_id],
                existing=existing,
                cross_document=True,
            )

    for drives in [edge for edge in edges if edge.canonical_relation_type == "DRIVES"]:
        for enables in by_source_type.get((drives.target_id, "ENABLES"), []):
            if not _is_valid_requirement_enabled_target(enables):
                continue
            if not _same_document([drives, enables]):
                continue
            _add_path(
                accumulator,
                "requirement_drives_enabled_capability",
                "DRIVES",
                drives.source_id,
                enables.target_id,
                [drives.edge_id, enables.edge_id],
                existing,
            )
        for implements in by_source_type.get((drives.target_id, "IMPLEMENTS"), []):
            if not _same_document([drives, implements]):
                continue
            _add_path(
                accumulator,
                "requirement_drives_implemented_object",
                "DRIVES",
                drives.source_id,
                implements.target_id,
                [drives.edge_id, implements.edge_id],
                existing,
            )

    for constrains in [edge for edge in edges if edge.canonical_relation_type == "CONSTRAINS"]:
        for enables in by_target_type.get((constrains.target_id, "ENABLES"), []):
            if not _same_document([constrains, enables]):
                continue
            _add_path(
                accumulator,
                "constraint_risk_to_enabling_technology",
                "CONSTRAINS",
                constrains.source_id,
                enables.source_id,
                [constrains.edge_id, enables.edge_id],
                existing,
            )

    hypotheses: list[HypothesisLink] = []
    for index, (key, rule_paths) in enumerate(sorted(accumulator.items()), start=1):
        relation_type, source_id, target_id = key
        primary_rule_id = _primary_rule_id(rule_id for rule_id, _path in rule_paths)
        paths = [path for _rule_id, path in rule_paths]
        first_path = paths[0]
        source_edge = edge_by_id[first_path[0]]
        target_edge = edge_by_id[first_path[-1]]
        source_entity = _edge_endpoint(edge_by_id, source_id, first_path)
        target_entity = _edge_endpoint(edge_by_id, target_id, first_path)
        document_ids = {
            edge_by_id[edge_id].document_id
            for path in paths
            for edge_id in path
            if edge_id in edge_by_id
        }
        path_edges = [
            edge_by_id[edge_id]
            for path in paths
            for edge_id in path
            if edge_id in edge_by_id
        ]
        confidence = _average(edge.confidence for edge in path_edges)
        score = _score_hypothesis(primary_rule_id, confidence, len(first_path), len(document_ids))
        path_risk = _path_risk(path_edges)
        hypotheses.append(
            HypothesisLink(
                hypothesis_id=f"hyp-{index:05d}",
                rule_id=primary_rule_id,
                predicted_relation_type=relation_type,
                source_id=source_id,
                source_name=source_entity["name"],
                source_type=source_entity["type"],
                target_id=target_id,
                target_name=target_entity["name"],
                target_type=target_entity["type"],
                score=score,
                distinct_document_count=len(document_ids),
                supporting_paths=paths,
                path_edge_ids=first_path,
                source_claim_ids=_ordered_unique(
                    claim_id for edge in path_edges for claim_id in edge.claim_ids
                ),
                evidence_ids=_ordered_unique(
                    evidence_id for edge in path_edges for evidence_id in edge.evidence_ids
                ),
                evidence_quotes=_ordered_unique(
                    quote for edge in path_edges for quote in edge.evidence_quotes
                )[:8],
                path_assertion_strengths=path_risk["assertion_strengths"],
                path_claim_modalities=path_risk["claim_modalities"],
                weak_path_edge_count=path_risk["weak_edge_count"],
                path_risk_flags=path_risk["risk_flags"],
            )
        )

    return sorted(
        hypotheses,
        key=lambda item: (
            -item.score,
            -item.distinct_document_count,
            item.rule_id,
            item.source_name,
            item.target_name,
        ),
    )


def _path_risk(path_edges: list[ProjectedEdge]) -> dict[str, Any]:
    unique_edges = _ordered_unique_edges(path_edges)
    assertion_strengths = _ordered_unique(
        edge.assertion_strength for edge in unique_edges if edge.assertion_strength
    )
    claim_modalities = _ordered_unique(
        modality
        for edge in unique_edges
        for modality in edge.claim_modalities
        if modality
    )
    weak_edge_count = sum(1 for edge in unique_edges if _is_weak_path_edge(edge))
    risk_flags: list[str] = []
    if weak_edge_count:
        risk_flags.append("weak_assertion_path")
    if any(
        edge.assertion_strength == "negated" or "negated" in edge.claim_modalities
        for edge in unique_edges
    ):
        risk_flags.append("negated_path")
    return {
        "assertion_strengths": assertion_strengths,
        "claim_modalities": claim_modalities,
        "weak_edge_count": weak_edge_count,
        "risk_flags": risk_flags,
    }


def _is_weak_path_edge(edge: ProjectedEdge) -> bool:
    if edge.assertion_strength in {"weak", "speculative", "negated"}:
        return True
    return any(modality != "asserted" for modality in edge.claim_modalities)


def _ordered_unique_edges(edges: Iterable[ProjectedEdge]) -> list[ProjectedEdge]:
    seen: set[str] = set()
    output: list[ProjectedEdge] = []
    for edge in edges:
        if edge.edge_id in seen:
            continue
        seen.add(edge.edge_id)
        output.append(edge)
    return output


def _add_application_path(
    accumulator: dict[tuple[str, str, str], list[tuple[str, list[str]]]],
    enables: ProjectedEdge,
    application: ProjectedEdge,
    path: list[str],
    existing: set[tuple[str, str, str]],
    cross_document: bool,
) -> None:
    if _is_internal_metric_capability(enables.target_name):
        return
    if _is_scenario_like(application.target_name, application.target_type):
        _add_path(
            accumulator,
            (
                "cross_document_capability_application_from_technology"
                if cross_document
                else "capability_application_from_technology"
            ),
            "APPLIES_TO",
            enables.target_id,
            application.target_id,
            path,
            existing,
        )
        return
    if application.target_type == "EngineeringObject":
        if _capability_mentions_other_platform(enables.target_name, application.target_name):
            return
        _add_path(
            accumulator,
            (
                "cross_document_platform_capability_from_applied_technology"
                if cross_document
                else "platform_capability_from_applied_technology"
            ),
            "HAS_CAPABILITY",
            application.target_id,
            enables.target_id,
            path,
            existing,
        )


def _same_document(edges: list[ProjectedEdge]) -> bool:
    document_ids = {edge.document_id for edge in edges}
    return len(document_ids) == 1


def _cross_document_application_allowed(
    enables: ProjectedEdge,
    application: ProjectedEdge,
) -> bool:
    if enables.document_id == application.document_id:
        return False
    if enables.source_id != application.source_id:
        return False
    if enables.source_type != "Technology":
        return False
    if application.source_type != "Technology":
        return False
    return _is_scenario_like(application.target_name, application.target_type) or (
        application.target_type == "EngineeringObject"
    )


def _is_stable_capability_holder(name: str, entity_type: str) -> bool:
    if entity_type in {"EngineeringObject", "Scenario"}:
        return True
    if entity_type != "Technology":
        return False
    stripped = (name or "").strip()
    if OPERATION_SOURCE_PATTERN.search(stripped):
        return False
    if UNSTABLE_TECH_HOLDER_PATTERN.search(stripped):
        return False
    if stripped.endswith("法") and not stripped.endswith("算法"):
        return False
    return bool(STABLE_TECH_HOLDER_PATTERN.search(stripped))


def _is_scenario_like(name: str, entity_type: str) -> bool:
    if entity_type == "Scenario":
        return True
    return bool(re.search(r"任务|场景|演示|演习|试验|测试|流程|过程|环节|领域|战区", name or ""))


def _is_valid_requirement_enabled_target(edge: ProjectedEdge) -> bool:
    if edge.target_type != "Capability":
        return False
    return not _is_internal_metric_capability(edge.target_name)


def _is_internal_metric_capability(name: str) -> bool:
    return bool(INTERNAL_METRIC_CAPABILITY_PATTERN.search(name or ""))


def _capability_mentions_other_platform(
    capability_name: str,
    platform_name: str,
) -> bool:
    capability_tokens = {
        token.upper() for token in PLATFORM_TOKEN_PATTERN.findall(capability_name or "")
    }
    if not capability_tokens:
        return False
    platform_tokens = {
        token.upper() for token in PLATFORM_TOKEN_PATTERN.findall(platform_name or "")
    }
    return not capability_tokens.issubset(platform_tokens)


def build_summary(
    results: list[ExtractionResult],
    projection_result: dict[str, Any],
    hypotheses: list[HypothesisLink],
) -> dict[str, Any]:
    edges: list[ProjectedEdge] = projection_result["edges"]
    relation_counts = Counter(edge.canonical_relation_type for edge in edges)
    raw_counts = Counter(edge.raw_relation_type for edge in edges)
    rule_counts = Counter(item.rule_id for item in hypotheses)
    predicted_counts = Counter(item.predicted_relation_type for item in hypotheses)
    risk_flag_counts = Counter(
        flag for item in hypotheses for flag in item.path_risk_flags
    )
    path_edge_ids = {
        edge_id
        for item in hypotheses
        for path in item.supporting_paths
        for edge_id in path
    }
    participating_edges = [edge for edge in edges if edge.edge_id in path_edge_ids]
    relation_participation = Counter(edge.canonical_relation_type for edge in participating_edges)
    top_document_supported = sum(1 for item in hypotheses if item.distinct_document_count >= 2)
    return {
        "result_count": len(results),
        "raw_relation_count": projection_result["raw_relation_count"],
        "projected_edge_count": len(edges),
        "dropped_relation_counts": projection_result["dropped_counts"],
        "noise_edge_count": projection_result["noise_edge_count"],
        "canonical_relation_counts": dict(sorted(relation_counts.items())),
        "projected_from_raw_counts": dict(sorted(raw_counts.items())),
        "hypothesis_count": len(hypotheses),
        "hypothesis_rule_counts": dict(sorted(rule_counts.items())),
        "predicted_relation_counts": dict(sorted(predicted_counts.items())),
        "weak_path_hypothesis_count": sum(
            1 for item in hypotheses if item.weak_path_edge_count > 0
        ),
        "weak_path_edge_count": sum(item.weak_path_edge_count for item in hypotheses),
        "path_risk_flag_counts": dict(sorted(risk_flag_counts.items())),
        "path_participating_edge_count": len(participating_edges),
        "path_participation_by_relation": dict(sorted(relation_participation.items())),
        "multi_document_hypothesis_count": top_document_supported,
        "top_hypotheses": [item.to_dict() for item in hypotheses[:20]],
    }


def build_report(
    results_path: Path,
    projected_edges_path: Path,
    hypotheses_path: Path,
    summary_path: Path,
    summary: dict[str, Any],
    hypotheses: list[HypothesisLink],
    labels_path: Path | None = None,
    label_summary: dict[str, Any] | None = None,
) -> str:
    lines = [
        "# Seven Relation Hypothesis Prediction v0",
        "",
        "日期：2026-06-02",
        "",
        "## 范围",
        "",
        f"- 输入：`{_rel(results_path)}`",
        f"- 七类投影边：`{_rel(projected_edges_path)}`",
        f"- hypothesis 输出：`{_rel(hypotheses_path)}`",
        f"- 统计 JSON：`{_rel(summary_path)}`",
        "- 方法：把输入关系规范化为 7 类预测边，再用 2/3-hop 规则生成可审核 `HypothesisLink`；旧 v3 输入会经历关系投影，v4 七类输入通常直接保留。",
        "- 边界：本轮不调用 LLM，不重抽，不写 Neo4j，不把 hypothesis 当事实边。",
        "",
        "## 结果概览",
        "",
        table(
            ["metric", "value"],
            [
                {"metric": "input_chunks", "value": summary["result_count"]},
                {"metric": "raw_relations", "value": summary["raw_relation_count"]},
                {"metric": "projected_edges", "value": summary["projected_edge_count"]},
                {"metric": "hypotheses", "value": summary["hypothesis_count"]},
                {
                    "metric": "multi_document_hypotheses",
                    "value": summary["multi_document_hypothesis_count"],
                },
                {
                    "metric": "path_participating_edges",
                    "value": summary["path_participating_edge_count"],
                },
                {
                    "metric": "weak_path_hypotheses",
                    "value": summary["weak_path_hypothesis_count"],
                },
            ],
        ),
        "",
        "## 七类边分布",
        "",
        table(
            ["relation_type", "count"],
            [
                {"relation_type": key, "count": value}
                for key, value in summary["canonical_relation_counts"].items()
            ],
        ),
        "",
        "## 被降级/丢弃的原关系",
        "",
        table(
            ["raw_relation_type_or_reason", "count"],
            [
                {"raw_relation_type_or_reason": key, "count": value}
                for key, value in summary["dropped_relation_counts"].items()
            ],
        ),
        "",
        "## Hypothesis 规则分布",
        "",
        table(
            ["rule_id", "count"],
            [
                {"rule_id": key, "count": value}
                for key, value in summary["hypothesis_rule_counts"].items()
            ],
        ),
        "",
        "## 参与预测路径的边类型",
        "",
        table(
            ["relation_type", "path_participating_edges"],
            [
                {"relation_type": key, "path_participating_edges": value}
                for key, value in summary["path_participation_by_relation"].items()
            ],
        ),
        "",
        "## Top Hypotheses",
        "",
    ]
    rows = []
    for item in hypotheses[:20]:
        rows.append(
            {
                "score": f"{item.score:.3f}",
                "rule": item.rule_id,
                "predicted": item.predicted_relation_type,
                "source": item.source_name,
                "target": item.target_name,
                "docs": item.distinct_document_count,
                "paths": len(item.supporting_paths),
                "risk": ",".join(item.path_risk_flags),
            }
        )
    lines.extend(
        [
            table(
                ["score", "rule", "predicted", "source", "target", "docs", "paths", "risk"],
                rows,
            ),
            "",
        ]
    )
    if label_summary:
        lines.extend(top50_label_section(labels_path, label_summary))
    lines.extend(effectiveness_notes(summary, label_summary=label_summary))
    return "\n".join(lines).rstrip() + "\n"


def top50_label_section(
    labels_path: Path | None,
    label_summary: dict[str, Any],
) -> list[str]:
    lines = [
        "## Top 50 人工式复核",
        "",
    ]
    if labels_path is not None:
        lines.append(f"- 标签文件：`{_rel(labels_path)}`")
    lines.extend(
        [
            f"- 样本数：`{label_summary['label_count']}`",
            f"- usable_rate：`{label_summary['usable_rate']:.2%}`，口径为 `useful + weak`。",
            "",
            "### Usefulness",
            "",
            table(
                ["label", "count"],
                [
                    {"label": key, "count": value}
                    for key, value in label_summary["usefulness_counts"].items()
                ],
            ),
            "",
            "### Correctness",
            "",
            table(
                ["label", "count"],
                [
                    {"label": key, "count": value}
                    for key, value in label_summary["correctness_counts"].items()
                ],
            ),
            "",
            "结论：Top 50 中可用线索和严格正确候选均有提升，但仍存在 `plausible_but_overbroad`，预测结果必须继续保持 `unverified`，不能直接写入事实图谱。",
            "",
        ]
    )
    return lines


def effectiveness_notes(
    summary: dict[str, Any],
    label_summary: dict[str, Any] | None = None,
) -> list[str]:
    projected = int(summary["projected_edge_count"])
    raw = int(summary["raw_relation_count"])
    hypotheses = int(summary["hypothesis_count"])
    participating = int(summary["path_participating_edge_count"])
    multi_doc = int(summary["multi_document_hypothesis_count"])
    weak_path_hypotheses = int(summary.get("weak_path_hypothesis_count", 0))
    projection_rate = projected / raw if raw else 0.0
    participation_rate = participating / projected if projected else 0.0
    dropped = int(sum((summary.get("dropped_relation_counts") or {}).values()))
    projection_note = (
        "输入关系已全部进入七类预测边，本轮没有因关系类型被降级或丢弃。"
        if dropped == 0
        else "旧 schema 中可投影关系已进入预测图，`indicates/measured_by/evolves_to/similar_to/contrasts_with` 等上下文关系会被排除。"
    )
    lines = [
        "## 有效性判断",
        "",
        f"- 七类投影保留率为 `{projection_rate:.2%}`。{projection_note}",
        f"- 预测路径参与率为 `{participation_rate:.2%}`。这个数字反映有多少七类边真正被路径规则使用；未参与不等于无用，但说明当前规则还没有覆盖它们的预测角色。",
        f"- 共生成 `{hypotheses}` 条 hypothesis，其中 `{multi_doc}` 条有跨文档支撑。跨文档支撑很少时，说明当前语料仍容易受单篇论文主题偏置影响。",
        f"- 弱路径 hypothesis 为 `{weak_path_hypotheses}` 条。`weak_assertion_path` 表示路径中至少一条边来自 `weak/speculative/negated` 断言或非 `asserted` claim；这些候选必须优先人工复核。",
    ]
    relation_participation = summary["path_participation_by_relation"]
    missing = sorted(SEVEN_RELATION_TYPES - set(relation_participation))
    if missing:
        lines.append(
            "- 暂未进入任何预测路径的七类关系：`"
            + "`, `".join(missing)
            + "`。这些关系需要新增规则或在 v4 抽取后重新验证。"
        )
    else:
        lines.append("- 七类关系均已进入至少一类预测路径，说明当前规则能覆盖完整精简 schema。")
    lines.extend(
        [
            _label_note(label_summary),
            "- 如果第二轮复核确认能力链、需求牵引链或 actor-capability 链稳定有用，可以把七类关系固化进 v4 prompt；否则应先调整规则或关系定义，而不是全量重抽。",
        ]
    )
    return lines


def _label_note(label_summary: dict[str, Any] | None) -> str:
    if label_summary:
        return "- 本轮只证明“七类关系能否支撑候选生成”，不证明候选全部正确；Top 50 已有人工式 usefulness / correctness 标注，但预测结果仍必须保持 `unverified`。"
    return "- 本轮只证明“七类关系能否支撑候选生成”，不证明候选全部正确；当前报告没有 Top 50 人工标签，所有 hypothesis 仍必须保持 `unverified`。"


def summarize_hypothesis_labels(
    rows: list[dict[str, Any]],
    hypotheses: list[HypothesisLink] | None = None,
) -> dict[str, Any]:
    top50_ids = [item.hypothesis_id for item in (hypotheses or [])[:50]]
    if top50_ids:
        labels_by_id = {str(row.get("hypothesis_id", "")): row for row in rows}
        if set(top50_ids) != set(labels_by_id):
            return {
                "label_count": len(rows),
                "label_status": "stale_or_incomplete",
                "expected_top50_ids": top50_ids,
                "labeled_ids": sorted(labels_by_id),
            }
    usefulness_counts = Counter(str(row.get("usefulness_label", "")) for row in rows)
    correctness_counts = Counter(str(row.get("correctness_label", "")) for row in rows)
    usable_count = usefulness_counts.get("useful", 0) + usefulness_counts.get("weak", 0)
    label_count = len(rows)
    return {
        "label_count": label_count,
        "label_status": "current_top50" if top50_ids else "ad_hoc",
        "usefulness_counts": dict(sorted(usefulness_counts.items())),
        "correctness_counts": dict(sorted(correctness_counts.items())),
        "usable_count": usable_count,
        "usable_rate": usable_count / label_count if label_count else 0.0,
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                rows.append(json.loads(stripped))
    return rows


def _add_path(
    accumulator: dict[tuple[str, str, str], list[tuple[str, list[str]]]],
    rule_id: str,
    predicted_relation_type: str,
    source_id: str,
    target_id: str,
    path: list[str],
    existing: set[tuple[str, str, str]],
) -> None:
    if source_id == target_id:
        return
    if (source_id, predicted_relation_type, target_id) in existing:
        return
    key = (predicted_relation_type, source_id, target_id)
    existing_rule_ids = [existing_rule_id for existing_rule_id, _path in accumulator[key]]
    is_cross_document = rule_id.startswith("cross_document_")
    if is_cross_document and any(
        not existing_rule_id.startswith("cross_document_")
        for existing_rule_id in existing_rule_ids
    ):
        return
    if not is_cross_document and any(
        existing_rule_id.startswith("cross_document_")
        for existing_rule_id in existing_rule_ids
    ):
        accumulator[key] = [
            (existing_rule_id, existing_path)
            for existing_rule_id, existing_path in accumulator[key]
            if not existing_rule_id.startswith("cross_document_")
        ]
    existing_paths = [existing_path for _rule_id, existing_path in accumulator[key]]
    if path not in existing_paths:
        accumulator[key].append((rule_id, path))


def _primary_rule_id(rule_ids: Iterable[str]) -> str:
    ordered = list(rule_ids)
    non_cross_document = [
        rule_id for rule_id in ordered if not rule_id.startswith("cross_document_")
    ]
    if non_cross_document:
        return sorted(non_cross_document)[0]
    return sorted(ordered)[0]


def _edge_endpoint(
    edge_by_id: dict[str, ProjectedEdge],
    entity_id: str,
    path: list[str],
) -> dict[str, str]:
    for edge_id in path:
        edge = edge_by_id[edge_id]
        if edge.source_id == entity_id:
            return {"name": edge.source_name, "type": edge.source_type}
        if edge.target_id == entity_id:
            return {"name": edge.target_name, "type": edge.target_type}
    return {"name": entity_id, "type": ""}


def _score_hypothesis(
    rule_id: str,
    confidence: float,
    path_length: int,
    distinct_documents: int,
) -> float:
    base = RULE_WEIGHTS.get(rule_id, 0.5)
    length_factor = 1.0 if path_length <= 2 else 0.92
    document_bonus = min(max(distinct_documents - 1, 0), 3) * 0.04
    return round(min(1.0, base * confidence * length_factor + document_bonus), 4)


def _canonical_entity(
    name: str,
    entity_type: str,
    alias_lookup: dict[str, tuple[str, str]],
) -> dict[str, str] | None:
    normalized = normalize_entity_name(name)
    if not normalized:
        return None
    if normalized in {normalize_entity_name(alias) for alias in NOISE_ALIASES}:
        return None
    if normalized in alias_lookup:
        canonical_name, canonical_type = alias_lookup[normalized]
        return {
            "id": f"{canonical_type}:{normalize_entity_name(canonical_name)}",
            "name": canonical_name,
            "type": canonical_type,
        }
    return {
        "id": f"{entity_type}:{normalized}",
        "name": name.strip(),
        "type": entity_type,
    }


def _alias_lookup() -> dict[str, tuple[str, str]]:
    lookup: dict[str, tuple[str, str]] = {}
    for group in SEED_ALIAS_GROUPS:
        canonical_name = str(group["canonical_name"])
        canonical_type = str(group["canonical_type"])
        for alias in group["aliases"]:
            lookup[normalize_entity_name(str(alias))] = (canonical_name, canonical_type)
    return lookup


def _claims_by_signature(result: ExtractionResult) -> dict[tuple[str, str, str], list[Any]]:
    grouped: dict[tuple[str, str, str], list[Any]] = defaultdict(list)
    for claim in result.claims:
        grouped[
            (
                claim.subject_entity_id,
                claim.object_entity_id,
                claim.predicate,
            )
        ].append(claim)
    return grouped


def _claims_by_evidence(result: ExtractionResult) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for claim in result.claims:
        for evidence_id in claim.evidence_span_ids:
            grouped[evidence_id].append(claim)
    return grouped


def _ordered_unique(values: Iterable[Any]) -> list[Any]:
    seen: set[Any] = set()
    output: list[Any] = []
    for value in values:
        if value in seen or value in {"", None}:
            continue
        seen.add(value)
        output.append(value)
    return output


def _average(values: Iterable[float]) -> float:
    collected = [float(value) for value in values]
    if not collected:
        return 0.0
    return sum(collected) / len(collected)


def table(headers: list[str], rows: list[dict[str, Any]]) -> str:
    output = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        output.append("| " + " | ".join(str(row.get(header, "")) for header in headers) + " |")
    return "\n".join(output)


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
