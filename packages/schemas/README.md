# packages/schemas

## Purpose

JSON Schema artifacts (Action Contract, run-context, etc.).

## Scope

Protected path. Validates Plan/Execution artifacts.

## Current decision

CONFIRMED Action Contract schema requirement; files NOT IMPLEMENTED.

**거취 확정 (2026-07-12, 사용자 — W0)**: 본 디렉토리는 **파생 산출물(codegen artifacts) 전용**으로 유지한다. 수기 편집 계약 스키마의 유일한 SSOT는 `packages/contracts`(ADR-0011)이며, 여기에는 codegen이 생성한 타입/검증 산출물만 배치된다. 수기 파일 반입 = 리뷰 거부 사유.

## Constraints

- Human approval required flag immutable once signed
- 수기 편집 금지 — 원본은 `packages/contracts`, 생성 도구는 W1 codegen spike에서 확정 (ADR-0009/0011)

## Open decisions

- ~~Exact schema file layout~~ — 종결: 파생 전용 재정의(위). 생성물 배치 규칙은 W1 codegen 도구 확정 시 부속 결정

## Source specification references

- Algorithm §5.2; Prompt package §1

## Status

NOT IMPLEMENTED
