# ADR-0003: Approval transition authority path (WAITING_APPROVAL → EXECUTING)

- Status: **accepted**
- Date: 2026-07-12 (decided: 2026-07-12, 사용자 승인)
- Deciders: 사용자 (repo owner)
- Decision: Lead 권고 경로 채택 — B 서명 → Policy Gate 선행 검증·기록(`policy.decision.recorded.v1`) → 승인 시에만 plan-contract-service가 Temporal signal 직발(이벤트 버스 경유 배제) → Temporal 재검증 = defense-in-depth. `plan.contract.approved.v1`은 통지 전용, 전이 트리거 아님.

## Purpose

B부서 승인이 EXECUTING 전이를 유발하는 권위 경로와 이중 검증(Policy Gate·Temporal)의 우선순위를 확정한다.

## Scope

In: 승인 신호의 전송 메커니즘, 검증 순서, 충돌 시 우선순위.
Out: 승인 UI/체크리스트 내용 (Prompt pkg §6), per-unit 승인 스코핑 (별도 보안 권고).

## Context

k3s spec §4.3 "Policy Gate와 Temporal workflow가 이 상태 전이를 각각 검증한다"는 두 검증 지점을 명시하나 트리거 메커니즘이 없다. agent-orchestrator README는 signed Action Contract(consumed contract)와 plan.contract.approved.v1(consumed event)을 모두 나열 — 권위 경로 미정. 이벤트 버스 경유 시 지연·순서·중복 배달 문제가 승인이라는 보안 결정에 유입된다. Policy Gate가 거부했는데 Temporal이 이미 전이한 경우의 우선순위가 spec에 없다.

## Current decision

**미결 — Lead 권고 (감사 수렴안):**

1. B부서 signed approval 접수 (forge-console-api → plan-contract-service)
2. **Policy Gate 선행 검증·기록** — `policy.decision.recorded.v1` 발행, 거부 시 여기서 종료
3. Policy Gate 승인 시에만 plan-contract-service가 **Temporal signal을 직접 발송** (이벤트 버스 경유 배제 — 지연·순서 문제 회피)
4. Temporal workflow의 자체 재검증(contract hash·서명)은 **defense-in-depth** — 1차 권위 아님. 불일치 시 전이 거부 + audit event
5. `plan.contract.approved.v1` 이벤트는 상태 전파용(다른 consumer 통지)이며 전이 트리거가 아님

## Constraints

- WAITING_APPROVAL → EXECUTING은 signed approval만 (k3s §4.3 CONFIRMED)
- 서명 주체·키 관리·검증 지점 정의 필요 (보안 감사 F-4 연계 — Action Contract에 evidence_ledger_hash 포함)

## Open decisions

- 서명 체계 (키 관리, 서명 알고리즘) — 별도 설계 문서
- signal 전달 실패 시 재시도·타임아웃 정책

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §4.3 (:235)
- `services/foundation/plan-contract-service/README.md`, `services/platform/agent-orchestrator-service/README.md`
- 감사 보고서 H-2 (plat D5, arch D-0 격상)

## Status

accepted (2026-07-12, 사용자)
