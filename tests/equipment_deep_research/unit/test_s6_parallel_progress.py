import asyncio

import pytest

from equipment_deep_research.agents.workflows import orchestrator as workflow


def test_parallel_columns_stream_in_completion_order_through_managed_provider(monkeypatch):
    monkeypatch.setattr(workflow, "_deep_dialogue_technology_column_publishable", lambda _: True)

    async def scenario():
        started = set()
        all_started = asyncio.Event()
        releases = {key: asyncio.Event() for key in workflow.DEEP_DIALOGUE_S6_CARD_FIELDS}
        progress = asyncio.Queue()

        class Host:
            def _emit_deep_dialogue_progress(self, row):
                if row.get("kind") == "answer":
                    progress.put_nowait(row)

        class Provider:
            async def complete_json(self, **kwargs):
                key = kwargs["payload"]["current_column"]["key"]
                started.add(key)
                if len(started) == 5:
                    all_started.set()
                await releases[key].wait()
                return {"content": f"Completed section: {key}"}

        task = asyncio.create_task(workflow._write_deep_dialogue_s6_columns(
            Host(), synthesis_payload={}, synthesis_spine={}, provider_runtime=Provider(),
        ))
        await asyncio.wait_for(all_started.wait(), 1)
        order = ["winning_logic", "overview", "operational_process",
                 "technology_implementation", "capability_effects"]
        for count, key in enumerate(order, 1):
            releases[key].set()
            row = await asyncio.wait_for(progress.get(), 1)
            assert row["column_key"] == key
            assert row["column_content"] == f"Completed section: {key}"
            assert row["completed_count"] == count
            assert row["total_count"] == 5
            if count < 5:
                assert not task.done()
        draft, failures = await task
        assert list(draft) == list(workflow.DEEP_DIALOGUE_S6_CARD_FIELDS)
        assert failures == []

    asyncio.run(scenario())


def test_exploratory_technology_answer_is_streamed_without_quality_retry():
    async def scenario():
        calls = {}
        rows = []

        class Host:
            def _emit_deep_dialogue_progress(self, row):
                rows.append(row)

            async def _run_core_json(self, agent, prompt, payload, schema, budget, *, phase):
                key = payload["current_column"]["key"]
                calls[key] = calls.get(key, 0) + 1
                if key == "technology_implementation":
                    if calls[key] == 1:
                        return {"content": "Rejected incomplete section"}
                    raise AssertionError("exploratory answer must not trigger a retry")
                return {"content": f"Completed section: {key}"}

        draft, failures = await workflow._write_deep_dialogue_s6_columns(
            Host(), synthesis_payload={}, synthesis_spine={},
        )
        assert len(draft) == 5
        assert draft["technology_implementation"] == "Rejected incomplete section"
        assert failures == []
        assert calls["technology_implementation"] == 1
        assert all(calls[key] == 1 for key in draft)
        answers = [row for row in rows if row["kind"] == "answer"]
        assert [row["completed_count"] for row in answers] == [1, 2, 3, 4, 5]
        technology_rows = [
            row for row in answers if row["column_key"] == "technology_implementation"
        ]
        assert technology_rows[0]["technology_research_status"] == "advisory_quality_gap"
        assert answers[-1]["status"] == "completed"

    asyncio.run(scenario())


def test_empty_technology_answer_stays_pending_after_bounded_recovery():
    async def scenario():
        rows = []

        class Host:
            def _emit_deep_dialogue_progress(self, row):
                rows.append(row)

            async def _run_core_json(self, _agent, _prompt, payload, _schema, _budget, *, phase):
                if payload["current_column"]["key"] == "technology_implementation":
                    return {"content": ""}
                return {"content": f"完整栏目：{payload['current_column']['key']}"}

        draft, failures = await workflow._write_deep_dialogue_s6_columns(
            Host(),
            synthesis_payload={},
            synthesis_spine={
                "selected_direction": {
                    "name": "测试装备",
                    "equipment_form": "分体任务节点",
                    "operational_mechanism": "在任务窗口内完成直接作用",
                }
            },
        )
        assert failures == ["第2栏“装备与技术实现”未完成"]
        assert "technology_implementation" not in draft
        technology_rows = [
            row
            for row in rows
            if row.get("column_key") == "technology_implementation"
            and row.get("kind") == "summary"
        ]
        assert technology_rows
        assert technology_rows[-1]["technology_research_status"] == "pending_retry"
        assert "来源边界" not in technology_rows[-1]["text"]
        assert not [
            row
            for row in rows
            if row.get("kind") == "answer"
            and row.get("column_key") == "technology_implementation"
        ]

    asyncio.run(scenario())


def test_technology_search_failure_uses_model_only_recovery():
    async def scenario():
        technology_phases = []

        class Host:
            def _emit_deep_dialogue_progress(self, _row):
                return None

        class Provider:
            async def complete_json(self, **kwargs):
                key = kwargs["payload"]["current_column"]["key"]
                phase = kwargs["phase"]
                if key == "technology_implementation":
                    technology_phases.append(phase)
                    if len(technology_phases) < 3:
                        # First the hosted-search turn, then the search-less
                        # retry both fail to produce visible prose.
                        return {"content": ""}
                    return {
                        "content": (
                            "模型依据已锁定构型直接给出工程路线：主路径采用弹载处理模块与传感器接口集成，"
                            "备选路径保留外部节点引导；核心瓶颈是时延、供能和热控耦合，需把算法落装到任务计算机并"
                            "通过硬件在环、环境试验和失效注入验证迁移断点与任务窗口。"
                        )
                    }
                return {"content": f"完整栏目：{key}"}

        draft, failures = await workflow._write_deep_dialogue_s6_columns(
            Host(),
            synthesis_payload={},
            synthesis_spine={},
            provider_runtime=Provider(),
        )

        assert failures == []
        assert draft["technology_implementation"].startswith("模型依据已锁定构型")
        assert technology_phases == [
            "deep_contextual_dialogue_s6_column_2",
            "deep_contextual_dialogue_s6_column_2_retry",
            "deep_contextual_dialogue_s6_column_2_model_recovery",
        ]

    asyncio.run(scenario())


def test_cancelling_card_cancels_all_column_workers():
    async def scenario():
        started = set()
        cancelled = set()
        all_started = asyncio.Event()

        class Provider:
            async def complete_json(self, **kwargs):
                key = kwargs["payload"]["current_column"]["key"]
                started.add(key)
                if len(started) == 5:
                    all_started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.add(key)

        task = asyncio.create_task(workflow._write_deep_dialogue_s6_columns(
            object(), synthesis_payload={}, synthesis_spine={}, provider_runtime=Provider(),
        ))
        await asyncio.wait_for(all_started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancelled == set(workflow.DEEP_DIALOGUE_S6_CARD_FIELDS)

    asyncio.run(scenario())


def test_s6_resume_reuses_completed_columns_and_checkpoints_new_results():
    async def scenario():
        calls = []
        checkpoints = []

        class Host:
            def _emit_deep_dialogue_progress(self, _row):
                return None

        class Provider:
            async def complete_json(self, **kwargs):
                key = kwargs["payload"]["current_column"]["key"]
                calls.append(key)
                return {"content": f"fresh:{key}"}

        resume = {
            "schema_version": "deep-s6-columns-checkpoint-v1",
            "kind": "deep_s6_column_checkpoint",
            "card_authoring_id": "job-1",
            "s6_columns": {
                key: {
                    "key": key,
                    "status": "completed",
                    "content": f"saved:{key}",
                    "attempt": 1,
                }
                for key in ("overview", "operational_process", "winning_logic")
            },
        }
        draft, failures = await workflow._write_deep_dialogue_s6_columns(
            Host(),
            synthesis_payload={},
            synthesis_spine={},
            provider_runtime=Provider(),
            checkpoint_callback=checkpoints.append,
            card_authoring_id="job-1",
            resume_checkpoint=resume,
        )

        assert failures == []
        assert set(calls) == {"technology_implementation", "capability_effects"}
        assert draft["overview"] == "saved:overview"
        assert draft["winning_logic"] == "saved:winning_logic"
        assert len(checkpoints) == 2
        assert all(item["completed_count"] == 4 + index for index, item in enumerate(checkpoints))
        assert checkpoints[-1]["s6_columns"]["overview"]["content"] == "saved:overview"
        assert checkpoints[-1]["s6_columns"]["technology_implementation"]["content"] == "fresh:technology_implementation"

    asyncio.run(scenario())


def test_s6_checkpoint_from_another_authoring_job_is_ignored():
    async def scenario():
        calls = []

        class Host:
            def _emit_deep_dialogue_progress(self, _row):
                return None

        class Provider:
            async def complete_json(self, **kwargs):
                key = kwargs["payload"]["current_column"]["key"]
                calls.append(key)
                return {"content": f"current:{key}"}

        draft, failures = await workflow._write_deep_dialogue_s6_columns(
            Host(),
            synthesis_payload={},
            synthesis_spine={},
            provider_runtime=Provider(),
            card_authoring_id="current-job",
            resume_checkpoint={
                "card_authoring_id": "stale-job",
                "s6_columns": {
                    "overview": {"status": "completed", "content": "stale"}
                },
            },
        )
        assert failures == []
        assert len(calls) == 5
        assert draft["overview"] == "current:overview"

    asyncio.run(scenario())


def test_s6_failed_column_is_not_reused_on_next_attempt():
    async def scenario():
        checkpoints = []
        calls = []

        class Host:
            def _emit_deep_dialogue_progress(self, _row):
                return None

        class FirstProvider:
            async def complete_json(self, **kwargs):
                key = kwargs["payload"]["current_column"]["key"]
                calls.append(key)
                if key == "capability_effects":
                    return {"content": ""}
                return {"content": f"saved:{key}"}

        draft, failures = await workflow._write_deep_dialogue_s6_columns(
            Host(),
            synthesis_payload={},
            synthesis_spine={},
            provider_runtime=FirstProvider(),
            checkpoint_callback=checkpoints.append,
            card_authoring_id="job-2",
        )
        assert any("能力与作战效果" in item for item in failures)
        assert "capability_effects" not in draft
        failed_checkpoint = checkpoints[-1]
        assert failed_checkpoint["s6_columns"]["capability_effects"]["status"] == "failed"

        calls.clear()

        class RetryProvider:
            async def complete_json(self, **kwargs):
                key = kwargs["payload"]["current_column"]["key"]
                calls.append(key)
                return {"content": f"retried:{key}"}

        resumed, retry_failures = await workflow._write_deep_dialogue_s6_columns(
            Host(),
            synthesis_payload={},
            synthesis_spine={},
            provider_runtime=RetryProvider(),
            checkpoint_callback=checkpoints.append,
            card_authoring_id="job-2",
            resume_checkpoint=failed_checkpoint,
        )
        assert retry_failures == []
        assert calls == ["capability_effects"]
        assert resumed["overview"] == "saved:overview"
        assert resumed["capability_effects"] == "retried:capability_effects"

    asyncio.run(scenario())
