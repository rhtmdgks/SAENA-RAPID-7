# ADR-0008: v1 contract format — JSON Schema family, gRPC/Proto deferred

- Status: accepted
- Date: 2026-07-12 (외부 리뷰 R6, 사용자 승인 — spec 권위)
- Deciders: 사용자 (repo owner)

## Purpose

v1 계약 포맷을 확정하고, k3s spec §1 "Internal API: gRPC + Protobuf" (CONFIRMED)와의 편차를 기록한다.

## Scope

In: 도메인·서명 계약, 동기 API, 이벤트 포맷, proto 재도입 조건.
Out: envelope 필드 (ADR-0006), 계약 우선순위 (synthesis §7).

## Current decision

**v1 포맷 — 단일 JSON Schema 패밀리:**

| 계약 유형 | 포맷 |
|---|---|
| 도메인·사람 서명 계약 (ChangePlan/ApprovalDecision/QueryExperiment 등) | JSON Schema |
| 동기 API | **OpenAPI + JSON** |
| 비동기 이벤트 | AsyncAPI + 공통 JSON Schema |
| Proto/gRPC | **이연** — 측정된 필요 발생 시 별도 ADR로 도입 |

**JSON↔Proto 이중 매핑은 v1에서 제거** (기존 Wave 1 작업 삭제).

## Context — proto 이연의 측정 근거

- 내부 low-RPS 환경 (B부서 전용, 파일럿 3~5개) — gRPC의 직렬화·HTTP/2 이득이 측정 불가 수준
- 대형 payload는 전부 object storage ref (k3s §4.1 "PII·secret payload 금지, object reference만") — proto 크기 이득의 주 대상이 계약상 부재
- v1 플로우에 streaming RPC 없음 (runner 실행은 Temporal 비동기, 관측은 Job)
- 언어 스택 미정 (OPEN) — proto codegen 툴체인 선결정은 순서 역전
- 서명·감사 산출물은 사람 판독 대상 — JSON이 evidence-first 원칙에 적합

**k3s §1 CONFIRMED 편차**: 본 ADR가 해당 조항의 v1 구현 해석을 보유 (spec 원본 불변). ADR-0002(계약≠배포 단위)와 동일 패턴.

## Proto/gRPC 재도입 트리거 (측정 가능 — 충족 시 별도 ADR + 해당 경로만 전환)

1. 핫 동기 경로(runner→policy-gate)의 p99 latency가 결정 캐싱 적용 후에도 SLO 초과
2. 이벤트 직렬화 CPU가 worker CPU의 10% 초과
3. streaming RPC 요구 발생 (v1 플로우에 없음)
4. 다언어 SDK 배포 필요

## Constraints

- `packages/contracts` 구획: json-schema/ + openapi/ + asyncapi/ (proto/는 예약 — 트리거 충족 ADR 전 비움)
- 계약 24종 버전 관리(Gate A)·단일 owner(Steward)·compatibility test 원칙 불변

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §1 (:20), §2, §4
- 외부 Architecture Review R6 (2026-07-12); Synthesis rev.2 §8

## Status

accepted (2026-07-12, 사용자)
