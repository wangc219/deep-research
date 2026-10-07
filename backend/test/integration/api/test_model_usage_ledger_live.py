"""真实 HTTP 模型请求、PostgreSQL 账本与数据总览的闭环验收。"""

import asyncio
import json
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select, text

from equipment_deep_research.providers.base import ModelMessage
from equipment_deep_research.providers.registry import ProviderRegistry
from equipment_deep_research.providers.platform_access import configure_model_observer
from equipment_deep_research.providers.responses import ProviderRequestError
from platform_core.models.providers.cache import ModelInfo
from platform_core.services.equipment_model_usage import create_equipment_call_observer
from platform_core.services.dashboard_service import DashboardService
from platform_core.repositories import model_call_repository
from platform_core.repositories.model_call_repository import record_model_call
from platform_core.storage.postgres.manager import pg_manager
from platform_core.storage.postgres.models_business import Department, User
from platform_core.storage_migrations.v074_model_calls import MODEL_CALL_SCHEMA_STATEMENTS
from platform_core.utils.auth_utils import AuthUtils

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_outbox_replays_after_database_recovery(tmp_path, monkeypatch):
    """写库失败先持久排队，总览读取时自动补账且重复事件不双计。"""
    pg_manager.initialize()
    marker = "outbox_test_" + uuid4().hex[:12]
    monkeypatch.setenv(model_call_repository.OUTBOX_ENV, str(tmp_path / "model-call-outbox.db"))
    row = {
        "id": marker,
        "model_spec": marker + ":model",
        "surface": "辅助模型调用",
        "run_id": "",
        "phase": "recovery-test",
        "status": "completed",
        "duration_ms": 20.0,
        "input_tokens": 4,
        "output_tokens": 3,
        "total_tokens": 7,
        "error_type": "",
    }
    original_insert = model_call_repository._insert_model_calls

    def unavailable(_rows):
        raise ConnectionError("temporary outage")

    monkeypatch.setattr(model_call_repository, "_insert_model_calls", unavailable)
    await asyncio.to_thread(record_model_call, row)
    assert model_call_repository.flush_pending_model_calls()["pending"] == 1
    monkeypatch.setattr(model_call_repository, "_insert_model_calls", original_insert)

    try:
        async with pg_manager.get_async_session_context() as db:
            overview = await DashboardService(db).get_model_usage_overview()
            count = await db.scalar(text("SELECT COUNT(*) FROM platform_model_calls WHERE id=:id"), {"id": marker})
        assert count == 1
        assert overview["summary"]["pending_sync_call_count"] == 0
        model = next(item for item in overview["by_model"] if item["model_spec"] == row["model_spec"])
        assert model["call_count"] == 1
        assert model["total_tokens"] == 7

        await asyncio.to_thread(record_model_call, row)
        async with pg_manager.get_async_session_context() as db:
            assert await db.scalar(text("SELECT COUNT(*) FROM platform_model_calls WHERE id=:id"), {"id": marker}) == 1
    finally:
        async with pg_manager.get_async_session_context() as db:
            await db.execute(text("DELETE FROM platform_model_calls WHERE id=:id"), {"id": marker})
            await db.commit()
        await pg_manager.close()


async def test_model_requests_reach_dashboard_without_double_counting(monkeypatch):
    """重试、失败和三类旧入口都会计次，HTTP 趋势与模型汇总一致。"""
    pg_manager.initialize()
    marker = "usage_test_" + uuid4().hex[:12]
    spec = marker + ":neutral"
    retry_calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path.endswith(("/embeddings", "/rerank")):
                if self.path.endswith("/embeddings"):
                    result = {"data": [{"embedding": [0.1, 0.2]}], "usage": {"total_tokens": 5}}
                elif payload["query"] == "invalid":
                    result = {"results": [], "usage": {"total_tokens": 2}}
                else:
                    result = {"results": [{"index": 0, "relevance_score": 0.9}]}
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(result).encode())
                return
            prompt = payload["messages"][-1]["content"]
            if prompt == "fail" or (prompt == "retry" and not retry_calls):
                if prompt == "retry":
                    retry_calls.append(1)
                self.send_response(403 if prompt == "fail" else 429)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            frame = {
                "choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
            }
            self.wfile.write(("data: " + json.dumps(frame) + "\n\ndata: [DONE]\n\n").encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/v1"
    info = ModelInfo(
        provider_id=marker,
        model_id="neutral",
        model_type="chat",
        display_name="test",
        api_key="local-test-key",
        base_url=url,
        provider_type="openai",
    )
    monkeypatch.setattr("platform_core.services.equipment_model_usage.model_cache.get_all_specs", lambda _: [info])
    configure_model_observer(create_equipment_call_observer)
    headers = []
    async with pg_manager.get_async_session_context() as db:
        for _ in range(2):
            for statement in MODEL_CALL_SCHEMA_STATEMENTS:
                await db.execute(text(statement))
        department_id = await db.scalar(select(Department.id).limit(1))
        for role in ("superadmin", "user"):
            user = User(
                uid=marker + role,
                username=marker + role,
                password_hash="disabled-test-login",
                role=role,
                department_id=department_id,
            )
            db.add(user)
            await db.flush()
            headers.append({"Authorization": "Bearer " + AuthUtils.create_access_token({"sub": str(user.id)})})
        await db.commit()
    try:
        started_at = datetime.now(UTC).replace(tzinfo=None)
        registry = ProviderRegistry.load("/app/configs/equipment_deep_research/providers.yaml")
        for isolation in ("query-gen-" + marker, "deep-" + marker, "prompt-evolution"):
            provider = registry.create(
                "platform", model="neutral", base_url=url, api_key="local-test-key", isolation_key=isolation
            )
            async for _ in provider.stream([ModelMessage("user", "ok")], [], {"_run_id": marker}):
                pass
        provider = registry.create(
            "platform", model="neutral", base_url=url, api_key="local-test-key", isolation_key=marker
        )
        async for _ in provider.stream(
            [ModelMessage("user", "retry")], [], {"_run_id": marker, "_provider_retry_attempts": 2}
        ):
            pass
        with pytest.raises(ProviderRequestError):
            async for _ in provider.stream([ModelMessage("user", "fail")], [], {"_run_id": marker}):
                pass
        # 原生 Agent 中间件和通用模型 callback 同时存在时仍只记一次。
        from types import SimpleNamespace
        from langchain.agents.middleware.types import ModelResponse
        from langchain_core.messages import AIMessage, HumanMessage
        from platform_core.models.chat import load_chat_model
        from platform_core.agents.middlewares.token_usage import TokenUsageMiddleware

        monkeypatch.setattr("platform_core.models.chat.model_cache.get_model_info", lambda _: info)
        monkeypatch.setattr("platform_core.models.chat.get_docker_safe_url", lambda value: value)
        chat = load_chat_model(spec)

        async def invoke_chat():
            combined = None
            async for chunk in chat.astream([HumanMessage(content="ok")]):
                combined = chunk if combined is None else combined + chunk
            return AIMessage(content=combined.content, usage_metadata=combined.usage_metadata)

        await invoke_chat()
        request = SimpleNamespace(
            model=chat,
            state={"messages": []},
            messages=[HumanMessage(content="ok")],
            system_message=None,
            tools=[],
            runtime=SimpleNamespace(context=SimpleNamespace(run_id=marker, model=spec, summary_threshold=2)),
        )

        async def handler(_request):
            return ModelResponse(result=[await invoke_chat()])

        await TokenUsageMiddleware().awrap_model_call(request, handler)

        # 知识库实际 HTTP 请求也必须进入同一账本；无 usage 保持 NULL。
        from platform_core.models.embed import OtherEmbedding
        from platform_core.models.rerank import OpenAIReranker

        monkeypatch.setattr("platform_core.models.embed.get_docker_safe_url", lambda value: value)
        monkeypatch.setattr("platform_core.models.rerank.get_docker_safe_url", lambda value: value)
        embedding = OtherEmbedding(
            model="neutral", model_id=spec, base_url=url + "/embeddings", api_key="local-test-key"
        )
        assert await asyncio.to_thread(embedding.encode, ["test"]) == [[0.1, 0.2]]
        assert await embedding.aencode(["test"]) == [[0.1, 0.2]]
        reranker = OpenAIReranker(
            model_name="neutral", model_spec=spec, base_url=url + "/rerank", api_key="local-test-key"
        )
        try:
            assert await reranker.acompute_score(["test", ["document"]], normalize=False) == [0.9]
            # 保留业务降级，但协议无效仍应计为失败，不能误计为成功。
            assert await reranker.acompute_score(["invalid", ["document"]], normalize=False) == [0.5]
        finally:
            await reranker.aclose()

        async with pg_manager.get_async_session_context() as db:
            rows = (
                (await db.execute(text("SELECT * FROM platform_model_calls WHERE model_spec=:spec"), {"spec": spec}))
                .mappings()
                .all()
            )
        assert len(rows) == 12
        finished_at = datetime.now(UTC).replace(tzinfo=None)
        assert all(started_at <= r["created_at"] <= finished_at for r in rows)
        assert sum(r["total_tokens"] or 0 for r in rows) == 72
        assert sum(r["status"] == "failed" for r in rows) == 3
        assert sum(r["surface"] == "知识库嵌入" for r in rows) == 2
        rerank_rows = [r for r in rows if r["surface"] == "知识库重排"]
        assert len(rerank_rows) == 2
        assert next(r for r in rerank_rows if r["status"] == "completed")["total_tokens"] is None
        assert next(r for r in rerank_rows if r["status"] == "failed")["total_tokens"] == 2
        await asyncio.to_thread(record_model_call, dict(rows[0]))
        async with httpx.AsyncClient(base_url="http://127.0.0.1:5050", timeout=30) as client:
            response = await client.get("/api/dashboard/stats/model-usage", headers=headers[0])
            assert response.status_code == 200, response.text
            model = next(row for row in response.json()["by_model"] if row["model_spec"] == spec)
            assert model["call_count"] == 12
            assert model["total_tokens"] == 72
            assert "local-test-key" not in response.text
            denied = await client.get("/api/dashboard/stats/model-usage", headers=headers[1])
            assert denied.status_code == 403
            response = await client.get("/api/dashboard/stats/calls/timeseries?type=models", headers=headers[0])
            assert response.status_code == 200, response.text
            assert sum(row["data"].get(spec, 0) for row in response.json()["data"]) == 12
    finally:
        async with pg_manager.get_async_session_context() as db:
            await db.execute(
                text("DELETE FROM platform_model_calls WHERE model_spec=:spec OR run_id=:run_id"),
                {"spec": spec, "run_id": marker},
            )
            for uid in (marker + "superadmin", marker + "user"):
                await db.execute(text("DELETE FROM platform_request_metrics WHERE uid=:uid"), {"uid": uid})
                await db.execute(
                    text("DELETE FROM operation_logs WHERE user_id IN (SELECT id FROM users WHERE uid=:uid)"),
                    {"uid": uid},
                )
                await db.execute(delete(User).where(User.uid == uid))
            await db.commit()
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(timeout=2)
        await pg_manager.close()
