# quality-eval-service

| Field | Value |
|---|---|
| Service name | `quality-eval-service` |
| Bounded context | Deterministic quality gates |
| Primary responsibility | build, test, lint, schema, link, a11y, content-evidence, diff eval |
| Owned data | test/eval evidence |
| Consumed contracts | patch units; quality-gates.yaml |
| Published events | quality.gate.passed.v1; quality.gate.failed.v1 |
| Consumed events | patch.unit.completed.v1 |
| Upstream dependencies | agent-runner-service |
| Downstream consumers | artifact-registry-service; agent-orchestrator-service; audit-ledger-service |
| Security boundary | critical gates skip 금지; independent of author agent self-eval |
| Planned runtime | k3s Job (`JobKind.QUALITY_EVAL`, `runner` pool, build-exec only, NO Git write, SA `saena-quality-eval` — ADR-0004) |
| Domain area | `platform` |
| Implementation status | **PARTIAL — W3 deterministic gate engine (w3-04)** |

## Source specification references

- `docs/specs/SAENA_AEO_Algorithm_and_Harness_Design_v1.md` §11.1 (필수 Quality Gates)
- `docs/specs/SAENA_k3s_Package_and_Operations_Spec_v1.md` §3–4
- `docs/architecture/execution-runtime.md` (`JobKind.QUALITY_EVAL` row, W3 shared execution-domain layer)
- `docs/decisions/ADR-0004-node-pool-revision-untrusted-jobs.md` (runner pool, 3-way ServiceAccount split)
- `docs/decisions/ADR-0017-test-tooling-quality-gates.md` (changed-line coverage ≥90% blocking, critical-gate-skip-금지)
- `packages/contracts/json-schema/domain/verification-result/v1/verification-result.schema.json`
- `packages/contracts/json-schema/event/quality-gate-result/v1/quality-gate-result.schema.json`
- `packages/contracts/json-schema/domain/patch-artifact/v1/patch-artifact.schema.json`
- `packages/contracts/json-schema/domain/change-plan/v1/change-plan.schema.json`

## Status

PARTIAL (w3-04) — `saena_quality_eval` package implements a pure,
deterministic Release Gate quality-gate engine:

- 21 gates (`gate_ids.GateId`): the 10 Algorithm §11.1 mandatory gates
  (build, tests, link/route, crawlability, structured data, content
  fidelity, security, accessibility, performance, diff rationality) plus 11
  additional gates this patch unit adds (`commit_coherence`,
  `schema_contract`, `lint`, `typecheck`, `unit_tests`,
  `integration_tests`, `boundary`, `changed_line_coverage`,
  `forbidden_file`, `secret_scan`, `generated_code_drift`). Every gate is
  BLOCKING — no warn-only tier (ADR-0017 "critical gate 스킵 불가").
- `manifest.resolve_patch_artifact` — patch artifact manifest-ref
  resolution via `saena_domain.persistence.ArtifactManifestPort`, validated
  against `domain/patch-artifact/v1`.
- `contract.extract_approved_contract_facts` — approved `ChangePlan` ->
  base commit / patch-unit ids / approved scope, validated against
  `domain/change-plan/v1`.
- `verification.build_verification_result` — one contract-validated
  `domain/verification-result/v1` row per gate (Ruling R4 bidirectional
  `failures` rule enforced at the `GateResult` value-object layer too).
- `events.build_gate_event_payload` — `quality.gate.passed.v1` /
  `quality.gate.failed.v1` via the shared
  `saena_domain.execution` builders.
- `audit.build_gate_audit_record` — log-safe per-gate audit summary
  (`error_code`s only, ADR-0015 scope).
- `engine.run_quality_evaluation` — the orchestrator: aggregates every
  gate into `QualityEvalOutcome` (`forbids_promotion`, `overall_status`),
  deterministic (same inputs -> byte-identical result, asserted directly)
  and idempotent (pure functions, no I/O, no side effects).
- `protocols.py` — `BuildRunner`/`TestRunner`/`SecurityScanner`/
  `SecretScanner`/`GeneratedCodeDriftScanner`/`CoverageReporter` Protocol
  adapters + pure in-memory `Fake*` reference implementations (no real
  subprocess/build in this patch unit).
- Redaction (`redaction.py`): a planted secret never reaches a
  `GateResult`/`VerificationResult` unredacted; `JobError`'s own
  construction-time stack-trace guard is exercised end-to-end.

NOT in this patch unit's scope: a real subprocess-invoking `BuildRunner`/
`TestRunner`/scanner adapter (build tool, pytest, secret/security scanner,
`diff-cover` — Protocol shape only, later unit), k3s Job manifest/Dockerfile,
bus publisher wiring for the emitted event payloads (system-wide w2-18
concern), `quality-gates.yaml` (canonical gate-list authoring, referenced
but not owned by this contract).

### Integrator action required

`saena-quality-eval` is NOT YET a registered `[tool.uv.workspace]` member in
root `pyproject.toml` (root config is outside this patch unit's exclusive
write paths) — `tests/unit/svc_quality_eval/conftest.py` inserts
`services/platform/quality-eval-service/src` onto `sys.path` directly as a
workaround. An Integrator should add
`services/platform/quality-eval-service` to root `pyproject.toml`'s
`[tool.uv.workspace].members` + `[dependency-groups].dev` +
`[tool.uv.sources]` (mirroring every other `services/platform/*-service`
entry there) so this package becomes a normal editable-installed workspace
member, and that `sys.path` workaround can then be removed from `conftest.py`.
