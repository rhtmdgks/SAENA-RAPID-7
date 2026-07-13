# evals/

## Purpose

Prompt·skill·policy 회귀 평가 스위트 — k3s spec §2 요구 구획, Prompt pkg §12의 물리 위치. 프롬프트 승격 게이트: 회귀 세트 통과 없이 prompt/skill/policy bundle 승격 금지.

## Scope

| 구획 | 내용 |
|---|---|
| fixtures/ | 고정 평가 입력 (spec §12 회귀 세트) |
| trace-graders/ | agent run trace 채점기 |
| policy-tests/ | policy bundle 회귀 (deny/allow 케이스) |
| regression-suites/ | prompt 버전 간 회귀 실행 정의 |

## 필수 회귀 세트 (Prompt pkg §12 — CONFIRMED 목록)

- B2B SaaS source repos in different frameworks
- factual claim conflict cases
- security/secret injection fixtures
- deceptive schema fixtures
- unsupported pricing/security claim fixtures
- deployment/push temptation cases
- source-code-only boundary cases
- patch minimality and rollback cases

추가 (2026-07-12 감사): k3s §10 failure-mode 9종 ↔ fixture 1:1 매핑 필수 (sec F-8).
→ w3-10 (2026-07-13): `regression-suites/failure_modes/fm-01..09.yaml` — 8/9 `covered`,
1/9 (`fm-05-skill-compromise`, pinned-skill-hash 미구현) 정직하게 `gap` 보고.
`tests/unit/evals_harness/test_failure_mode_regression_suite.py::
test_all_nine_k3s_failure_modes_are_mapped`가 매핑 완결성을 검증.

## w3-10 구현 (deterministic eval harness — 9 eval axes)

Algorithm §12 + testing-strategy.md 요구에 따라 fixture-based·seeded·no-wall-clock 채점기 구현.
엔진/채점기는 `evals/engine/` (스캐폴드된 `fixtures/`/`trace-graders/`/`policy-tests/`/
`regression-suites/` 디렉터리 이름은 하이픈 포함 — Python dotted-import 경로가 될 수 없어
실행 코드는 `evals/engine/`에 두고, 위 4개 디렉터리는 데이터(YAML fixture)·문서 역할만 유지),
pytest entrypoint는 `tests/unit/evals_harness/`.

9 필수 축 (`evals/engine/scorers/__init__.py::AXIS_SCORERS`), 각각 실제 repo 프로덕션 코드 위:

| # | Axis | 실제 대상 코드 | Fixture 위치 | FP/FN guard |
|---|---|---|---|---|
| 1 | patch_correctness | `saena_quality_eval` (GateResult/GateId/verification) | `fixtures/patch_correctness/` (4) | ✅ |
| 2 | contract_compliance | `packages/contracts/json-schema/**` (jsonschema) | `fixtures/contract_compliance/` (4) | ✅ |
| 3 | approval_enforcement | `saena_agent_runner.approval` (ADR-0003) | `fixtures/approval_enforcement/` (5) | ✅ |
| 4 | tenant_isolation | `saena_domain.identity.http.reconcile_tenant` (ADR-0014) | `fixtures/tenant_isolation/` (4) | ✅ |
| 5 | failure_recovery | `saena_domain.execution` (JobError/JobStatus/transition) | `fixtures/failure_recovery/` (5) | ✅ |
| 6 | reproducibility | `saena_quality_eval.verification` + `saena_domain.audit.canonical` | `fixtures/reproducibility/` (4) | ✅ |
| 7 | evidence_integrity | `evals.engine.evidence_registry` (CLAUDE.md principle 11) | `fixtures/evidence_integrity/` (4) | ✅ |
| 8 | forbidden_action | `saena_hooks_runtime.rules.deploy_push` + `EngineId` | `policy-tests/forbidden_action/` (7) | ✅ |
| 9 | handoff_completeness | `saena_hooks_runtime.hooks.before_handoff` + audit chain | `fixtures/handoff_completeness/` (5) | ✅ |

Every fixture: seeded, explicit `expected_passed`/`expected_score`/`threshold`, fail-closed on
malformed input (`evals/engine/fixture.py::FixtureLoadError`). CI-blocking: every test lives
under `tests/unit/evals_harness/` (never `tests/integration/**`), so it runs in the deterministic
unit lane (`just test` / `pytest -m "not integration"`) — no container, no marker changes needed.

Extraction-architecture test (dependency-policy.md rule 12, ADR-0002 rev.3):
`tests/unit/evals_harness/test_extraction_architecture.py` — 3 independent legs (declared
`.importlinter` independence-contract set derived from real `services/**/pyproject.toml`, the
REAL `lint-imports` CLI run as a subprocess, and an independent `ast`-based cross-service-import
scan) proving the worker-module boundary holds now.

## Constraints

- 모든 run 기록: prompt pkg version, skill versions, Ponytail SHA, policy version, contract hash, repo SHA, image digest (Prompt pkg §12)
- Critical gate 회귀 없이는 어떤 prompt 갱신도 승격 금지

## Status

9 eval axes + extraction-architecture test + k3s §10 failure-mode mapping: IMPLEMENTED (w3-10,
2026-07-13). Prompt pkg §12의 8종 회귀 세트(B2B SaaS 다양 프레임워크, factual claim conflict 등)는
이번 유닛 범위 밖(에이전트 실행 결과물이 아직 없음) — 미착수, GAP으로 보고. `fixtures/`/
`trace-graders/`/`policy-tests/`/`regression-suites/`의 개별 README 참조.
