"""Reusable, pytest-importable conformance suite for the measurement ports (w5-09).

Each `*ContractTests` class is an ABSTRACT test suite: it declares an abstract
`make_store()` factory and a full set of behavioral `test_*` methods written
against the PORT (never a concrete adapter). Any adapter proves its conformance
by subclassing the relevant class in a pytest-collected module and implementing
`make_store()` — the inherited `test_*` methods then run as real tests against
that adapter. The in-memory reference does this in
`tests/unit/domain_measurement_ports/test_conformance_in_memory.py`; the
Postgres adapter (w5-10) imports these SAME classes and subclasses them against
its own factory, so both backends are held to byte-for-byte identical
semantics — a divergence in either fails the shared contract immediately.

Design notes:

- Lives in the shipped package (not the test tree) precisely so a DIFFERENT
  package's test suite (w5-10) can `from saena_domain.measurement.
  ports_conformance import ...` without depending on this repo's `tests/`
  layout. This is an explicitly-allowed exclusive path for w5-09.
- Class names start with `Test` and carry no `__init__`, so pytest collects a
  subclass's inherited methods directly. The base classes themselves define an
  abstract `make_store` that raises, so pytest instantiating a base class (if
  it ever tried) collects methods that all error out via `make_store` — but
  because the bases are `abc.ABC` with an abstractmethod, they cannot be
  instantiated at all, so pytest reports no spurious base-class runs (verified
  by the in-memory driver being the only place tests actually execute).
- Records are built by small inline helpers here (not the test-tree factories)
  so the suite is self-contained for any importing package.
"""

from __future__ import annotations

import abc
from typing import Any

import pytest

from saena_domain.measurement.errors import (
    AppendOnlyViolationError,
    EvidenceHashMismatchError,
    IdempotencyConflictError,
    NotFoundError,
    TenantIsolationError,
)
from saena_domain.measurement.ports import (
    ConfirmationRecord,
    ConfirmationStore,
    EvidenceBundle,
    EvidenceBundleStore,
    MeasurementWindow,
    MeasurementWindowStore,
    OutcomeDecisionRecord,
    OutcomeDecisionStore,
    PutOutcome,
)

_TENANT_A = "acme-co"
_TENANT_B = "globex-co"
_HASH = "sha256:" + "e" * 64


def _confirmation(tenant: str = _TENANT_A, **overrides: Any) -> ConfirmationRecord:
    base: dict[str, Any] = {
        "tenant_id": tenant,
        "confirmation_key": "acme-co:run-0007:capsule-042",
        "measurement_kind": "citation_confirmation",
        "payload": {"citation_id": "cit-042"},
    }
    base.update(overrides)
    return ConfirmationRecord(**base)


def _window(tenant: str = _TENANT_A, **overrides: Any) -> MeasurementWindow:
    base: dict[str, Any] = {
        "tenant_id": tenant,
        "experiment_id": "exp-042",
        "starts_at": "2026-07-14T00:00:00Z",
        "ends_at": None,
        "policy_version": "1.0.0",
    }
    base.update(overrides)
    return MeasurementWindow(**base)


def _decision(tenant: str = _TENANT_A, **overrides: Any) -> OutcomeDecisionRecord:
    base: dict[str, Any] = {
        "tenant_id": tenant,
        "decision_key": ("exp-042", "primary"),
        "outcome": "lift_confirmed",
        "evidence_bundle_ref": _HASH,
        "policy_metadata": {"policy_version": "1.0.0"},
    }
    base.update(overrides)
    return OutcomeDecisionRecord(**base)


def _bundle(tenant: str = _TENANT_A, **overrides: Any) -> EvidenceBundle:
    base: dict[str, Any] = {"tenant_id": tenant, "manifest": {"artifacts": ["x"], "count": 1}}
    base.update(overrides)
    return EvidenceBundle(**base)


# --- ConfirmationStore -------------------------------------------------------------


class ConfirmationStoreContractTests(abc.ABC):
    """Behavioral contract every `ConfirmationStore` adapter must satisfy."""

    @abc.abstractmethod
    def make_store(self) -> ConfirmationStore:
        """Return a fresh, empty adapter under test."""
        raise NotImplementedError

    def test_absent_is_stored(self) -> None:
        store = self.make_store()
        rec = _confirmation()
        result = store.put_confirmation(_TENANT_A, rec.confirmation_key, rec)
        assert result.outcome is PutOutcome.STORED
        assert store.get(_TENANT_A, rec.confirmation_key) == rec

    def test_identical_replay_is_duplicate_noop(self) -> None:
        store = self.make_store()
        rec = _confirmation()
        store.put_confirmation(_TENANT_A, rec.confirmation_key, rec)
        result = store.put_confirmation(_TENANT_A, rec.confirmation_key, _confirmation())
        assert result.outcome is PutOutcome.DUPLICATE
        assert result.record == rec

    def test_different_content_conflicts_without_overwrite(self) -> None:
        store = self.make_store()
        rec = _confirmation(payload={"v": 1})
        store.put_confirmation(_TENANT_A, rec.confirmation_key, rec)
        with pytest.raises(IdempotencyConflictError):
            store.put_confirmation(_TENANT_A, rec.confirmation_key, _confirmation(payload={"v": 2}))
        assert store.get(_TENANT_A, rec.confirmation_key) == rec

    def test_get_absent_raises_not_found(self) -> None:
        store = self.make_store()
        with pytest.raises(NotFoundError):
            store.get(_TENANT_A, "nope")

    def test_cross_tenant_independent_and_non_leaking(self) -> None:
        store = self.make_store()
        a = _confirmation(_TENANT_A, payload={"o": "a"})
        b = _confirmation(_TENANT_B, payload={"o": "b"})
        store.put_confirmation(_TENANT_A, a.confirmation_key, a)
        store.put_confirmation(_TENANT_B, b.confirmation_key, b)
        assert store.get(_TENANT_A, a.confirmation_key) == a
        assert store.get(_TENANT_B, b.confirmation_key) == b
        # Tenant B never sees A's differing payload as a conflict.

    def test_forged_tenant_rejected(self) -> None:
        store = self.make_store()
        forged = _confirmation(_TENANT_B)
        with pytest.raises(TenantIsolationError):
            store.put_confirmation(_TENANT_A, forged.confirmation_key, forged)
        with pytest.raises(NotFoundError):
            store.get(_TENANT_A, forged.confirmation_key)

    def test_empty_tenant_rejected(self) -> None:
        store = self.make_store()
        rec = _confirmation()
        with pytest.raises(ValueError):
            store.put_confirmation("", rec.confirmation_key, rec)


# --- MeasurementWindowStore --------------------------------------------------------


class MeasurementWindowStoreContractTests(abc.ABC):
    """Behavioral contract every `MeasurementWindowStore` adapter must satisfy."""

    @abc.abstractmethod
    def make_store(self) -> MeasurementWindowStore:
        raise NotImplementedError

    def test_open_absent_is_stored(self) -> None:
        store = self.make_store()
        w = _window()
        assert store.open_window(_TENANT_A, w).outcome is PutOutcome.STORED
        assert store.get_active(_TENANT_A, w.experiment_id) == w

    def test_identical_reopen_is_duplicate(self) -> None:
        store = self.make_store()
        w = _window()
        store.open_window(_TENANT_A, w)
        assert store.open_window(_TENANT_A, _window()).outcome is PutOutcome.DUPLICATE

    def test_differing_start_conflicts(self) -> None:
        store = self.make_store()
        store.open_window(_TENANT_A, _window(starts_at="2026-07-14T00:00:00Z"))
        with pytest.raises(IdempotencyConflictError):
            store.open_window(_TENANT_A, _window(starts_at="2026-07-15T00:00:00Z"))

    def test_get_absent_raises_not_found(self) -> None:
        store = self.make_store()
        with pytest.raises(NotFoundError):
            store.get_active(_TENANT_A, "exp-none")

    def test_cross_tenant_independent(self) -> None:
        store = self.make_store()
        a = _window(_TENANT_A, starts_at="2026-07-14T00:00:00Z")
        b = _window(_TENANT_B, starts_at="2026-07-20T00:00:00Z")
        store.open_window(_TENANT_A, a)
        store.open_window(_TENANT_B, b)
        assert store.get_active(_TENANT_A, a.experiment_id) == a
        assert store.get_active(_TENANT_B, b.experiment_id) == b

    def test_forged_tenant_rejected(self) -> None:
        store = self.make_store()
        with pytest.raises(TenantIsolationError):
            store.open_window(_TENANT_A, _window(_TENANT_B))

    def test_empty_tenant_rejected(self) -> None:
        store = self.make_store()
        with pytest.raises(ValueError):
            store.open_window("", _window())


# --- OutcomeDecisionStore ----------------------------------------------------------


class OutcomeDecisionStoreContractTests(abc.ABC):
    """Behavioral contract every `OutcomeDecisionStore` adapter must satisfy."""

    @abc.abstractmethod
    def make_store(self) -> OutcomeDecisionStore:
        raise NotImplementedError

    def test_append_absent_is_stored(self) -> None:
        store = self.make_store()
        d = _decision()
        assert store.append_decision(_TENANT_A, d).outcome is PutOutcome.STORED
        assert store.get(_TENANT_A, d.decision_key) == d

    def test_identical_replay_is_duplicate(self) -> None:
        store = self.make_store()
        d = _decision()
        store.append_decision(_TENANT_A, d)
        assert store.append_decision(_TENANT_A, _decision()).outcome is PutOutcome.DUPLICATE

    def test_overwrite_raises_append_only_violation(self) -> None:
        store = self.make_store()
        store.append_decision(_TENANT_A, _decision(outcome="lift_confirmed"))
        with pytest.raises(AppendOnlyViolationError):
            store.append_decision(_TENANT_A, _decision(outcome="no_lift"))
        assert store.get(_TENANT_A, ("exp-042", "primary")).outcome == "lift_confirmed"

    def test_list_in_append_order(self) -> None:
        store = self.make_store()
        d1 = _decision(decision_key=("exp-1", "primary"))
        d2 = _decision(decision_key=("exp-1", "secondary"))
        store.append_decision(_TENANT_A, d1)
        store.append_decision(_TENANT_A, d2)
        assert store.list_decisions(_TENANT_A) == (d1, d2)

    def test_get_absent_raises_not_found(self) -> None:
        store = self.make_store()
        with pytest.raises(NotFoundError):
            store.get(_TENANT_A, ("exp-x", "primary"))

    def test_cross_tenant_independent(self) -> None:
        store = self.make_store()
        a = _decision(_TENANT_A, outcome="lift_confirmed")
        b = _decision(_TENANT_B, outcome="no_lift")
        store.append_decision(_TENANT_A, a)
        store.append_decision(_TENANT_B, b)
        assert store.get(_TENANT_A, a.decision_key) == a
        assert store.get(_TENANT_B, b.decision_key) == b

    def test_forged_tenant_rejected(self) -> None:
        store = self.make_store()
        with pytest.raises(TenantIsolationError):
            store.append_decision(_TENANT_A, _decision(_TENANT_B))

    def test_empty_tenant_rejected(self) -> None:
        store = self.make_store()
        with pytest.raises(ValueError):
            store.list_decisions("")


# --- EvidenceBundleStore -----------------------------------------------------------


class EvidenceBundleStoreContractTests(abc.ABC):
    """Behavioral contract every `EvidenceBundleStore` adapter must satisfy."""

    @abc.abstractmethod
    def make_store(self) -> EvidenceBundleStore:
        raise NotImplementedError

    def test_put_absent_is_stored(self) -> None:
        store = self.make_store()
        b = _bundle()
        assert store.put(_TENANT_A, _HASH, b).outcome is PutOutcome.STORED
        assert store.get(_TENANT_A, _HASH) == b

    def test_identical_content_replay_is_duplicate(self) -> None:
        store = self.make_store()
        store.put(_TENANT_A, _HASH, _bundle())
        assert store.put(_TENANT_A, _HASH, _bundle()).outcome is PutOutcome.DUPLICATE

    def test_same_hash_different_content_raises_mismatch(self) -> None:
        store = self.make_store()
        original = _bundle(manifest={"artifacts": ["x"], "count": 1})
        store.put(_TENANT_A, _HASH, original)
        with pytest.raises(EvidenceHashMismatchError):
            store.put(_TENANT_A, _HASH, _bundle(manifest={"artifacts": ["y"], "count": 2}))
        assert store.get(_TENANT_A, _HASH) == original

    def test_get_absent_raises_not_found(self) -> None:
        store = self.make_store()
        with pytest.raises(NotFoundError):
            store.get(_TENANT_A, "sha256:" + "0" * 64)

    def test_cross_tenant_same_hash_independent(self) -> None:
        store = self.make_store()
        a = _bundle(_TENANT_A, manifest={"o": "a"})
        b = _bundle(_TENANT_B, manifest={"o": "b"})
        store.put(_TENANT_A, _HASH, a)
        store.put(_TENANT_B, _HASH, b)
        assert store.get(_TENANT_A, _HASH) == a
        assert store.get(_TENANT_B, _HASH) == b

    def test_forged_tenant_rejected(self) -> None:
        store = self.make_store()
        with pytest.raises(TenantIsolationError):
            store.put(_TENANT_A, _HASH, _bundle(_TENANT_B))

    def test_empty_tenant_rejected(self) -> None:
        store = self.make_store()
        with pytest.raises(ValueError):
            store.put("", _HASH, _bundle())


__all__ = [
    "ConfirmationStoreContractTests",
    "EvidenceBundleStoreContractTests",
    "MeasurementWindowStoreContractTests",
    "OutcomeDecisionStoreContractTests",
]
