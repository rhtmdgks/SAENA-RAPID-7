"""Tests for `InMemoryPlanRepository` (`PlanRepository` port)."""

from __future__ import annotations

import pytest
from saena_domain.identity import TenantId
from saena_domain.persistence import (
    DecisionConflictError,
    InMemoryPlanRepository,
    NotFoundError,
    TenantIsolationError,
)
from saena_domain.policy import DecisionRecord, PlanSnapshot, PlanState

TENANT_A = TenantId("acme-co")
TENANT_B = TenantId("globex-co")


def _snapshot(contract_hash: str = "sha256:abc", fingerprint: str = "fp-1") -> PlanSnapshot:
    return PlanSnapshot(contract_hash=contract_hash, content_fingerprint=fingerprint)


def _decision(**overrides: object) -> DecisionRecord:
    base: dict[str, object] = {
        "contract_hash": "sha256:abc",
        "approver_actor_id": "actor-approver-1",
        "decision": "approved",
        "proposer_actor_id": "actor-proposer-1",
        "high_risk": False,
        "decided_at": "2026-07-12T09:00:00Z",
    }
    base.update(overrides)
    return DecisionRecord(**base)  # type: ignore[arg-type]


# --- plan snapshot -------------------------------------------------------------


def test_put_then_get_plan_round_trips() -> None:
    repo = InMemoryPlanRepository()
    snap = _snapshot()

    repo.put_plan(TENANT_A, snap)

    assert repo.get_plan(TENANT_A, snap.contract_hash) == snap


def test_get_plan_missing_raises_not_found() -> None:
    repo = InMemoryPlanRepository()

    with pytest.raises(NotFoundError):
        repo.get_plan(TENANT_A, "sha256:missing")


def test_cross_tenant_get_plan_raises_tenant_isolation_error() -> None:
    repo = InMemoryPlanRepository()
    snap = _snapshot()
    repo.put_plan(TENANT_A, snap)

    with pytest.raises(TenantIsolationError):
        repo.get_plan(TENANT_B, snap.contract_hash)


def test_cross_tenant_put_plan_raises_tenant_isolation_error() -> None:
    repo = InMemoryPlanRepository()
    snap = _snapshot()
    repo.put_plan(TENANT_A, snap)

    with pytest.raises(TenantIsolationError):
        repo.put_plan(TENANT_B, snap)


# --- plan state -----------------------------------------------------------------


def test_set_then_get_state_round_trips() -> None:
    repo = InMemoryPlanRepository()
    repo.set_state(TENANT_A, "sha256:abc", PlanState.PROPOSED)

    assert repo.get_state(TENANT_A, "sha256:abc") == PlanState.PROPOSED


def test_get_state_missing_raises_not_found() -> None:
    repo = InMemoryPlanRepository()

    with pytest.raises(NotFoundError):
        repo.get_state(TENANT_A, "sha256:missing")


def test_cross_tenant_get_state_raises_tenant_isolation_error() -> None:
    repo = InMemoryPlanRepository()
    repo.set_state(TENANT_A, "sha256:abc", PlanState.WAITING_APPROVAL)

    with pytest.raises(TenantIsolationError):
        repo.get_state(TENANT_B, "sha256:abc")


# --- decisions --------------------------------------------------------------------


def test_record_decision_stores_new_decision() -> None:
    repo = InMemoryPlanRepository()
    decision = _decision()

    result = repo.record_decision(TENANT_A, decision)

    assert result == decision
    assert repo.get_decisions(TENANT_A, "sha256:abc") == (decision,)


def test_record_decision_is_idempotent_on_identical_replay() -> None:
    repo = InMemoryPlanRepository()
    decision = _decision()

    first = repo.record_decision(TENANT_A, decision)
    second = repo.record_decision(TENANT_A, decision)

    assert first == second
    assert repo.get_decisions(TENANT_A, "sha256:abc") == (decision,)


def test_record_decision_conflict_raises() -> None:
    repo = InMemoryPlanRepository()
    repo.record_decision(TENANT_A, _decision(decision="approved"))

    with pytest.raises(DecisionConflictError):
        repo.record_decision(TENANT_A, _decision(decision="rejected"))


def test_cross_tenant_decision_conflict_raises_tenant_isolation_error() -> None:
    repo = InMemoryPlanRepository()
    repo.record_decision(TENANT_A, _decision())

    with pytest.raises(TenantIsolationError):
        repo.record_decision(TENANT_B, _decision())


def test_get_decisions_empty_when_none_recorded() -> None:
    repo = InMemoryPlanRepository()

    assert repo.get_decisions(TENANT_A, "sha256:none") == ()


def test_get_decisions_filters_by_contract_hash() -> None:
    repo = InMemoryPlanRepository()
    repo.record_decision(TENANT_A, _decision(contract_hash="sha256:abc"))
    repo.record_decision(
        TENANT_A,
        _decision(contract_hash="sha256:def", approver_actor_id="actor-approver-2"),
    )

    result = repo.get_decisions(TENANT_A, "sha256:abc")

    assert len(result) == 1
    assert result[0].contract_hash == "sha256:abc"
