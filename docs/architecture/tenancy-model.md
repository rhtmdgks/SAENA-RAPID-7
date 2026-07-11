# Tenancy model

## Purpose

Tenant-aware design for internal-k3s and future SaaS profiles.

## Scope

Identifiers, isolation, namespaces, source isolation.

## Current decision

**CONFIRMED**

- Every customer run: independent namespace, short-lived workspace, tenant-scoped secret
- Events/records carry `tenant_id` (and related IDs as applicable)
- Customer source processed only in per-run isolated workspace
- Central API does not directly edit customer code

**PROPOSED** for SaaS reuse

- Same SAENA Core container images across profiles
- Profile-specific config + infrastructure adapters only
- `internal-k3s` uses a fixed `tenant_id` (single-operator context) but still threads IDs
- SaaS: per-tenant isolation of data, cache, events, workflow namespaces

## 격리 단위 명확화 (2026-07-12 감사)

- **namespace = tenant 단위** (`saena-tenant-<id>`, k3s §1), **workspace/secret = run 단위** (Algorithm §6.1) — 두 spec은 모순 아님 (감사 교차 판정).
- 확인 질문 (OPEN): internal-k3s fixed tenant_id 하에서 복수 고객 run이 같은 tenant namespace 안에서 workspace 분리만으로 격리되는 구조가 의도인가, 고객별 tenant 부여인가 — **고객별 tenant 권장 (security P1 권고)**.
- **테넌시 전파 방식**: env var 패턴(`.env.example`의 `SAENA_TENANT_ID`)은 **internal-k3s 전용**. saas-shared는 하나의 프로세스가 다중 테넌트 요청을 처리하므로 request-scoped 전파(gRPC metadata/JWT claim) 별도 설계 필요 — OPEN DECISION. 이 차이를 "동일 이미지" 원칙이 가리지 않도록 명시.
- saas-shared 공유 스토어의 row-level 격리(RLS)는 **2차 방어로만** — 1차는 namespace/schema 분리, RLS 정책 누락 마이그레이션 차단 CI 필수 (security 판정).

## Identifier set (required future acceptance)

| ID | Role |
|---|---|
| tenant_id | hard isolation boundary |
| workspace_id | operator/customer workspace |
| project_id | engagement/project |
| site_id | domain/site under project |
| run_id | single FORGE run |
| actor_id | human or system actor |

## Constraints

- Cross-tenant access target: 0
- Strategy Skill Bank: aggregate_only; no proprietary customer text sharing
- Redis not a cross-tenant source of truth

## Open decisions

- SaaS auth/billing — OUT OF SCOPE for this bootstrap (explicitly not implemented)
- internal-k3s 고객-간 격리 단위 (fixed vs per-customer tenant) — 위 명확화 절 참조
- saas-shared request-scoped 테넌시 전파 설계

(참고: namespace 명명 `saena-tenant-<id>`는 k3s spec CONFIRMED — Open 항목 아님, 2026-07-12 감사 boot B8로 본 절에서 Current decision 성격으로 재분류)

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.1
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §1, §5–6

## Status

CONFIRMED isolation principles / NOT IMPLEMENTED enforcement
