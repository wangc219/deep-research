"""知识图谱金标评测、阈值校准与 Pilot 验收门禁。"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from .gold_contract import GoldDocument
from .graph_retrieval_quality import GRAPH_RETRIEVAL_QUALITY_CRITERIA, graph_retrieval_quality_gate
from .innovation_quality import INNOVATION_ACCEPTANCE_CRITERIA, innovation_quality_gate
from .pilot_requirements import PILOT_GRAPH_QUOTAS, PILOT_QUOTAS
from .retrieval_comparison import RETRIEVAL_ACCEPTANCE_CRITERIA, retrieval_comparison_gate

EXPECTED_GOLD_SPLITS = {"train": 210, "dev": 30, "test": 60}
MINIMUM_AUTO_ACCEPT_PRECISION = 0.90
PILOT_ACCEPTANCE_CONTRACT = "defense-kg-pilot-acceptance-v5"
AUTHORITATIVE_ACCEPTANCE_SNAPSHOT_CONTRACT = "defense-kg-authoritative-acceptance-snapshot-v2"
BASE_ACCEPTANCE_CRITERIA = frozenset(
    {
        "gold_dataset",
        "source_documents",
        "paper_documents",
        "patent_documents",
        "documents_with_build_runs",
        "accepted_entities",
        "accepted_relations",
        "relation_count_semantics",
        "entity_precision",
        "entity_f1",
        "relation_precision",
        "relation_f1",
        "alignment_accuracy",
        "evidence_span_rebuild",
        "evidence_completeness",
        "dynamic_update_verified",
        "multi_hop_query_verified",
        "evolution_analysis_verified",
        "innovation_integration_verified",
        "api_contract_verified",
        "reproducible_report_verified",
    }
)
PILOT_ACCEPTANCE_CRITERIA = (
    BASE_ACCEPTANCE_CRITERIA
    | RETRIEVAL_ACCEPTANCE_CRITERIA
    | GRAPH_RETRIEVAL_QUALITY_CRITERIA
    | INNOVATION_ACCEPTANCE_CRITERIA
)


class PredictionEntity(BaseModel):
    entity_id: str = Field(min_length=1, max_length=128)
    block_id: str = Field(min_length=1, max_length=128)
    type: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=512)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    confidence: float = Field(ge=0, le=1)
    canonical_entity_id: str | None = Field(default=None, max_length=128)
    review_status: Literal["pending", "accepted", "rejected", "disputed", "superseded"] = "pending"

    @model_validator(mode="after")
    def validate_span(self):
        if self.end <= self.start:
            raise ValueError("预测实体 end 必须大于 start")
        return self


class PredictionEvidenceSpan(BaseModel):
    block_id: str = Field(min_length=1, max_length=128)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    text: str | None = None

    @model_validator(mode="after")
    def validate_span(self):
        if self.end <= self.start:
            raise ValueError("预测证据 end 必须大于 start")
        return self


class PredictionRelation(BaseModel):
    relation_id: str = Field(min_length=1, max_length=128)
    type: str = Field(min_length=1, max_length=256)
    source_entity_id: str = Field(min_length=1, max_length=128)
    target_entity_id: str = Field(min_length=1, max_length=128)
    confidence: float = Field(ge=0, le=1)
    evidence_spans: list[PredictionEvidenceSpan] = Field(default_factory=list)
    applicable_conditions: list[str] = Field(default_factory=list, max_length=20)
    claim_level: Literal["Fact", "Inference", "Hypothesis"] = "Fact"
    review_status: Literal["pending", "accepted", "rejected", "disputed", "superseded"] = "pending"


class PredictionDocument(BaseModel):
    document_id: str = Field(min_length=1, max_length=128)
    pipeline_revision: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=256)
    entities: list[PredictionEntity] = Field(default_factory=list)
    relations: list[PredictionRelation] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self):
        entity_ids = [entity.entity_id for entity in self.entities]
        if len(entity_ids) != len(set(entity_ids)):
            raise ValueError("同一预测文档 entity_id 必须唯一")
        relation_ids = [relation.relation_id for relation in self.relations]
        if len(relation_ids) != len(set(relation_ids)):
            raise ValueError("同一预测文档 relation_id 必须唯一")
        known_entities = set(entity_ids)
        for relation in self.relations:
            if relation.source_entity_id not in known_entities or relation.target_entity_id not in known_entities:
                raise ValueError(f"预测关系 {relation.relation_id} 引用了不存在的实体")
        return self


class PilotBuildStats(BaseModel):
    source_documents: int = Field(ge=0)
    paper_documents: int = Field(ge=0)
    patent_documents: int = Field(ge=0)
    documents_with_build_runs: int = Field(ge=0)
    accepted_entities: int = Field(ge=0)
    accepted_relations: int = Field(ge=0)
    duplicate_relation_mentions_excluded: bool = False
    unreviewed_hypotheses_excluded: bool = False


def load_prediction_jsonl(path: str | Path) -> list[PredictionDocument]:
    """加载模型预测 JSONL，并拒绝文档重复和不完整引用。"""
    documents = []
    document_ids = set()
    with Path(path).open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                document = PredictionDocument.model_validate_json(line)
            except Exception as exc:
                raise ValueError(f"预测 JSONL 第 {line_number} 行无效: {exc}") from exc
            if document.document_id in document_ids:
                raise ValueError(f"预测文档 {document.document_id} 重复出现")
            document_ids.add(document.document_id)
            documents.append(document)
    if not documents:
        raise ValueError("预测 JSONL 不能为空")
    return documents


def audit_gold_dataset(
    documents: list[GoldDocument],
    *,
    expected_splits: dict[str, int] | None = None,
    require_pilot_provenance: bool = True,
) -> dict[str, Any]:
    """审计文档级切分、双标仲裁、标准实体和证据 Span。"""
    expected = expected_splits or EXPECTED_GOLD_SPLITS
    split_counts = Counter(document.split for document in documents)
    errors = []
    document_ids = [document.document_id for document in documents]
    if len(document_ids) != len(set(document_ids)):
        errors.append("document_id 不是全局唯一，存在跨集合泄漏")
    for split, expected_count in expected.items():
        actual = split_counts.get(split, 0)
        if actual != expected_count:
            errors.append(f"{split} 文档数应为 {expected_count}，实际为 {actual}")

    entity_count = 0
    relation_count = 0
    for document in documents:
        entity_count += len(document.entities)
        relation_count += len(document.relations)
        entity_keys = [_gold_entity_key(document.document_id, entity) for entity in document.entities]
        if len(entity_keys) != len(set(entity_keys)):
            errors.append(f"文档 {document.document_id} 存在重复严格实体 Span+类型")
        entity_key_by_id = {
            entity.entity_id: _gold_entity_key(document.document_id, entity) for entity in document.entities
        }
        relation_keys = [
            (
                relation.type,
                entity_key_by_id[relation.source_entity_id],
                entity_key_by_id[relation.target_entity_id],
            )
            for relation in document.relations
        ]
        if len(relation_keys) != len(set(relation_keys)):
            errors.append(f"文档 {document.document_id} 存在重复端点+类型+方向关系")
        if require_pilot_provenance:
            annotation = document.annotation
            if annotation is None:
                errors.append(f"文档 {document.document_id} 缺少标注来源")
            elif annotation.review_mode == "dual_model_expert":
                if len(annotation.model_prelabel_ids) < 2:
                    errors.append(f"文档 {document.document_id} 缺少两路独立模型预标来源")
                if annotation.expert_review_scope != "all_candidates":
                    errors.append(f"文档 {document.document_id} 的模型辅助 Gold 未经专家全量审核")
            elif len(annotation.annotator_ids) < 2:
                errors.append(f"文档 {document.document_id} 缺少两名独立标注人")
            if annotation is None or not annotation.adjudicated or not annotation.arbitrator_id:
                errors.append(f"文档 {document.document_id} 缺少专家仲裁记录")
            if annotation is None or not annotation.guideline_version:
                errors.append(f"文档 {document.document_id} 缺少标注规范版本")
            if not document.domain:
                errors.append(f"文档 {document.document_id} 缺少分层抽样领域")
            if document.source_type not in {"paper", "patent"}:
                errors.append(f"文档 {document.document_id} 来源类型不是 paper/patent")
            for entity in document.entities:
                if not entity.canonical_entity_id:
                    errors.append(f"实体 {document.document_id}/{entity.entity_id} 缺少标准实体 ID")
            for relation in document.relations:
                if relation.claim_level == "Fact" and not relation.evidence_spans:
                    errors.append(f"Fact 关系 {document.document_id}/{relation.relation_id} 缺少证据 Span")

    sealed_test_documents = {
        document.document_id: _document_sha256(document)
        for document in sorted(documents, key=lambda item: item.document_id)
        if document.split == "test"
    }
    return {
        "contract_version": "platform-gold-jsonl-v2",
        "document_count": len(documents),
        "entity_count": entity_count,
        "relation_count": relation_count,
        "split_counts": {split: split_counts.get(split, 0) for split in ("train", "dev", "test")},
        "expected_splits": expected,
        "sealed_test_documents": sealed_test_documents,
        "sealed_test_manifest_sha256": _canonical_sha256(sealed_test_documents),
        "pilot_ready": not errors,
        "errors": errors,
    }


def evaluate_ie_predictions(
    gold_documents: list[GoldDocument],
    prediction_documents: list[PredictionDocument],
) -> dict[str, Any]:
    """按文档严格计算实体、关系、对齐和证据指标。"""
    gold_by_id = _unique_documents(gold_documents, "金标")
    predictions_by_id = _unique_documents(prediction_documents, "预测")
    missing_predictions = sorted(set(gold_by_id) - set(predictions_by_id))
    unexpected_predictions = sorted(set(predictions_by_id) - set(gold_by_id))

    gold_entity_keys = []
    predicted_entity_keys = []
    gold_relation_keys = []
    predicted_relation_keys = []
    alignment_total = 0
    alignment_correct = 0
    accepted_items = 0
    accepted_items_with_evidence = 0
    evidence_span_total = 0
    evidence_span_valid = 0

    for document_id, gold in gold_by_id.items():
        prediction = predictions_by_id.get(document_id)
        gold_entities = {entity.entity_id: entity for entity in gold.entities}
        gold_keys_for_document = {entity.entity_id: _gold_entity_key(document_id, entity) for entity in gold.entities}
        gold_entity_keys.extend(gold_keys_for_document.values())
        gold_relation_keys.extend(
            (
                document_id,
                relation.type,
                gold_keys_for_document[relation.source_entity_id],
                gold_keys_for_document[relation.target_entity_id],
            )
            for relation in gold.relations
        )
        if prediction is None:
            alignment_total += sum(bool(entity.canonical_entity_id) for entity in gold.entities)
            continue

        predicted_entities = {entity.entity_id: entity for entity in prediction.entities}
        predicted_keys_for_document = {
            entity.entity_id: _prediction_entity_key(document_id, entity) for entity in prediction.entities
        }
        predicted_entity_keys.extend(predicted_keys_for_document.values())
        predicted_relation_keys.extend(
            (
                document_id,
                relation.type,
                predicted_keys_for_document[relation.source_entity_id],
                predicted_keys_for_document[relation.target_entity_id],
            )
            for relation in prediction.relations
        )

        predictions_by_key: dict[tuple[Any, ...], list[PredictionEntity]] = defaultdict(list)
        for entity in prediction.entities:
            predictions_by_key[_prediction_entity_key(document_id, entity)].append(entity)
            if entity.review_status == "accepted":
                accepted_items += 1
                if _prediction_entity_span_valid(entity, gold):
                    accepted_items_with_evidence += 1
                    evidence_span_valid += 1
                evidence_span_total += 1
        for gold_entity in gold.entities:
            if not gold_entity.canonical_entity_id:
                continue
            alignment_total += 1
            matches = predictions_by_key.get(_gold_entity_key(document_id, gold_entity), [])
            if any(item.canonical_entity_id == gold_entity.canonical_entity_id for item in matches):
                alignment_correct += 1

        for relation in prediction.relations:
            if relation.review_status != "accepted" or relation.claim_level != "Fact":
                continue
            accepted_items += 1
            valid_spans = [_prediction_evidence_span_valid(span, gold) for span in relation.evidence_spans]
            evidence_span_total += max(1, len(valid_spans))
            evidence_span_valid += sum(valid_spans)
            if valid_spans and all(valid_spans):
                accepted_items_with_evidence += 1

        if set(predicted_entities) != set(predicted_keys_for_document):
            raise AssertionError("预测实体索引不一致")
        if set(gold_entities) != set(gold_keys_for_document):
            raise AssertionError("金标实体索引不一致")

    for document_id in unexpected_predictions:
        prediction = predictions_by_id[document_id]
        predicted_keys_for_document = {
            entity.entity_id: _prediction_entity_key(document_id, entity) for entity in prediction.entities
        }
        predicted_entity_keys.extend(predicted_keys_for_document.values())
        predicted_relation_keys.extend(
            (
                document_id,
                relation.type,
                predicted_keys_for_document[relation.source_entity_id],
                predicted_keys_for_document[relation.target_entity_id],
            )
            for relation in prediction.relations
        )

    return {
        "evaluation_contract": "defense-kg-strict-eval-v1",
        "entity": _micro_prf(gold_entity_keys, predicted_entity_keys),
        "relation": _micro_prf(gold_relation_keys, predicted_relation_keys),
        "alignment": {
            "correct": alignment_correct,
            "total": alignment_total,
            "accuracy": _safe_divide(alignment_correct, alignment_total),
        },
        "evidence": {
            "valid_spans": evidence_span_valid,
            "total_spans": evidence_span_total,
            "span_rebuild_rate": _safe_divide(evidence_span_valid, evidence_span_total),
            "accepted_items_with_evidence": accepted_items_with_evidence,
            "accepted_items": accepted_items,
            "completeness": _safe_divide(accepted_items_with_evidence, accepted_items),
        },
        "coverage": {
            "gold_documents": len(gold_documents),
            "prediction_documents": len(prediction_documents),
            "missing_prediction_document_ids": missing_predictions,
            "unexpected_prediction_document_ids": unexpected_predictions,
        },
    }


def calibrate_acceptance_policy(
    gold_documents: list[GoldDocument],
    prediction_documents: list[PredictionDocument],
    *,
    pipeline_revision: str,
    profile_version: str = "defense-pilot-v1",
    minimum_precision: float = MINIMUM_AUTO_ACCEPT_PRECISION,
) -> dict[str, Any]:
    """仅使用 dev 集选择满足 Precision 门槛且召回最大的分类型阈值。"""
    if not 0.90 <= minimum_precision <= 1:
        raise ValueError("自动接受 minimum_precision 不得低于 0.90")
    dev_gold = [document for document in gold_documents if document.split == "dev"]
    dev_ids = {document.document_id for document in dev_gold}
    dev_predictions = [document for document in prediction_documents if document.document_id in dev_ids]
    if not dev_gold:
        raise ValueError("校准必须包含 dev 文档")
    if not dev_predictions:
        raise ValueError("校准必须包含 dev 预测")

    entity_rows, relation_rows = _calibration_rows(dev_gold, dev_predictions)
    entity_result = _calibrate_rows(entity_rows, minimum_precision)
    relation_result = _calibrate_rows(relation_rows, minimum_precision)
    calibrated = entity_result["ready"] and relation_result["ready"]
    return {
        "profile_version": profile_version,
        "pipeline_revision": pipeline_revision,
        "calibrated_pipeline_revision": pipeline_revision if calibrated else None,
        "calibrated": calibrated,
        "entity_precision": entity_result["precision"] if calibrated else None,
        "relation_precision": relation_result["precision"] if calibrated else None,
        "minimum_precision": minimum_precision,
        "entity_default_threshold": 1.0,
        "relation_default_threshold": 1.0,
        "entity_thresholds": entity_result["thresholds"],
        "relation_thresholds": relation_result["thresholds"],
        "calibrated_entity_types": sorted(entity_result["thresholds"]),
        "calibrated_relation_types": sorted(relation_result["thresholds"]),
        "auto_accept_enabled": calibrated,
        "fuse_state": "closed",
        "fuse_reason": "",
        "calibration_report": {
            "split": "dev",
            "document_ids": sorted(dev_ids),
            "entity": entity_result,
            "relation": relation_result,
        },
    }


def assess_pilot_acceptance(
    *,
    gold_audit: dict[str, Any],
    sealed_test_metrics: dict[str, Any],
    build_stats: PilotBuildStats | dict[str, Any],
    operational_checks: dict[str, bool] | None = None,
    retrieval_comparison: dict[str, Any] | None = None,
    graph_retrieval_quality: dict[str, Any] | None = None,
    innovation_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """按 DOCX 和实施计划生成不可跳过的综合验收结论。"""
    stats = build_stats if isinstance(build_stats, PilotBuildStats) else PilotBuildStats.model_validate(build_stats)
    checks = operational_checks or {}
    criteria = [
        _criterion("gold_dataset", bool(gold_audit.get("pilot_ready")), "300 篇双标金标及 210/30/60 密封切分"),
        _criterion(
            "source_documents",
            stats.source_documents >= PILOT_QUOTAS["source_documents"],
            f"来源文档不少于 {PILOT_QUOTAS['source_documents']}",
            stats.source_documents,
        ),
        _criterion(
            "paper_documents",
            stats.paper_documents >= PILOT_QUOTAS["paper_documents"],
            f"论文不少于 {PILOT_QUOTAS['paper_documents']}",
            stats.paper_documents,
        ),
        _criterion(
            "patent_documents",
            stats.patent_documents >= PILOT_QUOTAS["patent_documents"],
            f"专利不少于 {PILOT_QUOTAS['patent_documents']}",
            stats.patent_documents,
        ),
        _criterion(
            "documents_with_build_runs",
            stats.documents_with_build_runs >= stats.source_documents >= PILOT_QUOTAS["source_documents"],
            "全部来源具有构建运行记录",
            stats.documents_with_build_runs,
        ),
        _criterion(
            "accepted_entities",
            stats.accepted_entities >= PILOT_GRAPH_QUOTAS["accepted_entities"],
            f"标准实体不少于 {PILOT_GRAPH_QUOTAS['accepted_entities']}",
            stats.accepted_entities,
        ),
        _criterion(
            "accepted_relations",
            stats.accepted_relations >= PILOT_GRAPH_QUOTAS["accepted_relations"],
            f"有效关系不少于 {PILOT_GRAPH_QUOTAS['accepted_relations']}",
            stats.accepted_relations,
        ),
        _criterion(
            "relation_count_semantics",
            stats.duplicate_relation_mentions_excluded and stats.unreviewed_hypotheses_excluded,
            "关系规模排除重复 mention 和未审核 Hypothesis",
        ),
        _metric_criterion("entity_precision", sealed_test_metrics, "entity", "precision", 0.85),
        _metric_criterion("entity_f1", sealed_test_metrics, "entity", "f1", 0.85),
        _metric_criterion("relation_precision", sealed_test_metrics, "relation", "precision", 0.80),
        _metric_criterion("relation_f1", sealed_test_metrics, "relation", "f1", 0.80),
        _metric_criterion("alignment_accuracy", sealed_test_metrics, "alignment", "accuracy", 0.85),
        _metric_criterion("evidence_span_rebuild", sealed_test_metrics, "evidence", "span_rebuild_rate", 1.0),
        _metric_criterion("evidence_completeness", sealed_test_metrics, "evidence", "completeness", 0.95),
    ]
    for name in (
        "dynamic_update_verified",
        "multi_hop_query_verified",
        "evolution_analysis_verified",
        "innovation_integration_verified",
        "api_contract_verified",
        "reproducible_report_verified",
    ):
        criteria.append(_criterion(name, checks.get(name) is True, f"运行验收项 {name}"))
    criteria.extend(retrieval_comparison_gate(retrieval_comparison))
    criteria.extend(graph_retrieval_quality_gate(graph_retrieval_quality))
    criteria.extend(innovation_quality_gate(innovation_quality))
    criterion_ids = [item["id"] for item in criteria]
    if len(criterion_ids) != len(set(criterion_ids)) or set(criterion_ids) != PILOT_ACCEPTANCE_CRITERIA:
        raise AssertionError("Pilot 验收项与模块声明不一致")
    return {
        "acceptance_contract": PILOT_ACCEPTANCE_CONTRACT,
        "passed": all(item["passed"] for item in criteria),
        "criteria": criteria,
        "failed_criteria": [item["id"] for item in criteria if not item["passed"]],
    }


def validate_pilot_acceptance_report(report: dict[str, Any]) -> None:
    """校验正式 Pilot 报告结构、完整性及通过结论自洽性。"""
    if report.get("acceptance_contract") != PILOT_ACCEPTANCE_CONTRACT:
        raise ValueError("report 不是受支持的 Pilot 验收契约")
    criteria = report.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise ValueError("report.criteria 必须是非空数组")

    criterion_ids = []
    failed_criteria = []
    for item in criteria:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("每个验收 criterion 必须包含字符串 id")
        if not isinstance(item.get("passed"), bool):
            raise ValueError(f"验收 criterion {item['id']} 缺少布尔 passed")
        criterion_ids.append(item["id"])
        if not item["passed"]:
            failed_criteria.append(item["id"])

    if len(criterion_ids) != len(set(criterion_ids)):
        raise ValueError("report.criteria 存在重复 id")
    actual_criteria = set(criterion_ids)
    if actual_criteria != PILOT_ACCEPTANCE_CRITERIA:
        missing = sorted(PILOT_ACCEPTANCE_CRITERIA - actual_criteria)
        unexpected = sorted(actual_criteria - PILOT_ACCEPTANCE_CRITERIA)
        raise ValueError(f"report.criteria 不完整，缺少 {missing}，未知 {unexpected}")
    if report.get("failed_criteria") != failed_criteria:
        raise ValueError("report.failed_criteria 与 criteria 不一致")
    if report.get("passed") != (not failed_criteria):
        raise ValueError("report.passed 与 criteria 不一致")


def validate_pilot_build_stats_consistency(report: dict[str, Any], stats: dict[str, Any]) -> None:
    """校验验收报告规模与 PostgreSQL 权威统计及固定阈值一致。"""
    validate_pilot_acceptance_report(report)
    criteria = {item["id"]: item for item in report["criteria"]}
    for criterion_id in (
        "source_documents",
        "paper_documents",
        "patent_documents",
        "documents_with_build_runs",
        "accepted_entities",
        "accepted_relations",
    ):
        if criteria[criterion_id].get("actual") != stats.get(criterion_id):
            raise ValueError(f"report {criterion_id} 与 PostgreSQL 当前权威统计不一致")

    expected_pass = {
        "source_documents": stats.get("source_documents", 0) >= PILOT_QUOTAS["source_documents"],
        "paper_documents": stats.get("paper_documents", 0) >= PILOT_QUOTAS["paper_documents"],
        "patent_documents": stats.get("patent_documents", 0) >= PILOT_QUOTAS["patent_documents"],
        "documents_with_build_runs": (
            stats.get("documents_with_build_runs", 0)
            >= stats.get("source_documents", 0)
            >= PILOT_QUOTAS["source_documents"]
        ),
        "accepted_entities": stats.get("accepted_entities", 0) >= PILOT_GRAPH_QUOTAS["accepted_entities"],
        "accepted_relations": stats.get("accepted_relations", 0) >= PILOT_GRAPH_QUOTAS["accepted_relations"],
    }
    for criterion_id, passed in expected_pass.items():
        if criteria[criterion_id]["passed"] != passed:
            raise ValueError(f"report {criterion_id} 结论与技术要求阈值不一致")

    relation_semantics = bool(
        stats.get("duplicate_relation_mentions_excluded") and stats.get("unreviewed_hypotheses_excluded")
    )
    if criteria["relation_count_semantics"]["passed"] != relation_semantics:
        raise ValueError("report relation_count_semantics 与 PostgreSQL 当前统计口径不一致")


def _calibration_rows(
    gold_documents: list[GoldDocument],
    prediction_documents: list[PredictionDocument],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    gold_by_id = _unique_documents(gold_documents, "金标")
    prediction_by_id = _unique_documents(prediction_documents, "预测")
    entity_rows = []
    relation_rows = []
    for document_id, gold in gold_by_id.items():
        prediction = prediction_by_id.get(document_id)
        if prediction is None:
            continue
        gold_entity_counter = Counter(_gold_entity_key(document_id, entity) for entity in gold.entities)
        gold_entity_by_id = {entity.entity_id: _gold_entity_key(document_id, entity) for entity in gold.entities}
        gold_relation_counter = Counter(
            (
                document_id,
                relation.type,
                gold_entity_by_id[relation.source_entity_id],
                gold_entity_by_id[relation.target_entity_id],
            )
            for relation in gold.relations
        )
        prediction_entity_by_id = {
            entity.entity_id: _prediction_entity_key(document_id, entity) for entity in prediction.entities
        }
        for entity in sorted(prediction.entities, key=lambda item: (-item.confidence, item.entity_id)):
            key = prediction_entity_by_id[entity.entity_id]
            correct = gold_entity_counter[key] > 0
            if correct:
                gold_entity_counter[key] -= 1
            entity_rows.append({"label": entity.type, "confidence": entity.confidence, "correct": correct})
        for relation in sorted(prediction.relations, key=lambda item: (-item.confidence, item.relation_id)):
            key = (
                document_id,
                relation.type,
                prediction_entity_by_id[relation.source_entity_id],
                prediction_entity_by_id[relation.target_entity_id],
            )
            correct = gold_relation_counter[key] > 0
            if correct:
                gold_relation_counter[key] -= 1
            relation_rows.append({"label": relation.type, "confidence": relation.confidence, "correct": correct})
    return entity_rows, relation_rows


def _calibrate_rows(rows: list[dict[str, Any]], minimum_precision: float) -> dict[str, Any]:
    by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_label[row["label"]].append(row)
    thresholds = {}
    label_stats = {}
    unmet_labels = []
    selected_rows = []
    for label, label_rows in sorted(by_label.items()):
        candidates = []
        for threshold in sorted({float(row["confidence"]) for row in label_rows}):
            selected = [row for row in label_rows if row["confidence"] >= threshold]
            tp = sum(bool(row["correct"]) for row in selected)
            precision = _safe_divide(tp, len(selected))
            if selected and precision >= minimum_precision:
                candidates.append((tp, precision, -threshold, threshold, selected))
        if not candidates:
            unmet_labels.append(label)
            label_stats[label] = {
                "ready": False,
                "candidate_count": len(label_rows),
                "correct_count": sum(bool(row["correct"]) for row in label_rows),
            }
            continue
        _, precision, _, threshold, selected = max(candidates, key=lambda item: item[:3])
        thresholds[label] = threshold
        selected_rows.extend(selected)
        label_stats[label] = {
            "ready": True,
            "threshold": threshold,
            "precision": precision,
            "accepted_count": len(selected),
            "true_positive_count": sum(bool(row["correct"]) for row in selected),
        }
    true_positives = sum(bool(row["correct"]) for row in selected_rows)
    precision = _safe_divide(true_positives, len(selected_rows))
    return {
        "ready": bool(rows) and bool(selected_rows) and not unmet_labels and precision >= minimum_precision,
        "precision": precision,
        "candidate_count": len(rows),
        "accepted_count": len(selected_rows),
        "true_positive_count": true_positives,
        "thresholds": thresholds,
        "unmet_labels": unmet_labels,
        "labels": label_stats,
    }


def _micro_prf(gold_keys: list[tuple[Any, ...]], predicted_keys: list[tuple[Any, ...]]) -> dict[str, Any]:
    gold_counter = Counter(gold_keys)
    predicted_counter = Counter(predicted_keys)
    true_positive = sum(min(count, predicted_counter[key]) for key, count in gold_counter.items())
    false_positive = len(predicted_keys) - true_positive
    false_negative = len(gold_keys) - true_positive
    precision = _safe_divide(true_positive, true_positive + false_positive)
    recall = _safe_divide(true_positive, true_positive + false_negative)
    return {
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "precision": precision,
        "recall": recall,
        "f1": _safe_divide(2 * precision * recall, precision + recall),
    }


def _gold_entity_key(document_id: str, entity) -> tuple[Any, ...]:
    return (document_id, entity.block_id, entity.start, entity.end, entity.type)


def _prediction_entity_key(document_id: str, entity: PredictionEntity) -> tuple[Any, ...]:
    return (document_id, entity.block_id, entity.start, entity.end, entity.type)


def _prediction_entity_span_valid(entity: PredictionEntity, gold: GoldDocument) -> bool:
    block = next((item for item in gold.blocks if item.block_id == entity.block_id), None)
    return bool(block and entity.end <= len(block.text) and block.text[entity.start : entity.end] == entity.text)


def _prediction_evidence_span_valid(span: PredictionEvidenceSpan, gold: GoldDocument) -> bool:
    block = next((item for item in gold.blocks if item.block_id == span.block_id), None)
    if block is None or span.end > len(block.text):
        return False
    evidence_text = block.text[span.start : span.end]
    return bool(evidence_text and (span.text is None or span.text == evidence_text))


def _unique_documents(documents: list[Any], label: str) -> dict[str, Any]:
    result = {}
    for document in documents:
        if document.document_id in result:
            raise ValueError(f"{label}文档 {document.document_id} 重复出现")
        result[document.document_id] = document
    return result


def _criterion(identifier: str, passed: bool, description: str, actual: Any = None) -> dict[str, Any]:
    return {"id": identifier, "passed": bool(passed), "description": description, "actual": actual}


def _metric_criterion(
    identifier: str,
    metrics: dict[str, Any],
    section: str,
    field: str,
    minimum: float,
) -> dict[str, Any]:
    actual = metrics.get(section, {}).get(field)
    return {
        "id": identifier,
        "passed": isinstance(actual, int | float) and math.isfinite(actual) and actual >= minimum,
        "description": f"{section}.{field} 不低于 {minimum:.2f}",
        "actual": actual,
        "minimum": minimum,
    }


def _safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _document_sha256(document: GoldDocument) -> str:
    return _canonical_sha256(document.model_dump(mode="json"))


def _canonical_sha256(payload: Any) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
