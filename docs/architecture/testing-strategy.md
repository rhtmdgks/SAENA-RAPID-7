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

## Open decisions

- ~~Coverage thresholds~~ — **확정 (ADR-0017, 사용자 2026-07-12)**: 핵심 모듈(validation/policy/compatibility) line ≥90% blocking + changed-lines ≥90% blocking + 전역 coverage 하락 금지(ratchet, blocking) + exclusion은 명시적 목록만(단순 데이터/generated/migration boilerplate). 게이트 활성 = 첫 실코드(W1 harness 포함)부터
- Browser harness vendor details — OPEN DECISION (W4 chatgpt-observer 착수 시; Playwright for Python이 ADR-0009 기본 후보)

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §11
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §10–11
- `docs/specs/SAENA_B_Department_Agent_Prompt_Package_v1.md` §12

## Status

CONFIRMED gate intent / NOT IMPLEMENTED suites
