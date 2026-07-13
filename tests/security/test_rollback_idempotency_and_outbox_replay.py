"""Rollback verification gate (testing-strategy.md sec F-7): workflow
retry/replay, duplicate-event dedup, outbox replay, idempotency key not
double-executed.

Fixture narrative: a patch unit fails once (rolled back — `saena_agent_
runner.runner` never produces an artifact/event for a rolled-back unit, see
`test_rollback_worktree_no_partial_commit.py`), is retried, and SUCCEEDS —
producing exactly one `patch.unit.completed.v1` envelope. The at-least-once
retry/redelivery machinery around that single logical outcome (a Temporal
retry, an at-least-once bus redelivery, an operator re-running the same job)
must never cause it to be double-applied downstream.

Wired against the REAL `saena_domain.bus`/`saena_domain.persistence`
primitives: `IdempotentConsumer` + `InMemoryIdempotencyStore` (consumer-side
dedup), `OutboxDrainer` + `InMemoryOutbox` + `InMemoryPublisher` (outbox
drain/replay — a transient publish failure leaves the row pending and is
retried on the next `drain_once`, at-least-once semantics; a row already
marked published is never re-published by a later drain).

Postgres-backed proof of the SAME mechanism (real container, not in-memory)
lives in `tests/integration/failure_modes/
test_rollback_outbox_idempotent_replay_postgres.py`.
"""

from __future__ import annotations

import asyncio

from runner_factories import (
    CONTRACT_HASH,
    PATCH_UNIT_ID,
    build_approval_decision,
    build_change_plan,
)
from saena_agent_runner.approval import parse_approval_decision
from saena_agent_runner.artifact import FakeArtifactRegistryGateway
from saena_agent_runner.clock import FakeClock
from saena_agent_runner.contract import parse_change_plan
from saena_agent_runner.runner import FileWrite, PatchUnitRequest, PatchUnitRunner
from saena_agent_runner.worktree import FakeCommandExecutor, FakeWorktreeFactory
from saena_domain.audit import InMemoryAuditChain
from saena_domain.bus import IdempotentConsumer, InMemoryPublisher, OutboxDrainer
from saena_domain.bus.errors import PublishFailedError
from saena_domain.events import EnvelopeFactory
from saena_domain.execution import JobContext, JobStatus
from saena_domain.identity import TenantId
from saena_domain.persistence import InMemoryIdempotencyStore, InMemoryOutbox


def _succeed_the_retry(
    job_context: JobContext,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
):
    """The SECOND attempt at the same patch unit — this one succeeds and
    produces exactly one `patch.unit.completed.v1` event_payload, mirroring
    what a real retry-after-rollback looks like from `runner.py`'s own
    perspective (a brand new, fully isolated worktree; the FIRST, rolled-back
    attempt left no trace behind to interfere with it)."""
    contract = parse_change_plan(build_change_plan())
    approval = parse_approval_decision(build_approval_decision())
    runner = PatchUnitRunner(
        worktree_factory=worktree_factory,
        command_executor=command_executor,
        artifact_gateway=artifact_gateway,
        audit_chain=audit_chain,
        clock=clock,
    )
    result = runner.run(
        job_context=job_context,
        contract=contract,
        expected_contract_hash=CONTRACT_HASH,
        approval=approval,
        requests=[
            PatchUnitRequest(
                patch_unit_id=PATCH_UNIT_ID,
                file_writes=(FileWrite("apps/web/docs/readme.md", b"the retried fix"),),
            )
        ],
    )
    assert result.outcomes[0].status == JobStatus.SUCCEEDED
    return result.outcomes[0]


def test_retried_success_envelope_redelivered_twice_is_handled_exactly_once(
    job_context: JobContext,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    outcome = _succeed_the_retry(
        job_context, worktree_factory, command_executor, artifact_gateway, audit_chain, clock
    )
    envelope = EnvelopeFactory.build_tenant_envelope(
        producer="agent-runner-service",
        event_type="patch.unit.completed.v1",
        tenant_id=job_context.tenant_id,
        run_id=job_context.run_id,
        idempotency_key=f"{job_context.tenant_id}:{job_context.run_id}:{PATCH_UNIT_ID}",
        payload=outcome.event_payload,
    )

    store = InMemoryIdempotencyStore()
    consumer = IdempotentConsumer(store)
    handled: list[dict[str, object]] = []

    async def handler(env: dict[str, object]) -> None:
        handled.append(env)

    async def scenario() -> tuple[bool, bool]:
        first_ran = await consumer.process(envelope, handler)
        # at-least-once redelivery: the SAME envelope arrives a second time.
        second_ran = await consumer.process(dict(envelope), handler)
        return first_ran, second_ran

    first_ran, second_ran = asyncio.run(scenario())

    assert first_ran is True
    assert second_ran is False, "redelivery must be a no-op dedup skip"
    assert len(handled) == 1, "handler ran exactly once despite two deliveries"
    assert store.seen(
        TenantId(job_context.tenant_id),
        f"{job_context.tenant_id}:{job_context.run_id}:{PATCH_UNIT_ID}",
    )


def test_outbox_drain_never_republishes_an_already_published_row(
    job_context: JobContext,
    worktree_factory: FakeWorktreeFactory,
    command_executor: FakeCommandExecutor,
    artifact_gateway: FakeArtifactRegistryGateway,
    audit_chain: InMemoryAuditChain,
    clock: FakeClock,
) -> None:
    outcome = _succeed_the_retry(
        job_context, worktree_factory, command_executor, artifact_gateway, audit_chain, clock
    )
    envelope = EnvelopeFactory.build_tenant_envelope(
        producer="agent-runner-service",
        event_type="patch.unit.completed.v1",
        tenant_id=job_context.tenant_id,
        run_id=job_context.run_id,
        idempotency_key=f"{job_context.tenant_id}:{job_context.run_id}:{PATCH_UNIT_ID}",
        payload=outcome.event_payload,
    )

    outbox = InMemoryOutbox()
    outbox.record(envelope)
    publisher = InMemoryPublisher()
    drainer = OutboxDrainer(outbox, publisher)

    async def scenario() -> None:
        first_drain = await drainer.drain_once()
        assert first_drain.published == (envelope["event_id"],)
        # a second drain (e.g. a retried/replayed workflow step re-invoking
        # the SAME drain call) must find nothing pending — no duplicate
        # publish of an already-published row.
        second_drain = await drainer.drain_once()
        assert second_drain.published == ()
        assert second_drain.retried_pending == ()

    asyncio.run(scenario())
    assert len(publisher.published) == 1, "exactly one publish reached the broker"


def test_outbox_drain_retries_a_transient_publish_failure_without_marking_published() -> None:
    """ "outbox replay": a transient publish failure leaves the row PENDING
    (never marked published) and the NEXT `drain_once` call retries it —
    at-least-once semantics, exactly the "workflow retry/replay" the
    mission names, proven at the pure in-memory layer."""

    class _FlakyOncePublisher:
        def __init__(self) -> None:
            self.attempts = 0
            self.published: list[tuple[str, dict[str, object]]] = []

        async def publish(self, topic: str, envelope: dict[str, object]) -> None:
            self.attempts += 1
            if self.attempts == 1:
                raise PublishFailedError("simulated transient broker outage", context={})
            self.published.append((topic, envelope))

    outbox = InMemoryOutbox()
    envelope = EnvelopeFactory.build_system_envelope(
        producer="agent-runner-service",
        event_type="patch.unit.completed.v1",
        idempotency_key="system:retry-replay-fixture:v1",
        payload={"patch_unit_id": PATCH_UNIT_ID, "worktree_commit": "c" * 40},
    )
    outbox.record(envelope)
    publisher = _FlakyOncePublisher()
    drainer = OutboxDrainer(outbox, publisher)

    async def scenario() -> None:
        first = await drainer.drain_once()
        assert first.published == ()
        assert first.retried_pending == (envelope["event_id"],)
        assert outbox.list_pending() == (envelope,)  # still pending, not lost

        second = await drainer.drain_once()
        assert second.published == (envelope["event_id"],)
        assert outbox.list_pending() == ()

    asyncio.run(scenario())
    assert publisher.attempts == 2
    assert len(publisher.published) == 1, "replayed exactly once after the transient failure"
