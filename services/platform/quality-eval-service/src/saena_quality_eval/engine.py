"""`run_quality_evaluation` — the deterministic gate-engine orchestrator
(Algorithm §11, Release Gate; `JobKind.QUALITY_EVAL`).

Ties together every other module in this package:

1. `gate_ids`/`gates` — the closed gate vocabulary + pure per-gate functions.
2. `verification.build_verification_result` — one contract-validated
   `domain/verification-result/v1` row per gate.
3. `events.build_gate_event_payload` — one `quality.gate.passed.v1` /
   `quality.gate.failed.v1` payload per gate (mission item 9).
4. `audit.build_gate_audit_record` — one log-safe audit summary per gate
   (mission item 9, "audit per gate").

`run_quality_evaluation` is itself pure: it does not read the wall clock
(`QualityEvalRequest.evaluated_at` is caller-supplied), does not perform I/O,
and does not mutate any argument (every input type is a frozen dataclass).
Calling it twice with two SEPARATELY CONSTRUCTED but field-equal
`QualityEvalRequest` instances returns a result whose `canonical.
canonical_json` rendering is byte-identical (mission item 8 determinism,
item 11 re-run idempotency — asserted directly in
`tests/unit/svc_quality_eval/test_determinism_and_idempotency.py`).

A single failing gate — including (but not limited to) the 10 Algorithm
§11.1 gates — sets `QualityEvalOutcome.forbids_promotion = True`
(CLAUDE.md 원칙 8 "critical gates skip 금지": every gate this package
defines is blocking, there is no warn-only tier). Nothing in this module
creates a pull request, writes to a worktree, or marks a `ChangePlan`
promoted — `forbids_promotion=True` is a pure DATA signal a caller
(agent-orchestrator-service's `ExecutionWorkflow`, out of this package's
scope) is expected to act on by refusing to advance the patch unit past
the Release Gate; this package has no write capability to violate that
signal with even if it wanted to (ADR-0004 "quality-eval: 빌드 실행 권한만,
Git write 없음").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from saena_domain.execution import (
    JobKind,
    JobStatus,
    JobTransitionOutcome,
    profile_for,
    resource_limits_for,
    transition,
)
from saena_domain.execution.job_kind import JobKindProfile
from saena_domain.execution.limits import ResourceLimits

from saena_quality_eval.audit import GateAuditRecord, build_gate_audit_record
from saena_quality_eval.events import build_gate_event_payload
from saena_quality_eval.gate_ids import GateId
from saena_quality_eval.gate_result import GateResult
from saena_quality_eval.gates import (
    gate_accessibility,
    gate_boundary,
    gate_build,
    gate_changed_line_coverage,
    gate_commit_coherence,
    gate_content_fidelity,
    gate_crawlability,
    gate_diff_rationality,
    gate_forbidden_file,
    gate_generated_code_drift,
    gate_integration_tests,
    gate_link_route,
    gate_lint,
    gate_performance,
    gate_schema_contract,
    gate_secret_scan,
    gate_security,
    gate_structured_data,
    gate_tests,
    gate_typecheck,
    gate_unit_tests,
)
from saena_quality_eval.inputs import (
    AccessibilityOutcome,
    BoundaryOutcome,
    BuildOutcome,
    ContentFidelityOutcome,
    CoverageReport,
    CrawlabilityOutcome,
    GeneratedCodeDriftOutcome,
    LinkRouteOutcome,
    LintOutcome,
    PatchDiff,
    PerformanceOutcome,
    SchemaContractOutcome,
    SecretScanOutcome,
    SecurityScanOutcome,
    StructuredDataOutcome,
    TestOutcome,
    TypecheckOutcome,
)
from saena_quality_eval.verification import build_verification_result

#: `JobKind.QUALITY_EVAL`'s static boundary facts (pool/read_only/
#: service_account/producer_id) and default `ResourceLimits`, sourced
#: directly from the shared execution-domain layer this service builds on
#: (`saena_domain.execution.job_kind`/`limits`) — re-exported here so a
#: caller wiring this engine behind a real k3s Job does not need a second
#: import of `saena_domain.execution` just to look these up.
QUALITY_EVAL_PROFILE: JobKindProfile = profile_for(JobKind.QUALITY_EVAL)
QUALITY_EVAL_RESOURCE_LIMITS: ResourceLimits = resource_limits_for(JobKind.QUALITY_EVAL)


@dataclass(frozen=True, slots=True)
class GateInputBundle:
    """Every already-collected, deterministic gate input this engine needs
    for one full quality-eval run. Every field is itself an immutable value
    object (`inputs.py`) — constructing a `GateInputBundle` performs no I/O."""

    build: BuildOutcome
    unit_tests: TestOutcome
    integration_tests: TestOutcome
    lint: LintOutcome
    typecheck: TypecheckOutcome
    schema_contract: SchemaContractOutcome
    security: SecurityScanOutcome
    boundary: BoundaryOutcome
    coverage: CoverageReport
    secret_scan: SecretScanOutcome
    generated_code_drift: GeneratedCodeDriftOutcome
    link_route: LinkRouteOutcome
    crawlability: CrawlabilityOutcome
    structured_data: StructuredDataOutcome
    content_fidelity: ContentFidelityOutcome
    accessibility: AccessibilityOutcome
    performance: PerformanceOutcome
    diff: PatchDiff


@dataclass(frozen=True, slots=True)
class QualityEvalRequest:
    """Everything `run_quality_evaluation` needs — a patch artifact
    reference (already resolved via `manifest.resolve_patch_artifact` into a
    plain dict, mission item 1), the approved contract's facts (`contract.
    extract_approved_contract_facts`), a caller-supplied `evaluated_at`
    (NEVER generated internally — determinism), and the full `GateInputBundle`.
    """

    tenant_id: str
    run_id: str
    patch_unit_id: str
    worktree_commit: str
    artifact_base_commit: str
    approved_base_commit: str
    approved_patch_unit_ids: frozenset[str]
    evaluated_at: str
    gate_inputs: GateInputBundle
    report_uri: str | None = None


@dataclass(frozen=True, slots=True)
class QualityEvalOutcome:
    """Aggregate result of one `run_quality_evaluation` call."""

    verification_results: tuple[dict[str, Any], ...]
    events: tuple[tuple[str, dict[str, Any]], ...]
    audit_records: tuple[GateAuditRecord, ...]
    forbids_promotion: bool
    overall_status: str

    def gate_result_for(self, gate_id: GateId) -> dict[str, Any]:
        """Convenience lookup: the `VerificationResult` dict for `gate_id`."""
        for result in self.verification_results:
            if result["gate_id"] == str(gate_id):
                return result
        raise KeyError(f"no VerificationResult for gate_id={gate_id!r}")


def _combined_test_outcome(unit: TestOutcome, integration: TestOutcome) -> TestOutcome:
    """Combine `unit`+`integration` suite outcomes into one `TestOutcome`
    for the Algorithm §11.1 top-level `tests` gate row (Algorithm §11.1:
    "affected test + regression test 성공" — this engine treats the unit
    suite as the affected-test set and the integration suite as the
    regression set; both must pass for the combined `tests` gate to pass)."""
    return TestOutcome(
        suite="unit+integration",
        total=unit.total + integration.total,
        passed=unit.passed + integration.passed,
        failed=unit.failed + integration.failed,
        failing_test_names=unit.failing_test_names + integration.failing_test_names,
    )


def _run_all_gates(request: QualityEvalRequest) -> tuple[GateResult, ...]:
    gi = request.gate_inputs
    return (
        gate_commit_coherence(
            approved_base_commit=request.approved_base_commit,
            artifact_base_commit=request.artifact_base_commit,
        ),
        gate_build(gi.build),
        gate_tests(_combined_test_outcome(gi.unit_tests, gi.integration_tests)),
        gate_unit_tests(gi.unit_tests),
        gate_integration_tests(gi.integration_tests),
        gate_lint(gi.lint),
        gate_typecheck(gi.typecheck),
        gate_schema_contract(gi.schema_contract),
        gate_security(gi.security),
        gate_boundary(gi.boundary),
        gate_changed_line_coverage(gi.coverage),
        gate_forbidden_file(gi.boundary.changed_files),
        gate_secret_scan(gi.secret_scan),
        gate_generated_code_drift(gi.generated_code_drift),
        gate_link_route(gi.link_route),
        gate_crawlability(gi.crawlability),
        gate_structured_data(gi.structured_data),
        gate_content_fidelity(gi.content_fidelity),
        gate_accessibility(gi.accessibility),
        gate_performance(gi.performance),
        gate_diff_rationality(gi.diff, approved_patch_unit_ids=request.approved_patch_unit_ids),
    )


def run_quality_evaluation(request: QualityEvalRequest) -> QualityEvalOutcome:
    """Run every gate in this engine's registry against `request` and
    aggregate the result. Pure — see module docstring."""
    gate_results = _run_all_gates(request)

    verification_results = tuple(
        build_verification_result(
            tenant_id=request.tenant_id,
            run_id=request.run_id,
            patch_unit_id=request.patch_unit_id,
            worktree_commit=request.worktree_commit,
            evaluated_at=request.evaluated_at,
            gate_result=gate_result,
            report_uri=request.report_uri,
        )
        for gate_result in gate_results
    )
    events = tuple(
        build_gate_event_payload(
            gate_result, patch_unit_id=request.patch_unit_id, report_uri=request.report_uri
        )
        for gate_result in gate_results
    )
    audit_records = tuple(
        build_gate_audit_record(gate_result, evaluated_at=request.evaluated_at)
        for gate_result in gate_results
    )
    forbids_promotion = any(not gr.passed for gr in gate_results)
    return QualityEvalOutcome(
        verification_results=verification_results,
        events=events,
        audit_records=audit_records,
        forbids_promotion=forbids_promotion,
        overall_status="failed" if forbids_promotion else "passed",
    )


def next_job_status(outcome: QualityEvalOutcome) -> JobStatus:
    """`JobStatus.FAILED` iff any gate failed, else `JobStatus.SUCCEEDED` —
    the terminal status a caller should drive `JobKind.QUALITY_EVAL`'s job
    lifecycle towards for this run's outcome."""
    return JobStatus.FAILED if outcome.forbids_promotion else JobStatus.SUCCEEDED


def advance_job_status(current: JobStatus, outcome: QualityEvalOutcome) -> JobTransitionOutcome:
    """Apply `saena_domain.execution.transition` to move `current` towards
    `next_job_status(outcome)` — reuses the shared execution-domain
    lifecycle state machine verbatim rather than re-implementing job-status
    transition legality in this package."""
    return transition(current, next_job_status(outcome))


__all__ = [
    "QUALITY_EVAL_PROFILE",
    "QUALITY_EVAL_RESOURCE_LIMITS",
    "GateInputBundle",
    "QualityEvalOutcome",
    "QualityEvalRequest",
    "advance_job_status",
    "next_job_status",
    "run_quality_evaluation",
]
