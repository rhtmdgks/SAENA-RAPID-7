# Security model

## Purpose

Security boundaries for agents, network, secrets, supply chain.

## Scope

Four safety gates, NetworkPolicy, secret lifecycle, prompt-injection model.

## Current decision

**CONFIRMED** gates: Input / Plan / Execution / Release.  
**CONFIRMED** default-deny NetworkPolicy; non-root Jobs; short-lived tokens.  
**CONFIRMED** deployment credentials never in FORGE.

## Four gates

| Gate | On failure |
|---|---|
| Input Gate | isolate/stop run |
| Plan Gate | B부서 re-review |
| Execution Gate | block command |
| Release Gate | isolate patch; forbid PR artifact promotion |

## Agent rules

- Plan Mode: read-only
- Execution: Action Contract scope only
- Critics: read-only
- Untrusted content never becomes instructions

## 감사·합성 반영 (2026-07-12 — CONFIRMED 설계, NOT IMPLEMENTED 강제)

- **승인 권위 경로 (ADR-0003)**: B 서명 → Policy Gate 선행 검증·기록(`policy.decision.recorded.v1`) → plan-contract가 Temporal signal 직발 → Temporal 재검증 = defense-in-depth. `plan.contract.approved.v1`은 통지 전용.
- **승인 원자성 해체 (H-7)**: per-patch-unit secret lease + Git write token 분리, 고위험 unit 2인 승인. 모든 lease는 policy-gate 단일 통과.
- **근거 고정 (H-3)**: Action Contract에 `evidence_ledger_hash` + scope glob 상한 + diff 예산. 실험 등록 hash는 audit-ledger 앵커링.
- **격리 단위 = 프로세스/Pod (ADR-0002 rev.3)**: worker 내 모듈은 논리 경계 — 침해 시 동거 모듈 전체 노출 가정. 최고 민감 자산은 worker 밖.
- **policy-gate = fail-closed**: gate 장애 시 승인·실행 불가 (fail-open 금지 — resilience.md).
- **LLM provider egress = 실행 단계 한정 명시 예외** (SECURITY.md — 학습 파이프라인 확장 금지, §13-4 retention 결정 대기).
- **Aggregate privacy (ADR-0006 rev.2)**: Strategy Card는 tenant_id 제거 + k-anonymity 게이트, lineage는 audit role 전용 ref.
- **강제 현황 정직 표기**: 상기 전부 설계 확정·미구현. 현재 기계 통제 = settings.example의 permissions.deny(채택 시) + plan 모드 1겹. 실차단 = W2A policy-gate + W3 hooks.

## Constraints

- Least privilege RBAC; default SA has no API power — runner/quality-eval/intake SA 3분리 (ADR-0004)
- SBOM + signature + pinned third-party skills
- Agent deny = **allowlist가 본체** (blacklist 문자열 단독 금지 — C-1 우회 교훈: `git -c … push`, `kubectl patch`, `helm upgrade`)

## Open decisions

- ChatGPT observation account/ToS owner — OPEN DECISION (design §13)
- External egress policy details per environment — OPEN DECISION
- audit hash chain 외부 앵커·WORM·immutable role 정의 (내부자 위협모델) — W2A 설계 시

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §5.4–5.5, §10
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §6, §10
- `SECURITY.md`

## Status

CONFIRMED model / NOT IMPLEMENTED controls
