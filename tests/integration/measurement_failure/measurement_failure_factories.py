"""Shared helpers for `tests/integration/measurement_failure` (w5-20).

Wires the SAME `pipeline_factories` fixture graph
`tests/unit/svc_experiment_attribution_pipeline` uses (registration,
submission, confirmation, DiD signals, policies — see that module's own
docstring) to the REAL Postgres port adapters (w5-10:
`saena_experiment_attribution.persistence.adapter`) instead of the in-memory
reference, so `run_measurement` (w5-13) is exercised end-to-end against a
real database for process-restart rebuild / at-least-once replay / rollback /
conflicting-replay scenarios — the properties only a real backend proves.

## Sync bridge — reused verbatim from `measurement_pg/sync_facade.py`

`run_measurement` (`orchestrator.py`) calls every port method WITHOUT
`await` — it is written against the synchronous `saena_domain.measurement.
ports` Protocol only. The Postgres adapters (`PgConfirmationStore` et al.)
are `async def` (`AsyncEngine`/asyncpg). `tests/integration/measurement_pg/
sync_facade.py` (w5-10) already solved exactly this bridging problem for its
own conformance suite: a thin synchronous facade per store, keyed by a
connection `url` (not a shared `engine`), that drives each call through its
own fresh `asyncio.run` + fresh same-loop-disposed `AsyncEngine` (the
cross-loop asyncpg discipline this whole workspace uses — no
pytest-asyncio plugin is installed). This module reuses that exact facade
family (duplicated, not imported — `measurement_pg` is outside this unit's
exclusive write paths and a bare cross-directory import collides under
pytest's `prepend` import mode, same rationale as every other duplicated
conftest/probe in this codebase) so `run_measurement` can be driven against
the REAL adapters unmodified — this module adds no logic of its own beyond
the sync bridge.

A facade keyed by `url` (rather than a shared `engine`) is also exactly what
"process restart" needs to mean here: each call opens and disposes its OWN
connection, so a `MeasurementPorts` built from a `url` genuinely has no
in-process state to lose between calls — the only durable state is what
actually landed in Postgres.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from pipeline_factories import make_ports as make_in_memory_ports  # noqa: F401 - re-export
from saena_domain.measurement.ports import (
    ConfirmationRecord,
    EvidenceBundle,
    MeasurementWindow,
    OutcomeDecisionRecord,
    PutResult,
)
from saena_experiment_attribution.persistence.adapter import (
    PgConfirmationStore,
    PgEvidenceBundleStore,
    PgMeasurementWindowStore,
    PgOutcomeDecisionStore,
)
from saena_experiment_attribution.pipeline.inputs import MeasurementPorts
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def _run_with_engine(url: str, work: Callable[[AsyncEngine], Awaitable[Any]]) -> Any:
    """Run `work(engine)` in a fresh event loop with a fresh, same-loop-disposed
    engine (the cross-loop asyncpg guard; see module docstring)."""

    async def _do() -> Any:
        engine = create_async_engine(url)
        try:
            return await work(engine)
        finally:
            await engine.dispose()

    return asyncio.run(_do())


class SyncPgConfirmationStore:
    def __init__(self, url: str) -> None:
        self._url = url

    def put_confirmation(self, tenant_id: str, key: str, record: ConfirmationRecord) -> PutResult:
        return _run_with_engine(
            self._url, lambda e: PgConfirmationStore(e).put_confirmation(tenant_id, key, record)
        )

    def get(self, tenant_id: str, key: str) -> ConfirmationRecord:
        return _run_with_engine(self._url, lambda e: PgConfirmationStore(e).get(tenant_id, key))


class SyncPgMeasurementWindowStore:
    def __init__(self, url: str) -> None:
        self._url = url

    def open_window(self, tenant_id: str, window: MeasurementWindow) -> PutResult:
        return _run_with_engine(
            self._url, lambda e: PgMeasurementWindowStore(e).open_window(tenant_id, window)
        )

    def get_active(self, tenant_id: str, experiment_id: str) -> MeasurementWindow:
        return _run_with_engine(
            self._url, lambda e: PgMeasurementWindowStore(e).get_active(tenant_id, experiment_id)
        )


class SyncPgOutcomeDecisionStore:
    def __init__(self, url: str) -> None:
        self._url = url

    def append_decision(self, tenant_id: str, decision: OutcomeDecisionRecord) -> PutResult:
        return _run_with_engine(
            self._url, lambda e: PgOutcomeDecisionStore(e).append_decision(tenant_id, decision)
        )

    def get(self, tenant_id: str, decision_key: tuple[str, str]) -> OutcomeDecisionRecord:
        return _run_with_engine(
            self._url, lambda e: PgOutcomeDecisionStore(e).get(tenant_id, decision_key)
        )

    def list_decisions(self, tenant_id: str) -> tuple[OutcomeDecisionRecord, ...]:
        return _run_with_engine(
            self._url, lambda e: PgOutcomeDecisionStore(e).list_decisions(tenant_id)
        )


class SyncPgEvidenceBundleStore:
    def __init__(self, url: str) -> None:
        self._url = url

    def put(self, tenant_id: str, manifest_hash: str, bundle: EvidenceBundle) -> PutResult:
        return _run_with_engine(
            self._url, lambda e: PgEvidenceBundleStore(e).put(tenant_id, manifest_hash, bundle)
        )

    def get(self, tenant_id: str, manifest_hash: str) -> EvidenceBundle:
        return _run_with_engine(
            self._url, lambda e: PgEvidenceBundleStore(e).get(tenant_id, manifest_hash)
        )


def make_pg_ports(url: str) -> MeasurementPorts:
    """Build a `MeasurementPorts` backed by the REAL Postgres adapters over
    `url` — the same four-store shape `pipeline_factories.make_ports`
    returns for the in-memory reference, so `run_measurement` accepts either
    interchangeably (Protocol-typed ports, per `pipeline/inputs.py`). Each
    store call opens its OWN fresh connection (see module docstring) — a
    fresh `make_pg_ports(url)` object is therefore indistinguishable, from
    `run_measurement`'s point of view, from "the service process restarted
    and reconnected".
    """
    return MeasurementPorts(
        confirmation_store=SyncPgConfirmationStore(url),
        window_store=SyncPgMeasurementWindowStore(url),
        decision_store=SyncPgOutcomeDecisionStore(url),
        evidence_store=SyncPgEvidenceBundleStore(url),
    )


__all__ = [
    "SyncPgConfirmationStore",
    "SyncPgEvidenceBundleStore",
    "SyncPgMeasurementWindowStore",
    "SyncPgOutcomeDecisionStore",
    "make_in_memory_ports",
    "make_pg_ports",
]
