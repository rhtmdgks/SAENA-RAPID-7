"""Real-Postgres durability/concurrency/integrity semantics (w5-10, E8/E9).

Beyond the shared conformance suite (`test_conformance_postgres.py`), these
prove the properties that only a REAL database can exercise:

- concurrent-writer race → exactly one STORED winner, the loser DUPLICATE (same
  content) or a fail-closed conflict (different content) — never two winners,
  never a silent overwrite;
- at-least-once replay → the same write applied twice is one row;
- restart → a brand-new connection/engine sees byte-identical state;
- transaction rollback leaves NO trace (no half-written/phantom row);
- cross-tenant isolation on real rows (non-leaking absent);
- append-only enforced at the DB level (the trigger denies UPDATE/DELETE even by
  direct SQL, not merely by the port lacking an update method);
- SF-4 → a manifest tampered DIRECTLY in the row fails re-verification on read.

Every test drives its own `asyncio.run(scenario())` (no pytest-asyncio); the
`engine` fixture is a fresh per-test engine, and scenarios that need a SECOND
independent connection (the concurrency race) create their own inside the same
loop.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from saena_domain.measurement import evidence  # noqa: E402
from saena_domain.measurement.errors import (  # noqa: E402
    IdempotencyConflictError,
    NotFoundError,
)
from saena_domain.measurement.ports import (  # noqa: E402
    ConfirmationRecord,
    EvidenceBundle,
    OutcomeDecisionRecord,
    PutOutcome,
)
from saena_experiment_attribution.persistence import fingerprint as fp  # noqa: E402
from saena_experiment_attribution.persistence import mapping, tables  # noqa: E402
from saena_experiment_attribution.persistence.adapter import (  # noqa: E402
    PgConfirmationStore,
    PgEvidenceBundleStore,
    PgOutcomeDecisionStore,
)

pytestmark = pytest.mark.integration

_TENANT_A = "acme-co"
_TENANT_B = "globex-co"


def _confirmation(
    tenant: str = _TENANT_A, key: str = "k-1", **payload: object
) -> ConfirmationRecord:
    return ConfirmationRecord(
        tenant_id=tenant,
        confirmation_key=key,
        measurement_kind="citation_confirmation",
        payload=dict(payload) or {"v": 1},
    )


# --- concurrent-writer race --------------------------------------------------------


def test_concurrent_same_key_identical_one_stored_one_duplicate(engine, run) -> None:  # type: ignore[no-untyped-def]
    """Two connections race the SAME key with IDENTICAL content: exactly one
    reports STORED, the other DUPLICATE (never two STORED, never a conflict)."""

    async def scenario() -> None:
        url = engine.url.render_as_string(hide_password=False)
        rec = _confirmation(key="race-identical", v=1)
        e1 = create_async_engine(url)
        e2 = create_async_engine(url)
        try:
            r1, r2 = await asyncio.gather(
                PgConfirmationStore(e1).put_confirmation(_TENANT_A, rec.confirmation_key, rec),
                PgConfirmationStore(e2).put_confirmation(_TENANT_A, rec.confirmation_key, rec),
            )
        finally:
            await e1.dispose()
            await e2.dispose()
        outcomes = sorted([r1.outcome, r2.outcome], key=lambda o: o.value)
        assert outcomes == [PutOutcome.DUPLICATE, PutOutcome.STORED]

    run(scenario())


def test_concurrent_same_key_different_content_one_stored_one_conflict(engine, run) -> None:  # type: ignore[no-untyped-def]
    """Two connections race the SAME key with DIFFERENT content: one STORED, the
    other a fail-closed IdempotencyConflictError — never a silent overwrite. The
    stored content is the winner's, whichever won."""

    async def scenario() -> None:
        url = engine.url.render_as_string(hide_password=False)
        a = _confirmation(key="race-diff", v=1)
        b = _confirmation(key="race-diff", v=2)
        e1 = create_async_engine(url)
        e2 = create_async_engine(url)
        try:
            results = await asyncio.gather(
                PgConfirmationStore(e1).put_confirmation(_TENANT_A, a.confirmation_key, a),
                PgConfirmationStore(e2).put_confirmation(_TENANT_A, b.confirmation_key, b),
                return_exceptions=True,
            )
        finally:
            await e1.dispose()
            await e2.dispose()
        stored = [r for r in results if not isinstance(r, BaseException)]
        conflicts = [r for r in results if isinstance(r, IdempotencyConflictError)]
        assert len(stored) == 1 and len(conflicts) == 1
        assert stored[0].outcome is PutOutcome.STORED

        # The stored row is exactly the winner's content — never overwritten.
        e3 = create_async_engine(url)
        try:
            got = await PgConfirmationStore(e3).get(_TENANT_A, "race-diff")
        finally:
            await e3.dispose()
        assert got == stored[0].record

    run(scenario())


# --- at-least-once replay ----------------------------------------------------------


def test_at_least_once_replay_is_single_row(engine, run) -> None:  # type: ignore[no-untyped-def]
    async def scenario() -> None:
        store = PgConfirmationStore(engine)
        rec = _confirmation(key="replay", v=7)
        for _ in range(5):  # at-least-once delivery replays the same event
            await store.put_confirmation(_TENANT_A, rec.confirmation_key, rec)
        # Exactly one physical row.
        async with engine.connect() as conn:
            ctable = tables.qualified_table(tables.CONFIRMATIONS_TABLE)
            count = (
                await conn.execute(
                    text(
                        f"SELECT count(*) FROM {ctable} "
                        "WHERE tenant_id = :t AND confirmation_key = :k"
                    ),
                    {"t": _TENANT_A, "k": "replay"},
                )
            ).scalar_one()
        assert count == 1

    run(scenario())


# --- restart: new connection sees identical state ----------------------------------


def test_restart_new_engine_sees_identical_state(engine, run) -> None:  # type: ignore[no-untyped-def]
    async def scenario() -> None:
        rec = _confirmation(key="durable", v=42)
        await PgConfirmationStore(engine).put_confirmation(_TENANT_A, rec.confirmation_key, rec)
        # "Restart": a brand-new engine (new pool, as a process restart would
        # produce) reads the persisted state back byte-identically.
        url = engine.url.render_as_string(hide_password=False)
        fresh = create_async_engine(url)
        try:
            got = await PgConfirmationStore(fresh).get(_TENANT_A, "durable")
        finally:
            await fresh.dispose()
        assert got == rec

    run(scenario())


# --- transaction rollback leaves no trace ------------------------------------------


def test_failed_write_rolls_back_leaving_no_trace(engine, run) -> None:  # type: ignore[no-untyped-def]
    """A conflicting write raises and MUST leave the store exactly as it was —
    no half-written row, no phantom key, no fingerprint drift."""

    async def scenario() -> None:
        store = PgConfirmationStore(engine)
        first = _confirmation(key="rollback", v=1)
        await store.put_confirmation(_TENANT_A, first.confirmation_key, first)
        with pytest.raises(IdempotencyConflictError):
            await store.put_confirmation(
                _TENANT_A, "rollback", _confirmation(key="rollback", v=999)
            )
        # Still exactly the first content, still exactly one row.
        got = await store.get(_TENANT_A, "rollback")
        assert got == first
        async with engine.connect() as conn:
            ctable = tables.qualified_table(tables.CONFIRMATIONS_TABLE)
            count = (
                await conn.execute(
                    text(
                        f"SELECT count(*) FROM {ctable} "
                        "WHERE tenant_id = :t AND confirmation_key = :k"
                    ),
                    {"t": _TENANT_A, "k": "rollback"},
                )
            ).scalar_one()
        assert count == 1

    run(scenario())


# --- cross-tenant isolation on real rows -------------------------------------------


def test_cross_tenant_non_leaking_absent(engine, run) -> None:  # type: ignore[no-untyped-def]
    async def scenario() -> None:
        store = PgConfirmationStore(engine)
        a = _confirmation(_TENANT_A, key="shared-key", v="a")
        b = _confirmation(_TENANT_B, key="shared-key", v="b")
        await store.put_confirmation(_TENANT_A, "shared-key", a)
        await store.put_confirmation(_TENANT_B, "shared-key", b)
        assert await store.get(_TENANT_A, "shared-key") == a
        assert await store.get(_TENANT_B, "shared-key") == b
        # A third tenant asking for the same key sees a non-leaking absent.
        with pytest.raises(NotFoundError):
            await store.get("intruder-co", "shared-key")

    run(scenario())


# --- append-only enforced at the DB level ------------------------------------------


def test_append_only_trigger_denies_direct_update_and_delete(engine, run) -> None:  # type: ignore[no-untyped-def]
    """The append-only invariant is enforced by a DB trigger, not merely by the
    port lacking an update method — a DIRECT SQL UPDATE/DELETE is refused."""

    async def scenario() -> None:
        store = PgOutcomeDecisionStore(engine)
        d = OutcomeDecisionRecord(
            tenant_id=_TENANT_A,
            decision_key=("exp-1", "primary"),
            outcome="lift_confirmed",
            evidence_bundle_ref="sha256:" + "e" * 64,
            policy_metadata={"policy_version": "1.0.0"},
        )
        await store.append_decision(_TENANT_A, d)
        dtable = tables.qualified_table(tables.DECISIONS_TABLE)
        async with engine.begin() as conn:
            with pytest.raises(Exception) as update_exc:
                await conn.execute(text(f"UPDATE {dtable} SET outcome = 'no_lift'"))
            assert "append-only" in str(update_exc.value)
        async with engine.begin() as conn:
            with pytest.raises(Exception) as delete_exc:
                await conn.execute(text(f"DELETE FROM {dtable}"))
            assert "append-only" in str(delete_exc.value)
        # Row still intact.
        assert (await store.get(_TENANT_A, ("exp-1", "primary"))).outcome == "lift_confirmed"

    run(scenario())


# --- SF-4: manifest tampered directly in the row fails re-verification on read -----


def _sealed_bundle() -> tuple[str, EvidenceBundle, dict]:
    entry = evidence.EvidenceEntry(
        kind=evidence.EvidenceKind.REGISTRATION,
        ref=evidence.EvidenceRef(uri="artifact://reg", content_hash="sha256:" + "a" * 64),
    )
    manifest = evidence.EvidenceBundleManifest.seal(
        tenant_id=_TENANT_A, run_id="run-1", experiment_id="exp-1", entries=(entry,)
    )
    manifest_dict = manifest.model_dump(mode="json")
    manifest_hash = "sha256:" + "d" * 64  # content address the row is keyed by
    bundle = EvidenceBundle(tenant_id=_TENANT_A, manifest=manifest_dict)
    return manifest_hash, bundle, manifest_dict


def test_sf4_intact_bundle_reads_back(engine, run) -> None:  # type: ignore[no-untyped-def]
    async def scenario() -> None:
        store = PgEvidenceBundleStore(engine)
        manifest_hash, bundle, manifest_dict = _sealed_bundle()
        await store.put(_TENANT_A, manifest_hash, bundle)
        got = await store.get(_TENANT_A, manifest_hash)
        assert got.manifest["manifest_hash"] == manifest_dict["manifest_hash"]

    run(scenario())


def test_sf4_row_tampered_manifest_read_raises(engine, run) -> None:  # type: ignore[no-untyped-def]
    """A manifest tampered DIRECTLY in the row (a malicious/corrupt DB write,
    bypassing the adapter) must be caught by re-verification on read — never
    handed back as a valid bundle."""

    async def scenario() -> None:
        store = PgEvidenceBundleStore(engine)
        manifest_hash, bundle, manifest_dict = _sealed_bundle()
        await store.put(_TENANT_A, manifest_hash, bundle)

        # Tamper the stored JSONB manifest content WITHOUT recomputing its
        # sealed commitment chain — directly, as a DBA/corruption would.
        tampered = json.loads(json.dumps(manifest_dict))
        tampered["entries"][0]["ref"]["uri"] = "artifact://SWAPPED"
        etable = tables.qualified_table(tables.EVIDENCE_TABLE)
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    f"UPDATE {etable} SET manifest = CAST(:m AS jsonb) "
                    "WHERE tenant_id = :t AND manifest_hash = :h"
                ),
                {"m": json.dumps(tampered), "t": _TENANT_A, "h": manifest_hash},
            )

        with pytest.raises(mapping.EvidenceIntegrityError):
            await store.get(_TENANT_A, manifest_hash)

    run(scenario())


def test_fingerprint_column_matches_stored_content(engine, run) -> None:  # type: ignore[no-untyped-def]
    """The persisted content_fingerprint equals the pure helper's fingerprint —
    proving the read-back-compare is against a faithful column."""

    async def scenario() -> None:
        rec = _confirmation(key="fp-check", v=5)
        await PgConfirmationStore(engine).put_confirmation(_TENANT_A, rec.confirmation_key, rec)
        expected = fp.confirmation_fingerprint(
            tenant_id=_TENANT_A,
            confirmation_key="fp-check",
            measurement_kind=rec.measurement_kind,
            payload=mapping._thaw(rec.payload),
        )
        async with engine.connect() as conn:
            stored_fp = (
                await conn.execute(
                    text(
                        "SELECT content_fingerprint FROM "
                        f"{tables.qualified_table(tables.CONFIRMATIONS_TABLE)} "
                        "WHERE tenant_id = :t AND confirmation_key = :k"
                    ),
                    {"t": _TENANT_A, "k": "fp-check"},
                )
            ).scalar_one()
        assert stored_fp == expected

    run(scenario())
