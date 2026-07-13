"""Pure, deterministic gate functions — one per `GateId` member.

Every function here has the shape `(typed input(s)) -> GateResult`: no I/O,
no wall-clock read, no randomness, no hidden mutable state. Calling any
function twice with equal (`==`) arguments always returns an equal
`GateResult` (mission item 8, "deterministic VerificationResult: same
inputs ⇒ byte-identical result" — asserted directly against these functions
in `tests/unit/svc_quality_eval/test_determinism_and_idempotency.py`, one
level below the full `engine.run_quality_evaluation` aggregate).

Gate ids and their Algorithm §11.1 / mission-item authority are documented
on `gate_ids.GateId` and on each input dataclass in `inputs.py` — this
module's docstrings focus on the pass/fail RULE each function applies, not
the authority (already documented at the type).
"""

from __future__ import annotations

from collections.abc import Iterable

from saena_domain.execution import JobError

from saena_quality_eval.gate_ids import GateId
from saena_quality_eval.gate_result import GateResult, failed, passed
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
from saena_quality_eval.redaction import redact_secret_snippet, redact_stack_trace, truncate

#: ADR-0017 "Changed-lines(diff-cover) >= 90%, blocking".
CHANGED_LINE_COVERAGE_THRESHOLD_PCT: float = 90.0

#: CLAUDE.md "Protected paths" table (`.claude`/root-level 원문과 대칭) — the
#: default forbidden-path prefix set `gate_forbidden_file` rejects any
#: changed file under. Callers MAY override with their own set (e.g. a
#: tenant-specific protected-path policy layered on top), but this default
#: is always the floor a caller opts INTO by omitting `forbidden_prefixes`,
#: never something a caller can accidentally weaken by forgetting to pass
#: it.
DEFAULT_FORBIDDEN_PATH_PREFIXES: tuple[str, ...] = (
    ".cursor/rules/",
    "docs/specs/",
    "packages/contracts/",
    "packages/schemas/",
    "events/",
    "workflows/",
    "deploy/",
    ".claude/settings",
    "docs/decisions/",
)


def _error(*, error_code: str, summary: str, retryable: bool, **detail: str) -> JobError:
    return JobError(
        error_code=error_code,
        summary=truncate(redact_stack_trace(summary)),
        retryable=retryable,
        redacted_detail={k: truncate(redact_stack_trace(v)) for k, v in detail.items()},
    )


# --- commit_coherence (mission item 1: base/target commit coherence) --------


def gate_commit_coherence(*, approved_base_commit: str, artifact_base_commit: str) -> GateResult:
    """The `PatchArtifact.base_commit` a quality-eval run is asked to verify
    MUST equal the approved `ChangePlan.repo_commit` it was authorized
    against — a target built on any other base is not covered by the
    approval that authorized it (ADR-0003 dual-verification intent extended
    to the build/verify step)."""
    if approved_base_commit == artifact_base_commit:
        return passed(GateId.COMMIT_COHERENCE)
    return failed(
        GateId.COMMIT_COHERENCE,
        (
            _error(
                error_code="saena.validation.base_commit_mismatch",
                summary="patch artifact base_commit does not match the approved "
                "ChangePlan repo_commit",
                retryable=False,
                expected_base_commit=approved_base_commit,
                actual_base_commit=artifact_base_commit,
            ),
        ),
    )


# --- build --------------------------------------------------------------------


def gate_build(outcome: BuildOutcome) -> GateResult:
    """Algorithm §11.1 "Build: 고객 repo의 공식 build command 성공"."""
    if outcome.succeeded:
        return passed(GateId.BUILD)
    return failed(
        GateId.BUILD,
        (
            _error(
                error_code="saena.internal.build_failed",
                summary=f"build command {outcome.command!r} exited {outcome.exit_code}",
                retryable=True,
                command=outcome.command,
                exit_code=str(outcome.exit_code),
                log_summary=outcome.log_summary,
            ),
        ),
    )


# --- tests / unit_tests / integration_tests ------------------------------------


def _test_gate(gate_id: GateId, outcome: TestOutcome) -> GateResult:
    if outcome.all_passed:
        return passed(gate_id)
    return failed(
        gate_id,
        (
            _error(
                error_code="saena.internal.tests_failed",
                summary=f"{outcome.suite} suite: {outcome.failed}/{outcome.total} tests failed",
                retryable=True,
                suite=outcome.suite,
                failed_count=str(outcome.failed),
                failing_tests=", ".join(outcome.failing_test_names[:5]),
            ),
        ),
    )


def gate_tests(outcome: TestOutcome) -> GateResult:
    """Algorithm §11.1 "Tests: affected test + regression test 성공" — the
    top-level `tests` gate row, evaluated over whichever single already-
    combined `TestOutcome` the caller supplies (`engine.py` combines
    `unit`+`integration` suites into one for this specific gate id; see
    `engine._combined_test_outcome`)."""
    return _test_gate(GateId.TESTS, outcome)


def gate_unit_tests(outcome: TestOutcome) -> GateResult:
    return _test_gate(GateId.UNIT_TESTS, outcome)


def gate_integration_tests(outcome: TestOutcome) -> GateResult:
    return _test_gate(GateId.INTEGRATION_TESTS, outcome)


# --- lint / typecheck -----------------------------------------------------------


def gate_lint(outcome: LintOutcome) -> GateResult:
    if outcome.violation_count == 0:
        return passed(GateId.LINT)
    return failed(
        GateId.LINT,
        (
            _error(
                error_code="saena.validation.lint_violations",
                summary=f"{outcome.tool}: {outcome.violation_count} lint violation(s)",
                retryable=True,
                tool=outcome.tool,
                sample_violations=", ".join(outcome.sample_violations[:5]),
            ),
        ),
    )


def gate_typecheck(outcome: TypecheckOutcome) -> GateResult:
    if outcome.error_count == 0:
        return passed(GateId.TYPECHECK)
    return failed(
        GateId.TYPECHECK,
        (
            _error(
                error_code="saena.validation.typecheck_errors",
                summary=f"{outcome.tool}: {outcome.error_count} type error(s)",
                retryable=True,
                tool=outcome.tool,
                sample_errors=", ".join(outcome.sample_errors[:5]),
            ),
        ),
    )


# --- schema_contract --------------------------------------------------------------


def gate_schema_contract(outcome: SchemaContractOutcome) -> GateResult:
    if outcome.valid:
        return passed(GateId.SCHEMA_CONTRACT)
    return failed(
        GateId.SCHEMA_CONTRACT,
        (
            _error(
                error_code="saena.validation.contract_shape_invalid",
                summary=f"{len(outcome.invalid_contract_ids)} contract(s) failed schema validation",
                retryable=False,
                invalid_contract_ids=", ".join(outcome.invalid_contract_ids),
            ),
        ),
    )


# --- security ------------------------------------------------------------------


def gate_security(outcome: SecurityScanOutcome) -> GateResult:
    """Algorithm §11.1 "Security: secret leak, injection propagation,
    supply-chain anomaly 0건" (zero-tolerance on all three counters)."""
    total = (
        outcome.secret_leak_count
        + outcome.injection_finding_count
        + outcome.supply_chain_anomaly_count
    )
    if total == 0:
        return passed(GateId.SECURITY)
    return failed(
        GateId.SECURITY,
        (
            _error(
                error_code="saena.upstream_engine.security_finding",
                summary=(
                    f"{outcome.secret_leak_count} secret leak(s), "
                    f"{outcome.injection_finding_count} injection finding(s), "
                    f"{outcome.supply_chain_anomaly_count} supply-chain anomaly(ies)"
                ),
                retryable=False,
                findings=", ".join(outcome.findings[:5]),
            ),
        ),
    )


# --- boundary --------------------------------------------------------------------


def gate_boundary(outcome: BoundaryOutcome) -> GateResult:
    """Every changed file must fall under one of the patch unit's approved
    scope globs. `out_of_scope_files` is already computed by the caller
    (glob matching itself is not this pure function's concern — it consumes
    the already-evaluated verdict, same "pluggable check over adapter
    output" shape as every other gate in this module)."""
    if not outcome.out_of_scope_files:
        return passed(GateId.BOUNDARY)
    return failed(
        GateId.BOUNDARY,
        (
            _error(
                error_code="saena.policy_denied.out_of_scope_files",
                summary=f"{len(outcome.out_of_scope_files)} changed file(s) outside approved scope",
                retryable=False,
                out_of_scope_files=", ".join(outcome.out_of_scope_files),
                approved_scope_globs=", ".join(outcome.approved_scope_globs),
            ),
        ),
    )


# --- changed_line_coverage (mission item 4, ADR-0017) --------------------------


def gate_changed_line_coverage(
    report: CoverageReport, *, threshold_pct: float = CHANGED_LINE_COVERAGE_THRESHOLD_PCT
) -> GateResult:
    pct = report.covered_pct
    if pct >= threshold_pct:
        return passed(GateId.CHANGED_LINE_COVERAGE)
    return failed(
        GateId.CHANGED_LINE_COVERAGE,
        (
            _error(
                error_code="saena.validation.changed_line_coverage_below_threshold",
                summary=f"changed-line coverage {pct:.2f}% is below the {threshold_pct:.2f}% "
                "blocking threshold (ADR-0017)",
                retryable=False,
                covered_pct=f"{pct:.2f}",
                threshold_pct=f"{threshold_pct:.2f}",
                changed_lines_total=str(report.changed_lines_total),
                changed_lines_covered=str(report.changed_lines_covered),
            ),
        ),
    )


# --- forbidden_file (mission item 5) --------------------------------------------


def _is_forbidden(path: str, forbidden_prefixes: Iterable[str]) -> bool:
    return any(path.startswith(prefix) for prefix in forbidden_prefixes)


def gate_forbidden_file(
    changed_files: tuple[str, ...],
    *,
    forbidden_prefixes: tuple[str, ...] = DEFAULT_FORBIDDEN_PATH_PREFIXES,
) -> GateResult:
    """A patch touching any protected path / forbidden file ⇒ FAIL
    (CLAUDE.md "Protected paths"). Zero tolerance — a single touched
    forbidden path fails the gate regardless of how many other files are
    in-scope."""
    touched = tuple(f for f in changed_files if _is_forbidden(f, forbidden_prefixes))
    if not touched:
        return passed(GateId.FORBIDDEN_FILE)
    return failed(
        GateId.FORBIDDEN_FILE,
        (
            _error(
                error_code="saena.policy_denied.forbidden_file_touched",
                summary=f"{len(touched)} changed file(s) touch a protected path",
                retryable=False,
                touched_files=", ".join(touched),
            ),
        ),
    )


# --- secret_scan (mission item 6) -----------------------------------------------


def gate_secret_scan(outcome: SecretScanOutcome) -> GateResult:
    """A planted secret anywhere in the patch ⇒ FAIL, redacted. This
    function NEVER reads `SecretScanFinding.matched_snippet` into a
    `JobError` field — `redaction.redact_secret_snippet` builds the safe
    description from `rule_id`/`file_path`/`line` only, structurally
    incapable of embedding the raw matched text."""
    if not outcome.findings:
        return passed(GateId.SECRET_SCAN)
    redacted_findings = tuple(
        redact_secret_snippet(f.rule_id, f.file_path, f.line) for f in outcome.findings
    )
    return failed(
        GateId.SECRET_SCAN,
        (
            _error(
                error_code="saena.internal.secret_detected",
                summary=f"{len(outcome.findings)} secret(s) detected in the patch",
                retryable=False,
                findings=", ".join(redacted_findings),
            ),
        ),
    )


# --- generated_code_drift (mission item 7) --------------------------------------


def gate_generated_code_drift(outcome: GeneratedCodeDriftOutcome) -> GateResult:
    """A codegen output path whose committed content differs from what
    regenerating it now would produce ⇒ FAIL (ADR-0011 codegen-is-SSOT)."""
    if not outcome.drifted_paths:
        return passed(GateId.GENERATED_CODE_DRIFT)
    return failed(
        GateId.GENERATED_CODE_DRIFT,
        (
            _error(
                error_code="saena.conflict.generated_code_drift",
                summary=f"{len(outcome.drifted_paths)} generated file(s) drifted from source",
                retryable=False,
                drifted_paths=", ".join(outcome.drifted_paths),
            ),
        ),
    )


# --- link_route ------------------------------------------------------------------


def gate_link_route(outcome: LinkRouteOutcome) -> GateResult:
    total = len(outcome.broken_links) + len(outcome.redirect_errors)
    if total == 0:
        return passed(GateId.LINK_ROUTE)
    return failed(
        GateId.LINK_ROUTE,
        (
            _error(
                error_code="saena.validation.link_route_errors",
                summary=f"{len(outcome.broken_links)} broken link(s), "
                f"{len(outcome.redirect_errors)} redirect error(s)",
                retryable=False,
                broken_links=", ".join(outcome.broken_links[:5]),
                redirect_errors=", ".join(outcome.redirect_errors[:5]),
            ),
        ),
    )


# --- crawlability ------------------------------------------------------------------


def gate_crawlability(outcome: CrawlabilityOutcome) -> GateResult:
    if not outcome.blocked_paths and outcome.rendering_ok:
        return passed(GateId.CRAWLABILITY)
    return failed(
        GateId.CRAWLABILITY,
        (
            _error(
                error_code="saena.validation.crawlability_regression",
                summary=f"{len(outcome.blocked_paths)} path(s) blocked for allowed crawlers"
                + ("" if outcome.rendering_ok else "; public rendering condition violated"),
                retryable=False,
                blocked_paths=", ".join(outcome.blocked_paths[:5]),
                rendering_ok=str(outcome.rendering_ok),
            ),
        ),
    )


# --- structured_data ------------------------------------------------------------------


def gate_structured_data(outcome: StructuredDataOutcome) -> GateResult:
    total = len(outcome.syntax_errors) + len(outcome.fabricated_markup_paths)
    if total == 0 and outcome.visible_content_parity_ok:
        return passed(GateId.STRUCTURED_DATA)
    return failed(
        GateId.STRUCTURED_DATA,
        (
            _error(
                error_code="saena.validation.structured_data_invalid",
                summary=f"{len(outcome.syntax_errors)} syntax error(s), "
                f"{len(outcome.fabricated_markup_paths)} fabricated markup path(s)"
                + (
                    "" if outcome.visible_content_parity_ok else "; visible-content parity violated"
                ),
                retryable=False,
                syntax_errors=", ".join(outcome.syntax_errors[:5]),
                fabricated_markup_paths=", ".join(outcome.fabricated_markup_paths[:5]),
            ),
        ),
    )


# --- content_fidelity ------------------------------------------------------------------


def gate_content_fidelity(outcome: ContentFidelityOutcome) -> GateResult:
    """Algorithm §11.1 "Content fidelity: every material claim → evidence
    ID, unsupported claim 0건" — ANY claim with `evidence_id=None` fails the
    gate (zero tolerance, no threshold)."""
    unsupported = tuple(c for c in outcome.claims if c.evidence_id is None)
    if not unsupported:
        return passed(GateId.CONTENT_FIDELITY)
    return failed(
        GateId.CONTENT_FIDELITY,
        tuple(
            _error(
                error_code="saena.validation.unsupported_claim",
                summary=f"claim {c.claim_id!r} has no evidence_id "
                "(content-fidelity zero tolerance)",
                retryable=False,
                claim_id=c.claim_id,
            )
            for c in unsupported
        ),
    )


# --- accessibility ------------------------------------------------------------------


def gate_accessibility(outcome: AccessibilityOutcome) -> GateResult:
    if not outcome.critical_violations:
        return passed(GateId.ACCESSIBILITY)
    return failed(
        GateId.ACCESSIBILITY,
        (
            _error(
                error_code="saena.validation.accessibility_regression",
                summary=f"{len(outcome.critical_violations)} critical a11y violation(s)",
                retryable=False,
                critical_violations=", ".join(outcome.critical_violations[:5]),
            ),
        ),
    )


# --- performance ------------------------------------------------------------------


def gate_performance(outcome: PerformanceOutcome) -> GateResult:
    if outcome.regression_pct <= outcome.regression_threshold_pct:
        return passed(GateId.PERFORMANCE)
    return failed(
        GateId.PERFORMANCE,
        (
            _error(
                error_code="saena.validation.performance_regression",
                summary=f"{outcome.metric_name} regressed {outcome.regression_pct:.2f}% "
                f"(threshold {outcome.regression_threshold_pct:.2f}%)",
                retryable=False,
                metric_name=outcome.metric_name,
                baseline_value=f"{outcome.baseline_value:.4f}",
                observed_value=f"{outcome.observed_value:.4f}",
                regression_pct=f"{outcome.regression_pct:.2f}",
            ),
        ),
    )


# --- diff_rationality ------------------------------------------------------------------


def gate_diff_rationality(
    diff: PatchDiff, *, approved_patch_unit_ids: frozenset[str]
) -> GateResult:
    """Algorithm §11.1 "Diff rationality: every hunk → Action Contract patch
    unit 연결" — a hunk with `patch_unit_id=None` OR a `patch_unit_id` not in
    the approved ChangePlan's own patch unit id set fails the gate."""
    unlinked = tuple(
        h
        for h in diff.hunks
        if h.patch_unit_id is None or h.patch_unit_id not in approved_patch_unit_ids
    )
    if not unlinked:
        return passed(GateId.DIFF_RATIONALITY)
    return failed(
        GateId.DIFF_RATIONALITY,
        tuple(
            _error(
                error_code="saena.validation.unlinked_diff_hunk",
                summary=f"hunk {h.hunk_id!r} in {h.file_path!r} is not linked to an approved "
                "Action Contract patch unit",
                retryable=False,
                hunk_id=h.hunk_id,
                file_path=h.file_path,
                patch_unit_id=h.patch_unit_id or "",
            )
            for h in unlinked
        ),
    )


__all__ = [
    "CHANGED_LINE_COVERAGE_THRESHOLD_PCT",
    "DEFAULT_FORBIDDEN_PATH_PREFIXES",
    "gate_accessibility",
    "gate_boundary",
    "gate_build",
    "gate_changed_line_coverage",
    "gate_commit_coherence",
    "gate_content_fidelity",
    "gate_crawlability",
    "gate_diff_rationality",
    "gate_forbidden_file",
    "gate_generated_code_drift",
    "gate_integration_tests",
    "gate_lint",
    "gate_link_route",
    "gate_performance",
    "gate_schema_contract",
    "gate_secret_scan",
    "gate_security",
    "gate_structured_data",
    "gate_tests",
    "gate_typecheck",
    "gate_unit_tests",
]
