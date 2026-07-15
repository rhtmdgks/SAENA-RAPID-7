"""Postgres implementations of the four measurement ports (w5-10) — REAL DRIVER.

Every class/function here is marked `# pragma: no cover` — the per-class pragma
markers are the CURRENT, self-sufficient mechanism keeping this real-driver
code out of the blocking unit-lane coverage ratchet. A root `pyproject.toml`
`[tool.coverage.run].omit` entry for this file does NOT exist yet: root
pyproject is Integrator-exclusive, so that registration happens at merge time
(Integrator-owned), matching the documented w2-13 persistence-adapter + w4-07
pgvector precedent entries already in that omit list. Rationale for the
exclusion either way: this code is MEANINGFULLY exercisable only against a live
PostgreSQL connection — a mock engine would test the mock, not the
SQL/idempotency/append-only behavior this module emits. Its behavior is proven
by the real-container conformance lane `tests/integration/measurement_pg/**`
(the SAME `saena_domain.measurement.ports_conformance` suite the in-memory
reference passes), which runs its OWN coverage measurement.

The PURE logic these adapters compose — SQL builders (`tables`), fingerprints
(`fingerprint`), record/row mapping + SF-4 re-verification (`mapping`) — is
unit-tested WITHOUT a database in `tests/unit/svc_experiment_attribution_persistence/**`.

## Idempotency (INSERT ... ON CONFLICT DO NOTHING + read-back-compare)

Each write:
  1. computes the incoming `content_fingerprint`;
  2. runs `INSERT ... ON CONFLICT (<key>) DO NOTHING RETURNING ...`;
  3. if a row came back → the INSERT landed → `PutResult(STORED, incoming)`;
  4. if nothing came back → the key was already present → read the stored row
     + its `content_fingerprint`; identical → `PutResult(DUPLICATE, stored)`;
     different → the port's fail-closed conflict error (never an overwrite).

The stored content is the FIRST accepted content, always. Step 2's
`ON CONFLICT DO NOTHING` is the concurrency serialization point: two
connections racing the same brand-new key both attempt the INSERT, Postgres's
unique/primary-key constraint admits exactly one, the loser gets no RETURNING
row and falls into step 4 — one `STORED` winner, one `DUPLICATE`-or-conflict
loser, with no advisory lock needed (the constraint IS the lock).

## Tenant isolation

`tenant_id` is the leading key column of every table, so a read under a
different tenant simply finds nothing (a non-leaking `NotFoundError`). A record
whose OWN embedded `tenant_id` disagrees with the caller-supplied `tenant_id`
(a forged tenant id) is rejected by `_ensure_caller_owns` BEFORE any statement
runs.

## Atomicity / no partial state

Each write runs inside ONE `engine.begin()` transaction. A statement that
raises (conflict error, append-only trigger, constraint) rolls the whole
transaction back — no half-written row, no phantom key. The read-back on the
conflict path runs on the SAME connection/transaction as the suppressed
INSERT, so it observes a consistent snapshot.
"""

from __future__ import annotations

from saena_domain.measurement.errors import (
    AppendOnlyViolationError,
    EvidenceHashMismatchError,
    IdempotencyConflictError,
    NotFoundError,
)
from saena_domain.measurement.ports import (
    ConfirmationRecord,
    EvidenceBundle,
    MeasurementWindow,
    OutcomeDecisionRecord,
    PutOutcome,
    PutResult,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from saena_experiment_attribution.persistence import fingerprint as fp
from saena_experiment_attribution.persistence import mapping, tables


def _require_tenant(tenant_id: str) -> None:  # pragma: no cover
    if not tenant_id:
        raise ValueError("tenant_id is required")


def _ensure_caller_owns(
    caller_tenant: str, record_tenant: str, *, key: object
) -> None:  # pragma: no cover
    # Reuse the domain port's own forged-tenant check (identical semantics /
    # error) rather than re-deriving one — imported lazily to keep this the
    # one place the check is defined for the whole store family.
    from saena_domain.measurement.ports import _ensure_caller_owns as _domain_check

    _domain_check(caller_tenant, record_tenant, key=key)


async def create_schema(engine: AsyncEngine) -> None:  # pragma: no cover
    """Apply every migration (alias of `apply_migrations`) — the test-scoped
    schema-setup entry point the integration conftest calls once per container."""
    await apply_migrations(engine)


async def apply_migrations(engine: AsyncEngine) -> None:  # pragma: no cover
    """Execute each committed migration file in order, idempotently.

    Each migration is IF-NOT-EXISTS / CREATE-OR-REPLACE, so re-applying is a
    no-op. Statements are split on `;` at top level; `$$`-quoted function
    bodies (the append-only trigger) are kept intact by the split guard."""
    async with engine.begin() as conn:
        for sql in tables.migration_sql():
            for statement in _split_sql_statements(sql):
                await conn.execute(text(statement))


def _split_sql_statements(sql: str) -> list[str]:  # pragma: no cover
    """Split a migration file into individual statements on top-level `;`,
    preserving `$$ ... $$` dollar-quoted bodies (the plpgsql trigger function)
    as single statements, and STRIPPING `--` line comments OUTSIDE dollar-quotes.

    Why split + strip: the asyncpg SQLAlchemy dialect executes each statement via
    the extended (prepared-statement) query protocol, which accepts exactly ONE
    command per call — a multi-statement file must be split — and does not
    tolerate a leading `--` comment block the way the simple protocol does, so
    every top-level line comment is stripped FIRST (before the `;` split — a `;`
    inside a comment must not be mistaken for a statement terminator). Comments
    INSIDE a `$$`-quoted plpgsql body are left intact (dollar-quoting is tracked
    across the strip so a `--` inside the function source is not removed). A
    naive split on `;` would also sever the trigger function body at its internal
    `;`, so `$$` fencing is respected there too."""
    # Pass 1: drop top-level `--` line comments, keeping dollar-quoted bodies whole.
    stripped_lines: list[str] = []
    in_dollar = False
    for line in sql.splitlines():
        # Toggle dollar-quote state on each `$$` occurrence in the line.
        if not in_dollar and line.strip().startswith("--"):
            continue
        stripped_lines.append(line)
        in_dollar ^= line.count("$$") % 2 == 1
    sql_no_comments = "\n".join(stripped_lines)

    # Pass 2: split on top-level `;`, preserving `$$ ... $$` bodies.
    statements: list[str] = []
    buf: list[str] = []
    in_dollar = False
    i = 0
    while i < len(sql_no_comments):
        if sql_no_comments.startswith("$$", i):
            in_dollar = not in_dollar
            buf.append("$$")
            i += 2
            continue
        ch = sql_no_comments[i]
        if ch == ";" and not in_dollar:
            statements.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    statements.append("".join(buf))

    return [s.strip() for s in statements if s.strip()]


async def truncate_all(engine: AsyncEngine) -> None:  # pragma: no cover
    """Per-test isolation helper — wipe every owned table (TRUNCATE CASCADE)."""
    async with engine.begin() as conn:
        await conn.execute(text(tables.truncate_all_sql()))


def make_engine(url: str) -> AsyncEngine:  # pragma: no cover
    """Convenience `AsyncEngine` factory (asyncpg driver assumed in `url`)."""
    return create_async_engine(url)


class PgConfirmationStore:  # pragma: no cover
    """`ConfirmationStore` over Postgres — keyed `(tenant_id, confirmation_key)`."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def put_confirmation(
        self, tenant_id: str, key: str, record: ConfirmationRecord
    ) -> PutResult:
        _require_tenant(tenant_id)
        if not key:
            raise ValueError("key is required")
        _ensure_caller_owns(tenant_id, record.tenant_id, key=key)
        incoming_fp = fp.confirmation_fingerprint(
            tenant_id=tenant_id,
            confirmation_key=key,
            measurement_kind=record.measurement_kind,
            payload=mapping._thaw(record.payload),
        )
        bind = mapping.confirmation_to_bind(tenant_id, key, record, incoming_fp)
        async with self._engine.begin() as conn:
            inserted = (
                (await conn.execute(text(tables.insert_confirmation_sql()), bind))
                .mappings()
                .first()
            )
            if inserted is not None:
                return PutResult(PutOutcome.STORED, record)
            stored_row = (
                (
                    await conn.execute(
                        text(tables.select_confirmation_sql()),
                        {"tenant_id": tenant_id, "confirmation_key": key},
                    )
                )
                .mappings()
                .first()
            )
            assert stored_row is not None  # ON CONFLICT fired => a row exists
            if stored_row["content_fingerprint"] == incoming_fp:
                stored = mapping.row_to_confirmation(dict(stored_row))
                return PutResult(PutOutcome.DUPLICATE, stored)
            raise IdempotencyConflictError(
                f"confirmation_key {key!r} for tenant {tenant_id!r} already holds "
                f"different content",
                context={"tenant_id": tenant_id, "confirmation_key": key},
            )

    async def get(self, tenant_id: str, key: str) -> ConfirmationRecord:
        _require_tenant(tenant_id)
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text(tables.select_confirmation_sql()),
                        {"tenant_id": tenant_id, "confirmation_key": key},
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            raise NotFoundError(
                f"no confirmation for tenant={tenant_id!r} key={key!r}",
                context={"tenant_id": tenant_id, "confirmation_key": key},
            )
        return mapping.row_to_confirmation(dict(row))


class PgMeasurementWindowStore:  # pragma: no cover
    """`MeasurementWindowStore` over Postgres — at-most-one active window per
    `(tenant_id, experiment_id)`, enforced by a partial UNIQUE index."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def open_window(self, tenant_id: str, window: MeasurementWindow) -> PutResult:
        _require_tenant(tenant_id)
        _ensure_caller_owns(tenant_id, window.tenant_id, key=window.experiment_id)
        incoming_fp = fp.window_fingerprint(
            tenant_id=tenant_id,
            experiment_id=window.experiment_id,
            starts_at=window.starts_at,
            ends_at=window.ends_at,
            policy_version=window.policy_version,
        )
        bind = mapping.window_to_bind(tenant_id, window, incoming_fp)
        async with self._engine.begin() as conn:
            inserted = (
                (await conn.execute(text(tables.insert_window_sql()), bind)).mappings().first()
            )
            if inserted is not None:
                return PutResult(PutOutcome.STORED, window)
            stored_row = (
                (
                    await conn.execute(
                        text(tables.select_window_sql()),
                        {"tenant_id": tenant_id, "experiment_id": window.experiment_id},
                    )
                )
                .mappings()
                .first()
            )
            assert stored_row is not None
            if stored_row["content_fingerprint"] == incoming_fp:
                return PutResult(PutOutcome.DUPLICATE, mapping.row_to_window(dict(stored_row)))
            raise IdempotencyConflictError(
                f"an active window with different parameters already exists for "
                f"experiment {window.experiment_id!r} (tenant {tenant_id!r})",
                context={"tenant_id": tenant_id, "experiment_id": window.experiment_id},
            )

    async def get_active(self, tenant_id: str, experiment_id: str) -> MeasurementWindow:
        _require_tenant(tenant_id)
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text(tables.select_window_sql()),
                        {"tenant_id": tenant_id, "experiment_id": experiment_id},
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            raise NotFoundError(
                f"no active window for tenant={tenant_id!r} experiment={experiment_id!r}",
                context={"tenant_id": tenant_id, "experiment_id": experiment_id},
            )
        return mapping.row_to_window(dict(row))


class PgOutcomeDecisionStore:  # pragma: no cover
    """`OutcomeDecisionStore` over Postgres — append-only per
    `(tenant_id, experiment_id, decision_slot)` (DB trigger denies UPDATE/DELETE)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def append_decision(self, tenant_id: str, decision: OutcomeDecisionRecord) -> PutResult:
        _require_tenant(tenant_id)
        _ensure_caller_owns(tenant_id, decision.tenant_id, key=list(decision.decision_key))
        incoming_fp = fp.decision_fingerprint(
            tenant_id=tenant_id,
            decision_key=decision.decision_key,
            outcome=decision.outcome,
            evidence_bundle_ref=decision.evidence_bundle_ref,
            policy_metadata=mapping._thaw(decision.policy_metadata),
        )
        bind = mapping.decision_to_bind(tenant_id, decision, incoming_fp)
        async with self._engine.begin() as conn:
            inserted = (
                (await conn.execute(text(tables.insert_decision_sql()), bind)).mappings().first()
            )
            if inserted is not None:
                return PutResult(PutOutcome.STORED, decision)
            experiment_id, decision_slot = decision.decision_key
            stored_row = (
                (
                    await conn.execute(
                        text(tables.select_decision_sql()),
                        {
                            "tenant_id": tenant_id,
                            "experiment_id": experiment_id,
                            "decision_slot": decision_slot,
                        },
                    )
                )
                .mappings()
                .first()
            )
            assert stored_row is not None
            if stored_row["content_fingerprint"] == incoming_fp:
                return PutResult(PutOutcome.DUPLICATE, mapping.row_to_decision(dict(stored_row)))
            raise AppendOnlyViolationError(
                f"decision {list(decision.decision_key)!r} for tenant {tenant_id!r} "
                f"already recorded — append-only, no overwrite",
                context={"tenant_id": tenant_id, "decision_key": list(decision.decision_key)},
            )

    async def get(self, tenant_id: str, decision_key: tuple[str, str]) -> OutcomeDecisionRecord:
        _require_tenant(tenant_id)
        experiment_id, decision_slot = decision_key
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text(tables.select_decision_sql()),
                        {
                            "tenant_id": tenant_id,
                            "experiment_id": experiment_id,
                            "decision_slot": decision_slot,
                        },
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            raise NotFoundError(
                f"no decision for tenant={tenant_id!r} decision_key={list(decision_key)!r}",
                context={"tenant_id": tenant_id, "decision_key": list(decision_key)},
            )
        return mapping.row_to_decision(dict(row))

    async def list_decisions(self, tenant_id: str) -> tuple[OutcomeDecisionRecord, ...]:
        _require_tenant(tenant_id)
        async with self._engine.connect() as conn:
            rows = (
                (await conn.execute(text(tables.list_decisions_sql()), {"tenant_id": tenant_id}))
                .mappings()
                .all()
            )
        return tuple(mapping.row_to_decision(dict(row)) for row in rows)


class PgEvidenceBundleStore:  # pragma: no cover
    """`EvidenceBundleStore` over Postgres — content-addressed per
    `(tenant_id, manifest_hash)`. Reads re-verify chain-bearing manifests (SF-4)."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def put(self, tenant_id: str, manifest_hash: str, bundle: EvidenceBundle) -> PutResult:
        _require_tenant(tenant_id)
        if not manifest_hash:
            raise ValueError("manifest_hash is required")
        _ensure_caller_owns(tenant_id, bundle.tenant_id, key=manifest_hash)
        incoming_fp = fp.bundle_fingerprint(
            tenant_id=tenant_id, manifest=mapping._thaw(bundle.manifest)
        )
        bind = mapping.evidence_to_bind(tenant_id, manifest_hash, bundle, incoming_fp)
        async with self._engine.begin() as conn:
            inserted = (
                (await conn.execute(text(tables.insert_evidence_sql()), bind)).mappings().first()
            )
            if inserted is not None:
                return PutResult(PutOutcome.STORED, bundle)
            stored_row = (
                (
                    await conn.execute(
                        text(tables.select_evidence_sql()),
                        {"tenant_id": tenant_id, "manifest_hash": manifest_hash},
                    )
                )
                .mappings()
                .first()
            )
            assert stored_row is not None
            if stored_row["content_fingerprint"] == incoming_fp:
                # DUPLICATE path still re-verifies via row_to_evidence_bundle (SF-4).
                return PutResult(
                    PutOutcome.DUPLICATE, mapping.row_to_evidence_bundle(dict(stored_row))
                )
            raise EvidenceHashMismatchError(
                f"manifest_hash {manifest_hash!r} for tenant {tenant_id!r} already "
                f"resolves to different content (hash collision / integrity violation)",
                context={"tenant_id": tenant_id, "manifest_hash": manifest_hash},
            )

    async def get(self, tenant_id: str, manifest_hash: str) -> EvidenceBundle:
        _require_tenant(tenant_id)
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text(tables.select_evidence_sql()),
                        {"tenant_id": tenant_id, "manifest_hash": manifest_hash},
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            raise NotFoundError(
                f"no evidence bundle for tenant={tenant_id!r} manifest_hash={manifest_hash!r}",
                context={"tenant_id": tenant_id, "manifest_hash": manifest_hash},
            )
        return mapping.row_to_evidence_bundle(dict(row))  # SF-4 re-verification happens here


__all__ = [
    "PgConfirmationStore",
    "PgEvidenceBundleStore",
    "PgMeasurementWindowStore",
    "PgOutcomeDecisionStore",
    "apply_migrations",
    "create_schema",
    "make_engine",
    "truncate_all",
]
