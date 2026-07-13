"""Tests for `saena_domain.bus.publisher` (`InMemoryPublisher`, key/topic
helpers, `RedpandaConfig`/`RedpandaPublisher` lifecycle + error-wrapping —
using an injected FAKE `AIOKafkaProducer`-shaped stub, no real broker; the
real-broker round-trip lives in `tests/integration/bus`)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from bus_factories import make_aggregate_envelope, make_system_envelope, make_tenant_envelope
from saena_domain.bus.errors import PublishFailedError
from saena_domain.bus.publisher import (
    InMemoryPublisher,
    RedpandaConfig,
    RedpandaPublisher,
    dlq_topic_for,
    partition_key_for,
)


def test_in_memory_publisher_records_topic_and_envelope() -> None:
    publisher = InMemoryPublisher()
    envelope = make_tenant_envelope()

    asyncio.run(publisher.publish("patch.unit.completed.v1", envelope))

    assert publisher.published == (("patch.unit.completed.v1", envelope),)


def test_in_memory_publisher_records_multiple_calls_in_order() -> None:
    publisher = InMemoryPublisher()
    first = make_tenant_envelope(idempotency_key="acme-co:run-1:patch-unit-1")
    second = make_tenant_envelope(idempotency_key="acme-co:run-1:patch-unit-2")

    async def scenario() -> None:
        await publisher.publish("patch.unit.completed.v1", first)
        await publisher.publish("patch.unit.completed.v1", second)

    asyncio.run(scenario())

    assert [envelope["idempotency_key"] for _, envelope in publisher.published] == [
        first["idempotency_key"],
        second["idempotency_key"],
    ]


def test_in_memory_publisher_return_value_is_defensive_copy() -> None:
    """Mutating the caller's envelope after publish must not corrupt the
    recorded copy."""
    publisher = InMemoryPublisher()
    envelope = make_tenant_envelope()

    asyncio.run(publisher.publish("patch.unit.completed.v1", envelope))
    envelope["payload"]["patch_unit_id"] = "TAMPERED"

    _, recorded = publisher.published[0]
    assert recorded["payload"]["patch_unit_id"] == "w2-18-outbox-bus"


def test_dlq_topic_for_appends_dlq_suffix() -> None:
    assert dlq_topic_for("patch.unit.completed.v1") == "patch.unit.completed.v1.dlq"


def test_partition_key_prefers_idempotency_key() -> None:
    envelope = make_tenant_envelope()
    key = partition_key_for(envelope)
    assert key == envelope["idempotency_key"].encode("utf-8")


def test_partition_key_falls_back_to_tenant_id_when_no_idempotency_key() -> None:
    envelope = make_tenant_envelope()
    del envelope["idempotency_key"]
    key = partition_key_for(envelope)
    assert key == envelope["tenant_id"].encode("utf-8")


def test_partition_key_none_when_neither_field_present() -> None:
    envelope = make_system_envelope()
    del envelope["idempotency_key"]
    assert partition_key_for(envelope) is None


def test_partition_key_for_aggregate_envelope_uses_idempotency_key() -> None:
    """Aggregate envelopes structurally carry no tenant_id at all —
    idempotency_key is the only available key, not merely a fallback."""
    envelope = make_aggregate_envelope()
    key = partition_key_for(envelope)
    assert key == envelope["idempotency_key"].encode("utf-8")
    assert "tenant_id" not in envelope


# --- RedpandaConfig.producer_kwargs --------------------------------------------------


def test_producer_kwargs_minimal_config_omits_optional_fields() -> None:
    config = RedpandaConfig(bootstrap_servers="localhost:9092")
    kwargs = config.producer_kwargs()
    assert kwargs == {"bootstrap_servers": "localhost:9092", "security_protocol": "PLAINTEXT"}


def test_producer_kwargs_includes_every_optional_field_when_set() -> None:
    config = RedpandaConfig(
        bootstrap_servers=["broker-1:9092", "broker-2:9092"],
        client_id="saena-outbox-drainer",
        security_protocol="SASL_SSL",
        sasl_mechanism="PLAIN",
        sasl_plain_username="svc-outbox",
        sasl_plain_password="resolved-from-secret-store",
        extra_producer_kwargs={"acks": "all"},
    )
    kwargs = config.producer_kwargs()
    assert kwargs == {
        "bootstrap_servers": ["broker-1:9092", "broker-2:9092"],
        "security_protocol": "SASL_SSL",
        "acks": "all",
        "client_id": "saena-outbox-drainer",
        "sasl_mechanism": "PLAIN",
        "sasl_plain_username": "svc-outbox",
        "sasl_plain_password": "resolved-from-secret-store",
    }


# --- RedpandaPublisher lifecycle + error wrapping (fake producer, no broker) ---------


class _FakeAIOKafkaProducer:
    """Minimal stand-in for `aiokafka.AIOKafkaProducer`'s async surface this
    module actually calls (`start`/`stop`/`send_and_wait`)."""

    def __init__(self, *, fail_with: Exception | None = None) -> None:
        self.started = False
        self.stopped = False
        self.sent: list[tuple[str, Any, bytes | None]] = []
        self._fail_with = fail_with

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send_and_wait(self, topic: str, *, value: Any, key: bytes | None = None) -> None:
        if self._fail_with is not None:
            raise self._fail_with
        self.sent.append((topic, value, key))


def test_redpanda_publisher_start_is_idempotent() -> None:
    fake = _FakeAIOKafkaProducer()
    config = RedpandaConfig(bootstrap_servers="localhost:9092")
    publisher = RedpandaPublisher(config, producer=fake)

    async def scenario() -> None:
        await publisher.start()
        await publisher.start()  # second call is a no-op early return

    asyncio.run(scenario())

    assert fake.started is True


def test_redpanda_publisher_stop_before_start_is_a_no_op() -> None:
    fake = _FakeAIOKafkaProducer()
    config = RedpandaConfig(bootstrap_servers="localhost:9092")
    publisher = RedpandaPublisher(config, producer=fake)

    asyncio.run(publisher.stop())

    assert fake.stopped is False


def test_redpanda_publisher_publish_before_start_raises_publish_failed() -> None:
    fake = _FakeAIOKafkaProducer()
    config = RedpandaConfig(bootstrap_servers="localhost:9092")
    publisher = RedpandaPublisher(config, producer=fake)
    envelope = make_tenant_envelope()

    with pytest.raises(PublishFailedError):
        asyncio.run(publisher.publish("patch.unit.completed.v1", envelope))


def test_redpanda_publisher_wraps_transport_failure_as_publish_failed() -> None:
    fake = _FakeAIOKafkaProducer(fail_with=TimeoutError("simulated broker timeout"))
    config = RedpandaConfig(bootstrap_servers="localhost:9092")
    publisher = RedpandaPublisher(config, producer=fake)
    envelope = make_tenant_envelope()

    async def scenario() -> None:
        await publisher.start()
        await publisher.publish("patch.unit.completed.v1", envelope)

    with pytest.raises(PublishFailedError):
        asyncio.run(scenario())


def test_redpanda_publisher_async_context_manager_starts_and_stops() -> None:
    fake = _FakeAIOKafkaProducer()
    config = RedpandaConfig(bootstrap_servers="localhost:9092")

    async def scenario() -> None:
        async with RedpandaPublisher(config, producer=fake) as publisher:
            assert fake.started is True
            await publisher.publish("patch.unit.completed.v1", make_tenant_envelope())
        assert fake.stopped is True

    asyncio.run(scenario())
    assert len(fake.sent) == 1
