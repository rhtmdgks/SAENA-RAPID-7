# ADR-0004: Node pool revision — untrusted Jobs and compute pool

- Status: **accepted**
- Date: 2026-07-12 (decided: 2026-07-12, 사용자 승인)
- Deciders: 사용자 (repo owner)
- Decision: 권고안 채택 — runner pool 확장("customer source 다루는 모든 Job = runner pool") + SA 3분리, browser pool 권한 차등, Redpanda/Redis/Temporal-DB = data pool. compute pool은 ADR-0002 모듈 통합 채택 시에만 신설 (현재 조건부 유지).

## Purpose

k3s spec §5.2 노드 풀 5종에 배정되지 않은 워크로드(untrusted 고객 코드 Job, 계산 모듈 host)의 배치를 확정한다.

## Scope

In: repository-intake·quality-eval Job의 pool 배정, Redpanda/Redis/Temporal persistence의 pool 배정, (ADR-0002 모듈 채택 시) compute pool 신설.
Out: pool별 리소스 사양.

## Context

§5.2는 control/data/runner/browser/gpu-optional 5종만 정의. 감사 발견(plat D3, MED-HIGH): repository-intake(고객 repo clone+SBOM/secret scan)와 quality-eval(고객 build/test 실행)의 Job은 untrusted 고객 코드를 직접 실행하나 pool 미배정 — control/data pool 오배치 시 격리 누수. Redpanda·Redis·Temporal persistence도 pool 미배정(plat D11).

## Current decision

**미결 — Lead 권고 (감사 수렴안):**

1. **runner pool 확장**: "customer source를 다루는 모든 Job은 runner pool 상속" 규칙 명문화 — agent-runner + repository-intake + quality-eval. 단 ServiceAccount는 3분리 (security 조건):
   - agent-runner: worktree write, 계약 범위 파일만
   - quality-eval: 빌드 실행 권한만, Git write 없음, egress는 approved package registry만
   - repository-intake: read-only Git만
2. **browser pool 권한 차등**: chatgpt-observer(관측) / site-discovery(read-only 크롤, Git credential 미발급 sub-profile)
3. Redpanda·Redis → data pool 명시. Temporal persistence → data pool (owner: agent-orchestrator, ADR-0002 연계)
4. (조건부) ADR-0002 모듈 통합 채택 시: 신규 `compute` pool (`saena.io/role=compute`) — Temporal worker/계산 모듈 host. agent runner·browser 배치 금지, tenant workspace 없음. control pool 재사용 불가 (저지연 게이팅 vs 계산 집약 리소스 경쟁)

## Constraints

- §5.2는 CONFIRMED 표 — 본 ADR 채택 전 임의 확장 금지
- data pool "untrusted browser 금지" 원칙 유지 — untrusted Job도 동일 적용

## Open decisions

- gpu-optional pool과 compute pool 통합 여부 (P0에서 GPU 비필수)

## Source specification references

- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §5.2 (:250-258)
- 감사 보고서 Medium (plat D3·D11, sec P3 완화 조건, arch P-D3 수용)

## Status

accepted (2026-07-12, 사용자) — compute pool은 ADR-0002 모듈 결정 연동 조건부
