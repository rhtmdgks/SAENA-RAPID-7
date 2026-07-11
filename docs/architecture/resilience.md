# Resilience

## Purpose

플랫폼 내부(서비스 간) 장애 대응 요구사항. 2026-07-12 감사에서 spec 3종 + architecture 문서 전체에 circuit breaker/fallback/bulkhead/DLQ/backpressure 관련 규정이 0건임이 확인되어 신설 (AA-1).

## Scope

서비스 간 gRPC 호출, 이벤트 버스 소비, 배포 안전장치. Agent runner 자체 한도(k3s §5.3 `activeDeadlineSeconds` 등)는 spec CONFIRMED — 본 문서 범위 외.

## Current decision

**PROPOSED** — 구현 착수 전 확정 필요.

### 동기 호출 (dependency-policy.md 규칙 6 연계)

- 모든 서비스 간 gRPC 호출: 명시적 timeout + retry budget + circuit breaker.
- policy-gate 앞: rate-limit + 결정 캐싱 (게이트키퍼의 가용성 SPOF 방지).
- Temporal Activity ↔ K8s Job 정합: runner Job을 감싸는 Activity는 `startToCloseTimeout ≥ activeDeadlineSeconds(7200s) + buffer`, heartbeat interval = Job 상태 poll 주기.

### 이벤트 발행·소비

- **Transactional outbox 필수** (ADR-0002 rev.3): 경계 이벤트는 DB 쓰기와 원자적으로 outbox 기록 → relay가 발행. bus 장애 시 producer는 outbox 적재 지속(차단 아님), drain은 복구 후. Wave 2A(bus 부재기)에도 동일 패턴.
- at-least-once + idempotent consumer는 CONFIRMED (k3s §4.1). 추가 필요: poison-message/DLQ 정책, consumer lag 알람.
- partition key 규약: 스토어·토픽별 결정 (ADR-0007 rev.2 — tenant discriminator는 논리 필수, physical key는 별개) — OPEN DECISION.

### 배포 안전장치

- liveness/readiness probe 전 Deployment 필수 (감사 AA-2: 현재 언급 0건).
- 점진 배포 전략 (canary/blue-green vs `helm --atomic` 단독) — OPEN DECISION. rollback runbook(k3s §8)은 CONFIRMED 유지.

### Degraded mode

- Plan-only run SLO의 "degraded" 상태(k3s §6.6) 외 서비스별 degraded 동작 미정의 — 서비스 계약 작성 시 필수 항목화.

## Constraints

- Resilience 장치가 critical quality gate·승인 게이트를 우회하는 fallback 금지 (예: policy-gate 장애 시 fail-open 금지 — fail-closed 강제).

## Open decisions

- DLQ 구현 방식, partition key 규약, 점진 배포 전략, 서비스별 SLO/degraded 표.

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §4.1, §5.3, §6.6, §8
- 감사 보고서 AA-1·AA-2, arch A-6 + platform 보강, P-Q6

## Status

PROPOSED / NOT IMPLEMENTED
