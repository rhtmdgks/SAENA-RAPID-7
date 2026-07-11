# CONTRIBUTING

## Purpose

기여·변경 절차 최소 규칙 (bootstrap).

## Scope

이 monorepo의 문서/골격/향후 구현 변경.

## Current decision

CONFIRMED contribution flow (W0). CI = GitHub Actions (`.github/workflows/ci.yml`, `security.yml` — ADR-0018). 로컬 게이트 = `uv run just verify` (CI와 동일 명령 집합).

### 로컬 설정 (W0 이후)

```sh
uv sync --locked                                    # 의존성 (uv.lock 고정)
uvx --from pre-commit pre-commit install            # pre-commit 훅 설치
uv run just verify                                  # 전체 로컬 게이트
```

Worktree 규약(ADR-0023): patch unit마다 `sh tools/development/worktree.sh create w<wave>-<seq2>-<slug> --paths '<glob>' --owner <agent>`.

### 인간 수행 체크리스트 (branch protection — 사용자 결정 2026-07-12)

GitHub Settings → Branches → main 보호 규칙: required status checks = `lint`, `schema-validate`, `boundaries`, `unit`, `contract-compat`, `guards`, `secret-scan`, `sbom`, `vuln-scan`, `actions-lint`; require code-owner review; force-push 금지. @saena-* teams 생성 전까지 CODEOWNERS는 선언적.

## Constraints

1. 설계 원본 `docs/specs/SAENA_*_v1.md` **수정 금지** (새 ADR/architecture 문서로 제안).
2. contract/schema/event/migration 변경은 단일 owner + ADR.
3. Cursor는 소범위만; 보호 경로는 Claude Code + 인간 승인.
4. 비밀정보·실 API key commit 금지.
5. Agent는 git push / merge / deploy 금지.

## Workflow (PROPOSED)

1. 관련 spec + architecture 문서 읽기
2. ADR 초안 (경계/계약 변경 시)
3. Plan / Action Contract (고객 run) 또는 개발 PR 설명
4. contract tests 우선
5. independent review
6. 인간 merge

## Open decisions

- ~~Branch protection rules~~ — **확정 (사용자 2026-07-12, ADR-0018)**: W0 즉시 활성. required checks = ci(lint, schema-validate, boundaries, unit, contract-compat) + security(guards, secret-scan, sbom, vuln-scan, actions-lint). GitHub 설정 변경은 인간 수행 (아래 체크리스트)
- CODEOWNERS final mapping — **활성 `CODEOWNERS` 존재** (2026-07-12; `.example` 삭제). teams 생성 + branch protection 활성화 전까지 선언적

## Source specification references

- Design specs under `docs/specs/`
- `docs/architecture/dependency-policy.md`; `agent-authority-boundaries.md`

## Status

PROPOSED
