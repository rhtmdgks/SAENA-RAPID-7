# ADR-0016: Telemetry conventions & attribute registry

- Status: accepted
- Date: 2026-07-12 (Wave 0 계획 승인 문답 — G2 사전 승인, 사용자)
- Deciders: 사용자 (repo owner)

## Purpose

observability.md의 "OpenTelemetry CONFIRMED intent"를 실행 가능한 규약으로 구체화하고,
`packages/observability`를 규약 보유자(convention-holder)로 확정한다. 스택 배포(OTel
Collector + Prometheus/Loki/Tempo + Grafana)는 W2C 유지 — 본 ADR은 W0 범위인
**규약 + 기계 검증 가능한 registry**만 정의한다.

## Scope

In: OTel semantic conventions 적용 방식, `saena.*` 커스텀 속성 네임스페이스, span/log/metric
naming, envelope-파생 context 규칙, registry 구조와 redaction 정책.
Out: Collector/backend 배포 토폴로지(W2C), Prometheus 변환 세부(W2C exporter), 대시보드
설계(observability.md 6종 유지).

## Context

- observability.md는 run trace envelope 필드(`trace_id`/`run_id`/`tenant_id`/`repo_sha`/
  `chart_version`/`image_digests`/`policy_bundle_hash`/`skill_bundle_hash`/
  `action_contract_hash`/`model_adapter`/`events`, k3s §9.1)와 tenant label 요구를
  CONFIRMED로 명시하되 속성 이름 규약은 미정.
- ADR-0006 rev.2가 3-context 모델(TenantContext/SystemContext/AggregateContext)을 확정:
  TenantContext는 `tenant_id` 필수, SystemContext는 `tenant_id`·`run_id` 면제,
  AggregateContext는 `tenant_id` 제거(재식별 방지). 텔레메트리 속성 규칙이 이 모델과
  별도로 정의되면 두 규약이 drift한다.
- event envelope 스키마(ADR-0013, W1 산출물)가 context 판별의 단일 소스가 되어야
  regression 없이 유지 가능 — 문서 두 곳에서 각자 규칙을 유지하면 편차가 감사에서
  재발한다(ADR-0006 SPEC-CONFLICT 선례).
- 문서-only 규약은 drift를 막지 못한다 — registry가 CI에서 lint되는 기계 검증 가능한
  형태여야 강제력을 가진다.

## Current decision

| 항목 | 결정 |
|---|---|
| 표준 | OpenTelemetry semantic conventions 기준 + `saena.*` 커스텀 속성 네임스페이스로 확장 |
| Span naming | `saena.<capability>.<operation>` — low-cardinality만 이름에 사용, run_id/tenant_id 등 식별자는 반드시 속성(attribute)으로만 부여, span name에 삽입 금지 |
| 필수 속성 (전 span 공통) | `saena.tenant_id`, `saena.run_id`, `saena.engine_id`, `saena.context`(`tenant`\|`system`\|`aggregate`) |
| Context별 요구 규칙 | **event envelope 스키마(ADR-0013)에서 파생 — 단일 소스.** `system`: `saena.tenant_id`·`saena.run_id` 면제. `aggregate`: `saena.tenant_id` **금지**(포함 시 위반) — exporter 레벨 강제가 목표(아래 registry 참조) |
| 로그 | 구조화 JSON, 1-line, OTel Logs Data Model 필드명 사용: `timestamp`(RFC3339 UTC), `severity_text`, `body`, `trace_id`, `span_id` + 동일한 `saena.*` 필수 속성 집합 |
| 메트릭 naming | `saena.<domain>.<name>` + UCUM 단위. Prometheus 이름 변환(`_total` 등)은 W2C exporter 책임으로 이연 — W0은 OTel 네이티브 이름만 정의 |
| 상관관계 | trace/log/event 3-way correlation은 **동일 `trace_id`**를 event envelope와 공유하는 방식으로 성립(envelope는 ADR-0013, k3s §9.1 run trace envelope의 `trace_id` 필드와 정합) |
| Registry (SSOT) | `packages/observability/registry/attributes.yaml` — 필드: name, type, cardinality, context-rules, PII flag. `packages/observability/registry/redaction-rules.yaml` — allowlist-first: registry에 등록된 속성만 export 허용 + 그 위에 secret/PII regex denylist 추가. `aggregate` context에서 `tenant_id` 계열 속성 발견 = 위반(redaction-rules로 차단 대상) |
| CI 강제 | registry는 CI에서 lint(스키마 검증 + context-rules가 envelope 스키마와 정합하는지 대조) — W0 산출물은 registry 골격 + lint 스크립트, 실제 exporter 배선은 W2C |
| 배포 | 스택(Collector/Prometheus/Loki/Tempo/Grafana) 배포는 observability.md 결정대로 **W2C 유지**. 본 ADR은 규약+registry만, 런타임 미변경 |

## Constraints

- Secret은 telemetry payload에 절대 포함 금지(observability.md 원칙 유지)
- Audit completeness 100% 요구는 telemetry 규약으로 대체되지 않음 — audit event는 별도 채널(k3s §9.3)
- `saena.context` 값과 envelope의 `context_type`(ADR-0013 예정 discriminator)은 동일 어휘 사용 — 별도 vocabulary 생성 금지
- registry 변경은 `packages/observability` 소유 경계 내(단일 owner 원칙, CLAUDE.md 원칙 7 준용) — 스키마 자체는 아니지만 계약적 성격이므로 임의 팀 편집 금지

## Open decisions

- Prometheus 이름 변환 규칙 상세(W2C exporter 설계 시점)
- registry lint를 CI 어느 stage에 배치할지(ADR-0018 gate matrix와 연동, T17에서 확정)
- ADR-0013 확정 전까지 context-rules 표는 envelope 초안 기준 잠정치 — ADR-0013 accepted 시 본 ADR의 context-rules 서술을 대조 검증 필요

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §9.1 (run trace envelope), §9.2 (dashboard themes)
- `docs/decisions/ADR-0006-event-envelope-vs-anonymity.md` (3-context 모델, rev.2)
- `docs/architecture/observability.md` (CONFIRMED intent, tenant label 3-context 면제)

## Status

accepted (2026-07-12, 사용자 — Wave 0 계획 G2 사전 승인)
