"""`OutcomeDecisionStore` append-only + no-partial-state semantics (w5-09).

Append-only decision records; decision + evidence_bundle_ref + policy metadata
are stored ATOMICALLY as one frozen record (the API shape makes a partial
write impossible). Overwrite of an existing decision → `AppendOnlyViolationError`.
"""

from __future__ import annotations

import dataclasses

import pytest
from measurement_factories import TENANT_A, TENANT_B, make_decision
from saena_domain.measurement.ports import (
    AppendOnlyViolationError,
    InMemoryOutcomeDecisionStore,
    NotFoundError,
    OutcomeDecisionRecord,
    PutOutcome,
    TenantIsolationError,
)


def test_append_absent_decision_is_stored() -> None:
    store = InMemoryOutcomeDecisionStore()
    d = make_decision()
    result = store.append_decision(TENANT_A, d)
    assert result.outcome is PutOutcome.STORED
    assert store.get(TENANT_A, d.decision_key) == d


def test_identical_replay_is_noop_duplicate_not_violation() -> None:
    # At-least-once replay of the SAME decision is a no-op, never a violation.
    store = InMemoryOutcomeDecisionStore()
    d = make_decision()
    store.append_decision(TENANT_A, d)
    result = store.append_decision(TENANT_A, make_decision())
    assert result.outcome is PutOutcome.DUPLICATE
    assert result.record == d


def test_overwrite_existing_decision_raises_append_only_violation() -> None:
    store = InMemoryOutcomeDecisionStore()
    d = make_decision(outcome="lift_confirmed")
    store.append_decision(TENANT_A, d)
    changed = make_decision(outcome="no_lift")
    with pytest.raises(AppendOnlyViolationError) as excinfo:
        store.append_decision(TENANT_A, changed)
    # The original decision is immutable — the overwrite left no trace.
    assert store.get(TENANT_A, d.decision_key).outcome == "lift_confirmed"
    assert excinfo.value.context["decision_key"] == list(d.decision_key)


def test_record_is_atomic_frozen_no_partial_state_possible() -> None:
    # The record is a frozen dataclass carrying decision + evidence ref +
    # policy metadata TOGETHER. There is no setter/no per-field write path —
    # a partial decision (decision without evidence, or vice versa) cannot be
    # constructed and stored through this port.
    d = make_decision()
    assert d.outcome and d.evidence_bundle_ref and d.policy_metadata
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.outcome = "tampered"  # type: ignore[misc]
    # Construction with a missing atomic component is a hard error.
    with pytest.raises((TypeError, ValueError)):
        OutcomeDecisionRecord(  # type: ignore[call-arg]
            tenant_id=TENANT_A,
            decision_key=("exp-1", "primary"),
            outcome="lift_confirmed",
            evidence_bundle_ref="",  # empty evidence ref is invalid
            policy_metadata={"policy_version": "1.0.0"},
        )


def test_missing_policy_metadata_rejected_at_construction() -> None:
    with pytest.raises((TypeError, ValueError)):
        OutcomeDecisionRecord(
            tenant_id=TENANT_A,
            decision_key=("exp-1", "primary"),
            outcome="lift_confirmed",
            evidence_bundle_ref="sha256:" + "a" * 64,
            policy_metadata={},  # empty metadata is invalid
        )


def test_get_absent_decision_raises_not_found() -> None:
    store = InMemoryOutcomeDecisionStore()
    with pytest.raises(NotFoundError):
        store.get(TENANT_A, ("exp-x", "primary"))


def test_list_decisions_in_append_order() -> None:
    store = InMemoryOutcomeDecisionStore()
    d1 = make_decision(decision_key=("exp-1", "primary"))
    d2 = make_decision(decision_key=("exp-1", "secondary"))
    store.append_decision(TENANT_A, d1)
    store.append_decision(TENANT_A, d2)
    listed = store.list_decisions(TENANT_A)
    assert listed == (d1, d2)


def test_list_decisions_empty_tuple_when_none() -> None:
    store = InMemoryOutcomeDecisionStore()
    assert store.list_decisions(TENANT_A) == ()


def test_cross_tenant_decisions_independent_and_isolated() -> None:
    store = InMemoryOutcomeDecisionStore()
    a = make_decision(tenant_id=TENANT_A, outcome="lift_confirmed")
    b = make_decision(tenant_id=TENANT_B, outcome="no_lift")
    store.append_decision(TENANT_A, a)
    store.append_decision(TENANT_B, b)  # same decision_key, different tenant
    assert store.get(TENANT_A, a.decision_key) == a
    assert store.get(TENANT_B, b.decision_key) == b
    assert store.list_decisions(TENANT_A) == (a,)
    assert store.list_decisions(TENANT_B) == (b,)


def test_cross_tenant_get_is_non_leaking_absent() -> None:
    store = InMemoryOutcomeDecisionStore()
    a = make_decision(tenant_id=TENANT_A)
    store.append_decision(TENANT_A, a)
    with pytest.raises(NotFoundError):
        store.get(TENANT_B, a.decision_key)


def test_forged_tenant_decision_rejected() -> None:
    store = InMemoryOutcomeDecisionStore()
    forged = make_decision(tenant_id=TENANT_B)
    with pytest.raises(TenantIsolationError):
        store.append_decision(TENANT_A, forged)
    with pytest.raises(NotFoundError):
        store.get(TENANT_A, forged.decision_key)


def test_empty_tenant_rejected() -> None:
    store = InMemoryOutcomeDecisionStore()
    d = make_decision()
    with pytest.raises(ValueError):
        store.append_decision("", d)
    with pytest.raises(ValueError):
        store.get("", d.decision_key)
    with pytest.raises(ValueError):
        store.list_decisions("")
