"""Async SQLAlchemy (asyncpg) adapters for every `saena_domain.persistence` port (w2-13).

Spec basis: ADR-0007 (schema-per-capability + `tenant_id` discriminator),
ADR-0014 (tenant propagation), ADR-0017 (testcontainers W2A+),
`saena_domain.persistence.ports`/`memory.py` (the reference Protocols and
in-memory semantics this module MUST match exactly).

Reference-semantics parity
---------------------------
Every adapter class here implements the exact same Protocol
(`saena_domain.persistence.ports`) as its `saena_domain.persistence.memory`
in-memory counterpart, and reproduces that reference adapter's behavior
byte-for-byte — same exceptions, same tenant-isolation checks, same
idempotent-replay/conflict rules, same defensive-copy discipline on returned
mutable values (JSONB round-trips already hand back independent Python
objects on every read — asyncpg/psycopg never return a live alias of a
server-side row — so no additional `copy.deepcopy` is needed on the read
path; this module still deep-copies caller-supplied JSONB payloads before
storing SQLAlchemy Core bind parameters, so a caller mutating the dict it
passed to `put`/`record` after the call returns can never retroactively
change what was persisted in the same transaction that has not committed
yet). See each method's docstring for the specific
`saena_domain.persistence.memory` counterpart it mirrors.

Async, connection/session-injectable
--------------------------------------
Every adapter method accepts an `AsyncConnection` (SQLAlchemy Core-style) as
either a constructor-bound default or a per-call override, so callers that
need transactional-outbox semantics (W2A requirement: outbox record in the
SAME transaction as the state change it accompanies) can pass their own
open connection/transaction through every write. `record_decision`/
`OutboxPort.record` in particular expose a `connection` parameter for this
purpose. When no `connection` is supplied, each adapter opens and commits
its own short-lived transaction via its bound `AsyncEngine`.

Transactional outbox pattern (W2A)
--------------------------------------
`PostgresPlanRepository.record_decision` and `PostgresOutbox.record` are
designed to be called with the SAME `AsyncConnection` inside one
caller-managed transaction — e.g. a service records an `ApprovalDecision`
and an outbox envelope for the resulting event in one `BEGIN`/`COMMIT`
block, so a crash between the two can never leave one written without the
other. This module does not itself orchestrate that pairing (no dispatch
loop, no bus client — W2A scope, `ports.py` module docstring); it only
accepts an injectable connection so a caller CAN pair them.
"""

from __future__ import annotations

import copy
from types import MappingProxyType
from typing import Any

from pydantic import RootModel
from saena_domain.audit import AuditEntry, guard_payload
from saena_domain.audit.hashing import GENESIS, compute_entry_hash
from saena_domain.identity import TenantContext, TenantId
from saena_domain.persistence._envelope_validation import validate_envelope
from saena_domain.persistence.errors import (
    DecisionConflictError,
    DuplicateManifestError,
    NotFoundError,
    OutboxValidationError,
    TenantIsolationError,
)
from saena_domain.persistence.ports import TenantRecord
from saena_domain.persistence.postgres.tables import (
    SYSTEM_SCOPE_KEY,
    artifact_manifests,
    audit_entries,
    decision_records,
    idempotency_keys,
    outbox,
    plan_decisions,
    plans,
    tenants,
)
from saena_domain.policy import DecisionRecord, PlanSnapshot, PlanState
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


def _plain_str(value: RootModel[str] | str | None) -> str | None:
    """Unwrap a generated root-model identifier field (e.g. `Sha256Ref`) to a
    plain `str` — local copy of `saena_domain.audit.chain._plain_str`'s
    trivial unwrap logic.

    Duplicated here (not imported) rather than reaching into
    `saena_domain.audit.chain`'s private (underscore-prefixed) helper — same
    "no private cross-module coupling" discipline
    `_envelope_validation.py`'s module docstring already establishes for
    this package. `RootModel` instances do not compare equal to a plain
    string of the same value and `str(...)` on one renders `"root='...'"`,
    not the wrapped value, so every place this module compares, hashes, or
    formats an `event_hash`/`prev_event_hash` unwraps through this helper
    first, exactly mirroring `saena_domain.audit.chain`'s own usage.
    """
    if isinstance(value, RootModel):
        return value.root
    return value


def _envelope_owner(envelope: dict[str, Any]) -> str | None:
    """Mirrors `saena_domain.persistence.memory._envelope_owner` exactly."""
    if envelope.get("context_type") == "tenant":
        owner = envelope.get("tenant_id")
        return owner if isinstance(owner, str) else None
    return None


def _check_envelope(envelope: dict[str, Any]) -> None:
    """Mirrors `saena_domain.persistence.memory._check_envelope` exactly."""
    messages = validate_envelope(envelope)
    if messages:
        raise OutboxValidationError(
            "envelope failed dual validation: " + "; ".join(messages),
            context={"messages": messages, "event_id": envelope.get("event_id")},
        )


async def _record_decision_atomically(
    conn: AsyncConnection,
    table: Any,
    tenant_id: TenantId,
    decision: DecisionRecord,
) -> DecisionRecord:
    """Race-safe idempotent record for `table` (`plan_decisions` or
    `decision_records` — both share the exact same column shape/PK), used by
    both `PostgresPlanRepository.record_decision` and
    `PostgresDecisionRecordStore.record`.

    A plain SELECT-then-INSERT has a genuine TOCTOU race under real
    concurrency (two connections both observe "no prior row", both attempt
    INSERT, one gets a raw `IntegrityError` from the primary key rather than
    the domain-level `DecisionConflictError`/idempotent-replay outcome the
    port promises). This function closes that race with a single atomic
    `INSERT ... ON CONFLICT DO NOTHING`: the loser of the race observes
    `rowcount == 0` and falls back to reading the WINNER's already-committed
    row to determine idempotent-replay vs conflict — exactly the same
    decision logic `InMemoryPlanRepository`/`InMemoryDecisionRecordStore`
    apply under their own `threading.Lock`, translated to Postgres's own
    concurrency-control primitive (`ON CONFLICT`) instead of an
    application-level mutex.
    """
    contract_hash, approver_actor_id = decision.decision_key
    insert_stmt = (
        pg_insert(table)
        .values(
            tenant_id=tenant_id.value,
            contract_hash=contract_hash,
            approver_actor_id=approver_actor_id,
            decision=decision.decision,
            proposer_actor_id=decision.proposer_actor_id,
            high_risk=decision.high_risk,
            decided_at=decision.decided_at,
        )
        .on_conflict_do_nothing(
            index_elements=[table.c.tenant_id, table.c.contract_hash, table.c.approver_actor_id]
        )
    )
    result = await conn.execute(insert_stmt)
    if result.rowcount == 1:
        return decision

    # Lost the race (or a genuinely pre-existing row from an earlier call):
    # read back whatever is now committed under this key.
    select_stmt = select(
        table.c.decision,
        table.c.proposer_actor_id,
        table.c.high_risk,
        table.c.decided_at,
    ).where(
        table.c.tenant_id == tenant_id.value,
        table.c.contract_hash == contract_hash,
        table.c.approver_actor_id == approver_actor_id,
    )
    row = (await conn.execute(select_stmt)).first()
    assert row is not None, "ON CONFLICT DO NOTHING with rowcount 0 implies a row exists"
    prior = DecisionRecord(
        contract_hash=contract_hash,
        approver_actor_id=approver_actor_id,
        decision=row[0],
        proposer_actor_id=row[1],
        high_risk=row[2],
        decided_at=row[3],
    )
    if prior.decision == decision.decision:
        return prior
    raise DecisionConflictError(
        f"conflicting decision for key {decision.decision_key!r}: "
        f"{prior.decision!r} then {decision.decision!r}",
        context={"tenant_id": tenant_id.value, "decision_key": list(decision.decision_key)},
    )


# --- TenantRepository --------------------------------------------------------------


class PostgresTenantRepository:
    """`TenantRepository` over Postgres — one row per `tenant_id` (`tables.tenants`).

    Mirrors `InMemoryTenantRepository` exactly: stores the RAW `TenantContext`
    payload as JSONB; `get` reconstructs `TenantContext.from_payload(...)`
    (identity-layer status gate fires naturally); `get_record`/
    `update_status` never construct a `TenantContext` (gate-free, critic
    MUST-FIX 4 parity).
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def put(
        self,
        tenant_id: TenantId,
        context: TenantContext,
        *,
        connection: AsyncConnection | None = None,
    ) -> None:
        if context.tenant_id.value != tenant_id.value:
            raise ValueError(
                f"context.tenant_id {context.tenant_id.value!r} does not match "
                f"the supplied tenant_id {tenant_id.value!r}"
            )
        payload = context.model.model_dump(mode="json")
        stmt = (
            pg_insert(tenants)
            .values(tenant_id=tenant_id.value, status=payload["status"], payload=payload)
            .on_conflict_do_update(
                index_elements=[tenants.c.tenant_id],
                set_={"status": payload["status"], "payload": payload},
            )
        )
        await self._run(stmt, connection=connection)

    async def get(
        self, tenant_id: TenantId, *, connection: AsyncConnection | None = None
    ) -> TenantContext:
        payload = await self._fetch_payload(tenant_id, connection=connection)
        return TenantContext.from_payload(dict(payload))

    async def get_record(
        self, tenant_id: TenantId, *, connection: AsyncConnection | None = None
    ) -> TenantRecord:
        payload = await self._fetch_payload(tenant_id, connection=connection)
        copied = copy.deepcopy(payload)
        return TenantRecord(
            tenant_id=tenant_id.value,
            status=copied["status"],
            raw_payload=MappingProxyType(copied),
        )

    async def update_status(
        self, tenant_id: TenantId, status: str, *, connection: AsyncConnection | None = None
    ) -> str:
        async def _do(conn: AsyncConnection) -> str:
            payload = await self._fetch_payload(tenant_id, connection=conn)
            updated_payload = dict(payload)
            updated_payload["status"] = status
            stmt = (
                tenants.update()
                .where(tenants.c.tenant_id == tenant_id.value)
                .values(status=status, payload=updated_payload)
            )
            await conn.execute(stmt)
            return status

        if connection is not None:
            return await _do(connection)
        async with self._engine.begin() as conn:
            return await _do(conn)

    async def _fetch_payload(
        self, tenant_id: TenantId, *, connection: AsyncConnection | None
    ) -> dict[str, Any]:
        stmt = select(tenants.c.payload).where(tenants.c.tenant_id == tenant_id.value)

        async def _do(conn: AsyncConnection) -> dict[str, Any] | None:
            result = await conn.execute(stmt)
            row = result.first()
            return row[0] if row is not None else None

        if connection is not None:
            payload = await _do(connection)
        else:
            async with self._engine.connect() as conn:
                payload = await _do(conn)
        if payload is None:
            raise NotFoundError(
                f"no TenantContext stored for tenant_id {tenant_id.value!r}",
                context={"tenant_id": tenant_id.value},
            )
        return payload

    async def _run(self, stmt: Any, *, connection: AsyncConnection | None) -> None:
        if connection is not None:
            await connection.execute(stmt)
            return
        async with self._engine.begin() as conn:
            await conn.execute(stmt)


# --- PlanRepository --------------------------------------------------------------------


class PostgresPlanRepository:
    """`PlanRepository` over Postgres (`tables.plans`/`tables.plan_decisions`).

    Mirrors `InMemoryPlanRepository` exactly, including cross-tenant
    `TenantIsolationError` checks on `get_plan`/`get_state`/`record_decision`
    keyed the same way (`contract_hash` / `decision_key` existing under a
    DIFFERENT tenant's rows raises isolation, never a bare not-found).
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def put_plan(
        self,
        tenant_id: TenantId,
        snapshot: PlanSnapshot,
        *,
        connection: AsyncConnection | None = None,
    ) -> None:
        async def _do(conn: AsyncConnection) -> None:
            await self._assert_plan_owned(tenant_id, snapshot.contract_hash, conn)
            stmt = (
                pg_insert(plans)
                .values(
                    tenant_id=tenant_id.value,
                    contract_hash=snapshot.contract_hash,
                    content_fingerprint=snapshot.content_fingerprint,
                )
                .on_conflict_do_update(
                    index_elements=[plans.c.tenant_id, plans.c.contract_hash],
                    set_={"content_fingerprint": snapshot.content_fingerprint},
                )
            )
            await conn.execute(stmt)

        await self._exec(_do, connection)

    async def get_plan(
        self, tenant_id: TenantId, contract_hash: str, *, connection: AsyncConnection | None = None
    ) -> PlanSnapshot:
        async def _do(conn: AsyncConnection) -> PlanSnapshot:
            await self._assert_plan_owned(tenant_id, contract_hash, conn)
            stmt = select(plans.c.content_fingerprint).where(
                plans.c.tenant_id == tenant_id.value, plans.c.contract_hash == contract_hash
            )
            result = await conn.execute(stmt)
            row = result.first()
            if row is None:
                raise NotFoundError(
                    f"no ChangePlan stored for contract_hash {contract_hash!r}",
                    context={"tenant_id": tenant_id.value, "contract_hash": contract_hash},
                )
            return PlanSnapshot(contract_hash=contract_hash, content_fingerprint=row[0])

        return await self._exec(_do, connection)

    async def get_state(
        self, tenant_id: TenantId, contract_hash: str, *, connection: AsyncConnection | None = None
    ) -> PlanState:
        async def _do(conn: AsyncConnection) -> PlanState:
            await self._assert_plan_owned(tenant_id, contract_hash, conn)
            stmt = select(plans.c.state).where(
                plans.c.tenant_id == tenant_id.value, plans.c.contract_hash == contract_hash
            )
            result = await conn.execute(stmt)
            row = result.first()
            if row is None or row[0] is None:
                raise NotFoundError(
                    f"no PlanState stored for contract_hash {contract_hash!r}",
                    context={"tenant_id": tenant_id.value, "contract_hash": contract_hash},
                )
            return PlanState(row[0])

        return await self._exec(_do, connection)

    async def set_state(
        self,
        tenant_id: TenantId,
        contract_hash: str,
        state: PlanState,
        *,
        connection: AsyncConnection | None = None,
    ) -> None:
        async def _do(conn: AsyncConnection) -> None:
            await self._assert_plan_owned(tenant_id, contract_hash, conn)
            stmt = (
                pg_insert(plans)
                .values(
                    tenant_id=tenant_id.value,
                    contract_hash=contract_hash,
                    content_fingerprint="",
                    state=state.value,
                )
                .on_conflict_do_update(
                    index_elements=[plans.c.tenant_id, plans.c.contract_hash],
                    set_={"state": state.value},
                )
            )
            await conn.execute(stmt)

        await self._exec(_do, connection)

    async def record_decision(
        self,
        tenant_id: TenantId,
        decision: DecisionRecord,
        *,
        connection: AsyncConnection | None = None,
    ) -> DecisionRecord:
        contract_hash, approver_actor_id = decision.decision_key

        async def _do(conn: AsyncConnection) -> DecisionRecord:
            await self._assert_decision_owned(tenant_id, contract_hash, approver_actor_id, conn)
            return await _record_decision_atomically(conn, plan_decisions, tenant_id, decision)

        return await self._exec(_do, connection)

    async def get_decisions(
        self, tenant_id: TenantId, contract_hash: str, *, connection: AsyncConnection | None = None
    ) -> tuple[DecisionRecord, ...]:
        async def _do(conn: AsyncConnection) -> tuple[DecisionRecord, ...]:
            stmt = (
                select(
                    plan_decisions.c.approver_actor_id,
                    plan_decisions.c.decision,
                    plan_decisions.c.proposer_actor_id,
                    plan_decisions.c.high_risk,
                    plan_decisions.c.decided_at,
                )
                .where(
                    plan_decisions.c.tenant_id == tenant_id.value,
                    plan_decisions.c.contract_hash == contract_hash,
                )
                .order_by(plan_decisions.c.insertion_seq)
            )
            result = await conn.execute(stmt)
            return tuple(
                DecisionRecord(
                    contract_hash=contract_hash,
                    approver_actor_id=row[0],
                    decision=row[1],
                    proposer_actor_id=row[2],
                    high_risk=row[3],
                    decided_at=row[4],
                )
                for row in result.all()
            )

        return await self._exec(_do, connection)

    async def _assert_plan_owned(
        self, tenant_id: TenantId, contract_hash: str, conn: AsyncConnection
    ) -> None:
        stmt = select(plans.c.tenant_id).where(plans.c.contract_hash == contract_hash)
        result = await conn.execute(stmt)
        for (other_tenant,) in result.all():
            if other_tenant != tenant_id.value:
                raise TenantIsolationError(
                    f"contract_hash {contract_hash!r} belongs to a different tenant",
                    context={"requested_tenant_id": tenant_id.value},
                )

    async def _assert_decision_owned(
        self,
        tenant_id: TenantId,
        contract_hash: str,
        approver_actor_id: str,
        conn: AsyncConnection,
    ) -> None:
        stmt = select(plan_decisions.c.tenant_id).where(
            plan_decisions.c.contract_hash == contract_hash,
            plan_decisions.c.approver_actor_id == approver_actor_id,
        )
        result = await conn.execute(stmt)
        for (other_tenant,) in result.all():
            if other_tenant != tenant_id.value:
                raise TenantIsolationError(
                    f"decision key {(contract_hash, approver_actor_id)!r} belongs to a "
                    "different tenant",
                    context={"requested_tenant_id": tenant_id.value},
                )

    async def _exec(self, fn: Any, connection: AsyncConnection | None) -> Any:
        if connection is not None:
            return await fn(connection)
        async with self._engine.begin() as conn:
            return await fn(conn)


# --- AuditLedgerPort ---------------------------------------------------------------


class PostgresAuditLedger:
    """`AuditLedgerPort` over Postgres (`tables.audit_entries`).

    Mirrors `InMemoryAuditLedger` exactly: one system-scope chain
    (`scope_key = tables.SYSTEM_SCOPE_KEY`) plus one chain per tenant
    (`scope_key = tenant_id`), each append-only and independently
    hash-linked — chain continuity is verified only within a `scope_key`'s
    own rows, matching `InMemoryAuditLedger._chain_for` exactly. `append`
    re-runs `guard_payload` (belt-and-suspenders, same as the in-memory
    reference) and re-verifies `prev_event_hash`/`event_hash` linkage
    against the current DB-resident tail before inserting — an entry whose
    linkage does not match the tail is rejected before it ever reaches
    storage, same as `saena_domain.audit.append_entry`.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def append(
        self, entry: AuditEntry, *, connection: AsyncConnection | None = None
    ) -> AuditEntry:
        guard_payload(entry.payload)
        tenant_id = TenantId(entry.tenant_id.root) if entry.tenant_id is not None else None
        scope_key = tenant_id.value if tenant_id is not None else SYSTEM_SCOPE_KEY

        async def _do(conn: AsyncConnection) -> AuditEntry:
            tail_hash, next_seq = await self._tail(scope_key, conn)
            actual_prev = _plain_str(entry.prev_event_hash)
            if actual_prev != tail_hash:
                raise ValueError(
                    "entry.prev_event_hash does not match the current chain tail "
                    f"(expected {tail_hash!r}, got {actual_prev!r})"
                )
            recomputed = compute_entry_hash(entry.hashable_fields(), actual_prev)
            actual_hash = _plain_str(entry.event_hash)
            if recomputed != actual_hash:
                raise ValueError("entry.event_hash does not match its own field content")

            insert_stmt = audit_entries.insert().values(
                scope_key=scope_key,
                seq=next_seq,
                tenant_id=tenant_id.value if tenant_id is not None else None,
                run_id=entry.run_id.root if entry.run_id is not None else None,
                scope=entry.scope.value,
                action=entry.action,
                recorded_at=entry.recorded_at.root,
                trace_id=entry.trace_id,
                payload=entry.payload,
                actor_id=entry.actor_id.root if entry.actor_id is not None else None,
                error_code=entry.error_code,
                event_hash=actual_hash,
                prev_event_hash=actual_prev,
            )
            await conn.execute(insert_stmt)
            return entry

        return await self._exec(_do, connection)

    async def read_range(
        self,
        *,
        tenant_id: TenantId | None = None,
        start_index: int = 0,
        end_index: int | None = None,
        connection: AsyncConnection | None = None,
    ) -> tuple[AuditEntry, ...]:
        scope_key = tenant_id.value if tenant_id is not None else SYSTEM_SCOPE_KEY

        async def _do(conn: AsyncConnection) -> tuple[AuditEntry, ...]:
            stmt = (
                select(audit_entries)
                .where(audit_entries.c.scope_key == scope_key)
                .order_by(audit_entries.c.seq)
            )
            result = await conn.execute(stmt)
            rows = result.mappings().all()
            entries = tuple(self._row_to_entry(row) for row in rows)
            stop = end_index if end_index is not None else len(entries)
            return entries[start_index:stop]

        return await self._exec(_do, connection)

    async def verify(
        self, *, tenant_id: TenantId | None = None, connection: AsyncConnection | None = None
    ) -> tuple[bool, int | None]:
        entries = await self.read_range(tenant_id=tenant_id, connection=connection)
        expected_prev: str | None = GENESIS
        for index, entry in enumerate(entries):
            actual_prev = _plain_str(entry.prev_event_hash)
            if actual_prev != expected_prev:
                return False, index
            recomputed = compute_entry_hash(entry.hashable_fields(), actual_prev)
            actual_hash = _plain_str(entry.event_hash)
            if recomputed != actual_hash:
                return False, index
            expected_prev = actual_hash
        return True, None

    async def _tail(self, scope_key: str, conn: AsyncConnection) -> tuple[str | None, int]:
        stmt = (
            select(audit_entries.c.event_hash, audit_entries.c.seq)
            .where(audit_entries.c.scope_key == scope_key)
            .order_by(audit_entries.c.seq.desc())
            .limit(1)
        )
        result = await conn.execute(stmt)
        row = result.first()
        if row is None:
            return GENESIS, 0
        return row[0], row[1] + 1

    @staticmethod
    def _row_to_entry(row: Any) -> AuditEntry:
        return AuditEntry.model_validate(
            {
                "event_hash": row["event_hash"],
                "prev_event_hash": row["prev_event_hash"],
                "action": row["action"],
                "recorded_at": row["recorded_at"],
                "scope": row["scope"],
                "trace_id": row["trace_id"],
                "payload": row["payload"],
                "tenant_id": row["tenant_id"],
                "run_id": row["run_id"],
                "actor_id": row["actor_id"],
                "error_code": row["error_code"],
            }
        )

    async def _exec(self, fn: Any, connection: AsyncConnection | None) -> Any:
        if connection is not None:
            return await fn(connection)
        async with self._engine.begin() as conn:
            return await fn(conn)


# --- DecisionRecordPort --------------------------------------------------------------


class PostgresDecisionRecordStore:
    """`DecisionRecordPort` over Postgres (`tables.decision_records`).

    Mirrors `InMemoryDecisionRecordStore` exactly — policy-gate's own
    idempotent decision log, distinct storage from
    `PostgresPlanRepository.record_decision`/`.get_decisions`.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record(
        self,
        tenant_id: TenantId,
        decision: DecisionRecord,
        *,
        connection: AsyncConnection | None = None,
    ) -> DecisionRecord:
        async def _do(conn: AsyncConnection) -> DecisionRecord:
            return await _record_decision_atomically(conn, decision_records, tenant_id, decision)

        return await self._exec(_do, connection)

    async def get(
        self,
        tenant_id: TenantId,
        decision_key: tuple[str, str],
        *,
        connection: AsyncConnection | None = None,
    ) -> DecisionRecord:
        contract_hash, approver_actor_id = decision_key

        async def _do(conn: AsyncConnection) -> DecisionRecord:
            stmt = select(
                decision_records.c.decision,
                decision_records.c.proposer_actor_id,
                decision_records.c.high_risk,
                decision_records.c.decided_at,
            ).where(
                decision_records.c.tenant_id == tenant_id.value,
                decision_records.c.contract_hash == contract_hash,
                decision_records.c.approver_actor_id == approver_actor_id,
            )
            result = await conn.execute(stmt)
            row = result.first()
            if row is None:
                raise NotFoundError(
                    f"no decision recorded for key {decision_key!r}",
                    context={"tenant_id": tenant_id.value, "decision_key": list(decision_key)},
                )
            return DecisionRecord(
                contract_hash=contract_hash,
                approver_actor_id=approver_actor_id,
                decision=row[0],
                proposer_actor_id=row[1],
                high_risk=row[2],
                decided_at=row[3],
            )

        return await self._exec(_do, connection)

    async def _exec(self, fn: Any, connection: AsyncConnection | None) -> Any:
        if connection is not None:
            return await fn(connection)
        async with self._engine.begin() as conn:
            return await fn(conn)


# --- ArtifactManifestPort -------------------------------------------------------------


class PostgresArtifactManifestStore:
    """`ArtifactManifestPort` over Postgres (`tables.artifact_manifests`).

    Mirrors `InMemoryArtifactManifestStore` exactly — put-once by
    `(tenant_id, patch_unit_id, worktree_commit)` with content-equality
    replay; cross-tenant key collisions raise `TenantIsolationError`.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def put(
        self,
        tenant_id: TenantId,
        patch_unit_id: str,
        worktree_commit: str,
        manifest: dict[str, Any],
        *,
        connection: AsyncConnection | None = None,
    ) -> dict[str, Any]:
        async def _do(conn: AsyncConnection) -> dict[str, Any]:
            await self._assert_owned(tenant_id, patch_unit_id, worktree_commit, conn)
            stmt = select(artifact_manifests.c.manifest).where(
                artifact_manifests.c.tenant_id == tenant_id.value,
                artifact_manifests.c.patch_unit_id == patch_unit_id,
                artifact_manifests.c.worktree_commit == worktree_commit,
            )
            result = await conn.execute(stmt)
            row = result.first()
            if row is not None:
                existing = row[0]
                if existing == manifest:
                    return copy.deepcopy(existing)
                raise DuplicateManifestError(
                    f"manifest key {(patch_unit_id, worktree_commit)!r} already stored "
                    "with different content",
                    context={
                        "tenant_id": tenant_id.value,
                        "patch_unit_id": patch_unit_id,
                        "worktree_commit": worktree_commit,
                    },
                )
            stored = copy.deepcopy(manifest)
            insert_stmt = artifact_manifests.insert().values(
                tenant_id=tenant_id.value,
                patch_unit_id=patch_unit_id,
                worktree_commit=worktree_commit,
                manifest=stored,
            )
            await conn.execute(insert_stmt)
            return copy.deepcopy(stored)

        return await self._exec(_do, connection)

    async def get(
        self,
        tenant_id: TenantId,
        patch_unit_id: str,
        worktree_commit: str,
        *,
        connection: AsyncConnection | None = None,
    ) -> dict[str, Any]:
        async def _do(conn: AsyncConnection) -> dict[str, Any]:
            await self._assert_owned(tenant_id, patch_unit_id, worktree_commit, conn)
            stmt = select(artifact_manifests.c.manifest).where(
                artifact_manifests.c.tenant_id == tenant_id.value,
                artifact_manifests.c.patch_unit_id == patch_unit_id,
                artifact_manifests.c.worktree_commit == worktree_commit,
            )
            result = await conn.execute(stmt)
            row = result.first()
            if row is None:
                raise NotFoundError(
                    f"no manifest stored for key {(patch_unit_id, worktree_commit)!r}",
                    context={
                        "tenant_id": tenant_id.value,
                        "patch_unit_id": patch_unit_id,
                        "worktree_commit": worktree_commit,
                    },
                )
            return copy.deepcopy(row[0])

        return await self._exec(_do, connection)

    async def _assert_owned(
        self,
        tenant_id: TenantId,
        patch_unit_id: str,
        worktree_commit: str,
        conn: AsyncConnection,
    ) -> None:
        stmt = select(artifact_manifests.c.tenant_id).where(
            artifact_manifests.c.patch_unit_id == patch_unit_id,
            artifact_manifests.c.worktree_commit == worktree_commit,
        )
        result = await conn.execute(stmt)
        for (other_tenant,) in result.all():
            if other_tenant != tenant_id.value:
                raise TenantIsolationError(
                    f"manifest key {(patch_unit_id, worktree_commit)!r} belongs to a "
                    "different tenant",
                    context={"requested_tenant_id": tenant_id.value},
                )

    async def _exec(self, fn: Any, connection: AsyncConnection | None) -> Any:
        if connection is not None:
            return await fn(connection)
        async with self._engine.begin() as conn:
            return await fn(conn)


# --- OutboxPort -------------------------------------------------------------------


class PostgresOutbox:
    """`OutboxPort` over Postgres (`tables.outbox`) — RECORDING ONLY (W2A scope).

    Mirrors `InMemoryOutbox` exactly: envelope dual-validation +
    `guard_payload` on `record`, idempotent-by-`event_id` replay/conflict,
    `mark_published` tenant-scope check against the envelope's OWN owning
    scope (`_envelope_owner`), `list_pending` tenant filter. `record`/
    `mark_published` accept an injectable `connection` for the transactional
    outbox pattern (W2A requirement — same transaction as the accompanying
    state change).
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def record(
        self, envelope: dict[str, Any], *, connection: AsyncConnection | None = None
    ) -> dict[str, Any]:
        _check_envelope(envelope)
        guard_payload(envelope.get("payload", {}))
        event_id = envelope["event_id"]
        owner = _envelope_owner(envelope)
        context_type = envelope.get("context_type", "")

        async def _do(conn: AsyncConnection) -> dict[str, Any]:
            stmt = select(outbox.c.envelope).where(outbox.c.event_id == event_id)
            result = await conn.execute(stmt)
            row = result.first()
            if row is not None:
                existing = row[0]
                if existing == envelope:
                    return copy.deepcopy(existing)
                raise OutboxValidationError(
                    f"event_id {event_id!r} already recorded with a different envelope",
                    context={"event_id": event_id},
                )
            stored = copy.deepcopy(envelope)
            insert_stmt = outbox.insert().values(
                event_id=event_id,
                owner_tenant_id=owner,
                context_type=context_type,
                envelope=stored,
                published=False,
            )
            await conn.execute(insert_stmt)
            return copy.deepcopy(stored)

        return await self._exec(_do, connection)

    async def list_pending(
        self, tenant_id: TenantId | None = None, *, connection: AsyncConnection | None = None
    ) -> tuple[dict[str, Any], ...]:
        async def _do(conn: AsyncConnection) -> tuple[dict[str, Any], ...]:
            stmt = select(outbox.c.envelope, outbox.c.owner_tenant_id, outbox.c.context_type).where(
                outbox.c.published.is_(False)
            )
            if tenant_id is not None:
                stmt = stmt.where(
                    outbox.c.context_type == "tenant", outbox.c.owner_tenant_id == tenant_id.value
                )
            stmt = stmt.order_by(outbox.c.insertion_seq)
            result = await conn.execute(stmt)
            return tuple(copy.deepcopy(row[0]) for row in result.all())

        return await self._exec(_do, connection)

    async def mark_published(
        self,
        tenant_id: TenantId | None,
        event_id: str,
        *,
        connection: AsyncConnection | None = None,
    ) -> None:
        async def _do(conn: AsyncConnection) -> None:
            stmt = select(outbox.c.owner_tenant_id).where(outbox.c.event_id == event_id)
            result = await conn.execute(stmt)
            row = result.first()
            if row is None:
                raise NotFoundError(
                    f"no outbox entry recorded for event_id {event_id!r}",
                    context={"event_id": event_id},
                )
            owner = row[0]
            caller_owner = tenant_id.value if tenant_id is not None else None
            if owner != caller_owner:
                raise TenantIsolationError(
                    f"event_id {event_id!r} belongs to a different owning scope",
                    context={
                        "event_id": event_id,
                        "requested_tenant_id": caller_owner,
                        "owning_tenant_id": owner,
                    },
                )
            update_stmt = (
                outbox.update().where(outbox.c.event_id == event_id).values(published=True)
            )
            await conn.execute(update_stmt)

        await self._exec(_do, connection)

    async def _exec(self, fn: Any, connection: AsyncConnection | None) -> Any:
        if connection is not None:
            return await fn(connection)
        async with self._engine.begin() as conn:
            return await fn(conn)


# --- IdempotencyStore ---------------------------------------------------------------


class PostgresIdempotencyStore:
    """`IdempotencyStore` over Postgres (`tables.idempotency_keys`).

    Mirrors `InMemoryIdempotencyStore` exactly — per-tenant set of seen
    idempotency keys; `mark` is an idempotent upsert (marking the same key
    twice is a no-op, not an error).
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def seen(
        self,
        tenant_id: TenantId,
        idempotency_key: str,
        *,
        connection: AsyncConnection | None = None,
    ) -> bool:
        async def _do(conn: AsyncConnection) -> bool:
            stmt = select(idempotency_keys.c.idempotency_key).where(
                idempotency_keys.c.tenant_id == tenant_id.value,
                idempotency_keys.c.idempotency_key == idempotency_key,
            )
            result = await conn.execute(stmt)
            return result.first() is not None

        return await self._exec(_do, connection)

    async def mark(
        self,
        tenant_id: TenantId,
        idempotency_key: str,
        *,
        connection: AsyncConnection | None = None,
    ) -> None:
        async def _do(conn: AsyncConnection) -> None:
            stmt = (
                pg_insert(idempotency_keys)
                .values(tenant_id=tenant_id.value, idempotency_key=idempotency_key)
                .on_conflict_do_nothing(
                    index_elements=[
                        idempotency_keys.c.tenant_id,
                        idempotency_keys.c.idempotency_key,
                    ]
                )
            )
            await conn.execute(stmt)

        await self._exec(_do, connection)

    async def _exec(self, fn: Any, connection: AsyncConnection | None) -> Any:
        if connection is not None:
            return await fn(connection)
        async with self._engine.begin() as conn:
            return await fn(conn)


__all__ = [
    "PostgresArtifactManifestStore",
    "PostgresAuditLedger",
    "PostgresDecisionRecordStore",
    "PostgresIdempotencyStore",
    "PostgresOutbox",
    "PostgresPlanRepository",
    "PostgresTenantRepository",
]
