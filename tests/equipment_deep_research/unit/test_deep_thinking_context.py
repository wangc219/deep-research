"""Regression tests for visible deep-thinking result context projection."""

import json

from equipment_deep_research.deep_thinking import (
    MAX_CONTEXT_CHARS,
    _bounded_json,
    append_message,
    build_deep_complete_sections,
    create_session,
    format_deep_complete_answer,
    get_session,
    single_equipment_innovation_context,
    synthesize_reply,
    update_session,
)


def test_synthesize_reply_uses_nested_candidate_and_result_context() -> None:
    answer = synthesize_reply(
        query="强对抗环境下的无人装备体系",
        question="继续挑战这条假设",
        capability_name="默认方向",
        context_refs={
            "client_context": {
                "current_result_context": {
                    "selected": {
                        "title": "选中诱导蜂群",
                        "mechanism_chain": "把拦截资源拖入多点响应",
                        "evidence_ids": ["E-selected"],
                    },
                    "capability_cards": [{"name": "协同压制能力"}],
                    "reference_weapons": [{"title": "低成本诱饵集群"}],
                }
            }
        },
    )

    core = answer["sections"][0]["text"]
    divergence = answer["sections"][1]["text"]
    innovation = answer["sections"][2]["text"]
    assert "选中诱导蜂群" in core
    assert "把拦截资源拖入多点响应" in core
    assert "协同压制能力" not in divergence
    assert "低成本诱饵集群" not in divergence
    assert "E-selected" not in innovation
    assert answer["sections"][2]["title"] == "新质装备方向"


def test_synthesize_reply_prefers_explicit_candidate_over_aggregate_cards() -> None:
    answer = synthesize_reply(
        query="装备能力缺口",
        question="为何值得研究？",
        context_refs={
            "candidate": {
                "name": "显式候选方向",
                "winning_mechanism": "显式候选制胜机理",
                "validation_plan": "显式候选验证计划",
            },
            "client_context": {
                "current_result_context": {
                    "capability_cards": [{
                        "name": "已有能力卡",
                        "mechanism_chain": "不应覆盖显式候选",
                    }]
                }
            },
        },
    )

    core = answer["sections"][0]["text"]
    innovation = answer["sections"][2]["text"]
    assert "显式候选方向" in core
    assert "显式候选制胜机理" in core
    assert "显式候选验证计划" not in innovation


def test_innovation_context_keeps_only_query_equipment_and_expert_questions() -> None:
    projected = single_equipment_innovation_context(
        {
            "query": "低空目标精确打击",
            "candidate": {
                "name": "折脊穿隙攻击无人机",
                "operational_mechanism": "折叠进入狭小空间后展开作用面",
                "evidence_ids": ["ev-parent"],
                "validation_plan": "沿用父任务验证计划",
                "failure_boundary": "沿用父任务边界",
            },
            "evidence_index": {"ev-parent": {"title": "父任务证据"}},
            "round_summary": "父任务总结",
        },
        question="还能形成什么新构型？",
        messages=[
            {"role": "user", "content": "如何改写任务角色？"},
            {"role": "assistant", "content": "父任务证据说明……"},
        ],
    )

    encoded = json.dumps(projected, ensure_ascii=False)
    assert projected["context_policy"] == "query_equipment_questions_only"
    assert projected["source_equipment"]["name"] == "折脊穿隙攻击无人机"
    assert projected["prior_expert_questions"] == ["如何改写任务角色？"]
    assert projected["query_weapons"][0]["name"] == "折脊穿隙攻击无人机"
    assert "ev-parent" not in encoded
    assert "validation" not in encoded
    assert "failure_boundary" not in encoded
    assert "父任务总结" not in encoded


def test_session_artifacts_are_idempotently_upserted(tmp_path) -> None:
    session = create_session(tmp_path / "outputs", run_id="run-1")
    update_session(
        tmp_path / "outputs",
        run_id="run-1",
        session_id=session["session_id"],
        artifacts=[{"capability_id": "deep-cap-1", "name": "初稿"}],
    )
    update_session(
        tmp_path / "outputs",
        run_id="run-1",
        session_id=session["session_id"],
        artifacts=[{"capability_id": "deep-cap-1", "name": "修订稿", "merge_status": "merged_pending_verification"}],
    )

    saved = get_session(tmp_path / "outputs", run_id="run-1", session_id=session["session_id"])
    assert saved is not None
    assert len(saved["artifacts"]) == 1
    assert saved["artifacts"][0]["name"] == "修订稿"
    assert saved["artifacts"][0]["merge_status"] == "merged_pending_verification"


def test_sidecar_assistant_turn_is_idempotently_upserted(tmp_path) -> None:
    output_root = tmp_path / "outputs"
    session = create_session(output_root, run_id="run-1")
    user = append_message(
        output_root,
        run_id="run-1",
        session_id=session["session_id"],
        role="user",
        content="继续推演",
        turn_id="request-1",
    )
    first = append_message(
        output_root,
        run_id="run-1",
        session_id=session["session_id"],
        role="assistant",
        content="暂时结果",
        status="partial",
        artifact_refs=("artifact-1",),
        turn_id="job-1",
    )
    second = append_message(
        output_root,
        run_id="run-1",
        session_id=session["session_id"],
        role="assistant",
        content="重试后的完整结果",
        status="completed",
        artifact_refs=("artifact-2",),
        version_refs=("version-1",),
        turn_id="job-1",
    )

    assert second["message_id"] == first["message_id"]
    assert second["created_at"] == first["created_at"]
    assert second["parent_message_id"] == user["message_id"]
    saved = get_session(output_root, run_id="run-1", session_id=session["session_id"])
    assert saved is not None
    assert len(saved["messages"]) == 2
    assistant = saved["messages"][-1]
    assert assistant["content"] == "重试后的完整结果"
    assert assistant["status"] == "completed"
    assert assistant["artifact_refs"] == ["artifact-1", "artifact-2"]
    assert assistant["version_refs"] == ["version-1"]
    assert saved["turn_count"] == 1


def test_context_budget_is_total_and_sensitive_fields_are_removed() -> None:
    payload = {
        "name": "候选方向",
        "api_key": "should-not-survive",
        "fields": [{"text": "长文本" * 20_000} for _ in range(8)],
    }
    bounded = _bounded_json(payload)
    encoded = json.dumps(bounded, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert len(encoded) <= MAX_CONTEXT_CHARS
    assert "api_key" not in encoded


def test_build_deep_complete_sections_includes_final_summary_and_s6() -> None:
    sections = build_deep_complete_sections(
        visible_summary=["围绕目标装备完成收敛"],
        selection_rationale="保留潜伏先机方向",
        agent_dialogue=[
            {
                "role": "新质颠覆架构 Agent",
                "axis": "颠覆·机理·链反转",
                "round": "divergence",
                "summary": "提出潜伏节点",
                "proposal_names": ["潜伏先机节点"],
            },
            {
                "role": "对抗裁决 Agent",
                "round": "critique",
                "summary": "保留颠覆方向",
                "verdicts": ["潜伏先机节点→keep"],
            },
            {
                "role": "能力画像综合总编",
                "round": "synthesis",
                "summary": "完成五栏成卡",
                "proposal_names": ["潜伏先机节点"],
            },
        ],
        directions=[
            {
                "name": "潜伏先机节点",
                "winning_angle": "任务链重构",
                "changed_assumption": "发射后必须立即攻击",
                "equipment_form": "潜伏展开节点",
                "operational_mechanism": "贴附后按态势触发",
                "direct_military_effects": "压缩机动窗口",
                "disruptive_difference": "从一次性弹药转为潜伏节点",
            }
        ],
        capability_card_draft={
            "overview": "概述正文",
            "technology_implementation": "技术实现正文",
            "operational_process": "作战流程正文",
            "capability_effects": "作战效果正文",
            "winning_logic": "制胜逻辑正文",
        },
        adjudication={"mission_focus": "夺取先机制衡", "review_summary": "淘汰线性升级"},
        open_questions=["如何继续闭合构型？"],
    )
    titles = [item["title"] for item in sections]
    assert titles[0] == "本轮完整结果"
    assert "五栏能力画像" in titles
    assert "候选方向" in titles
    text = format_deep_complete_answer({"sections": sections})
    assert "### 本轮完整结果" in text
    assert "概述正文" in text
    assert "#### 概述" in text
    assert "潜伏先机节点" in text
    assert "- 制胜角度：任务链重构" in text
    assert "如何继续闭合构型？" in text
    assert text.count("### 本轮完整结果") == 1


def test_innovation_context_projects_query_weapons_without_evidence() -> None:
    projected = single_equipment_innovation_context(
        {
            "query": "低空精确打击",
            "candidate": {
                "name": "折脊穿隙攻击无人机",
                "equipment_form": "折叠穿隙攻击器",
                "operational_mechanism": "折叠进入后展开作用面",
            },
            "current_result_context": {
                "capability_cards": [{
                    "name": "协同压制蜂群",
                    "equipment_form": "低成本诱饵集群",
                    "operational_mechanism": "把拦截资源拖入多点响应",
                    "evidence_ids": ["ev-card"],
                    "validation_plan": "不应进入发散",
                }],
                "reference_weapons": [{
                    "title": "末段拦截巡飞弹",
                    "equipment_form": "巡飞拦截弹药",
                    "direct_military_effects": "压缩末段交战窗口",
                    "failure_boundary": "不应进入发散",
                }],
            },
        },
        question="还能形成什么新构型？",
    )

    names = [item["name"] for item in projected["query_weapons"]]
    encoded = json.dumps(projected, ensure_ascii=False)
    assert "折脊穿隙攻击无人机" in names
    assert "协同压制蜂群" in names
    assert "末段拦截巡飞弹" in names
    assert "ev-card" not in encoded
    assert "validation_plan" not in encoded
    assert "failure_boundary" not in encoded
    assert "以当前 Query 下已有武器装备为基线" in projected["innovation_goal"]


def test_innovation_context_uses_living_window_instead_of_full_history() -> None:
    projected = single_equipment_innovation_context(
        {
            "query": "低空精确打击",
            "candidate": {"name": "折脊穿隙攻击无人机"},
        },
        question="继续闭合毁伤判据",
        messages=[
            {"role": "user", "content": "第一轮问题"},
            {"role": "assistant", "content": "第一轮结论"},
            {"role": "user", "content": "第二轮问题"},
            {"role": "assistant", "content": "第二轮结论"},
            {"role": "user", "content": "第三轮问题"},
            {"role": "assistant", "content": "第三轮结论"},
        ],
        working_memory={
            "schema_version": "deep-working-memory-v1",
            "current_objective": "闭合直接毁伤判据",
            "latest_summary": ["保留潜伏先机方向"],
            "user_constraints": ["不要增程"],
            "decisions": [{"candidate": "潜伏节点", "verdict": "keep"}],
        },
    )

    encoded = json.dumps(projected, ensure_ascii=False)
    assert "第一轮问题" not in projected["prior_expert_questions"]
    assert projected["prior_expert_questions"][:2] == ["第二轮问题", "第三轮问题"]
    assert any(item["content"] == "第三轮结论" for item in projected["living_transcript"])
    assert "第一轮结论" not in encoded
    assert projected["working_memory"]["current_objective"] == "闭合直接毁伤判据"
    assert "战创灵境" in projected["identity"]


def test_build_deep_complete_sections_states_leap_from_query_weapons() -> None:
    sections = build_deep_complete_sections(
        visible_summary=["围绕目标装备完成收敛"],
        selection_rationale="保留潜伏先机方向",
        directions=[{
            "name": "潜伏先机节点",
            "winning_angle": "任务链重构",
            "changed_assumption": "发射后必须立即攻击",
            "equipment_form": "潜伏展开节点",
            "operational_mechanism": "贴附后按态势触发",
            "direct_military_effects": "压缩机动窗口",
            "disruptive_difference": "从一次性弹药转为潜伏节点",
        }],
        source_equipment_label="折脊穿隙攻击无人机",
        query_weapon_names=["折脊穿隙攻击无人机", "协同压制蜂群"],
    )
    lead = sections[0]["text"]
    assert "折脊穿隙攻击无人机" in lead
    assert "潜伏先机节点" in lead
    assert "Query 已有装备" in lead
