-- Migration 0001 — measurement persistence schema (w5-10).
--
-- ADDITIVE-ONLY (wave5-plan.md "Rollback": no destructive migration; rollback
-- = revert the unit commit). Every statement is IF-NOT-EXISTS / idempotent, so
-- re-applying this migration is a no-op — the adapter's apply_migrations()
-- runs it unconditionally at schema-setup time (test-scoped) and a production
-- migration runner may re-run it safely.
--
-- Own-schema-per-service (ADR-0007 rev.2 §5): saena_experiment_attribution is
-- this service's dedicated schema, shared with no other unit.
--
-- tenant_id-first composite keys (ADR-0014): every PRIMARY KEY leads with
-- tenant_id so a cross-tenant lookup is a different key by construction.
--
-- Idempotency (ports.py "Idempotency model"): content_fingerprint carries the
-- canonical-JSON fingerprint of the row's logical content; the adapter's
-- INSERT ... ON CONFLICT DO NOTHING + read-back-compare uses it to distinguish
-- an idempotent replay (same fingerprint -> DUPLICATE no-op) from a fail-closed
-- conflict (different fingerprint under the same key -> error, never overwrite).

CREATE SCHEMA IF NOT EXISTS "saena_experiment_attribution";

-- confirmations: keyed (tenant_id, confirmation_key). --------------------------
CREATE TABLE IF NOT EXISTS "saena_experiment_attribution"."confirmations" (
    tenant_id           TEXT        NOT NULL,
    confirmation_key    TEXT        NOT NULL,
    measurement_kind    TEXT        NOT NULL,
    payload             JSONB       NOT NULL,
    content_fingerprint TEXT        NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, confirmation_key)
);

-- measurement_windows: keyed (tenant_id, experiment_id). ----------------------
-- `active` distinguishes the current window from any future historical rows.
-- A partial UNIQUE index enforces AT-MOST-ONE active window per key at the DB
-- level (pgvector r4-01 precedent: the invariant is enforced by the constraint,
-- not merely by application logic), and is the ON CONFLICT arbiter the adapter
-- targets. `ends_at` NULL means still open.
CREATE TABLE IF NOT EXISTS "saena_experiment_attribution"."measurement_windows" (
    tenant_id           TEXT        NOT NULL,
    experiment_id       TEXT        NOT NULL,
    starts_at           TEXT        NOT NULL,
    ends_at             TEXT,
    policy_version      TEXT        NOT NULL,
    active              BOOLEAN     NOT NULL DEFAULT TRUE,
    content_fingerprint TEXT        NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_measurement_windows_active_key
    ON "saena_experiment_attribution"."measurement_windows" (tenant_id, experiment_id)
    WHERE active;

-- outcome_decisions: keyed (tenant_id, experiment_id, decision_slot). ----------
-- APPEND-ONLY: no UPDATE/DELETE path exists in the port, and a trigger denies
-- both at the DB level so an append-only decision cannot be overwritten even by
-- direct SQL. `seq` (BIGSERIAL) preserves insertion order for list_decisions.
CREATE TABLE IF NOT EXISTS "saena_experiment_attribution"."outcome_decisions" (
    seq                 BIGSERIAL,
    tenant_id           TEXT        NOT NULL,
    experiment_id       TEXT        NOT NULL,
    decision_slot       TEXT        NOT NULL,
    outcome             TEXT        NOT NULL,
    evidence_bundle_ref TEXT        NOT NULL,
    policy_metadata     JSONB       NOT NULL,
    content_fingerprint TEXT        NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, experiment_id, decision_slot)
);

-- Append-only enforcement (constraint-based denial, documented): a BEFORE
-- UPDATE OR DELETE trigger raises unconditionally, so once a decision row is
-- inserted it can never be mutated or removed by row-level DML. TRUNCATE (DDL,
-- test-reset only) is not row-level DML and does not fire this trigger.
CREATE OR REPLACE FUNCTION "saena_experiment_attribution".deny_decision_mutation()
    RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'outcome_decisions is append-only: % is not permitted', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_outcome_decisions_append_only
    ON "saena_experiment_attribution"."outcome_decisions";
CREATE TRIGGER trg_outcome_decisions_append_only
    BEFORE UPDATE OR DELETE ON "saena_experiment_attribution"."outcome_decisions"
    FOR EACH ROW EXECUTE FUNCTION "saena_experiment_attribution".deny_decision_mutation();

-- evidence_bundles: content-addressed, keyed (tenant_id, manifest_hash). -------
CREATE TABLE IF NOT EXISTS "saena_experiment_attribution"."evidence_bundles" (
    tenant_id           TEXT        NOT NULL,
    manifest_hash       TEXT        NOT NULL,
    manifest            JSONB       NOT NULL,
    content_fingerprint TEXT        NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, manifest_hash)
);
