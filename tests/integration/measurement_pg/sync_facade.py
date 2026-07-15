"""Synchronous facades over the async Pg measurement stores (w5-10 integration).

The reusable conformance suite (`saena_domain.measurement.ports_conformance`)
is written against the SYNCHRONOUS port surface — its `test_*` methods call
`store.put_confirmation(...)` / `store.get(...)` directly and assert on the
result, with no `await`. The in-memory reference is synchronous, so it satisfies
that suite as-is. The Postgres adapter is ASYNC (`AsyncEngine`/asyncpg), so to
hold it to the exact same suite we wrap each async method in a thin synchronous
facade that drives it via `asyncio.run` — one fresh event loop per call, matching
this workspace's no-pytest-asyncio, `asyncio.run(scenario())`-per-test
discipline (see `tests/integration/persistence_postgres/conftest.py`).

Cross-loop asyncpg discipline: each facade CALL is its own `asyncio.run` (its
own event loop), and a single conformance test method makes SEVERAL such calls
against the same logical store. An `asyncpg` connection is bound to the loop it
was created on and cannot be reused across a different loop, so the facade
creates a FRESH `AsyncEngine` from the shared `url` INSIDE each call and
disposes it in the SAME loop (`_run_with_engine`) — no engine/connection ever
straddles two `asyncio.run` calls. The container/schema is shared (session
fixture); only the cheap in-process engine object is per-call. This is the
same fresh-engine-per-async-unit rule the persistence suite documents, applied
at method granularity because the conformance suite (not this module) owns the
call sequencing.

Each facade forwards to the real async adapter unchanged — same SQL, same
idempotency/append-only/tenant semantics, same exceptions — so a green
conformance run here is a green run of the REAL Postgres behavior, not of a
reimplementation. The facades add no logic of their own beyond the sync bridge.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

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
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def _run_with_engine(url: str, work: Callable[[AsyncEngine], Awaitable[Any]]) -> Any:
    """Run `work(engine)` in a fresh event loop with a fresh, same-loop-disposed
    engine — the cross-loop asyncpg guard (see module docstring)."""

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


__all__ = [
    "SyncPgConfirmationStore",
    "SyncPgEvidenceBundleStore",
    "SyncPgMeasurementWindowStore",
    "SyncPgOutcomeDecisionStore",
]
