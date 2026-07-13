# packages/vector-store

## Purpose

`saena-vector-store` (module `saena_vector_store`) — the `VectorStore` port
Wave 4's demand-graph/claim-evidence/entity-resolution retrieval capability
sits behind (w4-07). Ships the port itself, a deterministic in-memory
reference backend, one deterministic offline test embedder, and ONE real
concrete backend (pgvector, over Postgres) for CI verification.

## Authority

- ADR-0007 §4-5 rev.2 — "Vector = 제품별 collection·namespace 결정": the
  per-product (`collection`) namespacing axis this package's
  `record.collection_key()` implements.
- `docs/architecture/data-ownership.md` row 28 — "Qdrant/pgvector |
  retrieval | tenant partition | demand-graph/claim-evidence/
  entity-resolution 소유 파티션 분리": tenant is the hard isolation axis
  (every port method takes `tenant_id` as a REQUIRED first parameter — see
  `port.py`), the three named services are the intended callers/owners of
  the data flowing through this port (this package itself owns none of
  their domain data — it is infrastructure they sit on top of).
- `docs/architecture/tenancy-model.md` — tenant_id hard isolation boundary
  convention this package's tenant-required API + `TenantIsolationError`
  mirror.

## Backend choice: pgvector implemented here, Qdrant equally authorized

The Qdrant-vs-pgvector CHOICE is explicitly **OPEN** (`SAENA_AEO_Algorithm_
and_Harness_Design_v1.md` §398) — this package does NOT standardize the
product on either backend. `PgVectorStore` (`pgvector/adapter.py`) is the
one concrete backend shipped by this patch unit, chosen purely for CI cost:
it reuses this repo's existing real-Postgres testcontainer convention
(ADR-0017, the same pattern `tests/integration/persistence_postgres/`
already established), so `tests/integration/vector/` can prove the port
against a REAL backend without adding a new kind of test infrastructure to
CI. A Qdrant adapter behind the exact same `port.VectorStore` Protocol is
equally authorized and can be added by a future patch unit without any
change to `port.py`, `record.py`, or any caller — every caller only ever
depends on the `VectorStore` Protocol, never on `PgVectorStore` directly.

## Embedding provider: OPEN, production-only

Which embedding model/provider a production caller uses is an OPEN decision
this package does not make. The only embedder shipped here,
`embedder.TestEmbedder`, is deterministic/seeded and fully offline (SHA-256
+ L2-normalization, stdlib only) — used exclusively so this package's own
tests (and any caller's tests) never depend on network access, an external
provider's credentials, availability, or cost. A real provider integration
is out of scope for this patch unit.

## Tenant isolation guarantee

Every `VectorStore` method takes `tenant_id` as a **required, first,
positional** parameter — there is no default, no keyword-only bypass, and
no alternate entry point. Every concrete backend applies the tenant filter
**inside** its own storage lookup (a dict key component for
`InMemoryVectorStore`, a SQL `WHERE tenant_id = ...` clause for
`PgVectorStore`) rather than as a post-hoc filter over an already
tenant-unaware result — a numerically-nearer vector belonging to a
different tenant is never even a candidate for `search`, so it structurally
cannot leak regardless of distance. See `port.py`'s module docstring and
`tests/integration/vector/test_pgvector_store.py`'s cross-tenant NN-leakage
negative test for the proof against a real backend.

An additional "forged tenant id" guard
(`record.ensure_caller_owns_record`) rejects any `VectorRecord` whose own
`tenant_id` field disagrees with the caller-supplied `tenant_id` argument,
before any write reaches storage under either tenant.

## Dimension safety

- `VectorRecord.__post_init__` (`record.py`) fails closed if
  `len(vector) != embedding.dimension` — a record can never even be
  constructed inconsistently.
- `InMemoryVectorStore` tracks the dimension established per
  `(tenant_id, collection)` by the first upsert and rejects any later
  upsert/search whose dimension disagrees (`DimensionMismatchError`).
- `PgVectorStore` bakes its dimension into the `vector(N)` Postgres column
  type at `create_schema()` time (pgvector has no dimension-agnostic column
  type); a mismatched vector is rejected by Postgres itself, and the raw
  driver error is translated into the package's own `DimensionMismatchError`
  (never leaked as a raw `asyncpg`/SQLAlchemy exception) — see
  `pgvector/adapter.py`'s module docstring.

## Stale-vector invalidation

An upsert whose `source_snapshot_hash` differs from the currently-active
record's own hash supersedes the old version (`superseded=True`,
`superseded_by_hash` set) rather than overwriting it in place — full
version history stays retrievable via `list_versions`. `invalidate_snapshot`
lets a caller proactively supersede every active record derived from a
given (now-stale) source snapshot hash, ahead of re-embedding. An upsert
whose hash matches the currently-active record's is treated as an
idempotent replay (no-op).

## Packaging note (Integrator actions)

This patch unit's exclusive write paths are `packages/vector-store/**`,
`tests/unit/vector_store/**`, `tests/integration/vector/**` only — root
config (`pyproject.toml` `[tool.uv.workspace]` members, dev-group
dependency, `[tool.mypy]` files, `[tool.coverage.run]` source,
`.importlinter` `root_packages`) is out of scope (mirrors `tools/forgectl`'s
own w2-19 -> w2-20 precedent, see `tools/forgectl/README.md` "Packaging
note"). Until an Integrator registers `saena-vector-store` as a workspace
member:

- `tests/unit/vector_store/conftest.py` and `tests/integration/vector/
  conftest.py` both insert `packages/vector-store/src` onto `sys.path`
  directly so `import saena_vector_store` resolves without an editable
  install.
- `sqlalchemy`/`asyncpg` are already present in the shared workspace venv
  as transitive dependencies of `saena-domain` — no new dependency had to
  be installed to verify this unit locally, but the Integrator should still
  add this package's own `pyproject.toml` dependencies explicitly to root
  `[tool.uv.sources]`/the dev dependency group when registering it, rather
  than relying on that transitive coincidence long-term.
- Add `saena_vector_store` to `.importlinter` `root_packages` with a
  boundary contract (likely: may be imported by `demand-graph`,
  `claim-evidence`, `entity-resolution` services; must not import
  `saena_domain` or any service — this package is infrastructure, not
  domain logic).

## Testing

- `tests/unit/vector_store/**` — deterministic, in-process only (record
  model invariants, dimension checks, tenant-required API signature
  introspection, provenance/stale-invalidation semantics against
  `InMemoryVectorStore`).
- `tests/integration/vector/**` — real Postgres + `CREATE EXTENSION
  vector` via testcontainers (`pytest.mark.integration`; honest
  Docker-unavailable skip, mirroring `tests/integration/
  persistence_postgres/conftest.py`'s own probe): upsert/search round-trip,
  cross-tenant NN-leakage negative, dimension-mismatch rejection, stale
  invalidation — all against `PgVectorStore`.

```bash
uv run pytest tests/unit/vector_store -q
uv run pytest -m integration tests/integration/vector -q -p no:cacheprovider
```

## Source specification references

- `docs/decisions/ADR-0007-final-synthesis-ownership-topology.md` §4-5 rev.2
- `docs/architecture/data-ownership.md` row 28
- `docs/architecture/tenancy-model.md`
- `SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §398 (Qdrant-vs-pgvector OPEN)
