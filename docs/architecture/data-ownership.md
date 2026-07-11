# Data ownership

## Purpose

Per-service owned data and store classes.

## Scope

Logical ownership only. Physical schemas NOT IMPLEMENTED.

## Current decision

**CONFIRMED** ownership column from Algorithm §6.2.  
**CONFIRMED** store classes from Algorithm §6.4 (Postgres, ClickHouse, object storage, vector, graph P1, Redis ephemeral).

## Ownership table

See `service-catalog.md` and each `services/**/README.md` "Owned data" field.

## Store classes (CONFIRMED intent)

| Store | Use | Principle | Owner (2026-07-12 감사 — PROPOSED) |
|---|---|---|---|
| PostgreSQL | tenancy, workflow, Action Contract, policy, metadata | strong transactions | schema-per-service (17종 매핑 가능 — service-catalog Owned data 기준). 물리 배치 OPEN |
| Temporal persistence DB | workflow execution history | external DB (k3s §7) | agent-orchestrator-service. 각주: 서비스의 "workflow state"는 Temporal history의 **도메인 projection**이며 Temporal 내부 스토리지의 재정의가 아님 |
| ClickHouse | event/observation/metrics analytics | append-only | 테이블별: chatgpt-observer(ROL), citation-intelligence, experiment-attribution, observability 후보 — **OPEN DECISION**. tenant partition/row policy 규칙 필요 |
| Object storage | raw responses, snapshots, artifacts, SBOM | content hash + lifecycle | manifest = artifact-registry. **blob 쓰기 단일 관문 = artifact-registry** (직접 쓰기 금지 — PROPOSED) |
| Qdrant/pgvector | retrieval | tenant partition | demand-graph/claim-evidence/entity-resolution 후보 — OPEN DECISION |
| Graph store | QEEG/TAG | P1 | QEEG: 논리 소유는 3분할 유지(demand-graph/entity-resolution/claim-evidence), 물리 owner = claim-evidence 잠정 + **CQRS read-only projection** (하단 규칙). TAG owner — OPEN DECISION |
| Redis | locks, rate limits, short-lived state | not system of record | lock 소유 서비스·tenant key prefix 규칙 — OPEN DECISION |

## Cross-cutting read model 규칙 (PROPOSED — 감사 aeo F15)

QEEG projection·RunContext 실험 파라미터·engine-neutral gateway가 반복 노출한 카테고리 공백. 규칙:

1. 여러 서비스 데이터를 조인하는 read model은 **CQRS projection**으로만 구성 — 원 소유 서비스의 이벤트를 구독해 자체 뷰 구축. 원본 스키마 직접 접근 금지.
2. projection은 **쓰기 권한 없음** — 수정은 반드시 원 소유 서비스의 command API 경유.
3. projection마다 owner 서비스 명시 필수 — "누구 것도 아닌 공유 뷰" 금지 (소유 완화 방식은 감사에서 ENCROACHMENT 판정).
4. RunContext는 분할 소유: run lifecycle/승인 메타 = forge-console-api / 실험 설계 파라미터(engine, locale, observation cell) = experiment-attribution (사전등록 불변성 — 등록 시점 hash를 audit-ledger에 앵커링).

## Constraints

- Own DB or own schema per service
- No PII/secrets in event payloads — object refs + access policy
- Tenant identifiers on core records (see tenancy-model.md)

## Open decisions

- Graph store product choice — OPEN DECISION
- Managed vs in-cluster data services per profile — see deployment-profiles.md

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §6.2, §6.4
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §4

## Status

CONFIRMED ownership intent / NOT IMPLEMENTED schemas
