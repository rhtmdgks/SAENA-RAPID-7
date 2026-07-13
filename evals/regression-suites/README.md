# evals/regression-suites

See ../README.md. Scaffold approved 2026-07-12 (ADR-0007 D-7).

## 등재 스위트 (Wave 3 구현)

- Prompt pkg §12 회귀 세트 8종 (../README.md) — **NOT IMPLEMENTED / GAP**
  (w3-10 scope: this unit builds the 9-axis eval harness + the extraction-
  architecture test; the Prompt pkg §12 regression set needs real agent-run
  trace artifacts to fixture against, which do not exist yet in this repo —
  reported here, not fabricated).
- k3s §10 failure-mode 9종 ↔ fixture 1:1 매핑 — **IMPLEMENTED (w3-10)**.
  `failure_modes/fm-01..09.yaml`, one file per k3s §10 row: `status`
  (`covered`/`gap`) + `covering_axis` (one of the 9 mandatory axes, or
  `regression_suite_native` for a dedicated non-axis check) +
  `covering_fixture_ids`/`covering_test`. **9/9 `covered`** (w3-12 resolved
  the former `fm-05-skill-compromise` gap: a dedicated skill-bundle
  content-integrity verifier — `saena_domain.execution.skill_bundle` —
  now exists and is enforced fail-closed at both the session_start and
  agent-runner boundaries; the regression check exercises the real verifier).
  Verified by
  `tests/unit/evals_harness/test_failure_mode_regression_suite.py::
  test_all_nine_k3s_failure_modes_are_mapped`.
- **추출 아키텍처 테스트 (ADR-0002 rev.3 규칙 12)**: worker-hosted 모듈을 독립 배포로
  분리해도 모듈 코드 변경 0 검증 — 경계 이벤트·published interface 규칙 위반 검출 —
  **IMPLEMENTED (w3-10)**. `tests/unit/evals_harness/
  test_extraction_architecture.py` (3 independent legs: `.importlinter`
  declared-set-vs-real-packages check, a real `lint-imports` subprocess run,
  and an independent `ast`-based cross-service-import scan — none of the 24
  service packages import a sibling service's Python code directly).

`failure_modes/*.yaml` also backs 4 `regression_suite_native` checks (code
conflict / secret exposure / scope creep / measurement fraud) that are not
one of the 9 mandatory eval axes but were needed to close the k3s §10
mapping honestly — implemented directly in
`tests/unit/evals_harness/test_failure_mode_regression_suite.py` over real
`saena_agent_runner.worktree`/`.scope` and `saena_hooks_runtime.redact`
(measurement fraud is the one exception: no experiment-attribution service
exists yet, so that check is a harness-owned encoding of the Algorithm
§11.3 business-integrity rule rather than a wrapper around production code
— see that fixture's own `notes`).
