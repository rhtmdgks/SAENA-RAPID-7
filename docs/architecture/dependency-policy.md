# Dependency policy

## Purpose

Allowed dependency directions between packages, services, and planes.

## Scope

Code dependencies (future) and runtime call/event directions.

## Current decision

**PROPOSED** policy derived from CONFIRMED contract-first / no shared DB rules.

## Allowed directions (PROPOSED)

```text
apps → services (via contracts) → packages/{contracts,schemas,domain,shared}
services ✗→ other services' databases
services → events (publish/consume versioned)
packages/provider-adapters → packages/contracts (interfaces only)
algorithm/domain ✗→ deploy profile packages
deploy ✗→ algorithm source
```

## Rules

1. Depend on contracts/schemas, not concrete service internals.
2. State changes via versioned events; sync limited to query/command APIs.
3. Provider-specific code only under `packages/provider-adapters/<provider>/`.
4. Infrastructure adapters (storage, queue, k8s) isolated from AEO scoring logic.
5. No dependency install by agents without pin + allowlist (runtime policy).

### 동기 호출·순환 규칙 (2026-07-12 감사 + rev.2)

6. 동기 호출은 3종으로 한정: (a) console → control plane 명령 (b) runner → policy-gate 결정 질의 — rate-limit + allow/deny bool 응답만(정책 근거 미노출) + 질의 audit event화 (c) artifact fetch. 각 동기 경로는 **timeout + circuit breaker 정책 필수 명시** (policy-gate의 가용성 SPOF 방지).
7. **동기 API 순환 금지.** 이벤트 피드백 루프는 명시 선언 시에만 허용 — 현재 선언된 루프 2개: ① 실행 saga 루프 (orchestrator→runner→quality-eval→orchestrator) ② cross-run 학습 루프 (runner→experiment-attribution→skill-bank→intervention-generator→plan-contract→orchestrator). CI에서 그래프 사이클 정적 검증 (선언 외 사이클 = 실패).
8. **featureFlags 분기는 gateway/plan-contract 경계에서만** — intelligence/optimization 서비스(알고리즘 코드) 내부에 Helm flag 분기 금지.

### Worker 내 모듈 경계 규칙 (ADR-0002 rev.3 — 2026-07-12)

9. **경계 이벤트 필수**: 타 bounded context가 소비하는 상태 변화(계약 이벤트)는 반드시 발행 — 소비자가 동거 모듈이어도 in-process 전달로 대체 금지. **transactional outbox**로 DB 쓰기·발행 원자성.
10. 모듈 내부 상태·중간 계산은 bus 강제 없음.
11. 동거 모듈 간 동기 호출 = published contract interface 경유만 (타 모듈 내부 함수·스키마 직접 접근 금지) — 코드 리뷰 + 언어 확정 후 lint/아키텍처 테스트로 강제.
12. 추출 불변식: worker 분리 시 모듈 코드 변경 0 — evals/regression-suites 아키텍처 테스트로 검증.
13. 격리 주의: worker 내 모듈 경계는 **논리·소유권 경계이지 보안 경계 아님** — credential·장애·보안 격리는 프로세스/Pod 수준에서만 성립 (ADR-0002 rev.3 위협모델).

## Constraints

- Bootstrap: no package manager lockfiles / manifests yet (OPEN DECISION language stack)

## Open decisions

- Primary languages per service — OPEN DECISION
- Monorepo tooling (Nx/Bazel/etc.) — OPEN DECISION

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §4.1
- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.1

## Status

PROPOSED
