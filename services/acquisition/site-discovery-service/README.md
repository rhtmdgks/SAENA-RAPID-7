# site-discovery-service

| Field | Value |
|---|---|
| Service name | `site-discovery-service` |
| Bounded context | Technical site inventory |
| Primary responsibility | route, framework, render, robots, canonical, sitemap audit |
| Owned data | site inventory |
| Consumed contracts | repository manifest; site URLs |
| Published events | site.inventory.completed.v1 |
| Consumed events | repo.intaken.v1 |
| Upstream dependencies | repository-intake-service |
| Downstream consumers | demand-graph-service; intervention-generator-service |
| Security boundary | read-only discovery; untrusted web content quarantine |
| Planned runtime | k3s Deployment (CONFIRMED intent) |
| Domain area | `acquisition` |
| Implementation status | **PARTIAL — W3 minimal (w3-05)** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4
- `docs/architecture/execution-runtime.md` (`JobKind.SITE_DISCOVERY`'s pool/read-only/ServiceAccount/resource-limit profile, w3-01 foundation)
- `docs/architecture/contract-catalog.md` row 37 (`ContentRecord`, P1 — no `packages/contracts` schema yet)
- ADR-0004 (browser pool, "read-only 크롤, Git credential 미발급" sub-profile)

## Status

PARTIAL (w3-05) — `saena_site_discovery` package implements, for
`JobKind.SITE_DISCOVERY`, a W3 MINIMAL (fake-adapter-only, no real
crawler/browser-pool client) read-only site inventory pass:

- `SiteCrawlerPort` (`crawler.py`): structurally read-only crawl adapter
  Protocol (`check_robots`/`fetch_route` only — no write/mutate method
  exists) + `FakeSiteCrawler`, the only implementation this patch unit
  ships (no real network/browser I/O; a real Playwright/browser-pool
  client is **W4**).
- `ContentRecordProjection` (`records.py`): immutable, frozen per-route
  inventory record (render mode, robots, canonical, sitemap, structured-data
  presence) carrying an opaque `evidence_ref` (never raw fetched content) —
  this service's own `ContentRecord`-**like** projection, not the eventual
  formal P1 `ContentRecord` contract itself (no `packages/contracts` schema
  exists for it yet).
- `run_site_discovery` (`inventory.py`): the pipeline — robots/policy
  boundary hook (a disallow skips + records, NEVER fetches), bounded retry
  on transient fetch failures, rate/timeout enforcement via
  `CrawlBudget`/`crawl_budget_for` (derived from
  `saena_domain.execution.resource_limits_for(JobKind.SITE_DISCOVERY)`),
  per-route audit trail (`AuditEntry`), and the `site.inventory.completed.v1`
  event payload (via `saena_domain.execution.build_site_inventory_completed_payload`).
- `InMemorySiteInventoryStore` (`store.py`): tenant-scoped observation
  store — cross-tenant put/get is rejected (`CrossTenantObservationError`),
  mirroring `saena_artifact_registry.blobstore`'s gating discipline.

NOT in this patch unit's scope (W4 or later, deliberately not
implemented): a real crawler/browser-pool client, demand-graph/
intervention-generator consumption, any scoring/recommendation/learning
over captured records, ClickHouse/vector storage, a k3s Deployment
manifest or Dockerfile. This package is also NOT YET a root `uv` workspace
member (see `pyproject.toml`'s own note) — registering it is the
Integrator's job at merge time.
