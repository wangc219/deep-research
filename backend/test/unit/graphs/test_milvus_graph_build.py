from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from platform_core.knowledge.graphs.extractors import (
    GraphExtractorFactory,
    LLMGraphExtractor,
    normalize_extraction_result,
)
from platform_core.knowledge.graphs.extractors.base import (
    MAX_ENTITY_LABEL_LENGTH,
    MAX_ENTITY_NAME_LENGTH,
    MAX_RELATION_TYPE_LENGTH,
)
from platform_core.knowledge.graphs.extraction_cache import (
    attach_extraction_cache_metadata,
    build_extraction_cache_manifest,
)
from platform_core.knowledge.graphs.graph_utils import build_graph_payload
from platform_core.knowledge.graphs.milvus_graph_service import (
    MilvusGraphService,
    build_graph_pipeline_stages,
    build_query_pipeline_trace,
)
from platform_core.knowledge.graphs.milvus_graph_vector_store import MilvusGraphVectorStore
import platform_core.knowledge.graphs.milvus_graph_vector_store as milvus_graph_vector_store_module
from platform_core.storage.postgres.models_knowledge import KnowledgeGraphEntity, KnowledgeGraphTriple


def _raw_graph_node(node_id: str, *, labels: list[str] | None = None, name: str | None = None) -> dict:
    return {
        "id": node_id,
        "labels": labels or ["MilvusKB", "Entity"],
        "properties": {"name": name or node_id, "kb_id": "kb_test"},
    }


def _raw_graph_edge(edge_id: str, source_id: str, target_id: str) -> dict:
    return {
        "id": edge_id,
        "type": "RELATED_TO",
        "source_id": source_id,
        "target_id": target_id,
        "properties": {},
    }


def test_graph_pipeline_stages_expose_authoritative_build_progress_and_warnings():
    pipeline = build_graph_pipeline_stages(
        configured=True,
        total_chunks=10,
        pending_chunks=2,
        indexed_chunks=7,
        structured_chunks=8,
        extraction_counts={"pending": 2, "succeeded": 7, "failed": 1},
        vector_counts={"pending": 1, "processing": 0, "indexed": 12, "failed": 1},
        projection_counts={"pending": 1, "processing": 0, "completed": 7, "failed": 0},
        entity_count=6,
        relationship_count=4,
        build_task_status="running",
        build_task_progress=72,
    )

    stages = {item["key"]: item for item in pipeline["stages"]}
    assert pipeline["contract_version"] == "lightrag-graph-pipeline-v1"
    assert stages["document_parse"]["status"] == "completed"
    assert stages["information_extraction"]["status"] == "warning"
    assert stages["information_extraction"]["metrics"]["task_progress"] == 72
    assert stages["authoritative_commit"]["metrics"]["relationship_count"] == 4
    assert stages["graph_projection"]["status"] == "active"
    assert stages["vector_projection"]["status"] == "warning"


def test_query_pipeline_trace_marks_individual_retrieval_degradation():
    trace = build_query_pipeline_trace(
        requested_retrieval_mode="mix",
        query_plan={"low_level_keywords": ["雷达"], "provenance": {"status": "completed"}},
        entity_hits=[{"id": "entity-1"}],
        triple_hits=[],
        chunk_hits=[{"id": "chunk-1"}],
        fusion={"entity_ids": ["entity-1"], "fusion_method": "reciprocal-rank-fusion-v1"},
        retrieval_failures=[{"channel": "triple", "failure_type": "TimeoutError"}],
        subgraph_node_count=3,
        subgraph_edge_count=2,
        candidate_path_count=2,
        returned_path_count=1,
        reranking={"provenance": {"status": "completed"}},
    )

    stages = {item["key"]: item for item in trace["stages"]}
    assert trace["contract_version"] == "lightrag-query-trace-v1"
    assert trace["degraded"] is True
    assert stages["entity_retrieval"]["status"] == "completed"
    assert stages["relation_retrieval"]["status"] == "warning"
    assert stages["relation_retrieval"]["failure_channels"] == ["triple"]
    assert stages["chunk_retrieval"]["count"] == 1
    assert stages["path_search"]["count"] == 2
    assert stages["path_reranking"]["count"] == 1


@pytest.mark.asyncio
async def test_projection_target_requires_embedding_model_before_destructive_rebuild():
    service = MilvusGraphService(
        kb_repo=SimpleNamespace(
            get_by_kb_id=AsyncMock(return_value=SimpleNamespace(kb_type="milvus", embedding_model_spec=None))
        )
    )

    with pytest.raises(ValueError, match="embedding_model_spec"):
        await service.ensure_projection_target("kb_test")


def test_graph_vector_store_uses_connection_alias_for_database_selection(monkeypatch):
    """图谱向量库的建库和切库不得落到 pymilvus 默认连接。"""

    calls = []
    store = MilvusGraphVectorStore.__new__(MilvusGraphVectorStore)
    store.connection_alias = "milvus-graph-test"
    store.milvus_uri = "http://milvus:19530"
    store.milvus_token = ""
    store.milvus_db = "deep_research"

    monkeypatch.setattr(milvus_graph_vector_store_module.connections, "has_connection", lambda alias: False)
    monkeypatch.setattr(
        milvus_graph_vector_store_module.connections,
        "connect",
        lambda **kwargs: calls.append(("connect", kwargs)),
    )
    monkeypatch.setattr(
        milvus_graph_vector_store_module.db,
        "list_database",
        lambda **kwargs: calls.append(("list", kwargs)) or [],
    )
    monkeypatch.setattr(
        milvus_graph_vector_store_module.db,
        "create_database",
        lambda name, **kwargs: calls.append(("create", name, kwargs)),
    )
    monkeypatch.setattr(
        milvus_graph_vector_store_module.db,
        "using_database",
        lambda name, **kwargs: calls.append(("use", name, kwargs)),
    )

    store._init_connection()

    assert calls == [
        ("connect", {"alias": "milvus-graph-test", "uri": "http://milvus:19530", "token": ""}),
        ("list", {"using": "milvus-graph-test"}),
        ("create", "deep_research", {"using": "milvus-graph-test"}),
        ("use", "deep_research", {"using": "milvus-graph-test"}),
    ]


@pytest.mark.asyncio
async def test_pending_entity_vectors_apply_optional_extractive_evidence_summary():
    records = [
        {
            "id": "entity-1",
            "content": "宽带射频收发器",
            "evidence_rows": [{"evidence_id": "relation-mention:9", "text": "频率捷变提高抗干扰能力"}],
        }
    ]
    graph_repo = SimpleNamespace(
        claim_vector_records=AsyncMock(return_value=("lease-1", records)),
        mark_vector_records_indexed=AsyncMock(return_value=["entity-1"]),
        finalize_graph_indexed_chunks=AsyncMock(return_value=1),
    )
    kb_repo = SimpleNamespace(
        get_by_kb_id=AsyncMock(
            return_value=SimpleNamespace(
                kb_type="milvus",
                embedding_model_spec="local:embedding",
                additional_params={
                    "graph_build_config": {
                        "extractor_options": {
                            "retrieval_evidence_summary": {
                                "enabled": True,
                                "model_spec": "local:military-chat",
                            }
                        }
                    }
                },
            )
        )
    )
    vector_store = SimpleNamespace(upsert_graph_records=AsyncMock())

    class Selector:
        options = None
        closed = False

        def __init__(self, options):
            Selector.options = options

        async def enhance_records(self, values):
            enhanced = [dict(value) for value in values]
            enhanced[0]["content"] += "\n检索证据摘录：\n- [relation-mention:9] 频率捷变提高抗干扰能力"
            return enhanced

        async def aclose(self):
            Selector.closed = True

    service = MilvusGraphService(
        kb_id="kb_test",
        kb_repo=kb_repo,
        graph_repo=graph_repo,
        graph_vector_store=vector_store,
        evidence_summary_selector_factory=Selector,
    )

    result = await service.index_pending_graph_vectors("kb_test", record_types=("entity",))

    assert result == {"entity": {"claimed": 1, "indexed": 1, "failed": 0}}
    assert Selector.options["model_spec"] == "local:military-chat"
    assert Selector.closed is True
    assert graph_repo.claim_vector_records.await_args.kwargs["include_evidence_rows"] is True
    indexed = vector_store.upsert_graph_records.await_args.kwargs["records"]
    assert "[relation-mention:9]" in indexed[0]["content"]


def test_normalize_extraction_result_defaults_and_validates_refs():
    result = normalize_extraction_result(
        {
            "entities": [{"text": "张三"}, {"text": "公司"}],
            "relations": [{"source": "张三", "target": "公司", "text": "任职于"}],
        },
        "llm",
    )

    assert result["entities"][0]["label"] == "Entity"
    assert result["relations"][0]["label"] == "RELATED_TO"
    assert result["relations"][0]["source"] == {"text": "张三", "label": "Entity", "attributes": []}
    assert result["metadata"] == {"extractor_type": "llm", "schema_version": 1}


def test_normalize_extraction_result_accepts_llm_nested_relation_entities():
    result = normalize_extraction_result(
        {
            "relations": [
                {
                    "source": {
                        "text": "张三",
                        "label": "Person",
                        "attributes": [{"text": "工程师", "label": "Occupation"}],
                    },
                    "target": {"text": "公司", "label": "Organization"},
                    "text": "任职于",
                    "label": "WORKS_AT",
                }
            ]
        },
        "llm",
    )

    assert result["entities"] == [
        {"text": "张三", "label": "Person", "attributes": [{"text": "工程师", "label": "Occupation"}]},
        {"text": "公司", "label": "Organization", "attributes": []},
    ]
    assert result["relations"][0]["source"]["attributes"] == [{"text": "工程师", "label": "Occupation"}]
    assert result["relations"][0]["target"] == {"text": "公司", "label": "Organization", "attributes": []}


def test_normalize_extraction_result_governs_claims_and_military_value_metadata():
    relations = [
        {
            "source": "A",
            "target": "B",
            "text": f"探索关系 {index}",
            "label": "RELATED_TO",
            "claim_level": "Hypothesis",
            "confidence": -1,
            "reasoning_basis": "存在互补机理",
            "expected_capability_gain": "提高复杂环境适应性",
            "uncertainty": "尚缺少联合验证",
        }
        for index in range(4)
    ]
    relations.insert(
        0,
        {
            "source": "A",
            "target": "B",
            "text": "直接关系",
            "claim_level": "Fact",
            "confidence": 2,
            "military_value_dimensions": ["复杂对抗环境适应性", "非法维度"],
        },
    )

    result = normalize_extraction_result(
        {"entities": [{"text": "A"}, {"text": "B"}], "relations": relations},
        "llm",
        {"max_hypotheses_per_chunk": 3},
    )

    fact = result["relations"][0]
    assert fact["claim_level"] == "Inference"
    assert fact["confidence"] == 1.0
    assert fact["military_value_dimensions"] == ["复杂对抗环境适应性"]
    hypotheses = [relation for relation in result["relations"] if relation["claim_level"] == "Hypothesis"]
    assert len(hypotheses) == 3
    assert all(relation["label"] == "PREDICTED_LINK" for relation in hypotheses)
    assert all(relation["expert_review_required"] for relation in hypotheses)
    assert all(relation["confidence"] == 0.0 for relation in hypotheses)


def test_normalize_extraction_result_drops_disabled_or_unsupported_hypotheses():
    payload = {
        "entities": [{"text": "A"}, {"text": "B"}, {"text": "孤立实体"}],
        "relations": [
            {
                "source": "A",
                "target": "B",
                "text": "证据关系",
                "claim_level": "Fact",
                "evidence_quote": "A 支撑 B",
            },
            {"source": "A", "target": "B", "text": "探索关系", "claim_level": "Hypothesis"},
            {"source": "A", "target": "孤立实体", "text": "无支撑探索", "claim_level": "Hypothesis"},
        ],
    }

    disabled = normalize_extraction_result(
        payload,
        "llm",
        {"enable_hypothesis_extraction": False, "max_hypotheses_per_chunk": 3},
    )
    enabled = normalize_extraction_result(payload, "llm", {"max_hypotheses_per_chunk": 3})

    assert [relation["text"] for relation in disabled["relations"]] == ["证据关系"]
    assert [relation["text"] for relation in enabled["relations"]] == ["证据关系", "探索关系"]


def test_build_graph_payload_preserves_relation_quality_metadata():
    normalized = normalize_extraction_result(
        {
            "entities": [{"text": "技术 A", "label": "Technology"}, {"text": "能力 B", "label": "Capability"}],
            "relations": [
                {
                    "source": "技术 A",
                    "target": "能力 B",
                    "text": "支撑",
                    "claim_level": "Fact",
                    "confidence": 0.91,
                    "evidence_quote": "技术 A 提升能力 B",
                    "military_value_dimensions": ["复杂对抗环境适应性"],
                    "expected_capability_gain": "提升抗干扰能力",
                }
            ],
        },
        "llm",
    )

    relation = build_graph_payload(normalized)["relations"][0]

    assert relation["claim_level"] == "Fact"
    assert relation["confidence"] == 0.91
    assert relation["evidence_quote"] == "技术 A 提升能力 B"
    assert relation["military_value_dimensions"] == ["复杂对抗环境适应性"]
    assert relation["expected_capability_gain"] == "提升抗干扰能力"


def test_graph_records_use_llm_canonical_name_without_changing_raw_mention_span():
    mention = "本文提出的复杂电磁环境宽带协同感知方法"
    normalized = normalize_extraction_result(
        {
            "entities": [
                {
                    "text": mention,
                    "label": "KeyTechnology",
                    "start": 0,
                    "end": len(mention),
                    "canonical_name": "复杂电磁环境宽带协同感知技术",
                    "raw_name": mention,
                    "aliases": ["宽带协同感知"],
                    "naming_rationale": "去除论文句式，保留环境限定与核心对象。",
                }
            ],
            "relations": [],
        },
        "lightrag_primary",
    )
    payload = build_graph_payload(normalized)
    service = MilvusGraphService.__new__(MilvusGraphService)

    records = service._build_entity_records("kb_test", payload["entities"], payload)

    assert payload["entities"][0]["text"] == mention
    assert records[0]["mention_text"] == mention
    assert records[0]["start_char"] == 0
    assert records[0]["end_char"] == len(mention)
    assert records[0]["name"] == "复杂电磁环境宽带协同感知技术"
    assert records[0]["normalized_name"] == "复杂电磁环境宽带协同感知技术"
    assert records[0]["aliases"] == ["宽带协同感知", mention]
    assert records[0]["naming_rationale"].startswith("去除论文句式")
    assert "实体名称：复杂电磁环境宽带协同感知技术" in records[0]["content"]
    assert "实体类型：KeyTechnology" in records[0]["content"]
    assert "语义角色：technology" in records[0]["content"]
    assert "别名：宽带协同感知" in records[0]["content"]
    assert "命名依据：去除论文句式" in records[0]["content"]


# 真实案例的形状：模型把一整段摘要正文当成了实体。原文 1672 字符，而列是 varchar(512)。
ABSTRACT_PARAGRAPH = (
    "Reliable engine-weight estimation at the conceptual design stage is critical to the "
    "development of new aircraft engines. It helps to identify the best engine concept "
    "amongst several candidates. "
) * 6


def test_normalize_extraction_result_drops_over_long_entity_and_its_relations():
    """超长实体必须被丢弃，而不是让同一批的好实体一起陪葬。

    原来做不到这一点：upsert_chunk_graph 把一个分块的所有实体放进一条多行 INSERT，
    一个值超过列长度，整批被 PostgreSQL 拒绝，该分块的图谱全部丢失且永远停在 pending。
    """
    result = normalize_extraction_result(
        {
            "entities": [
                {"text": "WATE", "label": "Tool"},
                {"text": ABSTRACT_PARAGRAPH, "label": "Abstract"},
                {"text": "NASA", "label": "Organization"},
            ],
            "relations": [
                {"source": "WATE", "target": "NASA", "text": "由...开发", "label": "DEVELOPED_BY"},
                {"source": "WATE", "target": ABSTRACT_PARAGRAPH, "text": "has abstract"},
            ],
        },
        "llm",
    )

    assert [entity["text"] for entity in result["entities"]] == ["WATE", "NASA"]
    assert [(relation["source"]["text"], relation["target"]["text"]) for relation in result["relations"]] == [
        ("WATE", "NASA")
    ]
    assert result["metadata"]["dropped_entities"] == 1
    assert result["metadata"]["dropped_relations"] == 1


def test_normalize_extraction_result_drops_pure_ocr_symbols_but_keeps_technical_symbols():
    result = normalize_extraction_result(
        {
            "entities": [
                {"id": "junk", "text": "%’(", "label": "ApplicationScenario"},
                {"id": "cpp", "text": "C++", "label": "AlgorithmModel"},
                {"id": "band", "text": "5G", "label": "KeyTechnology"},
            ],
            "relations": [
                {
                    "source": "cpp",
                    "target": "junk",
                    "text": "排版损伤关系",
                    "label": "APPLIED_TO",
                }
            ],
        },
        "lightrag_llm",
    )

    assert [entity["text"] for entity in result["entities"]] == ["C++", "5G"]
    assert result["relations"] == []
    assert result["metadata"]["dropped_entities"] == 1
    assert result["metadata"]["dropped_relations"] == 1


def test_normalize_extraction_result_drops_over_long_inline_endpoint():
    """关系以内联对象给出实体时，只丢这一条关系，其余照常。"""
    result = normalize_extraction_result(
        {
            "relations": [
                {
                    "source": {"text": "WATE", "label": "Tool"},
                    "target": {"text": ABSTRACT_PARAGRAPH, "label": "Abstract"},
                    "text": "has abstract",
                },
                {
                    "source": {"text": "WATE", "label": "Tool"},
                    "target": {"text": "NASA", "label": "Organization"},
                    "text": "由...开发",
                },
            ]
        },
        "llm",
    )

    assert [entity["text"] for entity in result["entities"]] == ["WATE", "NASA"]
    assert len(result["relations"]) == 1
    assert result["metadata"]["dropped_relations"] == 1


def test_normalize_extraction_result_drops_over_long_label_and_relation_type():
    over_long_label = normalize_extraction_result(
        {"entities": [{"text": "WATE", "label": "X" * (MAX_ENTITY_LABEL_LENGTH + 1)}], "relations": []},
        "llm",
    )
    assert over_long_label["entities"] == []

    over_long_relation_type = normalize_extraction_result(
        {
            "entities": [{"text": "A"}, {"text": "B"}],
            "relations": [{"source": "A", "target": "B", "text": "r", "label": "T" * (MAX_RELATION_TYPE_LENGTH + 1)}],
        },
        "llm",
    )
    assert [entity["text"] for entity in over_long_relation_type["entities"]] == ["A", "B"]
    assert over_long_relation_type["relations"] == []


def test_normalize_extraction_result_always_fits_entity_columns():
    """不变量：规范化后的实体名不会再超过列长度——写入失败的根因就是这个。"""
    result = normalize_extraction_result(
        {"entities": [{"text": ABSTRACT_PARAGRAPH}, {"text": "长" * 600}, {"text": "ok"}], "relations": []},
        "llm",
    )

    assert [entity["text"] for entity in result["entities"]] == ["ok"]
    assert all(len(entity["text"]) <= MAX_ENTITY_NAME_LENGTH for entity in result["entities"])


def test_normalize_extraction_result_counts_dropped_entities_distinctly():
    """同一个越界实体被多条关系引用时，实体数按去重计，关系数按条计。"""
    result = normalize_extraction_result(
        {
            "entities": [{"text": "A"}, {"text": "B"}, {"text": ABSTRACT_PARAGRAPH}],
            "relations": [
                {"source": "A", "target": ABSTRACT_PARAGRAPH, "text": "r1"},
                {"source": "B", "target": ABSTRACT_PARAGRAPH, "text": "r2"},
            ],
        },
        "llm",
    )

    assert [entity["text"] for entity in result["entities"]] == ["A", "B"]
    assert result["relations"] == []
    assert result["metadata"]["dropped_entities"] == 1
    assert result["metadata"]["dropped_relations"] == 2


def test_normalize_extraction_result_drops_relation_with_over_long_ref():
    """关系只以裸字符串引用一个超长名（未出现在 entities[]）时，丢弃该关系而不是让整块失败。"""
    result = normalize_extraction_result(
        {
            "entities": [{"text": "A"}],
            "relations": [{"source": "A", "target": ABSTRACT_PARAGRAPH, "text": "r"}],
        },
        "llm",
    )

    assert [entity["text"] for entity in result["entities"]] == ["A"]
    assert result["relations"] == []
    assert result["metadata"]["dropped_relations"] == 1


def test_normalize_extraction_result_keeps_metadata_clean_without_drops():
    """没有丢弃时不写这两个键，避免改变既有产物的形状。"""
    result = normalize_extraction_result({"entities": [{"text": "A"}], "relations": []}, "llm")

    assert result["metadata"] == {"extractor_type": "llm", "schema_version": 1}


def test_normalize_extraction_result_still_rejects_unknown_ref():
    """丢弃只针对越界实体；引用一个从未出现过的实体仍然是错误，不能被一并静默吞掉。"""
    with pytest.raises(ValueError, match="未找到"):
        normalize_extraction_result(
            {"entities": [{"text": "A"}], "relations": [{"source": "A", "target": "不存在", "text": "r"}]},
            "llm",
        )


def test_normalizer_limits_match_graph_column_lengths():
    """守卫常量必须与列定义一致：列更短则守卫失效，列更长则白丢数据。"""
    assert MAX_ENTITY_NAME_LENGTH == KnowledgeGraphEntity.name.type.length
    assert MAX_ENTITY_NAME_LENGTH == KnowledgeGraphEntity.normalized_name.type.length
    assert MAX_ENTITY_LABEL_LENGTH == KnowledgeGraphEntity.label.type.length
    assert MAX_RELATION_TYPE_LENGTH == KnowledgeGraphTriple.relation_type.type.length


@pytest.mark.parametrize(
    "payload",
    [
        {"entities": [{"text": "张三"}], "relations": [{"source": "张三", "target": "不存在", "text": "关系"}]},
        {"entities": [{"text": ""}], "relations": []},
    ],
)
def test_normalize_extraction_result_rejects_invalid_payload(payload):
    with pytest.raises(ValueError):
        normalize_extraction_result(payload, "llm")


def test_llm_graph_extractor_rejects_custom_prompt():
    extractor = LLMGraphExtractor({"model_spec": "test/model", "prompt": "custom"})

    with pytest.raises(ValueError, match="不支持自定义完整 Prompt"):
        extractor.validate_options()


def test_llm_graph_extractor_defaults_extraction_timeout():
    """不配置时使用适合公网推理模型的安全默认值。"""
    extractor = LLMGraphExtractor({"model_spec": "test/model"})

    assert extractor._resolve_timeout_seconds() == 180.0


@pytest.mark.asyncio
async def test_llm_graph_extractor_passes_configured_timeout_to_model(monkeypatch):
    """抽取超时必须真的传到模型调用上。

    它不能走 model_params：select_model 会把显式 timeout 覆盖到 model_params 之上，
    所以在 model_params 里写 timeout 是无效的，只能由抽取器显式传入。
    """
    captured = {}

    class FakeModel:
        async def call(self, prompt, stream=False):
            return SimpleNamespace(content='{"relations": []}')

    def fake_select_model(**kwargs):
        captured.update(kwargs)
        return FakeModel()

    monkeypatch.setattr("platform_core.knowledge.graphs.extractors.llm.select_model", fake_select_model)
    extractor = LLMGraphExtractor({"model_spec": "test/model", "timeout_seconds": 300})

    await extractor.extract("某型发动机的涵道比设计值为 9.0")

    assert captured["timeout"] == 300.0
    assert captured["model_spec"] == "test/model"


@pytest.mark.asyncio
async def test_llm_graph_extractor_defaults_timeout_when_absent(monkeypatch):
    """不配置超时时，安全默认值也必须真的传到模型调用上。"""
    captured = {}

    class FakeModel:
        async def call(self, prompt, stream=False):
            return SimpleNamespace(content='{"relations": []}')

    def fake_select_model(**kwargs):
        captured.update(kwargs)
        return FakeModel()

    monkeypatch.setattr("platform_core.knowledge.graphs.extractors.llm.select_model", fake_select_model)

    await LLMGraphExtractor({"model_spec": "test/model"}).extract("文本")

    assert captured["timeout"] == 180.0


@pytest.mark.parametrize("value", [300, "300", 600, 0.5])
def test_llm_graph_extractor_accepts_valid_timeout(value):
    """上界 600 与字符串数字都应当被接受（字符串数字与既有 concurrency_count 风格一致）。"""
    extractor = LLMGraphExtractor({"model_spec": "test/model", "timeout_seconds": value})

    extractor.validate_options()

    assert extractor._resolve_timeout_seconds() == float(value)


@pytest.mark.parametrize(
    "bad_value",
    [
        0,
        -1,
        600.0001,
        "abc",
        None,
        "",  # 空字符串
        True,  # bool 是 int 子类，float(True)==1.0 会被区间校验放行
        False,
        float("nan"),  # NaN 让区间比较全部为 False
        "NaN",
        float("inf"),
        10**400,  # 超大整数在 float() 上抛 OverflowError
    ],
    ids=[
        "zero",
        "negative",
        "above_max",
        "text",
        "null",
        "empty",
        "true",
        "false",
        "nan",
        "nan_str",
        "inf",
        "huge_int",
    ],
)
def test_llm_graph_extractor_rejects_invalid_timeout(bad_value):
    """越界、非数字、非有限值与布尔要显式失败。

    这几类如果被静默放行，会变成「配置保存成功、构建时整库全挂」：bool 会配出 1 秒超时，
    NaN/inf 会让每次调用直接报错，超大整数则会在路由兜底分支变成 500 而非 400。
    """
    extractor = LLMGraphExtractor({"model_spec": "test/model", "timeout_seconds": bad_value})

    with pytest.raises(ValueError, match="timeout_seconds"):
        extractor.validate_options()


def test_llm_graph_extractor_appends_schema_to_fixed_prompt():
    extractor = LLMGraphExtractor(
        {
            "model_spec": "test/model",
            "schema": "实体类型只能是 Person 或 Organization",
            "concurrency_count": 5,
            "model_params": {"temperature": 0.1},
        }
    )

    prompt = extractor._build_prompt("张三任职于公司")

    assert "请从下面文本中抽取实体和实体关系" in prompt
    assert "抽取 Schema 约束" in prompt
    assert "不能放宽上述固定质量契约" in prompt
    assert "若 Schema 要求作者、机构、参考文献或证据实体" in prompt
    assert "实体类型只能是 Person 或 Organization" in prompt
    assert "文本：\n张三任职于公司" in prompt


def test_llm_graph_extractor_prompt_enforces_defense_quality_contract():
    prompt = LLMGraphExtractor({"model_spec": "test/model"})._build_prompt("文本")

    for entity_type in ("Concept", "Principle", "Technology", "Capability", "Application"):
        assert entity_type in prompt
    assert "复杂对抗环境适应性" in prompt
    assert "体系集成与互操作性" in prompt
    assert "在内部完成以下检查，但不要输出思考过程" in prompt
    assert "不得从局部实验效果直接外推为工程化、列装或实战能力" in prompt
    assert "机理依据—技术实现—可验证能力收益—装备/系统环节" in prompt
    assert "无法落到研发决策的 low 内容应放入 discarded_noise" in prompt
    assert "最多 2 条高价值探索关系" in prompt
    assert "expert_review_required=true" in prompt


def test_llm_graph_extractor_can_disable_hypothesis_extraction_in_prompt():
    prompt = LLMGraphExtractor(
        {
            "model_spec": "test/model",
            "enable_hypothesis_extraction": False,
            "max_hypotheses_per_chunk": 3,
        }
    )._build_prompt("文本")

    assert "不要输出任何探索性或假设关系" in prompt


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("enable_hypothesis_extraction", "true"),
        ("max_hypotheses_per_chunk", -1),
        ("max_hypotheses_per_chunk", 4),
        ("max_hypotheses_per_chunk", 1.5),
        ("max_hypotheses_per_chunk", True),
    ],
)
def test_llm_graph_extractor_rejects_invalid_hypothesis_options(option, value):
    extractor = LLMGraphExtractor({"model_spec": "test/model", option: value})

    with pytest.raises(ValueError, match=option):
        extractor.validate_options()


def test_llm_graph_extractor_marks_previous_chunks_as_context_only():
    extractor = LLMGraphExtractor({"model_spec": "test/model"})

    prompt = extractor._build_prompt(
        "它采用相控阵天线。",
        chunk_metadata={
            "context_chunks": [{"chunk_id": "chunk_1", "chunk_index": 0, "content": "雷达系统由研究所研制。"}]
        },
    )

    assert "相邻前文" in prompt
    assert "[前文 Chunk 0]\n雷达系统由研究所研制。" in prompt
    assert "当前文本：\n它采用相控阵天线。" in prompt
    assert "跨 Chunk 关系" in prompt
    assert "不要把“它”“该系统”“上述方法”等代词作为实体" in prompt


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("context_window_size", -1),
        ("context_window_size", 6),
        ("context_window_size", 1.5),
        ("context_window_size", True),
        ("context_max_chars", 499),
        ("context_max_chars", 20_001),
        ("context_max_chars", "not-a-number"),
    ],
)
def test_llm_graph_extractor_rejects_invalid_adjacent_context_options(option, value):
    extractor = LLMGraphExtractor({"model_spec": "test/model", option: value})

    with pytest.raises(ValueError, match=option):
        extractor.validate_options()


def test_graph_extractor_factory_supports_v1_and_v2_extractors_and_rejects_spacy():
    assert GraphExtractorFactory.supported_types() == [
        "llm",
        "lightrag_primary",
    ]

    with pytest.raises(ValueError, match="spacy"):
        GraphExtractorFactory.create("spacy", {"model": "zh_core_web_sm"})


@pytest.mark.asyncio
async def test_graph_extraction_retries_twice_before_third_attempt_succeeds(monkeypatch):
    chunk = SimpleNamespace(
        chunk_id="chunk_1",
        file_id="file_1",
        chunk_index=0,
        content="张三任职于公司",
        extraction_result=None,
        graph_extraction_details={"status": "failed", "attempt_count": 3},
    )
    extractor = SimpleNamespace(
        extractor_type="llm",
        extract=AsyncMock(
            side_effect=[
                TimeoutError("timeout"),
                ConnectionError("connection interrupted"),
                {"entities": [], "relations": []},
            ]
        ),
    )
    chunk_repo = SimpleNamespace(
        mark_graph_extraction_pending=AsyncMock(),
        mark_graph_extraction_failed=AsyncMock(),
        update_extraction_result=AsyncMock(),
    )
    service = MilvusGraphService(chunk_repo=chunk_repo)
    monkeypatch.setattr(
        "platform_core.knowledge.graphs.milvus_graph_service.GRAPH_EXTRACTION_RETRY_DELAYS_SECONDS",
        (0, 0),
    )

    result = await service._get_chunk_extraction_result("kb_test", chunk, extractor)

    assert result["metadata"]["extractor_type"] == "llm"
    assert extractor.extract.await_count == 3
    chunk_repo.mark_graph_extraction_pending.assert_awaited_once_with("chunk_1")
    chunk_repo.update_extraction_result.assert_awaited_once_with("chunk_1", result, 3)
    chunk_repo.mark_graph_extraction_failed.assert_not_awaited()


@pytest.mark.asyncio
async def test_graph_extraction_uses_nearest_previous_chunks_with_character_budget():
    chunk = SimpleNamespace(
        chunk_id="chunk_3",
        file_id="file_1",
        chunk_index=3,
        content="它采用相控阵天线。",
        extraction_result=None,
        graph_extraction_details={"status": "pending", "attempt_count": 0},
    )
    previous_chunks = [
        SimpleNamespace(chunk_id="chunk_1", chunk_index=1, content="ABCDE"),
        SimpleNamespace(chunk_id="chunk_2", chunk_index=2, content="123456"),
    ]
    extractor = SimpleNamespace(
        extractor_type="llm",
        options={"context_window_size": 2, "context_max_chars": 7},
        extract=AsyncMock(return_value={"entities": [], "relations": []}),
    )
    chunk_repo = SimpleNamespace(
        list_preceding_chunks=AsyncMock(return_value=previous_chunks),
        mark_graph_extraction_pending=AsyncMock(),
        mark_graph_extraction_failed=AsyncMock(),
        update_extraction_result=AsyncMock(),
    )
    service = MilvusGraphService(chunk_repo=chunk_repo)

    await service._get_chunk_extraction_result("kb_test", chunk, extractor)

    chunk_repo.list_preceding_chunks.assert_awaited_once_with("file_1", 3, 2)
    metadata = extractor.extract.await_args.kwargs["chunk_metadata"]
    assert metadata["context_chunks"] == [
        {"chunk_id": "chunk_1", "chunk_index": 1, "content": "E"},
        {"chunk_id": "chunk_2", "chunk_index": 2, "content": "123456"},
    ]


@pytest.mark.asyncio
async def test_hybrid_extraction_loads_context_from_lightrag_enhancement_budget():
    chunk = SimpleNamespace(chunk_id="chunk_2", file_id="file_1", chunk_index=2)
    previous = [SimpleNamespace(chunk_id="chunk_1", chunk_index=1, content="前文定义了该系统。")]
    chunk_repo = SimpleNamespace(list_preceding_chunks=AsyncMock(return_value=previous))
    extractor = SimpleNamespace(
        extractor_type="lightrag_primary",
        options={
            "primary": {"model_version": "lightrag"},
            "llm_enhancement": {
                "enabled": True,
                "context_window_size": 1,
                "context_max_chars": 500,
            },
        },
    )

    context = await MilvusGraphService(chunk_repo=chunk_repo)._load_preceding_context(chunk, extractor)

    assert context == [{"chunk_id": "chunk_1", "chunk_index": 1, "content": "前文定义了该系统。"}]
    chunk_repo.list_preceding_chunks.assert_awaited_once_with("file_1", 2, 1)


@pytest.mark.asyncio
async def test_v2_graph_extraction_reuses_only_matching_lineage_cache():
    options = {
        "endpoint": "http://ie-extractor:8011",
        "model_version": "lightrag.5-multi-v1",
        "ontology_version": "defense-kg-1.0",
        "pipeline_revision": "hybrid-v2-r1",
    }
    chunk = SimpleNamespace(
        chunk_id="chunk_1",
        file_id="file_1",
        chunk_index=0,
        content="ADRV9009 提升感知能力。",
        document_version=1,
        parser_name="paddlex",
        parser_version="3.1",
        source_metadata={"document_content_hash": "doc-hash"},
        extraction_result={"entities": [], "relations": [], "metadata": {}},
        graph_extraction_details={"status": "succeeded", "attempt_count": 1},
    )
    manifest = build_extraction_cache_manifest(
        chunk=chunk,
        extractor_type="lightrag_primary",
        extractor_options=options,
    )
    attach_extraction_cache_metadata(chunk.extraction_result, manifest)
    extractor = SimpleNamespace(
        extractor_type="lightrag_primary",
        options=options,
        extract=AsyncMock(side_effect=AssertionError("matching cache must be reused")),
    )
    chunk_repo = SimpleNamespace(
        mark_graph_extraction_pending=AsyncMock(),
        mark_graph_extraction_failed=AsyncMock(),
        update_extraction_result=AsyncMock(),
    )

    result = await MilvusGraphService(chunk_repo=chunk_repo)._get_chunk_extraction_result("kb_test", chunk, extractor)

    assert result["metadata"]["extraction_cache"]["key"]
    extractor.extract.assert_not_awaited()
    chunk_repo.update_extraction_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_v2_graph_extraction_rebuilds_when_model_lineage_changes():
    old_options = {
        "llm_enhancement": {"enabled": True, "model_spec": "local:lightrag-old"},
        "ontology_version": "defense-kg-1.0",
        "pipeline_revision": "hybrid-v2-r1",
    }
    new_options = {
        **old_options,
        "llm_enhancement": {"enabled": True, "model_spec": "local:lightrag-new"},
    }
    chunk = SimpleNamespace(
        chunk_id="chunk_1",
        file_id="file_1",
        chunk_index=0,
        content="ADRV9009 提升感知能力。",
        document_version=1,
        parser_name="paddlex",
        parser_version="3.1",
        source_metadata={"document_content_hash": "doc-hash"},
        extraction_result={"entities": [], "relations": [], "metadata": {}},
        graph_extraction_details={"status": "succeeded", "attempt_count": 1},
    )
    attach_extraction_cache_metadata(
        chunk.extraction_result,
        build_extraction_cache_manifest(
            chunk=chunk,
            extractor_type="lightrag_primary",
            extractor_options=old_options,
        ),
    )
    extractor = SimpleNamespace(
        extractor_type="lightrag_primary",
        options=new_options,
        extract=AsyncMock(return_value={"entities": [], "relations": [], "metadata": {}}),
    )
    chunk_repo = SimpleNamespace(
        mark_graph_extraction_pending=AsyncMock(),
        mark_graph_extraction_failed=AsyncMock(),
        update_extraction_result=AsyncMock(),
    )

    result = await MilvusGraphService(chunk_repo=chunk_repo)._get_chunk_extraction_result("kb_test", chunk, extractor)

    extractor.extract.assert_awaited_once()
    chunk_repo.update_extraction_result.assert_awaited_once_with("chunk_1", result, 1)
    assert result["metadata"]["extraction_cache"]["manifest"]["model_versions"]["lightrag_primary"] == (
        "local:lightrag-new"
    )


@pytest.mark.asyncio
async def test_v2_batch_extraction_only_sends_cache_misses_and_preserves_chunk_order():
    options = {
        "endpoint": "http://ie-extractor:8011",
        "model_version": "lightrag.5-multi-v1",
        "ontology_version": "defense-kg-1.0",
        "pipeline_revision": "hybrid-v2-r1",
        "context_window_size": 0,
        "extraction_options": {"batch_size": 4},
    }
    chunks = [
        SimpleNamespace(
            chunk_id=f"chunk_{index}",
            file_id="file_1",
            chunk_index=0,
            content=f"文本 {index}",
            document_version=1,
            parser_name="paddlex",
            parser_version="3.1",
            source_metadata={"document_content_hash": "doc-hash"},
            extraction_result=None,
            graph_extraction_details={"status": "pending", "attempt_count": 0},
        )
        for index in range(1, 4)
    ]
    chunks[0].extraction_result = {"entities": [], "relations": [], "metadata": {}}
    attach_extraction_cache_metadata(
        chunks[0].extraction_result,
        build_extraction_cache_manifest(
            chunk=chunks[0],
            extractor_type="lightrag_primary",
            extractor_options=options,
        ),
    )
    batch_outputs = [
        {"entities": [], "relations": [], "metadata": {"block": "chunk_2"}},
        {"entities": [], "relations": [], "metadata": {"block": "chunk_3"}},
    ]
    extractor = SimpleNamespace(
        extractor_type="lightrag_primary",
        options=options,
        extract_batch=AsyncMock(return_value=batch_outputs),
        extract=AsyncMock(side_effect=AssertionError("多块未命中必须走批量接口")),
    )
    persisted = {}

    async def update_extraction_result(chunk_id, result, attempt):
        persisted[chunk_id] = (result, attempt)

    chunk_repo = SimpleNamespace(
        mark_graph_extraction_pending=AsyncMock(),
        mark_graph_extraction_failed=AsyncMock(),
        update_extraction_result=AsyncMock(side_effect=update_extraction_result),
    )
    service = MilvusGraphService(chunk_repo=chunk_repo)

    results = await service._get_chunk_extraction_results("kb_test", chunks, extractor)

    batch_inputs = extractor.extract_batch.await_args.args[0]
    assert [item.chunk_metadata["chunk_id"] for item in batch_inputs] == ["chunk_2", "chunk_3"]
    assert [result["metadata"].get("block") for result in results] == [None, "chunk_2", "chunk_3"]
    assert set(persisted) == {"chunk_2", "chunk_3"}
    assert {attempt for _, attempt in persisted.values()} == {1}
    extractor.extract.assert_not_awaited()


@pytest.mark.asyncio
async def test_v2_batch_partial_validation_failure_does_not_overwrite_successful_chunk():
    options = {
        "endpoint": "http://ie-extractor:8011",
        "model_version": "lightrag.5-multi-v1",
        "ontology_version": "defense-kg-1.0",
        "context_window_size": 0,
    }
    chunks = [
        SimpleNamespace(
            chunk_id=f"chunk_{index}",
            file_id="file_1",
            chunk_index=0,
            content=f"文本 {index}",
            extraction_result=None,
            graph_extraction_details={"status": "pending", "attempt_count": 0},
        )
        for index in range(1, 3)
    ]
    extractor = SimpleNamespace(
        extractor_type="lightrag_primary",
        options=options,
        extract_batch=AsyncMock(
            return_value=[
                {"entities": [], "relations": [], "metadata": {"block": "chunk_1"}},
                {"entities": "invalid", "relations": []},
            ]
        ),
        extract=AsyncMock(side_effect=ValueError("single block remains invalid")),
    )
    chunk_repo = SimpleNamespace(
        mark_graph_extraction_pending=AsyncMock(),
        mark_graph_extraction_failed=AsyncMock(),
        update_extraction_result=AsyncMock(),
    )
    service = MilvusGraphService(chunk_repo=chunk_repo)

    results = await service._get_chunk_extraction_results("kb_test", chunks, extractor)

    assert results[0]["metadata"]["block"] == "chunk_1"
    assert isinstance(results[1], ValueError)
    chunk_repo.update_extraction_result.assert_awaited_once()
    assert chunk_repo.update_extraction_result.await_args.args[0] == "chunk_1"
    extractor.extract.assert_awaited_once()
    assert extractor.extract.await_args.kwargs["chunk_metadata"]["chunk_id"] == "chunk_2"
    chunk_repo.mark_graph_extraction_failed.assert_awaited_once_with(
        "chunk_2",
        2,
        "single block remains invalid",
    )


def test_ie_graph_build_batch_size_comes_from_runtime_extraction_options():
    assert (
        MilvusGraphService._get_extraction_batch_size(
            {
                "extractor_type": "lightrag_primary",
                "extractor_options": {"extraction_options": {"batch_size": 16}},
            }
        )
        == 4
    )
    assert (
        MilvusGraphService._get_extraction_batch_size(
            {
                "extractor_type": "lightrag_primary",
                "extractor_options": {"primary": {"extraction_options": {"batch_size": 8}}},
            }
        )
        == 4
    )
    assert (
        MilvusGraphService._get_extraction_batch_size(
            {"extractor_type": "llm", "extractor_options": {"batch_size": 64}}
        )
        == 1
    )


def test_lightrag_primary_batch_size_uses_bounded_agent_parallelism():
    config = {
        "extractor_type": "lightrag_primary",
        "extractor_options": {
            "orchestration_mode": "lightrag_primary",
            "primary": {"extraction_options": {"batch_size": 2}},
            "llm_enhancement": {"concurrency_count": 6},
        },
    }
    oversized = {
        "extractor_type": "lightrag_primary",
        "extractor_options": {
            "orchestration_mode": "lightrag_primary",
            "llm_enhancement": {"concurrency_count": 64},
        },
    }

    assert MilvusGraphService._get_extraction_batch_size(config) == 6
    assert MilvusGraphService._get_extraction_batch_size(oversized) == 8


def test_graph_query_deduplicates_cross_chunk_relation_mentions_by_triple_id():
    duplicate_one = _raw_graph_edge("neo4j-edge-1", "node-a", "node-b")
    duplicate_two = _raw_graph_edge("neo4j-edge-2", "node-a", "node-b")
    duplicate_one["properties"]["triple_id"] = "triple-stable"
    duplicate_two["properties"]["triple_id"] = "triple-stable"
    duplicate_one["properties"].update({"chunk_id": "chunk-1", "file_id": "file-1", "text": "证据一"})
    duplicate_two["properties"].update({"chunk_id": "chunk-2", "file_id": "file-2", "text": "证据二"})
    duplicate_one["properties"].update(
        {
            "claim_level": "Fact",
            "confidence": 0.9,
            "military_value_dimensions": ["复杂对抗环境适应性"],
            "expected_capability_gain": "收益一",
        }
    )
    duplicate_two["properties"].update(
        {
            "claim_level": "Inference",
            "confidence": 0.7,
            "military_value_dimensions": ["体系集成与互操作性"],
            "expected_capability_gain": "收益二",
            "uncertainty": "需联合验证",
            "expert_review_required": True,
        }
    )
    service = MilvusGraphService()

    result = service._process_subgraph_record(
        {
            "nodes": [_raw_graph_node("node-a"), _raw_graph_node("node-b")],
            "edges": [duplicate_one, duplicate_two],
        },
        limit=10,
        kb_id="kb_test",
    )

    assert [edge["id"] for edge in result["edges"]] == ["neo4j-edge-1"]
    assert result["edges"][0]["properties"]["evidence_count"] == 2
    assert result["edges"][0]["properties"]["evidence_chunk_ids"] == ["chunk-1", "chunk-2"]
    assert result["edges"][0]["properties"]["evidence_file_ids"] == ["file-1", "file-2"]
    assert result["edges"][0]["properties"]["evidence_texts"] == ["证据一", "证据二"]
    assert result["edges"][0]["properties"]["claim_level"] == "Inference"
    assert result["edges"][0]["properties"]["confidence"] == 0.7
    assert result["edges"][0]["properties"]["military_value_dimensions"] == [
        "复杂对抗环境适应性",
        "体系集成与互操作性",
    ]
    assert result["edges"][0]["properties"]["expected_capability_gain"] == "收益一；收益二"
    assert result["edges"][0]["properties"]["uncertainty"] == "需联合验证"
    assert result["edges"][0]["properties"]["expert_review_required"] is True


def test_llm_graph_extractor_focuses_on_substantive_defense_research_knowledge():
    prompt = LLMGraphExtractor({"model_spec": "test/model"})._build_prompt("某技术具备进一步评估价值。")

    assert "作用原理/机理" in prompt
    assert "工程约束" in prompt
    assert "成熟度" in prompt
    assert "转化潜力" in prompt
    assert "不得把可能性写成既成事实" in prompt
    assert "不要把宽泛主题、宣传性表述" in prompt


@pytest.mark.asyncio
async def test_graph_path_discovery_uses_semantic_entity_anchors():
    kb = SimpleNamespace(kb_type="milvus", embedding_model_spec="test/embedding")
    vector_store = SimpleNamespace(
        search_entities=AsyncMock(return_value=[{"id": "entity-1", "score": 0.91, "content": "技术 A"}]),
        search_triples=AsyncMock(return_value=[]),
    )
    service = MilvusGraphService(
        kb_id="kb_test",
        kb_repo=SimpleNamespace(get_by_kb_id=AsyncMock(return_value=kb)),
        graph_vector_store=vector_store,
    )
    service.query_seed_subgraph = AsyncMock(
        return_value={
            "nodes": [
                _raw_graph_node("node-a", name="技术 A"),
                _raw_graph_node("node-b", name="能力 B"),
            ],
            "edges": [_raw_graph_edge("edge-a-b", "node-a", "node-b")],
        }
    )
    service.query_seed_subgraph.return_value["nodes"][0]["properties"].update(
        {"entity_id": "entity-1", "label": "技术"}
    )
    service.query_seed_subgraph.return_value["nodes"][0]["type"] = "KeyTechnology"
    service.query_seed_subgraph.return_value["nodes"][1]["properties"]["label"] = "能力"
    service.query_seed_subgraph.return_value["nodes"][1]["type"] = "Capability"

    result = await service.discover_paths(
        query="技术 A",
        max_hops=6,
        max_paths=3,
        include_combinations=False,
    )

    vector_store.search_entities.assert_awaited_once_with(
        kb_id="kb_test",
        query_text="技术 A",
        embedding_model_spec="test/embedding",
        top_k=6,
    )
    vector_store.search_triples.assert_awaited_once_with(
        kb_id="kb_test",
        query_text="技术 A",
        embedding_model_spec="test/embedding",
        top_k=6,
    )
    service.query_seed_subgraph.assert_awaited_once_with(
        "kb_test",
        entity_ids=["entity-1"],
        max_nodes=300,
        max_depth=6,
        entity_only=True,
    )
    assert result["summary"]["retrieval_mode"] == "mix"
    assert result["summary"]["requested_retrieval_mode"] == "mix"
    assert result["summary"]["entity_hit_count"] == 1
    assert result["summary"]["triple_hit_count"] == 0
    assert result["summary"]["fusion_method"] == "reciprocal-rank-fusion-v1"
    assert result["query_plan"]["provenance"]["status"] == "disabled"
    assert result["summary"]["subgraph_node_count"] == 2
    assert result["paths"][0]["nodes"][0]["properties"]["query_relevance"] == 1.0
    assert result["query_analysis"]["analysis_version"] == "defense-requirement-analysis-v2"
    assert result["query_analysis"]["entity_mappings"][0]["entity_id"] == "entity-1"


@pytest.mark.asyncio
async def test_graph_path_discovery_fuses_llm_planned_entity_and_triple_retrieval():
    class _Planner:
        def __init__(self, options):
            self.options = options

        async def plan(self, query):
            return {
                "query": query,
                "low_level_keywords": ["相控阵雷达", "波束形成"],
                "high_level_keywords": ["抗干扰机理"],
                "capability_targets": ["复杂环境感知"],
                "constraints": ["低功耗"],
                "provenance": {"status": "completed"},
            }

        async def aclose(self):
            return None

    kb = SimpleNamespace(kb_type="milvus", embedding_model_spec="test/embedding")
    vector_store = SimpleNamespace(
        search_entities=AsyncMock(return_value=[{"id": "entity-1", "score": 0.9}]),
        search_triples=AsyncMock(
            return_value=[
                {
                    "id": "triple-1",
                    "source_id": "entity-2",
                    "target_id": "entity-1",
                    "score": 0.8,
                }
            ]
        ),
    )
    service = MilvusGraphService(
        kb_id="kb_test",
        kb_repo=SimpleNamespace(get_by_kb_id=AsyncMock(return_value=kb)),
        graph_vector_store=vector_store,
        query_planner_factory=_Planner,
    )
    graph = {
        "nodes": [
            _raw_graph_node("node-a", name="技术 A"),
            _raw_graph_node("node-b", name="能力 B"),
        ],
        "edges": [_raw_graph_edge("edge-a-b", "node-a", "node-b")],
    }
    graph["nodes"][0]["properties"].update({"entity_id": "entity-1", "label": "技术"})
    graph["nodes"][0]["type"] = "KeyTechnology"
    graph["nodes"][1]["properties"].update({"entity_id": "entity-2", "label": "能力"})
    graph["nodes"][1]["type"] = "Capability"
    service.query_seed_subgraph = AsyncMock(return_value=graph)

    result = await service.discover_paths(
        query="复杂环境感知",
        retrieval_mode="hybrid",
        query_enhancement={"enabled": True, "model_spec": "local:model"},
    )

    vector_store.search_entities.assert_awaited_once_with(
        kb_id="kb_test",
        query_text="复杂环境感知；相控阵雷达；波束形成",
        embedding_model_spec="test/embedding",
        top_k=6,
    )
    vector_store.search_triples.assert_awaited_once_with(
        kb_id="kb_test",
        query_text="复杂环境感知；抗干扰机理；低功耗",
        embedding_model_spec="test/embedding",
        top_k=6,
    )
    assert service.query_seed_subgraph.await_args.kwargs["entity_ids"] == ["entity-1", "entity-2"]
    assert result["summary"]["retrieval_mode"] == "hybrid"
    assert result["summary"]["entity_hit_count"] == 1
    assert result["summary"]["triple_hit_count"] == 1
    assert result["summary"]["query_planner_status"] == "completed"
    assert result["query_plan"]["low_level_keywords"] == ["相控阵雷达", "波束形成"]


@pytest.mark.asyncio
async def test_hybrid_graph_path_discovery_runs_entity_and_triple_search_concurrently():
    entity_started = asyncio.Event()
    triple_started = asyncio.Event()

    async def search_entities(**_kwargs):
        entity_started.set()
        await asyncio.wait_for(triple_started.wait(), timeout=0.5)
        return [{"id": "entity-1", "score": 0.9}]

    async def search_triples(**_kwargs):
        triple_started.set()
        await asyncio.wait_for(entity_started.wait(), timeout=0.5)
        return [{"id": "triple-1", "source_id": "entity-1", "target_id": "entity-2", "score": 0.8}]

    kb = SimpleNamespace(kb_type="milvus", embedding_model_spec="test/embedding")
    service = MilvusGraphService(
        kb_id="kb_test",
        kb_repo=SimpleNamespace(get_by_kb_id=AsyncMock(return_value=kb)),
        graph_vector_store=SimpleNamespace(
            search_entities=AsyncMock(side_effect=search_entities),
            search_triples=AsyncMock(side_effect=search_triples),
        ),
    )
    graph = {
        "nodes": [
            _raw_graph_node("node-a", name="技术 A"),
            _raw_graph_node("node-b", name="能力 B"),
        ],
        "edges": [_raw_graph_edge("edge-a-b", "node-a", "node-b")],
    }
    graph["nodes"][0]["properties"].update({"entity_id": "entity-1", "label": "技术"})
    graph["nodes"][0]["type"] = "KeyTechnology"
    graph["nodes"][1]["properties"].update({"entity_id": "entity-2", "label": "能力"})
    graph["nodes"][1]["type"] = "Capability"
    service.query_seed_subgraph = AsyncMock(return_value=graph)

    result = await asyncio.wait_for(service.discover_paths(query="技术 A"), timeout=1)

    assert result["summary"]["requested_retrieval_mode"] == "mix"
    assert result["summary"]["retrieval_mode"] == "mix"
    assert result["summary"]["entity_hit_count"] == 1
    assert result["summary"]["triple_hit_count"] == 1
    assert result["summary"]["retrieval_failures"] == []


@pytest.mark.asyncio
async def test_mix_graph_path_discovery_runs_keyword_and_vector_channels_concurrently():
    entity_started = asyncio.Event()
    triple_started = asyncio.Event()
    keyword_started = asyncio.Event()

    async def wait_for_all():
        await asyncio.wait_for(
            asyncio.gather(entity_started.wait(), triple_started.wait(), keyword_started.wait()),
            timeout=0.5,
        )

    async def search_entities(**_kwargs):
        entity_started.set()
        await wait_for_all()
        return [{"id": "entity-1", "score": 0.9}]

    async def search_triples(**_kwargs):
        triple_started.set()
        await wait_for_all()
        return []

    async def query_nodes(*_args, **_kwargs):
        keyword_started.set()
        await wait_for_all()
        return {
            "nodes": [_raw_graph_node("keyword-node", name="技术 A")],
            "edges": [],
        }

    kb = SimpleNamespace(kb_type="milvus", embedding_model_spec="test/embedding")
    service = MilvusGraphService(
        kb_id="kb_test",
        kb_repo=SimpleNamespace(get_by_kb_id=AsyncMock(return_value=kb)),
        graph_vector_store=SimpleNamespace(
            search_entities=AsyncMock(side_effect=search_entities),
            search_triples=AsyncMock(side_effect=search_triples),
        ),
    )
    seed_graph = {
        "nodes": [_raw_graph_node("seed-node", name="能力 B")],
        "edges": [],
    }
    seed_graph["nodes"][0]["properties"].update({"entity_id": "entity-1", "label": "能力"})
    service.query_seed_subgraph = AsyncMock(return_value=seed_graph)
    service.query_nodes = AsyncMock(side_effect=query_nodes)

    result = await asyncio.wait_for(service.discover_paths(query="技术 A", retrieval_mode="mix"), timeout=1)

    assert entity_started.is_set() and triple_started.is_set() and keyword_started.is_set()
    assert service.query_nodes.await_count == 1
    assert result["summary"]["retrieval_mode"] == "mix"
    assert result["summary"]["retrieval_failures"] == []


@pytest.mark.parametrize("retrieval_mode", ["mix", "naive"])
@pytest.mark.asyncio
async def test_chunk_graph_path_discovery_adds_accepted_and_pending_entity_anchors(retrieval_mode):
    kb = SimpleNamespace(kb_type="milvus", embedding_model_spec="test/embedding")
    graph_repo = SimpleNamespace(
        list_entity_ids_by_chunk_ids=AsyncMock(
            return_value={"chunk-accepted": ["entity-2"], "chunk-pending": ["entity-1"]}
        )
    )
    chunk_retriever = AsyncMock(
        return_value=[
            {"content": "已审核证据", "metadata": {"chunk_id": "chunk-accepted"}, "score": 0.9},
            {"content": "待审核候选", "metadata": {"chunk_id": "chunk-pending"}, "score": 0.8},
        ]
    )
    vector_store = SimpleNamespace(
        search_entities=AsyncMock(return_value=[]),
        search_triples=AsyncMock(return_value=[]),
    )
    service = MilvusGraphService(
        kb_id="kb_test",
        kb_repo=SimpleNamespace(get_by_kb_id=AsyncMock(return_value=kb)),
        graph_repo=graph_repo,
        graph_vector_store=vector_store,
        chunk_retriever=chunk_retriever,
    )
    graph = {
        "nodes": [
            _raw_graph_node("node-a", name="技术 A"),
            _raw_graph_node("node-b", name="能力 B"),
        ],
        "edges": [_raw_graph_edge("edge-a-b", "node-a", "node-b")],
    }
    graph["nodes"][0]["properties"].update({"entity_id": "entity-1", "label": "技术"})
    graph["nodes"][0]["type"] = "KeyTechnology"
    graph["nodes"][1]["properties"].update({"entity_id": "entity-2", "label": "能力"})
    graph["nodes"][1]["type"] = "Capability"
    service.query_seed_subgraph = AsyncMock(return_value=graph)
    service.query_nodes = AsyncMock(return_value={"nodes": [], "edges": []})

    result = await service.discover_paths(query="复杂环境能力", retrieval_mode=retrieval_mode)

    chunk_retriever.assert_awaited_once_with(kb_id="kb_test", query="复杂环境能力", top_k=6)
    graph_repo.list_entity_ids_by_chunk_ids.assert_awaited_once_with(
        kb_id="kb_test",
        chunk_ids=["chunk-accepted", "chunk-pending"],
        review_statuses=("accepted", "pending"),
    )
    service.query_seed_subgraph.assert_awaited_once()
    assert service.query_seed_subgraph.await_args.kwargs["entity_ids"] == ["entity-2", "entity-1"]
    assert result["summary"]["retrieval_mode"] == retrieval_mode
    assert result["summary"]["chunk_hit_count"] == 2
    assert result["summary"]["chunk_anchor_entity_count"] == 2
    assert result["summary"]["retrieval_failures"] == []
    if retrieval_mode == "naive":
        vector_store.search_entities.assert_not_awaited()
        vector_store.search_triples.assert_not_awaited()


@pytest.mark.asyncio
async def test_mix_graph_uses_unified_relationship_collection_and_pending_chunk_anchors():
    kb = SimpleNamespace(kb_type="milvus", embedding_model_spec="test/embedding")
    graph_repo = SimpleNamespace(
        list_entity_ids_by_chunk_ids=AsyncMock(
            return_value={"chunk-accepted": ["entity-1"], "chunk-pending": ["entity-2"]}
        )
    )
    chunk_retriever = AsyncMock(
        return_value=[
            {"content": "已审核证据", "metadata": {"chunk_id": "chunk-accepted"}, "score": 0.9},
            {"content": "待审核候选", "metadata": {"chunk_id": "chunk-pending"}, "score": 0.8},
        ]
    )
    service = MilvusGraphService(
        kb_id="kb_test",
        kb_repo=SimpleNamespace(get_by_kb_id=AsyncMock(return_value=kb)),
        graph_repo=graph_repo,
        graph_vector_store=SimpleNamespace(
            search_entities=AsyncMock(return_value=[]),
            search_triples=AsyncMock(
                return_value=[
                    {
                        "id": "triple-1",
                        "source_id": "entity-1",
                        "target_id": "entity-2",
                    }
                ]
            ),
        ),
        chunk_retriever=chunk_retriever,
    )
    graph = {
        "nodes": [
            _raw_graph_node("node-a", name="技术 A"),
            _raw_graph_node("node-b", name="能力 B"),
        ],
        "edges": [
            {
                **_raw_graph_edge("edge-a-b", "node-a", "node-b"),
                "properties": {"review_status": "pending"},
            }
        ],
    }
    graph["nodes"][0]["properties"].update({"entity_id": "entity-1", "label": "技术"})
    graph["nodes"][0]["type"] = "KeyTechnology"
    graph["nodes"][1]["properties"].update({"entity_id": "entity-2", "label": "能力"})
    graph["nodes"][1]["type"] = "Capability"
    service.query_seed_subgraph = AsyncMock(return_value=graph)
    service.query_nodes = AsyncMock(return_value={"nodes": [], "edges": []})

    result = await service.discover_paths(
        query="复杂环境能力",
        retrieval_mode="mix",
        review_scope="pending_preview",
    )

    graph_repo.list_entity_ids_by_chunk_ids.assert_awaited_once_with(
        kb_id="kb_test",
        chunk_ids=["chunk-accepted", "chunk-pending"],
        review_statuses=("accepted", "pending"),
    )
    assert service.query_seed_subgraph.await_args.kwargs["entity_ids"] == ["entity-1", "entity-2"]
    assert "review_scope" not in service.query_seed_subgraph.await_args.kwargs
    assert "review_scope" not in service.query_nodes.await_args.kwargs
    assert result["summary"]["review_scope"] == "all"
    assert result["summary"]["triple_hit_count"] == 1
    assert result["summary"]["relationship_vector_hit_count"] == 1
    assert "preview_triple_hit_count" not in result["summary"]
    assert result["summary"]["pending_evidence_path_count"] == 1
    assert result["paths"][0]["pending_evidence"] is True


@pytest.mark.asyncio
async def test_mix_chunk_anchors_interleave_chunks_deduplicate_and_apply_global_limit():
    chunk_ids = ["chunk-a", "chunk-b", "chunk-c"]
    chunk_hits = [{"content": chunk_id, "metadata": {"chunk_id": chunk_id}, "score": 1.0} for chunk_id in chunk_ids]
    anchors = {
        "chunk-a": ["shared", *[f"a-{index}" for index in range(23)]],
        "chunk-b": ["shared", *[f"b-{index}" for index in range(23)]],
        "chunk-c": [f"c-{index}" for index in range(24)],
    }
    graph_repo = SimpleNamespace(list_entity_ids_by_chunk_ids=AsyncMock(return_value=anchors))
    service = MilvusGraphService(
        graph_repo=graph_repo,
        chunk_retriever=AsyncMock(return_value=chunk_hits),
    )

    result = await service._retrieve_mix_chunk_anchors(
        kb_id="kb_test",
        query="抗干扰能力",
        top_k=6,
        review_scope="accepted",
    )

    entity_ids = [item["id"] for item in result["entity_hits"]]
    assert len(entity_ids) == 48
    assert len(set(entity_ids)) == 48
    assert entity_ids[:6] == ["shared", "c-0", "a-0", "b-0", "c-1", "a-1"]
    assert result["entity_hits"][0] == {
        "id": "shared",
        "chunk_id": "chunk-a",
        "chunk_rank": 1,
    }


@pytest.mark.asyncio
async def test_graph_path_discovery_overfetches_then_applies_closed_llm_reranking(monkeypatch):
    captured = {}

    def fake_discover(_graph, query, options):
        captured["candidate_limit"] = options.max_paths
        return {
            "query": query,
            "mode": "requirement_driven",
            "paths": [
                {"path_id": "p1", "score": 3.0, "nodes": [], "relations": [], "relation_ids": []},
                {"path_id": "p2", "score": 2.0, "nodes": [], "relations": [], "relation_ids": []},
                {"path_id": "p3", "score": 1.0, "nodes": [], "relations": [], "relation_ids": []},
            ],
            "candidate_context": {"known_relations": []},
            "summary": {"returned_path_count": 3},
        }

    class Reranker:
        def __init__(self, options):
            captured["options"] = options

        async def rerank(self, *, query, mode, paths):
            captured["rerank_input"] = (query, mode, [path["path_id"] for path in paths])
            return {
                "paths": list(reversed(paths)),
                "provenance": {
                    "reranker_version": "defense-lightrag-path-reranker-v1",
                    "status": "completed",
                    "ranked_count": len(paths),
                },
            }

        async def aclose(self):
            captured["closed"] = True

    monkeypatch.setattr(
        "platform_core.knowledge.graphs.milvus_graph_service.discover_graph_paths",
        fake_discover,
    )
    kb = SimpleNamespace(kb_type="milvus", embedding_model_spec=None)
    service = MilvusGraphService(
        kb_id="kb_test",
        kb_repo=SimpleNamespace(get_by_kb_id=AsyncMock(return_value=kb)),
        path_reranker_factory=Reranker,
    )
    service.query_nodes = AsyncMock(return_value={"nodes": [], "edges": []})

    result = await service.discover_paths(
        query="复杂电磁环境感知",
        mode="requirement_driven",
        max_paths=2,
        path_reranking={"enabled": True, "model_spec": "local:military-chat"},
    )

    assert captured["candidate_limit"] == 6
    assert captured["rerank_input"] == (
        "复杂电磁环境感知",
        "requirement_driven",
        ["p1", "p2", "p3"],
    )
    assert captured["closed"] is True
    assert [path["path_id"] for path in result["paths"]] == ["p3", "p2"]
    assert result["summary"]["returned_path_count"] == 2
    assert result["summary"]["path_reranker_status"] == "completed"


@pytest.mark.asyncio
async def test_graph_path_discovery_falls_back_to_keyword_query_when_vector_search_fails():
    kb = SimpleNamespace(kb_type="milvus", embedding_model_spec="test/embedding")
    service = MilvusGraphService(
        kb_id="kb_test",
        kb_repo=SimpleNamespace(get_by_kb_id=AsyncMock(return_value=kb)),
        graph_vector_store=SimpleNamespace(
            search_entities=AsyncMock(side_effect=RuntimeError("offline")),
            search_triples=AsyncMock(return_value=[]),
        ),
    )
    fallback_graph = {
        "nodes": [
            {**_raw_graph_node("node-a", name="技术 A"), "properties": {"name": "技术 A", "label": "技术"}},
            {**_raw_graph_node("node-b", name="能力 B"), "properties": {"name": "能力 B", "label": "能力"}},
        ],
        "edges": [_raw_graph_edge("edge-a-b", "node-a", "node-b")],
    }
    service.query_nodes = AsyncMock(return_value=fallback_graph)

    result = await service.discover_paths(query="技术 A", max_hops=5)

    service.query_nodes.assert_awaited_once_with(
        "kb_test",
        keyword="技术 A",
        max_depth=3,
        max_nodes=300,
        exclude_chunk=True,
    )
    assert result["summary"]["retrieval_mode"] == "mix"
    assert result["summary"]["retrieval_degraded"] is True
    assert result["summary"]["retrieval_failures"] == [{"channel": "entity", "failure_type": "RuntimeError"}]
    assert result["paths"]


@pytest.mark.asyncio
async def test_keyword_graph_exposes_exact_query_anchor_even_when_entity_is_isolated():
    kb = SimpleNamespace(kb_type="milvus", embedding_model_spec=None)
    service = MilvusGraphService(
        kb_id="kb_test",
        kb_repo=SimpleNamespace(get_by_kb_id=AsyncMock(return_value=kb)),
    )
    isolated = _raw_graph_node("node-anchor", name="分布式自适应规划控制")
    isolated["type"] = "KeyTechnology"
    isolated["properties"].update(
        {
            "entity_id": "anchor-1",
            "name": "分布式自适应规划控制",
            "label": "KeyTechnology",
        }
    )
    service.query_nodes = AsyncMock(return_value={"nodes": [isolated], "edges": []})

    result = await service.discover_paths(query="分布式自适应规划控制")

    assert result["paths"] == []
    assert result["summary"]["keyword_entity_hit_count"] == 1
    assert result["summary"]["explicit_query_anchor_count"] == 1
    assert result["query_anchors"][0]["properties"]["entity_id"] == "anchor-1"
    assert result["query_anchors"][0]["semantic_role"] == "technology"
    assert result["query_anchors"][0]["matched_keyword"] == "分布式自适应规划控制"


@pytest.mark.asyncio
async def test_hybrid_graph_path_discovery_keeps_triple_channel_when_entity_channel_fails():
    kb = SimpleNamespace(kb_type="milvus", embedding_model_spec="test/embedding")
    vector_store = SimpleNamespace(
        search_entities=AsyncMock(side_effect=RuntimeError("entity offline")),
        search_triples=AsyncMock(return_value=[{"id": "triple-1", "source_id": "entity-1", "target_id": "entity-2"}]),
    )
    service = MilvusGraphService(
        kb_id="kb_test",
        kb_repo=SimpleNamespace(get_by_kb_id=AsyncMock(return_value=kb)),
        graph_vector_store=vector_store,
    )
    graph = {
        "nodes": [
            _raw_graph_node("node-a", name="技术 A"),
            _raw_graph_node("node-b", name="能力 B"),
        ],
        "edges": [_raw_graph_edge("edge-a-b", "node-a", "node-b")],
    }
    graph["nodes"][0]["properties"].update({"entity_id": "entity-1", "label": "技术"})
    graph["nodes"][0]["type"] = "KeyTechnology"
    graph["nodes"][1]["properties"].update({"entity_id": "entity-2", "label": "能力"})
    graph["nodes"][1]["type"] = "Capability"
    service.query_seed_subgraph = AsyncMock(return_value=graph)
    service.query_nodes = AsyncMock()

    result = await service.discover_paths(query="技术 A", retrieval_mode="hybrid")

    service.query_seed_subgraph.assert_awaited_once()
    service.query_nodes.assert_not_awaited()
    assert result["summary"]["retrieval_mode"] == "global"
    assert result["summary"]["triple_hit_count"] == 1
    assert result["summary"]["retrieval_degraded"] is True
    assert result["summary"]["retrieval_failures"] == [{"channel": "entity", "failure_type": "RuntimeError"}]


@pytest.mark.asyncio
async def test_graph_build_keeps_extraction_concurrency_full_while_writes_are_blocked(monkeypatch):
    chunks = [
        SimpleNamespace(
            id=index,
            chunk_id=f"chunk_{index}",
            file_id="file_1",
            kb_id="kb_test",
            chunk_index=index,
            content=f"content {index}",
            start_char_pos=0,
            end_char_pos=10,
            extraction_result=None,
            graph_extraction_details={"status": "pending", "attempt_count": 0},
            graph_indexed=False,
        )
        for index in range(1, 7)
    ]
    chunks[0].extraction_result = {"entities": [], "relations": []}
    chunks[0].graph_extraction_details = {"status": "succeeded"}
    kb = SimpleNamespace(
        kb_type="milvus",
        embedding_model_spec="test/embedding",
        additional_params={
            "graph_build_config": {
                "locked": True,
                "extractor_type": "llm",
                "extractor_options": {"model_spec": "test/model", "concurrency_count": 2},
            }
        },
    )
    all_extractions_finished = asyncio.Event()
    release_writes = asyncio.Event()

    class Repo:
        async def get_by_kb_id(self, kb_id):
            return kb

    class ChunkRepo:
        async def count_graph_pending_by_kb_id(self, kb_id):
            return sum(not chunk.graph_indexed for chunk in chunks)

        async def count_graph_indexed_by_kb_id(self, kb_id):
            return sum(chunk.graph_indexed for chunk in chunks)

        async def count_graph_extraction_statuses_by_kb_id(self, kb_id):
            counts = {"pending": 0, "succeeded": 0, "failed": 0}
            for chunk in chunks:
                counts[chunk.graph_extraction_details["status"]] += 1
            return counts

        async def list_graph_pending_by_kb_id(self, kb_id, limit, *, after_id=0):
            return [chunk for chunk in chunks if chunk.id > after_id and not chunk.graph_indexed][:limit]

        async def update_extraction_result(self, chunk_id, extraction_result, attempt_count=1):
            chunk = next(chunk for chunk in chunks if chunk.chunk_id == chunk_id)
            chunk.extraction_result = extraction_result
            chunk.graph_extraction_details = {"status": "succeeded", "attempt_count": attempt_count}

        async def mark_graph_extraction_pending(self, chunk_id):
            chunk = next(chunk for chunk in chunks if chunk.chunk_id == chunk_id)
            chunk.graph_extraction_details = {"status": "pending", "attempt_count": 0}

        async def mark_graph_extraction_failed(self, chunk_id, attempt_count, error):
            chunk = next(chunk for chunk in chunks if chunk.chunk_id == chunk_id)
            chunk.graph_extraction_details = {
                "status": "failed",
                "attempt_count": attempt_count,
                "last_error": error,
            }

        async def get_by_chunk_id(self, chunk_id):
            return next(chunk for chunk in chunks if chunk.chunk_id == chunk_id)

        async def mark_graph_indexed(self, chunk_id, ent_ids=None):
            chunk = next(chunk for chunk in chunks if chunk.chunk_id == chunk_id)
            chunk.graph_indexed = True

        async def mark_graph_structure_indexed(self, chunk_id, ent_ids=None):
            chunk = next(chunk for chunk in chunks if chunk.chunk_id == chunk_id)
            chunk.graph_structure_indexed = True

    class Extractor:
        extractor_type = "llm"
        active = 0
        max_active = 0
        calls = 0
        completed = 0

        async def extract(self, text, *, chunk_metadata=None):
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                await asyncio.sleep(0.01)
                if text == "content 6":
                    raise ConnectionError("extract failed")
                return {"entities": [], "relations": []}
            finally:
                self.active -= 1
                self.completed += 1
                if self.completed == 7:
                    all_extractions_finished.set()

    extractor = Extractor()
    monkeypatch.setattr(GraphExtractorFactory, "create", lambda extractor_type, options: extractor)
    monkeypatch.setattr(
        "platform_core.knowledge.graphs.milvus_graph_service.GRAPH_EXTRACTION_RETRY_DELAYS_SECONDS",
        (0, 0),
    )

    async def wait_for_writes(**kwargs):
        await release_writes.wait()

    class GraphRepo:
        upsert_chunk_graph = AsyncMock(side_effect=wait_for_writes)

        async def claim_vector_records(self, **kwargs):
            return "token", []

        async def count_vector_statuses_by_kb_id(self, kb_id):
            return {"pending": 0, "processing": 0, "indexed": 0, "failed": 0}

        async def finalize_graph_indexed_chunks(self, kb_id):
            finalized = 0
            for chunk in chunks:
                if getattr(chunk, "graph_structure_indexed", False) and not chunk.graph_indexed:
                    chunk.graph_indexed = True
                    finalized += 1
            return finalized

    graph_repo = GraphRepo()
    graph_vector_store = SimpleNamespace(upsert_graph_records=AsyncMock())
    service = MilvusGraphService(
        kb_repo=Repo(),
        chunk_repo=ChunkRepo(),
        graph_repo=graph_repo,
        graph_vector_store=graph_vector_store,
    )
    monkeypatch.setattr(service, "prepare_chunk_graph_records", lambda kb_id, result: ({}, [], []))
    monkeypatch.setattr(service, "project_chunk_graph", lambda *args: None)

    build_task = asyncio.create_task(service.build_pending_chunks("kb_test"))
    await asyncio.wait_for(all_extractions_finished.wait(), timeout=1)

    assert extractor.max_active == 2
    assert extractor.calls == 7
    assert not build_task.done()

    release_writes.set()
    result = await asyncio.wait_for(build_task, timeout=1)

    assert result["success"] == 5
    assert result["extraction_failed"] == 1
    assert result["remaining"] == 1
    assert chunks[-1].graph_extraction_details["status"] == "failed"
    assert chunks[-1].graph_extraction_details["attempt_count"] == 3


@pytest.mark.asyncio
async def test_graph_build_cancellation_stops_backpressured_extraction_queue(monkeypatch):
    chunks = [
        SimpleNamespace(
            id=index,
            chunk_id=f"chunk_{index}",
            file_id="file_1",
            kb_id="kb_test",
            chunk_index=index,
            content=f"content {index}",
            extraction_result=None,
            graph_indexed=False,
        )
        for index in range(1, 10)
    ]
    kb = SimpleNamespace(
        kb_type="milvus",
        embedding_model_spec="test/embedding",
        additional_params={
            "graph_build_config": {
                "locked": True,
                "extractor_type": "llm",
                "extractor_options": {"model_spec": "test/model", "concurrency_count": 1},
            }
        },
    )
    extraction_started = asyncio.Event()
    never_finish = asyncio.Event()

    class Repo:
        async def get_by_kb_id(self, kb_id):
            return kb

    class ChunkRepo:
        async def count_graph_pending_by_kb_id(self, kb_id):
            return len(chunks)

        async def count_graph_indexed_by_kb_id(self, kb_id):
            return 0

        async def list_graph_pending_by_kb_id(self, kb_id, limit, *, after_id=0):
            return [chunk for chunk in chunks if chunk.id > after_id][:limit]

    class Extractor:
        extractor_type = "llm"

        async def extract(self, text, *, chunk_metadata=None):
            extraction_started.set()
            await never_finish.wait()

    class Context:
        cancel_requested = False

        async def raise_if_cancelled(self):
            if self.cancel_requested:
                raise asyncio.CancelledError

        async def set_progress(self, progress, message):
            return None

    context = Context()
    monkeypatch.setattr(GraphExtractorFactory, "create", lambda extractor_type, options: Extractor())
    service = MilvusGraphService(
        kb_repo=Repo(),
        chunk_repo=ChunkRepo(),
        graph_repo=SimpleNamespace(),
        graph_vector_store=SimpleNamespace(),
    )

    build_task = asyncio.create_task(service.build_pending_chunks("kb_test", context=context))
    await asyncio.wait_for(extraction_started.wait(), timeout=1)
    context.cancel_requested = True

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(build_task, timeout=1.5)


@pytest.mark.asyncio
async def test_graph_build_indexes_vectors_after_structure_write(monkeypatch):
    chunk = SimpleNamespace(
        id=1,
        chunk_id="chunk_1",
        file_id="file_1",
        kb_id="kb_test",
        chunk_index=1,
        content="张三任职于公司",
        start_char_pos=0,
        end_char_pos=8,
        document_version=2,
        page_number=5,
        block_type="paragraph",
        heading_path=["3 系统设计", "3.2 信号处理"],
        bbox=[10.0, 20.0, 500.0, 220.0],
        parser_name="paddlex",
        parser_version="3.0",
        extraction_result=normalize_extraction_result(
            {
                "relations": [
                    {
                        "source": {"text": "张三", "label": "Person"},
                        "target": {"text": "公司", "label": "Organization"},
                        "text": "任职于",
                        "label": "WORKS_AT",
                        "claim_level": "Fact",
                        "confidence": 0.92,
                        "evidence_quote": "张三任职于公司",
                        "reasoning_basis": "原文直接陈述",
                        "military_value_dimensions": ["体系集成与互操作性"],
                        "expected_capability_gain": "提升协同效率",
                        "application_direction": "组织协同",
                        "uncertainty": "仅用于验证元数据贯通",
                        "expert_review_required": True,
                    }
                ]
            },
            "llm",
        ),
        graph_structure_indexed=False,
        graph_indexed=False,
    )
    kb = SimpleNamespace(
        kb_type="milvus",
        embedding_model_spec="test/embedding",
        additional_params={
            "graph_build_config": {
                "locked": True,
                "extractor_type": "llm",
                "extractor_options": {"model_spec": "test/model", "concurrency_count": 2},
            }
        },
    )

    class ChunkRepo:
        async def count_graph_pending_by_kb_id(self, kb_id):
            return int(not chunk.graph_indexed)

        async def count_graph_indexed_by_kb_id(self, kb_id):
            return int(chunk.graph_indexed)

        async def count_graph_extraction_statuses_by_kb_id(self, kb_id):
            return {"pending": 0, "succeeded": 1, "failed": 0}

        async def list_graph_pending_by_kb_id(self, kb_id, limit, *, after_id=0):
            return [chunk] if chunk.id > after_id and not chunk.graph_indexed else []

        async def get_by_chunk_id(self, chunk_id):
            return chunk

        async def mark_graph_structure_indexed(self, chunk_id, ent_ids):
            chunk.graph_structure_indexed = True

    class GraphRepo:
        def __init__(self):
            self.pending = False
            self.indexed = False
            self.projection_event = None

        async def upsert_chunk_graph(self, **kwargs):
            self.pending = True
            self.projection_event = kwargs.get("projection_event")

        async def claim_vector_records(self, *, record_type, **kwargs):
            if record_type == "entity" and self.pending:
                self.pending = False
                return "token", [{"id": "entity_1", "content": "张三"}]
            return "token", []

        async def mark_vector_records_indexed(self, **kwargs):
            self.indexed = True

        async def mark_vector_records_failed(self, **kwargs):
            raise AssertionError("vector indexing should succeed")

        async def count_vector_statuses_by_kb_id(self, kb_id):
            return {
                "pending": int(self.pending),
                "processing": 0,
                "indexed": int(self.indexed),
                "failed": 0,
            }

        async def finalize_graph_indexed_chunks(self, kb_id):
            if chunk.graph_structure_indexed and self.indexed:
                chunk.graph_indexed = True
                return 1
            return 0

    graph_repo = GraphRepo()
    vector_store = SimpleNamespace(upsert_graph_records=AsyncMock())
    service = MilvusGraphService(
        kb_repo=SimpleNamespace(get_by_kb_id=AsyncMock(return_value=kb)),
        chunk_repo=ChunkRepo(),
        graph_repo=graph_repo,
        graph_vector_store=vector_store,
    )
    monkeypatch.setattr(
        service,
        "prepare_chunk_graph_records",
        lambda kb_id, result: ({}, [{"entity_id": "entity_1"}], []),
    )
    project_chunk_graph = MagicMock()
    monkeypatch.setattr(service, "project_chunk_graph", project_chunk_graph)

    result = await service.build_pending_chunks("kb_test")

    assert result == {
        "kb_id": "kb_test",
        "success": 1,
        "failed": 0,
        "extraction_failed": 0,
        "write_failed": 0,
        "remaining": 0,
        "batch_remaining": 0,
        "retryable_remaining": 0,
        "vector_failed": 0,
        "verified_facts": 0,
        "evidence_review_required": 0,
    }
    project_chunk_graph.assert_not_called()
    assert graph_repo.projection_event is not None
    assert graph_repo.projection_event["payload"]["kb_id"] == "kb_test"
    assert graph_repo.projection_event["payload"]["chunk"]["chunk_id"] == "chunk_1"
    vector_store.upsert_graph_records.assert_awaited_once()
    assert chunk.graph_structure_indexed is True
    assert chunk.graph_indexed is True


@pytest.mark.asyncio
async def test_graph_build_fails_after_three_vector_attempts(monkeypatch):
    chunk = SimpleNamespace(
        id=1,
        chunk_id="chunk_1",
        file_id="file_1",
        kb_id="kb_test",
        chunk_index=1,
        content="content",
        start_char_pos=0,
        end_char_pos=7,
        extraction_result={"entities": [], "relations": [], "metadata": {"extractor_type": "llm"}},
        graph_structure_indexed=False,
        graph_indexed=False,
    )
    kb = SimpleNamespace(
        kb_type="milvus",
        embedding_model_spec="test/embedding",
        additional_params={
            "graph_build_config": {
                "locked": True,
                "extractor_type": "llm",
                "extractor_options": {"model_spec": "test/model", "concurrency_count": 1},
            }
        },
    )

    class ChunkRepo:
        async def count_graph_pending_by_kb_id(self, kb_id):
            return 1

        async def count_graph_indexed_by_kb_id(self, kb_id):
            return 0

        async def count_graph_extraction_statuses_by_kb_id(self, kb_id):
            return {"pending": 0, "succeeded": 1, "failed": 0}

        async def list_graph_pending_by_kb_id(self, kb_id, limit, *, after_id=0):
            return [chunk] if chunk.id > after_id else []

        async def get_by_chunk_id(self, chunk_id):
            return chunk

        async def mark_graph_structure_indexed(self, chunk_id, ent_ids):
            chunk.graph_structure_indexed = True

    class GraphRepo:
        attempts = 0
        status = "pending"

        async def upsert_chunk_graph(self, **kwargs):
            return None

        async def claim_vector_records(self, *, record_type, **kwargs):
            if record_type != "entity" or self.status != "pending":
                return "token", []
            self.status = "processing"
            self.attempts += 1
            return "token", [{"id": "entity_1", "content": "entity"}]

        async def mark_vector_records_indexed(self, **kwargs):
            raise AssertionError("vector indexing should fail")

        async def mark_vector_records_failed(self, **kwargs):
            self.status = "failed" if self.attempts >= 3 else "pending"

        async def count_vector_statuses_by_kb_id(self, kb_id):
            return {
                "pending": int(self.status == "pending"),
                "processing": int(self.status == "processing"),
                "indexed": 0,
                "failed": int(self.status == "failed"),
            }

        async def finalize_graph_indexed_chunks(self, kb_id):
            return 0

    graph_repo = GraphRepo()
    service = MilvusGraphService(
        kb_repo=SimpleNamespace(get_by_kb_id=AsyncMock(return_value=kb)),
        chunk_repo=ChunkRepo(),
        graph_repo=graph_repo,
        graph_vector_store=SimpleNamespace(upsert_graph_records=AsyncMock(side_effect=RuntimeError("embed failed"))),
    )
    monkeypatch.setattr(
        service,
        "prepare_chunk_graph_records",
        lambda kb_id, result: ({}, [{"entity_id": "e"}], []),
    )
    monkeypatch.setattr(service, "project_chunk_graph", lambda *args: None)

    with pytest.raises(RuntimeError, match="vector_failed=1"):
        await service.build_pending_chunks("kb_test")

    assert graph_repo.attempts == 3


@pytest.mark.asyncio
async def test_graph_reconcile_skips_completed_structure(monkeypatch):
    chunk = SimpleNamespace(
        id=1,
        chunk_id="chunk_1",
        graph_structure_indexed=True,
        graph_indexed=False,
        extraction_result={"entities": [], "relations": []},
    )
    kb = SimpleNamespace(
        kb_type="milvus",
        embedding_model_spec="test/embedding",
        additional_params={
            "graph_build_config": {
                "locked": True,
                "extractor_type": "llm",
                "extractor_options": {"model_spec": "test/model", "concurrency_count": 1},
            }
        },
    )

    class ChunkRepo:
        async def count_graph_pending_by_kb_id(self, kb_id):
            return int(not chunk.graph_indexed)

        async def count_graph_indexed_by_kb_id(self, kb_id):
            return int(chunk.graph_indexed)

        async def count_graph_extraction_statuses_by_kb_id(self, kb_id):
            return {"pending": 0, "succeeded": 1, "failed": 0}

        async def list_graph_pending_by_kb_id(self, kb_id, limit, *, after_id=0):
            return [chunk] if chunk.id > after_id else []

    class GraphRepo:
        pending = True

        async def upsert_chunk_graph(self, **kwargs):
            raise AssertionError("reconcile must not rewrite graph structure")

        async def claim_vector_records(self, *, record_type, **kwargs):
            if record_type == "entity" and self.pending:
                self.pending = False
                return "token", [{"id": "entity_1", "content": "entity"}]
            return "token", []

        async def mark_vector_records_indexed(self, **kwargs):
            return None

        async def mark_vector_records_failed(self, **kwargs):
            raise AssertionError("vector indexing should succeed")

        async def count_vector_statuses_by_kb_id(self, kb_id):
            return {"pending": int(self.pending), "processing": 0, "indexed": 1, "failed": 0}

        async def finalize_graph_indexed_chunks(self, kb_id):
            chunk.graph_indexed = True
            return 1

    service = MilvusGraphService(
        kb_repo=SimpleNamespace(get_by_kb_id=AsyncMock(return_value=kb)),
        chunk_repo=ChunkRepo(),
        graph_repo=GraphRepo(),
        graph_vector_store=SimpleNamespace(upsert_graph_records=AsyncMock()),
    )
    monkeypatch.setattr(
        service,
        "prepare_chunk_graph_records",
        MagicMock(side_effect=AssertionError("must not write")),
    )

    result = await service.build_pending_chunks("kb_test")

    assert result["success"] == 1
    service.prepare_chunk_graph_records.assert_not_called()


@pytest.mark.asyncio
async def test_drain_pending_graph_vectors_does_not_enter_extraction_pipeline():
    graph_repo = SimpleNamespace(
        count_vector_statuses_by_kb_id=AsyncMock(
            return_value={"pending": 0, "processing": 0, "indexed": 3, "failed": 0}
        ),
        finalize_graph_indexed_chunks=AsyncMock(return_value=2),
    )
    service = MilvusGraphService(graph_repo=graph_repo)
    service.index_pending_graph_vectors = AsyncMock(
        side_effect=[
            {
                "entity": {"claimed": 2, "indexed": 2, "failed": 0},
                "triple": {"claimed": 1, "indexed": 1, "failed": 0},
            },
            {
                "entity": {"claimed": 0, "indexed": 0, "failed": 0},
                "triple": {"claimed": 0, "indexed": 0, "failed": 0},
            },
        ]
    )

    result = await service.drain_pending_graph_vectors("kb_test")

    assert result == {
        "kb_id": "kb_test",
        "batches": 1,
        "entity": {"claimed": 2, "indexed": 2, "failed": 0},
        "triple": {"claimed": 1, "indexed": 1, "failed": 0},
        "finalized_chunks": 2,
        "vector_counts": {"pending": 0, "processing": 0, "indexed": 3, "failed": 0},
    }
    assert service.index_pending_graph_vectors.await_count == 2
    graph_repo.finalize_graph_indexed_chunks.assert_awaited_once_with("kb_test")


@pytest.mark.asyncio
async def test_vector_index_race_removes_relation_that_became_inactive(monkeypatch):
    chunk = SimpleNamespace(
        id=1,
        chunk_id="chunk_1",
        graph_structure_indexed=True,
        graph_indexed=False,
        extraction_result={"entities": [], "relations": []},
    )
    kb = SimpleNamespace(
        kb_type="milvus",
        embedding_model_spec="test/embedding",
        additional_params={
            "graph_build_config": {
                "locked": True,
                "extractor_type": "llm",
                "extractor_options": {"model_spec": "test/model", "concurrency_count": 1},
            }
        },
    )

    class ChunkRepo:
        async def count_graph_pending_by_kb_id(self, kb_id):
            return int(not chunk.graph_indexed)

        async def count_graph_indexed_by_kb_id(self, kb_id):
            return int(chunk.graph_indexed)

        async def count_graph_extraction_statuses_by_kb_id(self, kb_id):
            return {"pending": 0, "succeeded": 1, "failed": 0}

        async def list_graph_pending_by_kb_id(self, kb_id, limit, *, after_id=0):
            return [chunk] if chunk.id > after_id else []

    class GraphRepo:
        pending = True

        async def upsert_chunk_graph(self, **kwargs):
            raise AssertionError("vector repair must not rewrite graph structure")

        async def claim_vector_records(self, *, record_type, **kwargs):
            if record_type == "triple" and self.pending:
                self.pending = False
                return "token", [{"id": "triple_inactive", "content": "stale relation"}]
            return "token", []

        async def mark_vector_records_indexed(self, **kwargs):
            # 权威关系在 Milvus upsert 期间失效，Repository 拒绝把它重新标为 indexed。
            return []

        async def mark_vector_records_failed(self, **kwargs):
            raise AssertionError("vector indexing should succeed before lifecycle race is detected")

        async def count_vector_statuses_by_kb_id(self, kb_id):
            return {"pending": int(self.pending), "processing": 0, "indexed": 0, "failed": 0}

        async def finalize_graph_indexed_chunks(self, kb_id):
            chunk.graph_indexed = True
            return 1

    vector_store = SimpleNamespace(
        upsert_graph_records=AsyncMock(),
        delete_graph_records=AsyncMock(),
    )
    service = MilvusGraphService(
        kb_repo=SimpleNamespace(get_by_kb_id=AsyncMock(return_value=kb)),
        chunk_repo=ChunkRepo(),
        graph_repo=GraphRepo(),
        graph_vector_store=vector_store,
    )
    monkeypatch.setattr(
        service,
        "prepare_chunk_graph_records",
        MagicMock(side_effect=AssertionError("must not write")),
    )

    result = await service.build_pending_chunks("kb_test")

    assert result["success"] == 1
    vector_store.upsert_graph_records.assert_awaited_once()
    vector_store.delete_graph_records.assert_awaited_once_with(
        "kb_test",
        entity_ids=[],
        triple_ids=["triple_inactive"],
    )
    service.prepare_chunk_graph_records.assert_not_called()


@pytest.mark.asyncio
async def test_milvus_graph_service_configure_rejects_spacy():
    kb = SimpleNamespace(kb_type="milvus", additional_params={})

    class Repo:
        async def get_by_kb_id(self, kb_id):
            return kb

        async def update(self, kb_id, data):
            raise AssertionError("unsupported extractor should not be persisted")

    service = MilvusGraphService(kb_repo=Repo())

    with pytest.raises(ValueError, match="不支持的图谱抽取器类型"):
        await service.configure(
            "kb_test",
            extractor_type="spacy",
            extractor_options={"model": "zh_core_web_sm"},
            created_by="user_1",
        )


@pytest.mark.asyncio
async def test_milvus_graph_service_configure_persists_updated_concurrency():
    kb = SimpleNamespace(
        kb_type="milvus",
        additional_params={
            "graph_build_config": {
                "locked": True,
                "extractor_type": "llm",
                "extractor_options": {"model_spec": "test/model", "concurrency_count": 5},
            }
        },
    )

    class Repo:
        async def get_by_kb_id(self, kb_id):
            return kb

        async def update(self, kb_id, data):
            kb.additional_params = data["additional_params"]
            return kb

    chunk_repo = SimpleNamespace(
        count_by_kb_id=AsyncMock(return_value=0),
        count_graph_pending_by_kb_id=AsyncMock(return_value=0),
        count_graph_indexed_by_kb_id=AsyncMock(return_value=0),
        count_graph_structure_indexed_by_kb_id=AsyncMock(return_value=0),
        count_graph_extraction_statuses_by_kb_id=AsyncMock(return_value={"pending": 0, "succeeded": 0, "failed": 0}),
    )
    graph_repo = SimpleNamespace(
        count_by_kb_id=AsyncMock(return_value=(3, 2)),
        count_vector_statuses_by_kb_id=AsyncMock(
            return_value={"pending": 0, "processing": 0, "indexed": 5, "failed": 0}
        ),
    )
    service = MilvusGraphService(kb_repo=Repo(), chunk_repo=chunk_repo, graph_repo=graph_repo)

    await service.configure(
        "kb_test",
        extractor_type="llm",
        extractor_options={"model_spec": "test/model", "concurrency_count": 9},
        created_by="user_1",
    )
    status = await service.get_status("kb_test")

    assert status["config"]["extractor_options"]["concurrency_count"] == 9
    assert status["entity_count"] == 3
    assert status["relationship_count"] == 2


@pytest.mark.asyncio
async def test_milvus_graph_service_configure_rejects_semantic_change_after_authoritative_write():
    kb = SimpleNamespace(
        kb_type="milvus",
        additional_params={
            "graph_build_config": {
                "locked": True,
                "extractor_type": "llm",
                "extractor_options": {"model_spec": "test/model-v1", "concurrency_count": 5},
            }
        },
    )

    class Repo:
        async def get_by_kb_id(self, kb_id):
            return kb

        async def update(self, kb_id, data):
            raise AssertionError("semantic drift must not be persisted")

    chunk_repo = SimpleNamespace(
        count_graph_structure_indexed_by_kb_id=AsyncMock(return_value=1),
        count_graph_indexed_by_kb_id=AsyncMock(return_value=1),
    )
    service = MilvusGraphService(kb_repo=Repo(), chunk_repo=chunk_repo)

    with pytest.raises(ValueError, match="显式图谱重建"):
        await service.configure(
            "kb_test",
            extractor_type="llm",
            extractor_options={"model_spec": "test/model-v2", "concurrency_count": 5},
            created_by="user_1",
        )

    chunk_repo.count_graph_structure_indexed_by_kb_id.assert_awaited_once_with("kb_test")
    chunk_repo.count_graph_indexed_by_kb_id.assert_awaited_once_with("kb_test")


def test_graph_extraction_runtime_caps_siliconflow_without_rewriting_saved_config():
    """SiliconFlow 的历史高并发配置应当安全执行，且保留原值供界面告警。"""
    config = {
        "extractor_type": "llm",
        "extractor_options": {
            "model_spec": "siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash",
            "concurrency_count": 200,
        },
    }

    runtime = MilvusGraphService._graph_extraction_runtime(config)

    assert runtime == {
        "configured_concurrency_count": 200,
        "effective_concurrency_count": 16,
        "concurrency_limit": 16,
        "concurrency_capped": True,
        "provider_id": "siliconflow-cn",
    }
    assert MilvusGraphService._get_worker_count(config) == 16
    assert config["extractor_options"]["concurrency_count"] == 200


def test_graph_extraction_runtime_uses_safe_defaults_and_generic_ceiling():
    default_config = {
        "extractor_type": "llm",
        "extractor_options": {"model_spec": "test:model"},
    }
    high_config = {
        "extractor_type": "llm",
        "extractor_options": {"model_spec": "local:model", "concurrency_count": 200},
    }

    assert MilvusGraphService._get_worker_count(default_config) == 8
    assert MilvusGraphService._get_worker_count(high_config) == 64


def test_lightrag_primary_runtime_uses_one_outer_worker_and_bounded_agent_slots(monkeypatch):
    monkeypatch.setenv("GRAPH_HYBRID_EXTRACTION_CONCURRENCY", "4")
    config = {
        "extractor_type": "lightrag_primary",
        "extractor_options": {
            "orchestration_mode": "lightrag_primary",
            "llm_enhancement": {
                "model_spec": "siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash",
                "concurrency_count": 6,
            },
        },
    }

    runtime = MilvusGraphService._graph_extraction_runtime(config)

    assert runtime == {
        "configured_concurrency_count": 6,
        "effective_concurrency_count": 6,
        "concurrency_limit": 8,
        "concurrency_capped": False,
        "provider_id": "siliconflow-cn",
        "parallelism_strategy": "bounded_chunk_fanout",
        "extraction_worker_count": 1,
        "agent_parallelism_configured": 6,
        "agent_parallelism_effective": 6,
        "chunk_batch_size": 6,
    }
    assert MilvusGraphService._get_worker_count(config) == 1


@pytest.mark.asyncio
async def test_graph_status_reports_latest_successful_run_as_completed():
    kb = SimpleNamespace(
        kb_type="milvus",
        additional_params={
            "graph_build_config": {
                "locked": True,
                "extractor_type": "llm",
                "extractor_options": {"model_spec": "test/model", "concurrency_count": 5},
            }
        },
    )

    class Repo:
        async def get_by_kb_id(self, kb_id):
            return kb

    class Tasker:
        async def find_task_by_payload(self, *, task_type, payload_match, statuses):
            assert statuses is None
            return SimpleNamespace(status="success", progress=100)

    chunk_repo = SimpleNamespace(
        count_by_kb_id=AsyncMock(return_value=10),
        count_graph_pending_by_kb_id=AsyncMock(return_value=0),
        count_graph_indexed_by_kb_id=AsyncMock(return_value=10),
        count_graph_structure_indexed_by_kb_id=AsyncMock(return_value=10),
        count_graph_extraction_statuses_by_kb_id=AsyncMock(return_value={"pending": 0, "succeeded": 10, "failed": 0}),
    )
    graph_repo = SimpleNamespace(
        count_by_kb_id=AsyncMock(return_value=(3, 2)),
        count_vector_statuses_by_kb_id=AsyncMock(
            return_value={"pending": 0, "processing": 0, "indexed": 5, "failed": 0}
        ),
    )
    service = MilvusGraphService(kb_repo=Repo(), chunk_repo=chunk_repo, graph_repo=graph_repo)

    status = await service.get_status("kb_test", tasker=Tasker())

    assert status["build_task_status"] == "completed"
    assert status["build_task_progress"] == 100
    assert status["pipeline_stages"]["contract_version"] == "lightrag-graph-pipeline-v1"
    assert [item["key"] for item in status["pipeline_stages"]["stages"]] == [
        "document_parse",
        "information_extraction",
        "entity_alignment",
        "authoritative_commit",
        "graph_projection",
        "vector_projection",
    ]


def test_milvus_graph_service_writes_chunk_entity_and_relation():
    tx = MagicMock()
    session = MagicMock()
    session.__enter__.return_value = session
    session.execute_write.side_effect = lambda func: func(tx)
    driver = MagicMock()
    driver.session.return_value = session
    connection = SimpleNamespace(driver=driver)
    service = MilvusGraphService(neo4j_connection=connection)
    chunk = SimpleNamespace(
        chunk_id="chunk_1",
        file_id="file_1",
        kb_id="kb_test",
        chunk_index=1,
        content="张三任职于公司",
        start_char_pos=0,
        end_char_pos=8,
        document_version=2,
        page_number=5,
        block_type="paragraph",
        heading_path=["3 系统设计", "3.2 信号处理"],
        bbox=[10.0, 20.0, 500.0, 220.0],
        parser_name="paddlex",
        parser_version="3.0",
    )

    entities, triples = service.write_chunk_graph(
        "kb_test",
        chunk,
        normalize_extraction_result(
            {
                "relations": [
                    {
                        "source": {
                            "text": "张三",
                            "label": "Person",
                            "attributes": [{"text": "工程师", "label": "Occupation"}],
                        },
                        "target": {"text": "公司", "label": "Organization"},
                        "text": "任职于",
                        "label": "WORKS_AT",
                        "claim_level": "Fact",
                        "confidence": 0.92,
                        "evidence_quote": "张三任职于公司",
                        "reasoning_basis": "原文直接陈述",
                        "military_value_dimensions": ["体系集成与互操作性"],
                        "expected_capability_gain": "提升协同效率",
                        "application_direction": "组织协同",
                        "uncertainty": "仅用于验证元数据贯通",
                        "expert_review_required": True,
                    }
                ],
            },
            "llm",
        ),
    )

    assert [entity["name"] for entity in entities] == ["张三", "公司"]
    assert {entity["label"] for entity in entities} == {"Person", "Organization"}
    assert triples[0]["relation_type"] == "WORKS_AT"
    queries = [call.args[0] for call in tx.run.call_args_list]
    assert any("MERGE (c:Chunk:MilvusKB:`kb_test`" in query for query in queries)
    assert any("MERGE (e:Entity:MilvusKB:`kb_test`" in query for query in queries)
    assert any("MERGE (source)-[r:RELATION" in query for query in queries)
    chunk_call = next(call for call in tx.run.call_args_list if "MERGE (c:Chunk" in call.args[0])
    assert chunk_call.kwargs["document_version"] == 2
    assert chunk_call.kwargs["page_number"] == 5
    assert chunk_call.kwargs["heading_path"] == ["3 系统设计", "3.2 信号处理"]
    assert chunk_call.kwargs["bbox"] == [10.0, 20.0, 500.0, 220.0]
    assert chunk_call.kwargs["parser_name"] == "paddlex"
    assert chunk_call.kwargs["parser_version"] == "3.0"
    entity_call = next(call for call in tx.run.call_args_list if "MERGE (e:Entity" in call.args[0])
    assert entity_call.kwargs["attributes"] == '[{"text": "工程师", "label": "Occupation"}]'
    assert entity_call.kwargs["review_status"] == "pending"
    relation_call = next(call for call in tx.run.call_args_list if "MERGE (source)-[r:RELATION" in call.args[0])
    assert relation_call.kwargs["claim_level"] == "Fact"
    assert relation_call.kwargs["confidence"] == 0.92
    assert relation_call.kwargs["evidence_quote"] == "张三任职于公司"
    assert relation_call.kwargs["military_value_dimensions"] == ["体系集成与互操作性"]
    assert relation_call.kwargs["expected_capability_gain"] == "提升协同效率"
    assert relation_call.kwargs["expert_review_required"] is True
    assert relation_call.kwargs["review_status"] == "pending"
    assert "军事价值维度：体系集成与互操作性" in triples[0]["content"]
    assert "预期能力收益：提升协同效率" in triples[0]["content"]
    assert "源实体：张三；类型：Person；角色：other" in triples[0]["content"]
    assert "目标实体：公司；类型：Organization；角色：other" in triples[0]["content"]


def test_review_status_outbox_projection_updates_exact_neo4j_mention():
    tx = MagicMock()
    tx.run.return_value.single.return_value = {"updated": 1}
    session = MagicMock()
    session.__enter__.return_value = session
    session.execute_write.side_effect = lambda func: func(tx)
    driver = MagicMock()
    driver.session.return_value = session
    service = MilvusGraphService(neo4j_connection=SimpleNamespace(driver=driver))

    service.project_projection_payload(
        {
            "event_type": "review_status",
            "version": 1,
            "kb_id": "kb_test",
            "chunk_id": "chunk_1",
            "target_type": "relation_mention",
            "entity_id": None,
            "triple_id": "triple_1",
            "review_status": "accepted",
            "decision_id": "decision_1",
        }
    )

    query = tx.run.call_args.args[0]
    assert "triple_id: $triple_id" in query
    assert "r.review_status = $review_status" in query
    assert tx.run.call_args.kwargs["chunk_id"] == "chunk_1"
    assert tx.run.call_args.kwargs["triple_id"] == "triple_1"


def test_relation_lifecycle_projection_updates_all_mentions():
    tx = MagicMock()
    tx.run.return_value.single.return_value = {"updated": 2}
    session = MagicMock()
    session.__enter__.return_value = session
    session.execute_write.side_effect = lambda func: func(tx)
    driver = MagicMock()
    driver.session.return_value = session
    service = MilvusGraphService(neo4j_connection=SimpleNamespace(driver=driver))

    service.project_projection_payload(
        {
            "event_type": "relation_lifecycle",
            "version": 1,
            "kb_id": "kb_test",
            "triple_id": "triple_old",
            "lifecycle_status": "superseded",
            "superseded_by_triple_id": "triple_new",
            "relation_version": 2,
            "valid_to": "2026-10-30T00:00:00+00:00",
            "reason": "新证据支持替代关系",
        }
    )

    query = tx.run.call_args.args[0]
    assert "relation.lifecycle_status = $lifecycle_status" in query
    assert "relation.relation_version = $relation_version" in query
    assert tx.run.call_args.kwargs["triple_id"] == "triple_old"
    assert tx.run.call_args.kwargs["superseded_by_triple_id"] == "triple_new"


@pytest.mark.asyncio
async def test_relation_lifecycle_outbox_replay_updates_neo4j_and_removes_milvus_vector():
    tx = MagicMock()
    tx.run.return_value.single.return_value = {"updated": 2}
    session = MagicMock()
    session.__enter__.return_value = session
    session.execute_write.side_effect = lambda func: func(tx)
    driver = MagicMock()
    driver.session.return_value = session
    event = {
        "event_id": "event_lifecycle_1",
        "kb_id": "kb_test",
        "payload": {
            "event_type": "relation_lifecycle",
            "version": 1,
            "kb_id": "kb_test",
            "triple_id": "triple_old",
            "lifecycle_status": "invalid",
            "superseded_by_triple_id": None,
            "relation_version": 2,
            "valid_to": "2026-10-30T00:00:00+00:00",
            "reason": "原始证据已被撤回",
        },
    }
    graph_repo = SimpleNamespace(
        claim_projection_events=AsyncMock(side_effect=[("lease_1", [event]), ("lease_2", [])]),
        mark_projection_event_completed=AsyncMock(return_value=True),
        mark_projection_event_failed=AsyncMock(return_value=True),
    )
    vector_store = SimpleNamespace(delete_graph_records=AsyncMock(return_value=None))
    service = MilvusGraphService(
        graph_repo=graph_repo,
        graph_vector_store=vector_store,
        neo4j_connection=SimpleNamespace(driver=driver),
    )
    service.index_pending_graph_vectors = AsyncMock(
        return_value={
            "entity": {"claimed": 2, "indexed": 2, "failed": 0},
            "triple": {"claimed": 1, "indexed": 1, "failed": 0},
        }
    )

    first_result = await service.replay_projection_outbox("kb_test", limit=20)
    second_result = await service.replay_projection_outbox("kb_test", limit=20)

    assert first_result == {"claimed": 1, "completed": 1, "failed": 0}
    assert second_result == {"claimed": 0, "completed": 0, "failed": 0}
    query = tx.run.call_args.args[0]
    assert "relation.lifecycle_status = $lifecycle_status" in query
    assert tx.run.call_args.kwargs["triple_id"] == "triple_old"
    vector_store.delete_graph_records.assert_awaited_once_with(
        "kb_test",
        entity_ids=[],
        triple_ids=["triple_old"],
    )
    graph_repo.mark_projection_event_completed.assert_awaited_once_with(
        event_id="event_lifecycle_1",
        lock_token="lease_1",
    )
    graph_repo.mark_projection_event_failed.assert_not_awaited()
    service.index_pending_graph_vectors.assert_awaited_once_with("kb_test")


@pytest.mark.asyncio
async def test_entity_redirect_outbox_replay_removes_superseded_entity_vector():
    tx = MagicMock()
    tx.run.return_value.single.return_value = {"updated": 1}
    session = MagicMock()
    session.__enter__.return_value = session
    session.execute_write.side_effect = lambda func: func(tx)
    driver = MagicMock()
    driver.session.return_value = session
    event = {
        "event_id": "event_redirect_1",
        "kb_id": "kb_test",
        "payload": {
            "event_type": "entity_redirect",
            "version": 1,
            "kb_id": "kb_test",
            "source_entity_id": "entity_source",
            "target_entity_ids": ["entity_target"],
            "operation": "merge",
            "redirect_id": "redirect_1",
            "reason": "文档级类型治理",
        },
    }
    graph_repo = SimpleNamespace(
        claim_projection_events=AsyncMock(return_value=("lease_1", [event])),
        mark_projection_event_completed=AsyncMock(return_value=True),
        mark_projection_event_failed=AsyncMock(return_value=True),
    )
    vector_store = SimpleNamespace(delete_graph_records=AsyncMock(return_value=None))
    service = MilvusGraphService(
        graph_repo=graph_repo,
        graph_vector_store=vector_store,
        neo4j_connection=SimpleNamespace(driver=driver),
    )
    service.index_pending_graph_vectors = AsyncMock(return_value={})

    result = await service.replay_projection_outbox("kb_test", limit=20)

    assert result == {"claimed": 1, "completed": 1, "failed": 0}
    vector_store.delete_graph_records.assert_awaited_once_with(
        "kb_test",
        entity_ids=["entity_source"],
        triple_ids=[],
    )
    graph_repo.mark_projection_event_completed.assert_awaited_once_with(
        event_id="event_redirect_1",
        lock_token="lease_1",
    )
    graph_repo.mark_projection_event_failed.assert_not_awaited()


@pytest.mark.parametrize(
    ("operation", "target_entity_ids", "expected_lifecycle"),
    [
        ("merge", ["entity_target"], "redirected"),
        ("split", ["entity_target_1", "entity_target_2"], "split"),
    ],
)
def test_entity_redirect_outbox_projection_updates_lifecycle_and_governance_edges(
    operation,
    target_entity_ids,
    expected_lifecycle,
):
    tx = MagicMock()
    tx.run.return_value.single.return_value = {"updated": len(target_entity_ids)}
    session = MagicMock()
    session.__enter__.return_value = session
    session.execute_write.side_effect = lambda func: func(tx)
    driver = MagicMock()
    driver.session.return_value = session
    service = MilvusGraphService(neo4j_connection=SimpleNamespace(driver=driver))

    service.project_projection_payload(
        {
            "event_type": "entity_redirect",
            "version": 1,
            "kb_id": "kb_test",
            "source_entity_id": "entity_source",
            "target_entity_ids": target_entity_ids,
            "operation": operation,
            "redirect_id": "redirect_1",
            "reason": "人工实体治理",
        }
    )

    query = tx.run.call_args.args[0]
    params = tx.run.call_args.kwargs
    assert "ENTITY_REDIRECT" in query
    assert "source.lifecycle_status = $lifecycle_status" in query
    assert params["source_entity_id"] == "entity_source"
    assert params["target_entity_ids"] == target_entity_ids
    assert params["primary_target_entity_id"] == target_entity_ids[0]
    assert params["lifecycle_status"] == expected_lifecycle
    assert params["operation"] == operation


@pytest.mark.parametrize(
    "payload",
    [
        {
            "event_type": "entity_redirect",
            "version": 1,
            "kb_id": "kb_test",
            "source_entity_id": "entity_source",
            "target_entity_ids": ["entity_target_1", "entity_target_2"],
            "operation": "merge",
            "redirect_id": "redirect_1",
        },
        {
            "event_type": "entity_redirect",
            "version": 1,
            "kb_id": "kb_test",
            "source_entity_id": "entity_source",
            "target_entity_ids": ["entity_target"],
            "operation": "split",
            "redirect_id": "redirect_1",
        },
    ],
)
def test_entity_redirect_projection_rejects_invalid_merge_and_split_payloads(payload):
    service = MilvusGraphService(neo4j_connection=SimpleNamespace(driver=MagicMock()))

    with pytest.raises(ValueError):
        service.project_projection_payload(payload)


@pytest.mark.parametrize("review_scope", ["accepted", "pending_preview"])
def test_visible_entity_predicate_excludes_redirected_entities(review_scope):
    predicate = MilvusGraphService._visible_node_predicate("node", review_scope)

    assert "coalesce(node.lifecycle_status, 'active') = 'active'" in predicate


def test_graph_vector_store_uses_idempotent_upsert():
    collection = MagicMock()
    store = MilvusGraphVectorStore.__new__(MilvusGraphVectorStore)

    store._upsert_entities(
        collection,
        [{"id": "entity_1", "content": "entity"}],
        [[0.1, 0.2]],
    )

    collection.upsert.assert_called_once_with([["entity_1"], ["entity"], [[0.1, 0.2]]])
    collection.insert.assert_not_called()


def test_graph_vector_store_upserts_all_relationships_in_one_shape():
    collection = MagicMock()
    store = MilvusGraphVectorStore.__new__(MilvusGraphVectorStore)

    store._upsert_triples(
        collection,
        [
            {
                "id": "triple-1",
                "content": "技术 A 形成能力 B",
                "source_id": "entity-a",
                "target_id": "entity-b",
            }
        ],
        [[0.1, 0.2]],
    )

    collection.upsert.assert_called_once_with(
        [
            ["triple-1"],
            ["技术 A 形成能力 B"],
            ["entity-a"],
            ["entity-b"],
            [[0.1, 0.2]],
        ]
    )


def test_graph_vector_store_combines_dense_and_bm25_inside_each_graph_channel():
    collection = MagicMock()
    hit = SimpleNamespace(
        distance=0.83,
        entity=SimpleNamespace(
            get=lambda field: {
                "id": "entity_1",
                "content": "宽带射频收发器\n实体类型：Component",
            }.get(field)
        ),
    )
    collection.hybrid_search.return_value = [[hit]]
    store = MilvusGraphVectorStore.__new__(MilvusGraphVectorStore)

    result = store._search_loaded_collection(
        collection,
        "宽带射频模块",
        [[0.1, 0.2]],
        7,
        ["id", "content"],
    )

    assert result == [
        {
            "id": "entity_1",
            "content": "宽带射频收发器\n实体类型：Component",
            "score": 0.83,
        }
    ]
    collection.load.assert_not_called()
    collection.search.assert_not_called()
    hybrid_call = collection.hybrid_search.call_args.kwargs
    assert hybrid_call["limit"] == 7
    assert hybrid_call["output_fields"] == ["id", "content"]
    assert hybrid_call["consistency_level"] == "Strong"
    assert hybrid_call["rerank"]._weights == [0.7, 0.3]
    dense_request, sparse_request = hybrid_call["reqs"]
    assert dense_request.anns_field == "embedding"
    assert dense_request.data == [[0.1, 0.2]]
    assert dense_request.param["metric_type"] == "COSINE"
    assert sparse_request.anns_field == "content_sparse"
    assert sparse_request.data == ["宽带射频模块"]
    assert sparse_request.param["metric_type"] == "BM25"


def test_milvus_graph_service_delete_file_graph_uses_scoped_streaming_queries():
    tx = MagicMock()
    session = MagicMock()
    session.__enter__.return_value = session
    session.execute_write.side_effect = lambda func: func(tx)
    driver = MagicMock()
    driver.session.return_value = session
    service = MilvusGraphService(neo4j_connection=SimpleNamespace(driver=driver))

    service._delete_file_graph_from_neo4j("kb_test", "file_1")

    queries = [call.args[0] for call in tx.run.call_args_list]
    assert len(queries) == 3
    cleanup_query = queries[1]
    assert "file_id: $file_id" in cleanup_query
    assert "DELETE m" in cleanup_query
    assert "WITH DISTINCT e" in cleanup_query
    assert "collect(" not in cleanup_query
    assert "MATCH (e:Entity:MilvusKB:`kb_test` {kb_id: $kb_id})" not in cleanup_query
    assert "DETACH DELETE c" in queries[2]


@pytest.mark.parametrize(
    ("payload", "limit", "exclude_chunk", "expected_node_ids", "expected_edge_ids"),
    [
        (
            [
                {
                    "h": _raw_graph_node("node-a"),
                    "t": _raw_graph_node("node-b"),
                    "r": _raw_graph_edge("edge-a-b", "node-a", "node-b"),
                }
            ],
            2,
            False,
            ["node-a", "node-b"],
            ["edge-a-b"],
        ),
        (
            [
                {
                    "h": _raw_graph_node("node-a"),
                    "t": _raw_graph_node("node-b"),
                    "r": _raw_graph_edge("edge-a-b", "node-a", "node-b"),
                }
            ],
            1,
            False,
            ["node-a"],
            [],
        ),
        (
            [
                {
                    "h": _raw_graph_node("entity-a"),
                    "t": _raw_graph_node("chunk-a", labels=["MilvusKB", "Chunk"]),
                    "r": _raw_graph_edge("edge-entity-chunk", "entity-a", "chunk-a"),
                }
            ],
            2,
            True,
            ["entity-a"],
            [],
        ),
        (
            [
                {
                    "h": _raw_graph_node("node-a"),
                    "t": _raw_graph_node("node-b"),
                    "r": _raw_graph_edge("edge-a-b", "node-a", "node-b"),
                }
            ],
            -1,
            False,
            [],
            [],
        ),
    ],
)
def test_milvus_graph_service_process_query_result(payload, limit, exclude_chunk, expected_node_ids, expected_edge_ids):
    service = MilvusGraphService()
    result = service._process_query_result(payload, limit=limit, kb_id="kb_test", exclude_chunk=exclude_chunk)

    assert [node["id"] for node in result["nodes"]] == expected_node_ids
    assert [edge["id"] for edge in result["edges"]] == expected_edge_ids


@pytest.mark.parametrize("max_depth", [1, 2, 3])
def test_milvus_graph_service_build_query_uses_requested_depth(max_depth):
    service = MilvusGraphService()

    query = service._build_query("kb_test", "entity", limit=20, max_depth=max_depth)

    assert f"[*1..{max_depth}]" in query
    assert "nodes(path)" in query
    assert "relationships(path)" in query
    assert "nodes(path)) + seeds AS nodes" in query
    assert "coalesce(path_rel.review_status, 'pending') IN ['accepted', 'pending']" in query
    assert "coalesce(path_rel.lifecycle_status, 'active') = 'active'" in query
    assert "coalesce(mention.review_status, 'pending') IN ['accepted', 'pending']" in query


def test_milvus_graph_service_build_query_excludes_chunks_from_entire_path():
    service = MilvusGraphService()

    query = service._build_query("kb_test", "entity", limit=20, max_depth=3, exclude_chunk=True)

    assert "NOT n:Chunk" in query
    assert "NOT path_node:Chunk" in query


def test_milvus_graph_service_build_query_treats_legacy_preview_scope_as_unified():
    service = MilvusGraphService()

    query = service._build_query(
        "kb_test",
        "entity",
        limit=20,
        max_depth=3,
        exclude_chunk=True,
        review_scope="pending_preview",
    )

    assert "coalesce(mention.review_status, 'pending') IN ['accepted', 'pending']" in query
    assert "coalesce(path_rel.review_status, 'pending') IN ['accepted', 'pending']" in query
    assert "coalesce(path_rel.lifecycle_status, 'active') = 'active'" in query


def test_milvus_graph_service_query_nodes_sync_returns_complete_multi_hop_path():
    query_result = MagicMock()
    query_result.single.return_value = {
        "nodes": [_raw_graph_node("node-a"), _raw_graph_node("node-b"), _raw_graph_node("node-c")],
        "edges": [
            _raw_graph_edge("edge-a-b", "node-a", "node-b"),
            _raw_graph_edge("edge-b-c", "node-b", "node-c"),
        ],
    }
    session = MagicMock()
    session.__enter__.return_value = session
    session.run.return_value = query_result
    driver = MagicMock()
    driver.session.return_value = session
    service = MilvusGraphService(neo4j_connection=SimpleNamespace(driver=driver))

    result = service._query_nodes_sync(
        "kb_test",
        "kb_test",
        "node-a",
        limit=3,
        max_depth=2,
        exclude_chunk=False,
    )

    assert [node["id"] for node in result["nodes"]] == ["node-a", "node-b", "node-c"]
    assert [edge["id"] for edge in result["edges"]] == ["edge-a-b", "edge-b-c"]
    query, query_params = session.run.call_args
    assert "[*1..2]" in query[0]
    assert query_params["path_limit"] == 30


def test_milvus_graph_service_query_nodes_sync_caps_max_depth():
    query_result = MagicMock()
    query_result.single.return_value = None
    session = MagicMock()
    session.__enter__.return_value = session
    session.run.return_value = query_result
    driver = MagicMock()
    driver.session.return_value = session
    service = MilvusGraphService(neo4j_connection=SimpleNamespace(driver=driver))

    service._query_nodes_sync(
        "kb_test",
        "kb_test",
        "node-a",
        limit=3,
        max_depth=100,
        exclude_chunk=False,
    )

    query, _ = session.run.call_args
    assert "[*1..3]" in query[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "kwargs", "expected"),
    [
        ("query_nodes", {"keyword": "test"}, {"nodes": [], "edges": []}),
        ("get_labels", {}, []),
        ("get_stats", {}, {"total_nodes": 0, "total_edges": 0, "entity_types": []}),
    ],
)
async def test_milvus_graph_service_early_returns_empty_for_missing_kb_id(method, kwargs, expected):
    service = MilvusGraphService()
    assert await getattr(service, method)(kb_id=None, **kwargs) == expected


@pytest.mark.parametrize("operation", ["has_collection", "drop_collection"])
def test_drop_graph_collections_propagates_storage_failure(monkeypatch, operation):
    """图集合检查或删除失败必须向上传播。"""
    from platform_core.knowledge.graphs import milvus_graph_vector_store as module

    store = MilvusGraphVectorStore.__new__(MilvusGraphVectorStore)
    store.connection_alias = "test"
    error = RuntimeError("Milvus unavailable")
    monkeypatch.setattr(module.utility, "has_collection", MagicMock(return_value=True))
    monkeypatch.setattr(module.utility, operation, MagicMock(side_effect=error))

    with pytest.raises(RuntimeError) as caught:
        store.drop_graph_collections("kb_test")

    assert caught.value is error
