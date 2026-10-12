"""合成资料验证排序、上下文边界和候选提及覆盖；不代表实测解析质量。"""

import asyncio
import copy
import json

import pytest

from document_research.contracts import ResearchError
from document_research.engine import Engine, local_matches, prepare_sources
from document_research.retrieval import evidence_coverage, terms

CONFIG = {
    "model": {
        "base_url": "https://model.example/v1",
        "model": "fixture",
        "api_key": "fixture",
    },
    "zhipu": {"api_key": "fixture", "libraries": {"alice": [{"id": "fixture"}]}},
}
TASK = {"problem": "复杂表格", "library_ids": ["local"], "owner": "alice"}


def source(identifier, text, **fields):
    return {
        "id": identifier,
        "library_id": "local",
        "document_id": identifier,
        "origin": "local",
        "text": text,
        "title": "合成资料",
        "page": 1,
        **fields,
    }


class Providers:
    def __init__(self):
        self.calls = []
        self.remote = []

    async def retrieve_zhipu(self, key, ids, query, authorize):
        authorize()
        self.calls.append(("zhipu", query))
        return self.remote

    async def public_sources(self, query, authorize):
        authorize()
        self.calls.append(("readme", query))
        return [], []

    async def search_public(self, key, query, authorize):
        authorize()
        self.calls.append(("search", query))
        return [], []

    async def model_report(self, config, messages, authorize):
        authorize()
        self.calls.append(("model", messages))
        return {"answer": [], "graph": [], "gaps": ["合成测试未生成答案"]}


def retrieve(task, sources, providers=None):
    return asyncio.run(
        Engine(lambda: CONFIG, providers or Providers()).retrieve(
            task, sources, lambda: None
        )
    )


def test_short_focused_evidence_outranks_long_keyword_noise():
    focused = source("focused", "merged cell alignment")
    noisy = source("noise", ("irrelevant " * 600) + ("merged cell " * 30))
    ranked = local_matches([noisy, focused], "merged cell")
    assert [item["id"] for item in ranked] == ["focused", "noise"]
    # The same evidence ranking is used when context limits are applied.
    prepared, _ = prepare_sources([noisy, focused], "merged cell")
    assert prepared[0]["original_id"] == "focused"


def test_rare_query_term_has_more_weight_than_common_term():
    frequent = [source(f"common-{i}", "table ordinary") for i in range(8)]
    uncommon = source("rare", "alignment ordinary")
    assert local_matches([*frequent, uncommon], "table alignment")[0]["id"] == "rare"


def test_query_and_evidence_share_overlapping_cjk_terms_and_ascii_word_boundaries():
    assert terms("复杂表格 Docling") == ["docling", "复杂", "杂表", "表格"]
    matching = source("matching", "杂表")
    irrelevant = source("irrelevant", "astronomy stable")
    assert [
        item["id"] for item in local_matches([irrelevant, matching], "复杂表格")
    ] == ["matching"]
    prepared, _ = prepare_sources([irrelevant, matching], "复杂表格")
    assert prepared[0]["original_id"] == "matching"
    assert local_matches([irrelevant], "table") == []
    assert local_matches([matching], "the and 什么 如何") == []


def test_same_document_duplicates_keep_exact_quote_and_locations_but_other_provenance_survives():
    original = source("first", "Docling\n  handles tables.", document_id="doc", page=2)
    duplicate = source(
        "duplicate", "Docling handles tables.", document_id="doc", page=8
    )
    other_document = source(
        "different", "Docling handles tables.", document_id="other", page=1
    )
    other_library = source(
        "foreign", "Docling handles tables.", document_id="doc", library_id="other"
    )
    inputs = [original, duplicate, other_document, other_library]
    before = copy.deepcopy(inputs)
    ranked = local_matches(inputs, "Docling tables")
    prepared, warnings = prepare_sources(ranked, "Docling tables")
    assert inputs == before
    assert len(prepared) == 3
    retained = next(item for item in prepared if item["original_id"] == "first")
    assert retained["text"] == original["text"] and retained["page"] == 2
    assert retained["duplicate_locations"] == [{"original_id": "duplicate", "page": 8}]
    assert "不同文档" in warnings[0]
    assert {item["original_id"] for item in prepared} == {
        "first",
        "different",
        "foreign",
    }


def test_deduplication_does_not_merge_unknown_documents_or_change_case():
    unknown = {"origin": "local", "library_id": "local", "text": "tables"}
    prepared, _ = prepare_sources([unknown, unknown], "tables")
    assert len(prepared) == 2
    variants = [
        source("first", "Case tables", document_id="doc"),
        source("next", "case tables", document_id="doc"),
    ]
    assert len(local_matches(variants, "tables")) == 2


def test_diversity_preserves_other_document_under_source_limit():
    many = [
        source(f"part-{i}", f"table alignment part {i}", document_id="long")
        for i in range(30)
    ]
    other = source("other", "table other evidence")
    prepared, warnings = prepare_sources([*many, other], "table alignment")
    assert len(prepared) == 24
    assert prepared[1]["original_id"] == "other"
    assert any("上下文上限" in item for item in warnings)


def test_coverage_only_counts_names_in_actual_retained_text():
    inputs = [
        source("s1", "DOCLING and PaddleOCR.", title="Unstructured"),
        source("s2", "myDoclingExtension unstructuredness"),
        source("s3", ("x " * 3100) + "Unstructured"),
    ]
    prepared, _ = prepare_sources(inputs, "Docling")
    coverage = evidence_coverage(prepared)
    assert coverage == {
        "kind": "text_mentions_only",
        "total_sources": 3,
        "candidates": [
            {"name": "Docling", "source_ids": ["S1"]},
            {"name": "PaddleOCR", "source_ids": ["S1"]},
            {"name": "Unstructured", "source_ids": []},
        ],
        "missing_candidates": ["Unstructured"],
    }
    assert evidence_coverage([])["missing_candidates"] == [
        "Docling",
        "PaddleOCR",
        "Unstructured",
    ]


def test_followup_shorthand_retrieves_again_using_prior_user_question():
    sources = [source("tables", "跨页表头识别失败"), source("other", "astronomy data")]
    assert retrieve({**TASK, "problem": "怎么改善它？"}, sources)["sources"] == []
    result = retrieve(
        {**TASK, "problem": "怎么改善它？", "context_questions": ["跨页表头识别不准"]},
        sources,
    )
    assert [item["original_id"] for item in result["sources"]] == ["tables"]
    assert any("历史答案不作为证据" in item for item in result["warnings"])
    assert result["evidence_coverage"]["total_sources"] == 1


@pytest.mark.parametrize(
    "context", [None, {}, "question", [""], [" "], [123], ["x" * 2001], ["x"] * 4]
)
def test_invalid_question_context_fails_before_any_provider_request(context):
    providers = Providers()
    with pytest.raises(ResearchError, match="追问上下文"):
        retrieve(
            {
                **TASK,
                "context_questions": context,
                "allow_public": True,
                "public_query": "Docling",
            },
            [],
            providers,
        )
    assert providers.calls == []


@pytest.mark.parametrize("invalid", [1, "true", [], None])
def test_context_truncation_marker_is_strict_boolean(invalid):
    with pytest.raises(ResearchError, match="追问上下文"):
        retrieve({**TASK, "context_truncated": invalid}, [])


def test_zhipu_query_prioritizes_current_then_newest_history_within_1000_chars():
    providers = Providers()
    task = {
        **TASK,
        "library_ids": ["zhipu:fixture"],
        "problem": "CURRENT " + "x" * 940,
        "context_questions": ["OLDEST " + "o" * 900, "NEWEST " + "n" * 900],
    }
    result = retrieve(task, [], providers)
    query = providers.calls[0][1]
    assert len(query) == 1000 and query.startswith(task["problem"] + "\nNEWEST ")
    assert "OLDEST" not in query
    assert any("1000" in warning for warning in result["warnings"])
    providers.calls.clear()
    task["problem"] = "c" * 1200
    retrieve(task, [], providers)
    assert providers.calls == [("zhipu", "c" * 1000)]


def test_public_queries_never_inherit_private_current_or_historical_questions():
    providers = Providers()
    retrieve(
        {
            **TASK,
            "problem": "PRIVATE_CURRENT",
            "context_questions": ["PRIVATE_OLD"],
            "allow_public": True,
            "allow_web_search": True,
            "public_query": "Docling tables",
        },
        [],
        providers,
    )
    assert providers.calls == [
        ("readme", "Docling tables"),
        ("search", "Docling tables"),
    ]
    with pytest.raises(ResearchError, match="公开关键词"):
        retrieve(
            {**TASK, "context_questions": ["PRIVATE_OLD"], "allow_web_search": True},
            [],
            providers,
        )


def test_model_receives_bounded_questions_and_fresh_sources_not_past_answers():
    providers = Providers()
    task = {
        **TASK,
        "mode": "answer",
        "allow_external_model": True,
        "problem": "怎么改善它？",
        "context_questions": ["跨页表头识别不准"],
        "context_truncated": True,
        "previous_answer": "DO_NOT_SEND_PRIOR_MODEL_TEXT",
    }
    result = asyncio.run(
        Engine(lambda: CONFIG, providers).run(
            task, [source("fresh", "Docling 跨页表头")], lambda: None
        )
    )
    messages = providers.calls[0][1]
    data = json.loads(messages[1]["content"])
    assert (
        data["context_questions"] == task["context_questions"]
        and data["context_truncated"] is True
    )
    assert "不是事实或证据" in messages[0]["content"]
    assert "DO_NOT_SEND_PRIOR_MODEL_TEXT" not in json.dumps(messages)
    assert data["sources"][0]["original_id"] == "fresh"
    assert data["evidence_coverage"] == result["evidence_coverage"]
    assert result["evidence_coverage"]["candidates"][0]["source_ids"] == ["S1"]


def test_research_warns_when_candidate_names_are_absent_from_selected_evidence():
    class ResearchProviders(Providers):
        async def model_report(self, config, messages, authorize):
            authorize()
            return {
                "summary": "资料尚不足以比较三种方案。",
                "comparisons": [],
                "experiments": [
                    {
                        "name": "准备表格基线",
                        "steps": ["冻结 PDF 样本及标注"],
                        "metrics": ["结构正确率"],
                        "acceptance": "阈值待定",
                        "source_ids": ["S1"],
                    }
                ],
                "recommendation": {
                    "text": "补充候选原始文档后再比较。",
                    "source_ids": ["S1"],
                },
                "assumptions": [],
                "gaps": ["缺少候选原始文档"],
                "graph": [],
                "measurement_status": "not_measured",
            }

    task = {
        **TASK,
        "mode": "research",
        "allow_external_model": True,
        "evidence_coverage": {"missing_candidates": [], "total_sources": 999},
    }
    result = asyncio.run(
        Engine(lambda: CONFIG, ResearchProviders()).run(
            task, [source("fresh", "复杂表格包含合并单元格")], lambda: None
        )
    )
    assert result["evidence_coverage"]["total_sources"] == 1
    assert result["evidence_coverage"]["missing_candidates"] == [
        "Docling",
        "PaddleOCR",
        "Unstructured",
    ]
    assert any(
        "原文未提及 Docling、PaddleOCR、Unstructured" in warning
        for warning in result["warnings"]
    )
    assert result["measurement_status"] == "not_measured"


@pytest.mark.parametrize(
    ("name", "cited_original_id", "retained"),
    [
        ("Docling", "docling", True),
        ("docling (v2)", "docling", True),
        ("Docling", "general", False),
        ("PaddleOCR", "docling", False),
        ("Camelot", "general", False),
        ("MyDoclingExtension", "docling", False),
        ("Docling / PaddleOCR", "docling", False),
    ],
)
def test_comparison_must_name_one_candidate_and_cite_its_own_mentions(
    name, cited_original_id, retained
):
    class ComparisonProviders(Providers):
        async def model_report(self, config, messages, authorize):
            authorize()
            sources = json.loads(messages[1]["content"])["sources"]
            source_id = next(
                item["id"]
                for item in sources
                if item["original_id"] == cited_original_id
            )
            return {
                "summary": "普通文档解析候选研究。",
                "comparisons": [
                    {
                        "name": name,
                        "approach": "读取所引原文后设计实验",
                        "pros": ["待验证"],
                        "cons": ["本地效果未测量"],
                        "source_ids": [source_id],
                    }
                ],
                "experiments": [
                    {
                        "name": "冻结样本",
                        "steps": ["准备带真值的 PDF 样本"],
                        "metrics": ["结构正确率"],
                        "acceptance": "阈值待定",
                        "source_ids": [source_id],
                    }
                ],
                "recommendation": {
                    "text": "建议先补齐资料和标注，待验证。",
                    "source_ids": [source_id],
                },
                "assumptions": [],
                "gaps": [],
                "graph": [],
                "measurement_status": "not_measured",
            }

    result = asyncio.run(
        Engine(lambda: CONFIG, ComparisonProviders()).run(
            {**TASK, "mode": "research", "allow_external_model": True},
            [
                source("docling", "Docling 的复杂表格资料。"),
                source("general", "复杂表格需要带标注的样本。"),
            ],
            lambda: None,
        )
    )
    assert bool(result["comparisons"]) is retained
    assert result["comparison_removed_count"] == (0 if retained else 1)
    assert bool(result["comparison_warnings"]) is not retained
    assert result["measurement_status"] == "not_measured"
    if retained:
        assert result["comparisons"][0]["name"] == name
    else:
        assert any("候选与引文不对应" in gap for gap in result["gaps"])
        assert any("已移除 1 个" in warning for warning in result["warnings"])
