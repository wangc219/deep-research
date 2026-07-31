from __future__ import annotations

from pathlib import Path
import sys
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.harness.events import AgentEvent  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import (  # noqa: E402
    AgentMessage,
    AssistantContentBlock,
    DomainWriteProposal,
    DomainTraceProposal,
    ToolCall,
    ToolResult,
    UserMessage,
)


class DemandDiscoveryTypesTests(unittest.TestCase):
    def test_messages_round_trip_to_dict(self) -> None:
        user = UserMessage(content="start", timestamp=1)
        assistant = AgentMessage(
            role="assistant",
            content=[AssistantContentBlock(type="text", text="hello")],
            timestamp=2,
        )

        self.assertEqual(user.to_dict()["role"], "user")
        self.assertEqual(assistant.to_dict()["content"][0]["text"], "hello")

    def test_tool_call_and_result_shape(self) -> None:
        call = ToolCall(id="call-1", name="echo", arguments={"text": "hi"})
        result = ToolResult(
            tool_call_id=call.id,
            tool_name=call.name,
            content="hi",
            details={"length": 2},
            domain_proposals=[
                DomainWriteProposal(
                    action="upsert",
                    object_type="EvidenceCard",
                    payload={"evidence_id": "ev-1"},
                )
            ],
            trace_proposals=[
                DomainTraceProposal(
                    event_type="evidence_created",
                    target_type="EvidenceCard",
                    target_id="ev-1",
                    payload_summary="created ev-1",
                    output_refs=["ev-1"],
                )
            ],
            is_error=False,
            terminate=False,
        )

        self.assertEqual(result.to_message().role, "tool_result")
        self.assertEqual(result.to_message().tool_call_id, "call-1")
        self.assertEqual(result.domain_proposals[0].object_type, "EvidenceCard")
        self.assertEqual(result.trace_proposals[0].event_type, "evidence_created")

    def test_agent_event_shape(self) -> None:
        event = AgentEvent(type="turn_start", run_id="run-1", payload={"turn": 1})

        self.assertEqual(event.type, "turn_start")
        self.assertEqual(event.payload["turn"], 1)


if __name__ == "__main__":
    unittest.main()
