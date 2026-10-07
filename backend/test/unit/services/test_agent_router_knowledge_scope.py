from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

agent_router = importlib.import_module("server.routers.agent_router")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("knowledge_ids", "expected_overrides"),
    [
        (None, {}),
        ([], {"context": {"knowledges": []}}),
        (
            [" kb-alpha ", "kb-beta", "kb-alpha", ""],
            {"context": {"knowledges": ["kb-alpha", "kb-beta"]}},
        ),
    ],
)
async def test_chat_knowledge_scope_is_run_local(
    monkeypatch: pytest.MonkeyPatch,
    knowledge_ids: list[str] | None,
    expected_overrides: dict,
) -> None:
    captured = {}

    async def submit_agent_request(**kwargs):
        captured.update(kwargs)
        return {"status": "queued"}

    monkeypatch.setattr(agent_router, "submit_agent_request", submit_agent_request)
    payload_data = {
        "query": "分析现有证据",
        "agent_slug": "assistant",
        "thread_id": "thread-1",
    }
    if knowledge_ids is not None:
        payload_data["knowledge_ids"] = knowledge_ids

    result = await agent_router.create_agent_run(
        agent_router.AgentRunCreate(**payload_data),
        current_user=SimpleNamespace(uid="user-1"),
        db=SimpleNamespace(),
    )

    assert result == {"status": "queued"}
    assert captured["request_input"].runtime_context_overrides == expected_overrides


@pytest.mark.asyncio
async def test_explicit_null_knowledge_scope_does_not_widen_agent_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    async def submit_agent_request(**kwargs):
        captured.update(kwargs)
        return {"status": "queued"}

    monkeypatch.setattr(agent_router, "submit_agent_request", submit_agent_request)
    payload = agent_router.AgentRunCreate(
        query="继续分析",
        agent_slug="assistant",
        thread_id="thread-1",
        knowledge_ids=None,
    )

    await agent_router.create_agent_run(
        payload,
        current_user=SimpleNamespace(uid="user-1"),
        db=SimpleNamespace(),
    )

    assert captured["request_input"].runtime_context_overrides == {}
