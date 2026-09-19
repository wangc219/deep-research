from equipment_deep_research.deep_conversation import (
    branch_message_path,
    build_working_memory,
    compaction_notice,
    conversation_context_usage,
    format_quoted_user_message,
    living_transcript,
    living_user_questions,
    parse_quoted_user_message,
    working_memory_prompt,
)


def _turn(sequence: int, role: str, content: str, *, branch_id: str = "main") -> dict:
    return {
        "message_id": f"m{sequence}",
        "sequence": sequence,
        "role": role,
        "content": content,
        "branch_id": branch_id,
        "parent_message_id": f"m{sequence - 1}" if sequence > 1 else "",
    }


def test_living_transcript_keeps_only_recent_turns() -> None:
    messages = [
        _turn(1, "user", "第一轮问题"),
        _turn(2, "assistant", "第一轮结论"),
        _turn(3, "user", "第二轮问题"),
        _turn(4, "assistant", "第二轮结论"),
        _turn(5, "user", "第三轮问题"),
        _turn(6, "assistant", "第三轮结论"),
    ]

    living = living_transcript(messages)

    assert [item["content"] for item in living] == [
        "第二轮问题",
        "第二轮结论",
        "第三轮问题",
        "第三轮结论",
    ]
    assert living_user_questions(messages) == ["第二轮问题", "第三轮问题"]


def test_context_usage_marks_older_turns_as_compacted_memory() -> None:
    messages = [
        _turn(1, "user", "旧问题"),
        _turn(2, "assistant", "旧结论"),
        _turn(3, "user", "最近问题"),
        _turn(4, "assistant", "最近结论"),
        _turn(5, "user", "当前窗口"),
        _turn(6, "assistant", "当前结论"),
    ]
    memory = {
        "schema_version": "deep-working-memory-v1",
        "current_objective": "闭合直接毁伤判据",
        "user_constraints": ["不要增程"],
        "decisions": [{"candidate": "潜伏节点", "verdict": "keep", "reason": "改写进入时机"}],
        "latest_summary": ["保留潜伏先机方向"],
        "open_questions": ["反制后如何保持收益？"],
    }

    usage = conversation_context_usage(messages=messages, working_memory=memory)

    assert usage["living_turns"] == 2
    assert usage["archived_turns"] == 1
    assert usage["compacted"] is True
    assert usage["constraint_count"] == 1
    assert usage["decision_count"] == 1
    assert "决策记忆" in compaction_notice(usage)
    assert "当前窗口" not in str(working_memory_prompt(memory).get("latest_summary"))


def test_branch_path_still_feeds_living_window() -> None:
    messages = [
        _turn(1, "user", "主线问题"),
        _turn(2, "assistant", "主线结论"),
        _turn(3, "user", "分支问题", branch_id="explore"),
        _turn(4, "assistant", "分支结论", branch_id="explore"),
    ]
    path = branch_message_path(
        messages,
        "explore",
        [{"branch_id": "explore", "forked_from_message_id": "m2"}],
    )

    assert living_user_questions(path) == ["主线问题", "分支问题"]


def test_working_memory_keeps_closure_fields_for_card_restore() -> None:
    memory = build_working_memory(
        answer={
            "visible_summary": ["保留潜伏先机方向"],
            "selection_rationale": "机理与直接毁伤闭合",
            "finalization_status": "awaiting_user_confirmation",
            "concept_directions": [
                {
                    "name": "潜伏先机节点",
                    "winning_angle": "任务链重构",
                    "changed_assumption": "发射后必须立即攻击",
                    "equipment_form": "可潜伏展开的任务节点",
                    "operational_mechanism": "贴附潜伏后按局部态势协同作用",
                    "decisive_target": "高价值机动平台关键任务舱段",
                    "direct_damage_mechanism": "进入脆弱区后释放定向物理效应造成结构破坏",
                    "mission_kill_criterion": "目标关键任务舱段失效并退出当前任务周期",
                    "direct_military_effects": "延迟触发并压缩目标机动窗口",
                    "disruptive_difference": "从一次性弹药转为潜伏任务节点",
                    "stable": True,
                }
            ],
        },
        question="确认成卡",
    )
    prompt = working_memory_prompt(memory)

    assert prompt["selection_rationale"] == "机理与直接毁伤闭合"
    assert prompt["candidate_directions"][0]["decisive_target"]
    assert prompt["candidate_directions"][0]["direct_military_effects"]
    assert prompt["candidate_directions"][0]["stable"] is True


def test_working_memory_tracks_research_frontier_assumptions_and_strategy() -> None:
    memory = build_working_memory(
        answer={
            "visible_summary": ["完成一轮跨视角发散"],
            "concept_directions": [
                {
                    "name": "潜伏先机节点",
                    "winning_angle": "任务窗口重构",
                    "changed_assumption": "发射后必须立即攻击",
                    "equipment_form": "可潜伏展开的任务节点",
                    "stable": False,
                }
            ],
            "research_strategy": {
                "mode": "adaptive_divergence",
                "actions": ["diverge", "challenge"],
                "rationale": "先扩展假设，再用最低成本反制质疑",
                "lenses": ["任务链反转", "反适应"],
            },
            "research_assessment": {
                "gaps": ["仍需闭合任务失能判据"],
            },
            "orchestration": {
                "divergence_axes": ["颠覆·机理·链反转"],
                "internal_dimensions": ["边界条件突变"],
            },
            "open_questions": ["对手清场后如何保持收益？"],
        },
        question="继续深度发散",
    )

    assert memory["schema_version"] == "deep-working-memory-v2"
    assert memory["research_iteration"] == 1
    assert memory["research_frontier"][0]["direction"] == "潜伏先机节点"
    assert memory["research_frontier"][0]["status"] == "exploring"
    assert memory["assumption_ledger"][0]["assumption"] == "发射后必须立即攻击"
    assert "任务链反转" in memory["explored_lenses"]
    assert "边界条件突变" in memory["explored_lenses"]
    assert "仍需闭合任务失能判据" in memory["research_gaps"]
    assert memory["last_research_strategy"]["actions"] == ["diverge", "challenge"]
    prompt = working_memory_prompt(memory)
    assert prompt["research_frontier"] == memory["research_frontier"]
    assert prompt["assumption_ledger"] == memory["assumption_ledger"]
    usage = conversation_context_usage(working_memory=memory)
    assert usage["frontier_count"] == 1
    assert usage["assumption_count"] == 1
    assert usage["explored_lens_count"] >= 2
    assert usage["research_gap_count"] >= 1


def test_quoted_follow_up_becomes_a_user_constraint() -> None:
    formatted = format_quoted_user_message(
        "继续闭合失能判据",
        "把打击对象收到关键任务舱段",
    )
    quote, body = parse_quoted_user_message(formatted)
    assert quote == "把打击对象收到关键任务舱段"
    assert body == "继续闭合失能判据"

    messages = [
        _turn(1, "user", formatted),
        _turn(2, "assistant", "已按引用继续深化"),
    ]
    living = living_transcript(messages)
    assert "专家点名引用" not in living[0]["content"]
    assert "关键任务舱段" in living[0]["content"]
    assert living_user_questions(messages) == ["继续闭合失能判据"]

    memory = build_working_memory(answer={"visible_summary": ["深化失能判据"]}, question=formatted)
    assert memory["current_objective"] == "继续闭合失能判据"
    assert any("关键任务舱段" in item for item in memory["user_constraints"])
    assert working_memory_prompt(memory)["user_constraints"]


def test_partial_answer_does_not_erase_prior_decision_memory() -> None:
    previous = {
        "schema_version": "deep-working-memory-v1",
        "branch_id": "main",
        "current_objective": "闭合潜伏节点的直接毁伤判据",
        "user_constraints": ["不得退化为平台换壳"],
        "candidate_directions": [
            {
                "name": "潜伏先机节点",
                "winning_angle": "任务链重构",
                "equipment_form": "可潜伏展开的任务节点",
                "stable": True,
            }
        ],
        "decisions": [
            {
                "candidate": "潜伏先机节点",
                "verdict": "keep",
                "reason": "能够改写进入时机",
            }
        ],
        "rejected_directions": [
            {
                "candidate": "单纯增程弹",
                "verdict": "reject",
                "reason": "只有参数升级",
            }
        ],
        "latest_summary": ["保留潜伏节点方向"],
        "selection_rationale": "机理与目标闭合",
        "open_questions": ["低成本反制后如何保持收益？"],
        "finalization_status": "awaiting_user_confirmation",
        "research_iteration": 2,
        "research_frontier": [
            {
                "direction": "潜伏先机节点",
                "status": "stable",
                "next_probe": "清场反制后的收益",
            }
        ],
        "assumption_ledger": [
            {
                "assumption": "发射后必须立即攻击",
                "direction": "潜伏先机节点",
                "status": "retained",
            }
        ],
        "explored_lenses": ["任务链反转"],
        "research_gaps": ["清场反制后的收益"],
        "last_research_strategy": {"mode": "adaptive_divergence"},
    }

    memory = build_working_memory(
        answer={"visible_summary": []},
        question="继续，但本轮模型暂时不可用",
        previous=previous,
    )

    assert memory["candidate_directions"] == previous["candidate_directions"]
    assert memory["decisions"] == previous["decisions"]
    assert memory["rejected_directions"] == previous["rejected_directions"]
    assert memory["latest_summary"] == previous["latest_summary"]
    assert memory["open_questions"] == previous["open_questions"]
    assert memory["selection_rationale"] == previous["selection_rationale"]
    assert memory["finalization_status"] == previous["finalization_status"]
    assert memory["research_iteration"] == 3
    assert memory["research_frontier"] == previous["research_frontier"]
    assert memory["assumption_ledger"] == previous["assumption_ledger"]
    assert memory["explored_lenses"] == previous["explored_lenses"]
    assert memory["last_research_strategy"] == previous["last_research_strategy"]
