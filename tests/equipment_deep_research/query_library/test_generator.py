from __future__ import annotations

import asyncio
import json

from equipment_deep_research.providers.base import (
    ProviderFinalTurn,
    ProviderStreamEvent,
)
from equipment_deep_research.providers.fake import ScriptedFakeProvider
from equipment_deep_research.query_library.generator import ModelQueryGenerator
from equipment_deep_research.query_library.models import SourceReference
from equipment_deep_research.query_library.quality import (
    coverage_plan,
    near_duplicate,
    sanitize_source_reference,
)


def test_generator_returns_all_twelve_coverage_slots_with_sources() -> None:
    source = {
        "title": "公开规划资料",
        "url": "https://example.test/planning",
        "relevance_note": "提供公开术语和规划线索。",
    }
    grounding = {
        "summary": "公开资料显示无人远程火力装备持续向智能协同与规模化发展。",
        "search_queries": ["无人远程火力 装备 规划"],
        "signals": ["智能协同", "低成本规模化"],
        "sources": [source],
    }
    rows = []
    for index, slot in enumerate(coverage_plan(12), start=1):
        rows.append(
            {
                "coverage_slot": slot,
                "query": f"无人远程火力装备第{index}类{slot.split('-', 1)[-1]}研究",
                "supplemental_information": (
                    "面向未来高强度对抗，分析任务约束、技术趋势、体系效能、失效边界、"
                    "指标方向和验证场景；兼顾智能自主、传统现役跨代做优、新质蓝海颠覆拓新、"
                    "低成本供应链和装备族规模发展，形成装备能力需求建议。"
                ),
                "generation_rationale": "该问题把公开发展信号转化为可验证的装备需求研究任务。",
                "sources": [
                    {
                        "url": source["url"],
                        "relevance_note": "该来源支持当前术语和发展方向的校验。",
                    }
                ],
            }
        )
    provider = ScriptedFakeProvider(
        [
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(
                        text=json.dumps(grounding, ensure_ascii=False),
                        metadata={"web_sources": [source]},
                    )
                )
            ],
            [
                ProviderStreamEvent.final(
                    ProviderFinalTurn(
                        text=json.dumps({"queries": rows}, ensure_ascii=False)
                    )
                )
            ],
        ]
    )

    result = asyncio.run(
        ModelQueryGenerator(provider).generate(
            topic="无人远程火力打击装备",
            supplemental_information="面向未来高端战争",
            reference_urls=("https://example.test/manual-reference",),
            count=12,
            existing_queries=[],
        )
    )

    assert len(result.candidates) == 12
    assert {item.coverage_slot for item in result.candidates} == set(coverage_plan(12))
    assert all(item.source_references for item in result.candidates)
    assert all(14 <= len(item.query) <= 30 for item in result.candidates)
    assert provider.remaining_steps == 0
    assert provider.inputs[0][2]["require_web_search"] is False
    assert provider.inputs[0][2]["_provider_retry_attempts"] == 3
    grounding_request = json.loads(provider.inputs[0][0][1].content)
    assert grounding_request["reference_urls"] == [
        "https://example.test/manual-reference"
    ]
    assert "web_search" not in provider.inputs[1][2]
    generation_request = json.loads(provider.inputs[1][0][1].content)
    requirements = "".join(generation_request["requirements"])
    assert "coverage_slot只是思考发生维度" in requirements
    assert "具体装备项目" in requirements
    assert "项目功能" in requirements


def test_generator_records_codex_situation_assessment_without_web_results() -> None:
    grounding = {
        "summary": "未获得外部网页来源，按用户母题进行语义发散。",
        "search_queries": [],
        "signals": ["任务牵引", "装备能力需求"],
        "sources": [],
    }
    row = {
        "coverage_slot": coverage_plan(1)[0],
        "query": "未来无人精确打击装备任务需求研究",
        "supplemental_information": "面向复杂对抗任务，分析作战场景、威胁约束、装备能力缺口、失效边界和可验证的发展方向。",
        "generation_rationale": "将输入母题中的任务牵引转化为可独立论证的装备能力研究问题。",
        "sources": [],
    }
    provider = ScriptedFakeProvider(
        [
            [ProviderStreamEvent.final(ProviderFinalTurn(text=json.dumps(grounding, ensure_ascii=False)))],
            [ProviderStreamEvent.final(ProviderFinalTurn(text=json.dumps({"queries": [row]}, ensure_ascii=False)))],
        ]
    )

    result = asyncio.run(
        ModelQueryGenerator(
            provider,
            provider_snapshot={"type": "codex_cli", "model": "test"},
        ).generate(
            topic="未来无人精确打击装备",
            supplemental_information="自动态势发散模式。不提供参考 URL 也应能够完成生成。",
            count=1,
            existing_queries=[],
        )
    )

    assert len(result.candidates) == 1
    assert result.source_references[0].source_kind == "document"
    assert result.source_references[0].url == ""
    assert result.source_references[0].title.startswith("态势研判")
    assert "中国当前安全环境" in result.source_references[0].relevance_note
    assert result.candidates[0].source_references == result.source_references
    grounding_request = json.loads(provider.inputs[0][0][1].content)
    assert grounding_request["analysis_mode"] == "codex_cli_china_situation_assessment"
    assert "3至5个聚焦检索" in grounding_request["task"]
    assert "外部态势→任务压力→作战缺口→武器装备能力与发展需求" in grounding_request["task"]
    assert provider.inputs[0][2]["web_search"]["search_context_size"] == "low"
    assert provider.inputs[0][2]["_provider_retry_attempts"] == 1
    generation_request = json.loads(provider.inputs[1][0][1].content)
    requirements = "".join(generation_request["requirements"])
    assert "实质不同的装备需求矛盾" in requirements
    assert "高关注方向" in requirements
    assert "不设固定类别配额" in requirements
    assert "充分发挥模型的异质发散能力" in requirements
    assert "被态势直接牵引的武器装备需求" in requirements
    assert "direct_strike_priority_slots" not in generation_request
    assert "不写成时事摘要" in requirements
    assert provider.inputs[1][2]["_provider_retry_attempts"] == 2


def test_source_sanitizer_removes_sensitive_query_parameters() -> None:
    cleaned = sanitize_source_reference(
        SourceReference(
            title="source",
            url="https://example.test/report?id=7&token=secret&api_key=hidden#part",
        )
    )

    assert cleaned.url == "https://example.test/report?id=7"
    assert "secret" not in cleaned.url
    assert "hidden" not in cleaned.url


def test_near_duplicate_normalizes_punctuation_and_spacing() -> None:
    assert near_duplicate(
        "研究 无人远程火力装备：体系能力需求",
        "研究无人远程火力装备体系能力需求",
    )
