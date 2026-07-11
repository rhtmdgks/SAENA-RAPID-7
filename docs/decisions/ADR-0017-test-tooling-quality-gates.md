# ADR-0017: Test tooling & quality gates

- Status: accepted
- Date: 2026-07-12 (Wave 0 계획 승인 문답 — G2 사전 승인, 사용자)
- Deciders: 사용자 (repo owner)

## Purpose

testing-strategy.md의 "Coverage thresholds — OPEN DECISION"을 종결하고, Algorithm §11.1
필수 Quality Gates를 실행 가능한 도구·gate matrix로 구체화한다.

## Scope

In: 테스트 실행 도구, coverage 정책(수치·ratchet·예외), 계약 호환성 harness 구조,
mutation testing 도입 시점, quality gate matrix(blocking/warn)의 wave별 활성화.
Out: CI 파이프라인 조립 자체(ADR-0018), 계약 판정 규칙의 내용(Contracts Steward 권한,
ADR-0012).

## Context

- Algorithm spec §11.1은 Build/Tests/Link/Crawlability/Structured data/Content
  fidelity/Security/Accessibility/Performance/Diff rationality 10개 gate를 필수로
  규정하되 구체 도구·수치는 미정.
- testing-strategy.md는 gate 존재를 CONFIRMED로, 디렉토리 레이아웃을 PROPOSED로,
  coverage 수치는 OPEN DECISION으로 남겨두었다.
- W0는 코드가 아니라 기반 결정 단계 — W1(계약 12종) entry에 "contract harness 골격 green"
  요구가 있으므로 harness 구조는 W0에서 확정해야 W1이 무결정 착수 가능.
- 계약 호환성 판정은 이원 정책(닫힌 계약/열린 event payload, ADR-0012 예정)의 소관이며,
  "규칙 = Contracts Steward 권한, harness 코드 = testing 소유"로 역할이 분리되어야
  단일 owner 원칙(CLAUDE.md 원칙 7)과 충돌하지 않는다.
- 사용자 확정(2026-07-12): coverage 정책은 초안 80% 대신 **핵심 모듈 90%+diff 90%+ratchet**
  3단 구조로 대체한다(본 ADR이 최종 정본 — 계획 문서 초안 수치는 상위 결정으로 대체됨).

## Current decision

| 항목 | 결정 |
|---|---|
| 단위 테스트 | pytest + pytest-cov |
| Diff coverage | diff-cover — 변경 라인 coverage 게이트 |
| Coverage ratchet | coverage.py 기반 — 전역 coverage 회귀 감시 |
| 스키마 검증 | check-jsonschema (JSON Schema 2020-12) |
| 통합 테스트 | testcontainers-python — **W2A부터 도입**(W0/W1은 미사용) |
| Mutation testing | mutmut — **W3로 이연**. 도입 트리거: `packages/domain`에 실코드가 존재 + 안정된 unit suite 확보. 도입 초기는 nightly non-blocking, blocking 전환은 별도 판단 |

### Coverage 정책 (사용자 확정 2026-07-12 — 초안 80%안을 대체하는 최종 정본)

| 범위 | 기준 | 성격 |
|---|---|---|
| 핵심 모듈(`validation`, `policy`, `compatibility`) | line coverage ≥ 90% | blocking |
| Changed-lines(diff-cover) | ≥ 90% | blocking |
| 전역 coverage | 이전 값보다 낮아질 수 없음(ratchet) | blocking |
| 제외 | pure data 파일, generated code, migration boilerplate만 — config 내 **명시적 per-path 제외 목록**으로만 허용, 암묵적 제외 금지 |

Gate는 **첫 실코드 등장 시 활성화**된다(W1 harness 코드부터 카운트 — "코드 없음" 기간에는
공집합 통과가 아니라 gate 자체가 미적용 상태임을 명확히 한다).

### 계약 호환성 harness

- **단일 구현**을 `tests/contract/`에 둔다(이원 구현 금지 — 상호 검토에서 통합 합의).
- 구성: ① 직전 tag(N-1) example 전건 valid 검증 ② 구조 diff(자체 구현, JSON Schema 주력)
  ③ oasdiff(OpenAPI 보조) ④ unknown-enum tolerant-read 케이스.
- 권한 분리: **판정 규칙·enum/tag 정책 = Contracts Steward 권한**(ADR-0012 소관),
  **harness 실행 코드 = testing 소유**(본 ADR 소관). Steward가 규칙을 바꿔도 harness
  코드 소유자가 별도로 바뀌지 않음 — 단일 owner 경계는 "규칙 vs 실행"으로 분리.

### Quality gate matrix (wave별 blocking/warn)

| Gate | W0 | W1 | W2A+ |
|---|---|---|---|
| format/lint | blocking | blocking | blocking |
| schema validate | blocking | blocking | blocking |
| spec-immutability guard | blocking | blocking | blocking |
| protected-path guard | blocking | blocking | blocking |
| secret scan | blocking | blocking | blocking |
| SBOM | blocking(dormant-armed) | blocking | blocking |
| contract-compat | — | blocking | blocking |
| coverage gates(90%/diff/ratchet) | — | blocking(첫 실코드부터) | blocking |
| rollback-verification | — | — | blocking(W2A+) |

### Eval harness

`evals/` 구획(README 기준 fixtures/trace-graders/policy-tests/regression-suites)과
run-record 스키마 필드는 **지금 규약만 확정**한다. 실제 실행(trace grading, 회귀 실행)은
W3. k3s §10 failure-mode 9종 ↔ `tests/security` fixture 1:1 매핑표는 runner GA 게이트로
유지(testing-strategy.md 감사 반영 요구 승계, 변경 없음).

## Constraints

- Critical gate는 스킵 불가(testing-strategy.md 원칙 유지)
- author self-eval만으로 합격 선언 금지 — independent critic 필수(CLAUDE.md 원칙 9)
- coverage 제외는 config의 명시 목록으로만 — 코드 내 인라인 `# pragma: no cover` 남용을
  암묵적 제외로 취급하지 않음(감사 추적성 요구)
- `just verify`와 CI 명령 동일성 유지(ADR-0010 제약 승계)

## Open decisions

- diff-cover 90% 기준의 "diff" 정의(PR 전체 vs patch unit 단위) — harness 구현 시점 확정
- mutation testing blocking 전환 시점(트리거 충족 후 별도 판단)
- rollback-verification gate의 구체 검증 절차(W2A 설계 시점, sec F-7 승계)

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §11.1 (필수 Quality Gates), §11.2 (Eval-driven Harness)
- `docs/architecture/testing-strategy.md` (gate 목록 CONFIRMED, coverage OPEN DECISION 종결 대상)
- `evals/README.md` (회귀 세트 스코프, k3s §10 failure-mode 매핑 요구)
- `docs/decisions/ADR-0010-monorepo-tooling.md` (`just verify` 단일 게이트 원칙)

## Status

accepted (2026-07-12, 사용자 — Wave 0 계획 G2 사전 승인, coverage 정책 확정 반영)
