# ADR-0001: Google/Gemini adapter deployment shape

- Status: **accepted**
- Date: 2026-07-12 (decided: 2026-07-12, 사용자 승인)
- Deciders: 사용자 (repo owner)
- Decision: **안 A** — gateway 내장 + adapter 인터페이스는 `packages/provider-adapters` 8종(+AnswerExtractor) 후보와 1:1 대응하는 별도 코드 유닛으로 물리 분리. 안 C(gateway 소멸) 기각. Feature flag granularity는 adapter 단위 = 재승인 단위로 정렬.

## Purpose

v1에서 비활성인 Google 계열/Gemini engine adapter를 어떤 배포 형태로 유지할지 확정한다.

## Scope

In: `google-generative-search`, `gemini` adapter의 물리적 배포 단위와 코드 위치.
Out: v1 활성화 여부 (전 spec에서 비활성 CONFIRMED — 본 ADR 대상 아님), 활성화 승인 기준 (k3s §12).

## Context

두 spec 문장이 서로 다른 구조를 함의한다.

- Algorithm §6.1: "`google-ai-adapter`와 `gemini-adapter`는 **배포되더라도** scale 0 또는 feature flag off" — 독립 배포 가능한 컴포넌트(scale-0 Deployment) 함의.
- `docs/architecture/service-catalog.md` Constraints: "google/gemini adapters **not separate microservices** — behind `engine-adapter-gateway` + packages" — 별도 서비스가 아닌 gateway 내장 + `packages/provider-adapters/` 라이브러리 형태 확정.

후자가 ADR 없이 catalog constraint로만 기록되어 있어, CLAUDE.md 원칙 1(설계 문서 충돌 시 질문 후 중단)에 따라 본 ADR로 결정 지점을 명시한다.

## Current decision

**미결 — 양안 기록.**

| 안 | 형태 | 장점 | 단점 |
|---|---|---|---|
| A. Gateway 내장 (catalog 현행) | adapter = `packages/provider-adapters/*` 라이브러리, 배포 단위는 `engine-adapter-gateway` 하나 | 서비스 수 억제, v1 미사용 코드에 인프라 비용 0, feature flag 단일 지점 | Algorithm §6.1 문언과 불일치, 향후 provider별 독립 scale/rate-limit 분리 시 재구조화 |
| B. 독립 scale-0 Deployment (Algorithm §6.1 문언) | adapter별 Deployment, v1은 replicas 0 + flag off | spec 문언 일치, 활성화 시 배포 경로 기성 | 24 + N 서비스 계약·차트 관리 비용, 죽은 배포물 유지 |
| C. Gateway 소멸 — observer 내 라이브러리 (감사 중 제안) | gateway 자체를 두지 않고 chatgpt-observer에 흡수 | v1 최소 구성 | **감사 판정 ENCROACHMENT-RISK (aeo A2)**: 유일한 엔진 중립 통제 지점 소멸, ROL owner가 이미 엔진명 서비스인 상황에서 2번째 엔진 시 core 오염 필연. 채택 비권장 |

### 스코프 확장 (2026-07-12 감사 반영)

본 ADR는 다음을 함께 결정한다:

1. **Feature flag granularity (aeo F8)**: Helm flag 3종(`googleAiOverviews`/`googleAiMode`/`gemini`) vs adapter 패키지 2종(`google-generative-search`/`gemini`) 불일치. 재승인 단위 = adapter 단위가 되도록 정렬 필요 (예: AI Overviews만 재승인되는 시나리오 처리).
2. **Gateway 존폐 (안 C)**: 별도 트랙 결정 금지 — 본 ADR에서만 다룬다.
3. **spec 명칭 대응표 (boot B7)**: Algorithm §6.1 `google-ai-adapter` = 본 repo `packages/provider-adapters/google-generative-search`, `gemini-adapter` = `packages/provider-adapters/gemini`.

**Lead 권고 (2026-07-12 감사)**: 안 A + adapter 인터페이스는 `packages/provider-adapters` 8종 후보와 1:1 대응하는 별도 코드 유닛으로 유지 (observer 비즈니스 로직과 물리 분리).

채택 시 이 표를 결정·근거로 교체하고 Status를 accepted로 변경한다. 채택 전까지 scaffold는 A안 형태(현행)를 유지하되 이를 CONFIRMED로 표기하지 않는다.

## Constraints

- v1: Google AI Overviews / AI Mode / Gemini에 대한 optimize/observe/claim 금지 (전 spec 공통) — 본 결정과 무관하게 유지.
- 어느 안이든 `engine-adapter-gateway`의 provider adapter contract·feature flag가 단일 통제 지점.
- 활성화는 별도 재승인 필요 (k3s §12).

## Open decisions

- A/B 선택 (Architecture + Lead)
- 선택 후 service-catalog.md Constraints 문구 및 Algorithm §6.1 해석 주석 정합화 (spec 원본은 불변 — 본 ADR가 해석을 보유)

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.1
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §12
- `docs/architecture/service-catalog.md` Constraints

## Status

accepted (2026-07-12, 사용자) — 안 A
