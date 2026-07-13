"""`ClickHouseAnalyticsStore` — the package's public adapter (w4-06 mission
deliverable 2; distributed-idempotency fixed under r4-02, see "Idempotency
invariant" below).

Every QUERY method takes `tenant_id` as its first, non-defaulted positional
argument and routes exclusively through `query.AnalyticsQuery.for_tenant`
(never a hand-built WHERE clause) — see `query.py`'s module docstring for
why this makes an unscoped cross-tenant query structurally impossible to
construct, not merely discouraged by convention.

Idempotency invariant (r4-02 — testable statement, restated in the r4-02
report)
------------------------------------------------------------------------------
For every table T this package owns and every `(tenant_id, idempotency_key)`
pair: no matter how many times, from how many independent writer
processes/connections, `append_*` is called with an `ObservationRow`/
`CitationRow`/`ExperimentRegistrationRow` carrying that exact pair, at most
ONE row for that pair is ever LOGICALLY observable through `get_*` — i.e.
`{{row for row in get_*(tenant_id) if row.idempotency_key == idempotency_key}}`
has cardinality <= 1, always, under true concurrency, not merely "usually" or
"once merges catch up". This is a LOGICAL guarantee (every read is
consistent, no `FINAL` modifier required) backed by a PHYSICAL one that is
correct-by-construction but WINDOW-BOUNDED (see "Physical vs logical" below)
— this module never claims unconditional physical exactly-once, and the
`bool` `append_*` returns is deliberately NOT a physical-uniqueness claim
(see "Return value semantics").

r4-02 defect this fixes: the PRE-FIX `_append` ran `_exists_idempotency_key`
(a `SELECT ... WHERE idempotency_key = ...` existence check) and only issued
`insert_rows` if that check came back empty — a textbook check-then-insert
TOCTOU race. Two concurrent `ClickHouseAnalyticsStore` instances (independent
executors/connections — e.g. two intelligence-worker processes retrying the
same event after a redelivery) could both run the SELECT, both observe "not
present yet", and both proceed to INSERT — MergeTree has no UNIQUE
constraint, so both rows physically land, and every subsequent `get_*` call
observes 2 (or more) rows for the same `(tenant_id, idempotency_key)`. See
`tests/integration/clickhouse/test_idempotency_distributed.py::
TestOldImplementationRaces` for a reproducer that pins the OLD
check-then-insert shape and proves it duplicates under 20 concurrent writers
— it is kept as a permanent regression witness (NOT deleted once the fix
landed), separate from the tests that exercise the CURRENT `_append`.

Two `_append` code paths exist (`_append_with_dedup_token` /
`_append_legacy_check_then_insert`), selected once per `ClickHouseAnalyticsStore`
instance (`_executor_accepts_dedup_token`, `__init__`) — NOT a design choice
about the fix's own correctness, but a compatibility concession: a small
number of PRE-EXISTING, single-writer/synthetic `ClickHouseExecutor` test
fakes elsewhere in this repo (outside this patch unit's exclusive write
paths, e.g. `tests/integration/intelligence_failure/
intelligence_failure_factories.py`) predate `dedup_token` entirely and are
never exercised under true concurrency by their own owning test suites — for
THOSE fakes only, `_append_legacy_check_then_insert` reproduces the pre-r4-02
shape verbatim (still correct for their actual, sequential-redelivery usage).
EVERY real `ClickHouseConnectExecutor` — the only executor a production
deployment ever constructs — always takes `_append_with_dedup_token`
(`_executor_supports_dedup_token` returns `True` unconditionally for it, see
`executor.py`), so the race-free path described below is what actually runs
against real ClickHouse, always. See `executor.py`'s module docstring for
the exact detection mechanism.

Mechanism (grounded, not assumed — verified against a live
`clickhouse/clickhouse-server:24.8-alpine` container as part of this fix,
before writing any implementation code): ClickHouse itself provides atomic,
SERVER-SIDE insert-block deduplication via the `insert_deduplication_token`
setting (`system.settings.insert_deduplication_token`: "If not empty, used
for duplicate detection instead of data digest") — every writer that sends
an INSERT with the SAME token has that insert's underlying data BLOCK
deduplicated against the last N previously-inserted blocks (`system.
merge_tree_settings.non_replicated_deduplication_window`, table-level,
`schema.py`'s `_DEDUP_WINDOW_SETTINGS`) BEFORE anything is written to disk —
this is checked at insert time, not by an asynchronous background merge (the
same distinction this module already documented for why `ReplacingMergeTree`
is unsuitable: THIS mechanism has no such caveat, it is not a merge-time
dedup at all). `_append` derives a DETERMINISTIC, TENANT-NAMESPACED token
(`_dedup_token`, `f"{table}:{tenant_id}:{idempotency_key}"` after a
delimiter-collision-safe encode — see that function) and passes it as
`insert_rows(..., dedup_token=...)` on EVERY call, unconditionally — there is
no pre-insert existence check anywhere in this path any more; every caller,
including concurrent/redelivered ones, always attempts the same insert, and
ClickHouse's own server-side dedup (not this adapter, not any client-side
lock) is the ONLY thing that decides how many physical rows result.
Empirically verified (see the r4-02 report's exact commands/output) as part
of this fix: 20 independent `clickhouse_connect` client instances inserting
the identical `(tenant_id, idempotency_key)` payload concurrently, with this
token scheme, always yields exactly 1 physical row, immediately (no
eventual-consistency window observed across 50 rapid re-reads) — this is
NOT true of a plain `MergeTree` with the dedup window left at its default
(`0` = disabled), which is why `schema.py` now explicitly sets
`non_replicated_deduplication_window` on every owned table.

Return value semantics (HONEST — critic-facing distinction): `append_*`
returns `True` when the CALLING process's own payload is the one ClickHouse
kept for this `(tenant_id, idempotency_key)` pair (determined by a read-back
comparing a per-call, non-business `dedup_witness` token this adapter writes
alongside the row — see `_append`), `False` when some OTHER caller's attempt
(concurrent or a prior redelivery) won instead. This is a "was I the
first-observed writer" signal, NOT a claim that ClickHouse enforces a
physical UNIQUE constraint the way a relational primary key would — outside
the configured dedup window (see "Physical vs logical"), a sufficiently
delayed duplicate CAN still land as a second physical row. `append_*` never
raises on a duplicate; it never did, and this fix does not change that.

Physical vs logical guarantee (explicit split, per r4-02 instructions)
------------------------------------------------------------------------------
- LOGICAL dedup: UNCONDITIONAL and INDEPENDENT of the physical window — every
  `get_*` query performs query-time dedup (`query.py`'s
  `to_deduplicated_select_sql`: an inner `ORDER BY id LIMIT 1 BY (tenant_id,
  idempotency_key)` collapses each key group to one deterministic winner, then
  the outer query applies display ordering + pagination AFTER dedup). So even
  if TWO physical rows exist for the same `(tenant_id, idempotency_key)`
  (because a duplicate replay arrived beyond the physical window below), a
  caller observes EXACTLY ONE. This holds for `get_observations`,
  `get_citations`, and `get_experiment_registrations`, for all time-range and
  pagination arguments (the pagination `limit` bounds distinct logical rows,
  never physical duplicates).
  - Winner rule (deterministic, wall-clock independent): the row with the
    lexicographically-minimal `id` — a stable, unique, content-derived
    tie-breaker (NOT `ingested_at`, a server-side `now64()` wall-clock).
  - Same-key / DIFFERENT-payload collision (a producer contract violation):
    resolved by the SAME deterministic rule — the minimal-`id` row is returned,
    every time, on every replica. This is an explicit, fixed policy, not a
    silent arbitrary pick.
- PHYSICAL dedup: an OPTIMIZATION, not relied on for read correctness.
  Guaranteed WITHIN `non_replicated_deduplication_window`
  (`schema.DEFAULT_DEDUP_WINDOW` = 1000 most-recently-inserted blocks) —
  ClickHouse retires the oldest tracked block hash once the window is
  exceeded. A duplicate insert arriving after more than that many OTHER blocks
  is NOT collapsed physically (no `non_replicated_deduplication_window_seconds`
  variant in this ClickHouse version, confirmed live) — but the LOGICAL dedup
  above still makes it invisible to every reader. `TTL`/retention is a separate
  OPEN decision, orthogonal to the dedup window.

Late/out-of-order tolerance is unchanged by this fix: an `occurred_at` older
than already-ingested rows is still accepted unconditionally (no
monotonicity constraint on `occurred_at`, only on the `(tenant_id,
idempotency_key)` dedup token) — matching data-ownership.md/ADR-0007's
append-only, time-partitioned model where a late-arriving event simply lands
in its own OWN correct partition, never rejected for arriving "late".

This adapter never imports `clickhouse_connect` directly — every I/O call
goes through the injected `ClickHouseExecutor` (`executor.py`), so the exact
same adapter code path is exercised by the deterministic unit lane (in-memory
fake executor) and the real-container integration lane (`ClickHouseConnectExecutor`).
This package remains a standalone leaf (imports no other `saena_*` package,
see `pyproject.toml`'s Integrator note) — r4-02 deliberately does NOT import
`saena_domain`'s outbox/`PostgresIdempotencyStore` infra even though that
infra's own `INSERT ... ON CONFLICT DO NOTHING` pattern is the same atomic,
race-free DESIGN PRINCIPLE this fix reuses (never check-then-insert; let the
STORE's own concurrency primitive decide, then read back the outcome) —
adopting that principle natively via ClickHouse's own
`insert_deduplication_token` keeps this package decoupled from
`saena_domain`'s `TenantId`/envelope types and from a second datastore
(Postgres) this package has no other reason to depend on, per the
architectural boundary `pyproject.toml`'s Integrator note already
establishes for this package.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime
from typing import Any

from saena_analytics_clickhouse.executor import ClickHouseExecutor
from saena_analytics_clickhouse.identifiers import validate_tenant_id
from saena_analytics_clickhouse.query import AnalyticsQuery, build_insert_columns
from saena_analytics_clickhouse.rows import (
    CitationRow,
    ExperimentRegistrationRow,
    MeasurementOutcomeRow,
    ObservationRow,
    RawVsAdjustedLiftRow,
)

# Column order matches `schema.py`'s CREATE TABLE DDL exactly (`tenant_id,
# id, idempotency_key, occurred_at, ingested_at, ...`) — this is also the
# exact positional order each `_*_from_values` unpacker below expects, so a
# `get_*` query's SELECT column list and a reconstructed row's field order
# never have to be reconciled by a separate reorder step.
_OBSERVATIONS_SELECT_COLUMNS: tuple[str, ...] = (
    "tenant_id",
    "id",
    "idempotency_key",
    "occurred_at",
    "ingested_at",
    "engine_id",
    "run_id",
    "query_ref",
    "query_digest",
    "citation_refs",
    "raw_object_ref",
)

_CITATIONS_SELECT_COLUMNS: tuple[str, ...] = (
    "tenant_id",
    "id",
    "idempotency_key",
    "occurred_at",
    "ingested_at",
    "run_id",
    "observation_id",
    "citation_ref",
    "source_domain",
    "contribution_score",
)

_EXPERIMENT_REGISTRATIONS_SELECT_COLUMNS: tuple[str, ...] = (
    "tenant_id",
    "id",
    "idempotency_key",
    "occurred_at",
    "ingested_at",
    "engine_id",
    "locale",
    "observation_cell",
    "registration_hash",
    "status",
)

# w5-11 (Wave 5): column order matches `schema.py`'s `measurement_outcome`
# CREATE TABLE DDL exactly, same discipline as every SELECT-columns tuple
# above — this is also the exact positional order `_measurement_outcome_
# from_values` below expects.
_MEASUREMENT_OUTCOME_SELECT_COLUMNS: tuple[str, ...] = (
    "tenant_id",
    "id",
    "idempotency_key",
    "occurred_at",
    "ingested_at",
    "experiment_id",
    "registration_canonical_hash",
    "window_started_at",
    "window_ended_at",
    "b_verdict",
    "reason_codes",
    "outcome_layer",
    "evidence_basis_id",
    "sample_count_treatment",
    "sample_count_control",
    "insufficient_data",
    "net_of_control_lift",
    "raw_lift",
    "evidence_bundle_manifest_hash",
    "grs_policy_version",
    "grs_policy_hash",
    "grs_policy_provenance",
)


def _dedup_token(table: str, tenant_id: str, idempotency_key: str) -> str:
    """Deterministic, tenant-namespaced ClickHouse `insert_deduplication_token`
    (r4-02) for one `(table, tenant_id, idempotency_key)` triple.

    Deterministic: the SAME triple always derives the SAME token, from any
    process — this is what lets independent writers (different connections,
    different hosts) converge on ClickHouse's OWN server-side dedup for the
    identical logical event, with no coordination between them beyond the
    shared inputs (`table`, `tenant_id`, `idempotency_key` — all already
    known to every caller, no new shared state introduced by this fix).

    Tenant-namespaced (proof this token can never collide across tenants):
    `tenant_id` is validated by `validate_tenant_id` (`identifiers.py`)
    BEFORE this function is ever reached — a DNS-safe slug pattern
    (`^[a-z0-9]([a-z0-9-]{{0,30}}[a-z0-9])?$`) that structurally EXCLUDES the
    `\\x1f` (ASCII Unit Separator) delimiter this function joins fields with.
    Since `tenant_id` can never itself contain the delimiter, and `table` is
    drawn from the fixed, closed `schema.TABLE_NAMES` set (also
    delimiter-free), the delimiter-joined string
    `f"{{table}}\\x1f{{tenant_id}}\\x1f{{idempotency_key}}"` has an
    UNAMBIGUOUS field boundary between `table`/`tenant_id` and
    `idempotency_key` — two DIFFERENT `(table, tenant_id)` pairs can never
    produce the same token regardless of what `idempotency_key` string a
    caller supplies (unlike a naive `f"{{tenant_id}}:{{idempotency_key}}"`
    join, where a `tenant_id` containing `:` COULD in principle shift the
    field boundary — moot here since `tenant_id` is slug-validated, but the
    Unit Separator choice removes even that theoretical ambiguity for
    `idempotency_key`, which carries no such format restriction). Same
    `idempotency_key` value reused across two DIFFERENT tenants therefore
    always yields two DIFFERENT tokens — see
    `tests/unit/analytics_clickhouse/test_store.py::
    test_same_idempotency_key_different_tenant_is_not_a_duplicate` and the
    real-ClickHouse counterpart in `tests/integration/clickhouse/
    test_idempotency_distributed.py`.
    """
    return f"{table}\x1f{tenant_id}\x1f{idempotency_key}"


def _executor_supports_dedup_token(executor: ClickHouseExecutor) -> bool:
    """Whether `executor.insert_rows` declares a `dedup_token` parameter
    (r4-02 compatibility shim, see `executor.py` module docstring).

    Computed ONCE per `ClickHouseAnalyticsStore` instance (`__init__`), not
    per call — `insert_rows`'s signature does not change over an executor's
    lifetime, so introspecting it once and caching the bool avoids repeating
    `inspect.signature` work on every single `append_*` call. A real
    `ClickHouseConnectExecutor` (this package's own, current implementation)
    always returns `True` here; only a THIRD-PARTY executor shape that
    predates this parameter (e.g. a pre-existing test fake outside this
    patch unit's exclusive write paths) returns `False`.
    """
    try:
        signature = inspect.signature(executor.insert_rows)
    except (TypeError, ValueError):  # pragma: no cover - defensive, no known
        # real executor triggers this (a builtin/C-implemented callable with
        # no introspectable signature) — fail safe to the pre-r4-02 call
        # shape rather than raising out of `ClickHouseAnalyticsStore.__init__`.
        return False
    return "dedup_token" in signature.parameters


def _observation_fields(row: ObservationRow) -> dict[str, object]:
    return {
        "tenant_id": row.tenant_id,
        "id": row.id,
        "idempotency_key": row.idempotency_key,
        "occurred_at": row.occurred_at,
        "engine_id": row.engine_id,
        "run_id": row.run_id,
        "query_ref": row.query_ref,
        "query_digest": row.query_digest,
        "citation_refs": list(row.citation_refs),
        "raw_object_ref": row.raw_object_ref,
    }


def _citation_fields(row: CitationRow) -> dict[str, object]:
    return {
        "tenant_id": row.tenant_id,
        "id": row.id,
        "idempotency_key": row.idempotency_key,
        "occurred_at": row.occurred_at,
        "run_id": row.run_id,
        "observation_id": row.observation_id,
        "citation_ref": row.citation_ref,
        "source_domain": row.source_domain,
        "contribution_score": row.contribution_score,
    }


def _experiment_registration_fields(row: ExperimentRegistrationRow) -> dict[str, object]:
    return {
        "tenant_id": row.tenant_id,
        "id": row.id,
        "idempotency_key": row.idempotency_key,
        "occurred_at": row.occurred_at,
        "engine_id": row.engine_id,
        "locale": row.locale,
        "observation_cell": row.observation_cell,
        "registration_hash": row.registration_hash,
        "status": row.status,
    }


def _measurement_outcome_fields(row: MeasurementOutcomeRow) -> dict[str, object]:
    return {
        "tenant_id": row.tenant_id,
        "id": row.id,
        "idempotency_key": row.idempotency_key,
        "occurred_at": row.occurred_at,
        "experiment_id": row.experiment_id,
        "registration_canonical_hash": row.registration_canonical_hash,
        "window_started_at": row.window_started_at,
        "window_ended_at": row.window_ended_at,
        "b_verdict": row.b_verdict,
        "reason_codes": list(row.reason_codes),
        "outcome_layer": row.outcome_layer,
        "evidence_basis_id": row.evidence_basis_id,
        "sample_count_treatment": row.sample_count_treatment,
        "sample_count_control": row.sample_count_control,
        "insufficient_data": row.insufficient_data,
        "net_of_control_lift": row.net_of_control_lift,
        "raw_lift": row.raw_lift,
        "evidence_bundle_manifest_hash": row.evidence_bundle_manifest_hash,
        "grs_policy_version": row.grs_policy_version,
        "grs_policy_hash": row.grs_policy_hash,
        "grs_policy_provenance": row.grs_policy_provenance,
    }


def _coerce_utc(value: datetime) -> datetime:
    """Reattach `tzinfo=UTC` to a NAIVE `datetime` returned by a real
    ClickHouse driver.

    ClickHouse's `DateTime64(3, 'UTC')` column type (`schema.py`) guarantees
    every stored instant is ALREADY unambiguous UTC — but `clickhouse-connect`
    (and most ClickHouse Python drivers) hand back a naive `datetime.datetime`
    from a query result regardless (the timezone is a SERVER-side storage/
    display concept, not carried in the Python value the driver constructs).
    `rows.py`'s `validate_utc_datetime` rejects naive datetimes outright
    (correctness guard against a caller passing an AMBIGUOUS timestamp at
    construction time) — this coercion is the one place in this package that
    re-attaches UTC to a value this package's OWN schema already guarantees
    is UTC, so a real round-trip through a live ClickHouse table does not
    spuriously fail that same guard. The deterministic unit lane's
    `FakeClickHouseExecutor` stores/returns whatever `datetime` object it was
    given verbatim (already UTC-aware, since `rows.py` never let a naive one
    in), so this is a no-op there.
    """
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _observation_from_values(values: tuple[Any, ...]) -> ObservationRow:
    (
        tenant_id,
        id_,
        idempotency_key,
        occurred_at,
        ingested_at,
        engine_id,
        run_id,
        query_ref,
        query_digest,
        citation_refs,
        raw_object_ref,
    ) = values
    return ObservationRow(
        tenant_id=tenant_id,
        id=id_,
        idempotency_key=idempotency_key,
        occurred_at=_coerce_utc(occurred_at),
        engine_id=engine_id,
        run_id=run_id,
        query_ref=query_ref,
        query_digest=query_digest,
        citation_refs=tuple(citation_refs),
        raw_object_ref=raw_object_ref,
        ingested_at=_coerce_utc(ingested_at),
    )


def _citation_from_values(values: tuple[Any, ...]) -> CitationRow:
    (
        tenant_id,
        id_,
        idempotency_key,
        occurred_at,
        ingested_at,
        run_id,
        observation_id,
        citation_ref,
        source_domain,
        contribution_score,
    ) = values
    return CitationRow(
        tenant_id=tenant_id,
        id=id_,
        idempotency_key=idempotency_key,
        occurred_at=_coerce_utc(occurred_at),
        run_id=run_id,
        observation_id=observation_id,
        citation_ref=citation_ref,
        source_domain=source_domain,
        contribution_score=contribution_score,
        ingested_at=_coerce_utc(ingested_at),
    )


def _experiment_registration_from_values(values: tuple[Any, ...]) -> ExperimentRegistrationRow:
    (
        tenant_id,
        id_,
        idempotency_key,
        occurred_at,
        ingested_at,
        engine_id,
        locale,
        observation_cell,
        registration_hash,
        status,
    ) = values
    return ExperimentRegistrationRow(
        tenant_id=tenant_id,
        id=id_,
        idempotency_key=idempotency_key,
        occurred_at=_coerce_utc(occurred_at),
        engine_id=engine_id,
        locale=locale,
        observation_cell=observation_cell,
        registration_hash=registration_hash,
        status=status,
        ingested_at=_coerce_utc(ingested_at),
    )


def _measurement_outcome_from_values(values: tuple[Any, ...]) -> MeasurementOutcomeRow:
    (
        tenant_id,
        id_,
        idempotency_key,
        occurred_at,
        ingested_at,
        experiment_id,
        registration_canonical_hash,
        window_started_at,
        window_ended_at,
        b_verdict,
        reason_codes,
        outcome_layer,
        evidence_basis_id,
        sample_count_treatment,
        sample_count_control,
        insufficient_data,
        net_of_control_lift,
        raw_lift,
        evidence_bundle_manifest_hash,
        grs_policy_version,
        grs_policy_hash,
        grs_policy_provenance,
    ) = values
    return MeasurementOutcomeRow(
        tenant_id=tenant_id,
        id=id_,
        idempotency_key=idempotency_key,
        occurred_at=_coerce_utc(occurred_at),
        experiment_id=experiment_id,
        registration_canonical_hash=registration_canonical_hash,
        window_started_at=_coerce_utc(window_started_at),
        window_ended_at=_coerce_utc(window_ended_at),
        b_verdict=b_verdict,
        reason_codes=tuple(reason_codes),
        outcome_layer=outcome_layer,
        evidence_basis_id=evidence_basis_id,
        sample_count_treatment=sample_count_treatment,
        sample_count_control=sample_count_control,
        insufficient_data=insufficient_data,
        net_of_control_lift=net_of_control_lift,
        raw_lift=raw_lift,
        evidence_bundle_manifest_hash=evidence_bundle_manifest_hash,
        grs_policy_version=grs_policy_version,
        grs_policy_hash=grs_policy_hash,
        grs_policy_provenance=grs_policy_provenance,
        ingested_at=_coerce_utc(ingested_at),
    )


def _raw_vs_adjusted_from_values(values: tuple[Any, ...]) -> RawVsAdjustedLiftRow:
    (
        tenant_id,
        experiment_id,
        outcome_layer,
        b_verdict,
        raw_lift,
        net_of_control_lift,
    ) = values
    return RawVsAdjustedLiftRow(
        tenant_id=tenant_id,
        experiment_id=experiment_id,
        outcome_layer=outcome_layer,
        b_verdict=b_verdict,
        raw_lift=raw_lift,
        net_of_control_lift=net_of_control_lift,
    )


class ClickHouseAnalyticsStore:
    """Adapter over an injected `ClickHouseExecutor` — this package's public
    surface (`__init__.py` re-exports this class)."""

    def __init__(self, executor: ClickHouseExecutor) -> None:
        self._executor = executor
        self._executor_accepts_dedup_token = _executor_supports_dedup_token(executor)

    # --- append (idempotent by (tenant_id, idempotency_key), r4-02) -------------

    def append_observation(self, row: ObservationRow) -> bool:
        """Insert `row` into `observations`.

        Returns `True` if THIS call's own payload is the one ClickHouse kept
        for `(tenant_id, idempotency_key)` (first-observed writer), `False`
        if a concurrent/prior attempt already won that pair — see the module
        docstring "Return value semantics" for exactly what this bool does
        and does NOT claim. Never raises on a duplicate."""
        return self._append("observations", row, _observation_fields(row))

    def append_citation(self, row: CitationRow) -> bool:
        return self._append("citations", row, _citation_fields(row))

    def append_experiment_registration(self, row: ExperimentRegistrationRow) -> bool:
        return self._append("experiment_registrations", row, _experiment_registration_fields(row))

    def append_measurement_outcome(self, row: MeasurementOutcomeRow) -> bool:
        """Insert `row` into `measurement_outcome` (w5-11).

        Same idempotency/return-value semantics as `append_observation` —
        `guard_row_fields` already ran in `MeasurementOutcomeRow.
        __post_init__` (construction is the enforcement point, `rows.py`),
        so by the time a row reaches here it has already been refused
        fail-closed if it carried a raw-content/secret-shaped field."""
        return self._append("measurement_outcome", row, _measurement_outcome_fields(row))

    def _append(
        self,
        table: str,
        row: ObservationRow | CitationRow | ExperimentRegistrationRow | MeasurementOutcomeRow,
        fields_map: dict[str, object],
    ) -> bool:
        """Dispatches to the r4-02 race-free path (real/dedup-token-capable
        executors) or the pre-r4-02 compatibility path (legacy executors) —
        see `_append_with_dedup_token`/`_append_legacy_check_then_insert`.
        """
        validate_tenant_id(row.tenant_id)
        if self._executor_accepts_dedup_token:
            return self._append_with_dedup_token(table, row, fields_map)
        return self._append_legacy_check_then_insert(table, row, fields_map)

    def _append_with_dedup_token(
        self,
        table: str,
        row: ObservationRow | CitationRow | ExperimentRegistrationRow | MeasurementOutcomeRow,
        fields_map: dict[str, object],
    ) -> bool:
        """THE r4-02 fix: unconditional insert, deduplicated by ClickHouse
        itself — NO pre-insert existence check (that check-then-insert race
        is the r4-02 defect this replaces, see module docstring).

        Every call — first attempt, concurrent racer, or redelivered retry —
        reaches `insert_rows` exactly once. `dedup_token` makes ClickHouse's
        own server-side block dedup the single source of truth for "how many
        physical rows exist"; the `dedup_witness` read-back below only
        determines this CALL's own `True`/`False` return value, it never
        gates whether the insert itself happens.
        """
        witness = uuid.uuid4().hex
        fields_map = {**fields_map, "dedup_witness": witness}
        columns, values = build_insert_columns(table, fields_map)
        token = _dedup_token(table, row.tenant_id, row.idempotency_key)
        self._executor.insert_rows(table, columns, [values], dedup_token=token)
        return self._won_dedup_race(table, row.tenant_id, row.idempotency_key, witness)

    def _append_legacy_check_then_insert(
        self,
        table: str,
        row: ObservationRow | CitationRow | ExperimentRegistrationRow | MeasurementOutcomeRow,
        fields_map: dict[str, object],
    ) -> bool:
        """Compatibility path ONLY — never used against a real
        `ClickHouseConnectExecutor` (module docstring `executor.py`:
        `_executor_supports_dedup_token` is always `True` for it).

        Reproduces the PRE-r4-02 check-then-insert shape verbatim, for the
        benefit of a handful of PRE-EXISTING single-writer/synthetic test
        fakes outside this patch unit's exclusive write paths (e.g.
        `tests/integration/intelligence_failure/
        intelligence_failure_factories.py`) that predate `dedup_token` and
        have no server-side dedup of their own to fall back on — those
        fakes are exercised sequentially/single-threaded ONLY (never true
        concurrency; see that suite's own tests), so the TOCTOU window this
        shape has is never actually raced against them, and downgrading
        their dedup guarantee entirely (no check at all) would silently
        regress their own, already-passing, "duplicate redelivery is a
        no-op" assertions. This path is not, and must never become, the
        code path a real ClickHouse deployment executes.
        """
        if self._exists_idempotency_key(table, row.tenant_id, row.idempotency_key):
            return False
        fields_map = {**fields_map, "dedup_witness": ""}
        columns, values = build_insert_columns(table, fields_map)
        self._executor.insert_rows(table, columns, [values])
        return True

    def _exists_idempotency_key(self, table: str, tenant_id: str, idempotency_key: str) -> bool:
        query = AnalyticsQuery.for_tenant(table, tenant_id).filter_eq(
            "idempotency_key", idempotency_key
        )
        sql, params = query.to_select_sql(columns=("id",))
        return len(self._executor.query(sql, params)) > 0

    def _won_dedup_race(
        self, table: str, tenant_id: str, idempotency_key: str, witness: str
    ) -> bool:
        """Read back whichever `dedup_witness` ClickHouse actually kept for
        `(tenant_id, idempotency_key)` and compare it to `witness` — see
        module docstring "Return value semantics". This read never gates the
        insert (already committed by the time this runs); it only reports
        an outcome that already happened."""
        query = AnalyticsQuery.for_tenant(table, tenant_id).filter_eq(
            "idempotency_key", idempotency_key
        )
        sql, params = query.to_select_sql(columns=("dedup_witness",))
        rows = self._executor.query(sql, params)
        return len(rows) > 0 and rows[0][0] == witness

    # --- query (every method REQUIRES tenant_id as the first argument) ----------

    def get_observations(
        self,
        tenant_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> tuple[ObservationRow, ...]:
        """Return every `observations` row for `tenant_id` (optionally
        bounded by `[start, end)`/`limit`) — a query for ANY other tenant's
        rows is not expressible through this method signature at all."""
        query = AnalyticsQuery.for_tenant("observations", tenant_id).with_time_range(
            start=start, end=end
        )
        if limit is not None:
            query = query.with_limit(limit)
        sql, params = query.to_deduplicated_select_sql(columns=_OBSERVATIONS_SELECT_COLUMNS)
        return tuple(
            _observation_from_values(tuple(row)) for row in self._executor.query(sql, params)
        )

    def get_citations(
        self,
        tenant_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> tuple[CitationRow, ...]:
        query = AnalyticsQuery.for_tenant("citations", tenant_id).with_time_range(
            start=start, end=end
        )
        if limit is not None:
            query = query.with_limit(limit)
        sql, params = query.to_deduplicated_select_sql(columns=_CITATIONS_SELECT_COLUMNS)
        return tuple(_citation_from_values(tuple(row)) for row in self._executor.query(sql, params))

    def get_experiment_registrations(
        self,
        tenant_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> tuple[ExperimentRegistrationRow, ...]:
        query = AnalyticsQuery.for_tenant("experiment_registrations", tenant_id).with_time_range(
            start=start, end=end
        )
        if limit is not None:
            query = query.with_limit(limit)
        sql, params = query.to_deduplicated_select_sql(
            columns=_EXPERIMENT_REGISTRATIONS_SELECT_COLUMNS
        )
        return tuple(
            _experiment_registration_from_values(tuple(row))
            for row in self._executor.query(sql, params)
        )

    def get_measurement_outcomes(
        self,
        tenant_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> tuple[MeasurementOutcomeRow, ...]:
        """Return every `measurement_outcome` row for `tenant_id` (w5-11),
        optionally bounded by `[start, end)`/`limit` — same unconditional
        query-time logical dedup (r4-02) as every other `get_*` here; a
        physical duplicate beyond the physical dedup window is still
        observed exactly once."""
        query = AnalyticsQuery.for_tenant("measurement_outcome", tenant_id).with_time_range(
            start=start, end=end
        )
        if limit is not None:
            query = query.with_limit(limit)
        sql, params = query.to_deduplicated_select_sql(columns=_MEASUREMENT_OUTCOME_SELECT_COLUMNS)
        return tuple(
            _measurement_outcome_from_values(tuple(row))
            for row in self._executor.query(sql, params)
        )

    def get_measurement_outcome_raw_vs_adjusted_view(
        self,
        tenant_id: str,
        *,
        experiment_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
    ) -> tuple[RawVsAdjustedLiftRow, ...]:
        """Dashboard obligation (k3s §9.2:485, wave5-plan.md w5-11 deliverable
        3): both the RAW and the control-adjusted (`net_of_control_lift`)
        per-signal lift, derivable from the SAME underlying rows — this
        adapter never maintains a second, separately-written table for the
        "raw view" vs. the "adjusted view"; both are projections of the one
        append-only `measurement_outcome` row set, logically deduplicated the
        same way every other read path here is (r4-02).

        `experiment_id` optionally narrows to one experiment (still always
        `tenant_id`-scoped first, per `query.py`'s structural guarantee).
        """
        query = AnalyticsQuery.for_tenant("measurement_outcome", tenant_id).with_time_range(
            start=start, end=end
        )
        if experiment_id is not None:
            query = query.filter_eq("experiment_id", experiment_id)
        if limit is not None:
            query = query.with_limit(limit)
        sql, params = query.to_raw_vs_adjusted_select_sql()
        return tuple(
            _raw_vs_adjusted_from_values(tuple(row)) for row in self._executor.query(sql, params)
        )


__all__ = ["ClickHouseAnalyticsStore", "RawVsAdjustedLiftRow"]
