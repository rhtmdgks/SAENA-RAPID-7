# ADR-0007: Final synthesis — ownership finalization, ROL neutrality, v1 edge, infra staging

- Status: accepted
- Date: 2026-07-12 (최종 Architecture Synthesis, 사용자 승인)
- Deciders: 사용자 (repo owner)

## Purpose

최종 합성(D-2·D-3·D-4·D-6)의 확정 사항을 기록한다. ADR-0002 rev.2(모듈 통합)와 한 세트.

## Scope

In: ROL 엔진 중립화 방식, 미확정 owner 4건, v1 edge, 인프라 도입 시점, blanket 파티션 규칙.
Out: 배포 토폴로지(ADR-0002 rev.2), 승인 경로(ADR-0003), envelope(ADR-0006).

## Current decision

### 1. ROL 엔진 중립화 = 계약 수준 (D-2)

`PlatformObservation` 계약을 `engine_id` 포함 엔진 중립형으로 정의. chatgpt-observer-service는 그 **첫 구현체** — 서비스명 유지(개명 비용>효익), 중립 observation-service 신설 기각(조기 추상화, Ponytail 위반). 2번째 엔진 = 동일 계약을 쓰는 신규 observer, core 재작업 0.

### 2. Owner 확정 4건 (D-3)

| 대상 | Owner | 근거 |
|---|---|---|
| WorkspaceContext, ProjectContext, **UsageRecord** | tenant-control-service | 테넌트 계층·quota·budget = tenant policy의 연장. 소유(tenant-control)·집행(agent-runner values)·관측(OTel 스택) 3분리 |
| ContentRecord | site-discovery-service | asset inventory. claim↔asset 엣지는 claim-evidence 소유 |
| QEEG 물리 projection | claim-evidence-service | 최하류 + evidence gate 보유. read-only CQRS (data-ownership.md 규칙) |
| TAG projection | experiment-attribution-service | 행동→실제 결과 연결 종점, 학습 루프 입력. read-only CQRS |

### 3. v1 edge = forge-console-api 단독 (D-4)

`apps/api-gateway`는 **FUTURE (SaaS)** 격하 — north-south gateway는 SaaS 외부 노출 시점에 재도입. service-catalog의 "forge-console-api vs api-gateway" OPEN DECISION 종결. 폴더는 보존(재도입 경로).

### 4. 인프라 스테이징 (D-6)

Wave 2 = Postgres + Temporal + Redpanda + MinIO(object storage) + OTel 스택. **ClickHouse·vector store는 Wave 4 도입** — 용도(관측·대량 분석)가 관측 개시 전 무용. Graph store는 P1 원안 유지. spec §6.4 스토어 클래스 불변 — 도입 시점만 스테이징.

### 5. Tenant discriminator vs physical partition (rev.2 — 외부 리뷰 R3 반영, blanket 규칙 철회)

~~전 스토어의 1차 파티션·prefix 키 = tenant_id~~ → 2계층으로 교체:

- **Tenant discriminator (논리, 필수)**: 모든 tenant-scoped 레코드·이벤트에 `tenant_id` 컬럼/필드. 면제 = global system metadata (SystemContext — ADR-0006 rev.2).
- **Physical partition (스토어별 결정)**: Postgres = schema-per-capability + tenant_id 인덱스/RLS(2차 방어) / ClickHouse = **시간 파티션** + ORDER BY (tenant_id, …) prefix — tenant별 파티션 금지(고카디널리티 파티션 폭발) / Redis = tenant prefix / Object storage = tenant path prefix / Vector = 제품별 collection·namespace 결정.

### 6. Bootstrap 정리 (D-5)

- `deploy/environments/` 삭제 — profiles × values overlay 단일 축 (plat D6 종결)
- `CODEOWNERS.example` 삭제 — 활성 CODEOWNERS로 대체 완료
- prompts/ 5종 + evals/ 4구획 스캐폴드 승인 (D-7; 원문 = Prompt pkg §4–9)

## Constraints

- 계약 24종·Gate A 불변. no shared DB·이벤트 상태 전파 원칙 불변.
- projection은 read-only — 수정은 원 소유 서비스 command API 경유만.

## Open decisions

- 언어 스택·monorepo 툴링 (W1 착수 전) / design §13 7건 / bootstrap 요구 문서 원문 / PII vs immutable audit (법무)

## Source specification references

- 최종 Architecture Synthesis 보고서 (2026-07-12), ADR-0001~0006
- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §3.2, §6.4; k3s spec §3, §7

## Status

accepted (2026-07-12, 사용자)
