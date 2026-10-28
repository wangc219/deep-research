"""真实模型、沙盒历史文件及 PostgreSQL checkpoint 的主动压缩验收。"""

import uuid
from pathlib import Path

import pytest
from e2e_helpers import cancel_run, delete_agent, wait_for_run
from test.live_api_cleanup import make_test_conversation_metadata, make_test_conversation_title

from platform_core.workspace.paths import user_workspace_dir

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.slow]


async def test_real_summary_preserves_fact_and_history(e2e_client, e2e_headers):
    """实际压缩旧轮次并回读历史文件，下一轮必须保留用户指定的唯一事实。"""
    client = e2e_client
    me = await client.get("/api/auth/me", headers=e2e_headers)
    assert me.status_code == 200, me.text
    uid = me.json()["uid"]
    slug = "e2e-summary-" + uuid.uuid4().hex[:10]
    thread_id = run_id = None
    marker = "SUMMARY_" + uuid.uuid4().hex[:12]
    response = await client.post(
        "/api/agent",
        headers=e2e_headers,
        json={
            "name": "真实摘要验收",
            "slug": slug,
            "backend_id": "ChatbotAgent",
            "config_json": {
                "context": {
                    "model": "siliconflow-cn:deepseek-ai/DeepSeek-V4-Flash",
                    "system_prompt": "回答简短。遵循用户要求记住验收标记。不要调用工具。",
                    "tools": [],
                    "skills": [],
                    "mcps": [],
                    "knowledges": [],
                    "subagents": [],
                    "summary_keep_messages": 2,
                }
            },
            "share_config": {
                "version": 2,
                "read_scope": {"access_level": "user", "user_uids": [uid]},
                "manage_scope": None,
            },
        },
    )
    assert response.status_code == 200, response.text
    try:
        response = await client.post(
            "/api/chat/thread",
            headers=e2e_headers,
            json={
                "agent_id": slug,
                "title": make_test_conversation_title("real-summary"),
                "metadata": make_test_conversation_metadata("real-summary", e2e=True),
            },
        )
        assert response.status_code == 200, response.text
        thread_id = response.json()["id"]
        for query in [
            f"请记住唯一验收标记：{marker}。只回复已记住。",
            "应急照明设备要检查电池。只回复收到。",
            "记录电缆检查和维护日期。只回复收到。",
        ]:
            response = await client.post(
                "/api/agent/runs",
                headers=e2e_headers,
                json={
                    "agent_slug": slug,
                    "thread_id": thread_id,
                    "query": query,
                    "meta": {"request_id": str(uuid.uuid4())},
                },
            )
            assert response.status_code == 200, response.text
            run_id = response.json()["run_id"]
            run = await wait_for_run(client, e2e_headers, run_id)
            assert run["status"] == "completed", run
        response = await client.post(f"/api/chat/thread/{thread_id}/compress", headers=e2e_headers, json={})
        assert response.status_code == 200, response.text
        compressed = response.json()
        assert compressed["status"] == "completed" and compressed["compressed_messages"] >= 2, compressed
        relative = Path(compressed["file_path"]).relative_to("/home/gem/user-data")
        history = user_workspace_dir(uid) / relative
        assert history.is_file() and marker in history.read_text(), compressed
        response = await client.get(
            f"/api/chat/thread/{thread_id}/state", params={"include_messages": True}, headers=e2e_headers
        )
        assert response.status_code == 200, response.text
        assert marker in str(response.json()), response.text
        response = await client.post(
            "/api/agent/runs",
            headers=e2e_headers,
            json={
                "agent_slug": slug,
                "thread_id": thread_id,
                "query": "请只输出最早记住的唯一验收标记。",
                "meta": {"request_id": str(uuid.uuid4())},
            },
        )
        assert response.status_code == 200, response.text
        run_id = response.json()["run_id"]
        run = await wait_for_run(client, e2e_headers, run_id)
        assert run["status"] == "completed", run
        response = await client.get(f"/api/agent/runs/{run_id}/result", headers=e2e_headers)
        assert response.status_code == 200, response.text
        assert marker in str(response.json()["output"]), response.text
        print(
            {
                "real_summary": "passed",
                "history_file": "persisted",
                "compressed_messages": compressed["compressed_messages"],
                "next_turn_fact": "preserved",
            }
        )
    finally:
        if run_id:
            await cancel_run(client, e2e_headers, run_id)
        if thread_id:
            await client.delete(f"/api/chat/thread/{thread_id}", headers=e2e_headers)
        await delete_agent(client, e2e_headers, slug)
