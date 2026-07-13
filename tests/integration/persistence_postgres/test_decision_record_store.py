"""Integration tests for `PostgresDecisionRecordStore` — mirrors
`InMemoryDecisionRecordStore`'s reference semantics
(`tests/unit/domain_persistence/test_decision_record_store.py`) over real
SQL."""

from __future__ import annotations

import pytest
from postgres_factories import run_async
from saena_domain.identity import TenantId
from saena_domain.persistence.errors import DecisionConflictError, NotFoundError
from saena_domain.persistence.postgres.adapters import PostgresDecisionRecordStore
from saena_domain.policy import DecisionRecord
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

TENANT_A = TenantId("acme-co")


def _decision(decision: str = "approved") -> DecisionRecord:
    return DecisionRecord(
        contract_hash="sha256:contract-1",
        approver_actor_id="approver-1",
        decision=decision,
        proposer_actor_id="proposer-1",
        high_risk=False,
        decided_at="2026-07-13T00:00:00Z",
    )


def test_record_then_get_round_trips(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PostgresDecisionRecordStore(engine)
        decision = _decision()

        await store.record(TENANT_A, decision)
        fetched = await store.get(TENANT_A, decision.decision_key)

        assert fetched == decision

    run_async(scenario())


def test_record_replay_returns_stored_record(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PostgresDecisionRecordStore(engine)
        decision = _decision()
        await store.record(TENANT_A, decision)

        replay = await store.record(TENANT_A, decision)

        assert replay == decision

    run_async(scenario())


def test_record_conflict_raises(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PostgresDecisionRecordStore(engine)
        await store.record(TENANT_A, _decision(decision="approved"))

        with pytest.raises(DecisionConflictError):
            await store.record(TENANT_A, _decision(decision="rejected"))

    run_async(scenario())


def test_get_missing_raises_not_found(engine: AsyncEngine) -> None:
    async def scenario() -> None:
        store = PostgresDecisionRecordStore(engine)
        with pytest.raises(NotFoundError):
            await store.get(TENANT_A, ("sha256:no-such", "approver-x"))

    run_async(scenario())


def test_caller_injected_connection_used_for_record_and_get(engine: AsyncEngine) -> None:
    """`record`/`get` also accept a caller-supplied `connection=` (session-scoped
    variant, `adapters.py`'s module docstring)."""

    async def scenario() -> None:
        store = PostgresDecisionRecordStore(engine)
        decision = _decision()

        async with engine.begin() as conn:
            recorded = await store.record(TENANT_A, decision, connection=conn)
            fetched = await store.get(TENANT_A, decision.decision_key, connection=conn)
            assert recorded == decision
            assert fetched == decision

    run_async(scenario())


def test_distinct_from_plan_repository_storage(engine: AsyncEngine) -> None:
    """`DecisionRecordPort` is policy-gate's OWN log, distinct storage from
    `PlanRepository.record_decision` — recording via one never satisfies a
    `get` on the other."""

    async def scenario() -> None:
        from saena_domain.persistence.postgres.adapters import PostgresPlanRepository

        plan_repo = PostgresPlanRepository(engine)
        decision_store = PostgresDecisionRecordStore(engine)
        decision = _decision()

        await plan_repo.record_decision(TENANT_A, decision)

        with pytest.raises(NotFoundError):
            await decision_store.get(TENANT_A, decision.decision_key)

    run_async(scenario())
