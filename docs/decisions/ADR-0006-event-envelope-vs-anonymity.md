# ADR-0006: Event envelope mandatory IDs vs Strategy Card anonymity (SPEC-CONFLICT)

- Status: **accepted (rev.2)** — 2026-07-12 외부 리뷰 R4 반영 개정, 사용자 승인
- Date: 2026-07-12
- Deciders: 사용자 (repo owner)
- Decision (rev.2): **3-context 모델** — rev.1 안 A(payload 필터 단일 규칙)를 개정:

| Context | 대상 | envelope 규칙 |
|---|---|---|
| **TenantContext** | tenant-scoped raw 이벤트 (관측·계약·patch·audit 등) | `tenant_id` 필수 유지 |
| **SystemContext** | global metadata (adapter config, policy bundle, SLO alert) | `tenant_id`·`run_id` 면제 |
| **AggregateContext** | cross-tenant Strategy Card | `tenant_id` **제거**. 필수 필드: `aggregate_scope_id`, `cohort_size`, `privacy_threshold`(최소 cohort 미달 시 발행 금지 — k-anonymity 게이트), `de_identification_status` |

원 tenant lineage는 **접근 제한(audit role 전용) audit-ledger reference로만** 보존 — 감사 추적성(security 요구)과 재식별 방지(architecture 요구)를 동시 충족. rev.1 대비 개선: payload 필터 단독 대신 envelope 계층에서 aggregate 익명성을 구조화하되, lineage 단절 없음. **SPEC-CONFLICT 해소 유지 — 본 ADR가 k3s §4.1과 Algorithm §8.4의 해석 우선순위 보유. events/schemas 구현 가능.**

## Purpose

spec 내부 모순 1건의 해소 방향을 확정한다. 감사에서 발견된 유일한 순수 SPEC-CONFLICT.

## Scope

In: event envelope 필수 필드 규칙, strategy.card.eligible.v1 및 비-run-scoped 이벤트의 예외 처리.
Out: envelope 필드 목록 자체의 재설계.

## Context

동시에 참일 수 없는 두 조항:

- k3s spec §4.1 (:182): "모든 event는 `event_id`, `tenant_id`, `run_id`, …를 가져야 한다" — 예외 없는 전건 강제.
- Algorithm spec §8.4 (:555) Strategy Card `privacy: aggregate_only` + §2.2 (:93) "대행사 운영 프로젝트의 **비식별** outcome을 Strategy Skill Bank에 축적" — tenant/run 식별자 보유 자체가 비식별 원칙과 충돌.

부수 문제: `tenant.policy.updated.v1`, `adapter.config.updated.v1`, `slo.alert.fired.v1`은 run-scoped가 아니라 `run_id`를 채울 수 없음.

## Current decision

**미결 — 양안 기록. Lead 권고 = 안 A.**

| 안 | 내용 | 장점 | 단점 |
|---|---|---|---|
| **A. envelope 유지 + payload 필터 (security 안, Lead 권고)** | 전 이벤트 envelope 8필드 유지 (비-run 이벤트만 `run_id` optional). strategy.card의 익명화는 **payload 계층**에서: 고객 식별 콘텐츠 제거 + cross-tenant 공유는 skill-bank 집계 경계에서 차단. envelope `tenant_id`는 내부 감사 전용 | audit completeness 100% 유지, 프라이버시 필터 위반 여부를 감사로 검증 가능 | 이벤트 스토어 접근 권한 관리 필요 (tenant_id 열람 = 내부 감사 role만) |
| B. 3계층 envelope (architecture 안) | run-scoped(8필드) / platform-scoped(5필드, tenant·run optional) / aggregate(4필드, tenant_id·run_id 금지). strategy.card=aggregate | 재식별 위험 원천 제거 | 익명 이벤트 경로 = 감사 사각지대 제도화, "이 카드가 어느 테넌트 유래인지" 추적 단절 → 프라이버시 필터 위반 검증 자체가 불가 (security REJECT 사유) |

## Constraints

- audit event completeness 100% (k3s §6.6) — 어느 안이든 훼손 금지
- Strategy Card에 고객 원문·식별 콘텐츠 유입 금지 (Algorithm 원칙 6) — 어느 안이든 유지

## Open decisions

- 채택 (spec 저자 결정 필수 — 두 spec 문장의 우선순위 확정)
- 안 A 채택 시: 이벤트 스토어의 tenant_id 열람 role 정의

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §4.1 (:182)
- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §2.2 (:93), §8.4 (:555)
- 감사 보고서 H-1 (plat D1 발견, arch 3계층 제안, sec REJECT 판정, boot SPEC-CONFLICT 확정)

## Status

accepted (2026-07-12, 사용자) — 안 A. events/schemas 구현 차단 해제
