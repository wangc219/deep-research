import pytest

from equipment_deep_research.domain.research_gaps import (
    sanitize_public_research_gap,
    sanitize_public_research_gaps,
    sanitize_public_research_prose,
    sanitize_public_research_value,
)


@pytest.mark.parametrize(
    "value",
    [
        "来源边界提示：国内外检索通道不可达，后续补充。",
        "国内外来源不可达。",
        "国际来源通道失败，建议补充。",
        "检索不通，后续补充。",
        "本轮搜索未返回结果。",
        "联网检索无结果。",
        "检索通道异常：timeout。",
        "没有可引用来源，以下为推演。",
        "未检索到可靠的新技术。",
        "无法访问中国知网。",
        "web search unavailable",
    ],
)
def test_retrieval_status_not_projected_as_public_gap(value: str) -> None:
    assert sanitize_public_research_gap(value) == ""


@pytest.mark.parametrize(
    "value",
    [
        "仍需补充公开证据以验证任务失能判据。",
        "下一轮应比较主路径与邻域迁移路径的热控约束。",
        "目标关键任务舱段的失能观测条件仍需收紧。",
        "公开事实支持构型方向，但移植断点需要试验确认。",
        "来源证据不足以区分两条作用机理，建议开展对照验证。",
    ],
)
def test_actionable_research_gaps_are_preserved(value: str) -> None:
    assert sanitize_public_research_gap(value) == value


def test_public_gap_projection_deduplicates_filtered_values() -> None:
    assert sanitize_public_research_gaps(
        [
            "检索不通，后续补充。",
            "仍需补充公开证据。",
            "仍需补充公开证据。",
            "来源通道失败。",
            "主路径的热控约束仍需验证。",
        ]
    ) == ["仍需补充公开证据。", "主路径的热控约束仍需验证。"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "来源边界提示：国内外检索通道不可达，后续补充。工程路线应先闭合热控与供能接口。",
            "工程路线应先闭合热控与供能接口。",
        ),
        (
            "工程路线应先闭合热控与供能接口。\n"
            "来源边界提示：国际来源通道失败。\n"
            "验证条件是完成硬件在环和任务级对照试验。",
            "工程路线应先闭合热控与供能接口。\n"
            "验证条件是完成硬件在环和任务级对照试验。",
        ),
        (
            "1. 主路径先做原理样机。\n"
            "2. 来源边界提示：检索不通。\n"
            "3. 备选路径再做环境试验。",
            "1. 主路径先做原理样机。\n3. 备选路径再做环境试验。",
        ),
        (
            "本轮检索围绕热控与控制接口，形成三条工程路线。",
            "本轮检索围绕热控与控制接口，形成三条工程路线。",
        ),
    ],
)
def test_public_research_prose_filters_status_units_only(
    value: str, expected: str
) -> None:
    assert sanitize_public_research_prose(value) == expected


def test_public_research_prose_returns_empty_for_status_only() -> None:
    assert (
        sanitize_public_research_prose(
            "来源边界提示：国内外检索通道不可达。\n"
            "检索通道异常：timeout。"
        )
        == ""
    )


def test_public_research_prose_honors_positional_limit() -> None:
    assert sanitize_public_research_prose("工程路线可行。", 4) == "工程路线"


def test_public_research_value_scrubs_nested_provider_diagnostics() -> None:
    projected = sanitize_public_research_value(
        {
            "provider_metadata": {
                "status": "来源边界提示：国内外检索通道不可达。",
                "summary": "主路径仍应闭合热控与供能接口。",
                "rows": [
                    "检索失败。",
                    "继续比较主路径与邻域迁移路径。",
                ],
            }
        }
    )

    assert projected == {
        "provider_metadata": {
            "summary": "主路径仍应闭合热控与供能接口。",
            "rows": ["继续比较主路径与邻域迁移路径。"],
        }
    }
