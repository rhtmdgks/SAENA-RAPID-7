# saena-analytics-clickhouse

ClickHouse analytical-store adapter + migrations (w4-06, Wave 4; query
privacy boundary fix — r4-04, Wave 4 remediation).

## Spec basis

- ADR-0007 rev.2 §4-5 ("Tenant discriminator vs physical partition"):
  ClickHouse = **time partition** + `ORDER BY (tenant_id, …)` prefix —
  per-tenant partition is **FORBIDDEN** (high-cardinality partition
  explosion).
- `docs/architecture/data-ownership.md` Store classes table: ClickHouse =
  event/observation/metrics analytics, append-only, one table per owning
  domain (chatgpt-observer ROL, citation-intelligence, experiment-attribution).
- `docs/architecture/tenancy-model.md` / `security-model.md`: every
  tenant-scoped record carries `tenant_id`; cross-tenant access target is
  **0**.

## Table inventory

| Table | Owner | Partition | ORDER BY | Idempotency key |
|---|---|---|---|---|
| `observations` | chatgpt-observer (ROL) | `toYYYYMM(occurred_at)` | `(tenant_id, occurred_at, id)` | `(tenant_id, idempotency_key)` |
| `citations` | citation-intelligence-service | `toYYYYMM(occurred_at)` | `(tenant_id, occurred_at, id)` | `(tenant_id, idempotency_key)` |
| `experiment_registrations` | experiment-attribution | `toYYYYMM(occurred_at)` | `(tenant_id, occurred_at, id)` | `(tenant_id, idempotency_key)` |

Every table:

- `ENGINE = MergeTree` (append-only; dedup is enforced at the **adapter**
  layer via an existence check before INSERT, not by
  `ReplacingMergeTree`/`Collapsing*` — those merge asynchronously and cannot
  guarantee read-your-own-write dedup without a `FINAL` modifier).
- `PARTITION BY toYYYYMM(occurred_at)` — a documented interpretation of the
  authority's "시간 파티션" mandate (ADR-0007 rev.2 does not itself spell out
  an exact expression); a future patch unit may replace it with a different
  granularity via an additive migration if the authority is amended.
- `ORDER BY (tenant_id, occurred_at, id)` — `tenant_id`-prefixed, per
  ADR-0007 rev.2 §5. The partition expression never references `tenant_id`.
- Row models carry **metadata/hash/ref columns only** — never raw
  response/screenshot/source content (`rows.py`, guarded fail-closed by
  `guard.py`'s `guard_row_fields`, called from every row's `__post_init__`).

See `schema.py` for the exact DDL and `MIGRATIONS` (a single, reversible
`Migration` entry as of this patch unit — `migrate_up`/`migrate_down`).

## Query privacy boundary (r4-04, round 2)

`observations.query_text String` (the pre-r4-04 column) stored the raw
customer query VERBATIM — a `data-ownership.md` Constraints violation ("No
PII/secrets in event payloads — object refs + access policy") that
`guard.py`'s SHAPE-only heuristic never caught (an ordinary sentence
carrying an email/phone/customer name has no oversize/secret-pattern/
forbidden-name shape). Fixed by replacing that column outright with:

- `query_ref String` (required) — an opaque, KEYED reference
  `query://<tenant_id>/<hmac_sha256_hex>`, mirroring `saena_chatgpt_observer.
  artifact_gateway.RawArtifactGatewayPort`'s "single gateway, ref only, raw
  content never leaves the gateway" discipline. Derive with
  `query_privacy.derive_query_ref(tenant_id=..., raw_query=...)`.
- `query_digest Nullable(String)` (optional) — a KEYED HMAC-SHA256
  pseudonymous digest, only present when a caller has an actual
  cross-run/cross-tenant query-correlation need. Derive with
  `query_privacy.derive_query_digest(raw_query=...)`.

**Round 2 (independent-critic MUST-FIX, both closed):** the FIRST version of
this fix derived `query_ref` from a PLAIN, UNKEYED `sha256(raw_query)` with
`tenant_id` used only as a cosmetic path prefix — (1) trivially reversible
by dictionary/brute-force attack for a low-entropy natural-language query,
and (2) the SAME query under two different tenants produced the SAME hash,
a cross-tenant correlation leak. `derive_query_ref` is now KEYED by the SAME
mechanism as `derive_query_digest`, with `tenant_id` INSIDE the HMAC input
(not a cosmetic prefix) — the SAME query under two different tenants, even
with the SAME key, now yields two DIFFERENT `query_ref` values, and reversal
requires the signing key.

Both `derive_query_ref`/`derive_query_digest` **fail closed**
(`MissingQuerySigningKeyError`) if the HMAC key is not resolvable via a
runtime `QuerySigningKeyRef` (env var `SAENA_ANALYTICS_QUERY_SIGNING_KEY`,
never committed) — neither function ever falls back to an unkeyed hash (an
unkeyed SHA-256 of a low-entropy natural-language query is reversible by
dictionary attack — see `query_privacy.py`'s module docstring for the full
rationale). `query_ref` is consequently ALWAYS required and ALWAYS keyed;
there is no keyless code path for either field.

The raw query itself never reaches `ObservationRow`/`observations` in any
form — a caller still holding the raw query (e.g. intelligence processing
upstream, transiently, in memory) must derive a `QueryRef`/`QueryDigest`
BEFORE constructing the row; there is no field on `ObservationRow` that
accepts raw query text any more. This is a same-commit `CREATE TABLE`
column swap (not an additive migration) — valid only because no Wave-4
data has reached a real production deployment through this still-
unreleased schema; see `schema.py`'s "r4-04" migration note for the exact
format-boundary record.

## Adapter API

`ClickHouseAnalyticsStore` (`store.py`) is the package's public adapter,
constructed over an injected `ClickHouseExecutor` (`executor.py`, a
`typing.Protocol` seam — see "Testing" below).

- `append_observation(row: ObservationRow) -> bool`
- `append_citation(row: CitationRow) -> bool`
- `append_experiment_registration(row: ExperimentRegistrationRow) -> bool`
  - Each returns `True` on a new INSERT, `False` on an idempotent-replay
    no-op keyed by `(tenant_id, idempotency_key)`.
- `get_observations(tenant_id, *, start=None, end=None, limit=None) -> tuple[ObservationRow, ...]`
- `get_citations(tenant_id, *, start=None, end=None, limit=None) -> tuple[CitationRow, ...]`
- `get_experiment_registrations(tenant_id, *, start=None, end=None, limit=None) -> tuple[ExperimentRegistrationRow, ...]`
  - `tenant_id` is a **required, non-defaulted, first positional argument**
    on every query method — there is no code path in `query.py`'s
    `AnalyticsQuery.for_tenant` (the only way to build a `TenantScopedQuery`)
    capable of producing a SELECT without a `tenant_id` predicate baked in.
    A cross-tenant query is not expressible through this API at all — see
    `query.py`'s module docstring for the full structural argument.

Late/out-of-order events are tolerated unconditionally: this store enforces
no monotonicity constraint on `occurred_at`, only on `idempotency_key`
uniqueness — a late-arriving event simply lands in its own correct time
partition.

## Testing

- `tests/unit/analytics_clickhouse/` — deterministic, no container. An
  in-memory `FakeClickHouseExecutor`
  (`analytics_clickhouse_factories.py`) implements the `ClickHouseExecutor`
  Protocol with zero I/O.
- `tests/integration/clickhouse/` — real `clickhouse/clickhouse-server`
  testcontainer (`@pytest.mark.integration`; honest `skipif` when Docker is
  unreachable or `clickhouse-connect` is not yet installed — see that
  package's own `conftest.py`).

## Open decisions

**TTL / retention is OPEN.** No concrete retention value exists in
ADR-0007, `data-ownership.md`, `tenancy-model.md`, or `security-model.md`
(`security-model.md`'s own "LLM provider egress ... §13-4 retention 결정
대기" note confirms this is explicitly deferred, not merely unwritten). Per
instruction, **no `TTL` clause is emitted by any `CREATE TABLE`** in
`schema.py` — this is recorded here as a **production-only** decision that
requires explicit human approval before a real deployment ships without a
retention policy; do not silently invent one.

## Integrator notes (registration required before this package is usable)

This package is **not yet a registered root workspace member** — see
`pyproject.toml`'s own "UPDATE (Integrator, at integration time)" comment
for the exact root `pyproject.toml` / `.importlinter` edits required
(`[tool.uv.workspace] members`, `[dependency-groups] dev`,
`[tool.uv.sources]`, `[tool.mypy] files`, `[tool.coverage.run] source`,
`.importlinter root_packages` + a standalone-leaf contract pair). Until
that registration lands, `clickhouse-connect` (this package's only
third-party runtime dependency) is not present in the shared `uv.lock`,
and the `tests/integration/clickhouse` lane self-skips with an honest,
distinct reason (see that package's `conftest.py`).
