# Execution runtime — Wave 3 bounded context

## Purpose

Fixes the shared execution-domain layer (`packages/domain/src/saena_domain/execution/`)
that all five Wave 3 job kinds build on, and the bounded-context boundary
between that layer, the W2-runtime Temporal orchestrator, and the 5
job-owning services this Wave introduces (agent-runner, repository-intake,
quality-eval, chatgpt-observer, site-discovery — canonical names per k3s spec
§5.2 and ADR-0004).

## Scope

In: the `JobKind` closed vocabulary and its pool/ServiceAccount/read-only
boundary facts; the mandatory `JobContext` execution identity; the job
lifecycle state machine; the canonical `JobError` value object; per-`JobKind`
resource-limit defaults; heartbeat/cancellation/progress `typing.Protocol`
interfaces (shape only, no implementation); the v1 engine guard; event
payload builders for the 4 CONFIRMED job-kind events; the import/dependency
policy this package holds itself to.

Out: any actual K8s Job manifest/Helm template (deploy/**, owned elsewhere);
any service-side implementation of the heartbeat/cancellation/progress
Protocols (later Wave 3 units, one per job kind); the `chatgpt-observer`
job's own event (`observation.captured.v1`) payload builder (deliberately
left for the unit that owns that service — see "Deferred to later units"
below); Temporal workflow/Activity code itself (owned by
`services/platform/agent-orchestrator-service`, W2B).

## Current decision

### The 5 Wave 3 jobs — responsibilities + ServiceAccount mapping

ADR-0004 ("Node pool revision — untrusted Jobs and compute pool") is the
authority for all 5 rows below: item 1 puts agent-runner, repository-intake,
and quality-eval on the `runner` k3s worker pool ("customer source를 다루는
모든 Job은 runner pool 상속") with a 3-way ServiceAccount split; item 2 puts
chatgpt-observer and site-discovery on the `browser` pool with differentiated
permissions.

| Job kind (`JobKind`) | Pool | Git write? | Responsibility | Producer id (AsyncAPI) | Its event |
|---|---|---|---|---|---|
| `AGENT_RUNNER` | `runner` | **Yes** — worktree write, **contract-scope files only** (ADR-0004: "worktree write, 계약 범위 파일만") | Executes an approved `ChangePlan`/Action Contract's patch units inside a per-run isolated worktree | `agent-runner-service` | `patch.unit.completed.v1` |
| `QUALITY_EVAL` | `runner` | **No** — build/test execution only (ADR-0004: "빌드 실행 권한만, Git write 없음"); egress restricted to the approved package registry | Runs the build/test/lint gates a `PatchArtifact` must pass before it can be declared verified | `quality-eval-service` | `quality.gate.passed.v1` / `quality.gate.failed.v1` |
| `REPOSITORY_INTAKE` | `runner` | **Read-only Git only** (ADR-0004: "repository-intake: read-only Git만") | Clones/snapshots a customer repository, runs SBOM/secret scanning, captures a `SourceSnapshot` | `repository-intake-service` | `repo.intaken.v1` |
| `CHATGPT_OBSERVER` | `browser` | No Git credential issued at all (observation only) | Runs ChatGPT Search observation sessions (v1 sole engine, `engine_id="chatgpt-search"`) and captures citations/observations | `chatgpt-observer-service` | `observation.captured.v1` (payload builder deferred — see below) |
| `SITE_DISCOVERY` | `browser` | Read-only crawl, no Git credential (ADR-0004: "read-only 크롤, Git credential 미발급 sub-profile") | Crawls/inventories a customer site/domain, publishes a `SiteContext` inventory pass | `site-discovery-service` | `site.inventory.completed.v1` |

This module's `read_only` field on `JobKindProfile`
(`saena_domain.execution.job_kind`) encodes the **Git-write** column above
specifically, not general filesystem read-only-ness — `QUALITY_EVAL` still
writes to an ephemeral build directory, it simply never has Git write
capability. `saena_domain.execution.limits.DEFAULT_RESOURCE_LIMITS` carries
k3s spec §5.3's 4 named per-Job budget fields
(`active_deadline_seconds`/`max_retries`/`max_artifact_mib`/`max_cost_usd`)
per kind; only `AGENT_RUNNER`'s numbers are sourced verbatim from
`deploy/charts/saena-forge/values.yaml` today (`activeDeadlineSeconds: 7200`,
`maxCostUsdPerRun: 100`, `maxArtifactsMiBPerRun: 1024`) — the other 4 kinds'
defaults are this module's own reasoned proposal pending each service's own
Helm values section (see that module's docstring for the full sourcing
caveat — this is a deliberate, documented gap, not a silent invention of
CONFIRMED ops config).

### Deferred to later units

- Service-side implementations of `HeartbeatSink` / `CancellationSignal` /
  `ProgressReporter` (`saena_domain.execution.protocols`) — this package
  fixes the call shape only.
- `observation.captured.v1`'s own payload builder for `CHATGPT_OBSERVER`
  (out of this patch unit's named 4-event list; that event also requires
  `payload.engine_id`, unlike the 4 built here — see
  `saena_domain.execution.events` module docstring).
- Any actual k3s Job manifest, ServiceAccount RBAC binding, or NetworkPolicy
  wiring the `service_account`/`pool` facts in `JOB_KIND_PROFILES` describe —
  those live in `deploy/**`, out of this package's write scope.
- Reconciling the 4 non-`AGENT_RUNNER` `JobKind`s' `ResourceLimits` defaults
  against each owning service's own future Helm values section.

## The W2-runtime connection boundary — orchestrator Activity → runner job

`services/platform/agent-orchestrator-service` (W2B) already defines the
Temporal-side half of this boundary:

- Its `ExecutionWorkflow` signals `WAITING_APPROVAL -> EXECUTING` only on a
  verified `plan.contract.approved` decision (ADR-0003 dual-verification —
  Policy Gate pre-verification is authoritative, Temporal's own
  re-verification is defense-in-depth).
- On reaching `EXECUTING`, the workflow calls
  `run_execution_activity(ExecutionActivityInput)` — currently a STUB
  (`services/platform/agent-orchestrator-service/src/saena_orchestrator/activities.py`,
  explicit module docstring: "real execution = W3") that only proves the
  heartbeat contract is live end-to-end. **This Activity call is the exact
  seam a later Wave 3 unit plugs the real `AGENT_RUNNER` k3s Job launch
  behind** — the Activity's signature (`ExecutionActivityInput` /
  `ExecutionActivityResult`) does not change when the stub is replaced with
  real Job-launch + poll logic; only the body does.
- `services/platform/agent-orchestrator-service/src/saena_orchestrator/timeouts.py`
  already fixes the Activity-side timing contract this package's
  `AGENT_RUNNER` `ResourceLimits.active_deadline_seconds` (7200) must stay
  coherent with: `ACTIVITY_START_TO_CLOSE_TIMEOUT_SECONDS >=
  RUNNER_JOB_ACTIVE_DEADLINE_SECONDS(7200) + buffer`
  (`docs/architecture/resilience.md`'s "Temporal Activity <-> K8s Job 정합"
  formula), with `HEARTBEAT_TIMEOUT_SECONDS` a small fraction of that
  start-to-close bound. A later unit wiring the real `AGENT_RUNNER` Job
  behind `run_execution_activity` MUST heartbeat at least that often via a
  `HeartbeatSink` implementation (this package's Protocol) or the Activity's
  own liveness detection starves before the Job's real deadline is reached.
- `blob 단일 관문` (single blob gateway) discipline: `activities.py`'s own
  docstring already establishes that Activity code never talks to blob
  storage directly — artifacts are referenced only by an opaque
  `manifest_ref`, resolved exclusively through `artifact-registry-service`'s
  published contract. Any later unit's runner-Job-launch implementation
  inherits this constraint unchanged; this package does not relax it.

In short: **the orchestrator (W2B) owns "when to start a job and how to wait
for it"; this package (`saena_domain.execution`, W3) owns "what a job's
identity/lifecycle/errors/limits/events look like"; a later Wave 3 unit owns
"how a job kind's service actually launches and runs the k3s Job."** None of
those three concerns collapse into another.

## Skill-bundle content integrity (F-5, k3s §10) — the two-boundary gate

`saena_domain.execution.skill_bundle` is the dedicated, pure skill-bundle
content-integrity verifier (distinct from the whole-ActionContract
`contract_hash` pin, which cannot see individual skill-file tampering). It
computes a deterministic `sha256:<hex>` over the bundle's framed manifest — the
k3s §9.1 run-trace `skill_bundle_hash` field / Helm `skillBundle.digest` — and
fails closed on byte change / file add / delete / rename / missing bundle /
missing-or-malformed pin / symlink / traversal.

It is enforced at **two boundaries**, each fail-closed and BEFORE any tool /
worktree / executor. The gate is **MANDATORY**: a *missing* pin is a DENY, not
a skip — there is no "no bundle → proceed" path (that would be fail-open: a run
with an unverified/absent bundle could execute).

- **agent-runner** (`saena_agent_runner.skill_bundle.enforce_skill_bundle_
  integrity`, called inside `PatchUnitRunner.run` after approval, before the
  first worktree). agent-runner imports the pure verifier directly (services →
  `saena_domain` is allowed). Because an agent-runner run always executes
  skill-derived commands, the pin AND source are UNCONDITIONALLY required:
  `expected_skill_bundle_hash=None` → `SkillBundleHashMissingError`; a None
  `skill_bundle_source` → `SkillBundleMissingError`; both DENY before any
  worktree. There is no waiver.
- **hooks-runtime `session_start`** — via an injected `SkillBundleIntegrityPort`.
  hooks-runtime is a stdlib-only leaf and CANNOT import `saena_domain`, so the
  concrete adapter (wrapping `verify_skill_bundle`) is supplied by the runtime
  host; hooks-runtime defines the Port + the fail-closed enforcement. The gate
  is UNCONDITIONAL — there is NO opt-out flag. `SessionStartInput` makes
  `expected_skill_bundle_hash` and `skill_bundle_port` REQUIRED fields (no
  default): an execution session cannot even be constructed without them, and a
  None pin / None port / raising adapter each DENY at runtime. The input type
  cannot express "skip the bundle gate" — a genuinely non-executing session
  would require a SEPARATE input type + entry point that this execution
  `session_start` cannot accept (none exists; there is no non-executing
  session-start caller). (agent-runner likewise has no waiver — it always
  executes.)

The `contract_hash` pin is retained as a complementary defense; it does not
substitute for bundle verification. Wiring the two independent implementations
of the same house canonicalization (contract-hash vs bundle-hash) is proven
connected by `tests/unit/domain_execution/test_skill_bundle_hooks_wiring.py`.

## Dependency / import policy

`saena_domain.execution` may import, within `saena_domain`, only:

- `saena_domain.identity` — reuses `TenantId` (tenant_id format/immutability,
  ADR-0014) inside `JobContext.__post_init__` rather than re-implementing the
  slug pattern a second time.
- `saena_domain.events` — read-only consumption is available (e.g. the
  AsyncAPI topic/producer catalog via `saena_domain.events._topics` in this
  package's own unit tests, to assert `JobKindProfile.producer_id` values
  stay in sync with the CONFIRMED catalog) but this package's production
  code does NOT depend on `saena_domain.events` at import time — event
  *payload* construction (`saena_domain.execution.events`) reuses the same
  generated `saena_schemas.event.*` pydantic models
  `saena_domain.events.factory.EVENT_PAYLOAD_MODELS` binds, imported
  directly from `saena_schemas` (a leaf package both modules already depend
  on), rather than importing `saena_domain.events` itself — this keeps
  `saena_domain.execution` free to be imported by, or to evolve alongside,
  `saena_domain.events` without a direct package-level dependency edge
  between two sibling `saena_domain` submodules.
- `saena_domain.policy` / `saena_domain.audit` — not imported by any module
  in this patch unit's initial delivery, but permitted per this package's
  mission scope (a later unit may need `saena_domain.audit`'s canonical JSON
  helpers, or `saena_domain.policy`'s transition style, without requiring a
  fresh ADR).
- `saena_schemas` / `saena_shared` — leaf packages, as every `saena_domain`
  submodule may already import.

`saena_domain.execution` imports NOTHING outside `saena_domain`/
`saena_schemas`/`saena_shared` — no service package, no `saena_observability`,
no `saena_testing`. This is enforced today by the repo-wide
`domain-below-services` `.importlinter` contract (source: `saena_domain`,
forbidden: every service + `saena_observability` + `saena_testing` +
`saena_forgectl`), which already covers this new submodule since
`.importlinter`'s `saena_domain` `source_modules` entry is package-level, not
per-submodule — this patch unit adds no new `.importlinter` contract (that
file is outside this unit's exclusive write paths) and needs none.

**Nothing imports `saena_domain.execution` back** in this patch unit — it is
a new leaf-ward addition under the existing `saena_domain` package, consumed
only by later Wave 3 service units (agent-runner-service,
repository-intake-service, quality-eval-service, chatgpt-observer-service,
site-discovery-service), none of which exist as importable packages yet.

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §5.2 (worker pool
  table), §5.3 (resource policy — `activeDeadlineSeconds`/max retry/max
  artifact size/max cost budget)
- `docs/decisions/ADR-0004-node-pool-revision-untrusted-jobs.md` (runner pool
  extension, 3-way ServiceAccount split, browser pool differentiation)
- `docs/decisions/ADR-0007-final-synthesis-ownership-topology.md` rev.2
  (tenant discriminator survives the withdrawn blanket partition rule)
- `docs/decisions/ADR-0013-event-envelope-v1.md` (9-field envelope, engine_id
  closed enum, event naming)
- `docs/decisions/ADR-0014-tenant-propagation.md` (tenant_id format,
  `TenantContext` fields)
- `docs/decisions/ADR-0015-canonical-error-model.md` (RFC 9457 taxonomy,
  `common/error-detail/v1` shape, AuditEvent error scope)
- `docs/architecture/tenancy-model.md` (Identifier set table —
  `JobContext`'s field list)
- `docs/architecture/resilience.md` (Temporal Activity <-> K8s Job timeout
  coherence formula)
- `services/platform/agent-orchestrator-service/src/saena_orchestrator/activities.py`
  and `timeouts.py` (the W2-runtime connection seam this doc describes)
- `deploy/charts/saena-forge/values.yaml` (`agentRunner.job`/`agentRunner.limits`
  — the only `JobKind` with a values.yaml-sourced `ResourceLimits` default)

## Status

CONFIRMED shared execution-domain layer (`packages/domain/src/saena_domain/execution/`,
this patch unit) / NOT IMPLEMENTED per-job-kind service execution (later
Wave 3 units).
