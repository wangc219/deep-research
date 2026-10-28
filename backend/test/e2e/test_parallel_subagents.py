"""通过真实模型、队列、worker 和状态接口验收两个异步子任务。"""

from datetime import datetime
from uuid import uuid4

import pytest

from e2e_helpers import cancel_run, delete_agent, wait_for_run
from test_subagent_stream_e2e import _create_agent, _create_run, _create_thread

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.slow]


async def test_two_subagents_run_concurrently_and_parent_collects_both(e2e_client, e2e_headers):
    """两个独立子线程须实际重叠运行，并由主智能体汇总各自结果。"""
    client, headers = e2e_client, e2e_headers
    me = (await client.get("/api/auth/me", headers=headers)).json()
    suffix = uuid4().hex[:8]
    child_slug, parent_slug = f"e2e-parallel-child-{suffix}", f"e2e-parallel-parent-{suffix}"
    share = {"version": 2, "read_scope": {"access_level": "user", "user_uids": [me["uid"]]}, "manage_scope": None}
    base = {"tools": [], "knowledges": [], "skills": [], "mcps": []}
    created = []
    run_id = thread_id = None
    try:
        for slug, backend, prompt in (
            (
                child_slug,
                "SubAgentBackend",
                "执行一次 execute 工具，命令为 python -c \"import time; time.sleep(8); print('CHILD_DONE')\"，"
                "然后原样返回任务中指定的标记。不要调用其他工具。",
            ),
            (
                parent_slug,
                "ChatbotAgent",
                f"把用户任务拆为两个独立子任务。必须先对 {child_slug} 连续调用两次 subagent_start。"
                "不要指定 thread_id，每次创建新线程，分别要求返回 PARALLEL_A 与 PARALLEL_B。"
                "启动两个任务后才能 await。等待两者完成后回复两者标记。不使用待办或其他工具。",
            ),
        ):
            await _create_agent(
                client,
                headers,
                {
                    "slug": slug,
                    "name": slug,
                    "backend_id": backend,
                    "is_subagent": backend == "SubAgentBackend",
                    "config_json": {
                        "context": {
                            **base,
                            "system_prompt": prompt,
                            **({"subagents": [child_slug]} if slug == parent_slug else {}),
                        }
                    },
                    "share_config": share,
                },
            )
            created.append(slug)
        thread_id, _ = await _create_thread(client, headers, parent_slug, suffix)
        run_id = await _create_run(
            client,
            headers,
            agent_slug=parent_slug,
            thread_id=thread_id,
            query="请启动两个独立子任务并行执行，等待两者完成，汇总 PARALLEL_A 和 PARALLEL_B。",
        )
        parent = await wait_for_run(client, headers, run_id)
        assert parent["status"] == "completed", parent
        state = (await client.get(f"/api/chat/thread/{thread_id}/state", headers=headers)).json()["agent_state"]
        children = state.get("subagent_runs") or []
        completed = [child for child in children if child["status"] == "completed"]
        assert len(completed) == 2, children
        assert len({child["child_thread_id"] for child in completed}) == 2
        runs = []
        for child in completed:
            child_state = (
                await client.get(f"/api/chat/thread/{child['child_thread_id']}/state", headers=headers)
            ).json()
            child_id = child_state["subagent_run"]["run_id"]
            runs.append((await client.get(f"/api/agent/runs/{child_id}", headers=headers)).json()["run"])
        starts = [datetime.fromisoformat(run["started_at"].replace("Z", "+00:00")) for run in runs]
        ends = [datetime.fromisoformat(run["finished_at"].replace("Z", "+00:00")) for run in runs]
        assert max(starts) < min(ends), "子任务没有实际并行运行"
        history = (await client.get(f"/api/chat/thread/{thread_id}/history", headers=headers)).text
        assert "PARALLEL_A" in history and "PARALLEL_B" in history
    finally:
        await cancel_run(client, headers, run_id)
        if thread_id:
            await client.delete(f"/api/chat/thread/{thread_id}", headers=headers)
        for slug in reversed(created):
            await delete_agent(client, headers, slug)
