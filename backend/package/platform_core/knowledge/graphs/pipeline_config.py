"""图谱抽取流水线的版本快照与配置规范化。"""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

from platform_core.knowledge.graphs.acceptance_policy import normalize_acceptance_policy
from platform_core.knowledge.graphs.defense_ontology import DEFENSE_ONTOLOGY_V1, ontology_payload
from platform_core.knowledge.graphs.lightrag_contract import LIGHTRAG_ENHANCEMENT_REVISION
from platform_core.knowledge.graphs.lightrag_adaptive_routing import normalize_adaptive_routing_options
from platform_core.knowledge.graphs.lightrag_relation_completion import normalize_relation_completion_options
from platform_core.knowledge.graphs.ontology_versioning import normalize_ontology_definition

IE_EXTRACTOR_TYPES = frozenset({"lightrag_primary"})
DEFAULT_PIPELINE_REVISION = "lightrag-primary-v1"
ORCHESTRATION_RELEASE_CHANNELS = frozenset({"stable", "experiment"})
REMOVED_LIGHTRAG_LOCAL_PROVIDER_IDS = frozenset({"local-lightrag", "local-lightrag-eval"})
LIGHTWEIGHT_RAG_ONLY_ENV = "KNOWLEDGE_GRAPH_LIGHTWEIGHT_RAG_ONLY"


def lightweight_rag_only_enabled() -> bool:
    """生产开关：图谱抽取只允许轻量化 RAG 兼容协议。"""
    return str(os.getenv(LIGHTWEIGHT_RAG_ONLY_ENV, "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def normalize_pipeline_options(
    extractor_type: str,
    options: dict[str, Any] | None,
    *,
    ontology_definition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """固定纯 LightRAG 抽取器所需的本体与运行快照。"""
    normalized_type = str(extractor_type or "").strip().lower()
    normalized = deepcopy(options or {})
    if normalized_type != "lightrag_primary":
        if lightweight_rag_only_enabled():
            raise ValueError("生产环境仅支持轻量化 RAG 图谱抽取器")
        return normalized
    requested_version = str(normalized.get("ontology_version") or DEFENSE_ONTOLOGY_V1.version)
    if ontology_definition is None:
        if requested_version != DEFENSE_ONTOLOGY_V1.version:
            raise ValueError(f"本体版本 {requested_version} 必须由治理服务提供不可变定义")
        ontology_definition = ontology_payload()
    snapshot = normalize_ontology_definition(ontology_definition)
    if snapshot["version"] != requested_version:
        raise ValueError("治理服务返回的本体定义与请求版本不一致")
    normalized["ontology_version"] = requested_version
    normalized["ontology_definition"] = snapshot
    normalized["pipeline_revision"] = str(normalized.get("pipeline_revision") or DEFAULT_PIPELINE_REVISION)
    normalized["orchestration_mode"] = "lightrag_primary"
    normalized["parallel_primary_extraction"] = False
    normalized.pop("secondary", None)
    normalized["extractor_family"] = "lightrag"
    normalized["acceptance_policy"] = normalize_acceptance_policy(
        normalized.get("acceptance_policy"),
        pipeline_revision=normalized["pipeline_revision"],
    )
    normalized["document_audit"] = _normalize_document_audit(normalized.get("document_audit"))
    release_channel = str(normalized.get("orchestration_release_channel") or "stable").strip()
    if release_channel not in ORCHESTRATION_RELEASE_CHANNELS:
        allowed = ", ".join(sorted(ORCHESTRATION_RELEASE_CHANNELS))
        raise ValueError(f"orchestration_release_channel 必须是: {allowed}")
    normalized["orchestration_release_channel"] = release_channel
    normalized["document_enhancement"] = _normalize_document_enhancement(
        normalized.get("document_enhancement"), normalized
    )
    normalized["entity_alignment"] = _normalize_entity_alignment(normalized.get("entity_alignment"))
    normalized["llm_enhancement"] = _normalize_llm_enhancement(
        normalized.get("llm_enhancement"), normalized, release_channel=release_channel
    )
    if not normalized["llm_enhancement"]["enabled"]:
        raise ValueError("lightrag_primary 编排必须启用 llm_enhancement")
    normalized["retrieval_evidence_summary"] = _normalize_retrieval_evidence_summary(
        normalized.get("retrieval_evidence_summary")
    )
    return normalized


def ontology_definition_from_options(options: dict[str, Any]) -> dict[str, Any]:
    """读取并校验抽取器携带的不可变本体快照。"""
    requested_version = str(options.get("ontology_version") or DEFENSE_ONTOLOGY_V1.version)
    definition = options.get("ontology_definition") or ontology_payload()
    if not isinstance(definition, dict):
        raise ValueError("ontology_definition 必须是对象")
    normalized = normalize_ontology_definition(definition)
    if normalized["version"] != requested_version:
        raise ValueError("ontology_definition.version 与 ontology_version 不一致")
    return normalized


def _normalize_backend_options(
    backend_options: dict[str, Any] | None,
    pipeline_options: dict[str, Any],
) -> dict[str, Any]:
    options = dict(backend_options or {})
    options["ontology_version"] = pipeline_options["ontology_version"]
    options["ontology_definition"] = deepcopy(pipeline_options["ontology_definition"])
    options["pipeline_revision"] = pipeline_options["pipeline_revision"]
    if "entity_attribute_groups" not in options and "entity_attribute_groups" in pipeline_options:
        options["entity_attribute_groups"] = deepcopy(pipeline_options["entity_attribute_groups"])
    return options


def _normalize_document_enhancement(
    enhancement_options: dict[str, Any] | None,
    pipeline_options: dict[str, Any],
) -> dict[str, Any]:
    options = dict(enhancement_options or {})
    if not options.get("enabled"):
        return {"enabled": False}
    options.update(
        {
            "enabled": True,
            "ontology_version": pipeline_options["ontology_version"],
            "pipeline_revision": pipeline_options["pipeline_revision"],
            "usage_mode": "offline",
            "relation_scope": "factual_only",
            "concurrency_count": _bounded_integer(
                options.get("concurrency_count", 2),
                "document_enhancement.concurrency_count",
                1,
                8,
            ),
            "document_concurrency_count": _bounded_integer(
                options.get("document_concurrency_count", 2),
                "document_enhancement.document_concurrency_count",
                1,
                8,
            ),
            "max_chars": _bounded_integer(
                options.get("max_chars", 16_000),
                "document_enhancement.max_chars",
                512,
                200_000,
            ),
            "max_candidate_pairs": _bounded_integer(
                options.get("max_candidate_pairs", 256),
                "document_enhancement.max_candidate_pairs",
                1,
                2048,
            ),
            "priority_max_blocks": _bounded_integer(
                options.get("priority_max_blocks", 192),
                "document_enhancement.priority_max_blocks",
                1,
                1024,
            ),
            "priority_max_chars": _bounded_integer(
                options.get("priority_max_chars", 32_000),
                "document_enhancement.priority_max_chars",
                512,
                200_000,
            ),
            "priority_max_entities": _bounded_integer(
                options.get("priority_max_entities", 64),
                "document_enhancement.priority_max_entities",
                2,
                256,
            ),
            "priority_llm_max_relations": _bounded_integer(
                options.get("priority_llm_max_relations", 24),
                "document_enhancement.priority_llm_max_relations",
                1,
                64,
            ),
            "priority_llm_max_output_tokens": _bounded_integer(
                options.get("priority_llm_max_output_tokens", 4096),
                "document_enhancement.priority_llm_max_output_tokens",
                256,
                32768,
            ),
            "priority_llm_max_truncation_retries": _bounded_integer(
                options.get("priority_llm_max_truncation_retries", 1),
                "document_enhancement.priority_llm_max_truncation_retries",
                0,
                2,
            ),
            "priority_entity_max_blocks": _bounded_integer(
                options.get("priority_entity_max_blocks", 96),
                "document_enhancement.priority_entity_max_blocks",
                1,
                512,
            ),
            "priority_entity_max_chars": _bounded_integer(
                options.get("priority_entity_max_chars", 24_000),
                "document_enhancement.priority_entity_max_chars",
                512,
                200_000,
            ),
            "priority_entity_max_candidates": _bounded_integer(
                options.get("priority_entity_max_candidates", 200),
                "document_enhancement.priority_entity_max_candidates",
                1,
                1000,
            ),
        }
    )
    llm_options = dict(options.get("llm_enhancement") or {})
    if llm_options.get("enabled"):
        model_spec = _project_model_spec(
            llm_options.get("model_spec"),
            "document_enhancement.llm_enhancement.model_spec",
        )
        options["llm_enhancement"] = {
            **llm_options,
            "enabled": True,
            "model_spec": model_spec,
            **_structured_llm_runtime_options(
                llm_options,
                "document_enhancement.llm_enhancement",
            ),
            "max_output_tokens": int(llm_options.get("max_output_tokens") or 2048),
            "max_relations": _bounded_integer(
                llm_options.get("max_relations", 12),
                "document_enhancement.llm_enhancement.max_relations",
                1,
                64,
            ),
            "min_confidence": _probability(
                llm_options.get("min_confidence", 0.9),
                "document_enhancement.llm_enhancement.min_confidence",
            ),
            "timeout_seconds": float(llm_options.get("timeout_seconds") or 120.0),
            "strict": llm_options.get("strict", False) is True,
        }
    else:
        options["llm_enhancement"] = {"enabled": False}
    entity_options = dict(options.get("entity_enhancement") or {})
    if entity_options.get("enabled"):
        model_spec = _project_model_spec(
            entity_options.get("model_spec"),
            "document_enhancement.entity_enhancement.model_spec",
        )
        layout_options = entity_options.get("layout_normalization") or {}
        if not isinstance(layout_options, dict):
            raise ValueError("document_enhancement.entity_enhancement.layout_normalization 必须是对象")
        layout_enabled = layout_options.get("enabled", True)
        if not isinstance(layout_enabled, bool):
            raise ValueError("document_enhancement.entity_enhancement.layout_normalization.enabled 必须是布尔值")
        max_gleanings = _bounded_integer(
            entity_options.get("max_gleanings", 0),
            "document_enhancement.entity_enhancement.max_gleanings",
            0,
            1,
        )
        gleaning_on_layout_damage = entity_options.get("gleaning_on_layout_damage", True)
        if not isinstance(gleaning_on_layout_damage, bool):
            raise ValueError("document_enhancement.entity_enhancement.gleaning_on_layout_damage 必须是布尔值")
        gleaning_on_role_gap = entity_options.get("gleaning_on_role_gap", True)
        if not isinstance(gleaning_on_role_gap, bool):
            raise ValueError("document_enhancement.entity_enhancement.gleaning_on_role_gap 必须是布尔值")
        options["entity_enhancement"] = {
            **entity_options,
            "enabled": True,
            "model_spec": model_spec,
            **_structured_llm_runtime_options(
                entity_options,
                "document_enhancement.entity_enhancement",
            ),
            "max_output_tokens": _bounded_integer(
                entity_options.get("max_output_tokens", 2048),
                "document_enhancement.entity_enhancement.max_output_tokens",
                128,
                32768,
            ),
            "timeout_seconds": _bounded_number(
                entity_options.get("timeout_seconds", 120.0),
                "document_enhancement.entity_enhancement.timeout_seconds",
                1.0,
                1800.0,
            ),
            "max_blocks": _bounded_integer(
                entity_options.get("max_blocks", 48),
                "document_enhancement.entity_enhancement.max_blocks",
                1,
                256,
            ),
            "max_chars": _bounded_integer(
                entity_options.get("max_chars", min(int(options["max_chars"]), 12_000)),
                "document_enhancement.entity_enhancement.max_chars",
                512,
                200_000,
            ),
            "max_candidates": _bounded_integer(
                entity_options.get("max_candidates", 100),
                "document_enhancement.entity_enhancement.max_candidates",
                1,
                1000,
            ),
            "max_entities_per_call": _bounded_integer(
                entity_options.get("max_entities_per_call", 24),
                "document_enhancement.entity_enhancement.max_entities_per_call",
                1,
                64,
            ),
            "max_repair_proposals_per_call": _bounded_integer(
                entity_options.get("max_repair_proposals_per_call", 4),
                "document_enhancement.entity_enhancement.max_repair_proposals_per_call",
                0,
                32,
            ),
            "min_confidence": _probability(
                entity_options.get("min_confidence", 0.85),
                "document_enhancement.entity_enhancement.min_confidence",
            ),
            "max_gleanings": max_gleanings,
            "gleaning_min_source_chars": _bounded_integer(
                entity_options.get("gleaning_min_source_chars", 512),
                "document_enhancement.entity_enhancement.gleaning_min_source_chars",
                128,
                200_000,
            ),
            "gleaning_min_candidates": _bounded_integer(
                entity_options.get("gleaning_min_candidates", 3),
                "document_enhancement.entity_enhancement.gleaning_min_candidates",
                1,
                1000,
            ),
            "gleaning_on_layout_damage": gleaning_on_layout_damage,
            "gleaning_on_role_gap": gleaning_on_role_gap,
            "strict": entity_options.get("strict", False) is True,
            "review_status": "pending",
            "stable_id_authority": "platform_alignment_only",
            "layout_normalization": {
                "enabled": layout_enabled,
                "max_deletions": _bounded_integer(
                    layout_options.get("max_deletions", 256),
                    "document_enhancement.entity_enhancement.layout_normalization.max_deletions",
                    1,
                    4096,
                ),
                "max_whitespace_chars": _bounded_integer(
                    layout_options.get("max_whitespace_chars", 8),
                    "document_enhancement.entity_enhancement.layout_normalization.max_whitespace_chars",
                    1,
                    32,
                ),
            },
        }
    else:
        options["entity_enhancement"] = {"enabled": False}
    cross_document_options = dict(options.get("cross_document_relation_enhancement") or {})
    if cross_document_options.get("enabled"):
        model_spec = _project_model_spec(
            cross_document_options.get("model_spec"),
            "document_enhancement.cross_document_relation_enhancement.model_spec",
        )
        min_document_support = _bounded_integer(
            cross_document_options.get("min_document_support", 2),
            "document_enhancement.cross_document_relation_enhancement.min_document_support",
            2,
            8,
        )
        max_documents_per_pair = _bounded_integer(
            cross_document_options.get("max_documents_per_pair", 3),
            "document_enhancement.cross_document_relation_enhancement.max_documents_per_pair",
            2,
            8,
        )
        if max_documents_per_pair < min_document_support:
            raise ValueError("cross_document_relation_enhancement.max_documents_per_pair 不能小于 min_document_support")
        review_scope = str(cross_document_options.get("review_scope") or "accepted_only").strip()
        if review_scope not in {"accepted_only", "pending_candidates"}:
            raise ValueError(
                "document_enhancement.cross_document_relation_enhancement.review_scope "
                "必须是 accepted_only 或 pending_candidates"
            )
        options["cross_document_relation_enhancement"] = {
            **cross_document_options,
            "enabled": True,
            "model_spec": model_spec,
            **_structured_llm_runtime_options(
                cross_document_options,
                "document_enhancement.cross_document_relation_enhancement",
            ),
            "min_document_support": min_document_support,
            "max_pairs": _bounded_integer(
                cross_document_options.get("max_pairs", 24),
                "document_enhancement.cross_document_relation_enhancement.max_pairs",
                1,
                128,
            ),
            "pairs_per_batch": _bounded_integer(
                cross_document_options.get("pairs_per_batch", 6),
                "document_enhancement.cross_document_relation_enhancement.pairs_per_batch",
                1,
                24,
            ),
            "concurrency_count": _bounded_integer(
                cross_document_options.get("concurrency_count", 2),
                "document_enhancement.cross_document_relation_enhancement.concurrency_count",
                1,
                8,
            ),
            "max_documents_per_pair": max_documents_per_pair,
            "max_scope_documents": _bounded_integer(
                cross_document_options.get("max_scope_documents", 128),
                "document_enhancement.cross_document_relation_enhancement.max_scope_documents",
                2,
                1024,
            ),
            "max_blocks": _bounded_integer(
                cross_document_options.get("max_blocks", 64),
                "document_enhancement.cross_document_relation_enhancement.max_blocks",
                4,
                256,
            ),
            "max_chars": _bounded_integer(
                cross_document_options.get("max_chars", 30_000),
                "document_enhancement.cross_document_relation_enhancement.max_chars",
                2_000,
                200_000,
            ),
            "max_relations": _bounded_integer(
                cross_document_options.get("max_relations", 24),
                "document_enhancement.cross_document_relation_enhancement.max_relations",
                1,
                128,
            ),
            "min_confidence": _probability(
                cross_document_options.get("min_confidence", 0.85),
                "document_enhancement.cross_document_relation_enhancement.min_confidence",
            ),
            "min_entity_confidence": _probability(
                cross_document_options.get("min_entity_confidence", 0.0),
                "document_enhancement.cross_document_relation_enhancement.min_entity_confidence",
            ),
            "max_entities_per_document": _bounded_integer(
                cross_document_options.get("max_entities_per_document", 96),
                "document_enhancement.cross_document_relation_enhancement.max_entities_per_document",
                2,
                512,
            ),
            "max_pairs_per_document": _bounded_integer(
                cross_document_options.get("max_pairs_per_document", 512),
                "document_enhancement.cross_document_relation_enhancement.max_pairs_per_document",
                1,
                4096,
            ),
            "max_output_tokens": _bounded_integer(
                cross_document_options.get("max_output_tokens", 4096),
                "document_enhancement.cross_document_relation_enhancement.max_output_tokens",
                128,
                32768,
            ),
            "max_repair_attempts": _bounded_integer(
                cross_document_options.get("max_repair_attempts", 1),
                "document_enhancement.cross_document_relation_enhancement.max_repair_attempts",
                0,
                1,
            ),
            "timeout_seconds": _bounded_number(
                cross_document_options.get("timeout_seconds", 180.0),
                "document_enhancement.cross_document_relation_enhancement.timeout_seconds",
                1.0,
                1800.0,
            ),
            "strict": cross_document_options.get("strict", False) is True,
            "relation_scope": "factual_only",
            "claim_level": "Inference",
            "review_status": "pending",
            "review_scope": review_scope,
            "accepted_mentions_only": review_scope == "accepted_only",
        }
    else:
        options["cross_document_relation_enhancement"] = {"enabled": False}
    if not any(
        (
            options["llm_enhancement"]["enabled"],
            options["entity_enhancement"]["enabled"],
            options["cross_document_relation_enhancement"]["enabled"],
        )
    ):
        raise ValueError("document_enhancement 至少必须启用一种 LightRAG 增强能力")
    if options.get("include_hypothesis_relations"):
        raise ValueError("document_enhancement 只允许事实关系；创新假设必须进入独立创新流水线")
    return options


def _normalize_document_audit(options: dict[str, Any] | None) -> dict[str, Any]:
    """默认启用保守分流和派生知识卡，可显式关闭以兼容旧运行。"""
    normalized = dict(options or {})
    raw_value_routing = normalized.get("value_routing") or {}
    if not isinstance(raw_value_routing, dict):
        raise ValueError("document_audit.value_routing 必须是对象")
    if raw_value_routing.get("enabled"):
        value_routing = {
            **raw_value_routing,
            "enabled": True,
            "model_spec": _project_model_spec(
                raw_value_routing.get("model_spec"),
                "document_audit.value_routing.model_spec",
            ),
            **_structured_llm_runtime_options(
                raw_value_routing,
                "document_audit.value_routing",
            ),
            "max_chars": _bounded_integer(
                raw_value_routing.get("max_chars", 12_000),
                "document_audit.value_routing.max_chars",
                1000,
                100_000,
            ),
            "max_output_tokens": _bounded_integer(
                raw_value_routing.get("max_output_tokens", 1200),
                "document_audit.value_routing.max_output_tokens",
                256,
                4096,
            ),
            "min_confidence": _probability(
                raw_value_routing.get("min_confidence", 0.8),
                "document_audit.value_routing.min_confidence",
            ),
            "concurrency_count": _bounded_integer(
                raw_value_routing.get("concurrency_count", 2),
                "document_audit.value_routing.concurrency_count",
                1,
                8,
            ),
            "timeout_seconds": _bounded_number(
                raw_value_routing.get("timeout_seconds", 120.0),
                "document_audit.value_routing.timeout_seconds",
                1.0,
                1800.0,
            ),
            "strict": raw_value_routing.get("strict", False) is True,
        }
    else:
        value_routing = {"enabled": False}
    return {
        "enabled": normalized.get("enabled", True) is not False,
        "filter_non_research": normalized.get("filter_non_research", True) is not False,
        "value_routing": value_routing,
    }


def _normalize_entity_alignment(
    alignment_options: dict[str, Any] | None,
) -> dict[str, Any]:
    """规范化跨文档 LLM 实体消歧与高置信自动链接。"""
    options = dict(alignment_options or {})
    if not options.get("enabled"):
        return {"enabled": False}
    model_spec = _project_model_spec(options.get("model_spec"), "entity_alignment.model_spec")
    strict = options.get("strict", False)
    auto_link_enabled = options.get("auto_link_enabled", False)
    if not isinstance(strict, bool):
        raise ValueError("entity_alignment.strict 必须是布尔值")
    if not isinstance(auto_link_enabled, bool):
        raise ValueError("entity_alignment.auto_link_enabled 必须是布尔值")
    return {
        **options,
        "enabled": True,
        "model_spec": model_spec,
        **_structured_llm_runtime_options(options, "entity_alignment"),
        "strict": strict,
        "auto_link_enabled": auto_link_enabled,
        "min_confidence": _probability(options.get("min_confidence", 0.95), "entity_alignment.min_confidence"),
        "min_vector_score": _probability(
            options.get("min_vector_score", 0.90),
            "entity_alignment.min_vector_score",
        ),
        "max_candidates": _bounded_integer(
            options.get("max_candidates", 5),
            "entity_alignment.max_candidates",
            1,
            10,
        ),
        "timeout_seconds": _bounded_number(
            options.get("timeout_seconds", 60.0),
            "entity_alignment.timeout_seconds",
            1.0,
            600.0,
        ),
        "max_output_tokens": _bounded_integer(
            options.get("max_output_tokens", 4096),
            "entity_alignment.max_output_tokens",
            128,
            32768,
        ),
    }


def _normalize_llm_enhancement(
    enhancement_options: dict[str, Any] | None,
    pipeline_options: dict[str, Any],
    *,
    release_channel: str,
) -> dict[str, Any]:
    """固定 LightRAG 风格初抽增强的模型、本体与补抽次数。"""
    options = dict(enhancement_options or {})
    if not options.get("enabled"):
        return {"enabled": False}
    options["model_spec"] = _project_model_spec(options.get("model_spec"), "llm_enhancement.model_spec")
    domain_guidance_enabled = options.get("domain_guidance_enabled", True)
    if not isinstance(domain_guidance_enabled, bool):
        raise ValueError("llm_enhancement.domain_guidance_enabled 必须是布尔值")
    lightrag_primary = str(pipeline_options.get("orchestration_mode") or "").strip() == "lightrag_primary"
    entity_review_mode = str(
        options.get("entity_review_mode") or ("apply_experiment" if lightrag_primary else "propose")
    ).strip()
    if entity_review_mode not in {"off", "propose", "apply_experiment"}:
        raise ValueError("llm_enhancement.entity_review_mode 必须是: apply_experiment, off, propose")
    layout_normalization = _normalize_layout_normalization(
        options.get("layout_normalization"),
        release_channel=release_channel,
    )
    ocr_repair_extraction = _normalize_ocr_repair_extraction(
        options.get("ocr_repair_extraction"),
        release_channel=release_channel,
    )
    adaptive_routing = normalize_adaptive_routing_options(options.get("adaptive_routing"))
    parallel_initial_review = options.get("parallel_initial_review", False)
    if not isinstance(parallel_initial_review, bool):
        raise ValueError("llm_enhancement.parallel_initial_review 必须是布尔值")
    primary_extract_relations = _primary_extract_relations(pipeline_options)
    relation_completion = normalize_relation_completion_options(
        options.get("relation_completion"),
        orchestration_mode=str(pipeline_options.get("orchestration_mode") or ""),
        primary_extract_relations=primary_extract_relations,
    )
    options.update(
        {
            "enabled": True,
            **_structured_llm_runtime_options(options, "llm_enhancement"),
            "enhancement_revision": LIGHTRAG_ENHANCEMENT_REVISION,
            "domain_guidance_enabled": domain_guidance_enabled,
            "entity_review_mode": entity_review_mode,
            "entity_review_min_confidence": _probability(
                options.get("entity_review_min_confidence", 0.95),
                "llm_enhancement.entity_review_min_confidence",
            ),
            "entity_review_trigger": str(
                options.get("entity_review_trigger") or ("all" if lightrag_primary else "suspect_only")
            ).strip(),
            "entity_review_max_candidates": _bounded_integer(
                options.get("entity_review_max_candidates", 24),
                "llm_enhancement.entity_review_max_candidates",
                1,
                512,
            ),
            "layout_normalization": layout_normalization,
            "ocr_repair_extraction": ocr_repair_extraction,
            "adaptive_routing": adaptive_routing,
            "concurrency_count": _bounded_integer(
                options.get("concurrency_count", 4 if lightrag_primary else 1),
                "llm_enhancement.concurrency_count",
                1,
                8,
            ),
            "parallel_initial_review": parallel_initial_review,
            "relation_completion": relation_completion,
            "ontology_version": pipeline_options["ontology_version"],
            "ontology_definition": deepcopy(pipeline_options["ontology_definition"]),
            "pipeline_revision": pipeline_options["pipeline_revision"],
            "max_gleanings": options.get("max_gleanings", 1),
            "context_window_size": options.get("context_window_size", 1),
            "context_max_chars": options.get("context_max_chars", 1200),
            "max_initial_entities": _bounded_integer(
                options.get("max_initial_entities", 48),
                "llm_enhancement.max_initial_entities",
                1,
                512,
            ),
            "max_initial_relations": _bounded_integer(
                options.get("max_initial_relations", 64),
                "llm_enhancement.max_initial_relations",
                1,
                512,
            ),
            "max_initial_records": _bounded_integer(
                options.get("max_initial_records", 96),
                "llm_enhancement.max_initial_records",
                1,
                512,
            ),
            "max_gleaning_entities": _bounded_integer(
                options.get("max_gleaning_entities", 24),
                "llm_enhancement.max_gleaning_entities",
                1,
                512,
            ),
            "max_gleaning_relations": _bounded_integer(
                options.get("max_gleaning_relations", 32),
                "llm_enhancement.max_gleaning_relations",
                1,
                512,
            ),
            "max_gleaning_records": _bounded_integer(
                options.get("max_gleaning_records", 48),
                "llm_enhancement.max_gleaning_records",
                1,
                512,
            ),
            "max_prompt_entities": _bounded_integer(
                options.get("max_prompt_entities", 48),
                "llm_enhancement.max_prompt_entities",
                1,
                512,
            ),
            "max_prompt_relations": _bounded_integer(
                options.get("max_prompt_relations", 64),
                "llm_enhancement.max_prompt_relations",
                1,
                512,
            ),
            "max_output_tokens": _bounded_integer(
                options.get("max_output_tokens", 4096),
                "llm_enhancement.max_output_tokens",
                256,
                32768,
            ),
            "max_prompt_chars": _bounded_integer(
                options.get("max_prompt_chars", 60_000),
                "llm_enhancement.max_prompt_chars",
                2_000,
                500_000,
            ),
            "max_gleaning_input_chars": _bounded_integer(
                options.get("max_gleaning_input_chars", 80_000),
                "llm_enhancement.max_gleaning_input_chars",
                2_000,
                500_000,
            ),
            "max_prompt_tokens": _bounded_integer(
                options.get("max_prompt_tokens", 24_000),
                "llm_enhancement.max_prompt_tokens",
                1_000,
                200_000,
            ),
            "max_gleaning_input_tokens": _bounded_integer(
                options.get("max_gleaning_input_tokens", 32_000),
                "llm_enhancement.max_gleaning_input_tokens",
                1_000,
                200_000,
            ),
        }
    )
    if options["max_initial_records"] < options["max_initial_entities"]:
        raise ValueError("llm_enhancement.max_initial_records 不能小于 max_initial_entities")
    if options["max_gleaning_records"] < options["max_gleaning_entities"]:
        raise ValueError("llm_enhancement.max_gleaning_records 不能小于 max_gleaning_entities")
    if options["entity_review_trigger"] not in {"suspect_only", "all"}:
        raise ValueError("llm_enhancement.entity_review_trigger 必须是: all, suspect_only")
    return options


def _primary_extract_relations(pipeline_options: dict[str, Any]) -> bool:
    """纯 LightRAG 主抽始终同时抽取实体和关系。"""
    return True


def _normalize_layout_normalization(
    normalization_options: dict[str, Any] | None,
    *,
    release_channel: str,
) -> dict[str, Any]:
    """规范化可回切原文 Span 的排版空白临时视图。"""
    if normalization_options is not None and not isinstance(normalization_options, dict):
        raise ValueError("llm_enhancement.layout_normalization 必须是对象")
    options = dict(normalization_options or {})
    enabled = options.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("llm_enhancement.layout_normalization.enabled 必须是布尔值")
    if not enabled:
        return {"enabled": False}
    max_entities = _bounded_integer(
        options.get("max_entities", 24),
        "llm_enhancement.layout_normalization.max_entities",
        1,
        128,
    )
    max_records = _bounded_integer(
        options.get("max_records", 48),
        "llm_enhancement.layout_normalization.max_records",
        1,
        256,
    )
    if max_records < max_entities:
        raise ValueError("llm_enhancement.layout_normalization.max_records 不能小于 max_entities")
    return {
        **options,
        "enabled": True,
        "release_channel": release_channel,
        "max_deletions": _bounded_integer(
            options.get("max_deletions", 256),
            "llm_enhancement.layout_normalization.max_deletions",
            1,
            4096,
        ),
        "max_whitespace_chars": _bounded_integer(
            options.get("max_whitespace_chars", 8),
            "llm_enhancement.layout_normalization.max_whitespace_chars",
            1,
            32,
        ),
        "max_entities": max_entities,
        "max_relations": _bounded_integer(
            options.get("max_relations", 32),
            "llm_enhancement.layout_normalization.max_relations",
            1,
            128,
        ),
        "max_records": max_records,
        "max_prompt_chars": _bounded_integer(
            options.get("max_prompt_chars", 60_000),
            "llm_enhancement.layout_normalization.max_prompt_chars",
            2_000,
            500_000,
        ),
        "max_prompt_tokens": _bounded_integer(
            options.get("max_prompt_tokens", 24_000),
            "llm_enhancement.layout_normalization.max_prompt_tokens",
            1_000,
            200_000,
        ),
        "authority_write_enabled": False,
        "source_text_policy": "preserve_original_and_map_spans",
    }


def _normalize_ocr_repair_extraction(
    repair_options: dict[str, Any] | None,
    *,
    release_channel: str,
) -> dict[str, Any]:
    """规范化证据保持型 OCR 修复复抽。"""
    if repair_options is not None and not isinstance(repair_options, dict):
        raise ValueError("llm_enhancement.ocr_repair_extraction 必须是对象")
    options = dict(repair_options or {})
    enabled = options.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError("llm_enhancement.ocr_repair_extraction.enabled 必须是布尔值")
    if not enabled:
        return {"enabled": False}
    max_entities = _bounded_integer(
        options.get("max_entities", 16),
        "llm_enhancement.ocr_repair_extraction.max_entities",
        1,
        128,
    )
    max_records = _bounded_integer(
        options.get("max_records", 28),
        "llm_enhancement.ocr_repair_extraction.max_records",
        1,
        256,
    )
    if max_records < max_entities:
        raise ValueError("llm_enhancement.ocr_repair_extraction.max_records 不能小于 max_entities")
    return {
        **options,
        "enabled": True,
        "release_channel": release_channel,
        "min_confidence": _probability(
            options.get("min_confidence", 0.85),
            "llm_enhancement.ocr_repair_extraction.min_confidence",
        ),
        "max_proposals": _bounded_integer(
            options.get("max_proposals", 8),
            "llm_enhancement.ocr_repair_extraction.max_proposals",
            1,
            64,
        ),
        "max_entities": max_entities,
        "max_relations": _bounded_integer(
            options.get("max_relations", 20),
            "llm_enhancement.ocr_repair_extraction.max_relations",
            1,
            128,
        ),
        "max_records": max_records,
        "max_prompt_chars": _bounded_integer(
            options.get("max_prompt_chars", 60_000),
            "llm_enhancement.ocr_repair_extraction.max_prompt_chars",
            2_000,
            500_000,
        ),
        "max_prompt_tokens": _bounded_integer(
            options.get("max_prompt_tokens", 24_000),
            "llm_enhancement.ocr_repair_extraction.max_prompt_tokens",
            1_000,
            200_000,
        ),
        "authority_write_enabled": False,
        "repair_dependent_candidate_policy": "isolate",
    }


def _normalize_retrieval_evidence_summary(options: dict[str, Any] | None) -> dict[str, Any]:
    """规范化默认关闭、仅选择已审核 evidence ID 的检索摘要。"""
    normalized = dict(options or {})
    if not normalized.get("enabled"):
        return {"enabled": False}
    if not str(normalized.get("model_spec") or "").strip():
        raise ValueError("启用 retrieval_evidence_summary 时必须配置 model_spec")
    source_text_policy = str(normalized.get("source_text_policy") or "").strip()
    if source_text_policy not in {"local_only", "approved_external"}:
        raise ValueError("retrieval_evidence_summary.source_text_policy 必须是 local_only 或 approved_external")
    model_spec = str(normalized["model_spec"]).strip()
    provider_id = model_spec.split(":", 1)[0].casefold()
    configured_local_provider_ids = normalized.get("local_provider_ids") or []
    if not isinstance(configured_local_provider_ids, list):
        raise ValueError("retrieval_evidence_summary.local_provider_ids 必须是数组")
    local_provider_ids = {
        "local",
        "local-provider",
        "local-llm",
        "ollama",
        "lmstudio",
        *(str(value).strip().casefold() for value in configured_local_provider_ids if str(value).strip()),
    }
    if source_text_policy == "local_only" and provider_id not in local_provider_ids:
        raise ValueError("source_text_policy=local_only 时 model_spec 必须属于已登记的本地模型提供方")
    return {
        **normalized,
        "enabled": True,
        "model_spec": model_spec,
        "source_text_policy": source_text_policy,
        "local_provider_ids": sorted(local_provider_ids),
        "strict": normalized.get("strict", False) is True,
        "max_selected": _bounded_integer(
            normalized.get("max_selected", 12),
            "retrieval_evidence_summary.max_selected",
            1,
            24,
        ),
        "concurrency": _bounded_integer(
            normalized.get("concurrency", 4),
            "retrieval_evidence_summary.concurrency",
            1,
            8,
        ),
        "timeout_seconds": _bounded_number(
            normalized.get("timeout_seconds", 90),
            "retrieval_evidence_summary.timeout_seconds",
            1,
            600,
        ),
        "max_output_tokens": _bounded_integer(
            normalized.get("max_output_tokens", 2048),
            "retrieval_evidence_summary.max_output_tokens",
            128,
            8192,
        ),
        "extractive_only": True,
        "authoritative_write": False,
    }


def _project_model_spec(value: Any, field: str) -> str:
    """拒绝已退役的 LightRAG 本地 7B/MLX 提供方。"""
    model_spec = str(value or "").strip()
    if not model_spec:
        raise ValueError(f"启用 {field.rsplit('.', 1)[0]} 时必须配置 model_spec")
    provider_id = model_spec.split(":", 1)[0].casefold()
    if provider_id in REMOVED_LIGHTRAG_LOCAL_PROVIDER_IDS:
        raise ValueError(f"{field} 不再支持本地 7B/MLX 模型，请选择项目模型设置中的通用模型")
    return model_spec


def _structured_llm_runtime_options(options: dict[str, Any], field: str) -> dict[str, Any]:
    """结构化抽取默认关闭思考链和指数输出重试，允许显式覆盖。"""

    enable_thinking = options.get("enable_thinking", False)
    if not isinstance(enable_thinking, bool):
        raise ValueError(f"{field}.enable_thinking 必须是布尔值")
    return {
        "enable_thinking": enable_thinking,
        "max_truncation_retries": _bounded_integer(
            options.get("max_truncation_retries", 0),
            f"{field}.max_truncation_retries",
            0,
            2,
        ),
    }


def _probability(value: Any, field: str) -> float:
    return _bounded_number(value, field, 0.0, 1.0)


def _bounded_number(value: Any, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} 必须是数字")
    try:
        normalized = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} 必须是数字") from exc
    if not minimum <= normalized <= maximum:
        raise ValueError(f"{field} 必须在 {minimum:g} 到 {maximum:g} 之间")
    return normalized


def _bounded_integer(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} 必须是整数")
    try:
        normalized = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} 必须是整数") from exc
    if normalized != value or not minimum <= normalized <= maximum:
        raise ValueError(f"{field} 必须在 {minimum} 到 {maximum} 之间")
    return normalized
