"""Integration tests for `PostgresPlanRepository` — mirrors
`InMemoryPlanRepository`'s reference semantics
(`tests/unit/domain_persistence/test_plan_repository.py`) over real SQL,
plus a concurrent-double-record_decision test using two independent
sessions/connections against the same running Postgres instance."""

from __future__ import annotations

import asyncio

import pytest
from postgres_factories import run_async
from saena_domain.identity import TenantId
from saena_domain.persistence.errors import (
    DecisionConflictError,
    NotFoundError,
    TenantIsolationError,
)
from saena_domain.persistence.postgres.adapters import PostgresPlanRepository
from saena_domain.policy import DecisionRecord, PlanSnapshot, PlanState
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

TENANT_A = TenantId("acme-co")
TENANT_B = TenantId("globex-co")


def _snapshot(contract_hash: str = "sha256:contract-1", fingerprint: str = "fp-1") -> PlanSnapshot:
    return PlanSnapshot(contract_hash=contract_hash, content_fingerprint=fingerprint)


def _decision(
    contract_hash: str = "sha256:contract-1",
    approver: str = "approver-1",
    decision: str = "approved",
) -> DecisionRecord:
    return DecisionRecord(
        contract_hash=contract_hash,
        approver_actor_id=approver,
        decision=decision,
        proposer_actor_id="proposer-1",
        high_risk=False,
        decided_at="2026-07-13T00:00:00Z",
    )


def test_put_plan_then_get_plan_round_trips(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        repo = PostgresPlanRepository(engine)
        snapshot = _snapshot()

        await repo.put_plan(TENANT_A, snapshot)
        fetched = await repo.get_plan(TENANT_A, snapshot.contract_hash)

        assert fetched == snapshot

    run_async(scenario())


def test_get_plan_missing_raises_not_found(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        repo = PostgresPlanRepository(engine)
        with pytest.raises(NotFoundError):
            await repo.get_plan(TENANT_A, "sha256:no-such-plan")

    run_async(scenario())


def test_get_plan_cross_tenant_raises_isolation(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        repo = PostgresPlanRepository(engine)
        snapshot = _snapshot()
        await repo.put_plan(TENANT_A, snapshot)

        with pytest.raises(TenantIsolationError):
            await repo.get_plan(TENANT_B, snapshot.contract_hash)

    run_async(scenario())


def test_set_state_then_get_state_round_trips(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        repo = PostgresPlanRepository(engine)
        snapshot = _snapshot()
        await repo.put_plan(TENANT_A, snapshot)

        await repo.set_state(TENANT_A, snapshot.contract_hash, PlanState.WAITING_APPROVAL)
        state = await repo.get_state(TENANT_A, snapshot.contract_hash)

        assert state == PlanState.WAITING_APPROVAL

    run_async(scenario())


def test_get_state_before_set_raises_not_found(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        repo = PostgresPlanRepository(engine)
        snapshot = _snapshot()
        await repo.put_plan(TENANT_A, snapshot)

        with pytest.raises(NotFoundError):
            await repo.get_state(TENANT_A, snapshot.contract_hash)

    run_async(scenario())


def test_record_decision_new_key_stores_and_returns_unchanged(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        repo = PostgresPlanRepository(engine)
        decision = _decision()

        result = await repo.record_decision(TENANT_A, decision)

        assert result == decision

    run_async(scenario())


def test_record_decision_replay_returns_stored_record(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        repo = PostgresPlanRepository(engine)
        decision = _decision()
        await repo.record_decision(TENANT_A, decision)

        replay = await repo.record_decision(TENANT_A, decision)

        assert replay == decision

    run_async(scenario())


def test_record_decision_conflict_raises(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        repo = PostgresPlanRepository(engine)
        await repo.record_decision(TENANT_A, _decision(decision="approved"))

        with pytest.raises(DecisionConflictError):
            await repo.record_decision(TENANT_A, _decision(decision="rejected"))

    run_async(scenario())


def test_get_decisions_returns_insertion_order(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        repo = PostgresPlanRepository(engine)
        first = _decision(approver="approver-1")
        second = _decision(approver="approver-2")
        await repo.record_decision(TENANT_A, first)
        await repo.record_decision(TENANT_A, second)

        decisions = await repo.get_decisions(TENANT_A, "sha256:contract-1")

        assert decisions == (first, second)

    run_async(scenario())


def test_record_decision_cross_tenant_key_raises_isolation(engine: AsyncEngine) -> None:
    """`record_decision`'s OWN cross-tenant isolation check on the
    `(contract_hash, approver_actor_id)` decision key — distinct from
    `get_plan`/`get_state`'s `contract_hash`-only isolation check: tenant B
    submitting a decision under a `(contract_hash, approver_actor_id)` pair
    already owned by tenant A must be denied, never silently recorded under
    a second tenant."""

    async def scenario() -> None:
        repo = PostgresPlanRepository(engine)
        await repo.record_decision(TENANT_A, _decision())

        with pytest.raises(TenantIsolationError):
            await repo.record_decision(TENANT_B, _decision())

    run_async(scenario())


def test_get_decisions_empty_when_none_recorded(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        repo = PostgresPlanRepository(engine)
        decisions = await repo.get_decisions(TENANT_A, "sha256:no-decisions")
        assert decisions == ()

    run_async(scenario())


def test_concurrent_double_record_decision_same_key_yields_single_row(engine: AsyncEngine) -> None:
    """Two independent CONNECTIONS both attempt `record_decision` for the
    SAME idempotency key concurrently — exactly one row must land, and both
    callers must observe a consistent (identical) outcome, never two
    conflicting rows.

    Each call is given its OWN connection (`connection=conn_a`/`conn_b`,
    each opened and committed independently via `record_decision`'s own
    per-call transaction — see `adapters.py`'s "Async,
    connection/session-injectable" module docstring) rather than one
    externally pre-opened transaction shared for the whole `asyncio.gather`
    — pre-opening BOTH transactions before either INSERT runs would create a
    genuine deadlock (each transaction's row-lock wait blocks on the
    other's commit, but neither commits until `gather` itself returns),
    which is a test-harness bug, not a product behavior this port needs to
    support. The atomic `INSERT ... ON CONFLICT DO NOTHING` inside
    `_record_decision_atomically` (`adapters.py`) is what actually makes the
    race safe: whichever call's own independent transaction commits FIRST
    wins the row; the other observes `rowcount == 0` and reads back the
    winner's already-committed value.
    """

    async def _record_with_own_transaction(
        repo: PostgresPlanRepository, decision: DecisionRecord
    ) -> DecisionRecord:
        async with engine.connect() as conn, conn.begin():
            return await repo.record_decision(TENANT_A, decision, connection=conn)

    async def scenario() -> None:
        repo = PostgresPlanRepository(engine)
        decision = _decision()

        results = await asyncio.gather(
            _record_with_own_transaction(repo, decision),
            _record_with_own_transaction(repo, decision),
            return_exceptions=True,
        )

        # Neither call may raise DecisionConflictError here (both callers
        # submit the IDENTICAL decision value — a true conflict only fires
        # for a genuinely different decision under the same key, see
        # `test_record_decision_conflict_raises`) — both must succeed with
        # the same, consistent outcome.
        for result in results:
            if isinstance(result, BaseException):
                raise result
            assert result == decision

        final = await repo.get_decisions(TENANT_A, decision.contract_hash)
        assert len(final) == 1
        assert final[0].decision == decision.decision

    run_async(scenario())
