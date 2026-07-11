# Architecture Decision Records

## Purpose

Record decisions that are not silently embedded in code.

## Scope

ADR files using `ADR-TEMPLATE.md`.

## Current decision

PROPOSED ADR process. Specs remain authoritative until ADR supersedes a PROPOSED item.

## Constraints

- Do not edit immutable `docs/specs/*_v1.md`; ADR may clarify implementation choice
- Mark status: proposed / accepted / superseded / rejected

## Open decisions

Seed ADRs not yet filed for remaining design §13 / k3s §12 items.

## Filed ADRs

| ADR | 주제 | Status |
|---|---|---|
| ADR-0001 | Google/Gemini adapter 배포 형태 + flag granularity + gateway 존폐 | **accepted** (안 A, 2026-07-12) |
| ADR-0002 | 계약 단위 vs 배포 단위 (24 서비스 토폴로지) | **accepted** (모듈 통합만 언어 결정 후 보류) |
| ADR-0003 | 승인 전이 권위 경로 (Policy Gate 선행 → Temporal signal) | **accepted** |
| ADR-0004 | Node pool 개정 (untrusted Job 배정, compute pool) | **accepted** (compute pool 조건부) |
| ADR-0005 | 사용자 결정 소급 기록 (chart명, 보안 채널, bootstrap 출처) | accepted |
| ADR-0006 | ~~SPEC-CONFLICT~~ envelope 필수 ID vs Strategy Card 익명성 | **accepted** (안 A — 해소, events 구현 차단 해제) |
| ADR-0007 | 최종 합성: owner 4건·ROL 계약 중립화·v1 edge·인프라 스테이징·discriminator/partition 2계층 | **accepted rev.2** (blanket 파티션 철회 — R3) |
| ADR-0008 | v1 계약 포맷: JSON Schema/OpenAPI/AsyncAPI, gRPC 이연 (k3s §1 편차 보유) | **accepted** (2026-07-12 — R6) |

개정 이력: ADR-0002 rev.3 (모듈 통합 발동 + R1 위협모델 정정 + R2 경계 이벤트 규칙 + R7 optimization-worker 개명) / ADR-0006 rev.2 (3-context 모델 + audit lineage ref — R4) / ADR-0007 rev.2 (R3).

## Source specification references

- Design §13; k3s §12

## Status

PROPOSED process
