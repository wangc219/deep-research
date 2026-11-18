from types import SimpleNamespace

import pytest

from platform_core.knowledge.graphs.extraction_cache import (
    attach_extraction_cache_metadata,
    build_extraction_cache_manifest,
    extraction_cache_key,
    extraction_result_matches_cache,
    semantic_config_fingerprint,
    semantic_extractor_config,
)


def _chunk(**overrides):
    values = {
        "chunk_id": "chunk-1",
        "file_id": "file-1",
        "chunk_index": 0,
        "content": "ADRV9009 宽带射频收发器提升感知能力。",
        "document_version": 2,
        "parser_name": "paddlex",
        "parser_version": "3.1",
        "source_metadata": {"document_content_hash": "source-sha256"},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _options(**overrides):
    values = {
        "endpoint": "http://ie-extractor:8011",
        "timeout_seconds": 120,
        "concurrency_count": 4,
        "model_version": "lightrag.5-multi-v1",
        "ontology_version": "defense-kg-1.0",
        "rule_version": "defense-quality-contract-v1",
        "pipeline_revision": "hybrid-v2-r1",
        "extraction_options": {
            "batch_size": 4,
            "chunk_size": 384,
            "chunk_overlap": 64,
            "entity_threshold": 0.5,
        },
    }
    values.update(overrides)
    return values


def test_semantic_fingerprint_ignores_runtime_and_secret_options():
    first = _options(endpoint="http://localhost:8011", timeout_seconds=30, concurrency_count=1)
    first["api_key"] = "must-not-leak"
    second = _options(
        endpoint="http://ie-extractor:8011",
        timeout_seconds=300,
        concurrency_count=32,
        max_inflight_requests=1,
    )
    second["extraction_options"] = {**second["extraction_options"], "batch_size": 16}

    assert semantic_config_fingerprint("lightrag_primary", first) == semantic_config_fingerprint(
        "lightrag_primary", second
    )
    assert "must-not-leak" not in str(semantic_extractor_config("lightrag_primary", first))


@pytest.mark.parametrize(
    "change",
    [
        {"model_version": "lightrag.6"},
        {"ontology_version": "defense-kg-2.0"},
        {"rule_version": "defense-quality-contract-v2"},
        {"pipeline_revision": "hybrid-v2-r2"},
        {"extraction_options": {"chunk_size": 512, "chunk_overlap": 64, "entity_threshold": 0.5}},
    ],
)
def test_semantic_fingerprint_changes_for_extraction_semantics(change):
    assert semantic_config_fingerprint("lightrag_primary", _options()) != semantic_config_fingerprint(
        "lightrag_primary", _options(**change)
    )


def test_attribute_groups_are_part_of_semantic_fingerprint():
    configured = _options(
        entity_attribute_groups=[
            {
                "code": "maturity",
                "labels": ["原理验证", "工程验证"],
                "applies_to": ["KeyTechnology"],
            }
        ]
    )

    assert semantic_config_fingerprint("lightrag_primary", _options()) != semantic_config_fingerprint(
        "lightrag_primary", configured
    )


def test_cross_document_relation_semantics_are_part_of_cache_fingerprint():
    baseline = _options()
    enhanced = _options(
        document_enhancement={
            "enabled": True,
            "model_version": "lightrag-doc-v1",
            "cross_document_relation_enhancement": {
                "enabled": True,
                "model_spec": "local:military-chat",
                "min_document_support": 2,
            },
        }
    )

    assert semantic_config_fingerprint("lightrag_primary", baseline) != semantic_config_fingerprint("lightrag_primary", enhanced)


@pytest.mark.parametrize(
    "chunk_overrides",
    [
        {"content": "不同文本"},
        {"document_version": 3},
        {"parser_version": "3.2"},
        {"source_metadata": {"document_content_hash": "different-source"}},
    ],
)
def test_cache_key_changes_for_document_or_parser_lineage(chunk_overrides):
    baseline = build_extraction_cache_manifest(
        chunk=_chunk(),
        extractor_type="lightrag_primary",
        extractor_options=_options(),
    )
    changed = build_extraction_cache_manifest(
        chunk=_chunk(**chunk_overrides),
        extractor_type="lightrag_primary",
        extractor_options=_options(),
    )

    assert extraction_cache_key(baseline) != extraction_cache_key(changed)


def test_cache_key_includes_preceding_context_content():
    baseline = build_extraction_cache_manifest(
        chunk=_chunk(chunk_index=2),
        extractor_type="lightrag_primary",
        extractor_options=_options(),
        context_chunks=[{"chunk_id": "chunk-0", "chunk_index": 0, "content": "标题 A"}],
    )
    changed = build_extraction_cache_manifest(
        chunk=_chunk(chunk_index=2),
        extractor_type="lightrag_primary",
        extractor_options=_options(),
        context_chunks=[{"chunk_id": "chunk-0", "chunk_index": 0, "content": "标题 B"}],
    )

    assert extraction_cache_key(baseline) != extraction_cache_key(changed)


def test_attached_cache_metadata_matches_only_exact_manifest():
    manifest = build_extraction_cache_manifest(
        chunk=_chunk(),
        extractor_type="lightrag_primary",
        extractor_options=_options(),
    )
    result = {"entities": [], "relations": [], "metadata": {}}

    key = attach_extraction_cache_metadata(result, manifest)

    assert extraction_result_matches_cache(result, key)
    assert not extraction_result_matches_cache(result, "0" * 64)
    assert result["metadata"]["extraction_cache"]["manifest"] == manifest


def test_lightrag_primary_cache_lineage_names_the_actual_primary_model():
    manifest = build_extraction_cache_manifest(
        chunk=_chunk(),
        extractor_type="lightrag_primary",
        extractor_options={
            "orchestration_mode": "lightrag_primary",
            "pipeline_revision": "hybrid-v2-r1",
            "ontology_version": "defense-kg-1.0",
            "primary": {"model_version": "fastino/lightrag.5-multi-v1"},
            "secondary": {"enabled": False},
            "llm_enhancement": {
                "enabled": True,
                "model_spec": "local-lightrag:qwen-7b",
            },
            "document_enhancement": {
                "enabled": True,
                "lightrag_enabled": False,
                "llm_enhancement": {
                    "enabled": True,
                    "model_spec": "local-lightrag:qwen-7b",
                },
            },
        },
    )

    assert manifest["model_versions"] == {
        "extractor_type": "lightrag_primary",
        "orchestration_mode": "lightrag_primary",
        "primary": "local-lightrag:qwen-7b",
        "lightrag_primary": "local-lightrag:qwen-7b",
        "document_relation_llm": "local-lightrag:qwen-7b",
    }


def test_first_class_lightrag_cache_lineage_has_no_sidecar_models():
    manifest = build_extraction_cache_manifest(
        chunk=_chunk(),
        extractor_type="lightrag_primary",
        extractor_options={
            "pipeline_revision": "lightrag-primary-v1",
            "ontology_version": "defense-kg-1.0",
            "llm_enhancement": {
                "enabled": True,
                "model_spec": "project:model",
            },
            "document_enhancement": {"enabled": False},
        },
    )

    assert manifest["model_versions"] == {
        "extractor_type": "lightrag_primary",
        "orchestration_mode": "lightrag_primary",
        "primary": "project:model",
        "lightrag_primary": "project:model",
    }
