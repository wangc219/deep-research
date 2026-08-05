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
    assert provider.inputs[0][2]["require_web_search"] is True
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
