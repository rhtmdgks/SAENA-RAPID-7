"""SQLAlchemy Core metadata for `saena_domain.persistence.postgres` (w2-13).

Spec basis: ADR-0007 (schema-per-capability + `tenant_id` discriminator —
"Postgres = schema-per-capability + tenant_id 인덱스/RLS(2차 방어)"),
ADR-0014 (tenant propagation / `tenant_id` discriminator), ADR-0017
(testcontainers introduced W2A+).

Expand/contract policy note (W2A rollback discipline)
-------------------------------------------------------
NO committed migration files exist anywhere in this repository yet —
`database/migrations/**` is a protected path this patch unit does not touch.
This module is the ONLY schema definition for the tables below: it is
SQLAlchemy Core `MetaData`/`Table` objects, applied test-scoped via
`metadata.create_all(...)` inside integration-test fixtures
(`tests/integration/persistence_postgres/conftest.py`), never against a
long-lived database and never via a hand-written `ALTER`/`CREATE` migration
script. When a real migration tool (e.g. Alembic) is introduced by a future,
human-owned patch unit, the following policy applies to any change made to
the `Table` definitions below:

- EXPAND first: new nullable columns / new tables / new indexes may be added
  freely — they are backward compatible with a not-yet-migrated reader.
- CONTRACT only after all readers/writers are migrated, and only via an
  explicit, human-approved, additive-first migration — dropping a column,
  narrowing a type, or dropping a table is never done in the same change
  that adds the replacement; deploy/rollback safety requires the old and new
  shapes to coexist for at least one release window.
- Destructive DDL (`DROP TABLE`, `DROP COLUMN`, `ALTER COLUMN TYPE` that
  narrows/truncates) is FORBIDDEN in this patch unit's scope and remains
  forbidden as a same-commit operation once real migrations exist — it
  requires a separate, explicitly human-approved change per CLAUDE.md
  principle 3 ("인간 승인 전 write 금지") and the protected-paths list
  (`database/migrations/**`).

Tenant discriminator (ADR-0007/ADR-0014, structural enforcement)
-------------------------------------------------------------------
EVERY tenant-scoped table below carries a non-null `tenant_id` column that
participates in that table's primary key (or a composite unique constraint
alongside the PK) — a row can never be inserted without a `tenant_id`
(`nullable=False`, no default), and the discriminator is therefore enforced
by the schema itself, not merely by application code convention. Row Level
Security (RLS) is named in ADR-0007 as the *second* line of defense
("2차 방어") on top of this structural discriminator; RLS policies are an
operational (human-owned, environment-specific) concern layered on top of
these table definitions, not part of this patch unit's scope (no `CREATE
POLICY`/`ALTER TABLE ... ENABLE ROW LEVEL SECURITY` statements are issued
here).

Audit ledger chain scoping (matches `InMemoryAuditLedger` exactly)
-----------------------------------------------------------------------
`saena_domain.persistence.memory.InMemoryAuditLedger` keeps ONE system-scope
chain (`tenant_id IS NULL`) plus one chain PER TENANT — chain continuity
(`prev_event_hash` linkage) is checked only within the relevant scope's own
entries, never across scopes and never across tenants. `audit_entries.seq`
below reproduces that exactly: a monotonically increasing integer assigned
per `(scope_key)` where `scope_key` is `tenant_id` for `scope='tenant'` rows
and the fixed sentinel `NULL` for `scope='system'` rows — `seq` is generated
by the adapter (not a DB identity/serial column) so the adapter can compute
it from the same "current tail" query it uses to determine
`prev_event_hash`, keeping both derived from one consistent read within the
same transaction.
"""

from __future__ import annotations

from sqlalchemy import (
    Boolean,
    Column,
    Identity,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

# Schema-per-capability (ADR-0007): every table in this module lives under
# one Postgres schema per owning capability. w2-13 ships the persistence
# ports' own adapters only (tenant-control/plan-contract/audit-ledger/
# artifact-registry/outbox/idempotency are five distinct P0 capability
# owners per contract-catalog.md), but a single shared SQLAlchemy
# `MetaData`/schema is used here deliberately: this patch unit's exclusive
# write path is one Python module tree
# (`packages/domain/src/saena_domain/persistence/postgres/**`), not one
# schema per service — splitting into five Postgres schemas with no
# corresponding service-level ownership split would misrepresent this
# module's own boundary. The `saena_persistence` schema name is a single,
# explicit namespace (schema-per-CAPABILITY-GROUP, "persistence ports"
# being the capability this patch unit owns) rather than the Postgres
# default `public` schema, satisfying ADR-0007's "own-schema" structural
# requirement without inventing five schemas this unit does not itself own
# five independent services for.
SCHEMA_NAME = "saena_persistence"

metadata = MetaData(schema=SCHEMA_NAME)

# --- tenants --------------------------------------------------------------------------
#
# `PostgresTenantRepository` — one row per tenant_id, storing the raw
# TenantContext payload as JSONB (mirrors `InMemoryTenantRepository`'s
# "store the raw payload, gate only on read via `get`" design, see
# `adapters.py`).

tenants = Table(
    "tenants",
    metadata,
    Column("tenant_id", String(32), nullable=False),
    Column("status", String(32), nullable=False),
    Column("payload", JSONB, nullable=False),
    PrimaryKeyConstraint("tenant_id", name="pk_tenants"),
)

# --- plans / plan_states / plan_decisions ------------------------------------------------
#
# `PostgresPlanRepository` — ChangePlan snapshot store (`plans`), a
# SEPARATE PlanState store (`plan_states`), plus idempotent ApprovalDecision
# log (`plan_decisions`), all keyed by
# `(tenant_id, contract_hash[, approver_actor_id])` per `PlanRepository`'s
# port docstring.
#
# `plan_states` is intentionally a DISTINCT table from `plans` (critic
# MUST-FIX, w2-13 review) — `InMemoryPlanRepository` keeps `_plans` and
# `_states` as two INDEPENDENT dicts (see `memory.py`), so `set_state`
# writing a PlanState for a `contract_hash` that has no `put_plan` row yet
# must NOT fabricate a `plans` row. An earlier version of this schema put
# `state` as a nullable column directly on `plans` and had `set_state`
# upsert into `plans` — that silently created a `plans` row with
# `content_fingerprint=""` on a state-only write, so a subsequent
# `get_plan` returned a FABRICATED `PlanSnapshot` instead of raising
# `NotFoundError` like the reference. A dedicated table with its own PK
# structurally prevents that: `set_state` can never touch `plans` at all.

plans = Table(
    "plans",
    metadata,
    Column("tenant_id", String(32), nullable=False),
    Column("contract_hash", String(256), nullable=False),
    Column("content_fingerprint", String(256), nullable=False),
    PrimaryKeyConstraint("tenant_id", "contract_hash", name="pk_plans"),
)

plan_states = Table(
    "plan_states",
    metadata,
    Column("tenant_id", String(32), nullable=False),
    Column("contract_hash", String(256), nullable=False),
    Column("state", String(32), nullable=False),
    PrimaryKeyConstraint("tenant_id", "contract_hash", name="pk_plan_states"),
)

plan_decisions = Table(
    "plan_decisions",
    metadata,
    Column("tenant_id", String(32), nullable=False),
    Column("contract_hash", String(256), nullable=False),
    Column("approver_actor_id", String(256), nullable=False),
    Column("decision", String(32), nullable=False),
    Column("proposer_actor_id", String(256), nullable=False),
    Column("high_risk", Boolean, nullable=False),
    Column("decided_at", String(64), nullable=False),
    # Insertion order for `PlanRepository.get_decisions` ("in insertion
    # order" per the port docstring) — a database-generated (`Identity()`)
    # surrogate rather than relying on physical row order, which Postgres
    # never guarantees. Plain `autoincrement=True` on a Core `Column` only
    # yields an implicit server-side default when the column is the SOLE
    # member of a single-column primary key (SQLAlchemy Core semantics,
    # not a Postgres limitation) — `insertion_seq` here is a plain (non-PK)
    # column, so an explicit `Identity()` is required to actually get
    # `GENERATED BY DEFAULT AS IDENTITY` DDL.
    Column("insertion_seq", Integer, Identity(), nullable=False),
    PrimaryKeyConstraint(
        "tenant_id", "contract_hash", "approver_actor_id", name="pk_plan_decisions"
    ),
    UniqueConstraint("insertion_seq", name="uq_plan_decisions_insertion_seq"),
)

# --- decision_records -------------------------------------------------------------------
#
# `PostgresDecisionRecordStore` — the policy-gate service's OWN idempotent
# decision log (`DecisionRecordPort`), a store distinct from `plans`/
# `plan_decisions` above (plan-contract-owned) even though both are keyed
# the same way (`decision_key` = contract_hash + canonicalized
# approver_actor_id) — see `ports.py`'s `DecisionRecordPort` docstring.

decision_records = Table(
    "decision_records",
    metadata,
    Column("tenant_id", String(32), nullable=False),
    Column("contract_hash", String(256), nullable=False),
    Column("approver_actor_id", String(256), nullable=False),
    Column("decision", String(32), nullable=False),
    Column("proposer_actor_id", String(256), nullable=False),
    Column("high_risk", Boolean, nullable=False),
    Column("decided_at", String(64), nullable=False),
    PrimaryKeyConstraint(
        "tenant_id", "contract_hash", "approver_actor_id", name="pk_decision_records"
    ),
)

# --- audit_entries ----------------------------------------------------------------------
#
# `PostgresAuditLedger` — append-only hash chain. `scope_key` is `tenant_id`
# for `scope='tenant'` rows, or the fixed sentinel string `SYSTEM_SCOPE_KEY`
# (`'__system__'`) for `scope='system'` rows (Postgres treats `NULL` as
# distinct-from-itself for uniqueness purposes, so a `NULL`-based
# scope_key cannot back a `(scope_key, seq)` uniqueness/ordering
# constraint the way a real, comparable sentinel value can — the sentinel
# is never a legal `tenant_id` per ADR-0014's slug pattern, so it can never
# collide with a genuine tenant scope). `seq` is a monotonically increasing,
# adapter-assigned integer PER `scope_key`, mirroring
# `InMemoryAuditLedger`'s "one chain per scope" semantics exactly (see
# module docstring "Audit ledger chain scoping").

SYSTEM_SCOPE_KEY = "__system__"

audit_entries = Table(
    "audit_entries",
    metadata,
    Column("scope_key", String(64), nullable=False),
    Column("seq", Integer, nullable=False),
    Column("tenant_id", String(32), nullable=True),
    Column("run_id", String(128), nullable=True),
    Column("scope", String(16), nullable=False),
    Column("action", String(256), nullable=False),
    Column("recorded_at", String(64), nullable=False),
    Column("trace_id", String(64), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("actor_id", String(128), nullable=True),
    Column("error_code", String(128), nullable=True),
    Column("event_hash", String(128), nullable=False),
    Column("prev_event_hash", String(128), nullable=True),
    PrimaryKeyConstraint("scope_key", "seq", name="pk_audit_entries"),
    UniqueConstraint("scope_key", "event_hash", name="uq_audit_entries_scope_hash"),
)

# --- artifact_manifests -------------------------------------------------------------------
#
# `PostgresArtifactManifestStore` — put-once by
# `(tenant_id, patch_unit_id, worktree_commit)` per `ArtifactManifestPort`.

artifact_manifests = Table(
    "artifact_manifests",
    metadata,
    Column("tenant_id", String(32), nullable=False),
    Column("patch_unit_id", String(256), nullable=False),
    Column("worktree_commit", String(64), nullable=False),
    Column("manifest", JSONB, nullable=False),
    PrimaryKeyConstraint(
        "tenant_id", "patch_unit_id", "worktree_commit", name="pk_artifact_manifests"
    ),
)

# --- outbox ---------------------------------------------------------------------------
#
# `PostgresOutbox` — transactional outbox, RECORDING ONLY (W2A scope).
# `event_id` unique (the outbox's own idempotency key, `OutboxPort.record`
# docstring); `owner_tenant_id` is the envelope's owning scope, `NULL` for
# system/aggregate-context envelopes (`_envelope_owner` semantics from
# `memory.py`, replicated exactly — see `adapters.py`).

outbox = Table(
    "outbox",
    metadata,
    Column("event_id", String(64), nullable=False),
    Column("owner_tenant_id", String(32), nullable=True),
    Column("context_type", String(32), nullable=False),
    Column("envelope", JSONB, nullable=False),
    Column("published", Boolean, nullable=False, server_default="false"),
    # Insertion order for `list_pending` ("every recorded envelope not yet
    # marked published", `memory.py`'s `_order` list equivalent) — see
    # `plan_decisions.insertion_seq`'s comment above for why `Identity()` is
    # required here rather than plain `autoincrement=True`.
    Column("insertion_seq", Integer, Identity(), nullable=False),
    PrimaryKeyConstraint("event_id", name="pk_outbox"),
    UniqueConstraint("insertion_seq", name="uq_outbox_insertion_seq"),
)

# --- idempotency_keys --------------------------------------------------------------------
#
# `PostgresIdempotencyStore` — per-tenant set of seen idempotency keys
# (`IdempotencyStore` port).

idempotency_keys = Table(
    "idempotency_keys",
    metadata,
    Column("tenant_id", String(32), nullable=False),
    Column("idempotency_key", String(512), nullable=False),
    PrimaryKeyConstraint("tenant_id", "idempotency_key", name="pk_idempotency_keys"),
)

__all__ = [
    "SCHEMA_NAME",
    "SYSTEM_SCOPE_KEY",
    "artifact_manifests",
    "audit_entries",
    "decision_records",
    "idempotency_keys",
    "metadata",
    "outbox",
    "plan_decisions",
    "plan_states",
    "plans",
    "tenants",
]
