"""Run the SHARED conformance suite against the REAL Postgres adapter (w5-10, E9).

This is the w5-10 half of the promise `saena_domain.measurement.ports_conformance`
was built for: the Postgres adapter subclasses the SAME abstract
`*ContractTests` classes the in-memory reference does (w5-09,
`tests/unit/domain_measurement_ports/test_conformance_in_memory.py`) and inherits
every behavioral `test_*` method — so the exact same absent/duplicate/conflict/
append-only/tenant-isolation assertions run against real PostgreSQL. A divergence
between the two backends fails the shared contract immediately (mock-only E2E is
forbidden — wave5-plan E9).

Each test gets a clean database: an autouse fixture TRUNCATEs every owned table
before the test's `make_store()` hands back a store bound to the session
container's URL (the sync facade builds a fresh, same-loop engine per call — see
`sync_facade` module docstring). Honest-skip when Docker is absent (conftest).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from saena_domain.measurement.ports_conformance import (  # noqa: E402
    ConfirmationStoreContractTests,
    EvidenceBundleStoreContractTests,
    MeasurementWindowStoreContractTests,
    OutcomeDecisionStoreContractTests,
)
from saena_experiment_attribution.persistence import adapter  # noqa: E402
from sync_facade import (  # noqa: E402
    SyncPgConfirmationStore,
    SyncPgEvidenceBundleStore,
    SyncPgMeasurementWindowStore,
    SyncPgOutcomeDecisionStore,
)

pytestmark = pytest.mark.integration


class _CleanDbMixin:
    """Bind the session container URL to the instance and TRUNCATE before each
    test, so every inherited conformance method starts from an empty database."""

    @pytest.fixture(autouse=True)
    def _clean(self, postgres_url: str, run) -> None:  # type: ignore[no-untyped-def]
        async def _do() -> None:
            engine = create_async_engine(postgres_url)
            try:
                await adapter.truncate_all(engine)
            finally:
                await engine.dispose()

        run(_do())
        self._url = postgres_url


class TestPgConfirmationStore(_CleanDbMixin, ConfirmationStoreContractTests):
    def make_store(self) -> SyncPgConfirmationStore:
        return SyncPgConfirmationStore(self._url)


class TestPgMeasurementWindowStore(_CleanDbMixin, MeasurementWindowStoreContractTests):
    def make_store(self) -> SyncPgMeasurementWindowStore:
        return SyncPgMeasurementWindowStore(self._url)


class TestPgOutcomeDecisionStore(_CleanDbMixin, OutcomeDecisionStoreContractTests):
    def make_store(self) -> SyncPgOutcomeDecisionStore:
        return SyncPgOutcomeDecisionStore(self._url)


class TestPgEvidenceBundleStore(_CleanDbMixin, EvidenceBundleStoreContractTests):
    def make_store(self) -> SyncPgEvidenceBundleStore:
        return SyncPgEvidenceBundleStore(self._url)
