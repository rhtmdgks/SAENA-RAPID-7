# evals/

## Purpose

Prompt·skill·policy 회귀 평가 스위트 — k3s spec §2 요구 구획, Prompt pkg §12의 물리 위치. 프롬프트 승격 게이트: 회귀 세트 통과 없이 prompt/skill/policy bundle 승격 금지.

## Scope

| 구획 | 내용 |
|---|---|
| fixtures/ | 고정 평가 입력 (spec §12 회귀 세트) |
| trace-graders/ | agent run trace 채점기 |
| policy-tests/ | policy bundle 회귀 (deny/allow 케이스) |
| regression-suites/ | prompt 버전 간 회귀 실행 정의 |

## 필수 회귀 세트 (Prompt pkg §12 — CONFIRMED 목록)

- B2B SaaS source repos in different frameworks
- factual claim conflict cases
- security/secret injection fixtures
- deceptive schema fixtures
- unsupported pricing/security claim fixtures
- deployment/push temptation cases
- source-code-only boundary cases
- patch minimality and rollback cases

추가 (2026-07-12 감사): k3s §10 failure-mode 9종 ↔ fixture 1:1 매핑 필수 (sec F-8).

## Constraints

- 모든 run 기록: prompt pkg version, skill versions, Ponytail SHA, policy version, contract hash, repo SHA, image digest (Prompt pkg §12)
- Critical gate 회귀 없이는 어떤 prompt 갱신도 승격 금지

## Status

SCAFFOLDED (구획만) / NOT IMPLEMENTED — 스캐폴드 승인: 2026-07-12 (ADR-0007 D-7)
