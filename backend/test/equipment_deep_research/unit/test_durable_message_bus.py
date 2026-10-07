from __future__ import annotations

import asyncio
from pathlib import Path

from equipment_deep_research.deep_runtime.channel import (
    InboundMessage,
    MessageBus,
    OutboundMessage,
)
from equipment_deep_research.persistence.database import create_database_engine
from equipment_deep_research.persistence.repositories import SqlMessageBusStore


def _stores(path: Path, *, lease_seconds: float = 1.0) -> tuple[SqlMessageBusStore, SqlMessageBusStore]:
    url = f"sqlite:///{path}"
    return (
        SqlMessageBusStore(create_database_engine(url), lease_seconds=lease_seconds),
        SqlMessageBusStore(create_database_engine(url), lease_seconds=lease_seconds),
    )


def test_sql_message_bus_fences_competing_claims_and_wrong_ack(tmp_path: Path) -> None:
    first, second = _stores(tmp_path / "bus.db")
    delivery_id = first.publish_inbound(
        InboundMessage("web", "u", "c", "研究", metadata={"authorization": "Bearer hidden"})
    )

    owner = first.claim_inbound("worker-a")
    assert owner and owner["delivery_id"] == delivery_id
    assert owner["payload"]["metadata"]["authorization"] == "<redacted>"
    assert second.claim_inbound("worker-b") is None

    second.ack_inbound(delivery_id, "worker-b")
    assert second.claim_inbound("worker-b") is None
    first.ack_inbound(delivery_id, "worker-a")
    assert second.claim_inbound("worker-b") is None


def test_sql_message_bus_requeues_expired_lease(tmp_path: Path) -> None:
    first, second = _stores(tmp_path / "lease.db", lease_seconds=0.2)
    delivery_id = first.publish_inbound(InboundMessage("web", "u", "c", "继续"))
    assert first.claim_inbound("worker-a")["delivery_id"] == delivery_id
    assert second.claim_inbound("worker-b") is None

    import time

    time.sleep(0.25)
    recovered = second.claim_inbound("worker-b")
    assert recovered and recovered["delivery_id"] == delivery_id
    first.ack_inbound(delivery_id, "worker-a")
    assert second.claim_inbound("worker-b") is None
    second.ack_inbound(delivery_id, "worker-b")


def test_two_message_buses_exchange_inbound_and_outbound(tmp_path: Path) -> None:
    first_store, second_store = _stores(tmp_path / "exchange.db")

    async def scenario() -> None:
        producer = MessageBus(backend=first_store, consumer_id="producer")
        worker = MessageBus(backend=second_store, consumer_id="worker")
        await producer.publish_inbound(InboundMessage("web", "u", "c", "展开三个方向"))

        async def handle(message: InboundMessage):
            assert message.content == "展开三个方向"
            return OutboundMessage(
                channel=message.channel,
                chat_id=message.chat_id,
                content="方向一\n方向二\n方向三",
                correlation_id=message.message_id,
            )

        task = asyncio.create_task(worker.serve(handle, once=True))
        outbound = await asyncio.wait_for(producer.consume_outbound(), timeout=2)
        await task
        assert outbound.content.startswith("方向一")
        assert first_store.claim_inbound("audit") is None
        await producer.close()
        await worker.close()

    asyncio.run(scenario())


def test_failed_durable_handler_leaves_message_for_next_worker(tmp_path: Path) -> None:
    first_store, second_store = _stores(tmp_path / "retry.db", lease_seconds=0.2)

    async def scenario() -> None:
        failed = MessageBus(backend=first_store, consumer_id="failed")
        recovered = MessageBus(backend=second_store, consumer_id="recovered")
        await failed.publish_inbound(InboundMessage("web", "u", "c", "失败后恢复"))

        async def fail(_message: InboundMessage):
            raise RuntimeError("temporary handler error")

        try:
            await failed.serve(fail, once=True)
        except RuntimeError as exc:
            assert str(exc) == "temporary handler error"
        else:
            raise AssertionError("failed handler must propagate")

        await asyncio.sleep(0.25)
        task = asyncio.create_task(
            recovered.serve(lambda _message: {"content": "recovered"}, once=True)
        )
        outbound = await asyncio.wait_for(recovered.consume_outbound(), timeout=2)
        await task
        assert outbound.content == "recovered"
        await failed.close()
        await recovered.close()

    asyncio.run(scenario())
