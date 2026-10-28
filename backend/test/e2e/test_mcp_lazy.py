"""真实模型通过按需发现调用 Streamable HTTP MCP。"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from uuid import uuid4

import pytest

from e2e_helpers import cancel_run, delete_agent, wait_for_run
from test_subagent_stream_e2e import _create_agent, _create_run, _create_thread

pytestmark = [pytest.mark.asyncio, pytest.mark.e2e, pytest.mark.slow]


async def test_real_model_loads_mcp_then_invokes_dynamic_tool(e2e_client, e2e_headers):
    """模型、队列与 worker 必须完成服务发现到远程工具执行的完整闭环。"""
    client, headers = e2e_client, e2e_headers
    suffix = uuid4().hex[:8]
    marker, slug, agent_slug = f"MCP_VERIFIED_{suffix}", f"pytest-lazy-{suffix}", f"e2e-lazy-{suffix}"
    methods = []

    class Handler(BaseHTTPRequestHandler):
        """提供无副作用的 MCP 协议对端。"""

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            method = request.get("method")
            methods.append(method)
            if "id" not in request:
                self.send_response(202)
                self.end_headers()
                return
            if method == "initialize":
                result = {
                    "protocolVersion": request["params"]["protocolVersion"],
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "acceptance", "version": "1"},
                }
            elif method == "tools/list":
                result = {
                    "tools": [
                        {
                            "name": "acceptance_echo",
                            "description": "返回验收标记",
                            "inputSchema": {"type": "object", "properties": {}},
                        }
                    ]
                }
            elif method == "tools/call":
                assert request["params"]["name"] == "acceptance_echo"
                result = {"content": [{"type": "text", "text": marker}], "isError": False}
            else:
                raise AssertionError(method)
            payload = json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            self.send_response(405)
            self.end_headers()

        def log_message(self, *_):
            pass

    protocol = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
    thread = Thread(target=protocol.serve_forever, daemon=True)
    thread.start()
    created = False
    thread_id = run_id = None
    try:
        me = (await client.get("/api/auth/me", headers=headers)).json()
        response = await client.post(
            "/api/system/mcp-servers",
            headers=headers,
            json={
                "slug": slug,
                "name": "MCP 验收服务",
                "transport": "streamable_http",
                "url": f"http://api:{protocol.server_port}/mcp",
                "description": "调用 acceptance_echo 获取验证标记",
            },
        )
        assert response.status_code == 200, response.text
        await _create_agent(
            client,
            headers,
            {
                "slug": agent_slug,
                "name": agent_slug,
                "backend_id": "ChatbotAgent",
                "config_json": {
                    "context": {
                        "mcps": [slug],
                        "mcp_tool_loading": "on_demand",
                        "tools": [],
                        "skills": [],
                        "knowledges": [],
                        "subagents_enabled": False,
                        "system_prompt": (
                            f"必须先调用 load_mcp_tools 加载 {slug}，再调用其 acceptance_echo 工具。"
                            "最后原样回复工具返回的标记。不要调用其他工具，不要猜测标记。"
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
        created = True
        assert not methods, "构图之前不应连接 MCP"
        thread_id, _ = await _create_thread(client, headers, agent_slug, suffix)
        run_id = await _create_run(
            client,
            headers,
            agent_slug=agent_slug,
            thread_id=thread_id,
            query="请调用配置的验证服务，返回它提供的标记。",
        )
        run = await wait_for_run(client, headers, run_id)
        assert run["status"] == "completed", run
        assert "tools/list" in methods and "tools/call" in methods, methods
        history = await client.get(f"/api/chat/thread/{thread_id}/history", headers=headers)
        assert marker in history.text
        assert "load_mcp_tools" in history.text and "acceptance_echo" in history.text
    finally:
        await cancel_run(client, headers, run_id)
        if thread_id:
            await client.delete(f"/api/chat/thread/{thread_id}", headers=headers)
        if created:
            await delete_agent(client, headers, agent_slug)
        await client.delete(f"/api/system/mcp-servers/{slug}", headers=headers)
        protocol.shutdown()
        protocol.server_close()
        thread.join(timeout=5)
