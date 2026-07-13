"""`ConfirmationStore` idempotency semantics (w5-09).

absent → stored; identical replay → no-op Duplicate; same key + different
canonical content → `IdempotencyConflictError` (NEVER arbitrary winner, NEVER
overwrite). Reads are tenant-scoped; cross-tenant → non-leaking absent.
"""

from __future__ import annotations

import copy

import pytest
from measurement_factories import TENANT_A, TENANT_B, make_confirmation
from saena_domain.measurement.ports import (
    IdempotencyConflictError,
    InMemoryConfirmationStore,
    NotFoundError,
    PutOutcome,
    TenantIsolationError,
)


def test_absent_key_is_stored_and_reports_stored() -> None:
    store = InMemoryConfirmationStore()
    rec = make_confirmation()
    result = store.put_confirmation(TENANT_A, rec.confirmation_key, rec)
    assert result.outcome is PutOutcome.STORED
    assert result.record == rec
    assert store.get(TENANT_A, rec.confirmation_key) == rec


def test_identical_replay_is_noop_duplicate() -> None:
    store = InMemoryConfirmationStore()
    rec = make_confirmation()
    store.put_confirmation(TENANT_A, rec.confirmation_key, rec)
    # Byte-identical canonical content (a distinct but equal object).
    replay = make_confirmation()
    result = store.put_confirmation(TENANT_A, replay.confirmation_key, replay)
    assert result.outcome is PutOutcome.DUPLICATE
    # The ALREADY-stored record is returned, unchanged.
    assert result.record == rec


def test_same_key_different_content_raises_conflict_and_never_overwrites() -> None:
    store = InMemoryConfirmationStore()
    rec = make_confirmation()
    store.put_confirmation(TENANT_A, rec.confirmation_key, rec)
    conflicting = make_confirmation(payload={"citation_id": "cit-999", "confirmed_at": "z"})
    with pytest.raises(IdempotencyConflictError) as excinfo:
        store.put_confirmation(TENANT_A, rec.confirmation_key, conflicting)
    # Fail-closed: the ORIGINAL record is still what is stored — no arbitrary
    # winner, no silent overwrite.
    assert store.get(TENANT_A, rec.confirmation_key) == rec
    assert excinfo.value.context["confirmation_key"] == rec.confirmation_key
    assert excinfo.value.error_code == "saena.measurement.idempotency_conflict"


def test_conflict_is_symmetric_regardless_of_arrival_order() -> None:
    # Whichever payload lands first wins; the second (different) one always
    # conflicts — there is never a "later write wins" path.
    a = make_confirmation(payload={"v": 1})
    b = make_confirmation(payload={"v": 2})
    s1 = InMemoryConfirmationStore()
    s1.put_confirmation(TENANT_A, a.confirmation_key, a)
    with pytest.raises(IdempotencyConflictError):
        s1.put_confirmation(TENANT_A, b.confirmation_key, b)
    s2 = InMemoryConfirmationStore()
    s2.put_confirmation(TENANT_A, b.confirmation_key, b)
    with pytest.raises(IdempotencyConflictError):
        s2.put_confirmation(TENANT_A, a.confirmation_key, a)


def test_get_absent_key_raises_not_found() -> None:
    store = InMemoryConfirmationStore()
    with pytest.raises(NotFoundError):
        store.get(TENANT_A, "no-such-key")


def test_cross_tenant_same_key_is_independent_no_leak() -> None:
    store = InMemoryConfirmationStore()
    a = make_confirmation(tenant_id=TENANT_A, payload={"owner": "a"})
    b = make_confirmation(tenant_id=TENANT_B, payload={"owner": "b"})
    # Same confirmation_key, different tenants: both stored independently, no
    # conflict, no leak.
    store.put_confirmation(TENANT_A, a.confirmation_key, a)
    store.put_confirmation(TENANT_B, b.confirmation_key, b)
    assert store.get(TENANT_A, a.confirmation_key) == a
    assert store.get(TENANT_B, b.confirmation_key) == b


def test_cross_tenant_get_is_non_leaking_absent_not_isolation_error() -> None:
    store = InMemoryConfirmationStore()
    a = make_confirmation(tenant_id=TENANT_A)
    store.put_confirmation(TENANT_A, a.confirmation_key, a)
    # Tenant B asking for A's key: structurally a different key namespace, so
    # NOT-FOUND (a non-leaking absent) — B cannot even observe that A's key
    # exists.
    with pytest.raises(NotFoundError):
        store.get(TENANT_B, a.confirmation_key)


def test_forged_tenant_id_on_record_is_rejected() -> None:
    store = InMemoryConfirmationStore()
    # Caller passes tenant A but the record claims tenant B: a forged-tenant
    # write, rejected before any key is written under either tenant.
    forged = make_confirmation(tenant_id=TENANT_B)
    with pytest.raises(TenantIsolationError):
        store.put_confirmation(TENANT_A, forged.confirmation_key, forged)
    # Nothing was stored under either tenant.
    with pytest.raises(NotFoundError):
        store.get(TENANT_A, forged.confirmation_key)
    with pytest.raises(NotFoundError):
        store.get(TENANT_B, forged.confirmation_key)


def test_empty_tenant_id_is_rejected() -> None:
    store = InMemoryConfirmationStore()
    rec = make_confirmation()
    with pytest.raises(ValueError):
        store.put_confirmation("", rec.confirmation_key, rec)
    with pytest.raises(ValueError):
        store.get("", rec.confirmation_key)


def test_returned_record_mutation_cannot_corrupt_store() -> None:
    # ConfirmationRecord is frozen (payload is a MappingProxy) — mutating a
    # copy of the payload must not affect the stored value.
    store = InMemoryConfirmationStore()
    rec = make_confirmation()
    store.put_confirmation(TENANT_A, rec.confirmation_key, rec)
    got = store.get(TENANT_A, rec.confirmation_key)
    with pytest.raises(TypeError):
        got.payload["citation_id"] = "tampered"  # MappingProxy is read-only
    # Deep-copy of the payload is independent.
    mutated = copy.deepcopy(dict(got.payload))
    mutated["citation_id"] = "tampered"
    assert store.get(TENANT_A, rec.confirmation_key).payload["citation_id"] == "cit-042"
