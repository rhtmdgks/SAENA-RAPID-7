# ADR-0002: Contract unit vs deployment unit (24 services)

- Status: **accepted**
- Date: 2026-07-12 (decided: 2026-07-12, 사용자 승인)
- Deciders: 사용자 (repo owner)
- Decision: 수렴 토폴로지 채택 — "계약 24종 = 불변 (Gate A), 배포 단위 = 운영 결정". 독립 7 + worker 5 + 병합 1 + OPEN 1(ADR-0001로 해소) 확정. **모듈 후보 10종의 통합 여부는 언어/런타임 결정 전까지 보류 유지** (개별 배포가 기본값).

## Purpose

"24개 마이크로서비스"가 계약 단위인지 배포 단위인지 확정하고, 초기 배포 토폴로지를 정한다.

## Scope

In: Deployment/Job/모듈 물리 배치, node pool 매핑, Gate A 해석.
Out: 서비스 경계·데이터 소유권 자체 (24종 bounded context는 CONFIRMED 유지), engine-adapter-gateway 형태 (ADR-0001).

## Context

k3s spec §0 "24개 마이크로서비스를 하나의 signed Helm release로 설치"는 24=배포 단위로 읽힐 개연성이 크나, Gate A(§11)의 요구는 "all 24 service API/event contracts versioned" — 계약 수 기준이다. 하나의 Helm release는 임의 개수의 Deployment를 가질 수 있어 두 해석이 분리 가능하다. 5-감사자 교차 검토(2026-07-12)에서 수렴된 토폴로지:

| 분류 | 서비스 | 형태 |
|---|---|---|
| 독립 Deployment (7) | forge-console-api, plan-contract, policy-gate, agent-orchestrator, audit-ledger(RBAC 별도 tier), tenant-control, artifact-registry | control pool (artifact-registry는 별도 tier) |
| worker Job (5) | agent-runner, repository-intake, quality-eval (runner pool, SA 3분리) / chatgpt-observer, site-discovery (browser pool, 권한 차등) | K8s Job / Temporal activity |
| 모듈 후보 — 조건부 (10) | demand-graph, entity-resolution, claim-evidence, citation-intelligence, absorption-analysis, intervention-generator, digital-twin, portfolio-optimizer, experiment-attribution, strategy-skill-bank | 조건: 언어/런타임의 schema 접근 강제 격리 증명 + compute pool 신설(ADR-0004). 미충족 시 개별 배포 유지 |
| 병합 (1) | observability → OTel Collector + Prometheus/Loki/Tempo + Grafana dashboards-as-code + Alertmanager webhook adapter | 책임은 SRE + emit 서비스로 재배분 — 서비스 소멸 아님(§6.2 #23 유지, 구현체가 기성 스택) |
| OPEN (1) | engine-adapter-gateway | ADR-0001 |

교차 검토 이력: tenant-control·artifact-registry 모듈화는 security REJECT + platform DISAGREE + architecture 자기 정정으로 기각. "배포 ≈10" 원안은 언어 스택 미정(OPEN)으로 조건부 하향.

## Current decision

**미결 — Lead 권고: 위 수렴 토폴로지 채택.** 원칙: "계약 24종 = 불변 (Gate A), 배포 단위 = 운영 결정". 모듈 통합은 언어 스택 결정 전까지 보류(개별 배포가 기본값).

## Constraints

- own DB/schema per service, no shared DB — 배치 형태와 무관하게 유지
- 모듈화하더라도 event envelope·schema-per-service·서비스별 DB 유저 격리 유지 (aeo 교차 검토 조건)
- Gate A "24 계약 버전 관리" 불변

## Open decisions

- 언어/monorepo 툴링 (모듈 통합의 전제)
- 채택 시 k3s §0 문언 해석을 본 ADR가 보유함을 requirements-matrix에 기재

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §0, §5.2, §11 Gate A
- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2
- 감사 보고서 (2026-07-12, 5-감사자 교차 검토)

## Status

accepted (2026-07-12, 사용자) — 모듈 통합만 언어 결정 후 보류
