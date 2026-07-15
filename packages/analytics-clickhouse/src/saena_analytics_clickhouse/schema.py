"""ClickHouse table DDL + reversible migrations for the W4 analytical
tables (`observations` / `citations` / `experiment_registrations`).

Spec basis (verbatim from the authority — no field of this module deviates
from these three documents):

- ADR-0007 §Current decision 5 (rev.2, "Tenant discriminator vs physical
  partition"): "ClickHouse = **시간 파티션** + ORDER BY (tenant_id, …)
  prefix — tenant별 파티션 금지(고카디널리티 파티션 폭발)".
- `docs/architecture/data-ownership.md` Store classes table: "ClickHouse |
  event/observation/metrics analytics | append-only | 테이블별:
  chatgpt-observer(ROL), citation-intelligence, experiment-attribution, 관측
  스택 — 확정 (ADR-0007)."
- `docs/architecture/tenancy-model.md` Constraints: "Tenant discriminator
  규칙 ... 모든 tenant-scoped 레코드·이벤트에 tenant_id 논리 필수."

Partition expression choice (documented interpretation, not itself in the
authority): the authority mandates "시간 파티션" but does not spell out an
exact ClickHouse expression. `toYYYYMM(occurred_at)` (one partition per
calendar month of event time) is the standard ClickHouse idiom for "time
partition" and is used here for all three tables — a future patch unit MAY
replace it with a different granularity via an additive migration (see
"Expand/contract policy" below) if the authority is amended with an exact
expression; this module's choice is NOT itself an authority citation.

TTL / retention: **OPEN** (no concrete retention value exists anywhere in
`docs/decisions/ADR-0007-final-synthesis-ownership-topology.md`,
`docs/architecture/data-ownership.md`, `docs/architecture/tenancy-model.md`,
or `docs/architecture/security-model.md` — `security-model.md`'s own
"LLM provider egress ... §13-4 retention 결정 대기" note confirms retention
is explicitly deferred, not merely unwritten). Per this task's own
instruction ("if OPEN, do NOT invent a retention — leave TTL unset and
record it as a production-only decision"), **no `TTL` clause is emitted by
any `CREATE TABLE` below**. See `README.md` "Open decisions" for the
production-only follow-up this implies.

`non_replicated_deduplication_window` (r4-02 distributed-idempotency fix,
see `store.py` module docstring for the full invariant): every table below
is a plain (non-replicated) `MergeTree`, and ClickHouse's block-level insert
deduplication (`insert_deduplication_token`) is **disabled by default on a
non-replicated `MergeTree`** — `system.merge_tree_settings.non_replicated_
deduplication_window` defaults to `0` (verified empirically against a live
`clickhouse/clickhouse-server:24.8-alpine` container as part of this fix,
not assumed from documentation alone: a fresh table with this setting unset
does NOT deduplicate a same-token repeated insert). Every `CREATE TABLE`
below therefore sets `non_replicated_deduplication_window = 1000` (last
1000 inserted blocks kept for dedup comparison — the block-count-bounded
window ClickHouse itself exposes for non-replicated tables; there is no
non-replicated `_seconds` variant in this ClickHouse version, confirmed via
the same live-server probe) — this is what makes `store.py`'s
`insert_deduplication_token`-keyed insert an ACTUAL atomic, server-side dedup
guarantee rather than a no-op setting on an executor that silently ignores
it.

`query_text` -> `query_ref`/`query_digest` (r4-04 query privacy boundary —
FORMAT BOUNDARY, not a live-data migration): the pre-r4-04 `observations`
table had a `query_text String` column carrying the raw customer query
verbatim (`data-ownership.md` Constraints violation — "No PII/secrets in
event payloads — object refs + access policy"). This migration's
`CREATE TABLE` below REPLACES that column outright with `query_ref String`
(required, opaque `query://...` ref — see `query_privacy.py`) and
`query_digest Nullable(String)` (optional, KEYED HMAC digest, `NULL` when a
caller did not derive one). This is recorded here, explicitly, as a
CONTRACT change to `MIGRATIONS[0]` itself (not a new additive migration
entry) because — per this task's own instruction — **no Wave-4 data has
reached a real production deployment through this still-unreleased schema**
(same "no real deployment has ingested data" precondition `dedup_witness`'s
own r4-02 addition already relied on, see below); the module docstring's
own CONTRACT-is-forbidden-once-deployed policy therefore does not (yet)
apply to this specific column swap. A schema already carrying LIVE data
under the pre-r4-04 `query_text` shape would require a separate, explicitly
human-approved, additive migration (`ALTER TABLE ... ADD COLUMN query_ref
...` + a backfill/dual-write window + a LATER drop of `query_text`) — this
migration is NOT that; it is a same-commit format-boundary replacement,
valid only because no production data exists yet. Do not silently reuse
this same-commit pattern once real data has landed.

Expand/contract policy note (mirrors `saena_domain.persistence.postgres.
tables`'s own documented policy — same rationale, reproduced for this
store): this module is the ONLY schema definition for these three tables.
`migrate_up`/`migrate_down` apply it via plain `CREATE TABLE`/`DROP TABLE`
DDL through a `ClickHouseExecutor` — there is no separate migration-runner
process, and no migration file format beyond the `Migration` dataclass
below. EXPAND (new nullable-shaped columns, new tables) is safe to add in a
later, additive `Migration` entry appended to `MIGRATIONS`. CONTRACT
(dropping a column, narrowing `ORDER BY`, changing `PARTITION BY`) is
FORBIDDEN as a same-commit operation once a real deployment has ingested
data — `migrate_down` exists for pre-production/test reversibility only
(dropping an EMPTY, never-deployed table), not as a live-rollback tool; a
live-data rollback is a separate, explicitly human-approved operation per
CLAUDE.md principle 3 and the protected-paths list.
"""

from __future__ import annotations

from dataclasses import dataclass

from saena_analytics_clickhouse.errors import MigrationError, UnknownTableError

# Every table this package owns — the query builder (`query.py`) and the
# guard in `store.py` both reject any table name outside this set, so a
# typo'd or forged table name can never reach an executor.
#
# `measurement_outcome` (w5-11, Wave 5 Stage 2): append-only projection of
# experiment B-gate outcome decisions — see `_measurement_outcome_ddl` below
# for the full column-by-column spec basis. Added the SAME way `MIGRATIONS`'s
# own "Expand/contract policy" note already permits (EXPAND: a brand-new
# table is always additive, never a same-commit CONTRACT of an existing one)
# — a NEW `Migration` entry (`0002`), never a same-commit edit of `0001`.
TABLE_NAMES: tuple[str, ...] = (
    "observations",
    "citations",
    "experiment_registrations",
    "measurement_outcome",
)


def require_known_table(table: str) -> None:
    """Raise `UnknownTableError` unless `table` is one of `TABLE_NAMES`.

    Used by `query.py`'s `AnalyticsQuery.for_tenant`/`build_insert` so a
    typo'd or forged table name is rejected before any SQL string is ever
    built, not merely by the executor rejecting an unknown table at
    execution time."""
    if table not in TABLE_NAMES:
        raise UnknownTableError(
            f"unknown analytics table {table!r} (known: {TABLE_NAMES})",
            context={"table": table},
        )


# --- DDL --------------------------------------------------------------------------
#
# Every table: append-only `MergeTree` (no `ReplacingMergeTree`/`Collapsing*`
# — `ReplacingMergeTree` merges are ASYNCHRONOUS and do not guarantee
# read-your-own-write dedup, a query run immediately after a duplicate
# insert could still observe two rows without a `FINAL` modifier this
# package does not otherwise need). Idempotency dedup (r4-02 fix) is
# enforced by ClickHouse's OWN server-side, atomic, block-level insert
# deduplication (`insert_deduplication_token`, driven by `store.py`) — NOT
# by a client-side existence-check-before-insert (the r4-02 defect this
# migration's `SETTINGS non_replicated_deduplication_window` clause fixes
# the table-level precondition for; see `store.py` module docstring for the
# full invariant/mechanism and the live-server verification performed).
# `PARTITION BY toYYYYMM(occurred_at)` (time partition, see module
# docstring) + `ORDER BY (tenant_id, occurred_at, id)` (tenant_id-prefixed,
# per-tenant partitioning FORBIDDEN — ADR-0007 rev.2 §5) on every table.

#: Production physical-dedup window (blocks). Read paths do NOT depend on this
#: for correctness — they perform query-time LOGICAL dedup (see store.py
#: `get_*` / query.py `to_deduplicated_select_sql`), so a duplicate replay
#: delayed beyond this window is still observed exactly once. The window only
#: bounds how far apart two physical copies can be while ClickHouse still
#: collapses them at insert time.
DEFAULT_DEDUP_WINDOW = 1000


def _dedup_window_settings(deduplication_window: int) -> str:
    if deduplication_window < 0:
        raise ValueError(f"deduplication_window must be >= 0, got {deduplication_window}")
    return f"SETTINGS non_replicated_deduplication_window = {int(deduplication_window)}"


_DEDUP_WINDOW_SETTINGS = _dedup_window_settings(DEFAULT_DEDUP_WINDOW)

# `dedup_witness` (r4-02): adapter-internal bookkeeping column, NEVER part of
# any public `rows.py` dataclass and NEVER selected by any `get_*` query
# (`store.py`'s `_OBSERVATIONS_SELECT_COLUMNS`/etc. never name it) — its only
# purpose is to let `store.py._append` determine, via an immediate read-back,
# whether the CALLING process's own insert attempt is the one ClickHouse's
# server-side `insert_deduplication_token` dedup kept for a given
# `(tenant_id, idempotency_key)` pair (see `store.py` module docstring
# "Return value semantics"). An EXPAND-only addition per this module's own
# migration policy (module docstring) — safe to add to `MIGRATIONS[0]`
# directly since no real deployment has ingested data through this
# still-unreleased (Wave 4 remediation) schema yet.


def _observations_ddl(settings: str) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS observations
(
    tenant_id String,
    id String,
    idempotency_key String,
    occurred_at DateTime64(3, 'UTC'),
    ingested_at DateTime64(3, 'UTC') DEFAULT now64(3, 'UTC'),
    engine_id String,
    run_id String,
    query_ref String,
    query_digest Nullable(String),
    citation_refs Array(String),
    raw_object_ref String,
    dedup_witness String DEFAULT ''
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (tenant_id, occurred_at, id)
{settings}
""".strip()


def _citations_ddl(settings: str) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS citations
(
    tenant_id String,
    id String,
    idempotency_key String,
    occurred_at DateTime64(3, 'UTC'),
    ingested_at DateTime64(3, 'UTC') DEFAULT now64(3, 'UTC'),
    run_id String,
    observation_id String,
    citation_ref String,
    source_domain String,
    contribution_score Float64,
    dedup_witness String DEFAULT ''
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (tenant_id, occurred_at, id)
{settings}
""".strip()


def _experiment_registrations_ddl(settings: str) -> str:
    return f"""
CREATE TABLE IF NOT EXISTS experiment_registrations
(
    tenant_id String,
    id String,
    idempotency_key String,
    occurred_at DateTime64(3, 'UTC'),
    ingested_at DateTime64(3, 'UTC') DEFAULT now64(3, 'UTC'),
    engine_id String,
    locale String,
    observation_cell String,
    registration_hash String,
    status String,
    dedup_witness String DEFAULT ''
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (tenant_id, occurred_at, id)
{settings}
""".strip()


def _measurement_outcome_ddl(settings: str) -> str:
    """`measurement_outcome` (w5-11) — append-only projection of an
    experiment's B-gate outcome decision.

    Spec basis (wave5-plan.md w5-11/E9, ALG §3.7-3/§3.7-5/§11.3, k3s Gate C):
    - `tenant_id`/`experiment_id` — the decision's tenant + experiment scope.
    - `registration_canonical_hash` — cross-reference to the immutable
      registration hash (`saena_domain.experiment.ledger`'s H-3 anchor, same
      "store the hash, never the payload" discipline `experiment_registrations.
      registration_hash` above already uses).
    - `window_started_at`/`window_ended_at` — the measurement window this
      decision covers (the 7-day clock, ALG §7.3:483).
    - `b_verdict` — `LowCardinality(String)`: `pass`/`fail`/`undetermined`
      (wave5-plan E4: insufficient/contaminated/late data ⇒ UNDETERMINED, never
      silently PASS/FAIL). `LowCardinality` is the standard ClickHouse idiom
      for a small fixed-vocabulary string column (storage + scan efficiency);
      enum MEMBERSHIP is enforced by `rows.py`'s `MeasurementOutcomeRow`, not
      by a DB-level `ENUM` type, matching this table's siblings (`status`
      above is also a plain validated string, not a ClickHouse `Enum8`).
    - `reason_codes` — `Array(LowCardinality(String))`: the typed reason-code
      vocabulary (wave5-plan H7) explaining an UNDETERMINED/FAIL verdict —
      never free-text (no raw-content channel here, same discipline as
      `citation_refs`/`observation_cell` elsewhere in this file).
    - `outcome_layer` — the ALG §3.5 layer this signal belongs to
      (`discovery`/`citation`/`absorption`/`prominence`/`referral`, wave5-plan
      H4) — METADATA (a classification label), never raw content.
    - `evidence_basis_id` — a `sha256:` content ref into the evidence bundle
      for the signal this row's aggregates were computed from (H-3-style
      hash-only cross-reference, mirrors `registration_canonical_hash`'s own
      "hash, never payload" shape) — `Nullable` because a signal row MAY
      predate/omit a specific evidence-basis pointer (e.g. an early
      insufficient-data row) without blocking the rest of the projection.
    - `sample_count_treatment`/`sample_count_control` — METADATA-SAFE
      aggregate counts (never raw per-observation content) supporting the
      B-gate's "at least two independent layers" arithmetic and dashboard
      sample-size displays.
    - `insufficient_data` — `Bool`: this signal's own honest "not enough
      samples to decide" flag (wave5-plan E4 "insufficient ... ⇒ UNDETERMINED
      + reason code" — this column is the per-signal witness a dashboard/
      auditor can cross-check against the row's own `reason_codes`).
    - `net_of_control_lift` — `Nullable(Float64)`: the DECISION recorded in
      this task's own prompt — store the numeric per-signal
      control-adjusted (DiD) lift (needed for the raw+control-adjusted
      dashboard views, k3s §9.2:485) but NEVER a raw effect magnitude beyond
      this single control-adjusted number (no raw per-observation values, no
      raw treatment/control series — those remain evidence-bundle-referenced
      via `evidence_basis_id`, never inlined here). `Nullable` because an
      UNDETERMINED/insufficient-data row may have no computable lift at all.
    - `raw_lift` — `Nullable(Float64)`: the UNADJUSTED (pre-DiD-control)
      companion figure the same dashboard obligation requires ("raw+weighted
      evidence both retained", ALG §11.3:674-676) — paired with
      `net_of_control_lift` so `to_raw_vs_adjusted_view_sql` (`query.py`) can
      project both views from ONE row without a second table. This is a
      SUMMARY STATISTIC (one float), not raw per-observation content — the
      same "aggregate number, not raw series" boundary `net_of_control_lift`
      itself already draws.
    - `evidence_bundle_manifest_hash` — `sha256:` ref to the entry's evidence
      bundle (`saena_domain.measurement.evidence.EvidenceBundleManifest.
      manifest_hash`) — hash-only, never the bundle content itself.
    - `grs_policy_version`/`grs_policy_hash`/`grs_policy_provenance` — the
      GRS policy identity this decision was evaluated under (wave5-plan
      deliverable 5 / H1: "signed policy bundle" — this table stores the
      policy's OWN identity/provenance metadata as a cross-reference,
      mirroring `registration_hash`'s hash-only discipline, never the policy
      bundle's full content).
    - `dedup_witness` — adapter-internal r4-02 bookkeeping column, same
      shape/purpose as every sibling table's own (see module docstring above
      `_DEDUP_WINDOW_SETTINGS`) — never selected by any `get_*` query.

    `PARTITION BY toYYYYMM(occurred_at)` + `ORDER BY (tenant_id, occurred_at,
    id)` — identical convention to every other table in this file (ADR-0007
    rev.2 §5; per-tenant partition FORBIDDEN). No `TTL` clause (retention is
    OPEN, same "leave TTL unset" policy as the module docstring already
    records for the sibling tables — this is not a new decision).
    """
    return f"""
CREATE TABLE IF NOT EXISTS measurement_outcome
(
    tenant_id String,
    id String,
    idempotency_key String,
    occurred_at DateTime64(3, 'UTC'),
    ingested_at DateTime64(3, 'UTC') DEFAULT now64(3, 'UTC'),
    experiment_id String,
    registration_canonical_hash String,
    window_started_at DateTime64(3, 'UTC'),
    window_ended_at DateTime64(3, 'UTC'),
    b_verdict LowCardinality(String),
    reason_codes Array(LowCardinality(String)),
    outcome_layer LowCardinality(String),
    evidence_basis_id Nullable(String),
    sample_count_treatment UInt64,
    sample_count_control UInt64,
    insufficient_data Bool,
    net_of_control_lift Nullable(Float64),
    raw_lift Nullable(Float64),
    evidence_bundle_manifest_hash String,
    grs_policy_version String,
    grs_policy_hash String,
    grs_policy_provenance String,
    dedup_witness String DEFAULT ''
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (tenant_id, occurred_at, id)
{settings}
""".strip()


def create_table_statements(
    *, deduplication_window: int = DEFAULT_DEDUP_WINDOW
) -> tuple[str, str, str, str]:
    """The four `CREATE TABLE IF NOT EXISTS` statements, with a configurable
    physical-dedup window. Production uses `DEFAULT_DEDUP_WINDOW`; a test that
    needs to force a physical duplicate PAST the window (to prove query-time
    logical dedup still collapses it) passes a small value (e.g. 1)."""
    settings = _dedup_window_settings(deduplication_window)
    return (
        _observations_ddl(settings),
        _citations_ddl(settings),
        _experiment_registrations_ddl(settings),
        _measurement_outcome_ddl(settings),
    )


(
    _CREATE_OBSERVATIONS,
    _CREATE_CITATIONS,
    _CREATE_EXPERIMENT_REGISTRATIONS,
    _CREATE_MEASUREMENT_OUTCOME,
) = create_table_statements(deduplication_window=DEFAULT_DEDUP_WINDOW)

_DROP_OBSERVATIONS = "DROP TABLE IF EXISTS observations"
_DROP_CITATIONS = "DROP TABLE IF EXISTS citations"
_DROP_EXPERIMENT_REGISTRATIONS = "DROP TABLE IF EXISTS experiment_registrations"
_DROP_MEASUREMENT_OUTCOME = "DROP TABLE IF EXISTS measurement_outcome"


@dataclass(frozen=True, slots=True)
class Migration:
    """One reversible, safe-forward migration step.

    `up_sql`/`down_sql` are applied in LIST order by `migrate_up`/
    `migrate_down` respectively — `down_sql` is written in the REVERSE
    dependency order of `up_sql` by convention (see `MIGRATIONS` below), the
    same discipline a foreign-key-aware migration tool would enforce, even
    though ClickHouse itself has no FK constraints to violate.
    """

    version: str
    description: str
    up_sql: tuple[str, ...]
    down_sql: tuple[str, ...]


MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        version="0001",
        description=(
            "create observations/citations/experiment_registrations "
            "(ADR-0007 rev.2 time-partitioned, tenant-prefixed ORDER BY)"
        ),
        up_sql=(_CREATE_OBSERVATIONS, _CREATE_CITATIONS, _CREATE_EXPERIMENT_REGISTRATIONS),
        down_sql=(
            # Reverse of up_sql's creation order.
            _DROP_EXPERIMENT_REGISTRATIONS,
            _DROP_CITATIONS,
            _DROP_OBSERVATIONS,
        ),
    ),
    Migration(
        version="0002",
        description=(
            "create measurement_outcome (w5-11, Wave 5: append-only B-gate "
            "outcome projection — ADR-0007 rev.2 time-partitioned, "
            "tenant-prefixed ORDER BY, same convention as 0001)"
        ),
        up_sql=(_CREATE_MEASUREMENT_OUTCOME,),
        down_sql=(_DROP_MEASUREMENT_OUTCOME,),
    ),
)


def migrate_up(executor: object, *, migrations: tuple[Migration, ...] = MIGRATIONS) -> None:
    """Apply every migration's `up_sql`, in order, via `executor.execute`.

    `executor` is typed as `object` here (not `ClickHouseExecutor`) purely
    to avoid a circular import with `executor.py` at module load time; every
    real caller passes a `ClickHouseExecutor`-conforming object (`store.py`
    always does), and `execute()` is called via `getattr` duck-typing the
    same way `query.py`'s callers do.
    """
    execute = getattr(executor, "execute", None)
    if execute is None:
        raise MigrationError("executor does not implement execute(sql, params)", context={})
    for migration in migrations:
        for statement in migration.up_sql:
            execute(statement, {})


def migrate_down(executor: object, *, migrations: tuple[Migration, ...] = MIGRATIONS) -> None:
    """Reverse every migration's `down_sql`, in REVERSE migration order
    (last-applied migration is rolled back first)."""
    execute = getattr(executor, "execute", None)
    if execute is None:
        raise MigrationError("executor does not implement execute(sql, params)", context={})
    for migration in reversed(migrations):
        for statement in migration.down_sql:
            execute(statement, {})


__all__ = [
    "DEFAULT_DEDUP_WINDOW",
    "MIGRATIONS",
    "TABLE_NAMES",
    "Migration",
    "create_table_statements",
    "migrate_down",
    "migrate_up",
    "require_known_table",
]
