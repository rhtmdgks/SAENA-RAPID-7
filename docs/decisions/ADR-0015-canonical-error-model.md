# ADR-0015: Canonical error model — RFC 9457 + taxonomy + event error convention

- Status: accepted
- Date: 2026-07-12 (Wave 0 계획 승인 문답 — G2 사전 승인, 사용자)
- Deciders: 사용자 (repo owner)

## Purpose

동기 API 에러 응답 포맷, 에러 분류 체계, 이벤트/audit 경로에서의 에러 표현 방식을 확정한다.

## Scope

In: RFC 9457 problem+json 확장 필드, 9종 에러 카테고리 및 retryable 여부, 이벤트 payload 내 공용 에러 표현, `AuditEvent` 에러 기록 범위, DLQ 명명 규약(문서화만, 배선은 W2C).
Out: DLQ 실제 배선(W2C), `common/v1/error-detail` 스키마 파일 작성(W1), policy-gate 세부 정책 로직(ADR-0003 소관).

## Context

- 동기 API 포맷은 ADR-0008이 OpenAPI+JSON으로 확정했다 — 에러 응답도 이 패밀리 안에서 표준화되어야 하며, RFC 9457(구 RFC 7807) `application/problem+json`이 OpenAPI 3.1 생태계의 사실상 표준이다.
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §8.4(Rollback)이 policy bundle defect 시 "previous signed policy bundle로 rollback, new runs pause"를 요구하며, ADR-0003(approval transition authority path)이 policy-gate의 fail-closed 원칙을 다룬다 — 에러 계약이 이 fail-closed 판정을 표현할 수 있어야 한다(`policy_denied` 카테고리에 게이트 자체 장애 케이스 포함).
- 이벤트는 at-least-once 배달(`api-event-contracts.md`)이 전제이므로, 별도의 "에러 이벤트" 토픽군을 신설하면 order-of-events 추적이 어려워진다 — 상호 검토에서 "실패도 도메인 이벤트를 타고 흐른다"는 원칙으로 수렴했다.
- `AuditEvent`(contract-catalog.md P0)는 payload PII/secret 금지 제약이 이미 있다 — 에러 기록도 이 제약(스택 트레이스·원문 콘텐츠 금지)을 준수해야 한다.

## Current decision

**동기 API 에러 포맷**: **RFC 9457** `application/problem+json`.

| 필드 | 출처 | 값 규칙 |
|---|---|---|
| `type` | RFC 9457 표준 | URI, `https://schemas.the-saena.ai/errors/<category>/<code>` (ADR-0011 `$id` 스킴과 동형, non-resolvable) |
| `title` | RFC 9457 표준 | 사람 판독 요약 |
| `status` | RFC 9457 표준 | HTTP status code |
| `detail` | RFC 9457 표준 | 구체 설명(PII/secret 금지) |
| `instance` | RFC 9457 표준 | 요청 인스턴스 식별 URI/ref |
| `error_code` | **확장** | `saena.<category>.<reason>` 패턴 |
| `retryable` | **확장** | boolean |
| `trace_id` | **확장** | ADR-0013 envelope `trace_id`와 동일 형식(32-hex W3C) — 3-way 상관의 기반 |
| `tenant_id` | **확장, optional** | 해당 시 |
| `run_id` | **확장, optional** | 해당 시 |

**에러 taxonomy — 9 카테고리**:

| category | `error_code` 예 | 기본 retryable | 비고 |
|---|---|---|---|
| `validation` | `saena.validation.schema_mismatch` | no | 요청/계약 스키마 위반 |
| `auth` | `saena.auth.token_invalid` | no | 인증 실패 |
| `policy_denied` | `saena.policy_denied.<reason>` | no | 정책 게이트 거부. **`saena.policy_denied.gate_unavailable`을 fail-closed 케이스로 포함** — 게이트 자체 장애 시에도 요청을 승인이 아닌 거부로 처리(fail-closed) |
| `conflict` | `saena.conflict.version_stale` | no | 낙관적 잠금 등 상태 충돌 |
| `not_found` | `saena.not_found.resource_missing` | no | |
| `rate_limited` | `saena.rate_limited.quota_exceeded` | **yes** | HTTP `Retry-After` 헤더 필수 동반 |
| `upstream_engine` | `saena.upstream_engine.timeout` | **yes** | 엔진(ChatGPT Search 등) 호출 실패 — backoff 전략 적용 |
| `unavailable` | `saena.unavailable.service_down` | **yes** | 서비스 자체 가용성 문제 |
| `internal` | `saena.internal.unexpected` | no (기본) | 예외 상황, 기본값은 non-retryable(원인 불명 시 안전측) |

`rate_limited`와 `upstream_engine`/`unavailable`은 retryable=true가 기본이며, 클라이언트는 `Retry-After`(rate_limited) 또는 지수 backoff(upstream_engine/unavailable)를 적용해야 한다.

**이벤트/audit 경로의 에러 표현**: **별도 에러-이벤트 토픽군을 신설하지 않는다.** 실패는 해당 도메인 이벤트(예: `patch.unit.completed.v1`이 실패 상태를 포함하는 형태, 또는 상응 실패 이벤트)의 payload 안에서 공용 `$ref`로 표현한다:

```
$ref: "https://schemas.the-saena.ai/common/error-detail/v1/error-detail.schema.json"
```

`common/v1/error-detail`은 최소 `error_code`, `retryable`, `summary`(사람 판독 짧은 요약) 3필드만 갖는다. **스택 트레이스와 원문 콘텐츠(customer source, raw payload)는 금지** — `AuditEvent`의 PII/secret 금지 제약과 동일 원칙.

**`AuditEvent` 에러 기록 범위**: `error_code` + `trace_id`만 기록한다. 상세 진단 정보(스택 트레이스, 요청 원문)는 audit 계약 밖 — 필요 시 별도의 접근 제한 진단 스토어를 통해서만 조회(본 ADR 범위 밖, 필요성 확인 시 후속 설계).

**DLQ 규약**: 토픽 `<topic>.dlq` 명명 규칙만 **지금 문서화**한다(예: `patch.unit.completed.v1.dlq`). 실제 배선(consumer 재시도 소진 후 DLQ 라우팅, 모니터링, 재처리 절차)은 **W2C**로 이연한다.

## Constraints

- `detail`/`summary` 필드에 customer source, secret, PII 원문 포함 금지 — `AuditEvent`·`common/v1/error-detail` 공통 제약.
- `policy_denied` 카테고리는 게이트 장애 시에도 승인 방향으로 fail-open 하지 않는다 — fail-closed 원칙 예외 없음.
- 별도 에러-이벤트 토픽 신설 금지 — 실패는 도메인 이벤트 payload 내부에서만 표현.
- `rate_limited` 응답은 `Retry-After` 헤더 누락 금지.

## Open decisions

- 상세 진단 정보(스택 트레이스 등)의 접근 제한 저장소 설계 필요성 및 구조 — 미확정.
- `error_code` 카탈로그(각 카테고리별 `<reason>` 값의 표준 목록) 관리 방식 — W1에서 `registry.json`류 산출물로 확정할지 별도 결정.
- DLQ 배선 세부(재처리 정책, 알림 임계치) — W2C.

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §8.4 (Rollback, policy bundle defect 절차)
- `docs/decisions/ADR-0003-approval-transition-authority-path.md` (policy-gate fail-closed 원칙)
- `docs/architecture/contract-catalog.md` (`AuditEvent` PII/secret 금지 제약)
- `docs/architecture/api-event-contracts.md` (at-least-once 배달, idempotent consumer 원칙)
- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §5, §9–10

## Status

accepted (2026-07-12, 사용자)
