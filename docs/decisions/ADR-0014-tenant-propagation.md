# ADR-0014: Tenant propagation — immutable slug, envelope/header/baggage, TenantContext fields

- Status: accepted
- Date: 2026-07-12 (Wave 0 계획 승인 문답 — G2 사전 승인, 사용자)
- Deciders: 사용자 (repo owner)

## Purpose

`tenant_id`의 형식과 3개 전파 경로(이벤트/동기 HTTP/관측)를 확정하고, `TenantContext` 계약 객체의 필드 목록을 W0에서 고정한다(스키마화는 W1).

## Scope

In: `tenant_id` 형식·불변성, 이벤트/HTTP/observability 전파 메커니즘, mismatch 처리, `TenantContext` 필드 목록.
Out: `TenantContext` JSON Schema 파일 작성(W1 P0 #1), saas-shared JWT claim 기반 tenancy 설계(OPEN), internal-k3s fixed-tenant vs per-customer tenant 배정 정책(tenancy-model.md 소관, 별도 결정).

## Context

- `tenancy-model.md`가 namespace 명명 `saena-tenant-<id>`(k3s spec CONFIRMED, ≤63자)를 이미 확정했다 — tenant_id 형식은 이 네임스페이스 규약을 계승해야 한다.
- 동일 문서가 internal-k3s는 env var 패턴(`SAENA_TENANT_ID`) 전파, saas-shared는 request-scoped 전파(gRPC metadata/JWT claim)가 필요함을 지적하며 후자를 OPEN으로 남겼다 — "동일 이미지" 원칙이 이 전파 방식 차이를 가려서는 안 된다.
- `api-event-contracts.md`의 core business identifier 목록에 `tenant_id`가 포함되며, 이벤트에서는 ADR-0013의 envelope가 이미 전파 경로(context별 요구/금지 규칙)를 규정한다 — 본 ADR은 이벤트 경로를 envelope에 위임하고 동기/관측 경로를 추가로 확정한다.
- `contract-catalog.md`의 P0 #1이 `TenantContext`다(owner: tenant-control) — 필드 목록을 W0에서 먼저 고정해야 W1에서 스키마 작성이 무결정 착수 가능하다.

## Current decision

**`tenant_id` 형식**: **불변(immutable)** DNS-safe slug.

```
^[a-z0-9]([a-z0-9-]{1,30}[a-z0-9])$
```

- 최대 32자(위 정규식으로 시작/끝 영숫자 1자 + 중간 최대 30자 = 총 32자 상한).
- `saena-tenant-<id>` 네임스페이스(k3s spec CONFIRMED, ≤63자)에 접두어 `saena-tenant-`(13자)를 붙여도 63자 한계 내에 여유롭게 수납되도록 역산한 상한.
- 발급 후 값 변경 금지 — 변경이 필요하면 신규 tenant_id 발급 + 마이그레이션 절차(이관 프로세스는 별도 문서, W1 이후).

**전파 경로 3종**:

| 경로 | 메커니즘 |
|---|---|
| **이벤트** | envelope `tenant_id`(ADR-0013)가 **유일한 권위** — 이벤트 페이로드 내 별도 tenant 필드 중복 금지. |
| **동기 HTTP** | 요청 헤더 `X-Saena-Tenant-Id` + **pod env `SAENA_TENANT_ID`와의 일치 검증**. 불일치 시 **403 + audit 이벤트 발행**(어느 값과 불일치했는지 audit payload에 기록). saas-shared 환경의 JWT claim 기반 tenancy 바인딩은 **OPEN**(아래). |
| **관측(observability)** | OTel baggage + span attribute `saena.tenant_id`. `packages/observability`의 attribute registry(ADR-0016 대상)와 정합해야 한다. |

**`X-Saena-Tenant-Id` 검증 규칙**: internal-k3s 프로파일에서 각 pod는 자신이 속한 tenant의 `SAENA_TENANT_ID` env var를 갖는다(tenancy-model.md 기존 패턴). 수신 요청의 `X-Saena-Tenant-Id` 헤더 값이 이 env var 값과 다르면 요청을 즉시 거부(403)하고 audit 이벤트를 발행한다 — cross-tenant 접근 목표치 0(tenancy-model.md Constraints)의 동기 경로 집행 수단.

**`TenantContext` 계약 객체 — 필드 목록 (W0 확정, 스키마화는 W1 P0 #1)**:

| 필드 | 타입 | 비고 |
|---|---|---|
| `tenant_id` | string (위 slug 패턴) | 불변 |
| `display_name` | string | 사람 판독용, 변경 가능 |
| `isolation_profile` | enum: `internal-k3s` \| `saas-shared` | 격리 프로파일 |
| `namespace` | string | `saena-tenant-<tenant_id>` — `tenant_id`로부터 **derived**(별도 입력 아님, 저장은 하되 계산 필드로 취급) |
| `policy_version` | semver string | 적용 중인 정책 번들 버전 |
| `engine_scope` | array of string | v1 = `["chatgpt-search"]`(ADR-0013 `engine_id` 닫힌 enum과 정합) |
| `status` | enum: `active` \| `suspended` \| `terminating` | 라이프사이클 상태 |
| `retention_policy_ref` | string | 보존 정책 참조(opaque ref) |
| `created_at` | RFC3339 UTC timestamp | |
| `updated_at` | RFC3339 UTC timestamp | |

## Constraints

- `tenant_id` 값 변경(rename)은 금지 — 변경이 필요하면 신규 발급 절차를 따른다(불변성 원칙).
- 이벤트 페이로드에 envelope `tenant_id`와 별도로 tenant 식별 필드를 중복 정의하지 않는다.
- `X-Saena-Tenant-Id`/env mismatch를 조용히 무시하거나 200으로 처리하는 코드 경로 금지 — 반드시 403 + audit.
- `namespace` 필드는 `tenant_id`에서 결정적으로 파생되어야 하며 독립적으로 임의 값을 받아서는 안 된다.

## Open decisions

- saas-shared 환경의 JWT claim 기반 tenancy 바인딩 설계(request-scoped 전파 메커니즘 세부) — tenancy-model.md의 기존 OPEN 항목을 계승, 본 ADR에서 미해결.
- internal-k3s의 fixed-tenant vs per-customer tenant 배정 정책 — tenancy-model.md 소관(security P1 권고: per-customer), 본 ADR은 propagation 메커니즘만 다루고 배정 정책은 다루지 않는다.
- `retention_policy_ref`의 구체 포맷·조회 메커니즘 — W1 스키마 작성 시 확정.

## Source specification references

- `docs/architecture/tenancy-model.md` (namespace 규약, 전파 방식 OPEN 항목)
- `docs/architecture/contract-catalog.md` (`TenantContext` P0 #1 지정)
- `docs/architecture/api-event-contracts.md` (core business identifier 목록)
- `docs/decisions/ADR-0013-event-envelope-v1.md` (이벤트 경로 tenant_id 권위)
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §4.1

## Status

accepted (2026-07-12, 사용자)

> 검증 기록: independent critic conformance review PASS (2026-07-12) — 사용자 G2 처리 지침("계획·결정 부합 시 사전 승인")의 조건 충족 확인.
