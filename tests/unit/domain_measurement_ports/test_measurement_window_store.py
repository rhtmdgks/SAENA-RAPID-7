"""`MeasurementWindowStore` semantics (w5-09).

At most one active window per `(tenant_id, experiment_id)`. Second window with
a DIFFERING start → conflict; an IDENTICAL open request → no-op Duplicate.
"""

from __future__ import annotations

import pytest
from measurement_factories import TENANT_A, TENANT_B, make_window
from saena_domain.measurement.ports import (
    IdempotencyConflictError,
    InMemoryMeasurementWindowStore,
    NotFoundError,
    PutOutcome,
    TenantIsolationError,
)


def test_open_absent_window_is_stored() -> None:
    store = InMemoryMeasurementWindowStore()
    w = make_window()
    result = store.open_window(TENANT_A, w)
    assert result.outcome is PutOutcome.STORED
    assert store.get_active(TENANT_A, w.experiment_id) == w


def test_identical_reopen_is_noop_duplicate() -> None:
    store = InMemoryMeasurementWindowStore()
    w = make_window()
    store.open_window(TENANT_A, w)
    again = make_window()
    result = store.open_window(TENANT_A, again)
    assert result.outcome is PutOutcome.DUPLICATE
    assert result.record == w


def test_second_differing_start_raises_conflict() -> None:
    store = InMemoryMeasurementWindowStore()
    w = make_window(starts_at="2026-07-14T00:00:00Z")
    store.open_window(TENANT_A, w)
    differing = make_window(starts_at="2026-07-15T00:00:00Z")
    with pytest.raises(IdempotencyConflictError) as excinfo:
        store.open_window(TENANT_A, differing)
    # Original active window is untouched.
    assert store.get_active(TENANT_A, w.experiment_id) == w
    assert excinfo.value.context["experiment_id"] == w.experiment_id


def test_differing_end_or_policy_also_conflicts() -> None:
    store = InMemoryMeasurementWindowStore()
    w = make_window()
    store.open_window(TENANT_A, w)
    with pytest.raises(IdempotencyConflictError):
        store.open_window(TENANT_A, make_window(ends_at="2026-08-01T00:00:00Z"))
    with pytest.raises(IdempotencyConflictError):
        store.open_window(TENANT_A, make_window(policy_version="2.0.0"))


def test_get_active_absent_raises_not_found() -> None:
    store = InMemoryMeasurementWindowStore()
    with pytest.raises(NotFoundError):
        store.get_active(TENANT_A, "exp-none")


def test_cross_tenant_windows_independent() -> None:
    store = InMemoryMeasurementWindowStore()
    a = make_window(tenant_id=TENANT_A, starts_at="2026-07-14T00:00:00Z")
    b = make_window(tenant_id=TENANT_B, starts_at="2026-07-20T00:00:00Z")
    store.open_window(TENANT_A, a)
    store.open_window(TENANT_B, b)
    assert store.get_active(TENANT_A, a.experiment_id) == a
    assert store.get_active(TENANT_B, b.experiment_id) == b


def test_cross_tenant_get_is_non_leaking_absent() -> None:
    store = InMemoryMeasurementWindowStore()
    a = make_window(tenant_id=TENANT_A)
    store.open_window(TENANT_A, a)
    with pytest.raises(NotFoundError):
        store.get_active(TENANT_B, a.experiment_id)


def test_forged_tenant_window_rejected() -> None:
    store = InMemoryMeasurementWindowStore()
    forged = make_window(tenant_id=TENANT_B)
    with pytest.raises(TenantIsolationError):
        store.open_window(TENANT_A, forged)
    with pytest.raises(NotFoundError):
        store.get_active(TENANT_A, forged.experiment_id)


def test_empty_tenant_rejected() -> None:
    store = InMemoryMeasurementWindowStore()
    w = make_window()
    with pytest.raises(ValueError):
        store.open_window("", w)
    with pytest.raises(ValueError):
        store.get_active("", w.experiment_id)
