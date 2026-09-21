from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from equipment_deep_research.deep_runtime.channel import (
    InboundMessage,
    MessageBus,
    OutboundMessage,
)
from equipment_deep_research.deep_runtime.gateways import (
    ChannelPayloadRejected,
    DiscordGatewayAdapter,
    GatewayDeliveryCache,
    GatewayIdentity,
    TelegramGatewayAdapter,
    VerifiedChannelGateway,
    dispatch_gateway_payload,
    dispatch_verified_gateway_payload,
    WebhookReplayCache,
    WebhookSignaturePolicy,
)
from equipment_deep_research.deep_runtime.provider_runtime import (
    ProviderRequest,
    ProviderResult,
    ProviderRuntime,
)
from equipment_deep_research.deep_runtime.loop import (
    _canonical_identity_projection,
    run_deep_research_message,
)
from equipment_deep_research.deep_runtime import loop as runtime_loop
from equipment_deep_research.deep_runtime.subagents import (
    LightweightSubagentRunner,
    SubagentTask,
    default_divergence_subtasks,
    tasks_from_payload,
)
from equipment_deep_research.providers.base import (
    ModelMessage,
    ProviderFinalTurn,
    ProviderStreamEvent,
    ProviderToolCall,
)
from equipment_deep_research.providers.fake import ScriptedFakeProvider


def test_message_bus_keeps_channel_and_core_separate() -> None:
    async def scenario() -> None:
        bus = MessageBus()
        inbound = InboundMessage("web", "user-1", "chat-1", "继续深化")
        await bus.publish_inbound(inbound)

        async def handler(message: InboundMessage):
            assert message.session_key == "web:chat-1"
            return {"content": "已完成", "payload": {"research_gaps": ["下一问"]}}

        task = asyncio.create_task(bus.serve(handler, once=True))
        outbound = await bus.consume_outbound()
        await task
        assert isinstance(outbound, OutboundMessage)
        assert outbound.channel == "web"
        assert outbound.reply_to == inbound.message_id
        assert list(outbound.payload["research_gaps"]) == ["下一问"]

    asyncio.run(scenario())


def test_message_bus_serve_honors_stop_event_when_idle() -> None:
    async def scenario() -> None:
        bus = MessageBus()
        stop_event = asyncio.Event()
        task = asyncio.create_task(bus.serve(lambda _message: {"content": "unused"}, stop_event=stop_event))
        await asyncio.sleep(0)
        stop_event.set()
        await asyncio.wait_for(task, timeout=1)
        assert not bus.closed

    asyncio.run(scenario())


def test_channel_boundary_redacts_sensitive_metadata_and_acknowledges_both_queues() -> None:
    async def scenario() -> None:
        bus = MessageBus()
        await bus.publish_inbound(
            InboundMessage(
                "web",
                "u",
                "c",
                "研究",
                metadata={
                    "authorization": "Bearer top-secret",
                    "raw_response": "hidden",
                    "visible": "ok",
                },
            )
        )
        inbound = await bus.consume_inbound()
        assert inbound.metadata["authorization"] == "<redacted>"
        assert inbound.metadata["raw_response"] == "<redacted>"
        assert inbound.metadata["visible"] == "ok"
        await bus.publish_outbound(
            OutboundMessage(
                "web",
                "c",
                payload={"provider_metadata": {"api_key": "hidden"}, "answer": "ok"},
            )
        )
        outbound = await bus.consume_outbound()
        assert outbound.payload["provider_metadata"] == "<redacted>"
        await bus.drain()

    asyncio.run(scenario())


def test_public_boundaries_sanitize_non_string_fallbacks_and_provider_text() -> None:
    class SecretObject:
        def __str__(self) -> str:
            return "<think>hidden trace</think> api_key=abc Bearer token-123"

    inbound = InboundMessage(
        "web",
        "u",
        "c",
        "研究",
        metadata={"error": SecretObject()},
    )
    encoded_inbound = str(inbound.to_plain())
    assert "hidden trace" not in encoded_inbound
    assert "token-123" not in encoded_inbound
    assert "api_key=abc" not in encoded_inbound

    result = ProviderResult(
        text="<reasoning>private</reasoning> Authorization: Bearer provider-token password=hunter2",
        tool_calls=(
            ProviderToolCall(
                "call-1",
                "probe",
                {"api_key": "secret", "visible": "<analysis>hidden</analysis> Bearer argument-token"},
            ),
        ),
        metadata={"error": SecretObject()},
    )
    encoded_result = str(result.to_plain())
    for secret in ("private", "provider-token", "hunter2", "token-123", "api_key=abc"):
        assert secret not in encoded_result
    assert result.to_plain()["tool_calls"][0]["arguments"]["api_key"] == "<redacted>"


def test_provider_result_drops_whitespace_tool_calls_before_rebuilding() -> None:
    result = ProviderResult(tool_calls=(
        ProviderToolCall(" ", "search", {}),
        ProviderToolCall("valid", " \t", {}),
        ProviderToolCall(" kept ", " search ", {"query": "public"}),
    ))
    assert [(call.call_id, call.name) for call in result.tool_calls] == [("kept", "search")]


def test_inbound_timestamp_is_normalized_to_utc_for_plain_projection() -> None:
    message = InboundMessage(
        "cli",
        "u",
        "c",
        "研究",
        timestamp=datetime(2026, 1, 1, 8, 0),
    )
    assert message.timestamp.tzinfo == timezone.utc
    assert message.to_plain()["timestamp"].endswith("+00:00")


def test_close_never_blocks_on_a_full_bounded_queue() -> None:
    async def scenario() -> None:
        bus = MessageBus(maxsize=1)
        await bus.publish_inbound(InboundMessage("cli", "u", "c", "a"))
        await bus.close()
        await bus.drain()
        with pytest.raises(Exception):
            await bus.publish_inbound(InboundMessage("cli", "u", "c", "b"))

    asyncio.run(scenario())


def test_telegram_gateway_uses_trusted_session_and_shared_core() -> None:
    adapter = TelegramGatewayAdapter(
        allowed_senders=["17"],
        allowed_chats=["42"],
    )
    observed: list[OutboundMessage] = []
    captured: dict = {}

    def execute(payload):
        captured.update(payload)
        return {
            "visible_summary": ["方向一", "方向二"],
            "runtime": {"tools": ["diverge"]},
        }

    result = asyncio.run(
        dispatch_gateway_payload(
            adapter,
            {
                "update_id": 9,
                "session_key": "attacker-controlled",
                "message": {
                    "message_id": 101,
                    "from": {"id": 17, "is_bot": False},
                    "chat": {"id": 42},
                    "text": "/diverge 扩大构型空间",
                },
            },
            session_key="run-1:session-1",
            execute=execute,
            host_payload={"session_id": "session-1", "branch_id": "main"},
            observer=observed.append,
        )
    )

    assert result["runtime"]["tools"] == ["diverge"]
    assert captured["channel"] == "telegram"
    assert captured["session_key"] == "run-1:session-1"
    assert captured["session_id"] == "session-1"
    assert observed[0].content == "方向一\n方向二"
    rendered = adapter.render(observed[0])
    assert rendered[0]["method"] == "sendMessage"
    assert rendered[0]["chat_id"] == "42"
    assert rendered[0]["reply_parameters"] == {"message_id": "101"}


def test_verified_gateway_resolves_session_after_signature_and_replay_checks() -> None:
    adapter = TelegramGatewayAdapter(allowed_senders=["17"], allowed_chats=["42"])
    payload = {
        "update_id": 9,
        "session_key": "payload-must-not-win",
        "message": {
            "message_id": 101,
            "from": {"id": 17, "is_bot": False},
            "chat": {"id": 42},
            "text": "继续深度发散",
        },
    }
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    policy = WebhookSignaturePolicy(secret="host-secret", tolerance_seconds=60)
    timestamp = "1000"
    nonce = "nonce-1"
    headers = {
        "X-Deep-Gateway-Timestamp": timestamp,
        "X-Deep-Gateway-Nonce": nonce,
        "X-Deep-Gateway-Signature": policy.sign(body, timestamp=timestamp, nonce=nonce),
    }
    cache = WebhookReplayCache()
    captured: dict = {}
    identities: list[GatewayIdentity] = []

    def resolver(identity: GatewayIdentity, _payload: dict) -> str:
        identities.append(identity)
        return "host-owned-session"

    def execute(request: dict) -> dict:
        captured.update(request)
        return {"visible_summary": ["ok"]}

    result = asyncio.run(
        dispatch_verified_gateway_payload(
            adapter,
            payload,
            body=body,
            headers=headers,
            signature_policy=policy,
            replay_cache=cache,
            session_resolver=resolver,
            execute=execute,
            host_payload={"session_id": "host-session"},
            now=1000,
        )
    )

    assert result == {"visible_summary": ["ok"]}
    assert identities == [
        GatewayIdentity(
            channel="telegram",
            sender_id="17",
            chat_id="42",
            message_id="telegram:101",
        )
    ]
    assert captured["session_key"] == "host-owned-session"
    assert captured["session_id"] == "host-session"

    with pytest.raises(ChannelPayloadRejected, match="already used"):
        asyncio.run(
            dispatch_verified_gateway_payload(
                adapter,
                payload,
                body=body,
                headers=headers,
                signature_policy=policy,
                replay_cache=cache,
                session_resolver=resolver,
                execute=execute,
                host_payload={},
                now=1001,
            )
        )


def test_verified_gateway_rejects_bad_signature_stale_timestamp_and_unmapped_identity() -> None:
    adapter = DiscordGatewayAdapter(allowed_senders=["7"], allowed_channels=["c1"])
    payload = {
        "id": "m1",
        "channel_id": "c1",
        "content": "研究",
        "author": {"id": "7", "bot": False},
    }
    body = json.dumps(payload, sort_keys=True)
    policy = WebhookSignaturePolicy(secret="host-secret", tolerance_seconds=60)
    good_headers = {
        "x-deep-gateway-timestamp": "1000",
        "x-deep-gateway-nonce": "nonce-2",
        "x-deep-gateway-signature": policy.sign(body, timestamp="1000", nonce="nonce-2"),
    }

    with pytest.raises(ChannelPayloadRejected, match="signature"):
        asyncio.run(
            dispatch_verified_gateway_payload(
                adapter,
                payload,
                body=body + "changed",
                headers=good_headers,
                signature_policy=policy,
                session_resolver=lambda _identity, _payload: "session",
                execute=lambda _request: {},
                host_payload={},
                now=1000,
            )
        )
    with pytest.raises(ChannelPayloadRejected, match="replay window"):
        asyncio.run(
            dispatch_verified_gateway_payload(
                adapter,
                payload,
                body=body,
                headers=good_headers,
                signature_policy=policy,
                session_resolver=lambda _identity, _payload: "session",
                execute=lambda _request: {},
                host_payload={},
                now=2000,
            )
        )
    with pytest.raises(ChannelPayloadRejected, match="not mapped"):
        asyncio.run(
            dispatch_verified_gateway_payload(
                adapter,
                payload,
                body=body,
                headers=good_headers,
                signature_policy=policy,
                session_resolver=lambda _identity, _payload: None,
                execute=lambda _request: {},
                host_payload={},
                now=1000,
            )
        )



def test_verified_channel_gateway_renders_delivery_bodies_without_owning_tokens() -> None:
    adapter = TelegramGatewayAdapter(allowed_senders=["17"], allowed_chats=["42"])
    payload = {
        "update_id": 10,
        "session_key": "payload-must-not-win",
        "message": {
            "message_id": 202,
            "from": {"id": 17, "is_bot": False},
            "chat": {"id": 42},
            "text": "/challenge 压力测试当前方向",
        },
    }
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    policy = WebhookSignaturePolicy(secret="host-secret", tolerance_seconds=60)
    headers = {
        "X-Deep-Gateway-Timestamp": "1000",
        "X-Deep-Gateway-Nonce": "nonce-object-gateway",
        "X-Deep-Gateway-Signature": policy.sign(
            body, timestamp="1000", nonce="nonce-object-gateway"
        ),
        "Authorization": "Bearer must-stay-outside",
    }
    captured: dict = {}

    def resolver(identity: GatewayIdentity, _payload: dict) -> str:
        assert identity.message_id == "telegram:202"
        return "server-owned-run-session"

    def host_payload(identity: GatewayIdentity, _payload: dict, session_key: str) -> dict:
        return {
            "session_id": "session-202",
            "branch_id": "main",
            "identity_message_id": identity.message_id,
            "trusted_session_key": session_key,
        }

    def execute(request: dict) -> dict:
        captured.update(request)
        return {
            "visible_summary": ["已转入对抗裁决", "保留开放缺口"],
            "provider_metadata": {"api_key": "must-stay-outside"},
        }

    gateway = VerifiedChannelGateway(
        adapter=adapter,
        signature_policy=policy,
        session_resolver=resolver,
        execute=execute,
    )

    dispatched = asyncio.run(
        gateway.dispatch(
            payload,
            body=body,
            headers=headers,
            host_payload=host_payload,
            now=1000,
        )
    )

    assert dispatched.identity == GatewayIdentity(
        channel="telegram",
        sender_id="17",
        chat_id="42",
        message_id="telegram:202",
    )
    assert dispatched.session_key == "server-owned-run-session"
    assert captured["session_key"] == "server-owned-run-session"
    assert captured["session_id"] == "session-202"
    assert captured["trusted_session_key"] == "server-owned-run-session"
    assert dispatched.outbound[0].content == "已转入对抗裁决\n保留开放缺口"
    assert dispatched.deliveries == (
        {
            "method": "sendMessage",
            "chat_id": "42",
            "text": "已转入对抗裁决\n保留开放缺口",
            "reply_parameters": {"message_id": "202"},
        },
    )
    plain = dispatched.to_plain()
    assert "must-stay-outside" not in json.dumps(plain, ensure_ascii=False)
    assert plain["identity"]["message_id"] == "telegram:202"
    assert plain["result"]["provider_metadata"] == "<redacted>"

    with pytest.raises(ChannelPayloadRejected, match="already used"):
        asyncio.run(
            gateway.dispatch(
                payload,
                body=body,
                headers=headers,
                host_payload={},
                now=1001,
            )
        )

def test_external_gateway_allowlists_and_bot_suppression_fail_closed() -> None:
    telegram = TelegramGatewayAdapter(allowed_senders=["17"])
    with pytest.raises(ChannelPayloadRejected, match="not allowed"):
        telegram.parse(
            {
                "message": {
                    "message_id": 1,
                    "from": {"id": 18},
                    "chat": {"id": 42},
                    "text": "研究",
                }
            },
            session_key="trusted",
        )


def test_verified_gateway_collapses_provider_retries_by_message_id() -> None:
    adapter = TelegramGatewayAdapter(allowed_senders=["17"], allowed_chats=["42"])
    policy = WebhookSignaturePolicy(secret="retry-secret", tolerance_seconds=60)
    payload = {
        "message": {
            "message_id": 303,
            "from": {"id": 17},
            "chat": {"id": 42},
            "text": "重复投递",
        }
    }
    body = json.dumps(payload, ensure_ascii=False).encode()
    calls = 0

    def execute(_request: dict) -> dict:
        nonlocal calls
        calls += 1
        return {"visible_summary": ["只执行一次"]}

    gateway = VerifiedChannelGateway(
        adapter=adapter,
        signature_policy=policy,
        session_resolver=lambda _identity, _payload: "run:session",
        execute=execute,
        delivery_cache=GatewayDeliveryCache(ttl_seconds=60),
    )

    def headers(nonce: str) -> dict[str, str]:
        timestamp = "1000"
        return {
            "X-Deep-Gateway-Timestamp": timestamp,
            "X-Deep-Gateway-Nonce": nonce,
            "X-Deep-Gateway-Signature": policy.sign(
                body, timestamp=timestamp, nonce=nonce
            ),
        }

    first = asyncio.run(
        gateway.dispatch(payload, body=body, headers=headers("nonce-a"), now=1000)
    )
    second = asyncio.run(
        gateway.dispatch(payload, body=body, headers=headers("nonce-b"), now=1001)
    )
    assert calls == 1
    assert second.to_plain() == first.to_plain()

def test_discord_gateway_suppresses_bot_messages() -> None:
    discord = DiscordGatewayAdapter(allowed_senders=["7"])
    with pytest.raises(ChannelPayloadRejected, match="bot/webhook"):
        discord.parse(
            {
                "id": "m1",
                "channel_id": "c1",
                "content": "研究",
                "author": {"id": "7", "bot": True},
            },
            session_key="trusted",
        )


def test_discord_gateway_normalizes_events_and_splits_delivery_bodies() -> None:
    adapter = DiscordGatewayAdapter(
        allowed_senders=["7"],
        allowed_channels=["c1"],
    )
    inbound = adapter.parse(
        {
            "id": "m1",
            "channel_id": "c1",
            "guild_id": "g1",
            "content": "继续对抗裁决",
            "author": {"id": "7", "bot": False},
        },
        session_key="run-1:session-1",
    )
    assert inbound.channel == "discord"
    assert inbound.session_key == "run-1:session-1"
    assert inbound.metadata["guild_id"] == "g1"

    outbound = OutboundMessage(
        channel="discord",
        chat_id="c1",
        content=("甲" * 1999) + "\n" + ("乙" * 10),
        reply_to="discord:m1",
    )
    bodies = adapter.render(outbound)
    assert len(bodies) == 2
    assert all(len(item["content"]) <= 2000 for item in bodies)
    assert bodies[0]["message_reference"] == {"message_id": "m1"}


def test_deep_runtime_message_entrypoint_publishes_one_channel_response() -> None:
    class Host:
        def _emit_deep_dialogue_progress(self, _row):
            return None

    async def scenario() -> None:
        bus = MessageBus()
        message = InboundMessage(
            "cli",
            "analyst",
            "chat",
            "/help",
            payload={"message_bus": "adapter-supplied replacement", "inbound_message": "spoof"},
        )
        result = await run_deep_research_message(Host(), bus, message)
        assert result["runtime"]["command"] == "help"
        response = await bus.consume_outbound()
        assert response.event_type == "deep_research.completed"
        assert response.reply_to == message.message_id

    asyncio.run(scenario())


def test_channel_hints_cannot_replace_or_introduce_host_governance(
    monkeypatch,
) -> None:
    captured: dict = {}

    async def capture(_host, request):
        captured.update(request)
        return {"ok": True}

    monkeypatch.setattr(runtime_loop, "_run_deep_research_turn", capture)
    trusted_identity = {"primary_equipment_identity": "当前源装备", "card_binding_id": "card-1"}
    trusted_memory = {"candidate_directions": [{"name": "当前方向"}]}
    workspace = object()
    provider_runtime = object()
    message = InboundMessage(
        "cli", "analyst", "chat", "继续研究",
        payload={
            "equipment_identity": {"primary_equipment_identity": "另一件装备"},
            "deep_parent_context": {"workspace_path": "/untrusted/workspace"},
            "working_memory": {"candidate_directions": [{"name": "伪造方向", "stable": True}]},
            "session_id": "another-session",
            "branch_id": "another-branch",
            "authoring_requested": True,
            "workspace_path": "/untrusted/workspace",
            "deep_workspace": "adapter replacement",
            "provider_runtime": "adapter replacement",
            "checkpoint_callback": "adapter replacement",
            "active_skill_ids": ["adapter-skill"],
            "deep_research_focus": {"lens": "任务窗口"},
        },
    )
    result = asyncio.run(
        run_deep_research_message(
            object(), MessageBus(), message,
            payload={
                "equipment_identity": trusted_identity,
                "working_memory": trusted_memory,
                "session_id": "current-session",
                "branch_id": "current-branch",
                "authoring_requested": False,
                "deep_workspace": workspace,
                "provider_runtime": provider_runtime,
                "active_skill_ids": ["host-skill"],
            },
        )
    )

    assert result == {"ok": True}
    assert captured["equipment_identity"] == trusted_identity
    assert captured["working_memory"] == trusted_memory
    assert captured["session_id"] == "current-session"
    assert captured["branch_id"] == "current-branch"
    assert captured["authoring_requested"] is False
    assert captured["deep_workspace"] is workspace
    assert captured["provider_runtime"] is provider_runtime
    assert captured["active_skill_ids"] == ["host-skill"]
    assert captured["deep_research_focus"] == {"lens": "任务窗口"}
    assert captured["question"] == message.content
    for field in ("workspace_path", "deep_parent_context", "checkpoint_callback"):
        assert field not in captured


def test_provider_runtime_normalizes_stream_and_snapshot() -> None:
    provider = ScriptedFakeProvider(
        [[
            ProviderStreamEvent.text_delta('{"finding":"ok"}'),
            ProviderStreamEvent.final(ProviderFinalTurn(finish_reason="completed")),
        ]]
    )

    async def scenario() -> None:
        runtime = ProviderRuntime(provider, provider_id="fake", model="fake-model")
        result = await runtime.complete(
            ProviderRequest((ModelMessage("user", "研究"),))
        )
        assert result.text == '{"finding":"ok"}'
        assert runtime.snapshot()["provider_id"] == "fake"
        assert runtime.capabilities().function_tools is True

    asyncio.run(scenario())


def test_provider_runtime_accepts_fenced_json_from_stream() -> None:
    provider = ScriptedFakeProvider(
        [[
            ProviderStreamEvent.final(
                ProviderFinalTurn(text='```json\n{"finding":"围栏"}\n```')
            )
        ]]
    )
    result = asyncio.run(
        ProviderRuntime(provider).complete_json(
            agent_id="probe",
            system="system",
            payload={},
            output_schema={"finding": "string"},
            max_output_tokens=256,
        )
    )
    assert result == {"finding": "围栏"}


def test_provider_snapshot_uses_allowlist_and_drops_nested_secrets() -> None:
    class Provider:
        model = "m"
        provider_type = "custom"

        def snapshot(self):
            return {
                "type": "custom",
                "base_url": "https://secret.example",
                "base_url_host": "secret.example",
                "api_key": "do-not-show",
                "provider_chain": [{"type": "backup", "authorization": "hidden"}],
                "hidden_reasoning": "do-not-show",
            }

        def capabilities(self):
            return type("Caps", (), {})()

        async def stream(self, *_args, **_kwargs):
            if False:
                yield None

    runtime = ProviderRuntime(Provider())
    snapshot = runtime.snapshot()
    assert "base_url" not in snapshot
    assert "api_key" not in snapshot
    assert "hidden_reasoning" not in snapshot
    assert snapshot["base_url_host"] == "secret.example"
    assert snapshot["provider_chain"] == [{"type": "backup"}]


def test_provider_runtime_supports_legacy_five_argument_host_callback() -> None:
    calls: list[str] = []

    def callback(agent_id, system, payload, schema, max_tokens):
        calls.append(agent_id)
        return {"finding": payload["question"], "schema": list(schema), "limit": max_tokens}

    async def scenario() -> None:
        runtime = ProviderRuntime(json_callback=callback)
        result = await runtime.complete_json(
            agent_id="probe",
            system="system",
            payload={"question": "问题"},
            output_schema={"finding": "string"},
            max_output_tokens=256,
        )
        assert result["finding"] == "问题"
        assert calls == ["probe"]

    asyncio.run(scenario())


def test_provider_runtime_normalizes_json_text_from_legacy_callback() -> None:
    def callback(*_args, **_kwargs):
        return '```json\n{"finding":"文本结果"}\n```'

    result = asyncio.run(
        ProviderRuntime(json_callback=callback).complete_json(
            agent_id="probe",
            system="system",
            payload={},
            output_schema={"finding": "string"},
            max_output_tokens=256,
        )
    )
    assert result == {"finding": "文本结果"}


@pytest.mark.parametrize("as_text", [False, True])
def test_structured_provider_outputs_are_safe_without_losing_long_content(as_text: bool) -> None:
    output = {
        "content": "完整正文" * 1200,
        "finding": "Bearer provider-token",
        "raw_response": "private wire body",
        "nested": {"model_response": "private model body", "visible": "ok"},
    }

    def callback(*_args, **_kwargs):
        return json.dumps(output, ensure_ascii=False) if as_text else output

    result = asyncio.run(
        ProviderRuntime(json_callback=callback).complete_json(
            agent_id="probe", system="system", payload={},
            output_schema={"content": "string"}, max_output_tokens=4200,
        )
    )
    assert result["content"] == output["content"]
    assert result["raw_response"] == "<redacted>"
    assert result["nested"] == {"model_response": "<redacted>", "visible": "ok"}
    assert "provider-token" not in str(result)
    assert output["raw_response"] == "private wire body"


def test_direct_provider_preserves_nested_schema_and_sanitizes_parsed_json() -> None:
    captured: dict = {}
    schema = {
        "directions": [{
            "name": "string",
            "details": {"assumption": "string", "effects": ["string"]},
        }],
    }

    class Provider:
        async def stream(self, _messages, _tools, options):
            captured.update(options)
            yield ProviderStreamEvent.final(ProviderFinalTurn(
                text='{"finding":"Bearer direct-secret","raw_output":"private","content":"ok"}'
            ))

    result = asyncio.run(
        ProviderRuntime(Provider()).complete_json(
            agent_id="probe", system="system", payload={},
            output_schema=schema, max_output_tokens=256,
        )
    )
    assert captured["output_schema"] == schema
    assert result["content"] == "ok"
    assert result["raw_output"] == "<redacted>"
    assert "direct-secret" not in str(result)
    assert "_provider_error" not in result


def test_direct_provider_routes_run_identity_to_fairness_without_model_metadata() -> None:
    captured: dict = {}

    class Provider:
        async def stream(self, messages, _tools, options):
            captured["messages"] = messages
            captured["options"] = dict(options)
            yield ProviderStreamEvent.final(ProviderFinalTurn(text='{"ok":true}'))

    result = asyncio.run(
        ProviderRuntime(Provider()).complete_json(
            agent_id="probe",
            system="system",
            payload={"run_id": "run-deep-1", "input": {"question": "问题"}},
            output_schema={"ok": "boolean"},
            max_output_tokens=256,
            phase="deep_contextual_dialogue_synthesis",
        )
    )

    assert result == {"ok": True}
    assert captured["options"]["_run_id"] == "run-deep-1"
    assert captured["options"]["_fairness_key"] == "run-deep-1"
    assert captured["options"]["_codex_call_priority"] == "critical"
    assert "run-deep-1" not in captured["messages"][1].content


def test_direct_provider_technology_lane_has_bounded_search_options() -> None:
    captured: dict = {}

    class Provider:
        async def stream(self, _messages, _tools, options):
            captured.update(options)
            yield ProviderStreamEvent.final(ProviderFinalTurn(text='{"ok":true}'))

    result = asyncio.run(
        ProviderRuntime(Provider()).complete_json(
            agent_id="deep_thinking_dialogue",
            system="system",
            payload={},
            output_schema={"ok": "boolean"},
            max_output_tokens=256,
            phase="deep_contextual_dialogue_s6_column_2",
        )
    )

    assert result == {"ok": True}
    assert captured["_disable_provider_timeout"] is False
    assert captured["_provider_timeout_seconds"] == 180
    assert captured["web_search"]["external_web_access"] is True
    assert captured["include_web_sources"] is True
    assert captured["require_web_search"] is False


def test_sync_callback_internal_type_error_is_not_retried() -> None:
    calls: list[str] = []

    def callback(*_args, **_kwargs):
        calls.append("called")
        raise TypeError("phase handler failed inside provider")

    with pytest.raises(TypeError, match="inside provider"):
        asyncio.run(ProviderRuntime(json_callback=callback).complete_json(
            agent_id="probe", system="system", payload={},
            output_schema={}, max_output_tokens=256,
        ))
    assert calls == ["called"]


def test_injected_provider_drives_conductor_tools_and_default_subagents() -> None:
    phases: list[str] = []
    host_calls: list[str] = []
    direction = {
        "name": "研究候选",
        "equipment_form": "概念构型",
        "operational_mechanism": "明确的概念作用关系",
        "winning_angle": "重构任务窗口",
        "stable": True,
    }

    class Host:
        async def _run_core_json(self, *_args, **_kwargs):
            host_calls.append("unexpected")
            raise AssertionError("injected provider must be authoritative")

        def _emit_deep_dialogue_progress(self, _row):
            return None

    async def callback(_agent, _system, payload, _schema, _tokens, *, phase):
        phases.append(phase)
        assert "provider_runtime" not in payload
        if phase == "deep_research_conduct":
            return {"tools": ["deepen"], "intent": "deepen"}
        if phase == "deep_runtime_subagent":
            return {"finding": "独立研究发现", "assumptions": [], "next_probe": "边界"}
        assert phase == "deep_contextual_dialogue_deepen"
        return {"visible_summary": ["本轮推进"], "concept_directions": [direction]}

    result = asyncio.run(runtime_loop._run_deep_research_turn(
        Host(), {
            "question": "继续比较研究方向",
            "working_memory": {"candidate_directions": [direction]},
            "provider_runtime": ProviderRuntime(json_callback=callback),
            "subagent_tasks": True,
        },
    ))
    assert host_calls == []
    assert phases.count("deep_runtime_subagent") == 2
    assert "deep_research_conduct" in phases
    assert "deep_contextual_dialogue_deepen" in phases
    assert result["visible_summary"] == ["本轮推进"]
    assert result["runtime"]["subagents"]["completed"] == 2


def test_provider_runtime_ignores_non_streaming_host_wrapper_when_callback_exists() -> None:
    class Wrapper:
        pass

    class Host:
        provider = Wrapper()

        async def _run_core_json(self, agent_id, system, payload, schema, max_tokens, **_kwargs):
            return {"finding": payload["question"], "agent_id": agent_id}

    runtime = ProviderRuntime.from_host(Host())
    assert runtime is not None

    result = asyncio.run(
        runtime.complete_json(
            agent_id="probe",
            system="system",
            payload={"question": "兼容"},
            output_schema={"finding": "string"},
            max_output_tokens=256,
        )
    )
    assert result["finding"] == "兼容"


def test_lightweight_subagent_runner_returns_mergeable_result() -> None:
    provider = ScriptedFakeProvider(
        [[
            ProviderStreamEvent.final(
                ProviderFinalTurn(text='{"finding":"反例","assumptions":["A"],"next_probe":"B"}')
            )
        ]]
    )

    async def scenario() -> None:
        runner = LightweightSubagentRunner(ProviderRuntime(provider), max_tasks=1)
        task = SubagentTask(
            task_id="probe",
            role="反制探针",
            prompt="寻找一个反例",
            merge_contract="返回发现与下一探针",
        )
        result = (await runner.run_many([task]))[0]
        assert result.status == "completed"
        assert result.finding == "反例"
        assert result.to_public()["assumptions"] == ["A"]

    asyncio.run(scenario())


@pytest.mark.parametrize("output", [
    {"_provider_error": "invalid_json", "_text": "private provider error"},
    {"assumptions": ["only metadata"]},
])
def test_subagent_rejects_outputs_without_a_mergeable_finding(output: dict) -> None:
    class Runtime:
        async def complete_json(self, **_kwargs):
            return output

        def snapshot(self):
            return {}

    task = SubagentTask("probe", "探针", "检查一个问题", "返回一条发现")
    result = asyncio.run(LightweightSubagentRunner(Runtime()).run(task))
    assert result.status == "invalid"
    assert result.finding is None
    assert "private provider error" not in str(result.to_public())


def test_default_divergence_subtasks_are_bounded_and_orthogonal() -> None:
    tasks = default_divergence_subtasks("新的作战约束")
    assert len(tasks) == 2
    assert {task.task_id for task in tasks} == {
        "configuration_probe",
        "countermeasure_probe",
    }


def test_subagent_context_cannot_override_server_owned_equipment_identity() -> None:
    payload = {
        "equipment_identity": {
            "primary_equipment_identity": "折脊穿隙攻击无人机",
            "card_binding_id": "card-7",
        },
        "deep_parent_context": {
            "source_equipment": {"name": "客户端伪造装备"},
        },
    }
    projection = _canonical_identity_projection(payload)
    assert projection["primary_equipment_identity"] == "折脊穿隙攻击无人机"
    assert projection["card_binding_id"] == "card-7"
    tasks = tasks_from_payload(
        [{
            "task_id": "probe",
            "role": "反制探针",
            "prompt": "找反例",
            "context": {
                "canonical_equipment_identity": {"name": "另一个装备"},
            },
        }],
        question="研究",
        context={"canonical_equipment_identity": projection},
    )
    assert tasks[0].context["canonical_equipment_identity"] == projection


def test_subagent_context_and_result_redact_provider_secrets() -> None:
    task = SubagentTask(
        task_id="probe",
        role="审计探针",
        prompt="检查边界",
        merge_contract="返回一条发现",
        context={"api_key": "top-secret", "visible": "ok"},
    )
    assert task.context["api_key"] == "<redacted>"
    assert task.context["visible"] == "ok"

    class Runtime:
        async def complete_json(self, **_kwargs):
            return {"finding": {"provider_response": "hidden", "answer": "ok"}}

        def snapshot(self):
            return {"provider_metadata": "hidden"}

    result = asyncio.run(LightweightSubagentRunner(Runtime()).run(task))
    public = result.to_public()
    assert public["finding"]["provider_response"] == "<redacted>"
    assert public["finding"]["answer"] == "ok"
    assert public["provider"]["provider_metadata"] == "<redacted>"
