"""Step 10 — event bus publish, against a REAL `redpandadata/redpanda`
testcontainer (`tests/integration/bus/conftest.py`'s own
`redpanda_bootstrap_servers` fixture pattern, duplicated as this
directory's own fixture per that package's own precedent of NOT sharing
fixtures cross-directory — see this module's own `conftest.py` docstring).

Publishes the REAL envelopes this suite's four job kinds actually produce
across the synthetic-tenant run (`repo.intaken.v1`, `plan.contract.
approved.v1`, `patch.unit.completed.v1`, `quality.gate.passed.v1` /
`quality.gate.failed.v1`) via `EnvelopeFactory`/each job kind's own payload
builder — never a hand-rolled envelope shape — and consumes every one back,
asserting byte-for-byte round trip equality (`saena_domain.bus.publisher.
RedpandaPublisher`, same adapter `tests/integration/bus/
test_redpanda_publisher.py` proves against the transport layer alone).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator

import pytest
from aiokafka import AIOKafkaConsumer
from saena_domain.bus.publisher import RedpandaConfig, RedpandaPublisher
from saena_domain.events import EnvelopeFactory
from saena_domain.execution import (
    build_patch_unit_completed_payload,
    build_quality_gate_failed_payload,
    build_quality_gate_passed_payload,
    build_repo_intaken_payload,
)
from saena_domain.execution.job_error import JobError
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

pytestmark = pytest.mark.integration

TENANT_1 = "e2e-tenant-one"
RUN_ID = "run-e2e-0001"
PATCH_UNIT_ID = "PU-01"
BASE_COMMIT = "a" * 40


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def redpanda_bootstrap_servers() -> Iterator[str]:
    kafka_port = _free_port()
    container = DockerContainer("redpandadata/redpanda:latest")
    container.with_bind_ports(9092, kafka_port)
    container.with_command(
        "redpanda start --smp 1 --memory 512M --overprovisioned --node-id 0 "
        "--check=false --kafka-addr PLAINTEXT://0.0.0.0:9092 "
        f"--advertise-kafka-addr PLAINTEXT://127.0.0.1:{kafka_port} "
        "--pandaproxy-addr 0.0.0.0:8082 --schema-registry-addr 0.0.0.0:8081"
    )
    container.start()
    try:
        wait_for_logs(container, "Successfully started Redpanda!", timeout=60)
        yield f"127.0.0.1:{kafka_port}"
    finally:
        import contextlib

        with contextlib.suppress(Exception):
            container.stop()


def _unique_topic(base: str) -> str:
    return f"{base}.{uuid.uuid4().hex[:8]}"


async def _consume_one(bootstrap_servers: str, topic: str, timeout: float = 20.0) -> dict:
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=bootstrap_servers,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        group_id=f"execution-e2e-{uuid.uuid4().hex[:8]}",
    )
    await consumer.start()
    try:
        async for msg in consumer:
            return json.loads(msg.value.decode("utf-8"))
        raise AssertionError("consumer stream ended with no message")
    finally:
        await asyncio.wait_for(consumer.stop(), timeout=timeout)


def _run_execution_run_envelopes() -> list[dict]:
    """The REAL envelope for every event this suite's job kinds emit across
    one synthetic-tenant run — built through the SAME `EnvelopeFactory` +
    per-job-kind payload builders `tests/e2e/execution/
    test_synthetic_tenant_execution_e2e.py` exercises the payload SHAPES of
    (that suite proves the payload builders; this one proves the transport)."""
    repo_intaken_payload = build_repo_intaken_payload(
        repo_commit=BASE_COMMIT,
        content_hash="sha256:" + ("b" * 64),
        snapshot_uri=f"git://source-host.example/{TENANT_1}/synthetic-repo",
    )
    patch_unit_payload = build_patch_unit_completed_payload(
        patch_unit_id=PATCH_UNIT_ID,
        worktree_commit="c" * 40,
        manifest_uri=f"manifest://{TENANT_1}/{PATCH_UNIT_ID}/{'c' * 40}",
        changed_files=["apps/web/docs/new-page.md"],
        quality_gate_ids=["build", "tests"],
    )
    quality_passed_payload = build_quality_gate_passed_payload(
        patch_unit_id=PATCH_UNIT_ID, gate_id="build", report_uri="artifact://reports/PU-01"
    )
    quality_failed_payload = build_quality_gate_failed_payload(
        patch_unit_id=PATCH_UNIT_ID,
        gate_id="secret_scan",
        failures=[
            JobError(
                error_code="saena.internal.secret_detected",
                summary="secret scan finding (redacted)",
                retryable=False,
            )
        ],
    )

    envelopes = [
        EnvelopeFactory.build_tenant_envelope(
            producer="repository-intake-service",
            event_type="repo.intaken.v1",
            tenant_id=TENANT_1,
            run_id=RUN_ID,
            idempotency_key=f"{TENANT_1}:{RUN_ID}:intake",
            payload=repo_intaken_payload,
        ),
        EnvelopeFactory.build_tenant_envelope(
            producer="plan-contract-service",
            event_type="plan.contract.approved.v1",
            tenant_id=TENANT_1,
            run_id=RUN_ID,
            idempotency_key=f"{TENANT_1}:{RUN_ID}:plan-approved",
            payload={"contract_hash": "sha256:" + ("d" * 64), "decision": "approved"},
        ),
        EnvelopeFactory.build_tenant_envelope(
            producer="agent-runner-service",
            event_type="patch.unit.completed.v1",
            tenant_id=TENANT_1,
            run_id=RUN_ID,
            idempotency_key=f"{TENANT_1}:{RUN_ID}:{PATCH_UNIT_ID}",
            payload=patch_unit_payload,
        ),
        EnvelopeFactory.build_tenant_envelope(
            producer="quality-eval-service",
            event_type="quality.gate.passed.v1",
            tenant_id=TENANT_1,
            run_id=RUN_ID,
            idempotency_key=f"{TENANT_1}:{RUN_ID}:{PATCH_UNIT_ID}:build",
            payload=quality_passed_payload,
        ),
        EnvelopeFactory.build_tenant_envelope(
            producer="quality-eval-service",
            event_type="quality.gate.failed.v1",
            tenant_id=TENANT_1,
            run_id=RUN_ID,
            idempotency_key=f"{TENANT_1}:{RUN_ID}:{PATCH_UNIT_ID}:secret_scan",
            payload=quality_failed_payload,
        ),
    ]
    return envelopes


def test_every_run_event_envelope_round_trips_through_real_redpanda(
    redpanda_bootstrap_servers: str,
) -> None:
    envelopes = _run_execution_run_envelopes()
    topics = [_unique_topic(envelope["event_type"]) for envelope in envelopes]

    async def scenario() -> list[dict]:
        config = RedpandaConfig(bootstrap_servers=redpanda_bootstrap_servers)
        async with RedpandaPublisher(config) as publisher:
            for topic, envelope in zip(topics, envelopes, strict=True):
                await publisher.publish(topic, envelope)
        return [await _consume_one(redpanda_bootstrap_servers, topic) for topic in topics]

    received = asyncio.run(scenario())

    assert len(received) == len(envelopes)
    for sent, got in zip(envelopes, received, strict=True):
        assert got == sent
        assert got["event_id"] == sent["event_id"]
        assert got["idempotency_key"] == sent["idempotency_key"]
        assert got["tenant_id"] == TENANT_1

    event_types = {e["event_type"] for e in received}
    assert event_types == {
        "repo.intaken.v1",
        "plan.contract.approved.v1",
        "patch.unit.completed.v1",
        "quality.gate.passed.v1",
        "quality.gate.failed.v1",
    }
    # `patch.unit.completed.v1`'s payload never carries file CONTENT, only
    # paths — a real-effects re-assertion at the transport layer (the
    # payload builder itself already guarantees this shape; this proves the
    # guarantee survives a real produce/consume round trip unmodified).
    patch_unit_envelope = next(e for e in received if e["event_type"] == "patch.unit.completed.v1")
    assert patch_unit_envelope["payload"]["changed_files"] == ["apps/web/docs/new-page.md"]

    failed_envelope = next(e for e in received if e["event_type"] == "quality.gate.failed.v1")
    assert failed_envelope["payload"]["failures"][0]["error_code"] == (
        "saena.internal.secret_detected"
    )
