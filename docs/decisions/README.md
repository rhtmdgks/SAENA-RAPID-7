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

## Source specification references

- Design §13; k3s §12

## Status

PROPOSED process
