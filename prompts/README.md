# prompts/

## Purpose

B부서 실행 프롬프트 5종 — k3s spec §2 요구 구획. 원문 = `docs/specs/SAENA_B_Department_Agent_Prompt_Package_v1.md` §4–9에서 verbatim 추출 (2026-07-12, ADR-0007 D-7 승인).

## Scope

| 파일 | 원본 | 단계 | 권한 |
|---|---|---|---|
| bootstrap.md | Prompt pkg §4 (Prompt 0) | Preflight | read-only |
| plan.md | Prompt pkg §5 (Prompt 1) | Plan Mode | read-only |
| execution.md | Prompt pkg §7 (Prompt 2) | Approved Execution | Contract 범위 write |
| verification.md | Prompt pkg §8 (Prompt 3) | Independent Review | read-only |
| handoff.md | Prompt pkg §9 (Prompt 4) | Handoff | 생성 전용 |

## Constraints

- 원본 spec이 권위 — 본 파일들은 배포용 사본. spec 변경 없이 수정 금지.
- 프롬프트 승격은 evals/ 회귀 세트 통과 필수 (Prompt pkg §12).
- 버전·정책·skill 버전과 함께 release bundle에 lock (k3s §1).

## Status

SCAFFOLDED (원문 사본) / eval 게이트 NOT IMPLEMENTED
