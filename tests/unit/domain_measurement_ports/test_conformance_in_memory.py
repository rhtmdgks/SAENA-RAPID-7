"""Run the reusable conformance suite against the in-memory reference (w5-09).

`saena_domain.measurement.ports_conformance` exposes abstract
`*ContractTests` classes with an abstract `make_store()` factory. Any adapter
(the in-memory reference here; the Postgres adapter in w5-10) subclasses each
class, implements `make_store()`, and inherits the entire behavioral contract
as real pytest test methods — the SAME assertions run against every backend,
so an adapter that diverges from the reference semantics fails immediately.

This module IS that subclass for the in-memory backend. It also asserts the
`runtime_checkable` Protocol `isinstance` structural conformance of every
in-memory adapter.
"""

from __future__ import annotations

import pytest
from saena_domain.measurement.ports import (
    ConfirmationStore,
    EvidenceBundleStore,
    InMemoryConfirmationStore,
    InMemoryEvidenceBundleStore,
    InMemoryMeasurementWindowStore,
    InMemoryOutcomeDecisionStore,
    MeasurementWindowStore,
    OutcomeDecisionStore,
)
from saena_domain.measurement.ports_conformance import (
    ConfirmationStoreContractTests,
    EvidenceBundleStoreContractTests,
    MeasurementWindowStoreContractTests,
    OutcomeDecisionStoreContractTests,
)


class TestInMemoryConfirmationStore(ConfirmationStoreContractTests):
    def make_store(self) -> ConfirmationStore:
        return InMemoryConfirmationStore()


class TestInMemoryMeasurementWindowStore(MeasurementWindowStoreContractTests):
    def make_store(self) -> MeasurementWindowStore:
        return InMemoryMeasurementWindowStore()


class TestInMemoryOutcomeDecisionStore(OutcomeDecisionStoreContractTests):
    def make_store(self) -> OutcomeDecisionStore:
        return InMemoryOutcomeDecisionStore()


class TestInMemoryEvidenceBundleStore(EvidenceBundleStoreContractTests):
    def make_store(self) -> EvidenceBundleStore:
        return InMemoryEvidenceBundleStore()


def test_in_memory_adapters_satisfy_protocols() -> None:
    assert isinstance(InMemoryConfirmationStore(), ConfirmationStore)
    assert isinstance(InMemoryMeasurementWindowStore(), MeasurementWindowStore)
    assert isinstance(InMemoryOutcomeDecisionStore(), OutcomeDecisionStore)
    assert isinstance(InMemoryEvidenceBundleStore(), EvidenceBundleStore)


@pytest.mark.parametrize(
    "base",
    [
        ConfirmationStoreContractTests,
        MeasurementWindowStoreContractTests,
        OutcomeDecisionStoreContractTests,
        EvidenceBundleStoreContractTests,
    ],
)
def test_base_make_store_is_abstract_contract(base: type) -> None:
    # A subclass that defers to the base `make_store` (instead of returning a
    # real adapter) surfaces the abstract contract's NotImplementedError — this
    # is the guard that a downstream adapter (w5-10) MUST implement `make_store`
    # rather than silently inherit a non-functional one.
    class _Deferring(base):  # type: ignore[valid-type, misc]
        def make_store(self):  # type: ignore[no-untyped-def]
            return super().make_store()

    with pytest.raises(NotImplementedError):
        _Deferring().make_store()
