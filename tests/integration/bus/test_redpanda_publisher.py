"""Integration tests: `RedpandaPublisher` against a real Redpanda container.

Spec basis: ADR-0004 (Redpanda = data pool component), ADR-0013 (envelope
serialization round-trip), ADR-0015 (DLQ naming `<topic>.dlq`). Real
produce->consume round-trip, key partitioning, and DLQ topic delivery — every
test here talks to an actual `redpandadata/redpanda` container (see
`conftest.py`'s `redpanda_bootstrap_servers` fixture), no mocking of the
transport layer.

Event-loop-per-test discipline: same `asyncio.run(scenario())` pattern as
`tests/integration/persistence_postgres` (no pytest-asyncio plugin
installed in this workspace).
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

import pytest
from aiokafka import AIOKafkaConsumer

_UNIT_TEST_FACTORIES_DIR = Path(__file__).resolve().parents[2] / "unit" / "domain_bus"
if str(_UNIT_TEST_FACTORIES_DIR) not in sys.path:
    sys.path.insert(0, str(_UNIT_TEST_FACTORIES_DIR))

from bus_factories import make_aggregate_envelope, make_tenant_envelope  # noqa: E402
from saena_domain.bus.publisher import (  # noqa: E402
    RedpandaConfig,
    RedpandaPublisher,
    dlq_topic_for,
)


def _unique_topic(base: str) -> str:
    """Every test gets its own topic name (Redpanda `auto_create_topics`
    creates it on first produce) so tests never interfere via shared state."""
    return f"{base}.{uuid.uuid4().hex[:8]}"


async def _consume_one(bootstrap_servers: str, topic: str, timeout: float = 20.0) -> dict:
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=bootstrap_servers,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        group_id=f"test-{uuid.uuid4().hex[:8]}",
    )
    await consumer.start()
    try:
        async for msg in consumer:
            return json.loads(msg.value.decode("utf-8"))
        raise AssertionError("consumer stream ended with no message")
    finally:
        await asyncio.wait_for(consumer.stop(), timeout=timeout)


@pytest.mark.integration
def test_produce_consume_round_trip_preserves_envelope(redpanda_bootstrap_servers: str) -> None:
    # `event_type` must stay a real AsyncAPI catalog value for
    # `EnvelopeFactory` to build a valid envelope; the topic PUBLISHED to is
    # independently unique per-test (topic selection at the transport layer
    # does not have to equal `event_type` for this specific round-trip
    # probe — only `OutboxDrainer` enforces that ADR-0013 1:1 rule).
    topic = _unique_topic("patch.unit.completed.v1")
    envelope = make_tenant_envelope()

    async def scenario() -> dict:
        config = RedpandaConfig(bootstrap_servers=redpanda_bootstrap_servers)
        async with RedpandaPublisher(config) as publisher:
            await publisher.publish(topic, envelope)
        return await _consume_one(redpanda_bootstrap_servers, topic)

    received = asyncio.run(scenario())

    assert received == envelope
    assert received["event_id"] == envelope["event_id"]
    assert received["idempotency_key"] == envelope["idempotency_key"]


@pytest.mark.integration
def test_aggregate_envelope_survives_serialization(redpanda_bootstrap_servers: str) -> None:
    topic = _unique_topic("strategy.card.eligible.v1")
    envelope = make_aggregate_envelope()

    async def scenario() -> dict:
        config = RedpandaConfig(bootstrap_servers=redpanda_bootstrap_servers)
        async with RedpandaPublisher(config) as publisher:
            await publisher.publish(topic, envelope)
        return await _consume_one(redpanda_bootstrap_servers, topic)

    received = asyncio.run(scenario())

    assert received == envelope
    assert "tenant_id" not in received
    assert received["context_type"] == "aggregate"


@pytest.mark.integration
def test_key_partitioning_same_idempotency_key_same_partition(
    redpanda_bootstrap_servers: str,
) -> None:
    """Two envelopes sharing the SAME `idempotency_key` must land on the
    SAME partition (deterministic hashed-key partitioning, aiokafka default
    partitioner) — proves `partition_key_for`'s key is actually threaded
    through to the producer, not silently dropped."""
    topic = _unique_topic("patch.unit.completed.v1")
    shared_key = "acme-co:run-shared:same-partition-probe"
    envelope_one = make_tenant_envelope(idempotency_key=shared_key)
    envelope_two = make_tenant_envelope(
        idempotency_key=shared_key,
        payload={"patch_unit_id": "second-envelope", "worktree_commit": "abcdef1"},
    )

    async def scenario() -> tuple[int, int]:
        config = RedpandaConfig(bootstrap_servers=redpanda_bootstrap_servers)
        partitions: list[int] = []
        async with RedpandaPublisher(config) as publisher:
            for envelope in (envelope_one, envelope_two):
                key = envelope["idempotency_key"].encode("utf-8")
                record_metadata = await publisher._producer.send_and_wait(  # noqa: SLF001
                    topic, value=envelope, key=key
                )
                partitions.append(record_metadata.partition)
        return partitions[0], partitions[1]

    partition_one, partition_two = asyncio.run(scenario())

    assert partition_one == partition_two


@pytest.mark.integration
def test_dlq_topic_receives_poison_message(redpanda_bootstrap_servers: str) -> None:
    """A "poison" envelope published to `<topic>.dlq` (ADR-0015 naming) is
    delivered and consumable exactly like any other topic — proves the DLQ
    is a real, working topic, not a naming convention this module merely
    documents."""
    main_topic = _unique_topic("patch.unit.completed.v1")
    dlq_topic = dlq_topic_for(main_topic)
    poison_envelope = {"not": "a valid envelope", "_dlq_reason": {"error_code": "saena.bus.test"}}

    async def scenario() -> dict:
        config = RedpandaConfig(bootstrap_servers=redpanda_bootstrap_servers)
        async with RedpandaPublisher(config) as publisher:
            await publisher.publish(dlq_topic, poison_envelope)
        return await _consume_one(redpanda_bootstrap_servers, dlq_topic)

    received = asyncio.run(scenario())

    assert received == poison_envelope
    assert dlq_topic == f"{main_topic}.dlq"
