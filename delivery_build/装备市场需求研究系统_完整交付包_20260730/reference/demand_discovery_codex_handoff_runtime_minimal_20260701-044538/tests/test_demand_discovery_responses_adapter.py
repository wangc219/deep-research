from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import asyncio
import sys
import threading
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from knowledgegraph.demand_discovery.harness.tools import ToolDefinition  # noqa: E402
from knowledgegraph.demand_discovery.harness.types import (  # noqa: E402
    AgentMessage,
    AssistantContentBlock,
)
from knowledgegraph.demand_discovery.llm.model_config import ModelConfig  # noqa: E402
from knowledgegraph.demand_discovery.llm.responses_adapter import (  # noqa: E402
    ResponsesProvider,
    _default_sse_transport,
    build_codex_request,
    build_responses_request,
    map_responses_event,
    parse_sse_lines,
)
from knowledgegraph.demand_discovery.llm.types import LLMContext  # noqa: E402


async def _noop(call, ctx):
    raise AssertionError("not executed")


def _tool() -> ToolDefinition:
    return ToolDefinition(
        name="create_evidence_card",
        description="Create evidence",
        parameters_schema={"type": "object", "properties": {}},
        execute=_noop,
    )


class DemandDiscoveryResponsesAdapterTests(unittest.TestCase):
    def test_responses_compatible_builds_v1_request_without_codex_headers(self) -> None:
        config = ModelConfig(
            provider="openai",
            model="gpt-test",
            base_url="https://api.example.test",
            endpoint_mode="responses_compatible",
        )

        request = build_responses_request(
            config, LLMContext(messages=[]), [_tool()], {"text_verbosity": "low"}
        )

        self.assertEqual(request["url"], "https://api.example.test/v1/responses")
        self.assertEqual(request["payload"]["model"], "gpt-test")
        self.assertEqual(request["payload"]["tools"][0]["name"], "create_evidence_card")
        self.assertNotIn("OpenAI-Beta", request["headers"])
        self.assertNotIn("originator", request["headers"])
        self.assertEqual(request["payload"]["reasoning"]["effort"], "xhigh")

    def test_request_reasoning_effort_can_be_overridden_per_call(self) -> None:
        config = ModelConfig(provider="openai", model="gpt-test")

        request = build_responses_request(
            config,
            LLMContext(messages=[]),
            [],
            {"reasoning_effort": "high"},
        )

        self.assertEqual(request["payload"]["reasoning"]["effort"], "high")

    def test_codex_backend_normalizes_url_and_sets_codex_headers(self) -> None:
        config = ModelConfig(
            provider="codex",
            model="codex-test",
            base_url="https://codex.example.test/backend-api/",
            endpoint_mode="codex_backend",
        )

        request = build_codex_request(config, LLMContext(messages=[]), [], {})

        self.assertEqual(
            request["url"], "https://codex.example.test/backend-api/codex/responses"
        )
        self.assertEqual(request["headers"]["OpenAI-Beta"], "responses=experimental")
        self.assertIn("originator", request["headers"])

    def test_codex_backend_root_base_url_uses_v1_responses(self) -> None:
        config = ModelConfig(
            provider="codex",
            model="codex-test",
            base_url="https://codex-compatible.example.test",
            endpoint_mode="codex_backend",
        )

        request = build_codex_request(config, LLMContext(messages=[]), [], {})

        self.assertEqual(
            request["url"], "https://codex-compatible.example.test/v1/responses"
        )
        self.assertEqual(request["headers"]["OpenAI-Beta"], "responses=experimental")

    def test_codex_backend_endpoint_path_overrides_default_path(self) -> None:
        config = ModelConfig(
            provider="codex",
            model="codex-test",
            base_url="https://codex-compatible.example.test/api",
            endpoint_mode="codex_backend",
            endpoint_path="/v1/responses",
        )

        request = build_codex_request(config, LLMContext(messages=[]), [], {})

        self.assertEqual(
            request["url"], "https://codex-compatible.example.test/v1/responses"
        )

    def test_custom_endpoint_uses_exact_path_and_auth_header(self) -> None:
        config = ModelConfig(
            provider="custom",
            model="custom-test",
            base_url="https://proxy.example.test/root",
            endpoint_mode="custom_endpoint",
            endpoint_path="/exact/responses",
            auth_header="X-API-Key",
        )

        request = build_responses_request(
            config,
            LLMContext(messages=[]),
            [],
            {"api_key": "secret-key"},
        )

        self.assertEqual(request["url"], "https://proxy.example.test/exact/responses")
        self.assertEqual(request["headers"]["X-API-Key"], "secret-key")

    def test_tool_result_messages_convert_to_function_call_output(self) -> None:
        config = ModelConfig(provider="openai", model="gpt-test")
        context = LLMContext(
            messages=[
                AgentMessage(
                    role="tool_result",
                    content="created evidence ev-1",
                    timestamp=0,
                    tool_call_id="call-1",
                    tool_name="create_evidence_card",
                )
            ]
        )

        request = build_responses_request(config, context, [], {})

        self.assertEqual(
            request["payload"]["input"],
            [
                {
                    "type": "function_call_output",
                    "call_id": "call-1",
                    "output": "created evidence ev-1",
                }
            ],
        )
        self.assertNotIn("tool_result", str(request["payload"]["input"]))

    def test_tool_call_round_trip_uses_responses_function_items(self) -> None:
        config = ModelConfig(provider="openai", model="gpt-test")
        context = LLMContext(
            messages=[
                AgentMessage(
                    role="assistant",
                    content=[
                        AssistantContentBlock(
                            type="tool_call",
                            id="call-1",
                            name="create_evidence_card",
                            arguments={"evidence_id": "ev-1"},
                        )
                    ],
                    timestamp=0,
                ),
                AgentMessage(
                    role="tool_result",
                    content="created evidence ev-1",
                    timestamp=0,
                    tool_call_id="call-1",
                    tool_name="create_evidence_card",
                ),
            ]
        )

        request = build_responses_request(config, context, [], {})

        self.assertEqual(
            request["payload"]["input"],
            [
                {
                    "type": "function_call",
                    "call_id": "call-1",
                    "name": "create_evidence_card",
                    "arguments": '{"evidence_id": "ev-1"}',
                },
                {
                    "type": "function_call_output",
                    "call_id": "call-1",
                    "output": "created evidence ev-1",
                },
            ],
        )

    def test_model_config_trace_dict_redacts_sensitive_headers(self) -> None:
        config = ModelConfig(
            provider="custom",
            model="custom-test",
            headers={
                "Authorization": "Bearer SECRET",
                "X-API-Key": "SECRET",
                "api-key": "SECRET",
                "OpenAI-Api-Key": "SECRET",
                "X-Trace-Id": "trace-ok",
            },
            auth_header="X-API-Key",
        )

        trace = config.to_trace_dict()

        self.assertEqual(trace["headers"]["Authorization"], "<redacted>")
        self.assertEqual(trace["headers"]["X-API-Key"], "<redacted>")
        self.assertEqual(trace["headers"]["api-key"], "<redacted>")
        self.assertEqual(trace["headers"]["OpenAI-Api-Key"], "<redacted>")
        self.assertEqual(trace["headers"]["X-Trace-Id"], "trace-ok")
        self.assertNotIn("SECRET", str(trace))

    def test_output_schema_and_parallel_tool_calls_are_encoded_in_payload(self) -> None:
        config = ModelConfig(provider="openai", model="gpt-test")
        schema = {
            "type": "object",
            "required": ["audit_id"],
            "properties": {"audit_id": {"type": "string"}},
        }

        request = build_responses_request(
            config,
            LLMContext(messages=[]),
            [],
            {
                "text_verbosity": "low",
                "output_schema": schema,
                "output_schema_name": "audit_output",
                "parallel_tool_calls": False,
            },
        )

        payload = request["payload"]
        self.assertFalse(payload["parallel_tool_calls"])
        self.assertEqual(payload["text"]["verbosity"], "low")
        self.assertEqual(payload["text"]["format"]["type"], "json_schema")
        self.assertEqual(payload["text"]["format"]["name"], "audit_output")
        self.assertEqual(payload["text"]["format"]["schema"], schema)
        self.assertFalse(payload["text"]["format"]["strict"])

    def test_maps_responses_stream_events(self) -> None:
        mapped = [
            map_responses_event({"type": "response.output_text.delta", "delta": "hi"}),
            map_responses_event(
                {"type": "response.reasoning_summary_text.delta", "delta": "why"}
            ),
            map_responses_event(
                {
                    "type": "response.output_item.done",
                    "item": {
                        "type": "function_call",
                        "call_id": "c1",
                        "name": "tool",
                        "arguments": "{}",
                    },
                }
            ),
            map_responses_event({"type": "response.completed"}),
            map_responses_event(
                {"type": "response.failed", "error": {"message": "failed"}}
            ),
        ]

        self.assertEqual([event.type for event in mapped], [
            "text_delta",
            "thinking_delta",
            "toolcall_delta",
            "done",
            "error",
        ])
        self.assertEqual(mapped[2].payload["name"], "tool")
        self.assertEqual(mapped[4].payload["message"], "failed")

    def test_parse_sse_stops_after_completed(self) -> None:
        events = parse_sse_lines(
            [
                'data: {"type":"response.output_text.delta","delta":"a"}',
                "",
                'data: {"type":"response.completed"}',
                "",
                'data: {"type":"response.output_text.delta","delta":"ignored"}',
                "",
            ]
        )

        self.assertEqual([event.type for event in events], ["text_delta", "done"])
        self.assertEqual(events[0].payload["text"], "a")

    def test_completed_usage_is_mapped_to_done_event(self) -> None:
        events = parse_sse_lines(
            [
                'data: {"type":"response.output_text.delta","delta":"a"}',
                "",
                (
                    'data: {"type":"response.completed",'
                    '"response":{"usage":{"input_tokens":5,"output_tokens":3,'
                    '"input_token_details":{"cached_tokens":2}}}}'
                ),
                "",
            ]
        )

        self.assertEqual(events[-1].type, "done")
        self.assertEqual(events[-1].payload["usage"]["input_tokens"], 5)
        self.assertEqual(
            events[-1].payload["usage"]["input_token_details"]["cached_tokens"],
            2,
        )

    def test_completed_usage_normalizes_plural_input_token_details(self) -> None:
        events = parse_sse_lines(
            [
                (
                    'data: {"type":"response.completed",'
                    '"response":{"usage":{"input_tokens":5,"output_tokens":3,'
                    '"input_tokens_details":{"cached_tokens":2}}}}'
                ),
                "",
            ]
        )

        usage = events[-1].payload["usage"]

        self.assertEqual(usage["input_token_details"]["cached_tokens"], 2)
        self.assertEqual(usage["input_tokens_details"]["cached_tokens"], 2)

    def test_provider_stream_emits_delta_before_transport_completes(self) -> None:
        first_chunk_sent = threading.Event()
        allow_complete = threading.Event()

        def transport(request, timeout_ms):
            yield 'data: {"type":"response.output_text.delta","delta":"early"}'
            yield ""
            first_chunk_sent.set()
            allow_complete.wait(timeout=5)
            yield (
                'data: {"type":"response.completed",'
                '"response":{"usage":{"input_tokens":4,"output_tokens":2}}}'
            )
            yield ""

        async def run_probe():
            provider = ResponsesProvider(
                ModelConfig(provider="custom", model="gpt-test"),
                api_key="test-key",
                transport=transport,
            )
            stream = provider.stream(LLMContext(messages=[]), [], {})
            try:
                async for event in stream:
                    if event.type == "text_delta":
                        return event
            finally:
                allow_complete.set()
            raise AssertionError("text_delta not emitted")

        try:
            event = asyncio.run(asyncio.wait_for(run_probe(), timeout=0.5))
        finally:
            allow_complete.set()

        self.assertTrue(first_chunk_sent.is_set())
        self.assertEqual(event.payload["text"], "early")

    def test_provider_result_includes_completed_usage(self) -> None:
        def transport(request, timeout_ms):
            yield 'data: {"type":"response.output_text.delta","delta":"done"}'
            yield ""
            yield (
                'data: {"type":"response.completed",'
                '"response":{"usage":{"input_tokens":6,"output_tokens":4,'
                '"cached_tokens":1}}}'
            )
            yield ""

        async def run_provider():
            provider = ResponsesProvider(
                ModelConfig(provider="custom", model="gpt-test"),
                api_key="test-key",
                transport=transport,
            )
            stream = provider.stream(LLMContext(messages=[]), [], {})
            async for _event in stream:
                pass
            return stream.result()

        message = asyncio.run(run_provider())

        self.assertEqual(message.text(), "done")
        self.assertEqual(message.usage["input_tokens"], 6)
        self.assertEqual(message.usage["output_tokens"], 4)
        self.assertEqual(message.usage["cached_tokens"], 1)

    def test_streaming_transport_retries_reset_before_semantic_event(self) -> None:
        attempts = 0

        def transport(request, timeout_ms):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                yield ""
                raise ConnectionResetError("connection reset by peer")
            yield 'data: {"type":"response.output_text.delta","delta":"recovered"}'
            yield ""
            yield 'data: {"type":"response.completed"}'
            yield ""

        async def run_provider():
            provider = ResponsesProvider(
                ModelConfig(
                    provider="custom",
                    model="gpt-test",
                    max_retries=1,
                ),
                api_key="test-key",
                transport=transport,
            )
            stream = provider.stream(LLMContext(messages=[]), [], {})
            async for _event in stream:
                pass
            return stream.result()

        message = asyncio.run(run_provider())

        self.assertEqual(attempts, 2)
        self.assertEqual(message.text(), "recovered")

    def test_streaming_transport_does_not_retry_after_semantic_event(self) -> None:
        attempts = 0

        def transport(request, timeout_ms):
            nonlocal attempts
            attempts += 1
            yield 'data: {"type":"response.output_text.delta","delta":"partial"}'
            yield ""
            raise ConnectionResetError("connection reset by peer")

        async def run_provider():
            provider = ResponsesProvider(
                ModelConfig(
                    provider="custom",
                    model="gpt-test",
                    max_retries=1,
                ),
                api_key="test-key",
                transport=transport,
            )
            stream = provider.stream(LLMContext(messages=[]), [], {})
            async for _event in stream:
                pass
            return stream.result()

        with self.assertRaisesRegex(Exception, "connection reset"):
            asyncio.run(run_provider())

        self.assertEqual(attempts, 1)

    def test_parse_sse_waits_for_complete_function_call_arguments(self) -> None:
        events = parse_sse_lines(
            [
                (
                    'data: {"type":"response.output_item.added",'
                    '"output_index":0,'
                    '"item":{"type":"function_call","id":"fc-1",'
                    '"call_id":"call-1","name":"create_source_record",'
                    '"arguments":""}}'
                ),
                "",
                (
                    'data: {"type":"response.function_call_arguments.delta",'
                    '"output_index":0,"item_id":"fc-1",'
                    '"delta":"{\\"source_id\\":"}'
                ),
                "",
                (
                    'data: {"type":"response.function_call_arguments.delta",'
                    '"output_index":0,"item_id":"fc-1",'
                    '"delta":"\\"src-real-demo-1\\"}"}'
                ),
                "",
                (
                    'data: {"type":"response.function_call_arguments.done",'
                    '"output_index":0,"item_id":"fc-1",'
                    '"arguments":"{\\"source_id\\":\\"src-real-demo-1\\"}"}'
                ),
                "",
                'data: {"type":"response.completed"}',
                "",
            ]
        )

        self.assertEqual([event.type for event in events], ["toolcall_delta", "done"])
        self.assertEqual(events[0].payload["id"], "call-1")
        self.assertEqual(events[0].payload["name"], "create_source_record")
        self.assertEqual(
            events[0].payload["arguments"],
            {"source_id": "src-real-demo-1"},
        )

    def test_http_error_includes_response_body_without_request_headers(self) -> None:
        server = _ErrorServer(
            status=400,
            body=b'{"error":{"message":"invalid tool schema"}}',
        )
        server.start()
        try:
            with self.assertRaisesRegex(RuntimeError, "invalid tool schema") as ctx:
                list(
                    _default_sse_transport(
                        {
                            "url": server.url,
                            "headers": {"Authorization": "Bearer SECRET"},
                            "payload": {"model": "gpt-test"},
                        },
                        timeout_ms=10_000,
                    )
                )
        finally:
            server.stop()

        self.assertIn("HTTP 400", str(ctx.exception))
        self.assertNotIn("SECRET", str(ctx.exception))

    def test_http_404_error_includes_url_hint_without_request_headers(self) -> None:
        server = _ErrorServer(status=404, body=b"404 page not found")
        server.start()
        try:
            with self.assertRaisesRegex(RuntimeError, "requested URL") as ctx:
                list(
                    _default_sse_transport(
                        {
                            "url": server.url,
                            "headers": {"Authorization": "Bearer SECRET"},
                            "payload": {"model": "gpt-test"},
                        },
                        timeout_ms=10_000,
                    )
                )
        finally:
            server.stop()

        message = str(ctx.exception)
        self.assertIn("HTTP 404", message)
        self.assertIn(server.url, message)
        self.assertIn("--endpoint-mode responses_compatible", message)
        self.assertNotIn("SECRET", message)


class _ErrorServer:
    def __init__(self, status: int, body: bytes) -> None:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _ErrorHandler)
        self._server.status = status  # type: ignore[attr-defined]
        self._server.body = body  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}/v1/responses"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


class _ErrorHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            self.rfile.read(length)
        self.send_response(self.server.status)  # type: ignore[attr-defined]
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(self.server.body)  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: object) -> None:
        return


if __name__ == "__main__":
    unittest.main()
