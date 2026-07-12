# ADR-0024: W1 contract deviations — customer_id→tenant_id, compat vocabulary, cross-file $ref, pattern=breaking, no envelope-duplicate identifiers, uri pattern

- Status: accepted
- Date: 2026-07-12 (Wave 1 계획 승인 문답, 사용자)
- Deciders: 사용자 (repo owner)

## Purpose

W1(계약 12종 구현)에서 발견된, 상위 spec 원문과의 6건 편차·해석을 이 ADR 하나에 모아 해석 권위를 기록한다 — ADR-0002/ADR-0008/ADR-0013이 확립한 "spec 원본 불변, 편차 해석은 별도 ADR 보유" 패턴을 W1 전 계약에 일괄 적용한다.

## Scope

In: (a) `ChangePlan.customer_id`→`tenant_id` 개명, (b) registry `compat_class`/`signed` 어휘 확정 및 비서명 closed 계약 6종 승인, (c) 계약 간 cross-file `$ref` 규칙(common 카테고리 한정 + `/vN/` 경로 고정 + common 파일도 registry/compat 대상), (d) `pattern` 필드 변경의 open-class breaking 승격, (e) event payload에서 envelope 중복 식별자 투영 금지 + `plan.contract.approved` payload의 `approver_actor_id` 배제, (f) uri 계열 필드 공통 패턴.
Out: 개별 계약 파일 자체의 전체 필드 목록(각 계약 저작 unit 소관 — w1-04~07), envelope 필드 목록 자체(ADR-0013 소관, 본 ADR은 payload 투영 금지 규칙만 다룸), codegen 도구 확정(w1-02/w1-12).

## Context

- **(a) customer_id→tenant_id**: `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §5.2(:254)의 Action Contract 예시는 `"customer_id": "tenant-scoped-id"` 필드명을 쓴다. 그러나 `docs/architecture/api-event-contracts.md:70-80`(Core business identifiers)은 전 계약이 공유해야 할 핵심 식별자 목록에 `customer_id`가 아니라 `tenant_id`를 명시하며, ADR-0014(tenant propagation)가 이미 `tenant_id`를 이벤트·HTTP·관측 3경로의 유일 권위 식별자로 확정했다. `customer_id`를 그대로 반입하면 동일 개념에 두 필드명이 공존하는 상태가 되어 ADR-0014의 "이벤트 페이로드 내 별도 tenant 필드 중복 금지"(§Constraints)와 직접 충돌한다. ADR-0008/ADR-0013이 이미 "spec 원문은 불변으로 두고 편차 해석은 ADR이 보유" 패턴을 두 차례 확립했다 — 동일 패턴을 여기 적용한다.
- **(b) compat 어휘**: ADR-0012는 계약 class를 "서명 계약(closed) / 이벤트 payload(open) / envelope(frozen)"으로 3분했고 "서명 계약"이라는 표현으로 closed와 signed(사람 서명)를 사실상 동일시했다. 그러나 W1 필드 조사 결과 closed(구조적으로 봉인, `additionalProperties:false`)이면서도 사람 서명 대상이 아닌 계약(TenantContext, ActorContext, run-context-experiment, SourceSnapshot, PatchArtifact, AuditEvent)이 다수 확인되어, closed와 signed를 하나의 어휘로 묶으면 "closed=서명 대상"이라는 잘못된 함의가 registry에 새겨진다.
- **(c) cross-file $ref**: canonical-JSON 비교(closed/frozen class, ADR-0012)는 대상 파일 자체의 바이트 비교를 전제하는데, 계약이 다른 파일을 `$ref`로 참조하면 참조 대상 파일이 바뀌어도 참조하는 쪽 파일의 바이트는 불변이라 diff가 사각지대에 빠진다(Wave 1 계획 §1.1 R3).
- **(d) pattern 변경**: ADR-0012는 enum 변경(축소·확장 불문)을 major로 정정했다(§Current decision "enum 규칙"). `pattern`(정규식) 필드도 동일한 forward/backward-incompatible 위험을 갖는다 — 완화(허용 문자열 확대)는 enum 확장과 동형으로 구 consumer가 신규 값을 인식 못할 위험, 강화(허용 문자열 축소)는 enum 축소와 동형으로 기존 유효 값이 거부될 위험이다. 강화만 major로 보는 비대칭은 enum 규칙과 논리적으로 불일치한다.
- **(e) 중복 식별자·PII 필드**: Security critic이 두 가지를 MUST-FIX로 지정했다 — event payload에 envelope가 이미 나르는 `tenant_id`/`run_id`를 다시 투영하면 ADR-0014의 "중복 금지" 원칙 위반 및 두 값이 分岐(divergence)할 경우의 신뢰 불확실성이 생긴다. `plan.contract.approved` payload의 `approver_actor_id`는 k3s spec §4.1의 payload PII/secret 금지 원칙(사람 식별자를 이벤트 payload에 원문 노출) 위반 소지 — 승인자 식별은 `ApprovalDecision` 서명 계약(감사 대상, RBAC 제한)에서만 조회 가능해야 한다.
- **(f) uri 필드**: `snapshot_uri`(SourceSnapshot)·`artifact_uri`(PatchArtifact) 등 uri 계열 필드에 query string/fragment를 허용하면 presigned URL의 토큰이 스키마 레벨 검증을 통과한 채 계약 인스턴스에 실려 로그·audit trail로 유출될 경로가 열린다(Security critic MUST-FIX) — object reference만 허용하고 자격증명 성격의 쿼리 파라미터는 구조적으로 차단해야 한다.

## Current decision

**(a) `customer_id` → `tenant_id` 개명 (해석 권위)**: `packages/contracts/json-schema/domain/change-plan/v1/`의 `ChangePlan` 계약은 Algorithm spec §5.2(:254)의 `customer_id` 필드명을 **`tenant_id`로 개명**하여 구현한다. spec 원문(§5.2 예시)은 불변으로 남기고, 본 ADR이 이 필드명 편차의 v1 구현 해석 권위를 보유한다 — ADR-0002(24 서비스 vs 배포 단위)/ADR-0008(proto 이연) 편차 선례와 동일 패턴. 근거: `docs/architecture/api-event-contracts.md:70-80`의 core identifier 목록이 `tenant_id`를 표준 명칭으로 지정하고, ADR-0014가 이벤트 payload 내 tenant 필드 중복 정의를 이미 금지했다 — `customer_id`를 그대로 두면 이 금지 원칙과 정면 충돌한다.

**(b) compat 어휘 확정**: `packages/contracts/registry.json`의 entry는 다음 두 필드를 **분리** 보유한다.

| 필드 | 값 | 의미 |
|---|---|---|
| `compat_class` | `closed` \| `open` \| `frozen` | ADR-0012의 3-class 호환성 정책 판정 축 — 구조적 봉인 여부(`additionalProperties:false`)와 진화 허용 정책을 가리킨다 |
| `signed` | boolean | 계약 인스턴스가 사람 서명(승인) 대상인지 여부. `true`인 계약은 `ChangePlan`, `ApprovalDecision` 2종뿐(v1) |

ADR-0012의 "서명 계약(closed)"이라는 표현은 본 ADR로 `signed=true ∧ compat_class=closed`로 **정밀화**한다 — closed이지만 signed=false인 계약이 실재함을 인정하고 registry에 반영한다. **비서명 closed 계약 6종 승인 기록(사용자 확정, 2026-07-12)**: `TenantContext`, `ActorContext`, `run-context-experiment`, `SourceSnapshot`, `PatchArtifact`, `AuditEvent` — 이 6종은 `compat_class: closed`, `signed: false`로 registry에 등재한다(구조는 봉인하되 사람 서명 워크플로 대상이 아님).

**(c) cross-file `$ref` 규칙**:

1. 계약 파일 간 `$ref`는 **`common/` 카테고리 파일만 대상**으로 허용한다 — domain/context/event 계약이 서로를 직접 `$ref`하는 것은 금지(각 계약의 독립 버전 관리·N-1 비교 무결성 보호).
2. `$ref` 경로는 **`/vN/` major 버전 경로에 고정**한다(예: `.../common/error-detail/v1/error-detail.schema.json`) — minor/patch 변경은 참조 대상 파일이 같은 major 안에서 계속 호환 유지해야 하는 책임을 참조 대상 파일 자신의 compat 정책이 진다.
3. **`common/` 파일 자체도 registry entry + `compat_class` 지정 대상**이다(예외 없음) — canonical/구조 비교가 그 파일 자체의 변경을 정상적으로 검출하도록 하기 위함이며, 이것이 R3(cross-file 사각지대)의 해소책이다. `$ref`하는 쪽 파일의 바이트가 불변이어도, 참조되는 `common/` 파일의 compat 검사가 독립적으로 변경을 검출한다.
4. **W1 범위 밖**: 여러 파일에 걸친 "bundle" 단위의 resolved-schema 비교(참조를 전개한 뒤 통합 비교)는 W2 개선 항목으로 이연한다 — W1은 개별 파일 단위 compat 검사만 보장한다.

**(d) `pattern` 변경 = open-class breaking**: 이벤트 payload(open class, ADR-0012)에서 필드의 `pattern`(정규식) 값이 변경되면 — **강화(허용 범위 축소)든 완화(허용 범위 확대)든 방향 불문** — major 없이 이루어지면 breaking으로 판정한다. ADR-0012의 enum 양방향(narrowing/widening 모두 major) 판정과 동형 논리다: 완화는 구 producer가 만들 수 없던 값을 신규로 만들 가능성(구 consumer 미검증 값 유입)을, 강화는 기존에 유효했던 값이 거부될 가능성을 각각 열기 때문이다. `tests/contract/harness`의 구조 diff(structural_diff)는 `pattern` 변경을 required/type/enum과 동일한 breaking-후보 신호로 다룬다.

**(e) 중복 식별자·PII 배제**:

1. `events/` 하위 이벤트 payload 스키마는 envelope가 이미 나르는 `tenant_id`/`run_id`를 payload 안에 **재투영(duplicate)하지 않는다** — ADR-0014 §Constraints("이벤트 페이로드 내 별도 tenant 필드 중복 정의 금지")를 `run_id`까지 확장 적용한다. 위반 fixture(payload에 `tenant_id` 또는 `run_id` 키가 존재)는 각 이벤트 계약의 invalid fixture로 영구 보존한다(Security critic MUST-FIX 수용 기록).
2. `plan.contract.approved` 이벤트의 payload에서 **`approver_actor_id`를 배제**한다 — payload는 `contract_hash` 참조만 나른다(승인자 식별이 필요하면 `ApprovalDecision` 서명 계약을 `contract_hash`로 역참조해 RBAC 경유 조회). k3s spec §4.1의 payload PII 금지 원칙 집행이며 Security critic MUST-FIX 수용 기록이다.

**(f) uri 계열 필드 공통 패턴**: `snapshot_uri`, `artifact_uri`, `report_uri` 등 object-reference 목적의 uri 계열 필드는 공통 패턴을 적용한다.

```
^[a-z0-9+.-]+://[^?#]+$
```

scheme(`[a-z0-9+.-]+`) + `://` + query string(`?`)·fragment(`#`) **금지**(`[^?#]+`로 두 문자를 authority 이후 경로에서 배제). presigned URL의 토큰이 흔히 query string에 실리는 형태(예: `?X-Amz-Signature=...`)를 스키마 레벨에서 원천 차단한다 — Security critic MUST-FIX 수용 기록. 각 해당 계약(SourceSnapshot/PatchArtifact 등)의 invalid fixture에 query-string 포함 uri 사례를 반드시 포함한다.

## Constraints

- `customer_id`는 v1 어떤 계약 파일에도 필드명으로 등장하지 않는다 — 등장 시 리뷰 거부 사유.
- `registry.json` entry는 `compat_class`와 `signed`를 반드시 둘 다 명시한다(둘 중 하나 누락 = registry 스키마 위반).
- domain/context/event 계약 간 직접 `$ref`(common 우회) 금지. `$ref` 대상 경로에 `/vN/`이 없는 경우(major 미고정) 금지.
- open-class 계약의 `pattern` 필드 변경은 major bump 없이는 CI compat test에서 fail 처리한다(enum 규칙과 동일 취급).
- event payload 스키마에 `tenant_id`/`run_id` 프로퍼티가 존재하면 리뷰 거부 사유(단, envelope 레벨 필드는 예외 — 이 금지는 payload 컨테이너 내부에만 적용).
- `plan.contract.approved` payload에 `approver_actor_id` 또는 동등한 사람 식별 필드 반입 금지.
- uri 계열 필드에 `?`/`#` 문자를 허용하는 패턴 반입 금지.

## Open decisions

- 비-run tenant 이벤트 토픽의 `run_id` 처리 — ADR-0013 rev.2가 종결(해당 토픽 등장 시 그 토픽 ADR에서 재개정), 본 ADR은 (a)~(f) 범위 밖.
- bundle(resolved-schema) 단위 compat 비교 도입 여부·설계 — W2 개선 항목(위 (c)-4).
- `signed=true` 계약이 v1의 2종(ChangePlan/ApprovalDecision) 외로 확장될 경우의 서명 알고리즘·검증 책임 소재 — 미확정, 발생 시 별도 결정.

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §5.2 (:254, Action Contract 예시 `customer_id` 원문 — 본 ADR이 편차 해석 권위 보유)
- `docs/architecture/api-event-contracts.md` (:70-80, core business identifiers — `tenant_id` 표준 명칭 근거)
- `docs/decisions/ADR-0014-tenant-propagation.md` (§Constraints, 이벤트 payload tenant 필드 중복 금지 원칙)
- `docs/decisions/ADR-0012-contract-compatibility-policy.md` (§Current decision, enum 양방향 major 판정 — pattern 규칙의 동형 근거; "서명 계약(closed)" 표현의 정밀화 대상)
- `docs/decisions/ADR-0002-contract-unit-vs-deployment-unit.md`, `docs/decisions/ADR-0008-v1-contract-format.md` (spec 원문 불변 + ADR 편차 해석 권위 보유 패턴 선례)
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §4.1 (payload PII/secret 금지 원칙 — (e)-2 근거)
- Wave 1 계획 승인 문답 §1.1 R3/R5/R6/R7/R9, §1.2 항목 4 (`/Users/edmond104/.claude/plans/virtual-cooking-map.md`) — 룰링·사용자 확정 근거

## Status

accepted (2026-07-12, 사용자 — Wave 1 계획 승인)
