import asyncio

from equipment_deep_research.deep_runtime.agent_spec import (
    AgentSpec,
    spec_from_payload,
)
from equipment_deep_research.deep_runtime.identity import IDENTITY_SKILL
from equipment_deep_research.deep_runtime.subagents import (
    SubagentPool,
    SubagentResult,
    SubagentTask,
    attach_prior_findings,
    plan_subagent_tasks,
)


def test_resource_selection_matches_yuxi_semantics() -> None:
    spec = AgentSpec.from_mapping(
        {
            "tools": ["deepen", "challenge", "unknown"],
            "skills": None,
            "subagents": ["research-explorer", "missing"],
            "system_prompt": "只回答可证伪的方向。",
        }
    )
    assert spec.resolved_tools()[:2] == ("deepen", "challenge")
    assert "help" in spec.resolved_tools()
    assert spec.resolved_skills(["a", "b"]) == ("a", "b")
    assert spec.resolved_subagents(["research-explorer", "fact-verifier"]) == (
        "research-explorer",
    )
    overlay = spec.overlay_prompt(IDENTITY_SKILL)
    assert IDENTITY_SKILL in overlay
    assert "只回答可证伪的方向" in overlay


def test_empty_subagents_disable_dispatch() -> None:
    spec = AgentSpec.from_mapping({"subagents": []})
    assert spec.subagents_enabled is False
    assert spec.resolved_subagents(["research-explorer"]) == ()


def test_spec_from_payload_prefers_nested_agent_spec() -> None:
    spec = spec_from_payload(
        {
            "active_skill_ids": ["ignored"],
            "agent_spec": {
                "skills": ["counterfactual_triz_innovation"],
                "enable_subagents": True,
            },
        }
    )
    assert spec.skills == ("counterfactual_triz_innovation",)
    assert spec.subagents_enabled is True


def test_plan_subagent_tasks_for_complex_turns() -> None:
    tasks = plan_subagent_tasks(
        ["research_council"],
        "如何改写该装备的进入窗口？",
    )
    assert [item.slug for item in tasks] == [
        "research-explorer",
        "research-explorer",
        "fact-verifier",
    ]
    assert [item.task_id for item in tasks] == [
        "research_explorer_configuration",
        "research_explorer_countermeasure",
        "fact_verifier",
    ]
    challenge = plan_subagent_tasks(["challenge"], "核验当前方向")
    assert [item.slug for item in challenge] == ["fact-verifier"]


class _FakeRunner:
    async def run(self, task: SubagentTask) -> SubagentResult:
        return SubagentResult(
            task.task_id,
            task.role,
            "completed",
            finding=f"{task.slug or task.task_id}-ok",
            slug=task.slug,
            kind=task.kind,
        )


def test_subagent_pool_starts_then_awaits_in_parallel() -> None:
    async def scenario() -> None:
        pool = SubagentPool(_FakeRunner(), max_concurrent=3, max_tasks=3)
        tasks = plan_subagent_tasks(["diverge"], "正交构型")
        handles = [await pool.start(task) for task in tasks]
        assert all(handle.status == "running" for handle in handles)
        results = [await pool.await_run(handle.run_id) for handle in handles]
        assert {item.status for item in results} == {"completed"}
        assert {item.slug for item in results} == {"research-explorer", "fact-verifier"}

    asyncio.run(scenario())


def test_nested_subagent_pool_is_rejected() -> None:
    async def scenario() -> None:
        pool = SubagentPool(_FakeRunner(), nested=True)
        task = plan_subagent_tasks(["challenge"], "反例")[0]
        handle = await pool.start(task)
        result = await pool.await_run(handle.run_id)
        assert result.status == "failed"
        assert "cannot spawn" in result.error

    asyncio.run(scenario())


def test_omitted_skills_do_not_force_activation() -> None:
    spec = AgentSpec.from_mapping({})
    assert spec.skills is None
    assert spec.resolved_skills(["a", "b", "c"]) == ("a", "b", "c")


def test_plan_deepen_uses_research_explorer_lenses() -> None:
    tasks = plan_subagent_tasks(
        ["deepen"],
        "沿当前方向继续发散",
    )
    assert [item.slug for item in tasks] == ["research-explorer", "research-explorer"]


def test_complex_turn_dispatches_specialized_subagents() -> None:
    from equipment_deep_research.deep_runtime.loop import _run_deep_research_turn

    class Host:
        def _emit_deep_dialogue_progress(self, _row: dict) -> None:
            return None

    class Runner:
        def __init__(self) -> None:
            self.seen: list[str] = []

        async def run_many(self, tasks):
            self.seen = [task.slug for task in tasks]
            return [
                SubagentResult(
                    task.task_id,
                    task.role,
                    "completed",
                    finding=f"{task.slug}-ok",
                    slug=task.slug,
                    kind=task.kind,
                )
                for task in tasks
            ]

    runner = Runner()
    result = asyncio.run(
        _run_deep_research_turn(
            Host(),
            {
                "question": "如何改写该装备的进入窗口？",
                "enable_subagents": True,
                "agent_spec": {
                    "enable_subagents": True,
                    "subagents": ["research-explorer", "fact-verifier"],
                },
                "subagent_runner": runner,
            },
        )
    )
    assert runner.seen == ["research-explorer", "research-explorer", "fact-verifier"]
    assert [item["slug"] for item in result["subagent_results"]] == [
        "research-explorer",
        "research-explorer",
        "fact-verifier",
    ]
    assert result["runtime"]["subagents"]["parallel"] is True
    assert result["runtime"]["subagents"]["nesting"] is False


def test_research_waves_verify_after_parallel_exploration() -> None:
    async def scenario() -> None:
        pool = SubagentPool(_FakeRunner(), max_concurrent=3, max_tasks=3)
        tasks = plan_subagent_tasks(["research_council"], "进入窗口")
        results = await pool.dispatch_research_waves(tasks)
        assert [item.slug for item in results] == [
            "research-explorer",
            "research-explorer",
            "fact-verifier",
        ]
        verifier_task = attach_prior_findings(tasks[-1], results[:-1])
        assert verifier_task.context["prior_subagent_findings"]
        assert "核验" in verifier_task.prompt

    asyncio.run(scenario())


def test_seed_payload_carries_subagent_findings_for_synthesis() -> None:
    from equipment_deep_research.agents.workflows.orchestrator import (
        _compact_deep_dialogue_seed_payload,
    )

    compact = _compact_deep_dialogue_seed_payload(
        {
            "question": "进入窗口",
            "subagent_context": [
                {
                    "role": "深度调研",
                    "slug": "research-explorer",
                    "status": "completed",
                    "finding": "正交构型可改写入窗时机",
                    "next_probe": "核验最低成本反制",
                    "assumptions": ["单装备身份不变"],
                }
            ],
        }
    )
    assert compact["subagent_findings"][0]["finding"] == "正交构型可改写入窗时机"
    assert "综合" in compact["subagent_merge_policy"]
