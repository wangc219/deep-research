"""真实模型、Open Websearch 和 AMiner 的公开资料检索闭环。"""

import json
from uuid import uuid4

import asyncpg
import pytest

from e2e_helpers import cancel_run, delete_agent, postgres_dsn, wait_for_run
from test_subagent_stream_e2e import _create_agent, _create_run, _create_thread

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.slow]


async def test_real_web_and_academic_retrieval(e2e_client, e2e_headers):
    """供应商返回真实结果后才记为通过，降级或空结果不能冒充成功。"""
    client, headers = e2e_client, e2e_headers
    me = (await client.get("/api/auth/me", headers=headers)).json()
    slug = "e2e-retrieval-" + uuid4().hex[:8]
    run_id = thread_id = None
    await _create_agent(
        client,
        headers,
        {
            "slug": slug,
            "name": "真实检索验收",
            "backend_id": "ChatbotAgent",
            "config_json": {
                "context": {
                    "tools": ["web_search", "academic_search", "academic_get_papers"],
                    "skills": ["academic-evidence"],
                    "preload_skills": ["academic-evidence"],
                    "knowledges": [],
                    "mcps": [],
                    "subagents": [],
                    "subagents_enabled": False,
                    "system_prompt": (
                        "本轮只验收公开的软件文档解析资料检索。实际调用一次 web_search 搜索 Docling PDF parsing，"
                        "实际调用 academic_search 搜索 document layout analysis，"
                        "选择一篇论文调用 academic_get_papers 获取摘要。"
                        "不创建文件或子任务。最后用三句话说明获得的网页与论文证据并给出真实来源。"
                        "任何服务失败必须如实说明，不得把无结果说成成功。"
                    ),
                }
            },
            "share_config": {
                "version": 2,
                "read_scope": {"access_level": "user", "user_uids": [me["uid"]]},
                "manage_scope": None,
            },
        },
    )
    try:
        thread_id, _ = await _create_thread(client, headers, slug, uuid4().hex[:8])
        run_id = await _create_run(
            client,
            headers,
            agent_slug=slug,
            thread_id=thread_id,
            query="请实际完成网页检索、论文检索和论文摘要读取的软件验收。",
        )
        run = await wait_for_run(client, headers, run_id)
        assert run["status"] == "completed", run
        conn = await asyncpg.connect(postgres_dsn())
        try:
            rows = await conn.fetch(
                "SELECT t.tool_name,t.tool_output,t.status FROM tool_calls t "
                "JOIN messages m ON m.id=t.message_id WHERE m.run_id=$1",
                run_id,
            )
        finally:
            await conn.close()
        by_name = {row["tool_name"]: row for row in rows}
        for name in ("web_search", "academic_search", "academic_get_papers"):
            assert name in by_name, list(by_name)
            row = by_name[name]
            assert row["status"] == "success", dict(row)
            output = json.loads(row["tool_output"] or "{}")
            assert isinstance(output, dict), (name, output)
            assert output.get("status", "ok") == "ok", (name, output)
            assert not output.get("error"), (name, output)
            results = output.get("results")
            assert isinstance(results, list) and results, (name, output)
            assert all(item.get("title") for item in results), (name, results)
            if name == "web_search":
                assert all(str(item.get("url", "")).startswith("http") for item in results), results
            else:
                assert output.get("source") == "aminer", output
                assert all(item.get("id") for item in results), results
                if name == "academic_get_papers":
                    assert any(item.get("content_level") == "abstract" and item.get("content") for item in results), (
                        results
                    )
        print(
            json.dumps(
                {
                    "run_id": run_id,
                    "real_web_search": "passed",
                    "real_aminer_search": "passed",
                    "real_paper_abstract": "passed",
                    "tools": list(by_name),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    finally:
        await cancel_run(client, headers, run_id)
        if thread_id:
            await client.delete(f"/api/chat/thread/{thread_id}", headers=headers)
        await delete_agent(client, headers, slug)
