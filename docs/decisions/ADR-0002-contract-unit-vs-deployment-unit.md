# ADR-0002: Contract unit vs deployment unit (24 services)

- Status: **accepted** (rev.3 — 2026-07-12 외부 리뷰 R1·R2·R7·R9 반영, 사용자 승인)
- Date: 2026-07-12
- Deciders: 사용자 (repo owner)
- Decision (rev.3): "**24 logical capabilities** = 불변 (Gate A), rendering(배포 형태) = 운영 결정" + **모듈 통합 발동**.

  **격리·경계 모델 (R1 정정)**: 격리 단위 = 프로세스/Pod만 — credential·장애·보안 격리는 이 수준에서만 성립. worker 내 모듈 = **논리·소유권 경계** (보안 경계 아님). 모듈별 Postgres role/user + own-schema GRANT는 유지하되 목적 = ① 결함 봉쇄(실수 cross-schema 접근 DB 거부) ② 감사 가시성 ③ 추출 시 credential 무변경 이관. **위협모델: worker 프로세스 침해 = 동거 모듈 전 credential·데이터 노출 가정** — 이 가정 하에서도 최고 민감 자산(SourceSnapshot·PatchArtifact)은 worker 밖(runner Job + artifact-registry 독립)이므로 통합 유효.

  **모듈 경계 규칙 (R2 — rev.2의 "bus-only" 대체)**:
  1. 경계 이벤트 필수 — 타 bounded context가 소비하는 상태 변화(계약 이벤트)는 반드시 발행, 동거 모듈이 소비자여도 in-process 대체 금지. **transactional outbox**로 원자성.
  2. 모듈 내부 상태·중간 계산 = bus 강제 없음.
  3. 동거 모듈 간 동기 호출 = published contract interface 경유만 (내부 함수·스키마 직접 접근 금지) — 코드 리뷰 + 언어 확정 후 lint/아키텍처 테스트.
  4. 추출 불변식: "worker 분리 시 모듈 코드 변경 0" — evals 아키텍처 테스트.

  **최종 rendering**: Deployment 10 = independent 8 (control 6: console-api, plan-contract, policy-gate, orchestrator, audit-ledger, tenant-control + artifact-registry + engine-adapter-gateway) + worker host 2 (compute pool, ADR-0004 발동). Job 이미지 5. Worker host는 capability로 세지 않음 (R9).
  - `intelligence-worker`: demand-graph, entity-resolution, claim-evidence, citation-intelligence (P0) + absorption-analysis (P1 off)
  - `optimization-worker` (구 analytics-worker — R7 개명): intervention-generator (P0) + digital-twin, portfolio-optimizer, experiment-attribution, strategy-skill-bank (P1 off; 실험 등록 원장은 Wave 4 활성). **measurement-worker 추출 트리거**: ① DiD 배치가 optimization SLO·리소스 간섭 ② 등록 원장이 별도 RBAC tier·배포 주기 요구 ③ 팀 소유 분리 — 충족 시 experiment-attribution(±skill-bank) 추출, 규칙 4 덕에 코드 변경 0 목표.

  기각 대안: 24 개별 배포(0-6주 팀 운영 비용 극대), 1-worker(장애 반경 최대 + 도메인 소유 혼합).

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

accepted rev.3 (2026-07-12, 사용자) — 모듈 통합 발동, 경계 규칙 §4종, optimization-worker 개명
