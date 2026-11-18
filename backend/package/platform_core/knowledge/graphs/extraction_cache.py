"""图谱抽取缓存的确定性谱系与语义配置指纹。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

EXTRACTION_CACHE_SCHEMA_VERSION = 1

# 这些参数只影响服务连接、调度或吞吐，不改变声明的模型与抽取语义。
_RUNTIME_OPTION_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "base_url",
        "batch_size",
        "concurrency_count",
        "endpoint",
        "headers",
        "max_connections",
        "max_inflight_requests",
        "password",
        "secret",
        "timeout_seconds",
        "token",
        "verify_ssl",
    }
)


def semantic_extractor_config(extractor_type: str, options: Mapping[str, Any] | None) -> dict[str, Any]:
    """移除连接、密钥和吞吐参数，保留会改变抽取结果的配置。"""
    return {
        "extractor_type": str(extractor_type or "").strip().lower(),
        "extractor_options": _semantic_value(dict(options or {})),
    }


def semantic_config_fingerprint(extractor_type: str, options: Mapping[str, Any] | None) -> str:
    """生成可安全公开的语义配置 SHA-256。"""
    return _canonical_sha256(semantic_extractor_config(extractor_type, options))


def build_extraction_cache_manifest(
    *,
    chunk: Any,
    extractor_type: str,
    extractor_options: Mapping[str, Any] | None,
    context_chunks: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """为一次 Chunk 抽取生成可复现且不含服务密钥的输入清单。"""
    options = dict(extractor_options or {})
    source_metadata = getattr(chunk, "source_metadata", None)
    source_metadata = dict(source_metadata) if isinstance(source_metadata, Mapping) else {}
    content = str(getattr(chunk, "content", "") or "")
    normalized_context = [
        {
            "chunk_id": str(item.get("chunk_id") or ""),
            "chunk_index": int(item.get("chunk_index") or 0),
            "content_sha256": _text_sha256(str(item.get("content") or "")),
        }
        for item in context_chunks or []
    ]
    return {
        "schema_version": EXTRACTION_CACHE_SCHEMA_VERSION,
        "document": {
            "file_id": str(getattr(chunk, "file_id", "") or ""),
            "document_version": max(int(getattr(chunk, "document_version", None) or 1), 1),
            "content_hash": str(
                source_metadata.get("document_content_hash")
                or source_metadata.get("content_hash")
                or "legacy-unavailable"
            ),
        },
        "block": {
            "chunk_id": str(getattr(chunk, "chunk_id", "") or ""),
            "chunk_index": int(getattr(chunk, "chunk_index", None) or 0),
            "content_sha256": _text_sha256(content),
        },
        "parser": {
            "name": str(getattr(chunk, "parser_name", None) or "legacy-unversioned"),
            "version": str(getattr(chunk, "parser_version", None) or "legacy-unversioned"),
        },
        "pipeline_revision": str(options.get("pipeline_revision") or "legacy-v1"),
        "ontology_version": str(options.get("ontology_version") or "legacy-unversioned"),
        "rule_version": str(options.get("rule_version") or "defense-quality-contract-v1"),
        "model_versions": _model_versions(str(extractor_type or ""), options),
        "semantic_config_fingerprint": semantic_config_fingerprint(extractor_type, options),
        "context_chunks": normalized_context,
    }


def extraction_cache_key(manifest: Mapping[str, Any]) -> str:
    """对完整抽取输入清单生成确定性缓存键。"""
    return _canonical_sha256(dict(manifest))


def attach_extraction_cache_metadata(result: dict[str, Any], manifest: Mapping[str, Any]) -> str:
    """把缓存键和输入清单写入标准抽取结果 metadata。"""
    cache_key = extraction_cache_key(manifest)
    metadata = dict(result.get("metadata") or {})
    metadata["extraction_cache"] = {
        "schema_version": EXTRACTION_CACHE_SCHEMA_VERSION,
        "key": cache_key,
        "manifest": dict(manifest),
    }
    result["metadata"] = metadata
    return cache_key


def extraction_result_matches_cache(result: Any, expected_key: str) -> bool:
    """只接受带当前版本谱系且键完全匹配的抽取结果。"""
    if not isinstance(result, Mapping):
        return False
    metadata = result.get("metadata")
    if not isinstance(metadata, Mapping):
        return False
    cache = metadata.get("extraction_cache")
    return (
        isinstance(cache, Mapping)
        and cache.get("schema_version") == EXTRACTION_CACHE_SCHEMA_VERSION
        and cache.get("key") == expected_key
    )


def _semantic_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _semantic_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if not _is_runtime_option_key(str(key))
        }
    if isinstance(value, list | tuple):
        return [_semantic_value(item) for item in value]
    return value


def _model_versions(extractor_type: str, options: Mapping[str, Any]) -> dict[str, str]:
    normalized_type = extractor_type.strip().lower()
    versions = {"extractor_type": normalized_type or "unknown"}
    if normalized_type == "llm":
        versions["llm"] = str(options.get("model_spec") or "unknown")
    elif normalized_type == "lightrag_primary":
        versions["orchestration_mode"] = "lightrag_primary"
        llm_enhancement = options.get("llm_enhancement")
        llm_enhancement = dict(llm_enhancement) if isinstance(llm_enhancement, Mapping) else {}
        versions["primary"] = str(llm_enhancement.get("model_spec") or "unknown")
        versions["lightrag_primary"] = versions["primary"]
        enhancement = options.get("document_enhancement")
        enhancement = dict(enhancement) if isinstance(enhancement, Mapping) else {}
        if enhancement.get("enabled"):
            document_llm = enhancement.get("llm_enhancement")
            document_llm = dict(document_llm) if isinstance(document_llm, Mapping) else {}
            if document_llm.get("enabled"):
                versions["document_relation_llm"] = str(document_llm.get("model_spec") or "unknown")
            document_entity = enhancement.get("entity_enhancement")
            document_entity = dict(document_entity) if isinstance(document_entity, Mapping) else {}
            if document_entity.get("enabled"):
                versions["document_entity_llm"] = str(document_entity.get("model_spec") or "unknown")
            cross_document = enhancement.get("cross_document_relation_enhancement")
            cross_document = dict(cross_document) if isinstance(cross_document, Mapping) else {}
            if cross_document.get("enabled"):
                versions["cross_document_relation_llm"] = str(cross_document.get("model_spec") or "unknown")
    else:
        versions[normalized_type or "extractor"] = str(options.get("model_version") or "unknown")
    return versions


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_runtime_option_key(key: str) -> bool:
    normalized = key.strip().lower()
    return normalized in _RUNTIME_OPTION_KEYS or normalized.endswith(("_api_key", "_password", "_secret", "_token"))


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
