# chatgpt-observer-service

| Field | Value |
|---|---|
| Service name | `chatgpt-observer-service` |
| Bounded context | ChatGPT Search observation |
| Primary responsibility | approved ChatGPT Search observation; raw snapshot capture |
| Owned data | observation ledger (ROL) — **계약은 엔진 중립 `PlatformObservation`(+engine_id), 본 서비스는 그 첫 구현체 (ADR-0007). 2번째 엔진 = 동일 계약의 신규 observer, core 재작업 0** |
| Consumed contracts | observation cells; locale/browser policy |
| Published events | observation.captured.v1 |
| Consumed events | plan.contract.approved.v1 (measurement phase); baseline registration (PROPOSED) |
| Upstream dependencies | engine-adapter-gateway; forge-console-api |
| Downstream consumers | citation-intelligence-service; experiment-attribution-service |
| Security boundary | rate-limited; ToS-compliant; approved observation only |
| Planned runtime | k3s Deployment + browser Jobs (CONFIRMED intent) |
| Domain area | `acquisition` |
| Implementation status | **PARTIAL — W3 minimal (w3-05)** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4
- `docs/architecture/execution-runtime.md` (`JobKind.CHATGPT_OBSERVER`'s pool/read-only/ServiceAccount/resource-limit profile, w3-01 foundation; also documents `observation.captured.v1`'s payload builder as deliberately deferred)
- `docs/architecture/contract-catalog.md` row 41 (`PlatformObservation`, P1 — no `packages/contracts` schema yet)
- ADR-0007 (`PlatformObservation` engine-neutral contract, chatgpt-observer as its first implementation)
- ADR-0013 (`engine_id` v1 closed enum — `chatgpt-search` only)
- ADR-0004 (browser pool, "No Git credential issued at all — observation only")
- CLAUDE.md "Engine scope (v1)" (Google AI Overviews / Google AI Mode / Gemini disabled)

## Status

PARTIAL (w3-05) — `saena_chatgpt_observer` package implements, for
`JobKind.CHATGPT_OBSERVER`, a W3 MINIMAL (fake-adapter-only, no real
browser pool) read-only observation capture:

- `ObservationSourcePort` (`source.py`): structurally read-only capture
  adapter Protocol (`capture_observation` only — no write/publish/mutate
  method exists) + `FakeObservationSource`, the only implementation this
  patch unit ships. The real ChatGPT Search browser-pool session
  (Playwright fleet, ToS-compliant rate-limited automation) is explicitly
  **W4**, out of scope.
- `PlatformObservation` (`observation.py`): immutable, frozen capture
  record — `engine_id` is guarded to the v1 closed enum's sole permitted
  value (`chatgpt-search`) via `saena_domain.execution.guard_engine_id` at
  construction time (`google-aio`/`google-ai-overviews`/`google-ai-mode`/
  `gemini`/anything else raises). Carries an opaque `raw_object_ref` (never
  raw captured content) and `citation_refs` (zero citations is a valid
  signal, never rejected) — this service's own engine-neutral capture
  shape (ADR-0007's "첫 구현체"), not the eventual formal P1
  `PlatformObservation` contract itself (no `packages/contracts` schema
  exists for it yet).
- `run_chatgpt_observation` (`capture.py`): the pipeline — engine guard
  BEFORE any capture call, bounded retry on transient capture failures,
  rate/timeout enforcement via `ObservationBudget`/`observation_budget_for`
  (derived from
  `saena_domain.execution.resource_limits_for(JobKind.CHATGPT_OBSERVER)`),
  and per-query audit trail (`AuditEntry`). Deliberately builds NO event
  payload — `observation.captured.v1` is named in
  `docs/architecture/execution-runtime.md` "Deferred to later units" (it
  requires `payload.engine_id`, unlike the 4 events w3-01 already builds);
  this patch unit does not add it either.
- `InMemoryObservationStore` (`store.py`): tenant-scoped observation
  store — cross-tenant put/get is rejected (`CrossTenantObservationError`).

NOT in this patch unit's scope (W4 or later, deliberately not
implemented): a real browser-pool/Playwright client,
`observation.captured.v1`'s own event payload builder,
citation-intelligence/experiment-attribution analysis, any 2nd-engine
(Google/Gemini) adapter, a k3s Deployment manifest or Dockerfile. This
package is also NOT YET a root `uv` workspace member (see `pyproject.toml`'s
own note) — registering it is the Integrator's job at merge time.
