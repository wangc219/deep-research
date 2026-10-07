from equipment_deep_research.agents.workflows.reporter import (
    _clean_rewritten_title,
    _fallback_academic_title,
    _needs_title_rewrite,
    _rewrite_report_title,
)


def test_task_like_query_is_detected_and_cleaned() -> None:
    query = (
        "未来强干扰弱通信海空对抗下分布式低成本精确火力与反无人直接作战装备研究："
        "只提出约20个候选，按创新性评分并生成入选画像（GPT验收）"
    )
    assert _needs_title_rewrite(query)
    assert _fallback_academic_title(query) == (
        "未来强干扰弱通信海空对抗下分布式低成本精确火力与反无人直接作战装备研究"
    )


def test_concise_topic_does_not_require_rewrite() -> None:
    assert not _needs_title_rewrite("弱通信条件下边缘智能融合打击装备研究")


def test_rewritten_title_rejects_instructions_and_markdown() -> None:
    assert _clean_rewritten_title("# 题目：弱通信海空对抗分布式精确火力装备研究") == (
        "弱通信海空对抗分布式精确火力装备研究"
    )
    assert _clean_rewritten_title("按创新性30%评分") == ""


def test_reporter_rewrites_non_general_query() -> None:
    class Host:
        async def _run_reporter_text(self, system, payload, budget, *, phase, run_id):
            assert "学术化题目" in system
            assert phase == "report_title_rewrite"
            return "强干扰弱通信海空对抗分布式低成本精确火力装备需求研究"

    title = _rewrite_report_title(
        Host(),
        "未来强干扰弱通信海空对抗下分布式低成本精确火力与反无人直接作战装备研究："
        "只提出约20个候选并按评分选前7",
        run_id="test-run",
    )
    assert title == "强干扰弱通信海空对抗分布式低成本精确火力装备需求研究"
