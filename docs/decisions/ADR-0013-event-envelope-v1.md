# ADR-0013: Event envelope v1 — 9-field envelope, 3-context discriminator, engine_id

- Status: accepted
- Date: 2026-07-12 (Wave 0 계획 승인 문답 — G2 사전 승인, 사용자)
- Deciders: 사용자 (repo owner)

## Purpose

ADR-0006 rev.2(3-context envelope 모델)를 실행 가능한 envelope v1 스펙으로 구체화하고, k3s §4.1의 8필드 목록에 대한 v1 해석(9번째 필드 `event_type` 추가)을 이 ADR이 보유함을 기록한다.

## Scope

In: envelope 공통 필드 9종, `context_type` discriminator(tenant|system|aggregate) 구조, 각 context별 필드 요구·금지 규칙, `engine_id` payload 규칙, 이벤트 명명 규칙, 예시 인스턴스.
Out: 실제 스키마 파일 작성(W1 산출물 — 본 ADR은 필드 목록·구조·예시만 확정), `cohort_size ≥ privacy_threshold` 런타임 게이트 구현(W2A), tenant-scoped 비-run 이벤트의 `run_id` nullable 허용 여부(OPEN — 아래).

## Context

- k3s spec §4.1(:182)은 "모든 event는 `event_id`, `tenant_id`, `run_id`, `schema_version`, `producer`, `occurred_at`, `trace_id`, `idempotency_key`를 가져야 한다"고 명시한다(8필드, 예외 없는 전건 강제 문구).
- ADR-0006 rev.2가 이 8필드 전건 강제와 Algorithm spec §2.2/§8.4(Strategy Card 비식별 원칙)의 충돌을 3-context 모델(TenantContext/SystemContext/AggregateContext)로 해소했다 — SystemContext는 `tenant_id`·`run_id` 면제, AggregateContext는 `tenant_id`·`run_id` **제거**(금지)하고 별도 익명화 필드를 요구한다. 즉 k3s §4.1의 "예외 없는 전건 강제" 문구 자체가 ADR-0006 rev.2로 이미 수정 해석되어 있다.
- `api-event-contracts.md`가 이벤트 차원 필드로 `engine_id`(PROPOSED, 2026-07-12 감사)를 제안했다 — v1이 ChatGPT Search 단일 엔진이어도, Google/Gemini 계열 이벤트가 실수로라도 발행되면 스키마 레벨에서 즉시 탐지하기 위함(CLAUDE.md Engine scope v1 원칙과 직결).
- `event_type`을 9번째 필드로 추가하는 것은 k3s §4.1의 8필드 목록에 대한 **명시적 편차(deviation)**다. ADR-0002/ADR-0008과 동일 패턴 — spec 원문은 불변으로 두고, 본 ADR이 v1 구현 해석의 권위를 보유한다. 사용자가 2026-07-12 이 편차를 승인했다.
- W0/W1 배정 경계: envelope 스키마 파일 자체를 W0에 반입하면 implementation-waves.md의 W1(계약 12종) 배정과 충돌한다 — 상호 검토에서 "W0 = ADR + 예시 3종 + 비보호 fixture, 스키마 파일은 W1"로 후퇴 확정했다.

## Current decision

**Envelope v1 = 9 공통 필드** (k3s §4.1의 8필드는 **동결 유지**, `event_type`을 9번째로 추가 — 이것이 본 ADR이 보유하는 편차):

| # | 필드 | 타입/형식 | 비고 |
|---|---|---|---|
| 1 | `event_id` | UUIDv7 | 정렬 가능 UUID |
| 2 | `tenant_id` | string | context별 요구/금지 규칙은 아래 참조 |
| 3 | `run_id` | string | context별 요구/금지 규칙은 아래 참조 |
| 4 | `schema_version` | semver string | 계약 버전(ADR-0012 호환성 정책 대상) |
| 5 | `producer` | string | 발행 서비스 식별자 |
| 6 | `occurred_at` | RFC3339 UTC timestamp | |
| 7 | `trace_id` | 32-hex string | W3C trace context 형식 |
| 8 | `idempotency_key` | string | at-least-once 배달 하의 중복 제거 키 |
| 9 | **`event_type`** | string, 패턴 아래 | **9번째 필드** — k3s §4.1 대비 편차(본 ADR 보유), topic name과 동일 값 |

`event_type` 패턴: `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){2,3}\.v[0-9]+$` (예: `patch.unit.completed.v1`). 이 값은 AsyncAPI 토픽 이름과 항상 동일해야 한다(1:1 매핑, 이중 관리 금지).

**W0/W1 경계**: 위 9필드 목록과 아래 구조·예시는 본 ADR(W0 산출물)로 확정한다. 실제 JSON Schema 파일(`packages/contracts/json-schema/envelope/v1/`)과 비보호 fixture corpus는 **W1 산출물**이다. 기존 8필드는 동결, `event_type`만 9번째로 추가 — 그 외 필드 추가/제거는 본 ADR 범위 밖.

**`context_type` discriminator**: enum `tenant | system | aggregate`. 구조는 `oneOf` 3-분기 + `unevaluatedProperties: false`로 봉인한다(각 분기 밖 프로퍼티 유입 차단 — ADR-0011이 확정한 2020-12 방언의 `unevaluatedProperties` 지원을 전제).

| context_type | `tenant_id` | `run_id` | 추가 필수 필드 |
|---|---|---|---|
| **tenant** | 필수 | run-scoped 이벤트는 필수 (non-run tenant 이벤트의 nullable 허용 여부는 **OPEN**, 아래) | — |
| **system** | **프로퍼티 자체 금지** | **프로퍼티 자체 금지** | — |
| **aggregate** | **프로퍼티 자체 금지** | **프로퍼티 자체 금지** | `aggregate_scope_id`(string), `cohort_size`(integer, ≥1), `privacy_threshold`(integer, ≥1), `de_identification_status`(enum: `k_anonymized`\|`suppressed`\|`pending_review`), `lineage_audit_ref`(opaque audit-ledger hash 문자열, **audit role 전용** 열람) |

system/aggregate에서 "금지"는 optional 취급이 아니라 **프로퍼티 자체가 스키마상 존재할 수 없음**을 의미한다(ADR-0006 rev.2의 "제거" 표현을 그대로 구조화).

필드 수 조정 기록: ADR-0006 rev.2 본문은 AggregateContext 필수 필드를 4종(`aggregate_scope_id`, `cohort_size`, `privacy_threshold`, `de_identification_status`)으로 명시하며, 본 ADR은 ADR-0006이 서술한 "원 tenant lineage는 접근 제한(audit role 전용) audit-ledger reference로만 보존" 조항을 5번째 필수 필드 `lineage_audit_ref`로 **구조화·확장**한다(승인된 Wave 0 계획 명세). 즉 ADR-0006과의 차이는 침묵 이탈이 아니라 lineage 조항의 필드화이다.

**k-anonymity 게이트의 스키마 한계**: `cohort_size ≥ privacy_threshold` 관계는 JSON Schema로 표현 불가능하다(두 필드 간 대소 비교는 2020-12에서도 직접 표현 수단 없음). 따라서 **발행측 런타임 게이트가 필수**(W2A 구현 대상) — 스키마는 각 필드의 타입·하한만 강제하고, 관계 위반은 애플리케이션 레벨에서 차단한다. 이 게이트를 우회한 위반 사례를 재현하는 fixture는 **계약 테스트에 영구 보존**(회귀 방지 — cohort_size < privacy_threshold 조합을 invalid로 검증하는 게 아니라, 게이트가 없으면 스키마만으로는 통과된다는 사실 자체를 문서화하는 fixture).

**`engine_id`**: observation·citation·experiment 계열 이벤트 **payload**에 필수. **닫힌 enum**: `["chatgpt-search"]`(v1 단일값). Google/Gemini 등 다른 값은 스키마 레벨에서 즉시 reject — CLAUDE.md "Engine scope v1: ChatGPT Search only, Google AI Overviews/AI Mode/Gemini는 optimize/observe/claim 금지" 원칙의 계약 레벨 집행. 엔진 추가는 **별도 재승인 + ADR + major 버전 bump**(ADR-0012 호환성 정책의 enum 확장=major 규칙과 정합).

**이벤트 명명 규칙**: `<domain>.<entity>.<action>.v<major>` — `event_type` 필드 값과 AsyncAPI 토픽 이름이 이 패턴을 공유한다.

## Constraints

- 기존 8필드(`event_id`~`idempotency_key`)는 **동결** — 본 ADR에서 추가·제거·의미 변경 없음. `event_type`만 9번째로 신규 추가.
- envelope 구조 자체의 추가 변경(9필드 초과, discriminator 분기 추가 등)은 ADR-0012의 "envelope = frozen, 변경은 새 ADR" 원칙에 따라 본 ADR 개정 또는 후속 ADR 필요.
- `lineage_audit_ref` 열람은 audit role 전용 — 일반 서비스 코드/로그에 원문 노출 금지.
- W0 산출물은 ADR + fixture(비보호)까지이며, `packages/contracts` 스키마 파일 작성은 W1로 이연한다 — 본 ADR을 근거로 W0에서 스키마 파일을 선반입하지 않는다.

## Open decisions

- tenant-scoped **비-run** 이벤트(`tenant.policy.updated.v1` 등)에서 `run_id`의 nullable 허용 여부 — **사용자 결정 대기** (가상 계획 §8 항목 9).
- 이벤트 스토어에서 `tenant_id` 열람 role의 구체 정의 — ADR-0006 rev.2 Open decisions 항목, 안 A 채택에 따른 후속.
- `lineage_audit_ref`의 audit-ledger 저장 포맷(해시 알고리즘, 체인 구조) — W1/W2A 세부 설계.

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §4.1 (:182, 8필드 목록 — 본 ADR이 9번째 필드 편차 해석 보유)
- `docs/decisions/ADR-0006-event-envelope-vs-anonymity.md` (rev.2, 3-context 모델 확정)
- `docs/architecture/api-event-contracts.md` (envelope 필드 표, `engine_id` PROPOSED)
- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §2.2 (:93), §8.4 (:555)

## Status

accepted (2026-07-12, 사용자)

---

## 부록: 예시 인스턴스 3종

### 1. TenantContext — `patch.unit.completed.v1`

```json
{
  "event_id": "018f3a1e-7c2b-7c3e-9b1a-4e2f1a9d3c7b",
  "context_type": "tenant",
  "tenant_id": "acme-co",
  "run_id": "run-2026-0712-0007",
  "schema_version": "1.0.0",
  "producer": "agent-runner",
  "occurred_at": "2026-07-12T09:14:32Z",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "idempotency_key": "acme-co:run-2026-0712-0007:patch-unit-042",
  "event_type": "patch.unit.completed.v1",
  "payload": {
    "patch_unit_id": "w1-04-quality-adrs",
    "worktree_commit": "9f1c2e7",
    "quality_gate_status": "passed"
  }
}
```

### 2. SystemContext — `adapter.config.updated.v1`

```json
{
  "event_id": "018f3a1f-2b1c-7d4a-8e6f-1a2b3c4d5e6f",
  "context_type": "system",
  "schema_version": "1.0.0",
  "producer": "policy-gate",
  "occurred_at": "2026-07-12T10:02:11Z",
  "trace_id": "7d3f1a9c8e2b4f6a0d5c3b1e9f7a2d4c",
  "idempotency_key": "adapter-config:chatgpt-search:v1.3.0",
  "event_type": "adapter.config.updated.v1",
  "payload": {
    "engine_id": "chatgpt-search",
    "adapter_version": "1.3.0",
    "changed_fields": ["rate_limit_per_minute"]
  }
}
```

### 3. AggregateContext — `strategy.card.eligible.v1`

```json
{
  "event_id": "018f3a20-9e4d-7a1b-b3c5-2d6f8a1c4e9b",
  "context_type": "aggregate",
  "schema_version": "1.0.0",
  "producer": "intelligence-worker",
  "occurred_at": "2026-07-12T11:47:03Z",
  "trace_id": "a1b2c3d4e5f60718293a4b5c6d7e8f90",
  "idempotency_key": "strategy-card:aggregate-scope-014:2026-07-12",
  "event_type": "strategy.card.eligible.v1",
  "aggregate_scope_id": "aggregate-scope-014",
  "cohort_size": 12,
  "privacy_threshold": 5,
  "de_identification_status": "k_anonymized",
  "lineage_audit_ref": "sha256:8f2e1c9a7b3d5f4e6a8c2b1d9f7e3a5c4b6d8f2e1c9a7b3d5f4e6a8c2b1d9f7e",
  "payload": {
    "engine_id": "chatgpt-search",
    "strategy_card_id": "card-0142",
    "intervention_category": "structured-data-markup"
  }
}
```

> 검증 기록: independent critic conformance review PASS (2026-07-12) — 사용자 G2 처리 지침("계획·결정 부합 시 사전 승인")의 조건 충족 확인.
