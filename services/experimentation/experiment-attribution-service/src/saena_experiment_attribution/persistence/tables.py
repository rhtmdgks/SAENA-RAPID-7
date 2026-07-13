"""Schema names, migration loading, and DML SQL builders (w5-10) — PURE.

No I/O against a live database happens in this module: `apply_migrations`
(in `adapter.py`) executes the statements this module NAMES, but the strings
themselves — and every DML statement the adapter binds parameters into — are
built here as pure, testable functions.

## Own-schema-per-service (ADR-0007 rev.2 §5)

`saena_experiment_attribution` is this service's own dedicated schema,
distinct from `saena_persistence` (w2-13), `saena_vector` (w4-07), and every
other unit's schema — this unit shares a schema with no one. Four tables:

- `confirmations` — keyed `(tenant_id, confirmation_key)`.
- `measurement_windows` — keyed `(tenant_id, experiment_id)`; a partial
  UNIQUE index enforces at-most-one ACTIVE window per key (pgvector r4-01
  precedent — a DB-level backstop, not just application logic).
- `outcome_decisions` — keyed `(tenant_id, experiment_id, decision_slot)`;
  APPEND-ONLY, enforced by a trigger that raises on any UPDATE/DELETE (so a
  decision cannot be overwritten even by direct SQL, not merely by the
  absence of an UPDATE method in the port).
- `evidence_bundles` — content-addressed, keyed `(tenant_id, manifest_hash)`.

## tenant_id-first composite keys (ADR-0014)

Every PRIMARY KEY leads with `tenant_id`, so a lookup under a different
tenant is a different key entirely — a tenant can never read another's row
by construction, independent of any `WHERE` predicate (matching the
in-memory reference's structural-isolation rationale).

## Idempotency: ON CONFLICT DO NOTHING + read-back-compare

Every write is `INSERT ... ON CONFLICT (<pk>) DO NOTHING RETURNING ...`:

- row ABSENT → the INSERT lands, `RETURNING` yields the new row → `STORED`.
- row PRESENT → `ON CONFLICT DO NOTHING` suppresses the insert, `RETURNING`
  yields NOTHING → the adapter reads the stored row back and compares its
  `content_fingerprint` to the incoming one. Identical → `DUPLICATE` no-op;
  DIFFERENT → the port's fail-closed conflict error (never a silent
  overwrite). The stored content is the FIRST accepted content, always.

`content_fingerprint` is a real column with a `NOT NULL` constraint carrying
the canonical-JSON fingerprint (see `fingerprint.py`); the read-back-compare
is against THAT column, so byte-identity is decided by the same
canonicalization the in-memory reference uses.

`ON CONFLICT DO NOTHING` (not `ON CONFLICT DO UPDATE`) is what makes the
first writer win under a concurrent race: two connections racing the same
brand-new key both attempt the INSERT; Postgres serializes them on the
primary-key/unique constraint, exactly one INSERT lands and RETURNs a row
(that connection reports `STORED`), the other's INSERT is suppressed and
RETURNs nothing (that connection falls into the read-back-compare path and
reports `DUPLICATE` for identical content, or raises for differing content)
— no advisory lock needed, because the constraint itself is the
serialization point (contrast w4-07's pgvector upsert, which needed an
advisory lock only because its "active row" is a partial-index invariant an
INSERT-first-then-check path could race; here the full key IS the unique
constraint, so `ON CONFLICT` alone is race-safe for the confirmation/decision/
bundle stores, and the window store's partial unique index gives the same
guarantee for its at-most-one-active invariant).
"""

from __future__ import annotations

from pathlib import Path

SCHEMA_NAME = "saena_experiment_attribution"

CONFIRMATIONS_TABLE = "confirmations"
WINDOWS_TABLE = "measurement_windows"
DECISIONS_TABLE = "outcome_decisions"
EVIDENCE_TABLE = "evidence_bundles"

#: Migration files, in apply order. Additive-only (ADR: expand/contract; no
#: destructive migration — see `wave5-plan.md` "Rollback"). A future additive
#: change appends a new numbered file here; existing files are never edited.
_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
MIGRATION_FILENAMES: tuple[str, ...] = ("0001_measurement_schema.sql",)


def qualified_table(table: str) -> str:
    """`"schema"."table"` reference used by every statement below."""
    return f'"{SCHEMA_NAME}"."{table}"'


def migration_sql() -> tuple[str, ...]:
    """Return each migration file's SQL text, in apply order.

    Reads the committed `.sql` files (the migration SSOT) rather than
    embedding DDL as Python strings — so the exact bytes CI applies are the
    exact bytes reviewed in the migration files. Pure w.r.t. the database
    (it only reads files off disk); the adapter executes the returned text.
    """
    return tuple(
        (_MIGRATIONS_DIR / name).read_text(encoding="utf-8") for name in MIGRATION_FILENAMES
    )


def truncate_all_sql() -> str:
    """Per-test isolation: wipe every owned table without dropping schema.

    `CASCADE` covers the trigger-guarded `outcome_decisions` table — TRUNCATE
    is DDL, not a row-level DELETE, so the append-only DELETE/UPDATE trigger
    (which fires on row-level DML only) does not block it (this is the
    intended test-reset path; production has no truncate path)."""
    tables = ", ".join(
        qualified_table(t)
        for t in (CONFIRMATIONS_TABLE, WINDOWS_TABLE, DECISIONS_TABLE, EVIDENCE_TABLE)
    )
    return f"TRUNCATE TABLE {tables} CASCADE"


# --- DML builders (parameterized; every caller-supplied value is a bind param) ---
#
# NB: no caller/tenant value is EVER f-string-interpolated into these
# statements — only fixed schema/column identifiers are. Every tenant_id,
# key, payload, fingerprint below is passed as a real bind parameter by the
# adapter, so there is no SQL-injection surface (same discipline as
# `saena_vector_store.pgvector.adapter`).


def insert_confirmation_sql() -> str:
    t = qualified_table(CONFIRMATIONS_TABLE)
    return (
        f"INSERT INTO {t} "
        "(tenant_id, confirmation_key, measurement_kind, payload, content_fingerprint) "
        "VALUES (:tenant_id, :confirmation_key, :measurement_kind, "
        "CAST(:payload AS jsonb), :content_fingerprint) "
        "ON CONFLICT (tenant_id, confirmation_key) DO NOTHING "
        "RETURNING tenant_id, confirmation_key, measurement_kind, payload::text"
    )


def select_confirmation_sql() -> str:
    t = qualified_table(CONFIRMATIONS_TABLE)
    return (
        "SELECT tenant_id, confirmation_key, measurement_kind, payload::text, content_fingerprint "
        f"FROM {t} WHERE tenant_id = :tenant_id AND confirmation_key = :confirmation_key"
    )


def insert_window_sql() -> str:
    t = qualified_table(WINDOWS_TABLE)
    return (
        f"INSERT INTO {t} "
        "(tenant_id, experiment_id, starts_at, ends_at, policy_version, "
        "active, content_fingerprint) "
        "VALUES (:tenant_id, :experiment_id, :starts_at, :ends_at, :policy_version, "
        "TRUE, :content_fingerprint) "
        "ON CONFLICT (tenant_id, experiment_id) WHERE active DO NOTHING "
        "RETURNING tenant_id, experiment_id, starts_at, ends_at, policy_version"
    )


def select_window_sql() -> str:
    t = qualified_table(WINDOWS_TABLE)
    return (
        "SELECT tenant_id, experiment_id, starts_at, ends_at, policy_version, content_fingerprint "
        f"FROM {t} WHERE tenant_id = :tenant_id AND experiment_id = :experiment_id AND active"
    )


def insert_decision_sql() -> str:
    t = qualified_table(DECISIONS_TABLE)
    return (
        f"INSERT INTO {t} "
        "(tenant_id, experiment_id, decision_slot, outcome, evidence_bundle_ref, "
        "policy_metadata, content_fingerprint) "
        "VALUES (:tenant_id, :experiment_id, :decision_slot, :outcome, :evidence_bundle_ref, "
        "CAST(:policy_metadata AS jsonb), :content_fingerprint) "
        "ON CONFLICT (tenant_id, experiment_id, decision_slot) DO NOTHING "
        "RETURNING tenant_id, experiment_id, decision_slot, outcome, "
        "evidence_bundle_ref, policy_metadata::text"
    )


def select_decision_sql() -> str:
    t = qualified_table(DECISIONS_TABLE)
    return (
        "SELECT tenant_id, experiment_id, decision_slot, outcome, evidence_bundle_ref, "
        "policy_metadata::text, content_fingerprint "
        f"FROM {t} WHERE tenant_id = :tenant_id AND experiment_id = :experiment_id "
        "AND decision_slot = :decision_slot"
    )


def list_decisions_sql() -> str:
    t = qualified_table(DECISIONS_TABLE)
    # ORDER BY the append-order surrogate (seq) so list order is insertion
    # order (matches the in-memory reference's dict-insertion-order contract).
    return (
        "SELECT tenant_id, experiment_id, decision_slot, outcome, evidence_bundle_ref, "
        "policy_metadata::text "
        f"FROM {t} WHERE tenant_id = :tenant_id ORDER BY seq ASC"
    )


def insert_evidence_sql() -> str:
    t = qualified_table(EVIDENCE_TABLE)
    return (
        f"INSERT INTO {t} "
        "(tenant_id, manifest_hash, manifest, content_fingerprint) "
        "VALUES (:tenant_id, :manifest_hash, CAST(:manifest AS jsonb), :content_fingerprint) "
        "ON CONFLICT (tenant_id, manifest_hash) DO NOTHING "
        "RETURNING tenant_id, manifest_hash, manifest::text"
    )


def select_evidence_sql() -> str:
    t = qualified_table(EVIDENCE_TABLE)
    return (
        "SELECT tenant_id, manifest_hash, manifest::text, content_fingerprint "
        f"FROM {t} WHERE tenant_id = :tenant_id AND manifest_hash = :manifest_hash"
    )


__all__ = [
    "CONFIRMATIONS_TABLE",
    "DECISIONS_TABLE",
    "EVIDENCE_TABLE",
    "MIGRATION_FILENAMES",
    "SCHEMA_NAME",
    "WINDOWS_TABLE",
    "insert_confirmation_sql",
    "insert_decision_sql",
    "insert_evidence_sql",
    "insert_window_sql",
    "list_decisions_sql",
    "migration_sql",
    "qualified_table",
    "select_confirmation_sql",
    "select_decision_sql",
    "select_evidence_sql",
    "select_window_sql",
    "truncate_all_sql",
]
