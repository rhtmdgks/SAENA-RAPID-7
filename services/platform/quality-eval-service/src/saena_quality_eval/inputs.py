"""Gate INPUT value objects — the deterministic, already-collected data each
pure gate function in `gates.py` evaluates.

Every type here is a frozen, `slots=True` dataclass built from tuples (never
lists) so instances are hashable/immutable/order-stable — the same
discipline `saena_domain.execution`/`saena_domain.policy` value objects use,
and a prerequisite for this package's own determinism guarantee (mission
item 8): a `GateInputBundle` built from the same field values twice compares
equal and serializes identically, with no hidden mutable aliasing between
the two instances.

These are the "adapter output" shapes `protocols.py`'s `BuildRunner`/
`TestRunner`/`SecurityScanner`/`SecretScanner`/`CoverageReporter`/
`GeneratedCodeDriftScanner` Protocols return. The remaining
Algorithm-§11.1-specific gates (link/route, crawlability, structured data,
content fidelity, accessibility, performance) and this package's own
lint/typecheck/schema-contract/boundary gates take their outcome objects
directly as gate-function arguments (mission item 3: "pluggable
deterministic checks over fake adapter outputs") — a full-blown named
`typing.Protocol` per one of THOSE checks would be boilerplate without a
second production adapter behind it in this patch unit; the pure-function
gate over an explicit, typed outcome dataclass is the adapter boundary that
actually matters for pluggable-checks-over-fake-outputs, Protocol class or
not.

**Redaction discipline**: no field on any of these types ever carries a raw
stack trace, full log dump, or (for `SecretScanFinding.matched_snippet`)
anything that is not consumed exclusively by `gates.secret_scan` and
immediately redacted before it reaches a `GateResult`/`JobError` — see that
gate's docstring.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class BuildOutcome:
    """`BuildRunner.run_build()` result — Algorithm §11.1 "Build: 고객 repo의
    공식 build command 성공"."""

    succeeded: bool
    command: str
    exit_code: int
    log_summary: str = ""


@dataclass(frozen=True, slots=True)
class TestOutcome:
    """`TestRunner.run_tests(suite)` result for one named suite (`"unit"`,
    `"integration"`, `"regression"`, ...). Algorithm §11.1 "Tests: affected
    test + regression test 성공"."""

    #: Not a pytest test class despite the name — silences pytest's
    #: `PytestCollectionWarning` ("cannot collect test class 'TestOutcome'
    #: because it has a __init__ constructor"), which would otherwise fire
    #: in every test module that imports this dataclass.
    __test__ = False

    suite: str
    total: int
    passed: int
    failed: int
    failing_test_names: tuple[str, ...] = ()

    @property
    def all_passed(self) -> bool:
        return self.failed == 0 and self.total == self.passed


@dataclass(frozen=True, slots=True)
class LintOutcome:
    tool: str
    violation_count: int
    sample_violations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TypecheckOutcome:
    tool: str
    error_count: int
    sample_errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SchemaContractOutcome:
    """schema/contract validation gate input — e.g. a manifest/patch-unit
    payload checked against the relevant `packages/contracts/json-schema`
    file(s) upstream of this engine; this dataclass only carries the
    already-computed verdict."""

    valid: bool
    invalid_contract_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SecurityScanOutcome:
    """Algorithm §11.1 "Security: secret leak, injection propagation,
    supply-chain anomaly 0건". Deliberately distinct from
    `SecretScanOutcome`/`gates.secret_scan` — that gate is this package's own
    additional, independently-reportable secret-scan check (mission item 6)
    over the patch content itself; this one is the broader Algorithm-§11.1
    security sweep (may itself already fold in a secret-scan pass upstream,
    but this engine keeps the two `VerificationResult` rows separate for
    finer-grained release-gate reporting)."""

    secret_leak_count: int = 0
    injection_finding_count: int = 0
    supply_chain_anomaly_count: int = 0
    findings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BoundaryOutcome:
    """Patch-unit file-scope boundary check: every changed file must fall
    under one of the approved `ChangePlan.approved_scope` globs (CLAUDE.md
    원칙 6 "독점 수정 경로" applied to a single patch unit's own approved
    scope, not the multi-agent exclusive-path convention itself)."""

    changed_files: tuple[str, ...]
    approved_scope_globs: tuple[str, ...]
    out_of_scope_files: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """diff-cover-shaped changed-line coverage input (ADR-0017 "Changed-lines
    (diff-cover) >= 90%, blocking")."""

    changed_lines_total: int
    changed_lines_covered: int

    def __post_init__(self) -> None:
        if self.changed_lines_total < 0 or self.changed_lines_covered < 0:
            raise ValueError("CoverageReport counts must be non-negative")
        if self.changed_lines_covered > self.changed_lines_total:
            raise ValueError("changed_lines_covered cannot exceed changed_lines_total")

    @property
    def covered_pct(self) -> float:
        if self.changed_lines_total == 0:
            return 100.0
        return 100.0 * self.changed_lines_covered / self.changed_lines_total


@dataclass(frozen=True, slots=True)
class DiffHunk:
    """One diff hunk, and the Action Contract patch unit it claims to belong
    to (Algorithm §11.1 "Diff rationality: every hunk → Action Contract patch
    unit 연결"). `patch_unit_id=None` means the hunk carries no linkage at
    all — always a `gates.diff_rationality` failure, same as a non-empty but
    unrecognized id."""

    file_path: str
    hunk_id: str
    patch_unit_id: str | None


@dataclass(frozen=True, slots=True)
class PatchDiff:
    changed_files: tuple[str, ...]
    hunks: tuple[DiffHunk, ...] = ()


@dataclass(frozen=True, slots=True)
class SecretScanFinding:
    """One raw secret-scanner hit. `matched_snippet` is the RAW matched
    text — this field exists so `gates.secret_scan` has something to
    redact; it must never itself be copied into a `GateResult`/`JobError`/
    `VerificationResult` unredacted (see `redaction.redact_secret_snippet`
    and `test_redaction.py::test_secret_scan_never_leaks_raw_secret`)."""

    file_path: str
    line: int
    rule_id: str
    matched_snippet: str = field(repr=False, default="")


@dataclass(frozen=True, slots=True)
class SecretScanOutcome:
    findings: tuple[SecretScanFinding, ...] = ()


@dataclass(frozen=True, slots=True)
class GeneratedCodeDriftOutcome:
    """A non-empty `drifted_paths` means at least one generated-code path's
    committed content differs from what regenerating it now would produce
    (ADR-0011 codegen-is-SSOT discipline; this gate is what makes drift a
    hard release-gate failure rather than a silent divergence)."""

    drifted_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LinkRouteOutcome:
    broken_links: tuple[str, ...] = ()
    redirect_errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CrawlabilityOutcome:
    blocked_paths: tuple[str, ...] = ()
    rendering_ok: bool = True


@dataclass(frozen=True, slots=True)
class StructuredDataOutcome:
    syntax_errors: tuple[str, ...] = ()
    fabricated_markup_paths: tuple[str, ...] = ()
    visible_content_parity_ok: bool = True


@dataclass(frozen=True, slots=True)
class Claim:
    """One material claim the patch makes. `evidence_id=None` marks it
    unsupported — Algorithm §11.1 "Content fidelity: every material claim →
    evidence ID, unsupported claim 0건" (zero-tolerance: any unsupported
    claim fails the gate, no threshold)."""

    claim_id: str
    evidence_id: str | None


@dataclass(frozen=True, slots=True)
class ContentFidelityOutcome:
    claims: tuple[Claim, ...] = ()


@dataclass(frozen=True, slots=True)
class AccessibilityOutcome:
    critical_violations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PerformanceOutcome:
    """Algorithm §11.1 "Performance: agreed Core Web Vitals proxy / bundle
    regression threshold 이내". `regression_threshold_pct` is the maximum
    tolerated relative regression (observed worse than baseline by more than
    this percentage fails the gate); a NEGATIVE observed-vs-baseline delta
    (an improvement) always passes regardless of threshold."""

    metric_name: str
    baseline_value: float
    observed_value: float
    regression_threshold_pct: float

    def __post_init__(self) -> None:
        if self.baseline_value <= 0:
            raise ValueError("baseline_value must be positive")
        if self.regression_threshold_pct < 0:
            raise ValueError("regression_threshold_pct must be non-negative")

    @property
    def regression_pct(self) -> float:
        """Positive = worse than baseline, negative/zero = same or better."""
        return 100.0 * (self.observed_value - self.baseline_value) / self.baseline_value


__all__ = [
    "AccessibilityOutcome",
    "BoundaryOutcome",
    "BuildOutcome",
    "Claim",
    "ContentFidelityOutcome",
    "CoverageReport",
    "CrawlabilityOutcome",
    "DiffHunk",
    "GeneratedCodeDriftOutcome",
    "LintOutcome",
    "LinkRouteOutcome",
    "PatchDiff",
    "PerformanceOutcome",
    "SchemaContractOutcome",
    "SecretScanFinding",
    "SecretScanOutcome",
    "SecurityScanOutcome",
    "StructuredDataOutcome",
    "TestOutcome",
    "TypecheckOutcome",
]
