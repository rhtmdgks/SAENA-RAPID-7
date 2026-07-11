# .claude/agents/

## Purpose

SAENA FORGE 개발·B부서 run용 project custom subagent 정의. design §9.1 MAS 역할 + Prompt pkg §5·§7·§8을 Claude Code subagent로 이식.

## Status

**IMPLEMENTED (정의 문서)** — 14종 markdown 작성 완료 (2026-07-12). 런타임 tool-lease·정책 강제는 hook + Forge Policy Gate 소관으로 **NOT IMPLEMENTED**. 즉 이 파일들은 역할·경계 **선언**이며, 실제 권한 격리를 보장하지 않는다.

## 정의된 subagent

### research/ (Plan 단계, read-only)
- discovery-agent — site/repo 기술 인벤토리
- demand-agent — Query Cluster
- evidence-agent — claim/evidence ledger, BLOCKED 표기
- citation-competition-agent — citation vs absorption gap
- technical-risk-agent — 파괴 위험 평가
- planner-agent — 합성 + PLAN.md/action-contract.draft.json (`.saena/`만 write)

### implementation/ (Execution 단계, contract 범위 write)
- technical-patch-agent — 기술 unit
- content-compiler-agent — evidence-backed 콘텐츠 unit
- schema-agent — visible-parity structured data
- integrator-agent — 유일 충돌 해결자 (다중 worktree)

### review/ (Verify 단계)
- test-agent — 승인 명령 실행 (편집 없음)
- fidelity-critic — read-only claim/brand/legal
- security-critic — read-only secret/injection/supply-chain
- independent-release-reviewer — 릴리스 게이트 (**integration-reviewer 역할 포함**)

## 매핑 주석 (요청 산출물 18 대비)

요청의 "...reviewer / integration-reviewer" (전송 중 앞부분 손상) 계열은 위 review/ 4종으로 충족: 코드/충실도=fidelity-critic, 보안=security-critic, 테스트=test-agent, 통합·릴리스=independent-release-reviewer(integration-reviewer 책임 흡수). 별도 신규 역할은 spec §9.1에 근거 없어 추가하지 않음 (설계에 없는 결정 금지 원칙).

## Constraints

- Write agent: 배정 worktree + Action Contract `files`만. Critic: read-only.
- 모델 라우팅: 각 정의는 `model: inherit` — 세션 모델 상속. critic이 author와 다른 provider를 쓰는 정책(design §9.2)은 오케스트레이션 계층 결정.
- **런타임 강제 = hook + Policy Gate + k3s** (이 정의만으로 경계 미보장).

## Source specification references

- Algorithm §9.1–9.2; Prompt pkg §5, §7, §8; AGENTS.md 역할 카탈로그
