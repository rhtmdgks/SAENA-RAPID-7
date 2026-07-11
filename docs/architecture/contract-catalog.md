# Contract catalog

## Purpose

계약 21종의 owner·producer·consumer·우선순위·포맷·키·민감도·보존 단일 카탈로그. Synthesis rev.2 §7 + 감사 3표(architecture/platform/security) 병합.

## Scope

계약 정의 카탈로그만 — 실제 스키마 파일은 `packages/contracts/`(NOT IMPLEMENTED, Wave 1).

## Current decision

**CONFIRMED** (2026-07-12, Synthesis rev.2 + ADR-0007/0008): 포맷 = JSON Schema(서명·도메인) / OpenAPI+JSON(동기) / AsyncAPI+JSON Schema(이벤트). 공통: envelope 3-context (ADR-0006 rev.2), correlation = `trace_id`(+run-scoped는 `run_id`), version = additive-only + breaking 시 major bump + compatibility test.

## P0 — Wave 1 (12종)

| 계약 | Owner | Producer → Consumer | Idempotency key | Sensitivity | Retention |
|---|---|---|---|---|---|
| TenantContext | tenant-control | tenant-control → 전 tenant-scoped capability | tenant_id+policy_version | internal | 계약 존속+법정; 해지 파기 절차 OPEN |
| ActorContext | forge-console-api | console(RBAC) → policy-gate, audit, plan-contract | actor_id+session | **PII** | 부인방지 장기 ↔ PII 최소화: ledger에는 actor_id만, 신원 매핑 분리 보관 |
| WorkspaceContext | tenant-control (ADR-0007) | tenant-control → intake, runner | workspace_id | internal | workspace 수명 |
| ProjectContext | tenant-control (ADR-0007) | tenant-control → demand-graph, experiment-attr | project_id | internal/customer-proprietary | 계약 존속 |
| SiteContext | site-discovery | site-discovery → demand-graph, intervention-gen, observer | site_id+inventory_version | public(도메인)+internal | 사이트 활성 기간 |
| RunContext (분할) | lifecycle=forge-console-api / 실험 파라미터=experiment-attribution (ADR-0007) | console → 전 run-scoped | run_id | customer-proprietary 메타 | run 후 재현성 장기; secret 참조 금지 |
| SourceSnapshot | repository-intake | intake → discovery, runner, audit | repo SHA (content hash) | **customer-proprietary 최고** | per-run workspace+TTL; 중앙 보존은 customer policy, hash만 ledger |
| ChangePlan (=Action Contract) | plan-contract | plan-contract → orchestrator, policy-gate, runner, audit | contract_hash | customer-proprietary | 승인 후 immutable; **+evidence_ledger_hash, scope glob 상한, diff 예산 필드 (H-3/H-7)** |
| ApprovalDecision | plan-contract | console(서명) → orchestrator, policy-gate, audit | contract_hash+approver actor_id | **PII**+internal | 계약적 장기 immutable + 서명 |
| PatchArtifact | artifact-registry (manifest) | agent-runner → quality-eval, registry, audit, console | patch_unit_id+worktree_commit | **customer-proprietary 최고 (diff=소스)** | customer policy; tenant-scoped 암호화 |
| VerificationResult | quality-eval | quality-eval → orchestrator, registry, audit, console | run_id+patch_unit_id+gate_id | internal | audit retention (성공 선언 증거) |
| AuditEvent | audit-ledger | 전 plane → ledger 기록 | event hash (chain) | internal+actor PII 최소화 | contractual, immutable role; payload PII/secret 금지 |

## P1 — Wave 3–4 (8종)

| 계약 | Owner | 비고 |
|---|---|---|
| CrawlResult | site-discovery | public+제3자 PII 가능; robots/ToS 보존 |
| ContentRecord | site-discovery (ADR-0007; claim↔asset 엣지는 claim-evidence) | 게시 전 draft=customer-proprietary — 등급 전환 규칙 OPEN |
| ExtractedClaim | claim-evidence | claim_id; 유효일 버전 보존 |
| EvidenceRecord | claim-evidence | evidence_id; freshness 필수; 인용 span 최소화 |
| EntityRecord | entity-resolution | entity_id+graph_version |
| PlatformObservation | chatgpt-observer (첫 구현체 — 계약은 엔진 중립, **engine_id 필수**, ADR-0007) | raw는 object ref만; customer+ToS, encrypted |
| QueryExperiment | experiment-attribution | 사전등록 후 immutable — 등록 hash를 audit-ledger 앵커링 (H-3); JSON Schema(사람 서명 계열) |
| OptimizationProposal | intervention-generator | P2→P1 승격 (intervention-gen W4 활성) |

## P2 (1종)

| 계약 | Owner | 비고 |
|---|---|---|
| UsageRecord | tenant-control (ADR-0007) | billing 계약. v1 cost telemetry는 본 계약 불요 — runner `maxCostUsdPerRun` 집행 + OTel cost 메트릭 + per-tenant budget 대시보드로 충족 |

## Constraints

- 단일 owner: Contracts Steward 역할 (카테고리별 분리 승인 + 2인 검토 + CODEOWNERS)
- Cross-capability read model은 CQRS read-only projection만 (data-ownership.md 규칙): QEEG=claim-evidence, TAG=experiment-attribution
- PII 계약(ActorContext/ApprovalDecision)의 삭제권 vs immutable audit — 법무 검토 OPEN

## Open decisions

- ContentRecord 게시 전후 sensitivity 등급 전환 규칙 / TenantContext 해지 파기 절차 / PII vs audit (법무)

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §3.1, §5.2–5.3; k3s spec §4, §9.3; Prompt pkg §1
- ADR-0006 rev.2, ADR-0007, ADR-0008; Synthesis rev.2 §7–§9

## Status

CONFIRMED 카탈로그 / NOT IMPLEMENTED 스키마 (Wave 1)
