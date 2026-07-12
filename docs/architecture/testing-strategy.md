# Testing strategy

## Purpose

Test-first layers for contracts, agents, and package readiness.

## Scope

unit / contract / integration / e2e / security / performance (+ eval fixtures).

## Current decision

**CONFIRMED** quality gates list from Algorithm §11.1.  
**PROPOSED** directory layout under `tests/`.

## Layers

| Layer | Intent |
|---|---|
| unit | pure domain logic (future) |
| contract | JSON Schema/OpenAPI/AsyncAPI compatibility (ADR-0008 — proto 이연) |
| integration | service + bus + db testcontainers (future) |
| e2e | synthetic tenant Plan→Approve→Patch→Handoff |
| security | injection, secret, deploy-temptation fixtures |
| performance | runner/browser quotas, gate latency |
| architecture | **모듈 추출 불변식** — worker 분리 시 코드 변경 0, 경계 이벤트·published interface 위반 검출 (ADR-0002 rev.3 규칙 12; evals/regression-suites) |

## Completion categories (CONFIRMED)

AEO correctness; patch correctness; safety; reproducibility; measurement; business integrity

## 감사 반영 추가 요구 (2026-07-12)

- **failure-mode 9종(k3s §10) ↔ `tests/security` fixture 1:1 매핑 표** — runner GA 게이트 (sec F-8)
- **rollback 동작 검증 gate**: patch unit revert 적용 후 build/test 통과 확인 — quality gate 목록에 추가 (sec F-7)
- deny 우회 회귀 세트 (`git -c … push`, `kubectl patch`, `helm upgrade` 등 — C-1)
- W2A exit: policy-gate fail-closed 데모 필수

## Constraints

- Critical gates cannot be skipped
- Independent critic required for release
- No external lift claims without registered evidence

## Two-lane test execution (w2-20, Wave 2 exit)

Root cause: `tests/integration/**` suites exercise REAL external
test-server/container processes (Temporal `start_time_skipping()` embedded
test server; `postgres:16-alpine` / `redpandadata/redpanda` testcontainers).
Running these in the SAME `pytest` invocation as ~2,100 deterministic
unit/contract tests caused intermittent flakes under full-suite load —
process-scheduling contention when several real external processes start
concurrently with a large, fast unit run, not a bug in the tests or the code
under test (each flaked test passed reliably 3/3+ in isolation).

Fix: every test under `tests/integration/**` is auto-marked
`pytest.mark.integration` by `tests/integration/conftest.py`
(`pytest_collection_modifyitems`, path-scoped so it never touches items
collected elsewhere in the same session) and by `[tool.pytest.ini_options]`
`markers` in root `pyproject.toml` (canonical registration).

- `just test` (blocking, inside `just verify`) runs `pytest -m "not
  integration"` — deterministic unit + contract lane only. No real external
  test-server/container process runs in this lane; verified deterministic
  (5/5 identical pass counts) under repeated `just verify` runs, w2-20.
- `just test-integration` (NOT part of `verify`) runs `pytest -m
  integration` — the real Temporal/testcontainers lane, run separately/
  serially so cross-suite contention cannot recur.

CI must run BOTH lanes: the unit lane as the blocking required check
(ADR-0018 `just verify` == CI identity), the integration lane as a separate
serial job (not yet wired — `.github/workflows/**` is Integrator-only,
ADR-0018; this is a two-lane STRUCTURE decision recorded here, the actual
CI job wiring remains open work for whoever owns that path next).

### CI two-lane wiring (w2-22)

`.github/workflows/ci.yml` now mirrors this structure mechanically:

- `unit` job's pytest step selects `-m "not integration"` — byte-identical
  to justfile `test`'s selector. Blocking, deterministic, PR-required.
- `integration` job (`needs: [unit]`) runs `uv run just test-integration`
  (`-m integration`) — the real Temporal time-skipping test-server +
  Postgres/Redpanda testcontainers lane. Also blocking (not
  `continue-on-error`): a container that fails to start fails the job, it
  does not skip silently. Separate PR-required check from `unit`.
- `tests/unit/ci_identity/test_ci_matches_justfile.py` parses both
  `ci.yml` and `justfile` and asserts the two selectors stay identical and
  that the `integration` job exists and is not soft-failing — drift between
  CI and the justfile recipes is now a failing unit-lane test, not a silent
  divergence (ADR-0018 lockstep enforced mechanically).

Coverage consequence (ADR-0017 ratchet, honestly documented, not silently
weakened): `packages/domain/src/saena_domain/persistence/postgres/
adapters.py` (real SQLAlchemy-async Postgres SQL adapters, w2-13) has no
meaningful non-integration coverage — it is 100% covered by
`tests/integration/persistence_postgres/**` alone and ~21% by the unit lane
alone (incidental import/constructor coverage only). Per the coverage-ratchet
gate's own instruction ("do NOT weaken the ratchet silently"), this file is
explicitly `omit`-ted from `[tool.coverage.run]` (see that config's own
comment) so the BLOCKING unit-lane ratchet measures what that lane actually
exercises (99%, unchanged from the pre-split baseline) rather than silently
absorbing a ~5-point drop. The integration lane's own coverage run is NOT
subject to that omit and still shows this file at 100%.

## Open decisions

- ~~Coverage thresholds~~ — **확정 (ADR-0017, 사용자 2026-07-12)**: 핵심 모듈(validation/policy/compatibility) line ≥90% blocking + changed-lines ≥90% blocking + 전역 coverage 하락 금지(ratchet, blocking) + exclusion은 명시적 목록만(단순 데이터/generated/migration boilerplate). 게이트 활성 = 첫 실코드(W1 harness 포함)부터
- Browser harness vendor details — OPEN DECISION (W4 chatgpt-observer 착수 시; Playwright for Python이 ADR-0009 기본 후보)

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §11
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §10–11
- `docs/specs/SAENA_B_Department_Agent_Prompt_Package_v1.md` §12

## Status

CONFIRMED gate intent / unit+contract+integration+e2e(approval) suites
IMPLEMENTED (W2A-C, w2-01..w2-19) / two-lane split (unit lane blocking via
`just test`, integration lane serial via `just test-integration`) confirmed
w2-20 / `tests/security` and `tests/performance` still NOT IMPLEMENTED
(README-only placeholders — W3+)
