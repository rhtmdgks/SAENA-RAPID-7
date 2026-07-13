# Implementation waves

## Purpose

승인된 Synthesis rev.2의 구현 순서. Wave 진입·종료 기준·테스트·롤백 명시.

## Scope

계획만 — 코드·manifest는 각 Wave 착수 승인 후.

## Current decision (CONFIRMED — 2026-07-12 Synthesis rev.2 §10)

### W0 — 결정·거버넌스 (잔여)
언어 스택·monorepo 툴링 / design §13 7건 (GRS·ToS·source access·LLM retention·법무 SLA·PR 권한·k3s 사양) / bootstrap 요구 문서 원문 / PII vs immutable audit 법무.

### W1 — 계약
P0 12종 (contract-catalog.md) + 3-context envelope + engine_id + compatibility tests. 포맷 = ADR-0008 (proto 매핑 없음). Entry: 언어 확정. Exit: P0 스키마 12종 + 호환성 테스트 green.

### W2A — 승인 코어
forge-console-api, tenant-control, plan-contract, policy-gate, audit-ledger + PostgreSQL + 승인 플로우(제안→승인, per-unit).
- Entry: W1 exit. / Exit: 승인 E2E(제안→Gate 검증→승인→audit chain), **policy-gate fail-closed 데모**(gate 다운 시 승인 불가), deny 우회 회귀(kubectl patch·`git -c` push 등) 통과.
- Tests: 상태머신, hash chain, RBAC, 계약 호환. / Rollback: helm rollback + expand/contract migration (destructive 금지).
- 이벤트는 **transactional outbox 기록까지** — bus 배선은 2C.

### W2B — 오케스트레이션·아티팩트
agent-orchestrator + Temporal + artifact-registry + MinIO + engine-adapter-gateway.
- Entry: 2A exit + Temporal persistence DB (owner=orchestrator). / Exit: WAITING_APPROVAL→EXECUTING **signal 경로** E2E (ADR-0003 — Gate 거부 시 Temporal 전이 불가 검증), blob 단일 관문 검증, Activity `startToCloseTimeout ≥ 7200s+buffer` + heartbeat 정합.
- Tests: §4.3 전 상태 전이, signal 재시도, blob 우회 차단. / Rollback: workflow 버전 롤백 + manifest 불변성.

### W2C — 버스·관측·패키징
Redpanda + OTel 스택 + `saena-forge` Helm chart + forgectl + control-plane synthetic E2E.
- Entry: 2A/2B exit. / Exit: outbox drain→토픽 발행(3-context envelope 검증), 대시보드 6종 최소 구동, `forgectl preflight` 통과(Google flag on 시 fail 포함).
- Tests: envelope 회귀, consumer idempotency, preflight 실패 케이스. / Rollback: chart 전체 helm rollback + event replay freeze (k3s §8.4).

### W3 — Execution
Job 5종(runner/intake/quality-eval + observer/discovery, SA 3분리 — ADR-0004) + hooks 5종 실장 + synthetic tenant Plan→승인→patch→handoff E2E + evals 가동(추출 아키텍처 테스트 포함) + failure-mode 9종↔fixture 매핑 + rollback 동작 검증 gate.

### W4 — Intelligence
intelligence-worker P0 4 모듈 + chatgpt-observer(browser pool) + QEEG read-only projection + **ClickHouse·vector 도입** (시간 파티션+ORDER BY 규칙 — ADR-0007 rev.2) + 실험 등록 원장(hash 앵커링).

### W5 — Measurement·B계층
optimization-worker measurement 기능 활성(DiD) + `deployment.confirmed.v1` 7일 clock + `outcome_layer` B-gate(skill-bank는 B 검증 통과만 소비) + evidence bundle + GRS 정책(§13 결정 후). measurement-worker 추출은 트리거 충족 시 (ADR-0002 rev.3).

### Future
P1 flag-on 승격(absorption, digital-twin, portfolio-opt, skill-bank), SaaS(request-scoped 테넌시 + RLS 2차 + api-gateway), air-gap, 2nd provider adapter(별도 재승인 후만).

## Constraints

- 각 Wave 착수 = 인간 승인. Critical gate skip 금지. Wave 내 실패 시 rollback 절차 우선.

## Source specification references

- Algorithm spec §12; k3s spec §5, §8, §11; Synthesis rev.2 §10; ADR-0002 rev.3, 0003, 0004, 0007, 0008

## Status

CONFIRMED 계획 / W0-W1 구현 완료 / **W2A/W2B/W2C 구현 완료 (w2-01..w2-21,
wave2-runtime, 2026-07-13) — 코드 레벨 exit 조건 전 항목 PASS, 증거는
`docs/architecture/wave2-exit-report.md` 참조. deploy/infra 레벨 항목
(saena-forge Helm chart, 대시보드 6종, 프로덕션 Temporal/MinIO/Redpanda 배포,
helm rollback drill)은 BLOCKED(human) — `deploy/**` 보호 경로 + 라이브
클러스터 부재, 동일 문서 참조** / **W3 CONFIRMED (Execution, wave3-execution,
2026-07-13) — Job 5종·hook 5종·SA 3분리·synthetic E2E·evals(추출 아키텍처
테스트)·failure-mode 9종·rollback gate 전 항목 PASS, 증거는
`docs/architecture/wave3-exit-report.md`. production-only 항목(라이브 클러스터
배포, 대시보드 live 구동, browser pool=W4)은 정직히 범위 밖 기록** / **W4
CONFIRMED (Intelligence, PR #5+#6 merged to main `156568c`, 2026-07-13) —
intelligence-worker P0 4모듈·chatgpt-observer·ClickHouse/vector·실험 등록 원장,
증거 `docs/architecture/wave4-exit-report.md`** / **W5 PASS (code +
static-deployment mechanism, Measurement·B-Layer, wave5-measurement HEAD
`dab5e9a`, Wave 5 Closure 2026-07-14) — 24/24 seed unit 통합·유닛별 독립
adversarial critic·`just verify` green 3×: DiD 측정 활성
(experiment-attribution-service), deployment.confirmed.v1 7일
clock(Temporal durable timer, time-skipping 검증), outcome_layer ≥2 독립 layer
B-gate, evidence bundle, GRS 정책 mechanism(값은 BLOCKED §13-7), skill-bank
B-verified-only intake, 실 composed E2E(real PG16/CH24.8/Temporal), 완전
failure-mode matrix+F-9 repoint, conflicting-confirmation seam, w5-21
saena-forge Helm static wiring(SecretRef-only, 하드닝, GRS 값 없음). closure
MUST-FIX 수정+재검증: c5-03 security(multi-conflict hash crash), c5-01
zero-collected guard(3중), c5-06 audit-a(hyphen-infix `sk-live-` secret가
skill-bank production pool 유입 — 3 guard 수정). 증거
`docs/architecture/wave5-exit-report.md`. LIVE OPEN: 라이브 클러스터
install/rollback(미실행, 미주장). BLOCKED(human): 실 GRS 임계값/SLA(§13-7),
ChatGPT 관측 methodology/ToS(§13-1), PII-vs-audit legal. c5-04 Helm은
Lead-direct(H8 인간 승인 `9099c1d`, 독립 critic PASS); c5-06 audit-b(fail-closed/
tenant/replay)는 spawned auditor stall로 Lead-fallback 검증(정직 공시). 외부
lift 주장 없음. merge는 인간(PR #7).**
