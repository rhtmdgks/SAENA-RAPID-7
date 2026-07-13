"""Tests for `InMemoryDecisionRecordStore` (`DecisionRecordPort` port)."""

from __future__ import annotations

import pytest
from saena_domain.identity import TenantId
from saena_domain.persistence import (
    DecisionConflictError,
    InMemoryDecisionRecordStore,
    NotFoundError,
)
from saena_domain.policy import DecisionRecord

TENANT_A = TenantId("acme-co")
TENANT_B = TenantId("globex-co")


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


def test_record_then_get_round_trips() -> None:
    store = InMemoryDecisionRecordStore()
    decision = _decision()

    stored = store.record(TENANT_A, decision)

    assert stored == decision
    assert store.get(TENANT_A, decision.decision_key) == decision


def test_get_missing_raises_not_found() -> None:
    store = InMemoryDecisionRecordStore()

    with pytest.raises(NotFoundError):
        store.get(TENANT_A, ("sha256:missing", "actor-x"))


def test_record_is_idempotent_on_identical_replay() -> None:
    store = InMemoryDecisionRecordStore()
    decision = _decision()

    first = store.record(TENANT_A, decision)
    second = store.record(TENANT_A, decision)

    assert first == second


def test_record_conflict_raises_decision_conflict_error() -> None:
    store = InMemoryDecisionRecordStore()
    store.record(TENANT_A, _decision(decision="approved"))

    with pytest.raises(DecisionConflictError):
        store.record(TENANT_A, _decision(decision="rejected"))


def test_decision_keys_are_isolated_per_tenant() -> None:
    """Two tenants recording a decision with the SAME decision_key are
    independent — no cross-tenant conflict, no cross-tenant leak."""
    store = InMemoryDecisionRecordStore()
    decision = _decision()

    store.record(TENANT_A, decision)
    store.record(TENANT_B, decision)  # must not raise DecisionConflictError

    assert store.get(TENANT_A, decision.decision_key) == decision
    assert store.get(TENANT_B, decision.decision_key) == decision


def test_cross_tenant_get_does_not_see_other_tenants_decision() -> None:
    store = InMemoryDecisionRecordStore()
    decision = _decision()
    store.record(TENANT_A, decision)

    with pytest.raises(NotFoundError):
        store.get(TENANT_B, decision.decision_key)


def test_decision_key_canonicalizes_approver_actor_id_whitespace_case() -> None:
    """decision_key uses saena_domain.policy.canonical_actor_id — a
    whitespace/case variant of the same approver must map to the SAME
    replay key (mirrors saena_domain.policy.transitions's own guarantee)."""
    store = InMemoryDecisionRecordStore()
    first = _decision(approver_actor_id="Actor-Approver-1")
    replay = _decision(approver_actor_id=" actor-approver-1 ")

    store.record(TENANT_A, first)
    result = store.record(TENANT_A, replay)

    assert result == first
