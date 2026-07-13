# Wave 5 (Measurement·B-Layer) — authority, scope, DAG

Branch: `wave5-measurement` (from `main` = `156568c`, merged Wave 4 PR #5 + remediation PR #6).
This is a Wave-5 WORK document (not `docs/specs/**` — those stay immutable).
Authority extraction: 5 independent read-only agents (Algorithm spec / k3s spec /
ADR·waves / current code / B-dept package), 2026-07-14. Citations verbatim below.

## Authoritative scope (implementation-waves.md §W5, verbatim)

> "optimization-worker measurement 기능 활성(DiD) + `deployment.confirmed.v1` 7일
> clock + `outcome_layer` B-gate(skill-bank는 B 검증 통과만 소비) + evidence bundle
> + GRS 정책(§13 결정 후). measurement-worker 추출은 트리거 충족 시 (ADR-0002 rev.3)."

Five deliverables:
1. **DiD measurement activation** — Algorithm §3.7-4: "Difference-in-Differences 또는
   Bayesian hierarchical uplift"; P0 = deterministic DiD (Bayesian = P1/P2).
2. **`deployment.confirmed.v1` 7-day clock** — Algorithm §7.3:483: "고객 배포가 Day 2
   이후로 늦어지면 7일 외부 성과 clock은 시작하지 않는다." Sole clock-start authority.
3. **`outcome_layer` B-gate** — Algorithm §3.7-5:198: "최소 두 개 이상의 독립 signal
   layer에서 개선이 나타나야 B 계층 성과로 분류한다." api-event-contracts:68:
   skill-bank consumes B-verified outcomes only.
4. **Evidence bundle** — Algorithm §3.7-3:196 (snapshot+citation+timestamp+client code
   version+asset hash), §11.3:674-676 (reproducibility 100%, raw+weighted both),
   k3s Gate C:540 (raw evidence bundle + causal reporting).
5. **GRS policy** — k3s Gate C:539; threshold/SLA/credit = §13-7 OPEN →
   **mechanism only; production policy BLOCKED(human)**.

**Topology decision (code-verified)**: no `optimization-worker` service exists today —
`services/optimization/*` and `services/experimentation/*` are README-only scaffolds.
ADR-0002 rev.3 names experiment-attribution as the measurement module of the
optimization-worker deployment unit. W5 therefore implements measurement inside
**`experiment-attribution-service`** (declared producer of `experiment.outcome.observed.v1`,
TAG projection owner per ADR-0007 D-3), which IS "optimization-worker measurement 활성"
at contract-unit level. measurement-worker extraction: NO trigger met (①DiD batch SLO
interference ②ledger RBAC tier ③team split — none applies pre-production) → no extraction.
Extraction invariant (0 module code change) preserved by keeping compute in
`saena_domain.measurement` (pure) + thin service wiring.

## Non-scope (FORBIDDEN in W5)

- Conversion/attribution as 7-day success metric (Algorithm §4:212; k3s §12:553)
- KPI weight auto-optimization (Algorithm §3.6:190)
- Google AI Overviews / AI Mode / Gemini — any optimize/observe/claim path
- Full absorption-analysis P1 service/model, digital-twin, Bayesian survival,
  portfolio-optimizer, contextual bandit (P1/P2 flag-off). NOTE: `absorption` as an
  `outcome_layer` **enum value** is data-model support, NOT P1 model activation.
- Strategy-card auto-approval/global sharing; production skill-bank learning loop
  (W5 = fail-closed intake boundary ONLY)
- Production deploy / push to main / live customer observation / real ChatGPT calls
- Raw customer query/content/secret in events/logs/audit payloads
- Unverified external-lift claims (BPP §2 rule 9; release reject #9)

## Entry / Exit

**Entry (MET)**: W4 exit + remediation merged to main `156568c` (PR #5, #6); baseline
`just verify` green on `wave5-measurement` (2026-07-14); registration ledger live
(w4-09), ClickHouse (w4-06), Temporal time-skipping infra (W2B/W3).
STALENESS: implementation-waves.md:67 still says "W4 NOT IMPLEMENTED" → w5-23 updates
living status (W4 done, W5 in progress).

**Exit matrix** (implementation-waves.md gives W5 no explicit exit — derived from the 5
deliverables + Gate C + gate matrix; requires user sign-off, flagged as human item):

| # | Exit condition | Proven by |
|---|---|---|
| E1 | Treatment/control registration immutable (W4) + measurement-time binding rejects post-registration mutation/contamination | unit + adversarial tests (w5-04) |
| E2 | `deployment.confirmed.v1` is the ONLY clock start; identity/hash/target/confirmer/server-timestamp/idempotency/replay/backdate/cross-tenant validated | w5-03 tests + w5-14 Temporal time-skipping |
| E3 | DiD deterministic, recovers known synthetic effect, never passes zero-effect, separates common trend; FP/FN discriminating fixtures | w5-05 tests, 3× determinism |
| E4 | B-gate requires ≥2 independent layers (duplicate-basis counted once); 1-layer improvement ≠ PASS; insufficient/contaminated/late ⇒ UNDETERMINED + reason code | w5-06 + guard mutation |
| E5 | Evidence bundle complete + tamper/reorder/splice-evident; no raw customer content/secrets | w5-08 + w5-18 |
| E6 | GRS: signed policy bundle, missing/unsigned ⇒ fail-closed DENY/UNDETERMINED; TEST-ONLY fixture in tests; production values BLOCKED(human) | w5-07 |
| E7 | skill-bank intake consumes ONLY B-verified outcomes (fail-closed) | w5-16 |
| E8 | Tenant/privacy/idempotency/replay invariants green | w5-18, w5-20 |
| E9 | Real-container (Postgres/ClickHouse) + Temporal time-skipping integration green; mock-only E2E forbidden | w5-10/11/14/19 |
| E10 | All existing + new W5 named gates green; `just verify` 3× identical | w5-22, final |
| E11 | Independent critic requirement satisfied or Lead fallback honestly disclosed | critic ledger |
| E12 | No forbidden P1/Future activation; no deploy; no unsupported lift claim | w5-18 + exit report |

## Binding conventions (accepted ADRs — W5 must NOT relax)

- Contracts: JSON Schema 2020-12, `$schema` first key, `$id`
  `https://schemas.the-saena.ai/{category}/{name}/v{major}/...`, dir-per-major,
  registry.json + lockstep; `packages/contracts` SSOT hand-edit,
  `packages/schemas` codegen-only (ADR-0008/0011). Steward single owner (w5-02).
- Compat: closed=major-only; event open=additive-minor; envelope FROZEN;
  enum narrow AND widen = major; unknown-enum tolerant-read test (ADR-0012).
- Envelope v1: 10 members; `event_type` == topic; tenant context requires
  tenant_id+run_id; `engine_id` closed `["chatgpt-search"]` on experiment family
  (ADR-0013). No payload tenant_id/run_id duplication (ADR-0014/0024e).
- Errors: RFC 9457 / `common/error-detail/v1` $ref; `policy_denied.gate_unavailable`
  fail-closed (ADR-0015). Telemetry: registry-listed attrs, no PII (ADR-0016).
- Tests: coverage core ≥90 / diff ≥90 / global ratchet (99% baseline) never
  decreases; rollback-verification blocking; independent critic (ADR-0017).
- CI: justfile SSOT, `.github/workflows/**` Integrator-only, fragments via
  `tools/validation/ci-jobs/` (ADR-0018). ClickHouse: time partition +
  ORDER BY (tenant_id,…); per-tenant partition FORBIDDEN (ADR-0007 §5).
- B-gate/clock authority path: Policy-Gate-first fail-closed → direct Temporal
  signal; bus events notification-only (ADR-0003 pattern).
- Registration hash chain: reuse `saena_domain.audit.canonical` — no new hashing rule.
- W4 carried obligation: **outcome-field-gap** — open-class payloads cannot
  schema-reject stray `lift`/`outcome`; W5 closes via policy-gate/guard obligation
  honestly (w5-06/w5-12), not silently.

## Dependency DAG + exclusive paths

Existing channels: `experiment.outcome.observed.v1`, `strategy.card.eligible.v1`
exist **envelope-only** (16 channels); `deployment.confirmed.v1` = NEW channel #17.
Event-add hotspot files (registry/asyncapi/factory/codegen/cross-cutting test lists)
are w5-02-exclusive; root config (pyproject members, uv.lock, .importlinter, justfile,
ci.yml) is Integrator-exclusive at merge (W4 convention).

**Stage 0** (done)
- w5-00 this plan — Lead. `docs/architecture/wave5-plan.md`
- w5-01 baseline audit — `just verify` green @156568c ✓ (inline, evidence /tmp/saena-wave5/gates)

**Stage 1** (parallel; no path overlap)
- w5-02 measurement contracts/events (single owner "Contracts Steward"):
  `packages/contracts/**` (deployment-confirmed/v1 event + experiment-outcome-observed/v1
  payload + strategy-card-eligible/v1 payload + domain/experiment-outcome/v1 +
  domain/evidence-bundle-manifest/v1), `packages/schemas/**` codegen,
  `packages/domain/src/saena_domain/events/factory.py`, cross-cutting contract test
  lists (`tests/contract/validate/*`, `tests/unit/domain_events/*`).
- w5-03 deployment confirmation + trusted clock domain:
  `packages/domain/src/saena_domain/measurement/{__init__,confirmation,clock}.py`,
  `tests/unit/domain_measurement_clock/**`
- w5-04 experiment→measurement binding + contamination:
  `packages/domain/src/saena_domain/measurement/binding.py`,
  `tests/unit/domain_measurement_binding/**`
- w5-05 deterministic DiD engine:
  `packages/domain/src/saena_domain/measurement/did.py`,
  `tests/unit/domain_measurement_did/**`
- w5-06 outcome-layer model + B-gate + reason codes:
  `packages/domain/src/saena_domain/measurement/{outcome_layer,b_gate,reason_codes}.py`,
  `tests/unit/domain_measurement_bgate/**`
- w5-07 GRS policy interface + fail-closed bundle loading:
  `packages/domain/src/saena_domain/measurement/grs.py`,
  `tests/unit/domain_measurement_grs/**`
- w5-08 evidence-bundle manifest/hash/provenance:
  `packages/domain/src/saena_domain/measurement/evidence.py`,
  `tests/unit/domain_measurement_evidence/**`
- w5-09 persistence ports + idempotency semantics:
  `packages/domain/src/saena_domain/measurement/ports.py` + in-memory reference,
  `tests/unit/domain_measurement_ports/**`

(Note: w5-03..09 share `saena_domain/measurement/` package but own disjoint module
files; `__init__.py` exports = Integrator at merge.)

**Stage 2** (after relevant Stage-1 units)
- w5-10 Postgres measurement persistence (confirmations/windows/decisions):
  `services/experimentation/experiment-attribution-service/src/**/persistence/**`,
  migrations dir, `tests/integration/measurement_pg/**` (real container)
- w5-11 ClickHouse outcome projection (single owner of analytics-clickhouse src):
  `packages/analytics-clickhouse/src/**` outcome table/rows/guard/query,
  `tests/unit/analytics_clickhouse_outcome/**`, `tests/integration/clickhouse_outcome/**`
- w5-12 experiment-attribution service boundary (consume deployment.confirmed/
  observation.captured; publish experiment.outcome.observed; policy-gate obligation
  for outcome-field-gap): `services/experimentation/experiment-attribution-service/src/**`
  (excl. persistence/=w5-10, workflow/=w5-14), `tests/unit/svc_experiment_attribution/**`
- w5-13 measurement pipeline orchestration (registration+confirmation+observations →
  DiD → B-gate → evidence → outcome event):
  `services/experimentation/experiment-attribution-service/src/**/pipeline/**`,
  `tests/unit/svc_experiment_attribution_pipeline/**`
- w5-14 durable 7-day Temporal workflow/timers/signals (time-skipping tests):
  `services/experimentation/experiment-attribution-service/src/**/workflow/**`,
  `tests/integration/measurement_workflow/**`
- w5-15 observation scheduling/rate-policy boundary (approved-fixture adapter only):
  `services/acquisition/chatgpt-observer-service/src/**/scheduling*`,
  `tests/unit/svc_chatgpt_observer_scheduling/**`
- w5-16 B-verified-only skill-bank intake boundary (fail-closed):
  `services/experimentation/strategy-skill-bank-service/src/**`,
  `tests/unit/svc_strategy_skill_bank/**`
- w5-17 observability metrics/spans registry updates:
  `packages/observability/**` (measurement attrs), `tests/unit/observability_measurement/**`

**Stage 3**
- w5-18 privacy/tenant isolation/adversarial security: `tests/security/measurement_*.py`
- w5-19 synthetic E2E measurement flow (real containers + time-skipping; mock-only 금지):
  `tests/e2e/measurement/**`, `tests/integration/measurement_e2e/**`
- w5-20 failure/replay/rollback/rebuild/idempotency + F-9 adopt/supersede mapping:
  `tests/integration/measurement_failure/**`, evals failure-mode updates
- w5-21 Helm/forgectl wiring — **APPROVED (human, 2026-07-14, Wave 5 Closure)**:
  the user explicitly granted protected-path authorization for Wave 5
  measurement/B-layer deployment wiring under `deploy/charts/saena-forge/**`,
  `deploy/policies/**`, `deploy/README.md`, `tests/unit/deploy/**`,
  `tests/integration/deploy/**` (SecretRef/external secrets only; no plaintext
  values). This resolves H8 below. Live cluster install/rollback stays
  production-only OPEN; static chart correctness (lint/template/kubeconform/
  forgectl preflight) is in-scope. (Prior state, superseded: BLOCKED(human),
  approval unanswered.)
- w5-22 named CI gates (justfile recipes + ci fragments → Integrator applies .github):
  justfile (Integrator), `tools/validation/ci-jobs/w5-*.yml`
- w5-23 exit report + PR body + living status + final verification:
  `docs/architecture/wave5-{exit-report,pr-body}.md`, implementation-waves.md status

## Named CI gates (candidates, justfile SSOT)

`measurement-clock`, `experiment-registration` (binding), `did-attribution`,
`b-layer-gate`, `evidence-bundle`, `measurement-privacy`, `measurement-e2e`,
`measurement-failure-modes` — final names at w5-22.

## Author/critic allocation

Core units requiring 2 independent critics (correctness/stats + security/fail-closed):
w5-03 clock, w5-04 immutability/binding, w5-05 DiD, w5-06 B-gate, w5-07 GRS,
w5-08 evidence, w5-18 tenant/privacy, w5-19 E2E. Others: ≥1 critic.
Author never self-approves. Critics execute tests + adversarial probes (not diff-read
only). If critics idle-signal without verdict → Lead adversarial verification,
disclosed honestly (W4 convention, never labeled "independent critic PASS").

## Test/evidence requirements (per directive §8)

Reproducers/discriminating fixtures BEFORE implementation per core unit. Guard
mutation: removing each core guard must fail its adversarial test. Unit evidence JSON →
`/tmp/saena-wave5/units/w5-XX.json`; critic → `/tmp/saena-wave5/critics/`;
gates → `/tmp/saena-wave5/gates/`.

## Human decisions (consolidated request shown 2026-07-14 — unanswered; working
assumptions below are the directive-endorsed shapes; production values stay BLOCKED)

| # | Decision | Working assumption (mechanism) | BLOCKED part |
|---|---|---|---|
| H1 | GRS threshold + B-SLA remediation/credit (§13-7) | signed policy bundle, fail-closed, TEST-ONLY fixture | production values/credit mechanics |
| H2 | ChatGPT obs methodology/rate/ToS owner (§13-1) | approved-fixture adapter only in dev | owner assignment, live obs |
| H3 | "Independent layer" operational definition | distinct layer + distinct metric evidence basis; duplicate-basis counted once | spec-level confirmation |
| H4 | outcome_layer enum spelling | `[discovery,citation,absorption,prominence,referral]` (ALG §3.5:159; conversion excluded) | confirmation |
| H5 | deployment.confirmed.v1 confirmer trust model | ADR-0003 pattern: signed external identity → policy-gate-first → direct signal; server receive-time anchor | production confirmer identity/keys |
| H6 | 7-day timer mechanism | Temporal durable timer + time-skipping tests | — |
| H7 | Reason-code vocabulary | typed code-level enum v1 (ADR-proposed doc) | spec adoption |
| H8 | deploy/** (w5-21 Helm) | **APPROVED (human, 2026-07-14 Wave 5 Closure)** — static chart wiring/validation in scope; live install/rollback stays production-only OPEN | RESOLVED (grant recorded) |
| H9 | W5 exit matrix sign-off | E1–E12 above | sign-off |
| H10 | PII-vs-audit legal (W4 carry) | bundle carries hashes/refs only, no raw content | legal sign-off |

## Production-only (honest, never claimed PASS)

Live ChatGPT observation; real customer deploy + real deployment.confirmed.v1;
live 7-day wall-clock; GRS underwriting/credit issuance; live ClickHouse/dashboards;
cross-tenant card transfer; production key mgmt.

## Rollback

Each unit = additive modules + additive contracts (minor) + additive migrations;
rollback = revert unit commit(s); no destructive migration; registration ledger and
existing 38 contracts untouched except additive registry entries. Helm untouched (w5-21
blocked). Feature exposure: measurement service consumes events only when wired —
no existing runtime path altered.

## W5 완료 판정 규칙

PASS = E1–E12 green with evidence; BLOCKED items (H1 production values, H2 live obs,
H8 Helm, H10 legal) recorded as `mechanism PASS / production-policy BLOCKED(human)` —
never folded into PASS. UNDETERMINED semantics apply to the wave itself: missing
evidence = not claimed.
