from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage

from platform_core.agents.base import _replace_checkpoint_message_branch

pytestmark = [pytest.mark.unit]


class _Graph:
    def __init__(self, messages, summary_event=None):
        self.messages = messages
        self.summary_event = summary_event

    async def aget_state(self, _config):
        return SimpleNamespace(
            values={
                "messages": self.messages,
                "_summarization_event": self.summary_event,
            }
        )


@pytest.mark.asyncio
async def test_checkpoint_replacement_removes_old_branch_before_new_question():
    graph = _Graph(
        [
            HumanMessage(id="human-1", content="first"),
            AIMessage(id="ai-1", content="first answer"),
            HumanMessage(id="human-2", content="old question"),
            AIMessage(id="ai-2", content="old answer"),
        ]
    )
    new_question = HumanMessage(id="human-3", content="new question")

    graph_input = await _replace_checkpoint_message_branch(
        graph,
        {"configurable": {"thread_id": "thread-1"}},
        {"messages": [new_question]},
        {"source_id": "human-2", "content": "old question"},
    )

    assert [type(message) for message in graph_input["messages"]] == [
        RemoveMessage,
        RemoveMessage,
        HumanMessage,
    ]
    assert [message.id for message in graph_input["messages"]] == ["human-2", "ai-2", "human-3"]


@pytest.mark.asyncio
async def test_checkpoint_replacement_rejects_non_latest_human_message():
    graph = _Graph(
        [
            HumanMessage(id="human-1", content="older"),
            AIMessage(id="ai-1", content="answer"),
            HumanMessage(id="human-2", content="latest"),
        ]
    )

    with pytest.raises(ValueError, match="不是 checkpoint 中最新"):
        await _replace_checkpoint_message_branch(
            graph,
            {"configurable": {"thread_id": "thread-1"}},
            {"messages": [HumanMessage(content="edited")]},
            {"source_id": "human-1", "content": "older"},
        )
