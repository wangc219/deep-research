from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from equipment_deep_research.deep_runtime.gateways import (
    ChannelPayloadRejected,
    GatewayDeliveryCache,
    TelegramGatewayAdapter,
    VerifiedChannelGateway,
    WebhookSignaturePolicy,
)
from equipment_deep_research.persistence.database import create_database_engine
from equipment_deep_research.persistence.repositories import SqlGatewayDeliveryStore


def _gateway(execute):
    return VerifiedChannelGateway(
        adapter=TelegramGatewayAdapter(allowed_senders=["17", "18"]),
        signature_policy=WebhookSignaturePolicy(secret="test-only"),
        session_resolver=lambda identity, _: f"session:{identity.chat_id}",
        execute=execute,
    )


async def _send(gateway, nonce, *, chat=42, sender=17, content="hello", **kwargs):
    payload = {"message": {
        "message_id": 303, "from": {"id": sender},
        "chat": {"id": chat}, "text": content,
    }}
    body = json.dumps(payload).encode()
    return await gateway.dispatch(payload, body=body, now=1000, headers={
        "x-deep-gateway-timestamp": "1000",
        "x-deep-gateway-nonce": nonce,
        "x-deep-gateway-signature": gateway.signature_policy.sign(
            body, timestamp="1000", nonce=nonce
        ),
    }, **kwargs)


def test_concurrent_retries_and_disconnect_share_one_execution():
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []

        async def execute(payload):
            calls.append(payload["session_key"])
            entered.set()
            await release.wait()
            return {"visible_summary": ["done"]}

        gateway = _gateway(execute)
        first = asyncio.create_task(_send(gateway, "first"))
        await asyncio.wait_for(entered.wait(), 1)
        # A disconnected HTTP caller must not relinquish the live turn.
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        duplicates = [asyncio.create_task(_send(gateway, f"retry-{i}")) for i in range(12)]
        await asyncio.sleep(0)
        release.set()
        results = await asyncio.wait_for(asyncio.gather(*duplicates), 2)
        assert calls == ["session:42"]
        assert all(item is results[0] for item in results)
        await asyncio.sleep(0)
        assert not gateway._dispatch_tasks

    asyncio.run(scenario())


def test_cache_isolation_for_chat_sender_and_resolved_session():
    calls = []

    def execute(payload):
        calls.append((payload["chat_id"], payload["sender_id"], payload["session_key"]))
        return {"visible_summary": [payload["session_key"]]}

    gateway = _gateway(execute)
    first = asyncio.run(_send(gateway, "one"))
    other_chat = asyncio.run(_send(gateway, "two", chat=43))
    other_sender = asyncio.run(_send(gateway, "three", sender=18))
    gateway.session_resolver = lambda _identity, _payload: "replacement-session"
    other_session = asyncio.run(_send(gateway, "four"))
    assert len(calls) == 4
    assert all(item is not first for item in (other_chat, other_sender, other_session))
    assert other_chat.deliveries[0]["chat_id"] == "43"
    assert other_session.session_key == "replacement-session"


def test_conflicting_content_is_rejected_without_reusing_old_result():
    calls = []
    gateway = _gateway(lambda payload: calls.append(payload) or {"visible_summary": ["done"]})
    asyncio.run(_send(gateway, "one"))
    with pytest.raises(ChannelPayloadRejected, match="conflicting content"):
        asyncio.run(_send(gateway, "two", content="changed"))
    assert len(calls) == 1


def test_execution_failure_and_host_validation_release_claim():
    calls = []

    def execute(payload):
        calls.append(payload)
        if len(calls) == 1:
            raise RuntimeError("transient")
        return {"visible_summary": ["recovered"]}

    gateway = _gateway(execute)
    with pytest.raises(ChannelPayloadRejected, match="host payload"):
        asyncio.run(_send(gateway, "invalid", host_payload=lambda *_: "invalid"))
    with pytest.raises(RuntimeError, match="transient"):
        asyncio.run(_send(gateway, "failed"))
    result = asyncio.run(_send(gateway, "recovered"))
    assert result.result["visible_summary"] == ["recovered"]
    assert len(calls) == 2


def test_cache_claims_are_atomic_across_threads_and_do_not_evict_live_work():
    cache = GatewayDeliveryCache(max_entries=1, ttl_seconds=10)
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda _: cache.claim("message", now=0), range(32)))
    assert sum(owner for owner, _ in claims) == 1
    entry = claims[0][1]
    assert all(item is entry for _, item in claims)
    with pytest.raises(ChannelPayloadRejected, match="busy"):
        cache.claim("another", now=100)
    cache.complete("message", entry, "sentinel", now=100)
    assert cache.claim("message", now=109)[0] is False
    assert cache.claim("message", now=111)[0] is True


def test_duplicate_waiter_cancellation_does_not_cancel_shared_completion():
    async def scenario():
        cache = GatewayDeliveryCache()
        _, entry = cache.claim("message")
        waiter = asyncio.create_task(cache.wait(entry))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        cache.complete("message", entry, "sentinel")
        assert await cache.wait(entry) == "sentinel"

    asyncio.run(scenario())


def test_signed_body_cannot_authorize_a_different_payload():
    gateway = _gateway(lambda _: pytest.fail("unsigned payload must not execute"))
    body = b'{}'
    headers = {
        "x-deep-gateway-timestamp": "1000",
        "x-deep-gateway-nonce": "signed-body",
        "x-deep-gateway-signature": gateway.signature_policy.sign(
            body, timestamp="1000", nonce="signed-body"
        ),
    }
    with pytest.raises(ChannelPayloadRejected, match="does not match signed body"):
        asyncio.run(gateway.dispatch({"message": "unsigned"}, body=body, headers=headers, now=1000))


@pytest.mark.parametrize("timestamp", ["nan", "inf", "-inf"])
def test_nonfinite_timestamp_cannot_bypass_expiration(timestamp):
    policy = WebhookSignaturePolicy(secret="test-only")
    headers = {
        "x-deep-gateway-timestamp": timestamp,
        "x-deep-gateway-nonce": "timestamp",
        "x-deep-gateway-signature": policy.sign(b'{}', timestamp=timestamp, nonce="timestamp"),
    }
    with pytest.raises(ChannelPayloadRejected, match="timestamp is invalid"):
        policy.verify(b'{}', headers, now=1000)


def test_sql_gateway_delivery_store_replays_across_cache_instances(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'gateway-deliveries.db'}"
    first_store = SqlGatewayDeliveryStore(create_database_engine(database_url))
    second_store = SqlGatewayDeliveryStore(create_database_engine(database_url))
    calls = []
    entered, release = asyncio.Event(), asyncio.Event()

    async def execute(payload):
        calls.append(payload["inbound_message"].message_id)
        entered.set()
        await release.wait()
        return {"visible_summary": ["durable replay"]}

    def gateway(store):
        return VerifiedChannelGateway(
            adapter=TelegramGatewayAdapter(allowed_senders=["17"], allowed_chats=["42"]),
            signature_policy=WebhookSignaturePolicy(secret="durable-test"),
            session_resolver=lambda _identity, _payload: "session:42",
            execute=execute,
            delivery_cache=GatewayDeliveryCache(store=store, ttl_seconds=60),
        )

    first = gateway(first_store)
    second = gateway(second_store)

    async def scenario():
        payload = {"message": {
            "message_id": 909,
            "from": {"id": 17},
            "chat": {"id": 42},
            "text": "durable",
        }}
        body = json.dumps(payload).encode()

        def headers(nonce):
            return {
                "x-deep-gateway-timestamp": "1000",
                "x-deep-gateway-nonce": nonce,
                "x-deep-gateway-signature": first.signature_policy.sign(
                    body, timestamp="1000", nonce=nonce
                ),
            }

        owner = asyncio.create_task(first.dispatch(payload, body=body, headers=headers("owner"), now=1000))
        await asyncio.wait_for(entered.wait(), 1)
        replay = asyncio.create_task(second.dispatch(payload, body=body, headers=headers("replay"), now=1000))
        await asyncio.sleep(0)
        release.set()
        owner_result, replay_result = await asyncio.wait_for(
            asyncio.gather(owner, replay), 3
        )
        assert owner_result.to_plain() == replay_result.to_plain()
        assert len(calls) == 1

        # A fresh cache/process can replay the completed durable response.
        third = gateway(SqlGatewayDeliveryStore(create_database_engine(database_url)))
        restored = await third.dispatch(
            payload, body=body, headers=headers("fresh-process"), now=1000
        )
        assert restored.to_plain() == owner_result.to_plain()
        assert len(calls) == 1

    asyncio.run(scenario())


def test_sql_gateway_delivery_store_rejects_conflicting_fingerprint(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'gateway-conflict.db'}"
    store = SqlGatewayDeliveryStore(create_database_engine(database_url))
    store.claim("delivery", fingerprint="one", ttl_seconds=60)
    with pytest.raises(ValueError, match="conflicting content"):
        store.claim("delivery", fingerprint="two", ttl_seconds=60)


def test_sql_gateway_delivery_store_fences_stale_owner_after_lease_reclaim(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'gateway-fence.db'}"
    first = SqlGatewayDeliveryStore(create_database_engine(database_url))
    second = SqlGatewayDeliveryStore(create_database_engine(database_url))
    old = first.claim("delivery", fingerprint="same", ttl_seconds=60)
    with first.engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE gateway_deliveries SET expires_at = '2000-01-01T00:00:00+00:00' "
            "WHERE delivery_key = 'delivery'"
        )
    reclaimed = second.claim("delivery", fingerprint="same", ttl_seconds=60)
    assert reclaimed["owner_token"] != old["owner_token"]
    first.complete(
        "delivery",
        fingerprint="same",
        owner_token=old["owner_token"],
        response={"stale": True},
        ttl_seconds=60,
    )
    assert second.get("delivery", fingerprint="same")["status"] == "processing"
