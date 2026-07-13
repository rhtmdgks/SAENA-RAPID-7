"""saena_quality_eval — quality-eval-service (`JobKind.QUALITY_EVAL`, W3).

Pure/deterministic Release Gate quality-gate engine (Algorithm §11,
`docs/architecture/execution-runtime.md`'s `QUALITY_EVAL` row: `runner`
pool, build-exec only, NO Git write, `saena-quality-eval` ServiceAccount).
No I/O, no subprocess, no wall-clock read anywhere in this package's own
code — every gate function (`gates.py`) and the orchestrator
(`engine.run_quality_evaluation`) is a pure function over already-collected,
caller-supplied input value objects (`inputs.py`); `protocols.py` fixes the
Protocol call SHAPE a later patch unit's real subprocess-invoking adapters
(build tool, pytest, secret/security scanners, `diff-cover`) would satisfy,
alongside pure in-memory `Fake*` reference implementations this package's
own unit tests exercise.

Public API surface:

- `gate_ids.GateId` / `ALGORITHM_11_1_GATE_IDS` / `ADDITIONAL_GATE_IDS` /
  `ALL_GATE_IDS` — the closed gate vocabulary.
- `gate_result.GateResult` / `passed` / `failed` — pure per-gate outcome.
- `inputs.*` — deterministic, immutable gate INPUT value objects.
- `protocols.*` — adapter Protocols (`BuildRunner`/`TestRunner`/
  `SecurityScanner`/`SecretScanner`/`GeneratedCodeDriftScanner`/
  `CoverageReporter`) + their `Fake*` in-memory reference implementations.
- `gates.gate_*` — one pure function per `GateId`.
- `manifest.resolve_patch_artifact` — patch artifact manifest-ref
  resolution (`ArtifactManifestPort` -> validated `PatchArtifact` dict).
- `contract.extract_approved_contract_facts` — approved `ChangePlan` ->
  `ApprovedContractFacts` (base commit / patch-unit ids / approved scope).
- `verification.build_verification_result` — `GateResult` ->
  `domain/verification-result/v1`-validated dict.
- `events.build_gate_event_payload` — `GateResult` ->
  `(quality.gate.passed.v1 | quality.gate.failed.v1, payload)`.
- `audit.build_gate_audit_record` — `GateResult` -> log-safe per-gate audit
  summary.
- `engine.run_quality_evaluation` — the full orchestrator:
  `QualityEvalRequest` -> `QualityEvalOutcome` (verification results +
  events + audit records + `forbids_promotion`).
- `errors.*` — this package's exception hierarchy (ADR-0015 taxonomy).

See `docs/architecture/execution-runtime.md` for the `QUALITY_EVAL`
`JobKind` row this service implements, and each module's own docstring for
the authority behind its specific rules (Algorithm §11.1 table,
ADR-0017 coverage policy, CLAUDE.md Protected paths, ADR-0011
codegen-is-SSOT).
"""

from __future__ import annotations

from saena_quality_eval.audit import GateAuditRecord, build_gate_audit_record
from saena_quality_eval.contract import ApprovedContractFacts, extract_approved_contract_facts
from saena_quality_eval.engine import (
    QUALITY_EVAL_PROFILE,
    QUALITY_EVAL_RESOURCE_LIMITS,
    GateInputBundle,
    QualityEvalOutcome,
    QualityEvalRequest,
    advance_job_status,
    next_job_status,
    run_quality_evaluation,
)
from saena_quality_eval.errors import (
    ApprovedContractValidationError,
    PatchArtifactReferenceError,
    QualityEvalError,
    VerificationResultValidationError,
)
from saena_quality_eval.events import (
    QUALITY_GATE_FAILED_EVENT_TYPE,
    QUALITY_GATE_PASSED_EVENT_TYPE,
    build_gate_event_payload,
)
from saena_quality_eval.gate_ids import (
    ADDITIONAL_GATE_IDS,
    ALGORITHM_11_1_GATE_IDS,
    ALL_GATE_IDS,
    GateId,
)
from saena_quality_eval.gate_result import GateResult
from saena_quality_eval.manifest import resolve_patch_artifact
from saena_quality_eval.verification import build_verification_result

__all__ = [
    "ADDITIONAL_GATE_IDS",
    "ALGORITHM_11_1_GATE_IDS",
    "ALL_GATE_IDS",
    "QUALITY_EVAL_PROFILE",
    "QUALITY_EVAL_RESOURCE_LIMITS",
    "QUALITY_GATE_FAILED_EVENT_TYPE",
    "QUALITY_GATE_PASSED_EVENT_TYPE",
    "ApprovedContractFacts",
    "ApprovedContractValidationError",
    "GateAuditRecord",
    "GateId",
    "GateInputBundle",
    "GateResult",
    "PatchArtifactReferenceError",
    "QualityEvalError",
    "QualityEvalOutcome",
    "QualityEvalRequest",
    "VerificationResultValidationError",
    "advance_job_status",
    "build_gate_audit_record",
    "build_gate_event_payload",
    "build_verification_result",
    "extract_approved_contract_facts",
    "next_job_status",
    "resolve_patch_artifact",
    "run_quality_evaluation",
]
