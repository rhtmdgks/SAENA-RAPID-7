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
TABLE_NAMES: tuple[str, ...] = ("observations", "citations", "experiment_registrations")


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
# — this package's idempotency dedup is enforced at the ADAPTER layer,
# `store.py`'s existence-check-before-insert, not by a ClickHouse
# background-merge dedup engine, because `ReplacingMergeTree` merges are
# ASYNCHRONOUS and do not guarantee read-your-own-write dedup — a query run
# immediately after a duplicate insert could still observe two rows without
# a `FINAL` modifier this package does not otherwise need). `PARTITION BY
# toYYYYMM(occurred_at)` (time partition, see module docstring) + `ORDER BY
# (tenant_id, occurred_at, id)` (tenant_id-prefixed, per-tenant partitioning
# FORBIDDEN — ADR-0007 rev.2 §5) on every table.

_CREATE_OBSERVATIONS = """
CREATE TABLE IF NOT EXISTS observations
(
    tenant_id String,
    id String,
    idempotency_key String,
    occurred_at DateTime64(3, 'UTC'),
    ingested_at DateTime64(3, 'UTC') DEFAULT now64(3, 'UTC'),
    engine_id String,
    run_id String,
    query_text String,
    citation_refs Array(String),
    raw_object_ref String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (tenant_id, occurred_at, id)
""".strip()

_CREATE_CITATIONS = """
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
    contribution_score Float64
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (tenant_id, occurred_at, id)
""".strip()

_CREATE_EXPERIMENT_REGISTRATIONS = """
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
    status String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(occurred_at)
ORDER BY (tenant_id, occurred_at, id)
""".strip()

_DROP_OBSERVATIONS = "DROP TABLE IF EXISTS observations"
_DROP_CITATIONS = "DROP TABLE IF EXISTS citations"
_DROP_EXPERIMENT_REGISTRATIONS = "DROP TABLE IF EXISTS experiment_registrations"


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
    "MIGRATIONS",
    "TABLE_NAMES",
    "Migration",
    "migrate_down",
    "migrate_up",
    "require_known_table",
]
